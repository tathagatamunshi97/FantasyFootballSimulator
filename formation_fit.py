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
        {"slot": "CM", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6, "key_passes90": 0.4, "interceptions90": 0.4}},
        {"slot": "DM", "tags": ["DM", "CM", "MF"], "profile": {"tackles90": 0.8, "interceptions90": 0.7, "passes_completed90": 0.5, "clearances90": 0.4}},
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
        {"slot": "DM", "tags": ["DM", "CM", "MF"], "profile": {"tackles90": 0.8, "interceptions90": 0.7, "passes_completed90": 0.5}},
        {"slot": "CM2", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6, "interceptions90": 0.4}},
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
        {"slot": "DM", "tags": ["DM", "CM", "MF"], "profile": {"tackles90": 0.8, "interceptions90": 0.7, "passes_completed90": 0.5}},
        {"slot": "CM", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6}},
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
        {"slot": "DM", "tags": ["DM", "CM", "MF"], "profile": {"tackles90": 0.8, "interceptions90": 0.7, "passes_completed90": 0.5}},
        {"slot": "CM", "tags": ["CM", "DM", "MF"], "profile": {"passes_completed90": 0.7, "tackles90": 0.6}},
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
_RIGHT_FULLBACK_ROLES = frozenset({"RB", "RWB"})
_LEFT_FULLBACK_ROLES = frozenset({"LB", "LWB"})
_LEFT_SIDE_FB_SLOTS = frozenset({"LB", "LWB"})
_RIGHT_SIDE_FB_SLOTS = frozenset({"RB", "RWB"})
_CENTRE_BACK_SLOT_TAGS = frozenset({"CB", "DF"})
_DEFENCE_LINE_TAGS = frozenset({"CB", "LB", "RB", "WB", "DF", "DEF"})
_OUTFIELD_MID_TAGS = frozenset({"CM", "DM", "AM", "MF", "MID"})
_CB_POSSESSION_PROFILE: dict[str, float] = {
    "passes_completed90": 0.35,
    "xg_buildup90": 0.25,
}
# Predominant/natural players at their slot belong in the ~0.9+ band.
# Global 0.62/0.38 blend over-weights per-90 profile_fit: midfielder-biased
# STAT_CAPS + missing FBref zeros (scored as 0) drag profile to ~0.3–0.65 even
# when position_match is 1.0 — yielding systemic ~0.62–0.79 fits for natural
# GK/RW/LW/DM/ST/CB placements. Reweight toward position and floor naturals.
_NATURAL_POS_WEIGHT = 0.80
_NATURAL_PROF_WEIGHT = 0.20
_NATURAL_FLOOR = 0.90  # pos_match >= threshold → floor at 0.90
_NATURAL_POS_THRESHOLD = 0.95
# Back-compat aliases (CB-era names used by spot-check scripts).
_CB_POS_WEIGHT = _NATURAL_POS_WEIGHT
_CB_PROF_WEIGHT = _NATURAL_PROF_WEIGHT
_CB_NATURAL_FLOOR = _NATURAL_FLOOR
_CB_NATURAL_POS_THRESHOLD = _NATURAL_POS_THRESHOLD
_DEFAULT_POS_WEIGHT = 0.62
_DEFAULT_PROF_WEIGHT = 0.38
_GENERIC_POS_TAGS = frozenset({"MF", "FW", "DF", "DEF", "MID", "FWD"})
_MIDFIELD_BUCKET_TAGS = frozenset({"CM", "MF", "MID", "AM", "CAM"})
# Natural RB/RWB (right foot) at LB/LWB — and the LB/LWB + left @ RB/RWB mirror.
# Missing preferred_foot still hurts opposite-flank FBs, but less than when foot
# confirms they are on their weak side. Never invent a foot.
_WEAK_SIDE_FOOT_CONFIRMED = -0.12
_WEAK_SIDE_MISSING_FOOT = -0.06
# Caps tuned to centre-back volume (not shared midfielder ceilings).
_CB_STAT_CAPS: dict[str, float] = {
    "tackles90": 2.5,
    "interceptions90": 2.2,
    "clearances90": 7.0,
    "passes_completed90": 70.0,
    "xg_buildup90": 0.55,
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

    # FBref/Sofascore often bucket out-and-out wingers as CM/MF. Promote wing
    # tags from the per-90 attack profile so RW/LW slots see a natural match.
    # Thresholds tolerate minutes-credibility shrink toward CM priors (m0=1000):
    # e.g. Luis Díaz raw dribbles ~2.1 → ~1.70 after dampening, which failed the
    # old 1.8 cut and left him CM-only (~0.60 LW fit).
    xa = _stat_rate(player, "xa90")
    xg = _stat_rate(player, "xg90")
    goals = _stat_rate(player, "goals90")
    shots = _stat_rate(player, "shots90")
    mid_bucket = (
        primary in _MIDFIELD_BUCKET_TAGS
        or fpl == "MID"
        or bool(tags & _MIDFIELD_BUCKET_TAGS)
    ) and not bool(tags & {"ST", "CF", "FW", "RW", "LW"})
    creative_carry = dribbles >= 1.45 and kp >= 0.9 and (
        xg >= 0.12 or assists >= 0.10 or xa >= 0.12
    )
    goal_threat_wide = (
        clearances < 1.2
        and shots >= 1.8
        and (xg >= 0.22 or goals >= 0.22)
        and (dribbles >= 1.2 or kp >= 0.9)
    )
    wing_attack_profile = clearances < 1.5 and (creative_carry or goal_threat_wide)
    if mid_bucket and wing_attack_profile:
        tags.update({"RW", "RM", "LW", "LM", "FW"})

    return tags


def _declared_role_tags(player: PlayerStats) -> set[str]:
    return {p.upper() for p in player.positions}


def _is_centre_back_slot(tags: set[str]) -> bool:
    return bool(tags & {"CB"}) and not bool(tags & _WIDE_ROLE_TAGS)


def _is_pure_centre_back(player: PlayerStats) -> bool:
    """True when the player predominantly plays centre-back (not FB/mid hybrid)."""
    primary = player.primary_position.upper()
    declared = _declared_role_tags(player)
    # DF/DEF buckets from FBref map to centre-back when no fullback tags exist.
    if primary not in {"CB", "DF", "DEF"}:
        return False
    if primary in {"DF", "DEF"} and declared & _FULLBACK_TAGS:
        return False
    outfield = declared - {"GK", "DF", "DEF"}
    if not outfield and primary in {"CB", "DF", "DEF"}:
        return True
    if outfield & _OUTFIELD_MID_TAGS:
        return False
    if outfield & {"RW", "LW", "ST", "CF", "FW"}:
        return False
    # Defence-line only (CB and optional FB tags still OK if primary is CB/DF).
    if outfield & _FULLBACK_TAGS and primary != "CB":
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
    # Specific role tags (RW/LW/DM/ST/…) beat generic MF/FW/DF buckets — a
    # winger recovered via profile tags should score as natural on that wing.
    # Bare WB overlap alone is not sided enough for the natural band (RB≠LB).
    specific_slot = tags - _GENERIC_POS_TAGS
    specific_player = player_tags - _GENERIC_POS_TAGS
    sided_overlap = (specific_slot - {"WB"}) & (specific_player - {"WB"})
    if sided_overlap:
        return 0.98
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


def _profile_fit(
    stats: PlayerStats,
    profile: dict[str, float],
    *,
    skip_missing: bool = False,
    caps: dict[str, float] | None = None,
) -> float:
    if not profile:
        return 0.65
    cap_table = caps or STAT_CAPS
    scores: list[float] = []
    weights: list[float] = []
    for stat, weight in profile.items():
        raw_val = _fit_stat_value(stats, stat)
        if skip_missing and raw_val <= 0:
            # Missing source fields (common on FBref primes) must not score as 0.
            continue
        cap = cap_table.get(stat, STAT_CAPS.get(stat, 1.0))
        raw = raw_val / cap if cap else 0.0
        scores.append(min(1.0, raw) * weight)
        weights.append(weight)
    if not weights:
        return 0.65
    return sum(scores) / max(sum(weights), 1e-6)


def _centre_back_profile_fit(stats: PlayerStats, profile: dict[str, float]) -> float:
    """Blend defensive actions with build-up/passing so possession CBs aren't underrated."""
    merged = dict(profile)
    for stat, weight in _CB_POSSESSION_PROFILE.items():
        # Only reward possession metrics when present — FBref often leaves passes at 0.
        if float(getattr(stats, stat, 0.0) or 0.0) > 0:
            merged[stat] = max(merged.get(stat, 0.0), weight)
    if "clearances90" in merged:
        merged["clearances90"] = min(float(merged["clearances90"]), 0.75)
    return _profile_fit(stats, merged, skip_missing=True, caps=_CB_STAT_CAPS)


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


def _natural_fullback_side(player: PlayerStats) -> str | None:
    """Usual flank for a fullback/wingback: 'right', 'left', or None if unclear.

    Primary RB/RWB (or LB/LWB) wins. If primary is unsided (e.g. WB) but declared
    roles only cover one flank, use that flank. Players listed on both sides with
    an unsided primary are treated as versatile (no weak-side penalty).
    """
    primary = player.primary_position.upper()
    declared = {p.upper() for p in player.positions} | {primary}
    if primary in _RIGHT_FULLBACK_ROLES:
        return "right"
    if primary in _LEFT_FULLBACK_ROLES:
        return "left"
    has_right = bool(declared & _RIGHT_FULLBACK_ROLES)
    has_left = bool(declared & _LEFT_FULLBACK_ROLES)
    if has_right and not has_left:
        return "right"
    if has_left and not has_right:
        return "left"
    return None


def _preferred_foot_bonus(stats: PlayerStats, slot_name: str) -> float:
    foot = (stats.preferred_foot or "").lower()
    if not foot:
        return 0.0
    slot = slot_name.upper()
    if slot in {"LW", "LM", "LWB", "LB"} and foot == "left":
        return 0.04
    if slot in {"RW", "RM", "RWB", "RB"} and foot == "right":
        return 0.04
    if foot == "both":
        return 0.02
    return 0.0


def _weak_side_fullback_penalty(stats: PlayerStats, slot_name: str) -> float:
    """Penalise natural right-siders at LB/LWB (and left-siders at RB/RWB).

    Confirmed when preferred foot matches the natural flank (RB+right @ LB).
    Milder when foot is missing. No penalty when foot is 'both', when the player
    has no clear natural flank, or when foot contradicts (inverted FB).
    """
    slot = slot_name.upper()
    natural = _natural_fullback_side(stats)
    if natural is None:
        return 0.0
    on_wrong_flank = (natural == "right" and slot in _LEFT_SIDE_FB_SLOTS) or (
        natural == "left" and slot in _RIGHT_SIDE_FB_SLOTS
    )
    if not on_wrong_flank:
        return 0.0
    foot = (stats.preferred_foot or "").lower().strip()
    if foot in {"both", "either"}:
        return 0.0
    if not foot:
        return _WEAK_SIDE_MISSING_FOOT
    if natural == "right" and foot == "right":
        return _WEAK_SIDE_FOOT_CONFIRMED
    if natural == "left" and foot == "left":
        return _WEAK_SIDE_FOOT_CONFIRMED
    # Opposite foot on the "wrong" flank (inverted fullback) — no extra hit.
    return 0.0


def _slot_def_for_filter(formation: str, slot_name: str, role_filter: str | None) -> dict[str, Any] | None:
    """Resolve slot definition, preferring the remapped role when a filter is set."""
    from slot_roles import effective_slot_name, normalize_role_filter, allowed_role_filters

    natural = get_slot_definition(formation, slot_name)
    if not allowed_role_filters(slot_name):
        return natural
    rf = normalize_role_filter(slot_name, role_filter)
    opts = allowed_role_filters(slot_name)
    if not opts or rf == opts[0]:
        return natural
    eff = effective_slot_name(slot_name, rf)
    found = get_slot_definition(formation, eff)
    if found:
        return found
    for form in FORMATION_SLOTS:
        found = get_slot_definition(form, eff)
        if found:
            return found
    if natural:
        return {**natural, "slot": eff, "tags": [eff, *list(natural.get("tags") or [])]}
    return {"slot": eff, "tags": [eff], "profile": {}}


def player_slot_fit(
    stats: PlayerStats,
    formation: str,
    slot_name: str,
    role_filter: str | None = None,
) -> float:
    formation = normalize_formation(formation)
    slot_def = _slot_def_for_filter(formation, slot_name, role_filter)
    if slot_def is None:
        return 0.5
    from slot_roles import effective_slot_name

    foot_slot = effective_slot_name(slot_name, role_filter)
    pos = _position_match(stats, slot_def)
    base_profile = slot_def.get("profile", {})
    slot_tags = {t.upper() for t in slot_def["tags"]}
    # Natural GKs at GK are always a perfect fit — never dilute with save volume.
    if slot_tags <= {"GK"} and (stats.primary_position.upper() == "GK" or stats.fpl_position.upper() == "GK"):
        return 1.0
    foot = _preferred_foot_bonus(stats, foot_slot) + _weak_side_fullback_penalty(stats, foot_slot)
    if _is_centre_back_slot(slot_tags):
        prof = _centre_back_profile_fit(stats, base_profile)
    else:
        # Skip missing source fields so absent FBref zeros do not drag profile.
        prof = _profile_fit(stats, base_profile, skip_missing=True)
    blend = _NATURAL_POS_WEIGHT * pos + _NATURAL_PROF_WEIGHT * prof
    # Predominant/natural role match: profile only differentiates within/above
    # the natural band (never below it). Foot / weak-side apply after the floor
    # so opposite-flank fullbacks stay penalised.
    if pos >= _NATURAL_POS_THRESHOLD:
        blend = max(blend, _NATURAL_FLOOR)
    fit = blend + foot
    return max(0.25, min(1.0, fit))


def team_formation_fit(
    formation: str,
    lineup: list[tuple[str, str]] | list[tuple[str, str, str]],
    player_stats: dict[str, PlayerStats],
) -> dict[str, Any]:
    formation = normalize_formation(formation)
    rows = []
    fits = []
    for item in lineup:
        if len(item) >= 3:
            player_name, slot, role_filter = item[0], item[1], item[2]
        else:
            player_name, slot = item[0], item[1]
            role_filter = ""
        stats = player_stats.get(player_name)
        if stats is None:
            rows.append(
                {
                    "player": player_name,
                    "slot": slot,
                    "role_filter": role_filter or "",
                    "fit": 0.4,
                    "missing_stats": True,
                }
            )
            fits.append(0.4)
            continue
        fit = player_slot_fit(stats, formation, slot, role_filter=role_filter or None)
        rows.append(
            {
                "player": player_name,
                "slot": slot,
                "role_filter": (role_filter or "").strip().upper(),
                "fit": round(fit, 3),
                "position": stats.primary_position,
            }
        )
        fits.append(fit)
    avg = sum(fits) / len(fits) if fits else 0.5
    return {"formation": formation, "average_fit": round(avg, 3), "players": rows}
