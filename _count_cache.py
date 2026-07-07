import json
from pathlib import Path
out = Path("_count_out.txt")
p = json.loads(Path("data/player_stats_cache.json").read_text(encoding="utf-8"))
players = p.get("players", p)
lines = [f"count={len(players)}"]
for name in ["Harry Maguire", "Dayot Upamecano", "João Palhinha", "Mohamed Salah"]:
    e = players.get(name, {})
    lines.append(f"{name}: team={e.get('team')} aerial_pct={e.get('aerials_won_pct')} source={e.get('aerials_source')}")
out.write_text("\n".join(lines), encoding="utf-8")
