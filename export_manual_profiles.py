"""Export blank template for manual prime / season-pick profiles."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from export_player_catalog import STAT_COLUMNS
from manual_profiles import MANUAL_PROFILES_XLSX, list_manual_profiles

TEMPLATE_COLUMNS = [
    "player_name",
    "profile_type",
    "season_suffix",
    "team",
    "primary_position",
    "fpl_position",
    "league",
    "player_id",
    "minutes",
    "games",
    "starts",
    *STAT_COLUMNS,
    "notes",
]

INSTRUCTIONS = [
    ["Manual profiles — prime & season pick"],
    [""],
    ["profile_type", "Use exactly: prime  OR  season pick"],
    ["season_suffix", "Sofascore format: 16/17, 23/24, etc."],
    ["prime", "One row per player — stats for their designated prime season."],
    ["season pick", "One row per player+season — used when that season is picked in the lab."],
    [""],
    ["Save this file as data/manual_profiles.xlsx — the server loads it automatically."],
    ["Alternatively use data/manual_profiles.json (see existing Kanté example)."],
    [""],
    ["Lineup slots without prime/season pick still use the usual blended cache stats."],
]


def export_template(out: Path | None = None) -> Path:
    path = out or MANUAL_PROFILES_XLSX
    existing = list_manual_profiles()
    rows: list[dict] = []
    for profile in existing:
        row = {
            "player_name": profile["player_name"],
            "profile_type": "prime" if profile["profile_type"] == "prime" else "season pick",
            "season_suffix": profile["season_suffix"],
            **profile["stats"],
        }
        rows.append(row)
    rows.append(
        {
            "player_name": "",
            "profile_type": "season pick",
            "season_suffix": "16/17",
            "notes": "Example row — delete or replace",
        }
    )
    df = pd.DataFrame(rows)
    for col in TEMPLATE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[TEMPLATE_COLUMNS]
    readme = pd.DataFrame(INSTRUCTIONS)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        readme.to_excel(writer, sheet_name="README", index=False, header=False)
        df.to_excel(writer, sheet_name="Profiles", index=False)
    return path


if __name__ == "__main__":
    p = export_template()
    print(f"Wrote {p}")
