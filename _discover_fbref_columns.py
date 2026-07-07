"""List soccerdata FBref columns vs fields imported by fbref_client."""
from __future__ import annotations

import soccerdata as sd
import pandas as pd

from fbref_client import STAT_TYPES, _flat_df

IMPORTED = {
    "standard": {
        "Playing Time_MP", "Playing Time_Min", "Playing Time_Starts",
        "Performance_Gls", "Performance_Ast", "Per 90 Minutes_Gls", "Per 90 Minutes_Ast",
        "Performance_CrdY", "Performance_CrdR", "pos", "team", "player",
    },
    "shooting": {"Standard_Sh", "Standard_SoT", "Standard_Sh/90", "Standard_SoT/90"},
    "misc": {"Performance_TklW", "Performance_Int", "Performance_CrdY", "Performance_CrdR"},
    "defense": {"Clr", "Blocks_Blocks", "Tackles_TklW", "Int"},
    "keeper": set(),
    "playing_time": set(),
}

META = {"player", "team", "pos", "age", "born", "league", "season", "nation", "90s", "Matches", "Rk"}


def cols_for(stat_type: str) -> list[str]:
    reader = sd.FBref(leagues=["ENG-Premier League"], seasons=["2023-2024"])
    if stat_type == "defense":
        from fbref_client import _read_defense_player_frame

        seasons = reader.read_seasons()
        for (lkey, skey), season in seasons.iterrows():
            frame = _read_defense_player_frame(reader, lkey, skey, season)
            if frame is not None and not frame.empty:
                return sorted(_flat_df(frame).columns)
        return []
    raw = reader.read_player_season_stats(stat_type=stat_type)
    return sorted(_flat_df(raw).columns)


def main() -> None:
    for stat_type in ("standard", "shooting", "misc", "keeper", "playing_time", "defense"):
        print(f"=== {stat_type} ===")
        try:
            cols = cols_for(stat_type)
        except Exception as exc:
            print(f"ERROR: {exc}")
            print()
            continue
        imported = IMPORTED.get(stat_type, set())
        unused = [c for c in cols if c not in imported and _simplify(c) not in META]
        print("unused:", ", ".join(unused) if unused else "(none beyond metadata)")
        if stat_type == "defense":
            print("notes: custom FBref /defense/ scrape; soccerdata has no defense stat_type")
        elif stat_type not in STAT_TYPES and stat_type != "defense":
            print("notes: stat_type supported by soccerdata but not fetched in pipeline")
        print()


def _simplify(name: str) -> str:
    if "_level_0_" in name:
        return name.rsplit("_level_0_", 1)[-1]
    return name


if __name__ == "__main__":
    main()
