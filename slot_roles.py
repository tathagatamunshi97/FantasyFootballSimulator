"""Formation slot roles and unit-routing weights."""
from __future__ import annotations

from dataclasses import dataclass

from models import FplPosition

FULLBACK_SLOTS = frozenset({"RB", "LB", "RWB", "LWB"})
CENTRE_BACK_SLOTS = frozenset({"CB1", "CB2", "CB3"})
DM_SLOTS = frozenset({"DM", "DM1", "DM2"})
CM_SLOTS = frozenset({"CM", "CM1", "CM2", "CM3"})
AM_SLOTS = frozenset({"AM"})
WINGER_SLOTS = frozenset({"RW", "LW", "RM", "LM"})
STRIKER_SLOTS = frozenset({"ST", "ST1", "ST2", "CF", "CF1", "CF2"})

# Optional per-slot role remaps (UI filter). First entry is the natural default.
# Locked (no options): GK, CB*, ST/CF*, RW/LW.
ROLE_FILTER_OPTIONS: dict[str, tuple[str, ...]] = {
    "AM": ("AM", "CM"),
    "CM": ("CM", "DM"),
    "DM": ("DM", "CM"),
    "LB": ("LB", "LWB"),
    "LWB": ("LWB", "LB", "LM"),
    "LM": ("LM", "LWB"),
    "RB": ("RB", "RWB"),
    "RWB": ("RWB", "RB", "RM"),
    "RM": ("RM", "RWB"),
}


def slot_filter_key(slot: str) -> str:
    """Canonical key for role-filter lookup (CM1→CM, CB2→CB, …)."""
    s = (slot or "").strip().upper()
    if s == "GK" or s == "AM":
        return s
    if s.startswith("CB"):
        return "CB"
    if s.startswith("ST") or s.startswith("CF") or s.startswith("FW"):
        return "ST"
    if s.startswith("DM"):
        return "DM"
    if s.startswith("CM"):
        return "CM"
    return s


def allowed_role_filters(slot: str) -> list[str]:
    """Allowed role labels for a formation slot; empty if locked."""
    opts = ROLE_FILTER_OPTIONS.get(slot_filter_key(slot))
    return list(opts) if opts else []


def normalize_role_filter(slot: str, role_filter: str | None) -> str:
    """Return a valid filter label, or the natural default when locked/invalid."""
    opts = ROLE_FILTER_OPTIONS.get(slot_filter_key(slot))
    if not opts:
        return slot_filter_key(slot)
    rf = (role_filter or "").strip().upper()
    if rf in opts:
        return rf
    return opts[0]


def effective_slot_name(slot: str, role_filter: str | None = None) -> str:
    """
    Slot name used for weights / board role / fit when a filter is applied.
    Natural midfield numbered slots (CM1, DM2) keep their name when unfiltered.
    """
    key = slot_filter_key(slot)
    opts = ROLE_FILTER_OPTIONS.get(key)
    if not opts:
        return slot
    rf = normalize_role_filter(slot, role_filter)
    if rf == opts[0] and key in {"CM", "DM"}:
        return slot
    return rf


def role_filters_meta() -> dict[str, list[str]]:
    """slot → allowed filter labels (only remappable slots)."""
    # Expose by concrete formation slot names via callers; here the option map itself.
    return {k: list(v) for k, v in ROLE_FILTER_OPTIONS.items()}


@dataclass(frozen=True)
class SlotUnitWeights:
    """Multipliers applied to per-player unit contribution scores."""

    attack: float
    creation: float
    midfield: float
    defence: float
    midfield_defence: float


def slot_role(slot: str) -> str:
    s = slot.upper()
    if s == "GK":
        return "gk"
    if s in FULLBACK_SLOTS:
        return "fullback"
    if s in CENTRE_BACK_SLOTS:
        return "centre_back"
    if s in DM_SLOTS:
        return "dm"
    if s in CM_SLOTS:
        return "cm"
    if s in AM_SLOTS:
        return "am"
    if s in WINGER_SLOTS:
        return "winger"
    if s in STRIKER_SLOTS:
        return "striker"
    return "unknown"


def slot_unit_weights(slot: str, fpl_position: FplPosition) -> SlotUnitWeights:
    role = slot_role(slot)
    su = slot.upper()
    if role == "fullback":
        if su in {"LWB", "RWB"}:
            # Balanced wingbacks: defend and attack, less forward than LM/RM.
            return SlotUnitWeights(
                attack=0.68, creation=0.92, midfield=0.55, defence=0.78, midfield_defence=0.34
            )
        return SlotUnitWeights(
            attack=0.72, creation=1.0, midfield=0.52, defence=0.72, midfield_defence=0.28
        )
    if role == "centre_back":
        return SlotUnitWeights(attack=0.12, creation=0.18, midfield=0.24, defence=1.0, midfield_defence=0.18)
    if role == "dm":
        return SlotUnitWeights(attack=0.34, creation=0.58, midfield=1.0, defence=0.90, midfield_defence=1.0)
    if role == "cm":
        return SlotUnitWeights(attack=0.50, creation=0.78, midfield=1.0, defence=0.40, midfield_defence=0.75)
    if role == "am":
        return SlotUnitWeights(attack=0.64, creation=0.95, midfield=1.0, defence=0.26, midfield_defence=0.38)
    if role == "winger":
        if su in {"LM", "RM"}:
            # Attacking wide mids: push higher, create more, defend less than wingbacks.
            return SlotUnitWeights(
                attack=0.95, creation=1.05, midfield=0.45, defence=0.14, midfield_defence=0.18
            )
        return SlotUnitWeights(attack=0.90, creation=0.88, midfield=0.42, defence=0.16, midfield_defence=0.22)
    if role == "striker":
        return SlotUnitWeights(attack=1.0, creation=0.52, midfield=0.22, defence=0.08, midfield_defence=0.10)

    # Unknown slot — fall back to FPL position buckets
    if fpl_position == "DEF":
        return SlotUnitWeights(attack=0.18, creation=0.35, midfield=0.35, defence=1.0, midfield_defence=0.22)
    if fpl_position == "MID":
        return SlotUnitWeights(attack=0.55, creation=0.72, midfield=1.0, defence=0.35, midfield_defence=0.65)
    if fpl_position == "FWD":
        return SlotUnitWeights(attack=1.0, creation=0.55, midfield=0.25, defence=0.10, midfield_defence=0.12)
    return SlotUnitWeights(attack=0.0, creation=0.0, midfield=0.0, defence=0.0, midfield_defence=0.0)


def slot_scorer_weight(slot: str, fpl_position: FplPosition) -> float:
    role = slot_role(slot)
    if role == "fullback":
        return 0.24
    if role == "winger":
        return 0.82
    if role == "striker":
        return 1.0
    if role == "am":
        return 0.58
    if role in {"dm", "cm"}:
        return 0.42
    if role == "centre_back":
        return 0.08
    return {"GK": 0.0, "DEF": 0.08, "MID": 0.45, "FWD": 1.0}[fpl_position]


def slot_assist_weight(slot: str) -> float:
    role = slot_role(slot)
    if role == "fullback":
        return 1.18
    if role == "winger":
        return 1.05
    if role == "am":
        return 1.08
    if role == "cm":
        return 1.0
    if role == "dm":
        return 0.88
    if role == "striker":
        return 0.75
    if role == "centre_back":
        return 0.65
    return 1.0
