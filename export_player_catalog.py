"""Export collected player stats to Excel for manual prime/season enrichment."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from player_names import KNOWN_DISPLAY_NAMES, KNOWN_PRIME_SEASON_SUFFIX

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CACHE_FILE = DATA / "player_stats_cache.json"
SEED_PLAYERS_FILE = DATA / "seed_players.json"
SEED_SEASONS_FILE = DATA / "seed_seasons.json"
DEFAULT_OUT = DATA / "player_catalog_export.xlsx"

STAT_COLUMNS = [
    "goals90",
    "assists90",
    "xg90",
    "xa90",
    "shots90",
    "shots_on_target90",
    "key_passes90",
    "tackles90",
    "interceptions90",
    "clearances90",
    "dribbles90",
    "dribble_pct",
    "passes_completed90",
    "pass_pct",
    "long_balls90",
    "long_ball_pct",
    "big_chances_created90",
    "big_chances_missed90",
    "possession_lost90",
    "penalty_goals90",
    "saves90",
    "goals_prevented90",
    "goals_conceded90",
    "clean_sheet_pct",
    "yellow_cards90",
    "red_cards90",
    "rating",
    "npxg90",
    "xg_chain90",
    "xg_buildup90",
    "understat_key_passes90",
    "understat_xg90",
    "understat_xa90",
    "understat_shots90",
]

SUMMARY_COLUMNS = [
    "player_name",
    "team",
    "primary_position",
    "fpl_position",
    "league",
    "player_id",
    "minutes",
    "games",
    "starts",
    "seasons_used",
    "stat_profile",
    "data_source",
    "understat_matched",
    "prime_season_suffix",
    "pick_season_suffix",
    "enrichment_notes",
    *STAT_COLUMNS,
]

INSTRUCTIONS = [
    ["Player catalog export — manual enrichment guide"],
    [""],
    ["Sheets"],
    ["Players", "One row per player currently in our cache/seed data (default blended 24/25+25/26 unless noted)."],
    ["All_Stats", "Same players with every stored stat field (wide format)."],
    ["Season_Profiles", "Per-season stat rows (from seed_seasons.json). Add rows here for pick-season overrides."],
    ["Stat_Glossary", "Short description of stat columns used by the simulator."],
    [""],
    ["Columns you can fill in (Players sheet)"],
    ["prime_season_suffix", "Sofascore format e.g. 16/17 — best top-5 league season for Prime player mode."],
    ["pick_season_suffix", "Optional default pick-season if this player is often used that way."],
    ["enrichment_notes", "Free text — source, caveats, etc."],
    [""],
    ["Season_Profiles sheet — add new rows with:"],
    ["player_name", "Must match canonical name (see Players sheet)."],
    ["season_suffix", "Sofascore format: 23/24, 16/17, etc. (top-5 leagues only)."],
    ["All stat columns", "Per-90 rates and metadata — copy structure from existing Kanté row."],
    [""],
    ["After editing, share the file back to import into seed_players.json / seed_seasons.json."],
]

GLOSSARY = [
    ("goals90", "Goals per 90 minutes"),
    ("assists90", "Assists per 90"),
    ("xg90", "Expected goals per 90 (Sofascore)"),
    ("xa90", "Expected assists per 90"),
    ("npxg90", "Non-penalty xG per 90 (Understat when matched)"),
    ("xg_chain90", "xG chain per 90 (Understat)"),
    ("xg_buildup90", "xG buildup per 90 (Understat)"),
    ("tackles90", "Tackles per 90"),
    ("interceptions90", "Interceptions per 90"),
    ("rating", "Sofascore average rating"),
    ("minutes", "Total minutes in blended profile"),
    ("seasons_used", "Which seasons are blended in default profile"),
    ("stat_profile", "How stats were built: blended, seeded_sofascore, prime_season, etc."),
    ("understat_matched", "Whether Understat xG data was merged"),
]


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _player_id_to_name(players: dict[str, dict]) -> dict[int, str]:
    out: dict[int, str] = dict(KNOWN_DISPLAY_NAMES)
    for name, data in players.items():
        pid = data.get("player_id")
        if pid is not None:
            out[int(pid)] = name
    return out


def _flatten_player(name: str, data: dict, *, source: str) -> dict:
    seasons = data.get("seasons_used") or []
    if isinstance(seasons, list):
        seasons_str = ", ".join(str(s) for s in seasons)
    else:
        seasons_str = str(seasons)

    pid = data.get("player_id")
    prime = KNOWN_PRIME_SEASON_SUFFIX.get(int(pid)) if pid else ""

    row = {
        "player_name": name,
        "team": data.get("team", ""),
        "primary_position": data.get("primary_position", ""),
        "fpl_position": data.get("fpl_position", ""),
        "league": data.get("league", ""),
        "player_id": pid,
        "minutes": data.get("minutes"),
        "games": data.get("games"),
        "starts": data.get("starts"),
        "seasons_used": seasons_str,
        "stat_profile": data.get("stat_profile", "blended_cache"),
        "data_source": source,
        "understat_matched": data.get("understat_matched", False),
        "prime_season_suffix": prime or "",
        "pick_season_suffix": "",
        "enrichment_notes": "",
    }
    for col in STAT_COLUMNS:
        row[col] = data.get(col)
    return row


def build_players_df() -> pd.DataFrame:
    cache = _load_json(CACHE_FILE).get("players", {})
    seed = _load_json(SEED_PLAYERS_FILE).get("players", {})

    rows: list[dict] = []
    seen: set[str] = set()

    for name in sorted(cache.keys()):
        rows.append(_flatten_player(name, cache[name], source="cache"))
        seen.add(name)

    for name in sorted(seed.keys()):
        if name in seen:
            # Mark seeded entries already merged into cache
            for row in rows:
                if row["player_name"] == name and row["stat_profile"] != "blended_cache":
                    row["data_source"] = "cache+seed"
            continue
        rows.append(_flatten_player(name, seed[name], source="seed_only"))

    df = pd.DataFrame(rows)
    for col in SUMMARY_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[SUMMARY_COLUMNS].sort_values("player_name", key=lambda s: s.str.lower())


def build_season_profiles_df(players_df: pd.DataFrame) -> pd.DataFrame:
    seed = _load_json(SEED_SEASONS_FILE)
    id_to_name = {
        int(row.player_id): row.player_name
        for row in players_df.itertuples()
        if pd.notna(row.player_id)
    }
    id_to_name.update(KNOWN_DISPLAY_NAMES)

    rows: list[dict] = []
    for pid_str, seasons in seed.items():
        pid = int(pid_str)
        pname = id_to_name.get(pid, f"id:{pid}")
        for suffix, data in seasons.items():
            row = _flatten_player(pname, data, source="seed_season")
            row["season_suffix"] = suffix
            row["season_label"] = data.get("season_profile") or suffix
            rows.insert(0, row)

    # Template row for manual entry
    template = {col: "" for col in SUMMARY_COLUMNS}
    template.update(
        {
            "player_name": "(add player name)",
            "season_suffix": "16/17",
            "stat_profile": "seeded_season",
            "data_source": "manual_template",
            "enrichment_notes": "Delete this example row after adding real data",
        }
    )
    rows.append(template)

    if not rows:
        return pd.DataFrame(columns=["season_suffix", "season_label", *SUMMARY_COLUMNS])

    df = pd.DataFrame(rows)
    front = ["season_suffix", "season_label"]
    rest = [c for c in df.columns if c not in front]
    return df[front + rest]


def export_catalog(out_path: Path | None = None) -> Path:
    out = out_path or DEFAULT_OUT
    players_df = build_players_df()
    stats_df = players_df.copy()
    season_df = build_season_profiles_df(players_df)
    glossary_df = pd.DataFrame(GLOSSARY, columns=["column", "description"])
    instructions_df = pd.DataFrame(INSTRUCTIONS)

    meta = _load_json(CACHE_FILE).get("meta", {})
    meta_rows = pd.DataFrame(
        [{"key": k, "value": str(v)} for k, v in sorted(meta.items())]
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        instructions_df.to_excel(writer, sheet_name="README", index=False, header=False)
        players_df.to_excel(writer, sheet_name="Players", index=False)
        stats_df.to_excel(writer, sheet_name="All_Stats", index=False)
        season_df.to_excel(writer, sheet_name="Season_Profiles", index=False)
        glossary_df.to_excel(writer, sheet_name="Stat_Glossary", index=False)
        meta_rows.to_excel(writer, sheet_name="Cache_Meta", index=False)

    return out


if __name__ == "__main__":
    path = export_catalog()
    n = len(build_players_df())
    print(f"Exported {n} players to {path}")
