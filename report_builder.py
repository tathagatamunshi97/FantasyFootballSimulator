"""Build JSON-serializable matchup reports for CLI and web."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench_impact import bench_impact_for_team
from analysis_explainer import (
    build_matchup_analysis,
    build_squad_strengths_report,
    enrich_analysis_with_board_result,
    normalize_board_events,
)
from formation_fit import player_slot_fit, team_formation_fit
from match_engine import MatchSimConfig, monte_carlo_matches, simulate_match_once
from models import FantasyTeam, PlayerStats
from slot_roles import FULLBACK_SLOTS, slot_role
from team_profile import build_team_profile
from team_ratings import (
    UnitRatings,
    attack_to_xg,
    combined_attack_xg,
    compute_team_composites,
    compute_unit_ratings,
    compute_unit_ratings_by_slot,
    compute_wide_matchup_modifier,
    creation_to_xg,
    defence_suppression,
    midfield_battle_multiplier,
    team_composites_dict,
    _fullback_attack_exposure,
    _player_chance_creation_contrib,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_MATCHUP = DATA_DIR / "team_a_vs_b.json"


def load_matchup(path: Path | None = None) -> tuple[FantasyTeam, FantasyTeam]:
    p = path or DEFAULT_MATCHUP
    data = json.loads(p.read_text(encoding="utf-8"))
    return FantasyTeam.from_dict(data["home"]), FantasyTeam.from_dict(data["away"])


def _units_dict(u: UnitRatings) -> dict[str, float | bool]:
    return {
        "attack": u.attack,
        "finishing": u.finishing,
        "chance_creation": u.chance_creation,
        "midfield": u.midfield,
        "defence": u.defence,
        "midfield_defence": u.midfield_defence,
        "transition_risk": u.transition_risk,
        "goalkeeper": u.goalkeeper,
        "overall": u.overall,
        "gk_confidence": u.gk_confidence,
        "gk_is_backup": u.gk_is_backup,
    }


def _avg(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _scale(v: float, cap: float) -> float:
    return max(0.0, min(1.0, v / cap)) if cap > 0 else 0.0


def team_lineup_dict(team: FantasyTeam) -> dict[str, Any]:
    return {
        "name": team.name,
        "formation": team.formation,
        "lineup": [
            {
                "player": s.player,
                "slot": s.slot,
                "captain": s.is_captain,
                "vice_captain": s.is_vice_captain,
                "role_filter": (s.role_filter or "").strip().upper(),
            }
            for s in team.lineup
        ],
    }


def _starting_xi(team: FantasyTeam) -> list[str]:
    return [s.player for s in team.lineup if s.player]


def _bench_impact_side(team: FantasyTeam, player_stats: dict[str, PlayerStats]) -> dict[str, Any]:
    squad = _starting_xi(team) + list(team.bench or [])
    return bench_impact_for_team(team.name, _starting_xi(team), squad, team.bench or [], player_stats)


def team_payload_dict(team: dict[str, Any]) -> dict[str, Any]:
    """Serialize team dict for reports (includes season override selections)."""
    out = team_lineup_dict(FantasyTeam.from_dict(team))
    if team.get("prime_player"):
        out["prime_player"] = team["prime_player"]
    if team.get("peak_season"):
        out["peak_season"] = team["peak_season"]
    if team.get("bench"):
        out["bench"] = team["bench"]
    meta = team.get("sheet_meta")
    if meta:
        out["sheet_meta"] = {
            k: meta[k]
            for k in ("full_roster", "bench_players", "squad_size", "player_count")
            if k in meta
        }
    return out


def extended_metrics(team: FantasyTeam, stats: dict[str, PlayerStats]) -> dict[str, Any]:
    lineup = [stats[s.player] for s in team.lineup]
    defs = [p for p in lineup if p.fpl_position == "DEF"]
    mids = [p for p in lineup if p.fpl_position == "MID"]
    fwds = [p for p in lineup if p.fpl_position == "FWD"]
    units = compute_unit_ratings_by_slot(team, stats)
    composites = compute_team_composites(team, stats, units=units)
    fit = team_formation_fit(
        team.formation,
        [(s.player, s.slot, s.role_filter or "") for s in team.lineup],
        stats,
    )

    return {
        "defensive_unit": composites.defensive_solidity,
        "possession_control": composites.possession_control,
        "chance_creation": composites.creativity,
        "attacking_effectiveness": composites.attacking_effectiveness,
        "midfield_control": composites.midfield_control,
        "finishing_threat": composites.finishing_threat,
        "formation_fit": round(fit["average_fit"], 3),
        "pressing_intensity": composites.pressing_intensity,
        "press_resistance": composites.press_resistance,
        "transition_threat": composites.transition_threat,
        "aerial_defence": composites.aerial_defence,
        "team_composites": team_composites_dict(composites),
        "units": _units_dict(units),
        "xga_suppression": round(
            defence_suppression(
                units.defence, units.goalkeeper, units.midfield_defence, units.transition_risk
            ),
            3,
        ),
        "xg_split": {
            "finishing": round(attack_to_xg(units.finishing), 2),
            "creation": round(creation_to_xg(units.chance_creation), 2),
            "total_raw": round(combined_attack_xg(units), 2),
        },
        "fwd_xg90": round(_avg([p.xg90 for p in fwds]), 2),
        "avg_pass_pct": round(_avg([p.pass_pct for p in lineup]), 1),
        "formation_fit_players": fit["players"],
    }


def fullback_profile(team: FantasyTeam, stats: dict[str, PlayerStats]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for slot in team.lineup:
        if slot.slot.upper() not in FULLBACK_SLOTS and slot_role(slot.slot) != "fullback":
            continue
        p = stats[slot.player]
        fit = player_slot_fit(p, team.formation, slot.slot, role_filter=slot.role_filter or None)
        rows.append(
            {
                "player": slot.player,
                "slot": slot.slot,
                "xa90": round(p.xa90, 2),
                "key_passes90": round(p.key_passes90, 2),
                "creation_score": round(_player_chance_creation_contrib(p, fit), 3),
                "attack_exposure": round(_fullback_attack_exposure(p, fit), 3),
                "fit": round(fit, 3),
            }
        )
    u = compute_unit_ratings(team, stats)
    sup_base = defence_suppression(u.defence, u.goalkeeper, u.midfield_defence, 0.0)
    sup_trans = defence_suppression(
        u.defence, u.goalkeeper, u.midfield_defence, u.transition_risk
    )
    return {
        "fullbacks": rows,
        "transition_risk": u.transition_risk,
        "xga_suppression_base": round(sup_base, 3),
        "xga_suppression_with_transition": round(sup_trans, 3),
    }


def _serialize_match_result(result) -> dict[str, Any]:
    def goals(side) -> list[dict[str, Any]]:
        return [
            {"minute": g.minute, "scorer": g.scorer, "assister": g.assister}
            for g in side.scorers
        ]

    return {
        "scoreline": result.scoreline,
        "home": {
            "team": result.home.team,
            "goals": result.home.goals,
            "xg": result.home.xg,
            "scorers": goals(result.home),
        },
        "away": {
            "team": result.away.team,
            "goals": result.away.goals,
            "xg": result.away.xg,
            "scorers": goals(result.away),
        },
        "winner": result.winner,
    }


def build_report(
    home: FantasyTeam,
    away: FantasyTeam,
    player_stats: dict[str, PlayerStats],
    *,
    n_simulations: int = 10000,
    seed: int | None = None,
    include_single_match: bool = True,
    season_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    uh = compute_unit_ratings(home, player_stats)
    ua = compute_unit_ratings(away, player_stats)
    h_mid, a_mid = midfield_battle_multiplier(uh.midfield, ua.midfield)

    cfg = MatchSimConfig(n_simulations=n_simulations, seed=seed)
    mc = monte_carlo_matches(home, away, player_stats, cfg)

    home_prof = build_team_profile(home, player_stats)
    away_prof = build_team_profile(away, player_stats)
    home_bench = mc.get("bench_impact", {}).get("home") or _bench_impact_side(home, player_stats)
    away_bench = mc.get("bench_impact", {}).get("away") or _bench_impact_side(away, player_stats)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine_version": "slot-aware-v2",
        "matchup": {
            "home": team_lineup_dict(home),
            "away": team_lineup_dict(away),
        },
        "profiles": {
            "home": {
                "extended": extended_metrics(home, player_stats),
                "fullbacks": fullback_profile(home, player_stats),
                "trophy_multiplier": home_prof.trophy.multiplier,
                "players": home_prof.players,
            },
            "away": {
                "extended": extended_metrics(away, player_stats),
                "fullbacks": fullback_profile(away, player_stats),
                "trophy_multiplier": away_prof.trophy.multiplier,
                "players": away_prof.players,
            },
        },
        "mechanics": {
            "home_attacks_vs_away_defence": round(
                defence_suppression(ua.defence, ua.goalkeeper, ua.midfield_defence, ua.transition_risk),
                3,
            ),
            "away_attacks_vs_home_defence": round(
                defence_suppression(uh.defence, uh.goalkeeper, uh.midfield_defence, uh.transition_risk),
                3,
            ),
            "midfield_battle": {
                "home_multiplier": round(h_mid, 3),
                "away_multiplier": round(a_mid, 3),
            },
            "wide_matchup": mc.get("wide_matchup")
            or {
                "home": compute_wide_matchup_modifier(
                    home, away, player_stats, ua.transition_risk
                ),
                "away": compute_wide_matchup_modifier(
                    away, home, player_stats, uh.transition_risk
                ),
            },
            "press_matchup": mc.get("press_matchup") or {},
        },
        "monte_carlo": {
            "simulations": mc["simulations"],
            "expected_xg": mc["expected_xg"],
            "home_win_pct": mc["home_win_pct"],
            "draw_pct": mc["draw_pct"],
            "away_win_pct": mc["away_win_pct"],
            "home_goals_avg": mc["home_goals_avg"],
            "away_goals_avg": mc["away_goals_avg"],
            "total_goals_avg": mc["total_goals_avg"],
            "btts_pct": mc["btts_pct"],
            "over_2_5_pct": mc["over_2_5_pct"],
            "scorelines": mc["most_common_scorelines"],
            "unit_ratings": mc["unit_ratings"],
            "home_trophy_multiplier": mc["home_trophy_multiplier"],
            "away_trophy_multiplier": mc["away_trophy_multiplier"],
            "midfield_battle": mc["midfield_battle"],
            "bench_impact": mc.get("bench_impact") or {"home": home_bench, "away": away_bench},
        },
        "bench_impact": {"home": home_bench, "away": away_bench},
    }

    if include_single_match:
        import random

        rng = random.Random(seed)
        single = simulate_match_once(home, away, player_stats, cfg, rng)
        report["sample_match"] = _serialize_match_result(single)

    if season_overrides:
        report["season_overrides"] = season_overrides

    report["analysis"] = build_matchup_analysis(report)
    report["squad_analysis"] = build_squad_strengths_report(report)
    return report


def build_board_result_report(
    home: FantasyTeam,
    away: FantasyTeam,
    player_stats: dict[str, PlayerStats],
    *,
    home_goals: int,
    away_goals: int,
    board_events: list[dict[str, Any]] | None = None,
    match_log: list[dict[str, Any]] | dict[str, Any] | None = None,
    n_simulations: int = 800,
    seed: int | None = None,
    season_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ratings-based report enriched with the official pin-board score and events."""
    report = build_report(
        home,
        away,
        player_stats,
        n_simulations=max(200, int(n_simulations)),
        seed=seed,
        include_single_match=False,
        season_overrides=season_overrides,
    )
    report["analysis"] = enrich_analysis_with_board_result(
        report["analysis"],
        report,
        home_goals=int(home_goals),
        away_goals=int(away_goals),
        board_events=board_events,
        match_log=match_log,
    )
    report["board_result"] = {
        "home_goals": int(home_goals),
        "away_goals": int(away_goals),
        "board_events": normalize_board_events(board_events, match_log),
        "engine": "tactic_board",
    }
    return report
