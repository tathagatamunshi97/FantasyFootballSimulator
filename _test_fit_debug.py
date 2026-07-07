#!/usr/bin/env python3
"""Debug formation fit for reported misfit players (4-3-3 attacking)."""
import json
from pathlib import Path

from formation_fit import _position_match, _profile_fit, player_slot_fit, get_slot_definition
from models import PlayerStats
from player_names import resolve_player_name

ROOT = Path(__file__).resolve().parent
cache = json.loads((ROOT / "data" / "player_stats_cache.json").read_text(encoding="utf-8"))
players_cache = cache["players"]
manual = json.loads((ROOT / "data" / "manual_profiles.json").read_text(encoding="utf-8"))
season_picks = {
    p["player_name"]: p["stats"]
    for p in manual.get("profiles", [])
    if p.get("profile_type") == "season pick"
}


class _FakeStore:
    def __init__(self, names):
        self.players = {n: None for n in names}


STORE = _FakeStore(players_cache.keys())

CASES = [
    ("Nuno Mendes", "LM", "cache", "3-4-1-2 (flat)"),
    ("Nuno Mendes", "LB", "cache", "4-3-3 flat"),
    ("Désiré Doué", "RWB", "cache", "3-5-2"),
    ("Désiré Doué", "RM", "cache", "3-4-1-2 (flat)"),
    ("Guela Doue", "RM", "cache", "3-4-1-2 (flat)"),
]


def load_stats(name: str, source: str) -> PlayerStats:
    resolved = resolve_player_name(name, STORE)
    if source == "season":
        data = dict(season_picks.get(resolved, season_picks[name]))
    else:
        data = dict(players_cache[resolved])
    return PlayerStats.from_dict(resolved, data)


def report(name: str, slot: str, source: str, formation: str = "4-3-3 flat") -> dict:
    stats = load_stats(name, source)
    slot_def = get_slot_definition(formation, slot)
    pos = _position_match(stats, slot_def)
    prof = _profile_fit(stats, slot_def.get("profile", {}))
    fit = player_slot_fit(stats, formation, slot)
    misfit = fit < 0.55
    row = {
        "input": name,
        "resolved": stats.player,
        "formation": formation,
        "slot": slot,
        "primary": stats.primary_position,
        "positions": stats.positions,
        "dribbles90": round(stats.dribbles90, 3),
        "key_passes90": round(stats.key_passes90, 3),
        "xa90": round(stats.xa90, 3),
        "xg90": round(stats.xg90, 3),
        "position_match": round(pos, 3),
        "profile_fit": round(prof, 3),
        "fit": round(fit, 3),
        "misfit": misfit,
    }
    print(
        f"{name} -> {stats.player} @ {formation}/{slot}: fit={fit:.3f} "
        f"(pos={pos:.3f} prof={prof:.3f}) misfit={misfit}"
    )
    return row


if __name__ == "__main__":
    rows = [report(n, s, src, form) for n, s, src, form in CASES]
    print("\n--- JSON ---")
    print(json.dumps(rows, indent=2))
