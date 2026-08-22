"""Squad evaluation and limited opponent scouting without running simulations."""
from __future__ import annotations

import copy
import time
from typing import Any

from analysis_explainer import analyze_team_squad, build_scout_report
from bench_impact import bench_impact_for_team
from models import FantasyTeam
from report_builder import (
    extended_metrics,
    fullback_profile,
    team_payload_dict,
)
from stats_resolver import prepare_team_player_stats
from team_ratings import compute_team_composites, compute_unit_ratings_by_slot, team_composites_dict
from web.team_lineups import apply_saved_lineup

# Unit/team-composite keys benchmarked against the rest of the league.
# (label, key, higher_better) -- mirrors the pairs analysis_explainer.py
# already walks for tiering, so percentile and absolute-threshold tiering
# stay in sync about which metrics get a percentile at all.
_LEAGUE_UNIT_KEYS: tuple[tuple[str, bool], ...] = (
    ("attack", True),
    ("finishing", True),
    ("chance_creation", True),
    ("midfield", True),
    ("defence", True),
    ("midfield_defence", True),
    ("transition_risk", False),
    ("goalkeeper", True),
)
_LEAGUE_COMPOSITE_KEYS: tuple[str, ...] = (
    "creativity",
    "midfield_control",
    "possession_control",
    "finishing_threat",
    "defensive_solidity",
    "attacking_effectiveness",
    "pressing_intensity",
    "press_resistance",
    "transition_threat",
    "aerial_defence",
)

_LEAGUE_SNAPSHOT_CACHE: dict[str, Any] = {"at": 0.0, "data": {}}
_LEAGUE_SNAPSHOT_TTL_S = 300.0  # benchmark field refreshes at most every 5 min


def _apply_name_map(team: dict[str, Any], name_map: dict[str, str]) -> dict[str, Any]:
    out = copy.deepcopy(team)
    for row in out.get("lineup", []):
        raw = row.get("player", "")
        if raw in name_map:
            row["player"] = name_map[raw]
    for i, bp in enumerate(out.get("bench") or []):
        if bp in name_map:
            out["bench"][i] = name_map[bp]
    meta = out.get("sheet_meta") or {}
    if meta.get("full_roster"):
        meta["full_roster"] = [name_map.get(p, p) for p in meta["full_roster"]]
    if meta.get("bench_players"):
        meta["bench_players"] = [name_map.get(p, p) for p in meta["bench_players"]]
    if meta.get("roster_players"):
        meta["roster_players"] = [name_map.get(p, p) for p in meta["roster_players"]]
    out["sheet_meta"] = meta
    return out


def _ratings_only(fantasy: FantasyTeam, player_stats: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Units + team composites, skipping the narrative/bench pipeline.

    Used for the league-wide benchmark field and the what-if comparator,
    where only the numbers are needed -- running the full
    build_squad_evaluation per team (bench impact, formation fit text,
    tier phrasing) for every squad in the tournament would be wasted work.
    """
    units = compute_unit_ratings_by_slot(fantasy, player_stats)
    composites = compute_team_composites(fantasy, player_stats, units=units)
    units_dict = {
        "attack": units.attack,
        "finishing": units.finishing,
        "chance_creation": units.chance_creation,
        "midfield": units.midfield,
        "defence": units.defence,
        "midfield_defence": units.midfield_defence,
        "transition_risk": units.transition_risk,
        "goalkeeper": units.goalkeeper,
        "overall": units.overall,
    }
    return units_dict, team_composites_dict(composites)


def compute_league_snapshot(store: Any, *, force: bool = False) -> dict[str, dict[str, Any]]:
    """Units + team composites for every roster-ready sheet team.

    Best-effort and cached (5 min TTL): a team that fails to resolve
    (incomplete roster, no cached stats for its players) is silently
    skipped rather than failing the whole snapshot -- one broken squad
    elsewhere in the sheet shouldn't take down everyone else's benchmark.
    """
    now = time.time()
    if not force and now - _LEAGUE_SNAPSHOT_CACHE["at"] < _LEAGUE_SNAPSHOT_TTL_S:
        return _LEAGUE_SNAPSHOT_CACHE["data"]

    from google_sheets_teams import list_sheet_teams, load_team_by_name

    snapshot: dict[str, dict[str, Any]] = {}
    try:
        teams = list_sheet_teams()
    except Exception:
        return _LEAGUE_SNAPSHOT_CACHE["data"] or snapshot

    for t in teams:
        name = t.get("name")
        if not name or not t.get("ready"):
            continue
        try:
            team_dict = load_team_by_name(name, store=store)
            team_dict = apply_saved_lineup(team_dict)
            player_stats, name_map = prepare_team_player_stats(team_dict, store, cache_only=True)
            resolved = _apply_name_map(team_dict, name_map)
            fantasy = FantasyTeam.from_dict(resolved)
            units_dict, composites_dict = _ratings_only(fantasy, player_stats)
            snapshot[name] = {"units": units_dict, "team_composites": composites_dict}
        except Exception:
            continue

    _LEAGUE_SNAPSHOT_CACHE["at"] = now
    _LEAGUE_SNAPSHOT_CACHE["data"] = snapshot
    return snapshot


def _percentile_rank(value: float, population: list[float], *, higher_better: bool = True) -> float:
    """0-100: what share of the league this value is at or ahead of (self included)."""
    if not population:
        return 50.0
    if higher_better:
        rank = sum(1 for v in population if v <= value)
    else:
        rank = sum(1 for v in population if v >= value)
    return round(100.0 * rank / len(population), 1)


def compute_percentiles(
    units: dict[str, Any], team_composites: dict[str, Any], snapshot: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """This team's percentile rank vs. the league snapshot, per unit/composite key."""
    if not snapshot:
        return {}
    percentiles: dict[str, float] = {}
    for key, higher_better in _LEAGUE_UNIT_KEYS:
        pop = [s["units"][key] for s in snapshot.values() if key in s.get("units", {})]
        val = units.get(key)
        if val is None or not pop:
            continue
        percentiles[key] = _percentile_rank(float(val), pop, higher_better=higher_better)
    for key in _LEAGUE_COMPOSITE_KEYS:
        pop = [s["team_composites"][key] for s in snapshot.values() if key in s.get("team_composites", {})]
        val = team_composites.get(key)
        if val is None or not pop:
            continue
        percentiles[key] = _percentile_rank(float(val), pop, higher_better=True)
    return {"by_key": percentiles, "league_size": len(snapshot)}


def build_squad_evaluation(
    team_dict: dict[str, Any],
    store: Any,
    *,
    use_saved_lineup: bool = True,
    benchmark: bool = True,
) -> dict[str, Any]:
    """Full squad strengths/weaknesses for one team using saved lineup when available."""
    if use_saved_lineup:
        team_dict = apply_saved_lineup(team_dict)
    player_stats, name_map = prepare_team_player_stats(team_dict, store, cache_only=True)
    resolved = _apply_name_map(team_dict, name_map)
    fantasy = FantasyTeam.from_dict(resolved)
    profile = {
        "extended": extended_metrics(fantasy, player_stats),
        "fullbacks": fullback_profile(fantasy, player_stats),
    }
    starting_xi = [slot.player for slot in fantasy.lineup if slot.player]
    bench = bench_impact_for_team(fantasy.name, starting_xi, [], fantasy.bench, player_stats)

    percentiles: dict[str, Any] = {}
    if benchmark:
        try:
            snapshot = compute_league_snapshot(store)
            percentiles = compute_percentiles(
                profile["extended"]["units"], profile["extended"]["team_composites"], snapshot
            )
        except Exception:
            percentiles = {}

    evaluation = analyze_team_squad(fantasy.name, fantasy.formation, profile, bench, percentiles=percentiles)
    return {
        "team": team_payload_dict(resolved),
        "evaluation": evaluation,
    }


def build_opponent_scout(
    my_team_dict: dict[str, Any],
    opponent_team_dict: dict[str, Any],
    store: Any,
) -> dict[str, Any]:
    """Limited scout report comparing opponent to your squad."""
    my_bundle = build_squad_evaluation(my_team_dict, store)
    opp_bundle = build_squad_evaluation(opponent_team_dict, store)
    return build_scout_report(
        my_bundle["evaluation"],
        opp_bundle["evaluation"],
        my_team=my_bundle["team"],
        opponent_team=opp_bundle["team"],
    )


def simulate_lineup_swap(
    team_dict: dict[str, Any],
    store: Any,
    *,
    slot: str,
    new_player: str,
) -> dict[str, Any]:
    """Units/team-composite deltas from swapping one player into one slot.

    Compares the saved lineup against a hypothetical one-slot substitution
    (e.g. a bench player replacing a starter) -- both computed through the
    same rating engine, so the deltas are apples-to-apples.
    """
    base_dict = apply_saved_lineup(copy.deepcopy(team_dict))
    swapped_dict = copy.deepcopy(base_dict)
    out_player = None
    found = False
    for row in swapped_dict.get("lineup", []):
        if row.get("slot") == slot:
            out_player = row.get("player")
            row["player"] = new_player
            found = True
            break
    if not found:
        raise ValueError(f"Slot '{slot}' not found in this team's lineup.")
    if out_player == new_player:
        raise ValueError(f"{new_player} is already in slot {slot}.")

    def _rate(td: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        player_stats, name_map = prepare_team_player_stats(td, store, cache_only=True)
        resolved = _apply_name_map(td, name_map)
        fantasy = FantasyTeam.from_dict(resolved)
        return _ratings_only(fantasy, player_stats)

    base_units, base_composites = _rate(base_dict)
    new_units, new_composites = _rate(swapped_dict)

    def _deltas(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, b in before.items():
            if not isinstance(b, (int, float)):
                continue
            a = float(after.get(key, 0))
            out[key] = {"before": round(float(b), 3), "after": round(a, 3), "delta": round(a - float(b), 3)}
        return out

    return {
        "slot": slot,
        "out_player": out_player,
        "in_player": new_player,
        "units": _deltas(base_units, new_units),
        "team_composites": _deltas(base_composites, new_composites),
    }
