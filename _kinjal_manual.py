#!/usr/bin/env python3
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
    _fullback_attack_exposure,
    _player_midfield_defence_contrib,
    compute_team_composites,
    compute_unit_ratings_by_slot,
)

MANUAL = {
    "name": "Kinjal+Sayan C",
    "formation": "4-3-3 attacking",
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


def run(payload: dict) -> dict:
    store = StatsStore()
    ps, ov, _ = prepare_match_player_stats(payload, payload, store)
    team = FantasyTeam.from_dict(payload)
    units = compute_unit_ratings_by_slot(team, ps)
    comp = compute_team_composites(team, ps, units=units)
    fb = []
    dm = []
    cm = []
    for slot in team.lineup:
        st = ps[slot.player]
        fit = player_slot_fit(st, team.formation, slot.slot)
        role = slot_role(slot.slot)
        if role == "fullback" or slot.slot in FULLBACK_SLOTS:
            fb.append(
                {
                    "player": slot.player,
                    "slot": slot.slot,
                    "exposure": round(_fullback_attack_exposure(st, fit), 4),
                    "fit": round(fit, 3),
                }
            )
        w = slot_unit_weights(slot.slot, st.fpl_position)
        if role == "dm":
            dm.append(
                {
                    "player": slot.player,
                    "cover": round(_player_midfield_defence_contrib(st, fit) * w.midfield_defence, 4),
                }
            )
        if role == "cm":
            cm.append(
                {
                    "player": slot.player,
                    "cover": round(_player_midfield_defence_contrib(st, fit) * w.midfield_defence, 4),
                }
            )
    aerial = []
    for slot in team.lineup:
        st = ps[slot.player]
        if st.fpl_position != "DEF":
            continue
        if st.aerials_won90 > 0:
            wr = st.aerials_won_pct / 100 if st.aerials_won_pct > 0 else 0.55
            sig = st.aerials_won90 * max(0.45, wr)
            mode = "aerial"
        else:
            sig = st.clearances90 * 0.45
            mode = "clearance_fallback"
        aerial.append(
            {
                "player": st.player,
                "slot": slot.slot,
                "aerials_won90": round(st.aerials_won90, 3),
                "aerials_won_pct": round(st.aerials_won_pct, 1),
                "clearances90": round(st.clearances90, 3),
                "signal": round(sig, 4),
                "mode": mode,
                "primary_position": st.primary_position,
            }
        )
    bruno = ps.get("Bruno Guimarães")
    bruno_info = None
    if bruno:
        fit = player_slot_fit(bruno, team.formation, "AM")
        bruno_info = {
            "slot": "AM",
            "role": slot_role("AM"),
            "raw_middef": round(_player_midfield_defence_contrib(bruno, fit), 4),
            "would_cover_if_cm": round(_player_midfield_defence_contrib(bruno, fit) * 0.75, 4),
        }
    return {
        "transition_risk": units.transition_risk,
        "aerial_defence": comp.aerial_defence,
        "defence": units.defence,
        "midfield_defence": units.midfield_defence,
        "fullbacks": fb,
        "dm_cover": dm,
        "cm_cover": cm,
        "aerial_defenders": aerial,
        "bruno_excluded": bruno_info,
        "overrides": ov.get("team_a", {}),
        "lineup": [{"slot": s.slot, "player": s.player} for s in team.lineup],
    }


if __name__ == "__main__":
    out = run(MANUAL)
    # counterfactuals
    no_peak = dict(MANUAL)
    no_peak["peak_season"] = {"player": "", "season": ""}
    out["no_godin_peak"] = {
        k: run(no_peak)[k] for k in ("transition_risk", "aerial_defence")
    }
    bruno_cm = json.loads(json.dumps(MANUAL))
    for row in bruno_cm["lineup"]:
        if row["player"] == "Bruno Guimarães":
            row["slot"] = "CM"
        if row["player"] == "João Neves":
            row["slot"] = "AM"
    out["bruno_as_cm"] = {"transition_risk": run(bruno_cm)["transition_risk"]}
    path = ROOT / "_kinjal_manual_out.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(path.read_text(encoding="utf-8"))
