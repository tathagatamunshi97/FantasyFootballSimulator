"""Test season picks cache_only for all 15 Round 3 + Mahrez."""
from __future__ import annotations

import json
from pathlib import Path

from sofascore_client import StatsStore
from seasonal_stats import build_season_stats_dict

PICKS = [
    ("Edinson Cavani", "16/17"),
    ("Dani Alves", "17/18"),
    ("Marcelo", "16/17"),
    ("Giovanni Lo Celso", "18/19"),
    ("Gonzalo Higuaín", "15/16"),
    ("Diego Godín", "15/16"),
    ("Luis Suárez", "15/16"),
    ("Arturo Vidal", "15/16"),
    ("Ángel Di María", "13/14"),
    ("Fernandinho", "17/18"),
    ("Roberto Firmino", "17/18"),
    ("Neymar", "14/15"),
    ("Alexis Sánchez", "16/17"),
    ("Radamel Falcao", "16/17"),
    ("Riyad Mahrez", "22/23"),
]


def main() -> None:
    store = StatsStore()
    rows = []
    for name, suffix in PICKS:
        row = {"player": name, "season": suffix}
        try:
            canon, data, label = build_season_stats_dict(name, suffix, store, cache_only=True)
            row["ok"] = True
            row["canon"] = canon
            row["minutes"] = data.get("minutes")
            row["goals90"] = data.get("goals90")
            row["assists90"] = data.get("assists90")
            row["tackles90"] = data.get("tackles90")
            row["position"] = data.get("primary_position")
            row["source"] = data.get("data_source")
        except Exception as e:
            row["ok"] = False
            row["error"] = str(e)
        rows.append(row)

    Path("_test_season_picks_results.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    ok = sum(1 for r in rows if r.get("ok"))
    print(f"SEASON PICKS OK: {ok}/{len(PICKS)}")
    for r in rows:
        st = "OK" if r.get("ok") else "FAIL"
        print(
            f"{st} {r['player']:22} {r['season']} g90={r.get('goals90')} pos={r.get('position')}"
        )


if __name__ == "__main__":
    main()
