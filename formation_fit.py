"""Formation templates and player-slot fit scoring (Sofascore stats)."""
from __future__ import annotations

from typing import Any

from models import PlayerStats

DEFAULT_FORMATION = "4-3-3 flat"

_LEGACY_FORMATION_ALIASES: dict[str, str] = {
    "4-3-3": "4-3-3 attacking",
    "3-4-3": "3-4-3(2)",  # legacy LM/RM variant
}

_BACK_FOUR: list[dict[str, Any]] = [
    {"slot": "GK", "tags": ["GK"], "profile": {"saves90": 1.0, "goals_prevented90": 0.8, "clean_sheet_pct": 0.6}},
    {"slot": "RB", "tags": ["RB", "WB", "DF"], "profile": {"tackles90": 0.7, "passes_completed90": 0.5, "key_passes90": 0.4}},
    {"slot": "CB1", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "interceptions90": 0.8, "clearances90": 0.9}},
    {"slot": "CB2", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "interceptions90": 0.8, "clearances90": 0.9}},
    {"slot": "LB", "tags": ["LB", "WB", "DF"], "profile": {"tackles90": 0.7, "passes_completed90": 0.5, "key_passes90": 0.4}},
]

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
    "4-3-3 flat": [
        *_BACK_FOUR,
        {"slot": "DM", "tags": ["DM", "CM", "MF"], "profile": {"tackles90": 0.8, "interceptions90": 0.7, "passes_completed90": 0.5, "clearances90": 0.4}},
        {"slot": "CM1", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6, "key_passes90": 0.4, "interceptions90": 0.4}},
        {"slot": "CM2", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6, "key_passes90": 0.4, "interceptions90": 0.4}},
        {"slot": "RW", "tags": ["RW", "RM", "FW", "MF"], "profile": {"dribbles90": 0.8, "key_passes90": 0.6, "xa90": 0.6, "xg90": 0.4}},
        {"slot": "ST", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 1.0, "shots90": 0.9, "shots_on_target90": 0.7}},
        {"slot": "LW", "tags": ["LW", "LM", "FW", "MF"], "profile": {"dribbles90": 0.8, "key_passes90": 0.6, "xa90": 0.6, "xg90": 0.4}},
    ],
    "4-3-3 attacking": [
        *_BACK_FOUR,
        {"slot": "DM", "tags": ["DM", "CM", "MF"], "profile": {"tackles90": 0.8, "interceptions90": 0.7, "passes_completed90": 0.5, "clearances90": 0.4}},
        {"slot": "CM", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6, "key_passes90": 0.4, "interceptions90": 0.4}},
        {"slot": "AM", "tags": ["AM", "CM", "MF"], "profile": {"key_passes90": 0.8, "xa90": 0.7, "dribbles90": 0.5}},
        {"slot": "RW", "tags": ["RW", "RM", "FW", "MF"], "profile": {"dribbles90": 0.8, "key_passes90": 0.6, "xa90": 0.6, "xg90": 0.4}},
        {"slot": "ST", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 1.0, "shots90": 0.9, "shots_on_target90": 0.7}},
        {"slot": "LW", "tags": ["LW", "LM", "FW", "MF"], "profile": {"dribbles90": 0.8, "key_passes90": 0.6, "xa90": 0.6, "xg90": 0.4}},
    ],
    "4-3-1-2 diamond": [
        *_BACK_FOUR,
        {"slot": "DM", "tags": ["DM", "CM", "MF"], "profile": {"tackles90": 0.8, "interceptions90": 0.7, "passes_completed90": 0.5, "clearances90": 0.4}},
        {"slot": "CM1", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6, "key_passes90": 0.4, "interceptions90": 0.4}},
        {"slot": "CM2", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6, "key_passes90": 0.4, "interceptions90": 0.4}},
        {"slot": "AM", "tags": ["AM", "CM", "MF"], "profile": {"key_passes90": 0.8, "xa90": 0.7, "dribbles90": 0.5}},
        {"slot": "CF1", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 0.9, "shots90": 0.8, "shots_on_target90": 0.6}},
        {"slot": "CF2", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 0.9, "shots90": 0.8, "shots_on_target90": 0.6}},
    ],
    "3-4-1-2 (flat)": [
        {"slot": "GK", "tags": ["GK"], "profile": {"saves90": 1.0, "goals_prevented90": 0.8, "clean_sheet_pct": 0.6}},
        {"slot": "CB1", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9, "interceptions90": 0.7}},
        {"slot": "CB2", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9, "interceptions90": 0.7}},
        {"slot": "CB3", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9, "interceptions90": 0.7}},
        {"slot": "LM", "tags": ["LW", "LM", "WB", "LB", "MF"], "profile": {"key_passes90": 0.6, "dribbles90": 0.6, "xa90": 0.5, "tackles90": 0.5}},
        {"slot": "DM1", "tags": ["DM", "CM", "MF"], "profile": {"tackles90": 0.8, "interceptions90": 0.7, "passes_completed90": 0.5}},
        {"slot": "DM2", "tags": ["DM", "CM", "MF"], "profile": {"tackles90": 0.8, "interceptions90": 0.7, "passes_completed90": 0.5}},
        {"slot": "RM", "tags": ["RW", "RM", "WB", "RB", "MF"], "profile": {"key_passes90": 0.6, "dribbles90": 0.6, "xa90": 0.5, "tackles90": 0.5}},
        {"slot": "AM", "tags": ["AM", "CM", "MF"], "profile": {"key_passes90": 0.8, "xa90": 0.7, "dribbles90": 0.5}},
        {"slot": "CF1", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 0.9, "shots90": 0.8, "shots_on_target90": 0.6}},
        {"slot": "CF2", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 0.9, "shots90": 0.8, "shots_on_target90": 0.6}},
    ],
    "3-4-1-2 (normal)": [
        {"slot": "GK", "tags": ["GK"], "profile": {"saves90": 1.0, "goals_prevented90": 0.8, "clean_sheet_pct": 0.6}},
        {"slot": "CB1", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9, "interceptions90": 0.7}},
        {"slot": "CB2", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9, "interceptions90": 0.7}},
        {"slot": "CB3", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9, "interceptions90": 0.7}},
        {"slot": "LM", "tags": ["LW", "LM", "WB", "LB", "MF"], "profile": {"key_passes90": 0.6, "dribbles90": 0.6, "xa90": 0.5, "tackles90": 0.5}},
        {"slot": "DM", "tags": ["DM", "CM", "MF"], "profile": {"tackles90": 0.8, "interceptions90": 0.7, "passes_completed90": 0.5}},
        {"slot": "CM", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6, "key_passes90": 0.4, "interceptions90": 0.4}},
        {"slot": "RM", "tags": ["RW", "RM", "WB", "RB", "MF"], "profile": {"key_passes90": 0.6, "dribbles90": 0.6, "xa90": 0.5, "tackles90": 0.5}},
        {"slot": "AM", "tags": ["AM", "CM", "MF"], "profile": {"key_passes90": 0.8, "xa90": 0.7, "dribbles90": 0.5}},
        {"slot": "CF1", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 0.9, "shots90": 0.8, "shots_on_target90": 0.6}},
        {"slot": "CF2", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 0.9, "shots90": 0.8, "shots_on_target90": 0.6}},
    ],
    "3-5-2": [
        {"slot": "GK", "tags": ["GK"], "profile": {"saves90": 1.0, "goals_prevented90": 0.8, "clean_sheet_pct": 0.6}},
        {"slot": "CB1", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9, "interceptions90": 0.7}},
        {"slot": "CB2", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9, "interceptions90": 0.7}},
        {"slot": "CB3", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9, "interceptions90": 0.7}},
        {"slot": "RWB", "tags": ["RB", "WB", "RM", "RW", "DF"], "profile": {"key_passes90": 0.6, "tackles90": 0.6, "dribbles90": 0.5}},
        {"slot": "CM1", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6, "interceptions90": 0.4}},
        {"slot": "CM2", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6, "interceptions90": 0.4}},
        {"slot": "CM3", "tags": ["CM", "AM", "MF"], "profile": {"key_passes90": 0.6, "xa90": 0.5, "passes_completed90": 0.5}},
        {"slot": "LWB", "tags": ["LB", "WB", "LM", "LW", "DF"], "profile": {"key_passes90": 0.6, "tackles90": 0.6, "dribbles90": 0.5}},
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
    # Balanced wingbacks: help defend and attack; less forward than LM/RM.
    "3-4-3(1)": [
        {"slot": "GK", "tags": ["GK"], "profile": {"saves90": 1.0, "goals_prevented90": 0.8, "clean_sheet_pct": 0.6}},
        {"slot": "CB1", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9}},
        {"slot": "CB2", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9}},
        {"slot": "CB3", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9}},
        {"slot": "RWB", "tags": ["RB", "WB", "RM", "RW", "DF"], "profile": {"key_passes90": 0.55, "tackles90": 0.65, "dribbles90": 0.45, "xa90": 0.4}},
        {"slot": "CM1", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6}},
        {"slot": "CM2", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6}},
        {"slot": "LWB", "tags": ["LB", "WB", "LM", "LW", "DF"], "profile": {"key_passes90": 0.55, "tackles90": 0.65, "dribbles90": 0.45, "xa90": 0.4}},
        {"slot": "RW", "tags": ["RW", "FW", "MF"], "profile": {"xg90": 0.7, "dribbles90": 0.8, "key_passes90": 0.6}},
        {"slot": "ST", "tags": ["ST", "CF", "FW"], "profile": {"xg90": 1.0, "shots90": 0.9}},
        {"slot": "LW", "tags": ["LW", "FW", "MF"], "profile": {"xg90": 0.7, "dribbles90": 0.8, "key_passes90": 0.6}},
    ],
    # Attacking wide mids: push higher, defend less → more attack, higher transition risk.
    "3-4-3(2)": [
        {"slot": "GK", "tags": ["GK"], "profile": {"saves90": 1.0, "goals_prevented90": 0.8, "clean_sheet_pct": 0.6}},
        {"slot": "CB1", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9}},
        {"slot": "CB2", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9}},
        {"slot": "CB3", "tags": ["CB", "DF"], "profile": {"tackles90": 0.8, "clearances90": 0.9}},
        {"slot": "RM", "tags": ["RW", "RM", "WB", "RB", "MF"], "profile": {"key_passes90": 0.65, "dribbles90": 0.7, "xa90": 0.55, "shots90": 0.35, "tackles90": 0.35}},
        {"slot": "CM1", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6}},
        {"slot": "CM2", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6}},
        {"slot": "LM", "tags": ["LW", "LM", "WB", "LB", "MF"], "profile": {"key_passes90": 0.65, "dribbles90": 0.7, "xa90": 0.55, "shots90": 0.35, "tackles90": 0.35}},
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


def normalize_formation(formation: str, *, fallback: str | None = DEFAULT_FORMATION) -> str:
    """Map legacy names to supported formations; default unknown values."""
    text = (formation or "").strip()
    if text in _LEGACY_FORMATION_ALIASES:
        return _LEGACY_FORMATION_ALIASES[text]
    if text in FORMATION_SLOTS:
        return text
    return fallback if fallback is not None else text


def supported_formations() -> list[str]:
    return sorted(FORMATION_SLOTS.keys())


def get_slot_definition(formation: str, slot_name: str) -> dict[str, Any] | None:
    resolved = normalize_formation(formation, fallback=formation)
    for s in FORMATION_SLOTS.get(resolved, FORMATION_SLOTS[DEFAULT_FORMATION]):
        if s["slot"] == slot_name:
            return s
    return None


_WIDE_SLOT_TAGS = frozenset({"RW", "LW", "RM", "LM"})
_WINGBACK_SLOT_TAGS = frozenset({"RWB", "LWB"})
_WIDE_ROLE_TAGS = _WIDE_SLOT_TAGS | _WINGBACK_SLOT_TAGS
_FULLBACK_TAGS = frozenset({"LB", "RB", "WB"})
_CENTRE_BACK_SLOT_TAGS = frozenset({"CB", "DF"})
_DEFENCE_LINE_TAGS = frozenset({"CB", "LB", "RB", "WB", "DF", "DEF"})
_OUTFIELD_MID_TAGS = frozenset({"CM", "DM", "AM", "MF", "MID"})
_CB_POSSESSION_PROFILE: dict[str, float] = {
    "passes_completed90": 0.35,
    "xg_buildup90": 0.25,
}


def _stat_rate(player: PlayerStats, field: str) -> float:
    val = float(getattr(player, field, 0.0) or 0.0)
    if val > 0:
        return val
    return float(getattr(player, f"understat_{field}", 0.0) or 0.0)


def _player_position_tags(player: PlayerStats) -> set[str]:
    """Expand declared positions using per-90 profile (wingbacks, wide forwards)."""
    primary = player.primary_position.upper()
    fpl = player.fpl_position.upper()
    tags = {p.upper() for p in player.positions} | {primary, fpl}

    kp = _stat_rate(player, "key_passes90")
    dribbles = _stat_rate(player, "dribbles90")
    assists = _stat_rate(player, "assists90")
    clearances = _stat_rate(player, "clearances90")

    is_fullback = bool(tags & _FULLBACK_TAGS) or primary in _FULLBACK_TAGS
    attacking_fullback = is_fullback and (
        kp >= 0.9 or dribbles >= 1.0 or (assists >= 0.18 and kp >= 0.75)
    )
    if attacking_fullback:
        tags.add("WB")
        if "LB" in tags or primary == "LB":
            tags.update({"LM", "LWB", "LW"})
        if "RB" in tags or primary == "RB":
            tags.update({"RM", "RWB", "RW"})

    wide_forward = (
        fpl == "FWD"
        or primary in {"RW", "LW", "ST", "CF", "FW"}
        or bool(tags & {"RW", "LW", "ST", "CF", "FW"})
    )
    if wide_forward and kp >= 1.0 and (dribbles >= 1.0 or assists >= 0.12):
        tags.update({"RW", "RM", "LW", "LM"})
    elif wide_forward and primary in {"ST", "CF", "FW"} and kp >= 1.5 and clearances < 2.0:
        tags.update({"RW", "RM"})

    return tags


def _declared_role_tags(player: PlayerStats) -> set[str]:
    return {p.upper() for p in player.positions}


def _is_centre_back_slot(tags: set[str]) -> bool:
    return bool(tags & {"CB"}) and not bool(tags & _WIDE_ROLE_TAGS)


def _is_pure_centre_back(player: PlayerStats) -> bool:
    primary = player.primary_position.upper()
    declared = _declared_role_tags(player)
    if primary != "CB":
        return False
    outfield = declared - {"GK"}
    if outfield & _OUTFIELD_MID_TAGS:
        return False
    if outfield & {"RW", "LW", "ST", "CF", "FW"}:
        return False
    return not bool(outfield - _DEFENCE_LINE_TAGS)


def _is_multi_positional_cb(player: PlayerStats) -> bool:
    declared = _declared_role_tags(player)
    primary = player.primary_position.upper()
    has_cb = "CB" in declared or primary == "CB"
    has_mid = bool(declared & _OUTFIELD_MID_TAGS)
    return has_cb and has_mid


def _centre_back_position_match(player: PlayerStats, player_tags: set[str]) -> float | None:
    """Score natural centre-backs above generic/multi-role defenders at CB slots."""
    primary = player.primary_position.upper()
    fpl = player.fpl_position.upper()
    declared = _declared_role_tags(player)

    if _is_pure_centre_back(player):
        return 1.0
    if _is_multi_positional_cb(player):
        return 0.88
    if primary in _OUTFIELD_MID_TAGS and ("CB" in player_tags or "CB" in declared):
        return 0.82
    if primary in _CENTRE_BACK_SLOT_TAGS and "CB" in declared:
        return 0.95
    if primary in {"DF", "DEF"} or (fpl == "DEF" and primary not in {"LB", "RB", "WB"}):
        if "CB" in player_tags or "CB" in declared:
            return 0.95
        return 0.85
    return None


def _position_match(player: PlayerStats, slot_def: dict[str, Any]) -> float:
    tags = {t.upper() for t in slot_def["tags"]}
    is_gk_slot = tags == {"GK"}
    primary = player.primary_position.upper()
    fpl = player.fpl_position.upper()
    player_tags = _player_position_tags(player)
    wide_slots = _WIDE_SLOT_TAGS

    if fpl == "GK" or primary == "GK":
        return 1.0 if is_gk_slot else 0.02

    if is_gk_slot:
        return 0.02

    if _is_centre_back_slot(tags):
        cb_match = _centre_back_position_match(player, player_tags)
        if cb_match is not None:
            return cb_match

    if primary in tags:
        return 1.0
    if tags & player_tags:
        return 0.85
    # Wingback / wide-mid slots: fullbacks and creative forwards still fit wide roles.
    if tags & _WIDE_ROLE_TAGS:
        if player_tags & wide_slots:
            return 0.85
        if player_tags & _FULLBACK_TAGS and ("WB" in tags or tags & _WINGBACK_SLOT_TAGS or tags & wide_slots):
            return 0.92
        if fpl == "FWD" and primary in {"ST", "CF", "FW"}:
            kp = _stat_rate(player, "key_passes90")
            dribbles = _stat_rate(player, "dribbles90")
            if kp >= 1.0 and dribbles >= 1.0:
                return 0.85
            return 0.72
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


def _centre_back_profile_fit(stats: PlayerStats, profile: dict[str, float]) -> float:
    """Blend defensive actions with build-up/passing so possession CBs aren't underrated."""
    merged = dict(profile)
    for stat, weight in _CB_POSSESSION_PROFILE.items():
        merged[stat] = max(merged.get(stat, 0.0), weight)
    if "clearances90" in merged:
        merged["clearances90"] = min(float(merged["clearances90"]), 0.75)
    return _profile_fit(stats, merged)


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
    fb = fallbacks.get(stat)
    if fb and float(fb) > 0:
        return float(fb)
    if stat == "dribbles90":
        kp = float(stats.key_passes90 or stats.understat_key_passes90)
        ast = float(stats.assists90)
        if kp > 0 or ast > 0:
            return min(3.0, kp * 0.32 + ast * 0.55)
    return 0.0


def _preferred_foot_bonus(stats: PlayerStats, slot_name: str) -> float:
    foot = (stats.preferred_foot or "").lower()
    if not foot:
        return 0.0
    slot = slot_name.upper()
    if slot in {"LW", "LM", "LWB"} and foot == "left":
        return 0.04
    if slot in {"RW", "RM", "RWB"} and foot == "right":
        return 0.04
    if foot == "both":
        return 0.02
    return 0.0


def player_slot_fit(stats: PlayerStats, formation: str, slot_name: str) -> float:
    formation = normalize_formation(formation)
    slot_def = get_slot_definition(formation, slot_name)
    if slot_def is None:
        return 0.5
    pos = _position_match(stats, slot_def)
    base_profile = slot_def.get("profile", {})
    slot_tags = {t.upper() for t in slot_def["tags"]}
    if _is_centre_back_slot(slot_tags):
        prof = _centre_back_profile_fit(stats, base_profile)
    else:
        prof = _profile_fit(stats, base_profile)
    return max(0.25, min(1.0, 0.62 * pos + 0.38 * prof + _preferred_foot_bonus(stats, slot_name)))


def team_formation_fit(
    formation: str,
    lineup: list[tuple[str, str]],
    player_stats: dict[str, PlayerStats],
) -> dict[str, Any]:
    formation = normalize_formation(formation)
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
