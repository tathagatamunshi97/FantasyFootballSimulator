"""Export FotMob-enriched stats for Google Sheet roster players (verification)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from fotmob_client import FOTMOB_STAT_KEYS

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CACHE_FILE = DATA / "player_stats_cache.json"
SHEET_AUDIT_FILE = DATA / "sheet_stats_audit.json"
DEFAULT_OUT = DATA / "fotmob_stats_verification.xlsx"

CONTEXT_COLUMNS = [
    "player_name",
    "sheet_raw_name",
    "team",
    "league",
    "primary_position",
    "fpl_position",
    "minutes",
    "games",
    "starts",
    "seasons_used",
    "understat_matched",
    "clearances90",
    "tackles90",
    "interceptions90",
    "rating",
]

FOTMOB_COLUMNS = [
    "fotmob_id",
    "fotmob_matched",
    "preferred_foot",
    "duels_won_pct",
    "duels_source",
    "aerials_won_pct",
    "aerials_won90",
    "aerials_lost90",
    "aerials_source",
    "fotmob_seasons_blended",
    "fotmob_season_minutes",
]

EXPORT_COLUMNS = [*CONTEXT_COLUMNS, *FOTMOB_COLUMNS]

INSTRUCTIONS = [
    ["FotMob stats verification export"],
    [""],
    ["Source", "data/player_stats_cache.json merged with FotMob backfill"],
    ["Players", "All unique names from data/sheet_stats_audit.json (full_players)"],
    ["clearances90", "Sofascore/blended cache — compare with aerial proxies"],
    ["aerials_source", "fotmob | estimated | (blank if unknown)"],
    ["duels_source", "fotmob when duels_won_pct came from FotMob"],
    ["fotmob_seasons_blended", "League seasons used for minutes-weighted FotMob blend"],
    ["fotmob_season_minutes", "Per-season league minutes from FotMob"],
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _seasons_label(seasons: object) -> str:
    if isinstance(seasons, list):
        return ", ".join(str(s) for s in seasons)
    if seasons is None:
        return ""
    return str(seasons)


def _fotmob_minutes_label(minutes: object) -> str:
    if isinstance(minutes, dict):
        parts = [f"{season}: {int(m) if m == int(m) else m}" for season, m in minutes.items()]
        return ", ".join(parts)
    if minutes is None:
        return ""
    return str(minutes)


def _sheet_players() -> list[tuple[str, str]]:
    """Return (cached_name, sheet_raw_name) pairs in audit order."""
    audit = _load_json(SHEET_AUDIT_FILE)
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in audit.get("full_players", []):
        cached = (row.get("cached_as") or "").strip()
        if not cached or cached in seen:
            continue
        seen.add(cached)
        pairs.append((cached, (row.get("raw") or "").strip()))
    return pairs


def build_fotmob_verification_df() -> pd.DataFrame:
    cache = _load_json(CACHE_FILE).get("players", {})
    rows: list[dict] = []
    for cached_name, raw_name in _sheet_players():
        data = cache.get(cached_name, {})
        row = {
            "player_name": cached_name,
            "sheet_raw_name": raw_name,
            "team": data.get("team", ""),
            "league": data.get("league", ""),
            "primary_position": data.get("primary_position", ""),
            "fpl_position": data.get("fpl_position", ""),
            "minutes": data.get("minutes"),
            "games": data.get("games"),
            "starts": data.get("starts"),
            "seasons_used": _seasons_label(data.get("seasons_used")),
            "understat_matched": data.get("understat_matched", False),
            "clearances90": data.get("clearances90"),
            "tackles90": data.get("tackles90"),
            "interceptions90": data.get("interceptions90"),
            "rating": data.get("rating"),
        }
        for key in FOTMOB_STAT_KEYS:
            value = data.get(key)
            if key == "fotmob_seasons_blended":
                value = _seasons_label(value)
            elif key == "fotmob_season_minutes":
                value = _fotmob_minutes_label(value)
            row[key] = value
        rows.append(row)

    df = pd.DataFrame(rows)
    for col in EXPORT_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[EXPORT_COLUMNS]
    return df.sort_values("player_name", kind="stable").reset_index(drop=True)


def export_fotmob_stats(out: Path | None = None) -> Path:
    path = out or DEFAULT_OUT
    df = build_fotmob_verification_df()
    readme = pd.DataFrame(INSTRUCTIONS)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        readme.to_excel(writer, sheet_name="README", index=False, header=False)
        df.to_excel(writer, sheet_name="Sheet_Players", index=False)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output .xlsx path (default: {DEFAULT_OUT.name})",
    )
    args = parser.parse_args()
    out = export_fotmob_stats(args.output)
    df = build_fotmob_verification_df()
    print(f"Wrote {out}")
    print(f"Rows: {len(df)}")
    print(f"Columns: {list(df.columns)}")


if __name__ == "__main__":
    main()
