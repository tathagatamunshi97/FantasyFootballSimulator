import json
from pathlib import Path

root = Path(__file__).resolve().parent
audit = json.loads((root / "data/sheet_stats_audit.json").read_text(encoding="utf-8"))
cache = json.loads((root / "data/player_stats_cache.json").read_text(encoding="utf-8"))
players = cache.get("players") or cache
names = [r["cached_as"] for r in audit.get("full_players", []) if r.get("cached_as")]


def empty_pct(v):
    return v is None or v == "" or (isinstance(v, (int, float)) and v <= 0)


duel_gap = []
aerial_empty = []
aerial_estimated = []

for n in names:
    p = players.get(n, {})
    du = p.get("duels_won_pct")
    ds = p.get("duels_source")
    if empty_pct(du) or ds != "fotmob":
        duel_gap.append(n)

    aw = p.get("aerials_won_pct")
    asrc = p.get("aerials_source")
    if empty_pct(aw):
        aerial_empty.append(n)
    elif asrc == "estimated":
        aerial_estimated.append(n)

print(f"DUEL_GAP {len(duel_gap)}")
for x in sorted(duel_gap):
    print(x)
print(f"AERIAL_EMPTY {len(aerial_empty)}")
for x in sorted(aerial_empty):
    print(x)
print(f"AERIAL_ESTIMATED {len(aerial_estimated)}")
for x in sorted(aerial_estimated):
    print(x)
