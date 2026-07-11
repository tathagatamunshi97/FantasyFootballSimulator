#!/usr/bin/env python3
"""Spot-check weak-side fullback fit (RB+right @ LB / LB+left @ RB)."""
from __future__ import annotations

import json
from pathlib import Path

from formation_fit import (
    _WEAK_SIDE_FOOT_CONFIRMED,
    _WEAK_SIDE_MISSING_FOOT,
    _natural_fullback_side,
    _preferred_foot_bonus,
    _weak_side_fullback_penalty,
    player_slot_fit,
)
from models import PlayerStats

ROOT = Path(__file__).resolve().parent
FORMATION = "4-3-3 flat"
cache = json.loads((ROOT / "data" / "player_stats_cache.json").read_text(encoding="utf-8"))

CASES = [
    # natural RB, right foot → hurt at LB, strong at RB
    "Reece James",
    # natural LB, left foot → hurt at RB, strong at LB
    "Nuno Mendes",
    # natural LB, left foot (also listed RB) → still left-sided primary
    "Alphonso Davies",
    # natural RB via known override (cache may say LB), right foot
    "Achraf Hakimi",
]


def load(name: str) -> PlayerStats | None:
    data = cache.get("players", {}).get(name)
    if not data:
        return None
    return PlayerStats.from_dict(name, dict(data))


def synth_rb_no_foot() -> PlayerStats:
    return PlayerStats(
        player="Synth RB",
        primary_position="RB",
        fpl_position="DEF",
        positions=["RB"],
        preferred_foot="",
        tackles90=2.0,
        passes_completed90=40.0,
        key_passes90=0.8,
    )


print(
    f"{'Player':<18} {'nat':<6} {'foot':<6} "
    f"{'RB':>6} {'LB':>6} {'penRB':>6} {'penLB':>6} positions"
)
print("-" * 78)
for name in CASES:
    stats = load(name)
    if stats is None:
        print(f"{name:<18} MISSING")
        continue
    nat = _natural_fullback_side(stats) or "-"
    foot = (stats.preferred_foot or "-")[:5]
    fit_rb = player_slot_fit(stats, FORMATION, "RB")
    fit_lb = player_slot_fit(stats, FORMATION, "LB")
    pen_rb = _weak_side_fullback_penalty(stats, "RB")
    pen_lb = _weak_side_fullback_penalty(stats, "LB")
    print(
        f"{name:<18} {nat:<6} {foot:<6} "
        f"{fit_rb:6.3f} {fit_lb:6.3f} {pen_rb:6.2f} {pen_lb:6.2f} {stats.positions}"
    )

synth = synth_rb_no_foot()
assert _weak_side_fullback_penalty(synth, "LB") == _WEAK_SIDE_MISSING_FOOT
assert _weak_side_fullback_penalty(synth, "RB") == 0.0
assert _preferred_foot_bonus(synth, "RB") == 0.0

reece = load("Reece James")
assert reece is not None
assert _natural_fullback_side(reece) == "right"
assert reece.preferred_foot.lower() == "right"
assert _weak_side_fullback_penalty(reece, "LB") == _WEAK_SIDE_FOOT_CONFIRMED
assert _weak_side_fullback_penalty(reece, "RB") == 0.0
assert player_slot_fit(reece, FORMATION, "RB") > player_slot_fit(reece, FORMATION, "LB")

nuno = load("Nuno Mendes")
assert nuno is not None
assert _natural_fullback_side(nuno) == "left"
assert nuno.preferred_foot.lower() == "left"
assert _weak_side_fullback_penalty(nuno, "RB") == _WEAK_SIDE_FOOT_CONFIRMED
assert _weak_side_fullback_penalty(nuno, "LB") == 0.0
assert player_slot_fit(nuno, FORMATION, "LB") > player_slot_fit(nuno, FORMATION, "RB")

# CB floor still intact for a pure CB when present.
saliba = load("William Saliba")
if saliba is not None:
    cb_fit = player_slot_fit(saliba, FORMATION, "CB1")
    print(f"\nSaliba CB1 fit={cb_fit:.3f} (expect >= 0.90)")
    assert cb_fit >= 0.90

print("\nOK: weak-side penalties and CB floor checks passed.")
