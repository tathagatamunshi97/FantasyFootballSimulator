#!/usr/bin/env python3
"""Compare raw vs dampened attack rates + fit finishing for sheet attackers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from formation_fit import fit_score, normalize_formation
from models import PlayerStats
from sample_confidence import credibility_weight, role_bucket
from sofascore_client import StatsStore
from stats_resolver import prepare_match_player_stats
from team_ratings import _player_attack_contrib, _scale
from web.team_lineups import _load_all

ATK = {"ST", "ST1", "ST2", "CF", "CF1", "CF2", "RW", "LW", "AM", "CAM", "RM", "LM"}


def is_atk(slot: str) -> bool:
    s = (slot or "").upper()
    return s in ATK or any(s.startswith(p) for p in ("ST", "CF", "RW", "LW", "AM", "CAM"))


def main() -> None:
    store = StatsStore()
    cache = json.loads(Path("data/player_stats_cache.json").read_text(encoding="utf-8"))
    players = cache.get("players") or cache
    lineups = _load_all()

    print("player|slot|team|raw_xg|damped_xg|raw_sh|damped_sh|raw_sot|pass|drib%|bucket|c|atk_contrib|fit|flags")
    rows = []
    for rec in lineups.values():
        team = {
            "name": rec.get("team_name") or rec.get("name"),
            "formation": rec.get("formation"),
            "lineup": rec.get("lineup") or [],
            "bench": rec.get("bench") or [],
            "prime_player": rec.get("prime_player") or "",
            "peak_season": rec.get("peak_season") or {},
        }
        try:
            ps, overrides, name_map = prepare_match_player_stats(team, team, store, cache_only=True)
        except Exception as exc:
            print(f"FAIL {team['name']}: {exc}", file=sys.stderr)
            continue
        form = normalize_formation(team["formation"])
        for row in team["lineup"]:
            if not is_atk(row.get("slot", "")):
                continue
            raw_name = row.get("player") or ""
            canon = name_map.get(raw_name, raw_name)
            st = ps.get(canon)
            if not st:
                try:
                    canon = store.resolve(raw_name)
                    st = ps.get(canon)
                except Exception:
                    st = None
            if not st:
                print(f"{raw_name}|{row.get('slot')}|{team['name']}|MISSING")
                continue
            raw = players.get(canon) or {}
            # if prime override, raw for comparison is the PlayerStats itself
            is_prime = False
            for side in (overrides or {}).values():
                if not isinstance(side, dict):
                    continue
                for k in ("prime", "peak"):
                    meta = side.get(k) or {}
                    if meta.get("resolved_name") == canon or meta.get("requested") == raw_name:
                        is_prime = True
            raw_xg = float(raw.get("xg90") or 0) if raw and not is_prime else st.xg90
            raw_sh = float(raw.get("shots90") or 0) if raw and not is_prime else st.shots90
            raw_sot = float(raw.get("shots_on_target90") or 0) if raw and not is_prime else st.shots_on_target90
            if is_prime and raw:
                # show what dampening would have done to cache vs actual undamped
                pass
            c = credibility_weight(st.minutes)
            bucket = role_bucket(st.primary_position, st.fpl_position)
            fit = fit_score(st, form, row["slot"])
            atk = _player_attack_contrib(st, fit)
            flags = []
            if st.pass_pct <= 0:
                flags.append("ZERO_PASS")
            if st.dribble_pct <= 0 and st.dribbles90 > 0.2:
                flags.append("ZERO_DRIB%")
            if st.dribble_pct <= 0 and st.dribbles90 <= 0.2 and st.fpl_position == "FWD":
                flags.append("ZERO_DRIB_ALL")
            if not is_prime and raw_xg > 0 and st.xg90 < raw_xg * 0.85:
                flags.append(f"XG_SHRINK:{raw_xg:.2f}->{st.xg90:.2f}")
            if bucket == "CM" and row["slot"].upper() in {"AM", "CAM", "RW", "LW", "ST"}:
                flags.append("CM_BUCKET")
            if st.xg90 < 0.12 and row["slot"].upper().startswith(("ST", "CF")):
                flags.append("ST_LOW_XG")
            if atk < 0.35:
                flags.append(f"LOW_ATK:{atk:.2f}")
            # finishing scale saturates at 0.85 — show headroom
            xg_scale = _scale(st.xg90, 0.85)
            if xg_scale < 0.45 and row["slot"].upper() in ATK:
                flags.append(f"WEAK_XG_SCALE:{xg_scale:.2f}")
            line = (
                f"{canon}|{row.get('slot')}|{team['name']}|{raw_xg:.3f}|{st.xg90:.3f}|"
                f"{raw_sh:.2f}|{st.shots90:.2f}|{st.shots_on_target90:.2f}|{st.pass_pct:.1f}|"
                f"{st.dribble_pct:.1f}|{bucket}|{c:.2f}|{atk:.3f}|{fit:.3f}|{','.join(flags) or '-'}|prime={is_prime}"
            )
            print(line)
            rows.append(
                {
                    "player": canon,
                    "slot": row.get("slot"),
                    "team": team["name"],
                    "raw_xg": raw_xg,
                    "xg90": st.xg90,
                    "shots90": st.shots90,
                    "sot": st.shots_on_target90,
                    "pass_pct": st.pass_pct,
                    "dribble_pct": st.dribble_pct,
                    "bucket": bucket,
                    "c": c,
                    "atk": atk,
                    "fit": fit,
                    "flags": flags,
                    "prime": is_prime,
                }
            )

    Path("data/_attacker_finishing_audit.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    low = [r for r in rows if r["atk"] < 0.4 or any("ZERO" in f or "LOW" in f or "WEAK" in f or "SHRINK" in f for f in r["flags"])]
    print(f"\n--- summary attackers={len(rows)} concerning={len(low)} ---", file=sys.stderr)
    for r in sorted(low, key=lambda x: x["atk"]):
        print(
            f"  {r['player']}: atk={r['atk']:.2f} xg={r['xg90']:.2f} fit={r['fit']:.2f} {r['flags']}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
