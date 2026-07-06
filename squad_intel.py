"""Squad evaluation and limited opponent scouting without running simulations."""
from __future__ import annotations

import copy
from typing import Any

from analysis_explainer import analyze_team_squad, build_scout_report
from models import FantasyTeam
from report_builder import (
    _bench_impact_side,
    extended_metrics,
    fullback_profile,
    team_payload_dict,
)
from stats_resolver import prepare_team_player_stats
from web.team_lineups import apply_saved_lineup


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


def build_squad_evaluation(
    team_dict: dict[str, Any],
    store: Any,
    *,
    use_saved_lineup: bool = True,
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
    bench = _bench_impact_side(fantasy, player_stats)
    evaluation = analyze_team_squad(fantasy.name, fantasy.formation, profile, bench)
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
