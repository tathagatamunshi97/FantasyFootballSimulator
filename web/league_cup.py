"""League + Cup tournament format: 10-team double round-robin league with a
mid-season knockout cup carved out of it (playoff -> Round of 8 -> Semis ->
Final), plus a pre-season friendly round against an admin-only opponent
(Organ's XI). Coexists with the groups+knockout format in web/tournament.py
-- a fully separate document shape (``format: "league_cup"``), reusing that
module's storage layer and pure table/tie-building helpers by import.

See C:\\Users\\Admin\\.claude\\plans\\piped-strolling-hippo.md for the full design.
"""
from __future__ import annotations

import random
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from models import FantasyTeam
from stats_resolver import prepare_match_player_stats

from web import matchday_session
from web import tournament
from web.auth import _ADMIN_ONLY_TEAMS
from web.experiments import _apply_name_map
from web.state import get_stats_store
from web.team_lineups import apply_team_lineup, clear_all_finalize_locks

_READY_ROUND = {
    "round_key": "ready",
    "label": "Ready (no active tournament)",
    "tournament_id": None,
    "tournament_name": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Fixture generation
# ---------------------------------------------------------------------------


def _generate_friendlies(teams: list[str], opponent: str) -> list[dict[str, Any]]:
    return [
        {
            "id": f"fr-{i}",
            "home": team,
            "away": opponent,
            "played": False,
            "result_id": None,
            "score": None,
            "home_goals": None,
            "away_goals": None,
        }
        for i, team in enumerate(teams, start=1)
    ]


def _build_league_fixture(n: int, home: str, away: str, gw: int) -> dict[str, Any]:
    return {
        "id": f"lg-{n}",
        "home": home,
        "away": away,
        "original_gw": gw,
        "scheduled_gw": gw,
        "postponements": [],
        "played": False,
        "result_id": None,
        "score": None,
        "home_goals": None,
        "away_goals": None,
    }


def _generate_league_fixtures(teams: list[str]) -> list[dict[str, Any]]:
    """Double round-robin (home+away) over an even team count (10). GW1-9 is
    the first leg (circle method, same algorithm as
    tournament._round_robin_fixtures); GW10-18 mirrors the same pairs with
    home/away swapped, offset by the number of first-leg rounds."""
    n = len(teams)
    slots = list(teams)
    if n % 2 == 1:
        slots.append("__BYE__")
    count = len(slots)
    half = count // 2
    n_rounds = count - 1
    first_leg: list[tuple[int, str, str]] = []
    for rnd in range(n_rounds):
        for i in range(half):
            home, away = slots[i], slots[count - 1 - i]
            if home != "__BYE__" and away != "__BYE__":
                first_leg.append((rnd + 1, home, away))
        slots = [slots[0]] + [slots[-1]] + slots[1:-1]

    fixtures: list[dict[str, Any]] = []
    match_num = 0
    for gw, home, away in first_leg:
        match_num += 1
        fixtures.append(_build_league_fixture(match_num, home, away, gw))
    for gw, home, away in first_leg:
        match_num += 1
        fixtures.append(_build_league_fixture(match_num, away, home, gw + n_rounds))
    return fixtures


# ---------------------------------------------------------------------------
# Document / creation
# ---------------------------------------------------------------------------


def _default_league_cup_tournament(
    name: str, team_names: list[str], friendly_opponent: str, settings: dict[str, Any] | None
) -> dict[str, Any]:
    tid = uuid.uuid4().hex[:12]
    teams = [t.strip() for t in team_names if t and t.strip()]
    return {
        "id": tid,
        "name": name.strip() or f"League {tid[:6]}",
        "status": "active",
        "format": "league_cup",
        "created_at": _now(),
        "updated_at": _now(),
        "team_names": teams,
        "friendly_opponent": friendly_opponent,
        "friendlies": {"fixtures": _generate_friendlies(teams, friendly_opponent)},
        "league": {
            "teams": teams,
            "fixtures": _generate_league_fixtures(teams),
            "table": tournament._empty_table(teams),
        },
        "cup": {"next_gw": 10, "playoff": {"ties": []}, "rounds": []},
        "match_results": {},
        "player_tallies": [],
        "top_goalscorers": [],
        "top_assisters": [],
        "settings": settings or {},
    }


def create_tournament(
    name: str,
    team_names: list[str] | None,
    *,
    friendly_opponent: str = "Organ's XI",
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    teams = [x.strip() for x in (team_names or []) if x and x.strip()]
    if len(teams) != 10:
        raise ValueError(f"League + Cup requires exactly 10 teams, got {len(teams)}")
    if len(set(t.lower() for t in teams)) != 10:
        raise ValueError("Team names must be unique")
    clash = {t for t in teams if t.strip().lower() in _ADMIN_ONLY_TEAMS}
    if clash:
        raise ValueError(
            f"Admin-only team(s) cannot compete in the league/cup: {', '.join(sorted(clash))}"
        )
    t = _default_league_cup_tournament(name, teams, friendly_opponent.strip(), settings)
    tournament.save_tournament(t)
    # Round keys reuse league_cup:<fixture-id> across tournaments -- clear old
    # finalize locks so squads are editable for the new competition.
    clear_all_finalize_locks()
    return t


def delete_tournament(tournament_id: str) -> dict[str, Any]:
    return tournament.delete_tournament(tournament_id)


def get_tournament(tournament_id: str) -> dict[str, Any] | None:
    t = tournament.load_tournament(tournament_id)
    if t and t.get("format") != "league_cup":
        return None
    return t


def _require_league_cup(tournament_id: str) -> dict[str, Any]:
    t = tournament.load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    if t.get("format") != "league_cup":
        raise KeyError("Not a League + Cup tournament")
    return t


def tournament_for_api(t: dict[str, Any]) -> dict[str, Any]:
    from web import team_purse

    mrs = t.get("match_results") or {}
    league_defence = tournament.team_defence_board(t, competition="league")
    cup_defence = tournament.team_defence_board(t, competition="cup")
    return {
        **t,
        "match_results": {k: tournament.match_result_for_api(v) for k, v in mrs.items()},
        "league_boards": tournament.player_leaderboards(t, competition="league"),
        "cup_boards": tournament.player_leaderboards(t, competition="cup"),
        "league_team_ppda": tournament.team_ppda_board(t, competition="league"),
        "cup_team_ppda": tournament.team_ppda_board(t, competition="cup"),
        "league_team_least_goals_conceded": league_defence["least_goals_conceded"],
        "cup_team_least_goals_conceded": cup_defence["least_goals_conceded"],
        "league_team_least_xg_conceded": league_defence["least_xg_conceded"],
        "cup_team_least_xg_conceded": cup_defence["least_xg_conceded"],
        "purse": team_purse.purse_table_for_tournament(t),
    }


# ---------------------------------------------------------------------------
# Fixture lookup
# ---------------------------------------------------------------------------


def _find_playable(
    t: dict[str, Any], match_id: str
) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Returns (kind, fixture_or_leg, tie_or_none). kind in
    {"friendly", "league", "cup"}, or (None, None, None) if not found."""
    for fx in t["friendlies"]["fixtures"]:
        if fx["id"] == match_id:
            return "friendly", fx, None
    for fx in t["league"]["fixtures"]:
        if fx["id"] == match_id:
            return "league", fx, None
    for ti in t["cup"]["playoff"]["ties"]:
        for leg in ti.get("legs") or []:
            if leg["id"] == match_id:
                return "cup", leg, ti
    for rnd in t["cup"]["rounds"]:
        for ti in rnd["ties"]:
            for leg in ti.get("legs") or []:
                if leg["id"] == match_id:
                    return "cup", leg, ti
    return None, None, None


def _all_ties(t: dict[str, Any]) -> list[dict[str, Any]]:
    out = list(t["cup"]["playoff"]["ties"])
    for rnd in t["cup"]["rounds"]:
        out.extend(rnd["ties"])
    return out


# ---------------------------------------------------------------------------
# Immediate-round lookup (Squad Hub lineup-lock integration)
# ---------------------------------------------------------------------------


def _find_active_league_cup_for_team(team_name: str) -> dict[str, Any] | None:
    needle = team_name.strip().lower()
    candidates: list[dict[str, Any]] = []
    for summary in tournament.list_tournaments():
        t = tournament.load_tournament(summary["id"])
        if not t or t.get("format") != "league_cup" or t.get("status") != "active":
            continue
        names = [n.strip().lower() for n in t.get("team_names") or []]
        if needle in names:
            candidates.append(t)
    if not candidates:
        return None
    candidates.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return candidates[0]


def get_team_immediate_round(team_name: str, tournament: dict[str, Any] | None = None) -> dict[str, Any]:
    """Round context a team should finalize for -- earliest unplayed fixture
    across friendlies (first), then league + cup by scheduled gameweek."""
    try:
        t = tournament or _find_active_league_cup_for_team(team_name)
        if not t:
            return dict(_READY_ROUND)
        name = team_name.strip()

        for fx in t["friendlies"]["fixtures"]:
            if fx.get("played"):
                continue
            if name not in (fx.get("home"), fx.get("away")):
                continue
            return {
                "round_key": f"league_cup:{fx['id']}",
                "label": "Pre-season friendly",
                "tournament_id": t["id"],
                "tournament_name": t.get("name"),
            }

        candidates: list[tuple[int, str, str]] = []
        for fx in t["league"]["fixtures"]:
            if fx.get("played") or name not in (fx.get("home"), fx.get("away")):
                continue
            candidates.append((fx["scheduled_gw"], f"league_cup:{fx['id']}", f"League GW{fx['scheduled_gw']}"))
        for ti in _all_ties(t):
            for leg in ti.get("legs") or []:
                if leg.get("played") or name not in (leg.get("home"), leg.get("away")):
                    continue
                gw = ti.get("gw_leg1") if leg["leg"] == 1 else ti.get("gw_leg2")
                candidates.append((gw if gw is not None else 10**6, f"league_cup:{leg['id']}", "Cup"))

        if not candidates:
            return {
                "round_key": "ready",
                "label": "Awaiting next stage",
                "tournament_id": t.get("id"),
                "tournament_name": t.get("name"),
            }
        candidates.sort(key=lambda c: c[0])
        _, round_key, label = candidates[0]
        return {
            "round_key": round_key,
            "label": label,
            "tournament_id": t.get("id"),
            "tournament_name": t.get("name"),
        }
    except Exception as exc:
        print(f"league_cup: get_team_immediate_round({team_name!r}) failed, defaulting to ready: {exc}")
        return dict(_READY_ROUND)


# ---------------------------------------------------------------------------
# The scheduler (postponement pass)
# ---------------------------------------------------------------------------


def _unplayed_league_fixtures_at(t: dict[str, Any], gw: int) -> list[dict[str, Any]]:
    return [fx for fx in t["league"]["fixtures"] if not fx["played"] and fx["scheduled_gw"] == gw]


def _team_busy(t: dict[str, Any], team: str, gw: int) -> bool:
    for fx in t["league"]["fixtures"]:
        if fx["played"]:
            continue
        if fx["scheduled_gw"] == gw and team in (fx["home"], fx["away"]):
            return True
    for ti in _all_ties(t):
        if team in (ti.get("home"), ti.get("away")) and gw in (ti.get("gw_leg1"), ti.get("gw_leg2")):
            return True
    return False


def _postpone_for_cup_stage(t: dict[str, Any], blocked_teams: set[str], leg1_gw: int, leg2_gw: int) -> None:
    for target_gw in (leg1_gw, leg2_gw):
        fixtures = sorted(
            _unplayed_league_fixtures_at(t, target_gw),
            key=lambda f: (f["original_gw"], f["id"]),
        )
        for fx in fixtures:
            if fx["home"] not in blocked_teams and fx["away"] not in blocked_teams:
                continue
            candidate = target_gw + 1
            while _team_busy(t, fx["home"], candidate) or _team_busy(t, fx["away"], candidate):
                candidate += 1
            fx["postponements"].append(
                {"from_gw": fx["scheduled_gw"], "to_gw": candidate, "reason": "cup_clash", "at": _now()}
            )
            fx["scheduled_gw"] = candidate


# ---------------------------------------------------------------------------
# League table / playoff / cup progression
# ---------------------------------------------------------------------------


def _recompute_league_table(t: dict[str, Any]) -> None:
    table = tournament._empty_table(list(t["league"]["teams"]))
    for fx in sorted(t["league"]["fixtures"], key=lambda f: f["original_gw"]):
        if not fx.get("played"):
            continue
        tournament._apply_group_result(table, fx["home"], fx["away"], int(fx["home_goals"]), int(fx["away_goals"]))
    t["league"]["table"] = table


def _maybe_start_playoff(t: dict[str, Any]) -> None:
    if t["cup"]["playoff"]["ties"]:
        return
    first_leg = [fx for fx in t["league"]["fixtures"] if fx["original_gw"] <= 9]
    if not all(fx["played"] for fx in first_leg):
        return
    ranked = tournament._sort_standings(t["league"]["table"])
    r7, r8, r9, r10 = ranked[6], ranked[7], ranked[8], ranked[9]
    leg1_gw = t["cup"]["next_gw"]
    leg2_gw = leg1_gw + 1
    t["cup"]["next_gw"] = leg2_gw + 1
    tie1 = tournament._build_tie("po-1", r7, r8, None, True)
    tie2 = tournament._build_tie("po-2", r9, r10, None, True)
    tie1["gw_leg1"] = tie2["gw_leg1"] = leg1_gw
    tie1["gw_leg2"] = tie2["gw_leg2"] = leg2_gw
    t["cup"]["playoff"]["ties"] = [tie1, tie2]
    _postpone_for_cup_stage(t, {r7, r8, r9, r10}, leg1_gw, leg2_gw)


def draw_cup_round(tournament_id: str, *, seed: int | None = None) -> dict[str, Any]:
    """Admin action: random Round-of-8 draw once both playoff ties are decided."""
    t = _require_league_cup(tournament_id)
    if t["cup"]["rounds"]:
        raise ValueError("Cup bracket already drawn")
    ties = t["cup"]["playoff"]["ties"]
    if len(ties) != 2 or not all(ti.get("played") for ti in ties):
        raise ValueError("Both playoff ties must be completed before the cup draw")

    ranked = tournament._sort_standings(t["league"]["table"])
    top6 = ranked[:6]
    playoff_winners = [ti["winner"] for ti in ties]
    field = top6 + playoff_winners

    rng = random.Random(seed)
    pool = field[:]
    rng.shuffle(pool)
    pairs = [(pool[i], pool[i + 1]) for i in range(0, 8, 2)]

    r8_ties = [tournament._build_tie(f"cup-r8-{i}", h, a, None, True) for i, (h, a) in enumerate(pairs, start=1)]
    rounds_out = [{"name": "R8", "label": "Round of 8", "ties": r8_ties}]
    prev_ids = [ti["id"] for ti in r8_ties]
    for rname, rlabel in (("SF", "Semi-finals"), ("Final", "Final")):
        next_ties = []
        for j in range(0, len(prev_ids), 2):
            feeds = prev_ids[j : j + 2]
            tie_id = f"cup-{rname.lower()}-{j // 2 + 1}"
            next_ties.append(tournament._build_tie(tie_id, None, None, feeds, True))
        rounds_out.append({"name": rname, "label": rlabel, "ties": next_ties})
        prev_ids = [ti["id"] for ti in next_ties]

    t["cup"]["rounds"] = rounds_out
    leg1_gw = t["cup"]["next_gw"]
    leg2_gw = leg1_gw + 1
    t["cup"]["next_gw"] = leg2_gw + 1
    blocked: set[str] = set()
    for ti in r8_ties:
        ti["gw_leg1"] = leg1_gw
        ti["gw_leg2"] = leg2_gw
        blocked.add(ti["home"])
        blocked.add(ti["away"])
    _postpone_for_cup_stage(t, blocked, leg1_gw, leg2_gw)
    tournament.save_tournament(t)
    return t


def _advance_cup_stage(t: dict[str, Any], tie: dict[str, Any], winner: str) -> None:
    tie_id = tie["id"]
    for rnd in t["cup"]["rounds"]:
        for nxt in rnd["ties"]:
            feeds = nxt.get("feeds") or []
            if tie_id not in feeds:
                continue
            idx = feeds.index(tie_id)
            if idx == 0:
                nxt["home"] = winner
            else:
                nxt["away"] = winner
            tournament._sync_tie_legs(nxt)

    # Whichever round just became fully paired (every tie has both a home
    # and away team) and hasn't been gw-assigned yet gets its leg weeks now
    # -- at most one round can newly qualify per call, since a round only
    # becomes fully paired once its entire previous round is complete.
    for rnd in t["cup"]["rounds"]:
        ties = rnd["ties"]
        if not ties or ties[0].get("gw_leg1") is not None:
            continue
        if not all(ti.get("home") and ti.get("away") for ti in ties):
            continue
        leg1_gw = t["cup"]["next_gw"]
        leg2_gw = leg1_gw + 1
        t["cup"]["next_gw"] = leg2_gw + 1
        blocked: set[str] = set()
        for ti in ties:
            ti["gw_leg1"] = leg1_gw
            ti["gw_leg2"] = leg2_gw
            blocked.add(ti["home"])
            blocked.add(ti["away"])
        _postpone_for_cup_stage(t, blocked, leg1_gw, leg2_gw)
        break


def _maybe_complete_tournament(t: dict[str, Any]) -> None:
    all_league_played = all(fx["played"] for fx in t["league"]["fixtures"])
    rounds = t["cup"]["rounds"]
    cup_done = bool(rounds) and all(ti.get("played") for ti in rounds[-1]["ties"])
    if all_league_played and cup_done:
        t["status"] = "complete"


# ---------------------------------------------------------------------------
# Tie-leg outcome resolution (two-legged only -- every League+Cup knockout
# tie, including the Final, is two-legged per spec, unlike the legacy
# groups+knockout format which allows single-match rounds)
# ---------------------------------------------------------------------------


def _resolve_tie_leg(
    tie: dict[str, Any],
    leg: dict[str, Any],
    home_goals: int,
    away_goals: int,
    winner: str | None,
    decided: str | None,
    ph: int | None,
    pa: int | None,
    ft_h: int | None,
    ft_a: int | None,
) -> tuple[str | None, str | None, str | None, str | None, int | None, int | None]:
    """Returns (winner_this_leg, decided_this_leg, tie_winner, tie_decided, agg_home, agg_away)."""
    home, away = leg["home"], leg["away"]
    if leg["leg"] == 1:
        return None, None, None, None, None, None

    leg1 = tie["legs"][0]
    if not leg1.get("played"):
        raise ValueError("Leg 1 has not been played yet")
    leg1_home_goals = int(leg1["home_goals"])
    leg1_away_goals = int(leg1["away_goals"])
    agg_home_goals = leg1_home_goals + int(away_goals)
    agg_away_goals = leg1_away_goals + int(home_goals)

    if agg_home_goals != agg_away_goals:
        tie_winner = tie["home"] if agg_home_goals > agg_away_goals else tie["away"]
        tie_decided = "agg"
    else:
        tie_home_away_goals = int(away_goals)
        tie_away_away_goals = leg1_away_goals
        if tie_home_away_goals != tie_away_away_goals:
            tie_winner = tie["home"] if tie_home_away_goals > tie_away_away_goals else tie["away"]
            tie_decided = "away_goals"
        elif decided == "pens" and ph is not None and pa is not None:
            if ph == pa:
                raise ValueError("Penalty shoot-out must have a winner")
            tie_winner = home if ph > pa else away
            tie_decided = "pens"
        elif winner in (home, away):
            tie_decided = "pens" if ph is not None and pa is not None else "aet"
            tie_winner = winner
        else:
            tie_winner = home
            tie_decided = "pens" if ph is not None else "aet"

    if not decided:
        decided = "aet" if (ft_h is not None and ft_a is not None and (ft_h != home_goals or ft_a != away_goals)) else "ft"
    winner_this_leg = tie_winner if tie_winner in (home, away) else None
    return winner_this_leg, decided, tie_winner, tie_decided, agg_home_goals, agg_away_goals


# ---------------------------------------------------------------------------
# Match execution
# ---------------------------------------------------------------------------


def prepare_board_match(tournament_id: str, match_id: str) -> dict[str, Any]:
    t = _require_league_cup(tournament_id)
    kind, fx, tie = _find_playable(t, match_id)
    if fx is None:
        raise KeyError(f"Fixture '{match_id}' not found")
    if fx.get("played"):
        raise ValueError(f"Match {match_id} already played")
    if kind == "cup" and (not fx.get("home") or not fx.get("away")):
        raise ValueError(f"Match {match_id} is not ready (missing teams)")

    leg_context: dict[str, Any] | None = None
    if kind == "cup":
        leg_context = {"leg": fx["leg"], "twoLegged": True}
        if fx["leg"] == 2:
            leg1 = tie["legs"][0]
            if not leg1.get("played"):
                raise ValueError("Leg 1 has not been played yet")
            leg_context["enteringAggHome"] = int(leg1["away_goals"])
            leg_context["enteringAggAway"] = int(leg1["home_goals"])

    home, away = fx["home"], fx["away"]
    team_a, team_b = tournament._load_teams_for_match(home, away)
    tournament._preflight_match_stats(team_a, team_b)
    store = get_stats_store()
    player_stats, _season_overrides, name_map = prepare_match_player_stats(team_a, team_b, store, cache_only=True)
    resolved = _apply_name_map({"team_a": team_a, "team_b": team_b}, name_map)
    home_team = FantasyTeam.from_dict(resolved["team_a"])
    away_team = FantasyTeam.from_dict(resolved["team_b"])
    home_payload = tournament._board_side_payload(home_team, player_stats)
    away_payload = tournament._board_side_payload(away_team, player_stats)
    board = {
        "match_id": match_id,
        "home": home_payload,
        "away": away_payload,
        "unit_home": home_payload.get("_unit") or {},
        "unit_away": away_payload.get("_unit") or {},
    }
    seed = abs(hash(f"{tournament_id}:{match_id}")) % (2**31)
    is_final = bool(
        kind == "cup"
        and t["cup"]["rounds"]
        and any(ti["id"] == tie["id"] for ti in t["cup"]["rounds"][-1]["ties"])
    )
    status = matchday_session.start_board_session(
        tournament_id=tournament_id,
        tournament_name=t.get("name") or "League",
        fixture_id=match_id,
        stage=kind,
        home=home,
        away=away,
        team_a=home_payload,
        team_b=away_payload,
        board=board,
        seed=seed,
        is_knockout=(kind == "cup"),
        is_league=(kind == "league"),
        is_final=is_final,
        agg_context=leg_context,
    )
    return {
        "status": "board_ready",
        "engine": "tactic_board",
        "redirect": "/matchday",
        "tournament_id": tournament_id,
        "match_id": match_id,
        "stage": kind,
        "is_knockout": kind == "cup",
        "home": home,
        "away": away,
        "board": board,
        "matchday": status,
        "tournament": {"id": t["id"], "name": t.get("name"), "status": t.get("status")},
    }


def complete_from_board(
    tournament_id: str,
    match_id: str,
    home_goals: int,
    away_goals: int,
    winner: str | None = None,
    board_events: list[dict[str, Any]] | None = None,
    match_log: list[dict[str, Any]] | dict[str, Any] | None = None,
    *,
    decided_by: str | None = None,
    ft_home_goals: int | None = None,
    ft_away_goals: int | None = None,
    pens_home: int | None = None,
    pens_away: int | None = None,
    score_display: str | None = None,
) -> dict[str, Any]:
    if home_goals < 0 or away_goals < 0:
        raise ValueError("Goals must be non-negative")

    t = _require_league_cup(tournament_id)
    kind, fx, tie = _find_playable(t, match_id)
    if fx is None:
        raise KeyError(f"Fixture '{match_id}' not found")
    if fx.get("played"):
        raise ValueError(f"Match {match_id} already played")
    if kind == "cup" and (not fx.get("home") or not fx.get("away")):
        raise ValueError(f"Match {match_id} is not ready (missing teams)")

    home, away = fx["home"], fx["away"]
    decided = (decided_by or "").strip().lower() or None
    if decided not in (None, "ft", "aet", "pens"):
        decided = None
    ph = int(pens_home) if pens_home is not None else None
    pa = int(pens_away) if pens_away is not None else None
    ft_h = int(ft_home_goals) if ft_home_goals is not None else None
    ft_a = int(ft_away_goals) if ft_away_goals is not None else None
    if winner is not None:
        winner = str(winner).strip()
        if winner and winner not in (home, away):
            raise ValueError(f"Winner must be '{home}' or '{away}'")

    tie_winner: str | None = None
    tie_decided: str | None = None
    agg_home_goals: int | None = None
    agg_away_goals: int | None = None

    if kind == "cup":
        if fx["leg"] == 1:
            winner = None
            decided = None
            ph = pa = None
            ft_h = ft_a = None
        else:
            winner, decided, tie_winner, tie_decided, agg_home_goals, agg_away_goals = _resolve_tie_leg(
                tie, fx, home_goals, away_goals, winner, decided, ph, pa, ft_h, ft_a
            )
    else:
        if home_goals > away_goals:
            winner = home
        elif away_goals > home_goals:
            winner = away
        else:
            winner = None
        decided = None

    stored_events: list[dict[str, Any]] | None = None
    stored_log: dict[str, Any] | list[dict[str, Any]] | None = None
    if isinstance(board_events, list) and board_events:
        stored_events = [e for e in board_events if isinstance(e, dict)]
    if isinstance(match_log, dict) and match_log:
        stored_log = match_log
        if not stored_events and isinstance(match_log.get("events"), list):
            stored_events = [e for e in match_log["events"] if isinstance(e, dict)]
    elif isinstance(match_log, list) and match_log:
        stored_events = stored_events or [e for e in match_log if isinstance(e, dict)]
        stored_log = {"events": stored_events, "goals": [e for e in stored_events if e.get("type") == "goal"]}

    if kind == "cup":
        score = tournament._format_knockout_score(
            home_goals, away_goals, decided_by=decided, pens_home=ph, pens_away=pa, score_display=None
        )
    else:
        score = f"{home_goals}-{away_goals}"

    result_id = match_id
    result: dict[str, Any] = {
        "match_id": match_id,
        "competition": kind,
        "stage": kind,
        "home": home,
        "away": away,
        "score": score,
        "home_goals": int(home_goals),
        "away_goals": int(away_goals),
        "engine": "tactic_board",
        "engine_home_goals": int(home_goals),
        "engine_away_goals": int(away_goals),
        "winner": winner,
        "manually_overridden": False,
        "admin_accepted": True,
        "admin_reviewed_at": _now(),
        "played_at": _now(),
        "simulations": 0,
    }
    if kind == "cup":
        result["tie_id"] = tie["id"]
        result["leg"] = fx["leg"]
        if decided:
            result["decided_by"] = decided
    if ft_h is not None and ft_a is not None:
        result["ft_home_goals"] = ft_h
        result["ft_away_goals"] = ft_a
    if decided == "pens" and ph is not None and pa is not None:
        result["pens_home"] = ph
        result["pens_away"] = pa
    if stored_events:
        result["board_events"] = stored_events
    if stored_log is not None:
        result["match_log"] = stored_log
        if isinstance(stored_log, dict):
            # Season-diagnostics project -- league_cup.py never had
            # tournament.py's expected_xg/possession_pct promotion at all
            # (confirmed: only ppda was here before), which would have left
            # League+Cup teams' season stats missing xG for/against and
            # possession entirely. Added alongside team_stats below.
            live_xg = stored_log.get("xg") or stored_log.get("live_xg")
            if isinstance(live_xg, dict) and (
                live_xg.get("home") is not None or live_xg.get("away") is not None
            ):
                result["expected_xg"] = {
                    "home": round(float(live_xg.get("home") or 0), 2),
                    "away": round(float(live_xg.get("away") or 0), 2),
                }
            poss = stored_log.get("possession_pct") or stored_log.get("possession")
            if isinstance(poss, dict):
                result["possession_pct"] = {
                    "home": round(float(poss.get("home") or 0), 1),
                    "away": round(float(poss.get("away") or 0), 1),
                }
            counts = stored_log.get("counts")
            if isinstance(counts, dict):
                home_counts = counts.get("home") or {}
                away_counts = counts.get("away") or {}
                home_actions = home_counts.get("ppda_actions") or 0
                away_actions = away_counts.get("ppda_actions") or 0
                home_opp_passes = away_counts.get("ppda_passes") or 0
                away_opp_passes = home_counts.get("ppda_passes") or 0
                if home_actions or away_actions:
                    result["ppda"] = {
                        "home": {
                            "value": round(home_opp_passes / home_actions, 1) if home_actions else None,
                            "opp_passes": home_opp_passes,
                            "own_actions": home_actions,
                        },
                        "away": {
                            "value": round(away_opp_passes / away_actions, 1) if away_actions else None,
                            "opp_passes": away_opp_passes,
                            "own_actions": away_actions,
                        },
                    }
                # Season-diagnostics project -- same team_stats promotion
                # as tournament.py's complete_from_board.
                result["team_stats"] = {
                    side: {
                        "shots": bucket.get("shots") or 0,
                        "shots_on_target": bucket.get("shots_on_target") or 0,
                        "big_chances": bucket.get("big_chances") or 0,
                        "big_chance_goals": bucket.get("big_chance_goals") or 0,
                        "passes_attempted": bucket.get("passes_attempted") or 0,
                        "passes_completed": bucket.get("passes_completed") or 0,
                        "progressive_passes": bucket.get("progressive_passes") or 0,
                    }
                    for side, bucket in (("home", home_counts), ("away", away_counts))
                }
                # Analysis-dashboard project -- same zone_breakdown
                # promotion as tournament.py's complete_from_board.
                zone_totals = {
                    "home": {"left": 0, "central": 0, "right": 0},
                    "away": {"left": 0, "central": 0, "right": 0},
                }
                for ev in stored_log.get("events") or []:
                    if not isinstance(ev, dict) or ev.get("type") not in ("shot", "big_chance"):
                        continue
                    ev_side = ev.get("side")
                    ev_zone = ev.get("zone")
                    if ev_side in zone_totals and ev_zone in zone_totals[ev_side]:
                        zone_totals[ev_side][ev_zone] += 1
                result["zone_breakdown"] = zone_totals
    elif stored_events:
        result["match_log"] = {"events": stored_events, "goals": [e for e in stored_events if e.get("type") == "goal"]}

    tournament._attach_ai_commentary(result)

    t["match_results"][result_id] = result
    fx["played"] = True
    fx["result_id"] = result_id
    fx["score"] = score
    fx["home_goals"] = int(home_goals)
    fx["away_goals"] = int(away_goals)
    if kind == "cup" and decided and fx["leg"] != 1:
        fx["decided_by"] = decided

    if kind == "league":
        tournament._apply_group_result(t["league"]["table"], home, away, int(home_goals), int(away_goals))
        _maybe_start_playoff(t)
    elif kind == "cup" and tie_winner is not None:
        tie["played"] = True
        tie["result_id"] = result_id
        tie["winner"] = tie_winner
        tie["decided_by"] = tie_decided
        tie["agg_home_goals"] = agg_home_goals
        tie["agg_away_goals"] = agg_away_goals
        if tie_decided == "pens" and ph is not None and pa is not None:
            tie["pens_home"] = ph
            tie["pens_away"] = pa
        tie["score"] = tournament._format_tie_score(tie)
        _advance_cup_stage(t, tie, tie_winner)

    _maybe_complete_tournament(t)
    tournament.save_tournament(t)
    matchday_session.set_result(result)
    return {"tournament": t, "result": result}


# ---------------------------------------------------------------------------
# Admin correction
# ---------------------------------------------------------------------------


def _cup_downstream_played(t: dict[str, Any], tie_id: str) -> bool:
    for rnd in t["cup"]["rounds"]:
        for nxt in rnd["ties"]:
            if tie_id in (nxt.get("feeds") or []) and nxt.get("played"):
                return True
    return False


def reset_match_result(tournament_id: str, match_id: str) -> dict[str, Any]:
    """Admin: un-play a match, reversing its table/tie/tally contribution."""
    t = _require_league_cup(tournament_id)
    kind, fx, tie = _find_playable(t, match_id)
    if fx is None:
        raise KeyError(f"Fixture '{match_id}' not found")
    if not fx.get("played"):
        raise ValueError(f"Match {match_id} has not been played yet")
    if kind == "league" and fx["original_gw"] <= 9 and t["cup"]["playoff"]["ties"]:
        raise ValueError("Cannot reset a first-half league match after the playoff has started")
    if kind == "cup" and tie.get("played") and _cup_downstream_played(t, tie["id"]):
        raise ValueError("Cannot reset: a later cup round already used this tie's winner")

    result_id = fx.get("result_id")
    if result_id and result_id in t["match_results"]:
        del t["match_results"][result_id]
    fx["played"] = False
    fx["result_id"] = None
    fx["score"] = None
    fx["home_goals"] = None
    fx["away_goals"] = None
    fx.pop("decided_by", None)

    if kind == "league":
        _recompute_league_table(t)
    elif kind == "cup" and tie.get("played") and fx["leg"] == 2:
        tie["played"] = False
        tie["winner"] = None
        tie["result_id"] = None
        tie["decided_by"] = None
        tie["score"] = None
        tie.pop("agg_home_goals", None)
        tie.pop("agg_away_goals", None)
        tie.pop("pens_home", None)
        tie.pop("pens_away", None)

    if t.get("status") == "complete":
        t["status"] = "active"
    tournament.save_tournament(t)
    return {"tournament": t}


# ---------------------------------------------------------------------------
# Deterministic match analysis (league/cup matches only -- friendlies stay
# commentary-only, see _load_played_match_result below). This reuses
# tournament.py's own analysis machinery almost entirely as-is:
# _build_and_attach_board_analysis is already format-agnostic (it only
# touches `result`/team payloads, never t["groups"]/t["knockout"]), and the
# job-tracking dict/lock/response-shape helpers are pure enough to share
# directly rather than duplicate. Only the fixture lookup differs.
# ---------------------------------------------------------------------------


def _load_played_match_result(
    tournament_id: str, match_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return (t, fixture, result) for a completed league/cup match."""
    t = _require_league_cup(tournament_id)
    kind, fx, _tie = _find_playable(t, match_id)
    if fx is None:
        raise KeyError(f"Fixture '{match_id}' not found")
    if kind == "friendly":
        raise ValueError("Friendlies don't have a deterministic analysis report -- commentary only.")
    if not fx.get("played"):
        raise ValueError(f"Match {match_id} has not been played yet")
    result_id = fx.get("result_id") or match_id
    result = (t.get("match_results") or {}).get(result_id)
    if not result:
        raise KeyError(f"Result for '{match_id}' not found")
    return t, fx, result


def _build_and_persist_match_analysis(
    tournament_id: str,
    match_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """CPU-heavy build + disk persist. Run only from a background thread."""
    t, _fx, result = _load_played_match_result(tournament_id, match_id)
    if result.get("engine") == "tactic_board":
        if force or tournament._analysis_needs_rebuild(result):
            tournament._build_and_attach_board_analysis(t, result, tournament_id=tournament_id, match_id=match_id)
            result["fit_formula_version"] = tournament._FIT_FORMULA_VERSION
            tournament.save_tournament(t)
        return tournament._analysis_response(result, match_id)
    if tournament._result_has_analysis(result):
        return tournament._analysis_response(result, match_id)
    raise ValueError(f"Match {match_id} has no stored analysis to show.")


def _start_analysis_job(
    tournament_id: str,
    match_id: str,
    result: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Start (or join) a background analysis build; return generating/error payload.

    Shares tournament.py's global `_analysis_jobs` dict/lock -- job keys are
    `f"{tournament_id}:{match_id}"`, and tournament ids are unique across
    both formats, so there's no real collision risk from sharing it rather
    than keeping a second, parallel job registry.
    """
    key = tournament._analysis_job_key(tournament_id, match_id)
    with tournament._analysis_jobs_lock:
        job = tournament._analysis_jobs.get(key)
        if job and job.get("status") == "generating":
            return tournament._generating_analysis_response(result, match_id)
        if job and job.get("status") == "error" and not force:
            message = str(job.get("error") or "Analysis generation failed")
            tournament._analysis_jobs.pop(key, None)
            return tournament._error_analysis_response(result, match_id, message)
        tournament._analysis_jobs[key] = {
            "status": "generating",
            "force": force,
            "started_at": _now(),
            "error": None,
        }

    def _job() -> None:
        try:
            _build_and_persist_match_analysis(tournament_id, match_id, force=force)
            with tournament._analysis_jobs_lock:
                tournament._analysis_jobs[key] = {"status": "ready", "finished_at": _now(), "error": None}
        except Exception as exc:
            with tournament._analysis_jobs_lock:
                tournament._analysis_jobs[key] = {"status": "error", "finished_at": _now(), "error": str(exc)}

    threading.Thread(target=_job, daemon=True, name=f"lc-analysis-{key}").start()
    return tournament._generating_analysis_response(result, match_id)


def get_match_analysis(tournament_id: str, match_id: str) -> dict[str, Any]:
    """Return persisted analysis, or start a background build (status=generating)."""
    _t, _fx, result = _load_played_match_result(tournament_id, match_id)

    key = tournament._analysis_job_key(tournament_id, match_id)
    with tournament._analysis_jobs_lock:
        job = dict(tournament._analysis_jobs.get(key) or {})

    if job.get("status") == "generating":
        if tournament._result_has_analysis(result):
            return tournament._analysis_response(result, match_id)
        return tournament._generating_analysis_response(result, match_id)

    if job.get("status") == "error":
        message = str(job.get("error") or "Analysis generation failed")
        with tournament._analysis_jobs_lock:
            tournament._analysis_jobs.pop(key, None)
        if tournament._result_has_analysis(result):
            return tournament._analysis_response(result, match_id)
        return tournament._error_analysis_response(result, match_id, message)

    if job.get("status") == "ready":
        with tournament._analysis_jobs_lock:
            tournament._analysis_jobs.pop(key, None)
        # Reload -- worker persisted to disk after the in-memory snapshot above.
        _t, _fx, result = _load_played_match_result(tournament_id, match_id)

    if tournament._result_has_analysis(result) and not tournament._analysis_needs_rebuild(result):
        return tournament._analysis_response(result, match_id)

    if tournament._result_has_analysis(result) and tournament._analysis_needs_rebuild(result):
        _start_analysis_job(tournament_id, match_id, result, force=False)
        return tournament._analysis_response(result, match_id)

    return _start_analysis_job(tournament_id, match_id, result, force=False)


def generate_match_analysis(tournament_id: str, match_id: str) -> dict[str, Any]:
    """Admin backfill: start a background rebuild (does not change the score)."""
    _t, _fx, result = _load_played_match_result(tournament_id, match_id)
    return _start_analysis_job(tournament_id, match_id, result, force=True)
