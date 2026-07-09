#!/usr/bin/env python3
"""Audit Kinjal team aerial_defence and transition_risk."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from formation_fit import player_slot_fit
from models import FantasyTeam
from slot_roles import FULLBACK_SLOTS, slot_role, slot_unit_weights
from sofascore_client import StatsStore
from stats_resolver import prepare_match_player_stats
from team_ratings import (
    _compute_transition_risk,
    _fullback_attack_exposure,
    _player_midfield_defence_contrib,
    _scale,
    _clamp,
    compute_team_composites,
    compute_unit_ratings_by_slot,
)

KINJAL = {
    "name": "Kinjal+Sayan C",
    "formation": "4-3-3",
    "lineup": [
        {"slot": "GK", "player": "Joan García"},
        {"slot": "RB", "player": "Jules Koundé"},
        {"slot": "CB1", "player": "Willian Pacho"},
        {"slot": "CB2", "player": "Diego Godín"},
        {"slot": "LB", "player": "Nico O'Reilly"},
        {"slot": "DM", "player": "Casemiro"},
        {"slot": "CM", "player": "João Neves"},
        {"slot": "AM", "player": "Bruno Guimarães"},
        {"slot": "RW", "player": "Michael Olise"},
        {"slot": "ST", "player": "Harry Kane"},
        {"slot": "LW", "player": "Leandro Trossard"},
    ],
    "prime_player": "Casemiro",
    "peak_season": {"player": "Diego Godín", "season": "15/16"},
}


def _load_kinjal_payload(store: StatsStore) -> dict:
    from google_sheets_teams import load_team_by_name

    try:
        payload = load_team_by_name("Kinjal+Sayan C", formation="4-3-3", store=store)
        payload["prime_player"] = "Casemiro"
        payload["peak_season"] = {"player": "Diego Godín", "season": "15/16"}
        return payload
    except Exception:
        return KINJAL


def audit_kinjal() -> dict:
    store = StatsStore()
    team_dict = _load_kinjal_payload(store)
    player_stats, overrides, name_map = prepare_match_player_stats(team_dict, team_dict, store)
    team = FantasyTeam.from_dict(team_dict)
    units = compute_unit_ratings_by_slot(team, player_stats)
    composites = compute_team_composites(team, player_stats, units=units)

    fb_rows = []
    dm_rows = []
    cm_rows = []
    for slot in team.lineup:
        stats = player_stats[slot.player]
        fit = player_slot_fit(stats, team.formation, slot.slot)
        role = slot_role(slot.slot)
        if slot.slot.upper() in FULLBACK_SLOTS or role == "fullback":
            fb_rows.append(
                {
                    "player": slot.player,
                    "slot": slot.slot,
                    "exposure": round(_fullback_attack_exposure(stats, fit), 4),
                    "fit": round(fit, 3),
                    "xa90": round(stats.xa90, 3),
                    "key_passes90": round(stats.key_passes90, 3),
                    "xg_chain90": round(stats.xg_chain90, 3),
                    "shots90": round(stats.shots90, 3),
                    "dribbles90": round(stats.dribbles90, 3),
                    "big_chances_created90": round(stats.big_chances_created90, 3),
                }
            )
        if role == "dm":
            w = slot_unit_weights(slot.slot, stats.fpl_position)
            cov = _player_midfield_defence_contrib(stats, fit) * w.midfield_defence
            dm_rows.append(
                {
                    "player": slot.player,
                    "slot": slot.slot,
                    "cover": round(cov, 4),
                    "raw": round(_player_midfield_defence_contrib(stats, fit), 4),
                    "fit": round(fit, 3),
                    "weight": w.midfield_defence,
                }
            )
        if role == "cm":
            w = slot_unit_weights(slot.slot, stats.fpl_position)
            cov = _player_midfield_defence_contrib(stats, fit) * w.midfield_defence
            cm_rows.append(
                {
                    "player": slot.player,
                    "slot": slot.slot,
                    "cover": round(cov, 4),
                    "raw": round(_player_midfield_defence_contrib(stats, fit), 4),
                    "fit": round(fit, 3),
                    "weight": w.midfield_defence,
                }
            )

    max_exp = max(r["exposure"] for r in fb_rows)
    dm_avg = sum(r["cover"] for r in dm_rows) / len(dm_rows) if dm_rows else 0.38
    cm_avg = sum(r["cover"] for r in cm_rows) / len(cm_rows) if cm_rows else 0.38
    am_rows = []
    for slot in team.lineup:
        stats = player_stats[slot.player]
        fit = player_slot_fit(stats, team.formation, slot.slot)
        role = slot_role(slot.slot)
        if role == "am":
            w = slot_unit_weights(slot.slot, stats.fpl_position)
            cov = _player_midfield_defence_contrib(stats, fit) * w.midfield_defence
            am_rows.append(
                {
                    "player": slot.player,
                    "slot": slot.slot,
                    "cover": round(cov, 4),
                    "raw": round(_player_midfield_defence_contrib(stats, fit), 4),
                    "fit": round(fit, 3),
                    "weight": w.midfield_defence,
                }
            )
    am_avg = sum(r["cover"] for r in am_rows) / len(am_rows) if am_rows else 0.0
    cover = 0.68 * dm_avg + 0.32 * cm_avg + 0.14 * am_avg
    uncovered = max(0.08, 1.0 - cover * 0.95)
    risk_calc = _clamp(max_exp * uncovered * 1.35, 0.0, 0.48)

    defs = [player_stats[s.player] for s in team.lineup if player_stats[s.player].fpl_position == "DEF"]
    aerial_rows = []
    signals = []
    for p in defs:
        if p.aerials_won90 > 0:
            wr = p.aerials_won_pct / 100 if p.aerials_won_pct > 0 else 0.55
            sig = p.aerials_won90 * max(0.45, wr)
            mode = "aerial"
        else:
            sig = p.clearances90 * 0.45
            mode = "clearance_fallback"
        signals.append(sig)
        aerial_rows.append(
            {
                "player": p.player,
                "aerials_won90": round(p.aerials_won90, 3),
                "aerials_won_pct": round(p.aerials_won_pct, 1),
                "clearances90": round(p.clearances90, 3),
                "signal": round(sig, 4),
                "mode": mode,
                "primary_position": p.primary_position,
            }
        )

    avg_sig = sum(signals) / len(signals)
    avg_clr = sum(p.clearances90 for p in defs) / len(defs)
    aerial_calc = _clamp(_scale(avg_sig, 2.8) * 0.65 + _scale(avg_clr, 5.5) * 0.35)

    bruno = None
    for slot in team.lineup:
        if slot.player == "Bruno Guimarães":
            st = player_stats[slot.player]
            fit = player_slot_fit(st, team.formation, slot.slot)
            bruno = {
                "slot": slot.slot,
                "role": slot_role(slot.slot),
                "raw_middef": round(_player_midfield_defence_contrib(st, fit), 4),
                "would_cover_if_cm": round(
                    _player_midfield_defence_contrib(st, fit) * 0.75, 4
                ),
            }

    # Counterfactuals
    cf = {}
    # Without peak-season Godin override
    team_no_peak = dict(team_dict)
    team_no_peak["peak_season"] = {"player": "", "season": ""}
    ps_no_peak, _, _ = prepare_match_player_stats(team_no_peak, team_no_peak, store)
    t_no_peak = FantasyTeam.from_dict(team_no_peak)
    u_no_peak = compute_unit_ratings_by_slot(t_no_peak, ps_no_peak)
    c_no_peak = compute_team_composites(t_no_peak, ps_no_peak, units=u_no_peak)
    cf["no_godin_peak"] = {
        "aerial_defence": c_no_peak.aerial_defence,
        "transition_risk": u_no_peak.transition_risk,
    }
    # Bruno in CM instead of AM (hypothetical)
    hypo = json.loads(json.dumps(team_dict))
    for row in hypo["lineup"]:
        if row["player"] == "Bruno Guimarães":
            row["slot"] = "CM"
        if row["player"] == "João Neves":
            row["slot"] = "AM"
    ps_hypo, _, _ = prepare_match_player_stats(hypo, hypo, store)
    t_hypo = FantasyTeam.from_dict(hypo)
    u_hypo = compute_unit_ratings_by_slot(t_hypo, ps_hypo)
    cf["bruno_cm_neves_am"] = {"transition_risk": u_hypo.transition_risk}

    return {
        "units": {
            "transition_risk": units.transition_risk,
            "defence": units.defence,
            "midfield_defence": units.midfield_defence,
        },
        "composites": {"aerial_defence": composites.aerial_defence},
        "transition": {
            "fullbacks": fb_rows,
            "dm_cover": dm_rows,
            "cm_cover": cm_rows,
            "am_cover": am_rows,
            "max_exposure": round(max_exp, 4),
            "dm_avg": round(dm_avg, 4),
            "cm_avg": round(cm_avg, 4),
            "am_avg": round(am_avg, 4),
            "cover": round(cover, 4),
            "uncovered": round(uncovered, 4),
            "computed_risk": round(risk_calc, 4),
            "function_risk": round(_compute_transition_risk(team, player_stats), 4),
            "bruno_excluded": bruno,
        },
        "aerial": {
            "defenders": aerial_rows,
            "avg_signal": round(avg_sig, 4),
            "avg_clearances": round(avg_clr, 4),
            "computed_aerial": round(aerial_calc, 4),
        },
        "overrides": overrides.get("team_a", {}),
        "lineup": [
            {"slot": s.slot, "player": s.player} for s in team.lineup
        ],
        "formation": team.formation,
        "name_map": name_map,
        "counterfactuals": cf,
    }


def compare_tournament_teams() -> list[dict]:
    from google_sheets_teams import fetch_teams_dataframe, parse_teams_from_dataframe, team_payload_from_roster

    store = StatsStore()
    df = fetch_teams_dataframe()
    rosters = parse_teams_from_dataframe(df)
    rows = []
    for roster in sorted(rosters.values(), key=lambda r: r.name.lower()):
        try:
            payload = team_payload_from_roster(roster, formation="4-3-3", store=store)
            if not payload.get("prime_player"):
                payload["prime_player"] = ""
            ps, _, _ = prepare_match_player_stats(payload, payload, store)
            team = FantasyTeam.from_dict(payload)
            units = compute_unit_ratings_by_slot(team, ps)
            comp = compute_team_composites(team, ps, units=units)
            rows.append(
                {
                    "team": roster.name,
                    "formation": payload.get("formation"),
                    "transition_risk": units.transition_risk,
                    "aerial_defence": comp.aerial_defence,
                    "defence": units.defence,
                    "midfield_defence": units.midfield_defence,
                }
            )
        except Exception as exc:
            rows.append({"team": roster.name, "error": str(exc)})
    rows.sort(key=lambda r: r.get("transition_risk", 999))
    return rows


if __name__ == "__main__":
    out = {"kinjal": audit_kinjal()}
    try:
        out["tournament"] = compare_tournament_teams()
    except Exception as exc:
        out["tournament_error"] = str(exc)
    path = ROOT / "_kinjal_audit_out.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(path.read_text(encoding="utf-8"))
