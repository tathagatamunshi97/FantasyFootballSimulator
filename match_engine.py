"""Deterministic ratings-based expected-goals matchup projection.

Every match is decided live on the tactic board -- this module only produces
the pre-match ratings comparison (expected xG, unit ratings, press/wide
matchup modifiers) used to build analysis text. There is no simulation, no
randomness, and no win/draw/loss odds anywhere in this module.
"""
from __future__ import annotations

from typing import Any

from bench_impact import apply_bench_boost_to_units, bench_impact_for_team
from formation_fit import team_formation_fit
from models import FantasyTeam, PlayerStats
from team_ratings import (
    UnitRatings,
    combined_attack_xg,
    compute_team_composites,
    compute_unit_ratings,
    compute_wide_matchup_modifier,
    defence_suppression,
    midfield_battle_multiplier,
    press_xg_suppression,
)
from trophy_bonus import apply_trophy_multiplier, team_trophy_profile


def _starting_xi_names(team: FantasyTeam) -> list[str]:
    return [s.player for s in team.lineup if s.player]


def _full_squad_names(team: FantasyTeam) -> list[str]:
    starters = _starting_xi_names(team)
    if team.bench:
        return starters + [p for p in team.bench if p not in starters]
    return starters


def _units_with_bench(
    team: FantasyTeam,
    player_stats: dict[str, PlayerStats],
    trophy_mult: float,
) -> tuple[UnitRatings, dict[str, Any]]:
    units = apply_trophy_multiplier(
        compute_unit_ratings(team, player_stats),
        trophy_mult,
    )
    bench_impact = bench_impact_for_team(
        team.name,
        _starting_xi_names(team),
        _full_squad_names(team),
        team.bench,
        player_stats,
    )
    if bench_impact.get("contributed"):
        units = apply_bench_boost_to_units(units, bench_impact)
    return units, bench_impact


def _expected_goals(
    attack: UnitRatings,
    opponent: UnitRatings,
    *,
    attack_team: FantasyTeam,
    defend_team: FantasyTeam,
    player_stats: dict[str, PlayerStats],
    mid_mult: float,
    formation_fit: float,
    home_adv: float = 0.0,
    attack_composites=None,
    defend_composites=None,
) -> tuple[float, dict[str, float | bool], dict[str, float | bool]]:
    base = combined_attack_xg(attack)
    suppression = defence_suppression(
        opponent.defence,
        opponent.goalkeeper,
        opponent.midfield_defence,
        opponent.transition_risk,
    )
    fit_boost = 0.90 + 0.10 * formation_fit
    wide = compute_wide_matchup_modifier(
        attack_team, defend_team, player_stats, opponent.transition_risk
    )
    if attack_composites is None:
        attack_composites = compute_team_composites(attack_team, player_stats)
    if defend_composites is None:
        defend_composites = compute_team_composites(defend_team, player_stats)
    duel_bearers = [
        player_stats[s.player]
        for s in defend_team.lineup
        if player_stats[s.player].fpl_position in ("DEF", "MID")
        and player_stats[s.player].duels_won_pct > 0
    ]
    avg_duel = (
        sum(p.duels_won_pct for p in duel_bearers) / len(duel_bearers) if duel_bearers else 0.0
    )
    press = press_xg_suppression(
        attack_composites.pressing_intensity,
        defend_composites.press_resistance,
        duel_win_pct=avg_duel,
    )
    xg = max(
        0.25,
        base
        * suppression
        * mid_mult
        * fit_boost
        * float(wide["multiplier"])
        * float(press["multiplier"])
        * (1.0 + home_adv),
    )
    return xg, wide, press


def _units_dict(u: UnitRatings) -> dict[str, float]:
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


def expected_matchup(
    home: FantasyTeam,
    away: FantasyTeam,
    player_stats: dict[str, PlayerStats],
    *,
    home_advantage: float = 0.0,
) -> dict[str, Any]:
    """Deterministic pre-match ratings comparison: expected xG, unit ratings,
    press/wide matchup modifiers, bench impact. No randomness anywhere."""
    home_units, home_bench_impact = _units_with_bench(
        home, player_stats, team_trophy_profile(home, player_stats).multiplier
    )
    away_units, away_bench_impact = _units_with_bench(
        away, player_stats, team_trophy_profile(away, player_stats).multiplier
    )
    home_fit = team_formation_fit(
        home.formation,
        [(s.player, s.slot, getattr(s, "role_filter", "") or "") for s in home.lineup],
        player_stats,
    )
    away_fit = team_formation_fit(
        away.formation,
        [(s.player, s.slot, getattr(s, "role_filter", "") or "") for s in away.lineup],
        player_stats,
    )
    h_mid, a_mid = midfield_battle_multiplier(home_units.midfield, away_units.midfield)
    home_composites = compute_team_composites(home, player_stats)
    away_composites = compute_team_composites(away, player_stats)
    expected_home_xg, home_wide, home_press = _expected_goals(
        home_units,
        away_units,
        attack_team=home,
        defend_team=away,
        player_stats=player_stats,
        mid_mult=h_mid,
        formation_fit=home_fit["average_fit"],
        home_adv=home_advantage,
        attack_composites=home_composites,
        defend_composites=away_composites,
    )
    expected_away_xg, away_wide, away_press = _expected_goals(
        away_units,
        home_units,
        attack_team=away,
        defend_team=home,
        player_stats=player_stats,
        mid_mult=a_mid,
        formation_fit=away_fit["average_fit"],
        attack_composites=away_composites,
        defend_composites=home_composites,
    )

    return {
        "home_team": home.name,
        "away_team": away.name,
        "unit_ratings": {"home": _units_dict(home_units), "away": _units_dict(away_units)},
        "home_gk_meta": {
            "confidence": home_units.gk_confidence,
            "is_backup": home_units.gk_is_backup,
        },
        "away_gk_meta": {
            "confidence": away_units.gk_confidence,
            "is_backup": away_units.gk_is_backup,
        },
        "home_trophy_multiplier": team_trophy_profile(home, player_stats).multiplier,
        "away_trophy_multiplier": team_trophy_profile(away, player_stats).multiplier,
        "midfield_battle": {
            "home_chance_multiplier": round(h_mid, 3),
            "away_chance_multiplier": round(a_mid, 3),
        },
        "wide_matchup": {"home": home_wide, "away": away_wide},
        "press_matchup": {"home": home_press, "away": away_press},
        "team_composites": {
            "home": {
                "pressing_intensity": home_composites.pressing_intensity,
                "press_resistance": home_composites.press_resistance,
                "defensive_solidity": home_composites.defensive_solidity,
            },
            "away": {
                "pressing_intensity": away_composites.pressing_intensity,
                "press_resistance": away_composites.press_resistance,
                "defensive_solidity": away_composites.defensive_solidity,
            },
        },
        "expected_xg": {"home": round(expected_home_xg, 2), "away": round(expected_away_xg, 2)},
        "home_formation_fit": home_fit,
        "away_formation_fit": away_fit,
        "bench_impact": {"home": home_bench_impact, "away": away_bench_impact},
    }
