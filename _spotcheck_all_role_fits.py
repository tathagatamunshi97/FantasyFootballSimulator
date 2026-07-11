#!/usr/bin/env python3
"""Spot-check natural-role slot fits (GK/RW/LW/DM/CB) after fit formula v3."""
from __future__ import annotations

import json
from pathlib import Path

from formation_fit import (
    _NATURAL_FLOOR,
    _position_match,
    _profile_fit,
    _player_position_tags,
    get_slot_definition,
    player_slot_fit,
)
from models import PlayerStats

ROOT = Path(__file__).resolve().parent
FORMATION = "4-3-3 flat"
cache = json.loads((ROOT / "data" / "player_stats_cache.json").read_text(encoding="utf-8"))

CASES = [
    ("Lamine Yamal", "RW", 0.90),
    ("Mike Maignan", "GK", 1.00),
    ("Luis Díaz", "LW", 0.90),
    ("Fernandinho", "DM", 0.90),
    ("Leandro Trossard", "LW", 0.90),
    ("William Saliba", "CB1", 0.90),
    ("Virgil van Dijk", "CB1", 0.90),
]

MISMATCHES = [
    ("Lamine Yamal", "CB1", 0.50),  # winger at CB must stay weak
    ("Mike Maignan", "ST", 0.25),  # GK outfield hits absolute floor
]


def load(name: str) -> PlayerStats | None:
    data = cache.get("players", {}).get(name)
    if not data:
        return None
    return PlayerStats.from_dict(name, dict(data))


print(f"{'Player':<22} {'slot':<5} {'pos':>5} {'prof':>5} {'fit':>5} {'min':>5} ok?")
print("-" * 60)
failures: list[str] = []
for name, slot, minimum in CASES:
    st = load(name)
    if st is None:
        failures.append(f"{name} missing from cache")
        print(f"{name:<22} MISSING")
        continue
    slot_def = get_slot_definition(FORMATION, slot)
    assert slot_def is not None
    pos = _position_match(st, slot_def)
    if slot.upper() == "GK":
        prof = 1.0
    elif slot.upper().startswith("CB"):
        from formation_fit import _centre_back_profile_fit

        prof = _centre_back_profile_fit(st, slot_def.get("profile", {}))
    else:
        prof = _profile_fit(st, slot_def.get("profile", {}), skip_missing=True)
    fit = player_slot_fit(st, FORMATION, slot)
    ok = fit + 1e-9 >= minimum
    if not ok:
        failures.append(f"{name}@{slot} fit={fit:.3f} < {minimum}")
    print(
        f"{name:<22} {slot:<5} {pos:5.3f} {prof:5.3f} {fit:5.3f} {minimum:5.2f} "
        f"{'OK' if ok else 'FAIL'}  tags={sorted(_player_position_tags(st))}"
    )

print("\nMismatch sanity (must stay low):")
for name, slot, maximum in MISMATCHES:
    st = load(name)
    if st is None:
        continue
    fit = player_slot_fit(st, FORMATION, slot)
    ok = fit <= maximum
    if not ok:
        failures.append(f"{name}@{slot} fit={fit:.3f} > {maximum} (mismatch too high)")
    print(f"  {name}@{slot} fit={fit:.3f} (max {maximum}) {'OK' if ok else 'FAIL'}")

# Weak-side FB still differentiated.
reece = load("Reece James")
if reece is not None:
    rb = player_slot_fit(reece, FORMATION, "RB")
    lb = player_slot_fit(reece, FORMATION, "LB")
    ok = rb > lb
    if not ok:
        failures.append(f"Reece James RB ({rb:.3f}) should beat LB ({lb:.3f})")
    print(f"\nReece James RB={rb:.3f} LB={lb:.3f} ({'OK' if ok else 'FAIL'})")

print(f"\nNatural floor constant={_NATURAL_FLOOR}")
if failures:
    print("FAILURES:")
    for f in failures:
        print(" -", f)
    raise SystemExit(1)
print("\nOK: natural-role fits and mismatch checks passed.")
