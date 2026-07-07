#!/usr/bin/env python3
"""CB position fit comparison for reported misfit players."""
import json
from pathlib import Path

from formation_fit import _position_match, _profile_fit, _centre_back_profile_fit, player_slot_fit, get_slot_definition, _player_position_tags
from models import PlayerStats

ROOT = Path(__file__).resolve().parent
cache = json.loads((ROOT / "data" / "player_stats_cache.json").read_text(encoding="utf-8"))

PLAYERS = [
    "Dayot Upamecano",
    "Pau Cubarsí",
    "Eric García",
    "Dean Huijsen",
]
FORMATION = "4-3-3 flat"

# Captured before fix (4-3-3 flat / CB1, raw cache without name overrides).
BEFORE = {
    "Dayot Upamecano": {"position_match": 1.0, "profile_fit": 0.504, "total_fit": 0.812},
    "Pau Cubarsí": {"position_match": 1.0, "profile_fit": 0.451, "total_fit": 0.792},
    "Eric García": {"position_match": 1.0, "profile_fit": 0.509, "total_fit": 0.813},
    "Dean Huijsen": {"position_match": 1.0, "profile_fit": 0.659, "total_fit": 0.87},
}


def report(name: str) -> dict:
    data = dict(cache["players"][name])
    stats = PlayerStats.from_dict(name, data)
    slot_def = get_slot_definition(FORMATION, "CB1")
    pos = _position_match(stats, slot_def)
    prof = _centre_back_profile_fit(stats, slot_def.get("profile", {}))
    fit = player_slot_fit(stats, FORMATION, "CB1")
    before = BEFORE[name]
    return {
        "player": name,
        "positions": stats.positions,
        "primary_position": stats.primary_position,
        "position_match_before": before["position_match"],
        "position_match_after": round(pos, 3),
        "profile_fit_before": before["profile_fit"],
        "profile_fit_after": round(prof, 3),
        "total_fit_before": before["total_fit"],
        "total_fit_after": round(fit, 3),
    }


if __name__ == "__main__":
    rows = [report(n) for n in PLAYERS]
    print(f"{'Player':<18} {'positions':<16} {'pos(b/a)':<12} {'prof(b/a)':<14} {'total(b/a)':<14}")
    print("-" * 78)
    for row in rows:
        print(
            f"{row['player']:<18} {str(row['positions']):<16} "
            f"{row['position_match_before']:.3f}/{row['position_match_after']:.3f}   "
            f"{row['profile_fit_before']:.3f}/{row['profile_fit_after']:.3f}     "
            f"{row['total_fit_before']:.3f}/{row['total_fit_after']:.3f}"
        )
    print("\n--- JSON ---")
    print(json.dumps(rows, indent=2))
