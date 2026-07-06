"""Test prime + blended for 17 players."""
from __future__ import annotations

import json
from pathlib import Path

from sofascore_client import StatsStore
from seasonal_stats import build_prime_stats_dict
from player_names import known_sofascore_id

PLAYERS = [
    "kante", "ruben dias", "rodri", "cole palmer", "carvajal", "messi", "cr7", "casemiro",
    "mohammed salah", "sergio ramos", "griezmann", "rudiger", "harry maguire", "modric",
    "aymeric laporte", "neuer", "alaba",
]

def main() -> None:
    store = StatsStore()
    rows = []
    for p in PLAYERS:
        row = {"input": p}
        pid = known_sofascore_id(p)
        row["id"] = pid
        try:
            canon, data, label = build_prime_stats_dict(p, store, cache_only=True)
            row["prime_ok"] = True
            row["canon"] = canon
            row["prime_season"] = label
            row["prime_rating"] = data.get("rating", 0)
            row["prime_min"] = data.get("minutes", 0)
            row["prime_src"] = data.get("data_source")
        except Exception as e:
            row["prime_ok"] = False
            row["prime_error"] = str(e)

        cn = store._find_cached_player_name(p)
        entry = store._cache.get("players", {}).get(cn) if cn else None
        if entry and float(entry.get("minutes") or 0) > 0 and float(entry.get("rating") or 0) > 0:
            row["blended_ok"] = True
            row["blended_rating"] = entry.get("rating")
            row["blended_min"] = entry.get("minutes")
        else:
            row["blended_ok"] = False
        rows.append(row)

    Path("_test_prime_17_results.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    ok_prime = sum(1 for r in rows if r.get("prime_ok"))
    ok_blend = sum(1 for r in rows if r.get("blended_ok"))
    print(f"PRIME OK: {ok_prime}/17  BLENDED OK: {ok_blend}/17")
    for r in rows:
        ps = "OK" if r.get("prime_ok") else "FAIL"
        bs = "OK" if r.get("blended_ok") else "FAIL"
        print(f"{ps}/{bs} {r['input']:18} id={r.get('id')} prime={r.get('prime_season','?')} src={r.get('prime_src')}")


if __name__ == "__main__":
    main()
