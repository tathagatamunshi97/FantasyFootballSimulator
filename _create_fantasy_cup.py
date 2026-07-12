#!/usr/bin/env python3
"""Create Fantasy Cup with exact groups/fixtures and clear finalize locks."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from web import tournament as tmod
from web.team_lineups import clear_all_finalize_locks, list_team_lineups

GROUP_A = [
    "Sohom+Mayukh",
    "Rishav",
    "Subhadro+Shubhajit",
    "DDR",
    "Chintu",
    "Dilshad",
    "Rohan + AnaC",
]

GROUP_B = [
    "Raktim",
    "Sugata",
    "Anindo",
    "KP+SS",
    "Kinjal+Sayan C",
    "Ryan",
    "Moga+Sanmitro",
]

# (home, away) per round
FIXTURES_A: dict[int, list[tuple[str, str]]] = {
    1: [
        ("Rishav", "Rohan + AnaC"),
        ("Subhadro+Shubhajit", "Dilshad"),
        ("DDR", "Chintu"),
    ],
    2: [
        ("Sohom+Mayukh", "Rohan + AnaC"),
        ("Rishav", "Chintu"),
        ("Subhadro+Shubhajit", "DDR"),
    ],
    3: [
        ("Sohom+Mayukh", "Dilshad"),
        ("Rohan + AnaC", "Chintu"),
        ("Rishav", "Subhadro+Shubhajit"),
    ],
    4: [
        ("Sohom+Mayukh", "Chintu"),
        ("Dilshad", "DDR"),
        ("Rohan + AnaC", "Subhadro+Shubhajit"),
    ],
    5: [
        ("Sohom+Mayukh", "DDR"),
        ("Chintu", "Subhadro+Shubhajit"),
        ("Dilshad", "Rishav"),
    ],
    6: [
        ("Sohom+Mayukh", "Subhadro+Shubhajit"),
        ("DDR", "Rishav"),
        ("Dilshad", "Rohan + AnaC"),
    ],
    7: [
        ("Sohom+Mayukh", "Rishav"),
        ("DDR", "Rohan + AnaC"),
        ("Chintu", "Dilshad"),
    ],
}

FIXTURES_B: dict[int, list[tuple[str, str]]] = {
    1: [
        ("Sugata", "Moga+Sanmitro"),
        ("Anindo", "Ryan"),
        ("KP+SS", "Kinjal+Sayan C"),
    ],
    2: [
        ("Raktim", "Moga+Sanmitro"),
        ("Sugata", "Kinjal+Sayan C"),
        ("Anindo", "KP+SS"),
    ],
    3: [
        ("Raktim", "Ryan"),
        ("Moga+Sanmitro", "Kinjal+Sayan C"),
        ("Sugata", "Anindo"),
    ],
    4: [
        ("Raktim", "Kinjal+Sayan C"),
        ("Ryan", "KP+SS"),
        ("Moga+Sanmitro", "Anindo"),
    ],
    5: [
        ("Raktim", "KP+SS"),
        ("Kinjal+Sayan C", "Anindo"),
        ("Ryan", "Sugata"),
    ],
    6: [
        ("Raktim", "Anindo"),
        ("KP+SS", "Sugata"),
        ("Ryan", "Moga+Sanmitro"),
    ],
    7: [
        ("Raktim", "Sugata"),
        ("KP+SS", "Moga+Sanmitro"),
        ("Kinjal+Sayan C", "Ryan"),
    ],
}


def _build_fixtures(group_key: str, schedule: dict[int, list[tuple[str, str]]]) -> list[dict]:
    fixtures: list[dict] = []
    match_num = 0
    for rnd in sorted(schedule):
        for home, away in schedule[rnd]:
            match_num += 1
            fixtures.append(
                {
                    "id": f"g{group_key}-{match_num}",
                    "home": home,
                    "away": away,
                    "round": rnd,
                    "played": False,
                    "result_id": None,
                }
            )
    return fixtures


def _assert_teams(group_teams: list[str], schedule: dict[int, list[tuple[str, str]]]) -> None:
    names = set(group_teams)
    for rnd, pairs in schedule.items():
        for home, away in pairs:
            if home not in names:
                raise SystemExit(f"Unknown home '{home}' in round {rnd}")
            if away not in names:
                raise SystemExit(f"Unknown away '{away}' in round {rnd}")
    # Each team plays 6 others once (7-team RR)
    seen: set[tuple[str, str]] = set()
    for pairs in schedule.values():
        for home, away in pairs:
            key = tuple(sorted((home, away)))
            if key in seen:
                raise SystemExit(f"Duplicate pairing: {home} vs {away}")
            seen.add(key)
    expected = len(group_teams) * (len(group_teams) - 1) // 2
    if len(seen) != expected:
        raise SystemExit(f"Expected {expected} unique pairings, got {len(seen)}")


def main() -> None:
    _assert_teams(GROUP_A, FIXTURES_A)
    _assert_teams(GROUP_B, FIXTURES_B)

    team_names = GROUP_A + GROUP_B
    settings = tmod._settings_from_group_count(14, 2, advance_per_group=4)
    assert settings["advance_per_group"] == 4
    assert settings["group_count"] == 2
    assert settings["teams_per_group"] == 7

    t = tmod.create_tournament("Fantasy Cup", team_names, settings)
    tid = t["id"]

    fixtures_a = _build_fixtures("A", FIXTURES_A)
    fixtures_b = _build_fixtures("B", FIXTURES_B)

    t["groups"] = {
        "A": {
            "teams": list(GROUP_A),
            "fixtures": fixtures_a,
            "table": tmod._empty_table(GROUP_A),
        },
        "B": {
            "teams": list(GROUP_B),
            "fixtures": fixtures_b,
            "table": tmod._empty_table(GROUP_B),
        },
    }
    t["status"] = "group_stage"
    t["knockout"] = {"format": "single_elim", "rounds": []}
    t["match_results"] = {}
    t["player_tallies"] = []
    t["top_goalscorers"] = []
    t["top_assisters"] = []
    tmod.save_tournament(t)

    # create_tournament already clears locks; clear again after fixture setup for certainty
    cleared = clear_all_finalize_locks()
    locked = [r for r in list_team_lineups() if r.get("locked") or r.get("finalized")]

    fx_count = len(fixtures_a) + len(fixtures_b)
    print(
        json.dumps(
            {
                "ok": True,
                "id": tid,
                "name": t["name"],
                "status": t["status"],
                "advance_per_group": t["settings"]["advance_per_group"],
                "group_count": t["settings"]["group_count"],
                "teams_per_group": t["settings"]["teams_per_group"],
                "fixtures_a": len(fixtures_a),
                "fixtures_b": len(fixtures_b),
                "fixtures_total": fx_count,
                "locks_cleared": cleared,
                "still_finalized": [r["team_name"] for r in locked],
                "url": f"http://localhost:8083/tournament?id={tid}",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
