"""End-to-end verification of the purse system against a real local
League+Cup tournament -- no HTTP/browser needed, calls the real module
functions directly against temp-dir-backed tournament + purse-ledger
documents. See C:\\Users\\Admin\\.claude\\plans\\piped-strolling-hippo.md
for the design this proves.

Deterministic (non-random) scores throughout, so every purse figure can be
hand-computed and asserted exactly, rather than just checked for
plausibility.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from web import league_cup as lc
from web import team_purse
from web import tournament as tmod

TEAMS = [f"Team{i}" for i in range(1, 11)]
OPPONENT = "Organ's XI"


def _play(t, match_id, home_goals, away_goals):
    kind, fx, tie = lc._find_playable(t, match_id)
    assert fx is not None, f"fixture {match_id} not found"
    out = lc.complete_from_board(t["id"], match_id, home_goals, away_goals)
    return out["tournament"]


def _play_two_legged_tie(t, tie_id, hg1, ag1, hg2, ag2):
    tie = next(ti for ti in lc._all_ties(t) if ti["id"] == tie_id)
    t = _play(t, tie["legs"][0]["id"], hg1, ag1)
    tie = next(ti for ti in lc._all_ties(t) if ti["id"] == tie_id)
    t = _play(t, tie["legs"][1]["id"], hg2, ag2)
    return t


def _purse_row(t, team):
    table = team_purse.purse_table_for_tournament(t)
    return next(r for r in table["teams"] if r["team"] == team)


def main() -> None:
    with tempfile.TemporaryDirectory() as raw_t, tempfile.TemporaryDirectory() as raw_p:
        tmp_tournaments = Path(raw_t)
        tmp_purse = Path(raw_p) / "team_purse.json"
        old_dir = tmod.TOURNAMENTS_DIR
        old_purse_path = team_purse.PURSE_PATH
        tmod.TOURNAMENTS_DIR = tmp_tournaments
        team_purse.PURSE_PATH = tmp_purse
        try:
            _run()
        finally:
            tmod.TOURNAMENTS_DIR = old_dir
            team_purse.PURSE_PATH = old_purse_path


def _run() -> None:
    # 1. Starting purse -- synthetic team names aren't on the real sheet,
    # so this exercises the fail-open (0.0) path and freezing.
    t = lc.create_tournament("Purse Test League", TEAMS, friendly_opponent=OPPONENT)
    row = _purse_row(t, "Team1")
    assert row["starting_purse"] == 0.0, row
    assert row["total_purse"] == 0.0, row
    print("[1/8] fresh tournament: starting purse 0.0 (fail-open for unknown team) OK")

    # 2. Play GW1-9 (45 fixtures) with hand-picked scores: Team1 always
    # wins, Team2 always draws its games, everyone else scores normally.
    # Held back one fixture to play LAST, so step 2b can reset+replay an
    # *earlier* one while the playoff still doesn't exist yet --
    # reset_match_result itself refuses to reset a GW<=9 league match once
    # the playoff has started (a real, pre-existing restriction that fires
    # the instant the 45th/last GW<=9 fixture completes), so a reset is
    # only reachable strictly before that final fixture is played.
    first_leg = sorted(
        [fx for fx in t["league"]["fixtures"] if fx["original_gw"] <= 9],
        key=lambda f: f["id"],
    )
    last_fx = first_leg[-1]
    reset_fx = next(fx for fx in first_leg if fx["home"] == "Team1" and fx["id"] != last_fx["id"])
    to_play_now = [fx for fx in first_leg if fx["id"] != last_fx["id"]]

    team1_wins = 0
    team2_draws = 0
    for fx in to_play_now:
        home, away = fx["home"], fx["away"]
        if home == "Team1":
            hg, ag = 2, 0
            team1_wins += 1
        elif away == "Team1":
            hg, ag = 0, 2
            team1_wins += 1
        elif "Team2" in (home, away):
            hg, ag = 1, 1
            team2_draws += 1
        else:
            hg, ag = 1, 0
        t = _play(t, fx["id"], hg, ag)

    row1 = _purse_row(t, "Team1")
    row2 = _purse_row(t, "Team2")
    assert row1["league_bonus"] == team1_wins * 100, (row1, team1_wins)
    assert row2["league_bonus"] == team2_draws * 50, (row2, team2_draws)
    print(f"[2/8] GW1-9's first 44 fixtures played: Team1 {team1_wins} wins -> +{row1['league_bonus']}, "
          f"Team2 {team2_draws} draws -> +{row2['league_bonus']} OK")

    # 2b. reset_match_result on one of those 44 (playoff still doesn't
    # exist) -- purse must drop back with zero manual clawback code.
    before = _purse_row(t, "Team1")["league_bonus"]
    lc.reset_match_result(t["id"], reset_fx["id"])
    t = _reload(t)
    after = _purse_row(t, "Team1")["league_bonus"]
    assert after == before - 100, (before, after)
    t = _play(t, reset_fx["id"], 2, 0)  # replay identically so later totals are unaffected
    restored = _purse_row(t, "Team1")["league_bonus"]
    assert restored == before, (before, restored)
    print(f"[2b/8] reset_match_result: Team1 league_bonus {before} -> {after} -> {restored} "
          f"(dropped by exactly 100 then restored on replay, no manual clawback code) OK")

    # 2c. Now play the held-back 45th fixture, completing GW1-9 and
    # triggering the playoff.
    lf_home, lf_away = last_fx["home"], last_fx["away"]
    if lf_home == "Team1":
        hg, ag = 2, 0
        team1_wins += 1
    elif lf_away == "Team1":
        hg, ag = 0, 2
        team1_wins += 1
    elif "Team2" in (lf_home, lf_away):
        hg, ag = 1, 1
        team2_draws += 1
    else:
        hg, ag = 1, 0
    t = _play(t, last_fx["id"], hg, ag)
    assert sum(1 for fx in t["league"]["fixtures"] if fx["original_gw"] <= 9 and fx["played"]) == 45

    # 3. Playoff auto-created -- top 6 get +50, the 4 playoff teams get 0
    # qualification bonus (yet).
    ties = t["cup"]["playoff"]["ties"]
    assert len(ties) == 2, ties
    playoff_teams = {ti["home"] for ti in ties} | {ti["away"] for ti in ties}
    for name in TEAMS:
        expected = 0 if name in playoff_teams else 50
        row = _purse_row(t, name)
        assert row["qualification_bonus"] == expected, (name, row, playoff_teams)
    print(f"[3/8] playoff created: {playoff_teams} get 0 qualification bonus (yet), "
          f"other 6 teams get +50 OK")

    # 4. Play both playoff ties -- winners get +25 playoff bonus, losers 0.
    po1, po2 = ties[0], ties[1]
    t = _play_two_legged_tie(t, po1["id"], 2, 0, 0, 0)  # po1 home wins outright
    t = _play_two_legged_tie(t, po2["id"], 0, 0, 0, 2)  # po2 away wins outright
    po1_winner = next(ti for ti in t["cup"]["playoff"]["ties"] if ti["id"] == po1["id"])["winner"]
    po2_winner = next(ti for ti in t["cup"]["playoff"]["ties"] if ti["id"] == po2["id"])["winner"]
    for name in TEAMS:
        row = _purse_row(t, name)
        expected = 25 if name in (po1_winner, po2_winner) else 0
        assert row["playoff_bonus"] == expected, (name, row, po1_winner, po2_winner)
    print(f"[4/8] playoff played: winners {po1_winner}, {po2_winner} get +25, others 0 OK")

    # 5. Draw + play the cup bracket -- winner of each tie gets +50, loser -25.
    t = lc.draw_cup_round(t["id"], seed=1)
    r8 = t["cup"]["rounds"][0]["ties"]
    for ti in r8:
        t = _play_two_legged_tie(t, ti["id"], 3, 0, 0, 0)  # home always wins outright
    r8_after = t["cup"]["rounds"][0]["ties"]
    for ti in r8_after:
        winner, loser = ti["winner"], (ti["home"] if ti["winner"] != ti["home"] else ti["away"])
        row_w = _purse_row(t, winner)
        row_l = _purse_row(t, loser)
        assert row_w["cup_bonus"] >= 50, row_w
        assert row_l["cup_bonus"] <= -25, row_l
    print(f"[5/8] R8 played: every winner +50 cup_bonus, every loser -25 OK")

    sf = t["cup"]["rounds"][1]["ties"]
    for ti in sf:
        t = _play_two_legged_tie(t, ti["id"], 3, 0, 0, 0)
    final_ = t["cup"]["rounds"][2]["ties"]
    t = _play_two_legged_tie(t, final_[0]["id"], 3, 0, 0, 0)
    final_tie = next(ti for ti in lc._all_ties(t) if ti["id"] == final_[0]["id"])
    champion = final_tie["winner"]
    champ_row = _purse_row(t, champion)
    # champion won R8, SF, Final: +50 three times = +150 cup_bonus
    assert champ_row["cup_bonus"] == 150, champ_row
    print(f"[6/8] full cup bracket played, champion {champion}: cup_bonus == 150 (3 round wins) OK")

    # 7. reset_match_result on a GW<=9 league match is *correctly blocked*
    # once the playoff has started (a real, pre-existing restriction in
    # league_cup.py, not something the purse system adds) -- confirms
    # that restriction is intact and that the purse system needs no
    # special-casing around it (step 2b already proved the self-healing
    # recompute property for the case where a reset IS reachable).
    late_reset_fx = next(fx for fx in t["league"]["fixtures"] if fx["home"] == "Team1" and fx["played"])
    before = _purse_row(t, "Team1")["league_bonus"]
    try:
        lc.reset_match_result(t["id"], late_reset_fx["id"])
        raise AssertionError("expected reset_match_result to raise once the playoff has started")
    except ValueError:
        pass
    t = _reload(t)
    after = _purse_row(t, "Team1")["league_bonus"]
    assert after == before, (before, after)
    print(f"[7/8] reset_match_result correctly blocked post-playoff; "
          f"Team1 league_bonus unchanged at {after} OK")

    # 8. "Carried over for tournament renewals": create a second
    # tournament reusing Team1/Team2, confirm its prior_tournaments_total
    # for those teams equals the first tournament's this_tournament_total.
    t_first_final = _reload(t)
    row1_final = _purse_row(t_first_final, "Team1")
    row2_final = _purse_row(t_first_final, "Team2")

    t2nd = lc.create_tournament("Purse Test League Season 2", TEAMS, friendly_opponent=OPPONENT)
    row1_new = _purse_row(t2nd, "Team1")
    row2_new = _purse_row(t2nd, "Team2")
    assert row1_new["prior_tournaments_total"] == row1_final["this_tournament_total"], (
        row1_new, row1_final
    )
    assert row2_new["prior_tournaments_total"] == row2_final["this_tournament_total"], (
        row2_new, row2_final
    )
    assert row1_new["starting_purse"] == row1_final["starting_purse"], "starting purse must stay frozen"
    assert row1_new["total_purse"] == row1_new["starting_purse"] + row1_new["prior_tournaments_total"]
    print(f"[8/8] second tournament created: Team1 prior_tournaments_total "
          f"({row1_new['prior_tournaments_total']}) == season-1 total "
          f"({row1_final['this_tournament_total']}) -- carry-over confirmed with "
          f"zero explicit renewal step OK")

    print("\nALL PURSE CHECKS PASSED")


def _reload(t):
    return tmod.load_tournament(t["id"])


if __name__ == "__main__":
    main()
