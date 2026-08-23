"""
Personal tool -- not wired into the app (no route, no UI, nothing imports
this). Run it directly from the repo root:

    python tools/formation_sweep.py "MasterSimulator FC"

Sweeps every formation the app supports, auto-picks the best XI for each
using the same Hungarian-assignment algorithm the app's own auto-lineup
uses (lineup_builder.assign_lineup_slots), rates each XI with
team_ratings.compute_unit_ratings_by_slot, and ranks by Overall.

Ratings are a fast proxy, not ground truth -- for a real answer on the top
few candidates, ask Claude to run them through the tick-pump batch-match
harness (see memory: tick-pump-batch-simulation) for actual simulated
outcomes.
"""
from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows console default codepage can't print accented names

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from formation_fit import FORMATION_SLOTS  # noqa: E402
from google_sheets_teams import load_team_by_name  # noqa: E402
from lineup_builder import assign_lineup_slots, lineup_from_assignments  # noqa: E402
from models import FantasyTeam  # noqa: E402
from team_ratings import compute_unit_ratings_by_slot  # noqa: E402
from web.state import get_stats_store  # noqa: E402


def sweep(team_name: str) -> list[dict]:
    store = get_stats_store()
    team_payload = load_team_by_name(team_name, store=store)
    full_roster = team_payload.get("sheet_meta", {}).get("full_roster")
    if not full_roster:
        lineup_names = [row["player"] for row in team_payload.get("lineup", []) if row.get("player")]
        full_roster = lineup_names + list(team_payload.get("bench") or [])
    player_stats = store.cached_stats_map(full_roster)

    rows = []
    for formation in FORMATION_SLOTS:
        assignments = assign_lineup_slots(formation, full_roster, player_stats, max_players=None)
        lineup = [row for row in lineup_from_assignments(formation, assignments) if row.get("player")]
        if len(lineup) < 11:
            continue  # not enough eligible players for this formation's role mix
        used = {row["player"] for row in lineup}
        bench = [p for p in full_roster if p not in used]
        team = FantasyTeam.from_dict(
            {"name": team_name, "formation": formation, "lineup": lineup, "bench": bench}
        )
        ratings = compute_unit_ratings_by_slot(team, player_stats)
        rows.append(
            {
                "formation": formation,
                "lineup": lineup,
                "attack": ratings.attack,
                "finishing": ratings.finishing,
                "chance_creation": ratings.chance_creation,
                "midfield": ratings.midfield,
                "defence": ratings.defence,
                "midfield_defence": ratings.midfield_defence,
                "goalkeeper": ratings.goalkeeper,
                "overall": ratings.overall,
            }
        )
    rows.sort(key=lambda r: r["overall"], reverse=True)
    return rows


def main() -> None:
    team_name = sys.argv[1] if len(sys.argv) > 1 else "MasterSimulator FC"
    rows = sweep(team_name)
    if not rows:
        print(f"No viable formations found for '{team_name}' -- check the team name / roster.")
        return

    print(f"\nFormation sweep -- {team_name}\n")
    header = (
        f"{'Formation':<20}{'Overall':>9}{'Attack':>9}{'Finish':>9}"
        f"{'Create':>9}{'Mid':>9}{'Def':>9}{'MidDef':>9}{'GK':>9}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['formation']:<20}{r['overall']:>9.3f}{r['attack']:>9.3f}{r['finishing']:>9.3f}"
            f"{r['chance_creation']:>9.3f}{r['midfield']:>9.3f}{r['defence']:>9.3f}"
            f"{r['midfield_defence']:>9.3f}{r['goalkeeper']:>9.3f}"
        )

    print(f"\nTop 3 -- best XI per formation:\n")
    for r in rows[:3]:
        print(f"{r['formation']} (overall {r['overall']:.3f}):")
        for row in r["lineup"]:
            print(f"  {row['slot']:<5} {row['player']}")
        print()


if __name__ == "__main__":
    main()
