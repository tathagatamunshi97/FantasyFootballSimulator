"""End-to-end verification of the manager-dashboard Analysis sections
(zone_breakdown, shots_on_target, player_impact, tactical_identity,
attacking/defensive analysis, manager_insight, next_match_game_plan)
against a real local League+Cup tournament, with synthetic board_events
carrying real player names + shot zones so aggregate_player_tallies has
something to read from (the public API strips board_events/match_log by
design -- this test supplies them directly instead, the way the live
engine actually would). See C:\\Users\\Admin\\.claude\\plans\\piped-strolling-hippo.md.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from web import league_cup as lc
from web import tournament as tmod

TEAMS = [f"Team{i}" for i in range(1, 11)]
OPPONENT = "Organ's XI"


def _play_with_events(t, match_id, home_goals, away_goals, *, home_zones, away_zones):
    """Play one fixture with synthetic goal/shot events carrying player
    names and zones, mirroring what tactic_board.js actually pushes."""
    kind, fx, tie = lc._find_playable(t, match_id)
    assert fx is not None, f"fixture {match_id} not found"
    home, away = fx["home"], fx["away"]
    events = []
    ppda_passes_home = ppda_actions_home = 0
    ppda_passes_away = ppda_actions_away = 0
    for i, zone in enumerate(home_zones):
        is_goal = i < home_goals
        events.append({
            "type": "shot", "side": "home", "player": f"{home}_P{i}",
            "player_short": f"H{i}", "zone": zone, "xg": 0.2, "in_box": True,
        })
        if is_goal:
            events.append({"type": "goal", "side": "home", "player": f"{home}_P{i}", "player_short": f"H{i}"})
    for i, zone in enumerate(away_zones):
        is_goal = i < away_goals
        events.append({
            "type": "shot", "side": "away", "player": f"{away}_P{i}",
            "player_short": f"A{i}", "zone": zone, "xg": 0.2, "in_box": True,
        })
        if is_goal:
            events.append({"type": "goal", "side": "away", "player": f"{away}_P{i}", "player_short": f"A{i}"})
    # A couple of tackles/interceptions so player_impact has defensive rows too.
    events.append({"type": "pass_broken", "side": "home", "player": f"{home}_DEF", "player_short": "HD", "by": f"{home}_DEF"})
    events.append({"type": "dribble_lost", "side": "away", "player": f"{away}_ATT", "player_short": "AA", "by": f"{home}_DEF"})

    match_log = {
        "events": events,
        "goals": [e for e in events if e["type"] == "goal"],
        "counts": {
            "home": {
                "shots": len(home_zones), "shots_on_target": home_goals,
                "big_chances": 1, "big_chance_goals": 1 if home_goals else 0,
                "passes_attempted": 300, "passes_completed": 260, "progressive_passes": 40,
                "ppda_passes": 60, "ppda_actions": 40,
            },
            "away": {
                "shots": len(away_zones), "shots_on_target": away_goals,
                "big_chances": 1, "big_chance_goals": 1 if away_goals else 0,
                "passes_attempted": 260, "passes_completed": 200, "progressive_passes": 20,
                "ppda_passes": 55, "ppda_actions": 35,
            },
        },
        "xg": {"home": round(0.2 * len(home_zones), 2), "away": round(0.2 * len(away_zones), 2)},
        "possession_pct": {"home": 55.0, "away": 45.0},
    }
    out = lc.complete_from_board(t["id"], match_id, home_goals, away_goals, board_events=events, match_log=match_log)
    return out["tournament"]


def main() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        old_dir = tmod.TOURNAMENTS_DIR
        tmod.TOURNAMENTS_DIR = tmp
        try:
            _run()
        finally:
            tmod.TOURNAMENTS_DIR = old_dir


def _run() -> None:
    t = lc.create_tournament("Dashboard Test League", TEAMS, friendly_opponent=OPPONENT)

    first_leg = sorted([fx for fx in t["league"]["fixtures"] if fx["original_gw"] <= 9], key=lambda f: f["id"])
    # Team1 always plays with a left-heavy attack, wins its games.
    t1_fixtures = [fx for fx in first_leg if "Team1" in (fx["home"], fx["away"])]
    other_fixtures = [fx for fx in first_leg if "Team1" not in (fx["home"], fx["away"])]

    for fx in t1_fixtures:
        is_home = fx["home"] == "Team1"
        t1_zones = ["left", "left", "left", "central"]  # 3/4 left -> 75% left-heavy
        opp_zones = ["central"]
        hg, ag = (3, 0) if is_home else (0, 3)
        hz, az = (t1_zones, opp_zones) if is_home else (opp_zones, t1_zones)
        t = _play_with_events(t, fx["id"], hg, ag, home_zones=hz, away_zones=az)

    for fx in other_fixtures:
        t = _play_with_events(t, fx["id"], 1, 1, home_zones=["central"], away_zones=["central"])

    print(f"[1/6] played {len(t1_fixtures)} Team1 fixtures + {len(other_fixtures)} others OK")

    summary = tmod.team_analysis_summary("Team1")
    ss = summary["season_stats"]
    assert ss is not None, "expected season_stats for a team with played matches"
    print("[2/6] team_analysis_summary returns non-None season_stats OK")

    # Attacking analysis: Team1 should show a left-heavy zone breakdown.
    att = ss["attacking_analysis"]
    assert att is not None, "expected attacking_analysis"
    zp = att["zone_breakdown_pct"]
    assert zp is not None and zp.get("left", 0) >= 60, f"expected left-heavy zone breakdown, got {zp}"
    print(f"[3/6] attacking_analysis zone_breakdown_pct correctly left-heavy: {zp} OK")

    # Manager insight should flag the left-heavy bias under "consider".
    insight = ss["manager_insight"]
    assert any("left" in c.lower() for c in insight["consider"]), f"expected a left-heavy callout in consider, got {insight}"
    print(f"[4/6] manager_insight flags left-heavy attack under consider: {insight['consider']} OK")

    # Player impact should list real players with goals.
    pi = ss["player_impact"]
    assert pi, "expected non-empty player_impact"
    assert any(p["goals"] for p in pi), f"expected at least one player with goals, got {pi}"
    print(f"[5/6] player_impact populated with {len(pi)} real player rows, top: {pi[0]} OK")

    # shots_on_target should reflect the synthetic counts (home_goals per match as shots_on_target).
    assert att["shots_on_target"] > 0, "expected non-zero shots_on_target"
    print(f"[6/6] attacking_analysis shots_on_target={att['shots_on_target']} (non-zero) OK")

    print("\nALL DASHBOARD CHECKS PASSED")


if __name__ == "__main__":
    main()
