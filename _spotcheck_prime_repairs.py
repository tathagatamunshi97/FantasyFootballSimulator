"""Spot-check repaired primes + peak-season alignment."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from google_sheets_teams import ROUND3_SEASON_PICKS
from manual_profiles import (
    lookup_manual_season_pick,
    reload_manual_profiles,
)
from models import PlayerStats
from seasonal_stats import build_prime_stats_dict
from sofascore_client import StatsStore

NAMES = [
    "Lionel Messi",
    "Neymar",
    "Gonzalo Higuaín",
    "Cristiano Ronaldo",
    "Ayoub El Kaabi",
    "Edinson Cavani",
    "Radamel Falcao",
    "Arturo Vidal",
]


def main() -> None:
    reload_manual_profiles()
    store = StatsStore()
    print("=== Board-ready prime spot-check ===")
    for name in NAMES:
        try:
            canon, data, label = build_prime_stats_dict(name, store, cache_only=True)
            ps = PlayerStats.from_dict(canon, data)
            print(
                f"{canon} [{label}] "
                f"shots={ps.shots90:.2f} sot={ps.shots_on_target90:.2f} "
                f"g={ps.goals90:.2f} xg={ps.xg90:.2f} xa={ps.xa90:.2f} "
                f"kp={ps.key_passes90:.2f} dr={ps.dribbles90:.2f} "
                f"pp={ps.pass_pct:.1f} dp={ps.dribble_pct:.1f} "
                f"aer={ps.aerials_won90:.2f}"
            )
        except Exception as exc:
            print(f"FAIL {name}: {exc}")

    print("\n=== Peak/season pick alignment vs ROUND3 sheet ===")
    tl = json.loads(Path("data/team_lineups.json").read_text(encoding="utf-8"))
    mismatches = []
    for team_key, pick in ROUND3_SEASON_PICKS.items():
        hit = None
        needle = team_key.replace(" ", "").lower()
        for name, rec in tl.items():
            key = name.replace(" ", "").lower()
            if needle in key or key in needle:
                hit = rec
                break
        peak = (hit or {}).get("peak_season") or {}
        sp = lookup_manual_season_pick(pick["player"], pick["season"], cache_only=True)
        print(
            f"{team_key}: sheet={pick['player']} {pick['season']} | "
            f"lineup_peak={peak.get('player')} {peak.get('season')} | "
            f"manual_pick={'yes' if sp else 'NO'}"
        )
        if peak.get("season") and peak.get("season") != pick["season"]:
            mismatches.append({"team": team_key, "peak": peak, "sheet": pick})
    print(f"season mismatches vs ROUND3: {len(mismatches)}")
    for row in mismatches:
        print(" ", row)

    report = json.loads(Path("data/_prime_gap_backfill_report.json").read_text(encoding="utf-8"))
    print(
        f"\nBackfill summary: repaired={report['repaired_count']} "
        f"still_incomplete={report['still_incomplete_count']} "
        f"of {report['prime_or_pick_count']}"
    )


if __name__ == "__main__":
    main()
