#!/usr/bin/env python3
"""Extended matchup analysis: profiles + Monte Carlo."""
from __future__ import annotations

import json
import math
from pathlib import Path

from formation_fit import player_slot_fit, team_formation_fit
from match_engine import MatchSimConfig, monte_carlo_matches
from models import FantasyTeam, PlayerStats
from sofascore_client import StatsStore
from team_profile import build_team_profile
from slot_roles import FULLBACK_SLOTS, slot_role
from team_ratings import (
    attack_to_xg,
    combined_attack_xg,
    compute_unit_ratings,
    creation_to_xg,
    defence_suppression,
    midfield_battle_multiplier,
    _fullback_attack_exposure,
    _player_chance_creation_contrib,
)

DATA = Path(__file__).resolve().parent / "data" / "team_a_vs_b.json"


def _avg(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _scale(v: float, cap: float) -> float:
    return max(0.0, min(1.0, v / cap)) if cap > 0 else 0.0


def extended_metrics(team: FantasyTeam, stats: dict[str, PlayerStats]) -> dict:
    lineup = [stats[s.player] for s in team.lineup]
    defs = [p for p in lineup if p.fpl_position == "DEF"]
    mids = [p for p in lineup if p.fpl_position == "MID"]
    fwds = [p for p in lineup if p.fpl_position == "FWD"]
    gks = [p for p in lineup if p.fpl_position == "GK"]
    units = compute_unit_ratings(team, stats)
    fit = team_formation_fit(
        team.formation,
        [(s.player, s.slot, getattr(s, "role_filter", "") or "") for s in team.lineup],
        stats,
    )

    def_line = defs + mids[:0]  # pure def
    mid_line = mids + defs  # include progressive fullbacks in possession

    defensive_raw = (
        _scale(_avg([p.tackles90 for p in defs]), 2.5) * 0.25
        + _scale(_avg([p.interceptions90 for p in defs]), 1.8) * 0.25
        + _scale(_avg([p.clearances90 for p in defs]), 5.0) * 0.20
        + units.defence * 0.20
        + units.goalkeeper * 0.10
    )
    possession_raw = (
        _scale(_avg([p.passes_completed90 for p in mid_line + defs]), 55.0) * 0.30
        + _scale(_avg([p.pass_pct for p in lineup]), 100.0) * 0.25
        + _scale(_avg([p.xg_buildup90 for p in mid_line]), 0.65) * 0.25
        + _scale(12.0 - _avg([p.possession_lost90 for p in mid_line]), 12.0) * 0.20
    )
    chance_raw = (
        _scale(_avg([p.key_passes90 for p in lineup]), 2.0) * 0.22
        + _scale(_avg([p.xa90 for p in lineup]), 0.45) * 0.22
        + _scale(_avg([p.big_chances_created90 for p in lineup]), 0.9) * 0.22
        + _scale(_avg([p.xg_chain90 for p in lineup]), 0.85) * 0.18
        + _scale(_avg([p.understat_key_passes90 for p in lineup]), 2.0) * 0.16
    )
    attack_raw = (
        _scale(_avg([p.xg90 for p in fwds]), 0.85) * 0.30
        + _scale(_avg([p.npxg90 for p in fwds]), 0.75) * 0.20
        + _scale(_avg([p.shots90 for p in fwds]), 4.0) * 0.15
        + _scale(_avg([p.shots_on_target90 for p in fwds]), 2.0) * 0.10
        + units.attack * 0.25
    )
    unit_vals = [units.attack, units.midfield, units.defence, units.gk if hasattr(units, "gk") else units.goalkeeper]
    balance = 1.0 - _scale(max(unit_vals) - min(unit_vals), 0.45)

    press_raw = _scale(_avg([p.tackles90 + p.interceptions90 for p in lineup]), 4.5)
    transition_raw = _scale(_avg([p.dribbles90 for p in fwds + mids]), 2.5)
    aerial_raw = _scale(_avg([p.clearances90 for p in defs]), 5.5)

    return {
        "defensive_unit": round(defensive_raw, 3),
        "possession_control": round(possession_raw, 3),
        "chance_creation": round(chance_raw, 3),
        "attacking_effectiveness": round(attack_raw, 3),
        "overall_balance": round(balance, 3),
        "formation_fit": round(fit["average_fit"], 3),
        "pressing_intensity": round(press_raw, 3),
        "transition_threat": round(transition_raw, 3),
        "aerial_defence": round(aerial_raw, 3),
        "units": units,
        "xga_suppression": round(
            defence_suppression(
                units.defence,
                units.goalkeeper,
                units.midfield_defence,
                units.transition_risk,
            ),
            3,
        ),
        "fwd_xg90": round(_avg([p.xg90 for p in fwds]), 2),
        "mid_buildup90": round(_avg([p.xg_buildup90 for p in mids]), 2),
        "avg_pass_pct": round(_avg([p.pass_pct for p in lineup]), 1),
        "avg_poss_lost90": round(_avg([p.possession_lost90 for p in mid_line]), 1),
    }


def print_extended(name: str, m: dict) -> None:
    u = m["units"]
    print(f"\n--- {name} extended profile (0-1 scale unless noted) ---")
    print(f"  Defensive unit:          {m['defensive_unit']:.2f}  (DEF {u.defence:.2f}, MID-DEF {u.midfield_defence:.2f}, GK {u.goalkeeper:.2f}, trans-risk {u.transition_risk:.2f}, xGA suppress {m['xga_suppression']:.2f})")
    print(f"  Possession control:      {m['possession_control']:.2f}  (pass% {m['avg_pass_pct']:.1f}, poss lost {m['avg_poss_lost90']:.1f}/90)")
    print(f"  Chance creation:         {m['chance_creation']:.2f}")
    print(f"  Attacking effectiveness: {m['attacking_effectiveness']:.2f}  (FWD xG {m['fwd_xg90']:.2f}/90)")
    print(f"  Midfield progression:    buildup {m['mid_buildup90']:.2f}/90  |  MID unit {u.midfield:.2f}")
    print(f"  Overall balance:         {m['overall_balance']:.2f}  (ATK {u.attack:.2f} MID {u.midfield:.2f} DEF {u.defence:.2f} GK {u.goalkeeper:.2f})")
    print(f"  Formation fit:           {m['formation_fit']:.2f}")
    print(f"  Pressing / transitions:  press {m['pressing_intensity']:.2f}  |  counter {m['transition_threat']:.2f}  |  aerial DEF {m['aerial_defence']:.2f}")
    print(
        f"  Engine units:  FIN {u.finishing:.2f}  CREATE {u.chance_creation:.2f}  "
        f"MID-DEF {u.midfield_defence:.2f}  TRANS-RISK {u.transition_risk:.2f}"
    )
    print(
        f"  Raw xG split:  finishing {attack_to_xg(u.finishing):.2f}  "
        f"+ creation {creation_to_xg(u.chance_creation):.2f}  "
        f"= {combined_attack_xg(u):.2f} (pre-suppression)"
    )


def print_fullback_analysis(team: FantasyTeam, stats: dict[str, PlayerStats]) -> None:
    print(f"\n--- {team.name} fullback / transition profile ---")
    for slot in team.lineup:
        if slot.slot.upper() not in FULLBACK_SLOTS and slot_role(slot.slot) != "fullback":
            continue
        p = stats[slot.player]
        fit = player_slot_fit(p, team.formation, slot.slot)
        print(
            f"  {slot.player:<28} {slot.slot:<4}  "
            f"xa {p.xa90:.2f}  key-pass {p.key_passes90:.2f}  "
            f"create-score { _player_chance_creation_contrib(p, fit):.2f}  "
            f"attack-exposure {_fullback_attack_exposure(p, fit):.2f}  fit {fit:.2f}"
        )
    u = compute_unit_ratings(team, stats)
    sup = defence_suppression(u.defence, u.goalkeeper, u.midfield_defence, 0.0)
    sup_trans = defence_suppression(u.defence, u.goalkeeper, u.midfield_defence, u.transition_risk)
    print(f"  Team transition risk: {u.transition_risk:.3f}")
    print(f"  xGA suppression: {sup:.3f} without transition penalty  ->  {sup_trans:.3f} with fullbacks pushed")


def main() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    home = FantasyTeam.from_dict(data["home"])
    away = FantasyTeam.from_dict(data["away"])
    store = StatsStore()
    ps = store.players

    print("=" * 70)
    print(f"MATCHUP: {home.name} ({home.formation}) vs {away.name} ({away.formation})")
    print("Engine: slot-aware ratings, chance-creation xG channel, midfield shield, transition risk")
    print("=" * 70)

    for team in (home, away):
        prof = build_team_profile(team, ps)
        print_team = __import__("team_profile", fromlist=["print_team_profile"]).print_team_profile
        print_team(prof)

    hm = extended_metrics(home, ps)
    am = extended_metrics(away, ps)
    print_extended(home.name, hm)
    print_extended(away.name, am)
    print_fullback_analysis(home, ps)
    print_fullback_analysis(away, ps)

    uh = compute_unit_ratings(home, ps)
    ua = compute_unit_ratings(away, ps)
    h_mid_mult, a_mid_mult = midfield_battle_multiplier(uh.midfield, ua.midfield)
    print("\n--- Matchup mechanics ---")
    print(
        f"  {home.name} attacks vs {away.name} defence: "
        f"suppress {defence_suppression(ua.defence, ua.goalkeeper, ua.midfield_defence, ua.transition_risk):.3f} "
        f"(B trans-risk {ua.transition_risk:.2f})"
    )
    print(
        f"  {away.name} attacks vs {home.name} defence: "
        f"suppress {defence_suppression(uh.defence, uh.goalkeeper, uh.midfield_defence, uh.transition_risk):.3f} "
        f"(A trans-risk {uh.transition_risk:.2f})"
    )
    print(f"  Midfield battle: A x{h_mid_mult:.3f}  B x{a_mid_mult:.3f}")

    cfg = MatchSimConfig(n_simulations=20000, seed=42)
    mc = monte_carlo_matches(home, away, ps, cfg)

    print("\n" + "=" * 70)
    print(f"MONTE CARLO — {mc['simulations']:,} simulations (neutral venue)")
    print("=" * 70)
    print(f"\nExpected xG:  {home.name} {mc['expected_xg']['home']:.2f}  |  {away.name} {mc['expected_xg']['away']:.2f}")
    print(f"\nOUTCOME PROBABILITIES")
    print(f"  {home.name} win:  {mc['home_win_pct']:.1f}%")
    print(f"  Draw:             {mc['draw_pct']:.1f}%")
    print(f"  {away.name} win:  {mc['away_win_pct']:.1f}%")
    print(f"\nTop 3 most likely results:")
    for i, row in enumerate(mc["most_common_scorelines"][:3], 1):
        print(f"  {i}. {row['score']}  ({row['pct']:.1f}%)")
    print(f"\nGoals:  avg {home.name} {mc['home_goals_avg']:.2f}  |  {away.name} {mc['away_goals_avg']:.2f}  |  total {mc['total_goals_avg']:.2f}")
    print(f"Both teams score: {mc['btts_pct']:.1f}%  |  Over 2.5: {mc['over_2_5_pct']:.1f}%")
    print(f"\nTop 8 scorelines:")
    for row in mc["most_common_scorelines"][:8]:
        print(f"  {row['score']:<7} {row['pct']:.1f}%")

    ur = mc["unit_ratings"]
    mb = mc["midfield_battle"]
    print(f"\nUnit ratings (trophy-boosted, new engine):")
    for label, side in ((home.name, "home"), (away.name, "away")):
        u = ur[side]
        print(
            f"  {label:<10} ATK {u['attack']:.2f}  FIN {u['finishing']:.2f}  "
            f"CREATE {u['chance_creation']:.2f}  MID {u['midfield']:.2f}  "
            f"DEF {u['defence']:.2f}  MID-DEF {u['midfield_defence']:.2f}  "
            f"TRANS {u['transition_risk']:.2f}  GK {u['goalkeeper']:.2f}"
        )
    print(
        f"  Silverware: {home.name} x{mc['home_trophy_multiplier']:.3f}  |  "
        f"{away.name} x{mc['away_trophy_multiplier']:.3f}"
    )
    print(
        f"  Midfield multipliers: {home.name} x{mb['home_chance_multiplier']:.3f}  |  "
        f"{away.name} x{mb['away_chance_multiplier']:.3f}"
    )


if __name__ == "__main__":
    main()
