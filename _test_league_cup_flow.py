"""End-to-end verification of the League + Cup tournament format's
scheduling algorithm -- no HTTP/browser needed, calls the real module
functions directly against a temp-dir-backed tournament document. See
C:\\Users\\Admin\\.claude\\plans\\piped-strolling-hippo.md for the design this proves.
"""
from __future__ import annotations

import random
import tempfile
from pathlib import Path

from web import league_cup as lc
from web import tournament as tmod

TEAMS = [f"Team{i}" for i in range(1, 11)]
OPPONENT = "Organ's XI"


def _all_league_fixtures(t):
    return t["league"]["fixtures"]


def _all_ties(t):
    return lc._all_ties(t)


def _play(t, match_id, home_goals, away_goals, *, rng=None):
    """Play one fixture with synthetic goal events (for tally verification)."""
    kind, fx, tie = lc._find_playable(t, match_id)
    assert fx is not None, f"fixture {match_id} not found"
    home, away = fx["home"], fx["away"]
    events = []
    for _ in range(home_goals):
        events.append({"type": "goal", "side": "home", "player": f"{home}_scorer"})
    for _ in range(away_goals):
        events.append({"type": "goal", "side": "away", "player": f"{away}_scorer"})
    out = lc.complete_from_board(t["id"], match_id, home_goals, away_goals, board_events=events)
    return out


def _assert_no_double_booking(t):
    """No team appears in two fixtures (league or cup) scheduled at the same gw."""
    occ: dict[tuple[str, int], list[str]] = {}
    for fx in _all_league_fixtures(t):
        if fx["played"]:
            continue
        gw = fx["scheduled_gw"]
        for team in (fx["home"], fx["away"]):
            occ.setdefault((team, gw), []).append(fx["id"])
    for ti in _all_ties(t):
        for leg in ti.get("legs") or []:
            if leg["played"]:
                continue
            gw = ti.get("gw_leg1") if leg["leg"] == 1 else ti.get("gw_leg2")
            if gw is None:
                continue
            for team in (ti.get("home"), ti.get("away")):
                if team:
                    occ.setdefault((team, gw), []).append(leg["id"])
    dupes = {k: v for k, v in occ.items() if len(v) > 1}
    assert not dupes, f"double-booking detected: {dupes}"


def _reload(t):
    return tmod.load_tournament(t["id"])


def main() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        old_dir = tmod.TOURNAMENTS_DIR
        tmod.TOURNAMENTS_DIR = tmp
        try:
            _run(tmp)
        finally:
            tmod.TOURNAMENTS_DIR = old_dir


def _run(tmp: Path) -> None:
    rng = random.Random(42)

    # 1. Create
    t = lc.create_tournament("Test League", TEAMS, friendly_opponent=OPPONENT)
    assert len(t["friendlies"]["fixtures"]) == 10
    assert len(t["league"]["fixtures"]) == 90
    for fx in t["league"]["fixtures"]:
        assert fx["original_gw"] == fx["scheduled_gw"]
    print("[1/10] create_tournament OK: 10 friendlies, 90 league fixtures")

    league_goal_tally: dict[str, int] = {}
    cup_goal_tally: dict[str, int] = {}
    friendly_goal_tally: dict[str, int] = {}

    # 2. Friendlies
    for fx in list(t["friendlies"]["fixtures"]):
        hg, ag = rng.randint(0, 3), rng.randint(0, 3)
        out = _play(t, fx["id"], hg, ag)
        t = out["tournament"]
        friendly_goal_tally[fx["home"]] = friendly_goal_tally.get(fx["home"], 0) + hg
        friendly_goal_tally[OPPONENT] = friendly_goal_tally.get(OPPONENT, 0) + ag
    assert all(fx["played"] for fx in t["friendlies"]["fixtures"])
    league_boards = tmod.player_leaderboards(t, competition="league")
    cup_boards = tmod.player_leaderboards(t, competition="cup")
    assert league_boards["top_goalscorers"] == [], league_boards["top_goalscorers"]
    assert cup_boards["top_goalscorers"] == [], cup_boards["top_goalscorers"]
    print("[2/10] friendlies played, excluded from league/cup boards OK")

    # 3. GW1-9 (45 fixtures), checking no-double-booking after every result
    first_leg = sorted([fx for fx in t["league"]["fixtures"] if fx["original_gw"] <= 9], key=lambda f: f["id"])
    for fx in first_leg:
        hg, ag = rng.randint(0, 4), rng.randint(0, 4)
        out = _play(t, fx["id"], hg, ag)
        t = out["tournament"]
        league_goal_tally[fx["home"]] = league_goal_tally.get(fx["home"], 0) + hg
        league_goal_tally[fx["away"]] = league_goal_tally.get(fx["away"], 0) + ag
        _assert_no_double_booking(t)
    assert sum(1 for fx in t["league"]["fixtures"] if fx["played"]) == 45
    print("[3/10] GW1-9 played (45 fixtures), no double-booking at every step OK")

    # 4. Playoff auto-created
    ties = t["cup"]["playoff"]["ties"]
    assert len(ties) == 2, ties
    ranked = tmod._sort_standings(t["league"]["table"])
    r7, r8, r9, r10 = ranked[6], ranked[7], ranked[8], ranked[9]
    expect_pairs = {frozenset((r7, r8)), frozenset((r9, r10))}
    got_pairs = {frozenset((ti["home"], ti["away"])) for ti in ties}
    assert got_pairs == expect_pairs, (got_pairs, expect_pairs)
    assert ties[0]["gw_leg1"] == 10 and ties[0]["gw_leg2"] == 11
    assert ties[1]["gw_leg1"] == 10 and ties[1]["gw_leg2"] == 11
    blocked = {r7, r8, r9, r10}
    postponed_gw10 = [
        fx for fx in t["league"]["fixtures"]
        if fx["postponements"] and fx["postponements"][-1]["from_gw"] == 10
    ]
    for fx in postponed_gw10:
        assert fx["home"] in blocked or fx["away"] in blocked, fx
    _assert_no_double_booking(t)
    print(f"[4/10] playoff auto-created: {r7}v{r8}, {r9}v{r10} at GW10/11, "
          f"{len(postponed_gw10)} GW10 fixtures postponed OK")

    # 5. Play both playoff legs (each leg1 then leg2, synthetic low scores to
    # keep aggregate deterministic-ish; any level scenario resolved via
    # explicit winner + decided_by="pens" fallback)
    def _play_two_legged_tie(tie_id):
        nonlocal t
        tie = next(ti for ti in _all_ties(t) if ti["id"] == tie_id)
        leg1_id = tie["legs"][0]["id"]
        leg2_id = tie["legs"][1]["id"]
        hg1, ag1 = rng.randint(0, 3), rng.randint(0, 2)
        out = _play(t, leg1_id, hg1, ag1)
        t = out["tournament"]
        cup_goal_tally[tie["home"]] = cup_goal_tally.get(tie["home"], 0) + hg1
        cup_goal_tally[tie["away"]] = cup_goal_tally.get(tie["away"], 0) + ag1
        # leg 2: force a clean away-goals-safe decisive aggregate by scoring
        # the leg-2 home side (tie's away side) enough to avoid a level tie
        hg2, ag2 = rng.randint(0, 1), hg1 + ag1 + 2
        out = _play(t, leg2_id, hg2, ag2)
        t = out["tournament"]
        cup_goal_tally[tie["away"]] = cup_goal_tally.get(tie["away"], 0) + hg2
        cup_goal_tally[tie["home"]] = cup_goal_tally.get(tie["home"], 0) + ag2
        _assert_no_double_booking(t)

    _play_two_legged_tie("po-1")
    _play_two_legged_tie("po-2")
    assert all(ti["played"] for ti in t["cup"]["playoff"]["ties"])
    print("[5/10] both playoff legs played OK")

    # 6. Cup draw
    t = lc.draw_cup_round(t["id"], seed=7)
    r8_ties = t["cup"]["rounds"][0]["ties"]
    assert len(r8_ties) == 4
    field = set()
    for ti in r8_ties:
        field.add(ti["home"])
        field.add(ti["away"])
    assert len(field) == 8
    assert r8_ties[0]["gw_leg1"] == 12 and r8_ties[0]["gw_leg2"] == 13
    _assert_no_double_booking(t)
    print(f"[6/10] cup draw OK: R8 field={sorted(field)}, GW12/13")

    # 7. Play R8, assert SF auto-paired
    for ti in list(r8_ties):
        _play_two_legged_tie(ti["id"])
    sf_ties = t["cup"]["rounds"][1]["ties"]
    assert all(ti.get("home") and ti.get("away") for ti in sf_ties), sf_ties
    assert sf_ties[0]["gw_leg1"] is not None
    print(f"[7/10] R8 played, SF auto-paired at GW{sf_ties[0]['gw_leg1']}/{sf_ties[0]['gw_leg2']} OK")

    # 8. Play SF, assert Final auto-paired
    for ti in list(sf_ties):
        _play_two_legged_tie(ti["id"])
    final_ties = t["cup"]["rounds"][2]["ties"]
    assert len(final_ties) == 1
    assert final_ties[0].get("home") and final_ties[0].get("away")
    assert final_ties[0]["gw_leg1"] is not None
    print(f"[8/10] SF played, Final auto-paired at GW{final_ties[0]['gw_leg1']}/{final_ties[0]['gw_leg2']} OK")

    # 9. Play Final
    final_tie_id = final_ties[0]["id"]
    _play_two_legged_tie(final_tie_id)
    final_tie = next(ti for ti in _all_ties(t) if ti["id"] == final_tie_id)
    assert final_tie["played"]
    cup_winner = final_tie["winner"]
    print(f"[9/10] Final played, cup winner: {cup_winner}")

    # 10. Play out every remaining league fixture (catch-up gameweeks)
    remaining = [fx for fx in t["league"]["fixtures"] if not fx["played"]]
    assert remaining, "expected postponed catch-up fixtures still unplayed"
    max_gw = max(fx["scheduled_gw"] for fx in remaining)
    print(f"    remaining league fixtures: {len(remaining)}, catch-up reaches GW{max_gw}")
    assert t["status"] != "complete", "should not be complete with league fixtures still unplayed"
    for fx in sorted(remaining, key=lambda f: (f["scheduled_gw"], f["id"])):
        hg, ag = rng.randint(0, 4), rng.randint(0, 4)
        out = _play(t, fx["id"], hg, ag)
        t = out["tournament"]
        league_goal_tally[fx["home"]] = league_goal_tally.get(fx["home"], 0) + hg
        league_goal_tally[fx["away"]] = league_goal_tally.get(fx["away"], 0) + ag
    assert all(fx["played"] for fx in t["league"]["fixtures"])
    assert t["status"] == "complete", t["status"]
    print("[10/10] all league fixtures played, tournament marked complete OK")

    # Final leaderboard cross-check
    league_boards = tmod.player_leaderboards(t, competition="league")
    cup_boards = tmod.player_leaderboards(t, competition="cup")
    league_scored_teams = {row["team"] for row in league_boards["player_tallies"]}
    cup_scored_teams = {row["team"] for row in cup_boards["player_tallies"]}
    assert OPPONENT not in league_scored_teams
    assert OPPONENT not in cup_scored_teams
    league_total_goals = sum(row["goals"] for row in league_boards["player_tallies"])
    expected_league_total = sum(league_goal_tally.values())
    assert league_total_goals == expected_league_total, (league_total_goals, expected_league_total)
    cup_total_goals = sum(row["goals"] for row in cup_boards["player_tallies"])
    expected_cup_total = sum(cup_goal_tally.values())
    assert cup_total_goals == expected_cup_total, (cup_total_goals, expected_cup_total)
    print(f"    league goals: {league_total_goals} == expected {expected_league_total}")
    print(f"    cup goals: {cup_total_goals} == expected {expected_cup_total}")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
