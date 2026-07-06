"""Formation templates and player-slot fit scoring (Sofascore stats)."""
from __future__ import annotations

from typing import Any

from models import PlayerStats

FORMATION_SLOTS: dict[str, list[dict[str, Any]]] = {
    "4-4-2": [
        {"slot": "GK", "tags": ["GK"], "profile": {"saves90": 1.0, "goals_prevented90": 0.8, "clean_sheet_pct": 0.6}},
        {"slot": "RB", "tags": ["RB", "WB", "DF"], "profile": {"tackles90": 0.7, "key_passes90": 0.5, "passes_completed90": 0.4}},
        {"slot": "CB1", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "interceptions90": 0.8, "clearances90": 0.9}},
        {"slot": "CB2", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "interceptions90": 0.8, "clearances90": 0.9}},
        {"slot": "LB", "tags": ["LB", "WB", "DF"], "profile": {"tackles90": 0.7, "key_passes90": 0.5, "passes_completed90": 0.4}},
        {"slot": "RM", "tags": ["RW", "RM", "MF", "FW"], "profile": {"key_passes90": 0.6, "dribbles90": 0.7, "xa90": 0.5, "shots90": 0.4}},
        {"slot": "CM1", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6, "key_passes90": 0.4, "interceptions90": 0.4}},
        {"slot": "CM2", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6, "key_passes90": 0.4, "interceptions90": 0.4}},
        {"slot": "LM", "tags": ["LW", "LM", "MF", "FW"], "profile": {"key_passes90": 0.6, "dribbles90": 0.7, "xa90": 0.5, "shots90": 0.4}},
        {"slot": "ST1", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 0.9, "shots90": 0.8, "shots_on_target90": 0.6}},
        {"slot": "ST2", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 0.9, "shots90": 0.8, "shots_on_target90": 0.6}},
    ],
    "4-3-3": [
        {"slot": "GK", "tags": ["GK"], "profile": {"saves90": 1.0, "goals_prevented90": 0.8, "clean_sheet_pct": 0.6}},
        {"slot": "RB", "tags": ["RB", "WB", "DF"], "profile": {"tackles90": 0.7, "passes_completed90": 0.5, "key_passes90": 0.4}},
        {"slot": "CB1", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "interceptions90": 0.8, "clearances90": 0.9}},
        {"slot": "CB2", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "interceptions90": 0.8, "clearances90": 0.9}},
        {"slot": "LB", "tags": ["LB", "WB", "DF"], "profile": {"tackles90": 0.7, "passes_completed90": 0.5, "key_passes90": 0.4}},
        {"slot": "DM", "tags": ["DM", "CM", "MF"], "profile": {"tackles90": 0.8, "interceptions90": 0.7, "passes_completed90": 0.5, "clearances90": 0.4}},
        {"slot": "CM", "tags": ["CM", "AM", "MF"], "profile": {"key_passes90": 0.6, "passes_completed90": 0.6, "xa90": 0.5}},
        {"slot": "AM", "tags": ["AM", "CM", "MF"], "profile": {"key_passes90": 0.8, "xa90": 0.7, "dribbles90": 0.5}},
        {"slot": "RW", "tags": ["RW", "RM", "FW", "MF"], "profile": {"dribbles90": 0.8, "key_passes90": 0.6, "xa90": 0.6, "xg90": 0.4}},
        {"slot": "ST", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 1.0, "shots90": 0.9, "shots_on_target90": 0.7}},
        {"slot": "LW", "tags": ["LW", "LM", "FW", "MF"], "profile": {"dribbles90": 0.8, "key_passes90": 0.6, "xa90": 0.6, "xg90": 0.4}},
    ],
    "3-5-2": [
        {"slot": "GK", "tags": ["GK"], "profile": {"saves90": 1.0, "goals_prevented90": 0.8, "clean_sheet_pct": 0.6}},
        {"slot": "CB1", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9, "interceptions90": 0.7}},
        {"slot": "CB2", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9, "interceptions90": 0.7}},
        {"slot": "CB3", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9, "interceptions90": 0.7}},
        {"slot": "RWB", "tags": ["RB", "WB", "RM", "DF"], "profile": {"key_passes90": 0.6, "tackles90": 0.6, "dribbles90": 0.5}},
        {"slot": "CM1", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6, "interceptions90": 0.4}},
        {"slot": "CM2", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6, "interceptions90": 0.4}},
        {"slot": "CM3", "tags": ["CM", "AM", "MF"], "profile": {"key_passes90": 0.6, "xa90": 0.5, "passes_completed90": 0.5}},
        {"slot": "LWB", "tags": ["LB", "WB", "LM", "DF"], "profile": {"key_passes90": 0.6, "tackles90": 0.6, "dribbles90": 0.5}},
        {"slot": "ST1", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 0.9, "shots90": 0.8}},
        {"slot": "ST2", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 0.9, "shots90": 0.8}},
    ],
    "4-2-3-1": [
        {"slot": "GK", "tags": ["GK"], "profile": {"saves90": 1.0, "goals_prevented90": 0.8, "clean_sheet_pct": 0.6}},
        {"slot": "RB", "tags": ["RB", "WB", "DF"], "profile": {"tackles90": 0.7, "passes_completed90": 0.5}},
        {"slot": "CB1", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "interceptions90": 0.8, "clearances90": 0.9}},
        {"slot": "CB2", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "interceptions90": 0.8, "clearances90": 0.9}},
        {"slot": "LB", "tags": ["LB", "WB", "DF"], "profile": {"tackles90": 0.7, "passes_completed90": 0.5}},
        {"slot": "DM1", "tags": ["DM", "CM", "MF"], "profile": {"tackles90": 0.8, "interceptions90": 0.7, "passes_completed90": 0.5}},
        {"slot": "DM2", "tags": ["DM", "CM", "MF"], "profile": {"tackles90": 0.8, "interceptions90": 0.7, "passes_completed90": 0.5}},
        {"slot": "RW", "tags": ["RW", "RM", "FW", "MF"], "profile": {"dribbles90": 0.8, "key_passes90": 0.6, "xa90": 0.6}},
        {"slot": "AM", "tags": ["AM", "CM", "MF"], "profile": {"key_passes90": 0.9, "xa90": 0.8, "dribbles90": 0.5}},
        {"slot": "LW", "tags": ["LW", "LM", "FW", "MF"], "profile": {"dribbles90": 0.8, "key_passes90": 0.6, "xa90": 0.6}},
        {"slot": "ST", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 1.0, "shots90": 0.9, "shots_on_target90": 0.7}},
    ],
    "3-4-3": [
        {"slot": "GK", "tags": ["GK"], "profile": {"saves90": 1.0, "goals_prevented90": 0.8, "clean_sheet_pct": 0.6}},
        {"slot": "CB1", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9}},
        {"slot": "CB2", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9}},
        {"slot": "CB3", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9}},
        {"slot": "RM", "tags": ["RW", "RM", "WB", "MF"], "profile": {"key_passes90": 0.6, "dribbles90": 0.6, "xa90": 0.5}},
        {"slot": "CM1", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6}},
        {"slot": "CM2", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6}},
        {"slot": "LM", "tags": ["LW", "LM", "WB", "MF"], "profile": {"key_passes90": 0.6, "dribbles90": 0.6, "xa90": 0.5}},
        {"slot": "RW", "tags": ["RW", "FW", "MF"], "profile": {"xg90": 0.7, "dribbles90": 0.8, "key_passes90": 0.6}},
        {"slot": "ST", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 1.0, "shots90": 0.9}},
        {"slot": "LW", "tags": ["LW", "FW", "MF"], "profile": {"xg90": 0.7, "dribbles90": 0.8, "key_passes90": 0.6}},
    ],
}

STAT_CAPS: dict[str, float] = {
    "xg90": 1.0,
    "xa90": 0.6,
    "shots90": 4.0,
    "shots_on_target90": 2.5,
    "key_passes90": 2.5,
    "tackles90": 3.5,
    "interceptions90": 2.5,
    "clearances90": 6.0,
    "dribbles90": 3.0,
    "passes_completed90": 60.0,
    "pass_pct": 100.0,
    "saves90": 4.5,
    "goals_prevented90": 0.8,
    "clean_sheet_pct": 100.0,
    "big_chances_created90": 1.2,
    "big_chances_missed90": 1.0,
    "possession_lost90": 12.0,
    "long_balls90": 8.0,
    "xg_buildup90": 0.55,
    "xg_chain90": 0.9,
    "npxg90": 0.85,
}


def supported_formations() -> list[str]:
    return sorted(FORMATION_SLOTS.keys())


def get_slot_definition(formation: str, slot_name: str) -> dict[str, Any] | None:
    for s in FORMATION_SLOTS.get(formation, FORMATION_SLOTS["4-4-2"]):
        if s["slot"] == slot_name:
            return s
    return None


def _position_match(player: PlayerStats, slot_def: dict[str, Any]) -> float:
    tags = {t.upper() for t in slot_def["tags"]}
    is_gk_slot = tags == {"GK"}
    primary = player.primary_position.upper()
    fpl = player.fpl_position.upper()
    player_tags = {p.upper() for p in player.positions} | {primary, fpl}

    if fpl == "GK" or primary == "GK":
        return 1.0 if is_gk_slot else 0.02

    if is_gk_slot:
        return 0.02

    if primary in tags:
        return 1.0
    if tags & player_tags:
        return 0.85
    fpl_map = {
        "GK": {"GK"},
        "DEF": {"CB", "LB", "RB", "WB", "DF"},
        "MID": {"CM", "DM", "AM", "MF", "RM", "LM"},
        "FWD": {"ST", "CF", "FW", "RW", "LW"},
    }
    if tags & fpl_map.get(player.fpl_position, set()):
        return 0.62
    # Wide/striker slots: mild penalty for pure defenders
    if fpl == "DEF" and tags & {"RW", "LW", "ST", "CF", "FW"}:
        return 0.12
    if fpl == "FWD" and tags <= {"CB", "DF"}:
        return 0.15
    return 0.28


def _profile_fit(stats: PlayerStats, profile: dict[str, float]) -> float:
    if not profile:
        return 0.65
    scores = []
    for stat, weight in profile.items():
        cap = STAT_CAPS.get(stat, 1.0)
        raw = _fit_stat_value(stats, stat) / cap if cap else 0.0
        scores.append(min(1.0, raw) * weight)
    return sum(scores) / max(sum(profile.values()), 1e-6)


def _fit_stat_value(stats: PlayerStats, stat: str) -> float:
    val = float(getattr(stats, stat, 0.0))
    if val > 0:
        return val
    fallbacks = {
        "key_passes90": stats.understat_key_passes90,
        "xa90": stats.understat_xa90,
        "shots90": stats.understat_shots90,
        "xg90": stats.understat_xg90,
    }
    return float(fallbacks.get(stat, 0.0))


def player_slot_fit(stats: PlayerStats, formation: str, slot_name: str) -> float:
    slot_def = get_slot_definition(formation, slot_name)
    if slot_def is None:
        return 0.5
    pos = _position_match(stats, slot_def)
    prof = _profile_fit(stats, slot_def.get("profile", {}))
    return max(0.25, min(1.0, 0.62 * pos + 0.38 * prof))


def team_formation_fit(
    formation: str,
    lineup: list[tuple[str, str]],
    player_stats: dict[str, PlayerStats],
) -> dict[str, Any]:
    rows = []
    fits = []
    for player_name, slot in lineup:
        stats = player_stats.get(player_name)
        if stats is None:
            rows.append({"player": player_name, "slot": slot, "fit": 0.4, "missing_stats": True})
            fits.append(0.4)
            continue
        fit = player_slot_fit(stats, formation, slot)
        rows.append({"player": player_name, "slot": slot, "fit": round(fit, 3), "position": stats.primary_position})
        fits.append(fit)
    avg = sum(fits) / len(fits) if fits else 0.5
    return {"formation": formation, "average_fit": round(avg, 3), "players": rows}
