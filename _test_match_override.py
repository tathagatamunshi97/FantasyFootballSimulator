"""Quick check: group match override recomputes standings points."""
from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

from web import tournament as tmod


def _seed_group_tournament(tmp: Path) -> str:
    tid = uuid.uuid4().hex[:12]
    t = {
        "id": tid,
        "name": "Override Test",
        "status": "group_stage",
        "created_at": tmod._now(),
        "updated_at": tmod._now(),
        "team_names": ["Alpha", "Beta"],
        "settings": {
            "group_count": 1,
            "teams_per_group": 2,
            "advance_per_group": 1,
            "knockout_format": "single_elim",
            "simulations_per_match": 100,
        },
        "groups": {
            "A": {
                "teams": ["Alpha", "Beta"],
                "fixtures": [
                    {
                        "id": "gA-1",
                        "home": "Alpha",
                        "away": "Beta",
                        "round": 1,
                        "played": True,
                        "result_id": "gA-1",
                        "score": "1-0",
                        "winner": "Alpha",
                    }
                ],
                "table": {
                    "Alpha": {"played": 1, "w": 1, "d": 0, "l": 0, "gf": 1, "ga": 0, "gd": 1, "pts": 3},
                    "Beta": {"played": 1, "w": 0, "d": 0, "l": 1, "gf": 0, "ga": 1, "gd": -1, "pts": 0},
                },
            }
        },
        "knockout": {"format": "single_elim", "rounds": []},
        "match_results": {
            "gA-1": {
                "match_id": "gA-1",
                "stage": "group",
                "group": "A",
                "home": "Alpha",
                "away": "Beta",
                "score": "1-0",
                "home_goals": 1,
                "away_goals": 0,
                "engine_home_goals": 1,
                "engine_away_goals": 0,
                "winner": "Alpha",
                "manually_overridden": False,
                "admin_accepted": False,
                "home_win_pct": 55,
                "away_win_pct": 20,
                "expected_xg": {"home": 1.2, "away": 0.8},
                "played_at": tmod._now(),
            }
        },
    }
    path = tmp / f"{tid}.json"
    path.write_text(json.dumps(t, indent=2), encoding="utf-8")
    return tid


def main() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        old_dir = tmod.TOURNAMENTS_DIR
        tmod.TOURNAMENTS_DIR = tmp
        try:
            tid = _seed_group_tournament(tmp)
            before = tmod.load_tournament(tid)
            assert before["groups"]["A"]["table"]["Alpha"]["pts"] == 3
            assert before["groups"]["A"]["table"]["Beta"]["pts"] == 0

            out = tmod.override_match_result(tid, "gA-1", home_goals=0, away_goals=2)
            table = out["tournament"]["groups"]["A"]["table"]
            result = out["result"]

            assert table["Alpha"]["pts"] == 0, table
            assert table["Beta"]["pts"] == 3, table
            assert table["Beta"]["gf"] == 2 and table["Alpha"]["ga"] == 2
            assert result["manually_overridden"] is True
            assert result["engine_home_goals"] == 1
            assert result["engine_away_goals"] == 0
            assert result["home_goals"] == 0 and result["away_goals"] == 2
            assert result["winner"] == "Beta"
            assert out["match"]["score"] == "0-2"

            accepted = tmod.accept_match_result(tid, "gA-1")
            assert accepted["result"]["admin_accepted"] is True

            # Knockout draw override: winner required / MC tiebreak
            ko_id = uuid.uuid4().hex[:12]
            ko = {
                "id": ko_id,
                "name": "KO Override Test",
                "status": "knockout",
                "created_at": tmod._now(),
                "updated_at": tmod._now(),
                "team_names": ["Alpha", "Beta"],
                "settings": {"knockout_format": "single_elim"},
                "groups": {},
                "knockout": {
                    "format": "single_elim",
                    "rounds": [
                        {
                            "name": "Final",
                            "label": "Final",
                            "ties": [
                                {
                                    "id": "ko-final",
                                    "home": "Alpha",
                                    "away": "Beta",
                                    "played": True,
                                    "result_id": "ko-final",
                                    "score": "1-1",
                                    "winner": "Alpha",
                                    "feeds": [],
                                }
                            ],
                        }
                    ],
                },
                "match_results": {
                    "ko-final": {
                        "match_id": "ko-final",
                        "stage": "knockout",
                        "home": "Alpha",
                        "away": "Beta",
                        "score": "1-1",
                        "home_goals": 1,
                        "away_goals": 1,
                        "engine_home_goals": 1,
                        "engine_away_goals": 1,
                        "winner": "Alpha",
                        "home_win_pct": 40,
                        "away_win_pct": 45,
                        "expected_xg": {"home": 1.0, "away": 1.1},
                        "manually_overridden": False,
                        "admin_accepted": False,
                        "played_at": tmod._now(),
                    }
                },
            }
            (tmp / f"{ko_id}.json").write_text(json.dumps(ko, indent=2), encoding="utf-8")

            # Draw + no winner → MC tiebreak prefers Beta (higher away_win_pct)
            ko_out = tmod.override_match_result(ko_id, "ko-final", home_goals=2, away_goals=2)
            assert ko_out["result"]["winner"] == "Beta", ko_out["result"]

            # Explicit winner on draw
            ko_out2 = tmod.override_match_result(
                ko_id, "ko-final", home_goals=0, away_goals=0, winner="Alpha"
            )
            assert ko_out2["result"]["winner"] == "Alpha"
            assert ko_out2["match"]["winner"] == "Alpha"

            print("OK: group override recomputed points; KO draw uses MC / explicit winner")
        finally:
            tmod.TOURNAMENTS_DIR = old_dir


if __name__ == "__main__":
    main()
