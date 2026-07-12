#!/usr/bin/env python3
"""Audit board-ready finishing signals for ST/W/AM across Fantasy Cup lineups."""
from __future__ import annotations

import json
from pathlib import Path

from models import PlayerStats, _normalize_stat_gaps
from sample_confidence import (
    CREDIBILITY_M0,
    apply_credibility_dampening,
    credibility_weight,
    is_undamped_profile,
    role_bucket,
)
from sofascore_client import StatsStore
from stats_resolver import prepare_match_player_stats
from web.team_lineups import _load_all

ROOT = Path(__file__).resolve().parent
ATK_SLOTS = {
    "ST", "ST1", "ST2", "CF", "CF1", "CF2",
    "RW", "LW", "AM", "CAM", "RM", "LM",
}


def slot_is_attack(slot: str) -> bool:
    s = (slot or "").upper()
    if s in ATK_SLOTS:
        return True
    return any(s.startswith(p) for p in ("ST", "CF", "RW", "LW", "AM", "CAM"))


def board_like(st: PlayerStats) -> dict:
    d = st.to_dict() if hasattr(st, "to_dict") else st.__dict__
    return {
        "xg90": float(getattr(st, "xg90", 0) or 0),
        "npxg90": float(getattr(st, "npxg90", 0) or 0),
        "shots90": float(getattr(st, "shots90", 0) or 0),
        "sot": float(getattr(st, "shots_on_target90", 0) or 0),
        "goals90": float(getattr(st, "goals90", 0) or 0),
        "xa90": float(getattr(st, "xa90", 0) or 0),
        "pass_pct": float(getattr(st, "pass_pct", 0) or 0),
        "dribble_pct": float(getattr(st, "dribble_pct", 0) or 0),
        "dribbles90": float(getattr(st, "dribbles90", 0) or 0),
        "minutes": float(getattr(st, "minutes", 0) or 0),
        "primary": getattr(st, "primary_position", ""),
        "fpl": getattr(st, "fpl_position", ""),
        "cred": getattr(st, "credibility_weight", None),
        "cred_role": getattr(st, "credibility_role", None),
        "skip": bool(getattr(st, "skip_credibility_dampening", False) or is_undamped_profile(d if isinstance(d, dict) else {})),
    }


def flags(row: dict) -> list[str]:
    out = []
    if row["xg90"] <= 0.05 and row["slot_role"] in {"ST", "W", "AM"}:
        out.append("LOW_XG")
    if row["shots90"] <= 0.5:
        out.append("LOW_SHOTS")
    if row["sot"] <= 0 and row["shots90"] > 1:
        out.append("ZERO_SOT")
    if row["pass_pct"] <= 0:
        out.append("ZERO_PASS")
    if row["dribble_pct"] <= 0 and row["dribbles90"] > 0.3:
        out.append("ZERO_DRIBBLE_PCT")
    if row["primary_bucket"] == "CM" and row["slot_role"] in {"ST", "W", "AM"}:
        out.append("WRONG_BUCKET")
    if row.get("cred") is not None and row["cred"] < 0.55 and not row.get("undamped"):
        out.append("HEAVY_DAMP")
    if row["xg90"] < 0.15 and row["slot_role"] == "ST":
        out.append("ST_WEAK_XG")
    return out


def slot_role(slot: str) -> str:
    s = (slot or "").upper()
    if s.startswith("ST") or s.startswith("CF"):
        return "ST"
    if s in {"RW", "LW", "RM", "LM"} or s.startswith("RW") or s.startswith("LW"):
        return "W"
    if s in {"AM", "CAM"} or s.startswith("AM") or s.startswith("CAM"):
        return "AM"
    return "OTHER"


def main() -> None:
    store = StatsStore()
    lineups = _load_all()
    teams = list(lineups.values())
    print(f"teams={len(teams)}")

    # Resolve each team against a dummy opponent (self) so primes/peaks apply
    rows = []
    for rec in teams:
        team = {
            "name": rec.get("team_name") or rec.get("name"),
            "formation": rec.get("formation"),
            "lineup": rec.get("lineup") or [],
            "bench": rec.get("bench") or [],
            "prime_player": rec.get("prime_player") or "",
            "peak_season": rec.get("peak_season") or {},
        }
        try:
            player_stats, overrides, name_map = prepare_match_player_stats(
                team, team, store, cache_only=True
            )
        except Exception as exc:
            print(f"FAIL {team['name']}: {exc}")
            continue

        for row in team["lineup"]:
            if not slot_is_attack(row.get("slot", "")):
                continue
            raw = row.get("player") or ""
            canon = name_map.get(raw, raw)
            st = player_stats.get(canon)
            if not st:
                # try resolve
                try:
                    canon2 = store.resolve(raw)
                    st = player_stats.get(canon2)
                    canon = canon2
                except Exception:
                    st = None
            if not st:
                rows.append(
                    {
                        "team": team["name"],
                        "player": raw,
                        "slot": row.get("slot"),
                        "slot_role": slot_role(row.get("slot", "")),
                        "missing": True,
                        "flags": ["MISSING_STATS"],
                    }
                )
                continue
            b = board_like(st)
            # also compute raw undamped from cache for comparison
            try:
                raw_entry = store.get_raw(canon) if hasattr(store, "get_raw") else None
            except Exception:
                raw_entry = None
            if raw_entry is None:
                try:
                    raw_entry = dict(store._players.get(canon).__dict__) if canon in getattr(store, "_players", {}) else None
                except Exception:
                    raw_entry = None

            undamped = False
            # check override
            for side in overrides.values() if isinstance(overrides, dict) else []:
                if not isinstance(side, dict):
                    continue
                for kind in ("prime", "peak", "season_pick"):
                    meta = side.get(kind) or {}
                    if meta.get("resolved_name") == canon or meta.get("requested") == raw:
                        undamped = True

            # PlayerStats may already be damped
            payload = {
                "minutes": b["minutes"],
                "primary_position": b["primary"],
                "fpl_position": b["fpl"],
                "stat_profile": getattr(st, "stat_profile", ""),
                "manual_profile_type": getattr(st, "manual_profile_type", ""),
                "skip_credibility_dampening": getattr(st, "skip_credibility_dampening", False),
                "credibility_damped": getattr(st, "credibility_damped", False),
            }
            undamped = undamped or is_undamped_profile(payload) or bool(payload.get("skip_credibility_dampening"))

            r = {
                "team": team["name"],
                "player": canon,
                "slot": row.get("slot"),
                "slot_role": slot_role(row.get("slot", "")),
                "primary_bucket": role_bucket(b["primary"], b["fpl"]),
                "undamped": undamped,
                "missing": False,
                **b,
            }
            r["flags"] = flags(r)
            rows.append(r)

    # summary
    flagged = [r for r in rows if r.get("flags")]
    print(f"attackers={len(rows)} flagged={len(flagged)}")
    print("\n=== ALL ATTACKERS ===")
    hdr = f"{'Team':16} {'Player':22} {'Slot':5} {'xg':6} {'sh':5} {'sot':5} {'g90':5} {'xa':5} {'pass':5} {'drib%':5} {'min':5} {'c':5} {'bucket':5} flags"
    print(hdr)
    for r in sorted(rows, key=lambda x: (x.get("slot_role",""), -(x.get("xg90") or 0))):
        if r.get("missing"):
            print(f"{r['team'][:16]:16} {r['player'][:22]:22} {r['slot'][:5]:5} MISSING {r['flags']}")
            continue
        print(
            f"{r['team'][:16]:16} {r['player'][:22]:22} {str(r['slot'])[:5]:5} "
            f"{r['xg90']:6.3f} {r['shots90']:5.2f} {r['sot']:5.2f} {r['goals90']:5.2f} {r['xa90']:5.2f} "
            f"{r['pass_pct']:5.1f} {r['dribble_pct']:5.1f} {r['minutes']:5.0f} "
            f"{(r['cred'] if r['cred'] is not None else (-1 if r['undamped'] else 0)):5.2f} "
            f"{r['primary_bucket']:5} {','.join(r['flags']) or '-'}"
        )

    print("\n=== FLAG COUNTS ===")
    from collections import Counter
    c = Counter()
    for r in rows:
        for f in r.get("flags") or []:
            c[f] += 1
    for k, v in c.most_common():
        print(f"  {k}: {v}")

    out = ROOT / "data" / "_attacker_finishing_audit.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
