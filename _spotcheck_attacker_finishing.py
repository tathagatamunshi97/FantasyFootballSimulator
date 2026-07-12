#!/usr/bin/env python3
"""Spot-check attacker finishing signals after systemic fix."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from models import PlayerStats, _normalize_stat_gaps
from sample_confidence import role_bucket, role_bucket_for_stats, credibility_weight
from sofascore_client import StatsStore
from stats_resolver import prepare_match_player_stats
from formation_fit import player_slot_fit, normalize_formation
from team_ratings import _player_attack_contrib, compute_unit_ratings
from models import FantasyTeam
from web.team_lineups import _load_all

SAMPLE = [
    "Harry Kane",
    "Luis Díaz",
    "Lamine Yamal",
    "Erling Haaland",
    "Mohamed Salah",
    "Kevin De Bruyne",
    "Cole Palmer",
    "Cristiano Ronaldo",
    "Edinson Cavani",
    "Radamel Falcao",
    "Bruno Fernandes",
    "Raphinha",
]


def main() -> None:
    store = StatsStore()
    cache = json.loads(Path("data/player_stats_cache.json").read_text(encoding="utf-8"))
    players = cache.get("players") or cache

    print("=== normalize gaps (sparse primes) ===")
    for name in ("Kevin De Bruyne", "Edinson Cavani", "Radamel Falcao", "Cristiano Ronaldo"):
        # find in manual or cache
        raw = dict(players.get(name) or {})
        if not raw:
            print(name, "not in cache")
            continue
        before = (raw.get("pass_pct"), raw.get("dribble_pct"), raw.get("dribbles90"))
        d = dict(raw)
        _normalize_stat_gaps(d)
        print(
            f"{name}: pass {before[0]}->{d.get('pass_pct')} drib% {before[1]}->{d.get('dribble_pct')} "
            f"drib90={d.get('dribbles90')}"
        )

    print("\n=== role bucket promotion ===")
    for name in ("Jude Bellingham", "Bruno Fernandes", "Florian Wirtz", "Luis Díaz", "Lamine Yamal"):
        raw = dict(players.get(name) or {})
        if not raw:
            # try resolve
            try:
                canon = store.resolve(name)
                raw = dict(players.get(canon) or {})
                name = canon
            except Exception:
                print(name, "missing")
                continue
        declared = role_bucket(raw.get("primary_position", ""), raw.get("fpl_position", ""))
        inferred = role_bucket_for_stats(raw)
        print(f"{name}: declared={declared} inferred={inferred} xg={raw.get('xg90')} shots={raw.get('shots90')}")

    print("\n=== sheet attackers (resolved) ===")
    print(f"{'player':22} {'slot':4} {'xg':5} {'sh':4} {'sot':4} {'pass':4} {'dr%':4} {'fit':4} {'atk':4} {'buk':4} notes")
    rows = []
    ATK = {"ST", "ST1", "ST2", "CF", "CF1", "CF2", "RW", "LW", "AM", "CAM", "RM", "LM"}

    def is_atk(s):
        s = (s or "").upper()
        return s in ATK or any(s.startswith(p) for p in ("ST", "CF", "RW", "LW", "AM", "CAM"))

    for rec in _load_all().values():
        team = {
            "name": rec.get("team_name"),
            "formation": rec.get("formation"),
            "lineup": rec.get("lineup") or [],
            "bench": rec.get("bench") or [],
            "prime_player": rec.get("prime_player") or "",
            "peak_season": rec.get("peak_season") or {},
        }
        try:
            ps, _, nmap = prepare_match_player_stats(team, team, store, cache_only=True)
        except Exception as exc:
            print("FAIL", team["name"], exc)
            continue
        form = normalize_formation(team["formation"])
        for row in team["lineup"]:
            if not is_atk(row.get("slot", "")):
                continue
            raw = row.get("player") or ""
            canon = nmap.get(raw, raw)
            st = ps.get(canon)
            if not st:
                continue
            fit = player_slot_fit(st, form, row["slot"], row.get("role_filter") or None)
            atk = _player_attack_contrib(st, fit)
            # reconstruct bucket from current rates
            payload = {
                "primary_position": st.primary_position,
                "fpl_position": st.fpl_position,
                "xg90": st.xg90,
                "shots90": st.shots90,
                "shots_on_target90": st.shots_on_target90,
                "xa90": st.xa90,
                "key_passes90": st.key_passes90,
                "dribbles90": st.dribbles90,
                "goals90": st.goals90,
            }
            buk = role_bucket_for_stats(payload)
            note = []
            if st.pass_pct <= 0:
                note.append("ZERO_PASS")
            if st.dribble_pct <= 0:
                note.append("ZERO_DRIB")
            if canon in SAMPLE or any(s.lower() in canon.lower() for s in SAMPLE):
                note.append("SAMPLE")
            rows.append(
                {
                    "player": canon,
                    "slot": row["slot"],
                    "team": team["name"],
                    "xg": st.xg90,
                    "sh": st.shots90,
                    "sot": st.shots_on_target90,
                    "pass": st.pass_pct,
                    "drib": st.dribble_pct,
                    "fit": fit,
                    "atk": atk,
                    "buk": buk,
                    "note": note,
                }
            )

    # print sample first
    for r in rows:
        if "SAMPLE" in r["note"] or r["player"] in SAMPLE:
            print(
                f"{r['player'][:22]:22} {r['slot'][:4]:4} {r['xg']:5.2f} {r['sh']:4.1f} {r['sot']:4.1f} "
                f"{r['pass']:4.0f} {r['drib']:4.0f} {r['fit']:4.2f} {r['atk']:4.2f} {r['buk'][:4]:4} "
                f"{','.join(r['note']) or '-'}"
            )

    zero = [r for r in rows if r["pass"] <= 0 or r["drib"] <= 0]
    low_atk = [r for r in rows if r["atk"] < 0.4]
    print(f"\nattackers={len(rows)} zero_pct={len(zero)} low_atk<0.40={len(low_atk)}")
    if zero:
        print("still zero:", [r["player"] for r in zero])

    print("\n=== conversion factor (organicWillScore, boxed, form=1) ===")
    # approximate JS formula
    def conv(xg, shots, goals=0, sot=None, role="ST"):
        sot = sot if sot is not None else shots * 0.4
        fq = min(1.35, xg * 0.82 + shots * 0.055 + sot * 0.07 + goals * 0.12)
        xgW, shW = 0.42, 0.035
        elite = max(0, min(0.2, (fq - 0.42) * 0.24))
        p = 0.05 + xg * xgW + shots * shW + 0.1 + 0.045 + elite
        hiElite = max(0, min(0.24, (fq - 0.38) * 0.42))
        hi = min(0.72, max(0.32, 0.4 + hiElite))
        old_p = 0.05 + xg * 0.3 + shots * 0.02 + 0.1
        old_hi = 0.4
        return p, min(hi, p), old_p, min(old_hi, old_p), fq

    for label, xg, sh, g, sot in [
        ("Kane(damped)", 0.73, 3.81, 0.92, 1.90),
        ("Kane(prime)", 0.89, 4.40, 1.17, 2.28),
        ("Haaland", 0.64, 3.35, 0.66, 1.65),
        ("Díaz", 0.42, 2.73, 0.44, 1.13),
        ("AvgST", 0.45, 3.2, 0.34, 1.28),
        ("WeakST", 0.28, 2.0, 0.22, 0.8),
    ]:
        p, cl, op, ocl, fq = conv(xg, sh, g, sot)
        print(f"  {label}: fq={fq:.2f} NEW p={p:.2f}->{cl:.2f}  OLD p={op:.2f}->{ocl:.2f}  Δceil={cl-ocl:+.2f}")

    Path("data/_attacker_finishing_audit.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
