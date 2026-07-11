"""Monte Carlo real-football match simulation using unit ratings (Sofascore + Understat)."""
from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from bench_impact import apply_bench_boost_to_units, bench_impact_for_team
from formation_fit import player_slot_fit, team_formation_fit
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
from slot_roles import slot_assist_weight, slot_scorer_weight
from trophy_bonus import apply_trophy_multiplier, team_trophy_profile


@dataclass
class MatchSimConfig:
    n_simulations: int = 5000
    seed: int | None = None
    home_advantage: float = 0.0


@dataclass
class GoalEvent:
    scorer: str
    assister: str | None
    minute: int


@dataclass
class TeamMatchResult:
    team: str
    goals: int
    xg: float
    shots: int
    formation_fit: float
    units: UnitRatings
    scorers: list[GoalEvent] = field(default_factory=list)


@dataclass
class MatchResult:
    home: TeamMatchResult
    away: TeamMatchResult

    @property
    def scoreline(self) -> str:
        return f"{self.home.goals}-{self.away.goals}"

    @property
    def winner(self) -> str | None:
        if self.home.goals > self.away.goals:
            return self.home.team
        if self.away.goals > self.home.goals:
            return self.away.team
        return None


def _poisson(lam: float, rng: random.Random) -> int:
    lam = max(0.0, lam)
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(lam + rng.gauss(0, math.sqrt(lam)))))
    limit = math.exp(-lam)
    k, p = 0, 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1


def _pick_weighted(items: list[tuple[str, float]], rng: random.Random) -> str | None:
    if not items:
        return None
    total = sum(w for _, w in items)
    if total <= 0:
        return items[rng.randint(0, len(items) - 1)][0]
    r = rng.random() * total
    for name, w in items:
        r -= w
        if r <= 0:
            return name
    return items[-1][0]


def _scorer_shares(
    team: FantasyTeam,
    player_stats: dict[str, PlayerStats],
) -> list[tuple[str, float]]:
    shares: list[tuple[str, float]] = []
    for slot in team.lineup:
        stats = player_stats[slot.player]
        fit = player_slot_fit(stats, team.formation, slot.slot)
        pos_w = slot_scorer_weight(slot.slot, stats.fpl_position)
        share = (
            (stats.npxg90 or stats.xg90) * 0.42
            + stats.xg90 * 0.18
            + stats.xg_chain90 * 0.12
            + stats.shots90 * 0.05
            + stats.big_chances_created90 * 0.08
            + stats.penalty_goals90 * 0.15
        ) * pos_w * (0.55 + 0.45 * fit)
        if share > 0:
            shares.append((slot.player, share))
    return shares


def _assist_shares(
    team: FantasyTeam,
    player_stats: dict[str, PlayerStats],
) -> list[tuple[str, float]]:
    shares: list[tuple[str, float]] = []
    for slot in team.lineup:
        stats = player_stats[slot.player]
        fit = player_slot_fit(stats, team.formation, slot.slot)
        w = (
            stats.xa90 * 0.35
            + stats.xg_buildup90 * 0.20
            + stats.key_passes90 * 0.18
            + stats.understat_key_passes90 * 0.12
            + stats.big_chances_created90 * 0.15
            + stats.assists90 * 0.10
        ) * slot_assist_weight(slot.slot) * (0.55 + 0.45 * fit)
        if w > 0:
            shares.append((slot.player, w))
    return shares


def _assign_goals(
    n_goals: int,
    scorer_shares: list[tuple[str, float]],
    assist_shares: list[tuple[str, float]],
    rng: random.Random,
) -> list[GoalEvent]:
    events: list[GoalEvent] = []
    for _ in range(n_goals):
        scorer = _pick_weighted(scorer_shares, rng)
        if scorer is None:
            continue
        assister: str | None = None
        if rng.random() < 0.74:
            pool = [(n, w) for n, w in assist_shares if n != scorer]
            assister = _pick_weighted(pool, rng)
        minute = int(max(1, min(90, round(rng.betavariate(2.2, 2.0) * 90))))
        events.append(GoalEvent(scorer=scorer, assister=assister, minute=minute))
    events.sort(key=lambda e: e.minute)
    return events


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


def simulate_match_once(
    home: FantasyTeam,
    away: FantasyTeam,
    player_stats: dict[str, PlayerStats],
    cfg: MatchSimConfig,
    rng: random.Random,
) -> MatchResult:
    home_fit_info = team_formation_fit(
        home.formation, [(s.player, s.slot, getattr(s, "role_filter", "") or "") for s in home.lineup], player_stats
    )
    away_fit_info = team_formation_fit(
        away.formation, [(s.player, s.slot, getattr(s, "role_filter", "") or "") for s in away.lineup], player_stats
    )
    home_units, _home_bench = _units_with_bench(
        home, player_stats, team_trophy_profile(home, player_stats).multiplier
    )
    away_units, _away_bench = _units_with_bench(
        away, player_stats, team_trophy_profile(away, player_stats).multiplier
    )
    home_mid_mult, away_mid_mult = midfield_battle_multiplier(
        home_units.midfield, away_units.midfield
    )

    home_xg, _home_wide, _home_press = _expected_goals(
        home_units,
        away_units,
        attack_team=home,
        defend_team=away,
        player_stats=player_stats,
        mid_mult=home_mid_mult,
        formation_fit=home_fit_info["average_fit"],
        home_adv=cfg.home_advantage,
    )
    away_xg, _away_wide, _away_press = _expected_goals(
        away_units,
        home_units,
        attack_team=away,
        defend_team=home,
        player_stats=player_stats,
        mid_mult=away_mid_mult,
        formation_fit=away_fit_info["average_fit"],
    )

    home_goals = _poisson(home_xg, rng)
    away_goals = _poisson(away_xg, rng)

    home_scorers = _scorer_shares(home, player_stats)
    away_scorers = _scorer_shares(away, player_stats)

    return MatchResult(
        home=TeamMatchResult(
            team=home.name,
            goals=home_goals,
            xg=round(home_xg, 2),
            shots=int(max(0, round(home_xg * rng.uniform(9.0, 12.0) + rng.gauss(0, 2.0)))),
            formation_fit=home_fit_info["average_fit"],
            units=home_units,
            scorers=_assign_goals(
                home_goals, home_scorers, _assist_shares(home, player_stats), rng
            ),
        ),
        away=TeamMatchResult(
            team=away.name,
            goals=away_goals,
            xg=round(away_xg, 2),
            shots=int(max(0, round(away_xg * rng.uniform(9.0, 12.0) + rng.gauss(0, 2.0)))),
            formation_fit=away_fit_info["average_fit"],
            units=away_units,
            scorers=_assign_goals(
                away_goals, away_scorers, _assist_shares(away, player_stats), rng
            ),
        ),
    )


def monte_carlo_matches(
    home: FantasyTeam,
    away: FantasyTeam,
    player_stats: dict[str, PlayerStats],
    cfg: MatchSimConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or MatchSimConfig()
    rng = random.Random(cfg.seed)

    home_wins = away_wins = draws = 0
    home_goals_list: list[int] = []
    away_goals_list: list[int] = []
    total_goals_list: list[int] = []
    btts = over25 = 0
    scorelines: Counter[str] = Counter()
    example: MatchResult | None = None

    home_units, home_bench_impact = _units_with_bench(
        home, player_stats, team_trophy_profile(home, player_stats).multiplier
    )
    away_units, away_bench_impact = _units_with_bench(
        away, player_stats, team_trophy_profile(away, player_stats).multiplier
    )
    home_fit = team_formation_fit(
        home.formation, [(s.player, s.slot, getattr(s, "role_filter", "") or "") for s in home.lineup], player_stats
    )
    away_fit = team_formation_fit(
        away.formation, [(s.player, s.slot, getattr(s, "role_filter", "") or "") for s in away.lineup], player_stats
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
        home_adv=cfg.home_advantage,
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

    for i in range(cfg.n_simulations):
        result = simulate_match_once(home, away, player_stats, cfg, rng)
        if i == 0:
            example = result
        hg, ag = result.home.goals, result.away.goals
        home_goals_list.append(hg)
        away_goals_list.append(ag)
        total_goals_list.append(hg + ag)
        scorelines[result.scoreline] += 1
        if hg > ag:
            home_wins += 1
        elif ag > hg:
            away_wins += 1
        else:
            draws += 1
        if hg > 0 and ag > 0:
            btts += 1
        if hg + ag > 2:
            over25 += 1

    n = cfg.n_simulations

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

    return {
        "home_team": home.name,
        "away_team": away.name,
        "simulations": n,
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
        "wide_matchup": {
            "home": home_wide,
            "away": away_wide,
        },
        "press_matchup": {
            "home": home_press,
            "away": away_press,
        },
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
        "home_win_pct": round(100 * home_wins / n, 1),
        "away_win_pct": round(100 * away_wins / n, 1),
        "draw_pct": round(100 * draws / n, 1),
        "home_goals_avg": round(sum(home_goals_list) / n, 2),
        "away_goals_avg": round(sum(away_goals_list) / n, 2),
        "total_goals_avg": round(sum(total_goals_list) / n, 2),
        "btts_pct": round(100 * btts / n, 1),
        "over_2_5_pct": round(100 * over25 / n, 1),
        "most_common_scorelines": [{"score": s, "pct": round(100 * c / n, 1)} for s, c in scorelines.most_common(8)],
        "home_formation_fit": home_fit,
        "away_formation_fit": away_fit,
        "bench_impact": {"home": home_bench_impact, "away": away_bench_impact},
        "example_match": example,
    }
