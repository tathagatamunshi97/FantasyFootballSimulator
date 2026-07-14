"""Manual stat profiles for prime and season-pick overrides (no Sofascore fetch)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from player_names import canonical_name, names_loosely_match, normalize_key
from seasonal_stats import normalize_season_input, season_label_from_suffix

ProfileType = Literal["prime", "season_pick"]

DATA_DIR = Path(__file__).resolve().parent / "data"
MANUAL_PROFILES_FILE = DATA_DIR / "manual_profiles.json"
MANUAL_PROFILES_XLSX = DATA_DIR / "manual_profiles.xlsx"

STAT_FIELDS = (
    "team",
    "primary_position",
    "fpl_position",
    "positions",
    "minutes",
    "games",
    "starts",
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
    "understat_matched",
    "fbref_matched",
    "league",
    "player_id",
    "aerials_won90",
    "aerials_lost90",
    "aerials_won_pct",
    "aerials_source",
    "duels_won_pct",
)

_INDEX: dict[tuple[str, str, str], dict[str, Any]] | None = None
_INDEX_MTIME: float = 0.0


def _source_mtime() -> float:
    mtimes = [0.0]
    for path in (MANUAL_PROFILES_FILE, MANUAL_PROFILES_XLSX):
        if path.exists():
            mtimes.append(path.stat().st_mtime)
    return max(mtimes)


def _normalize_profile_type(raw: str) -> str | None:
    key = normalize_key(str(raw).strip())
    if key in {"prime", "prime season", "prime_season"}:
        return "prime"
    if key in {"season pick", "season_pick", "pick season", "pick_season", "pick-season", "peak season"}:
        return "season_pick"
    return None


def _normalize_season_suffix(raw: str) -> str:
    return normalize_season_input(str(raw).strip())


def _player_keys(raw_name: str) -> set[str]:
    canon = canonical_name(raw_name)
    return {normalize_key(canon), normalize_key(raw_name)}


def _row_to_profile(row: dict[str, Any]) -> dict[str, Any] | None:
    name = str(row.get("player_name") or row.get("player") or "").strip()
    profile_raw = row.get("profile_type") or row.get("override_type") or ""
    season_raw = row.get("season_suffix") or row.get("season") or row.get("pick_season_suffix") or ""
    if not name or not profile_raw or not season_raw:
        return None
    if str(name).startswith("(") or "add player" in name.lower():
        return None

    profile_type = _normalize_profile_type(str(profile_raw))
    if profile_type is None:
        return None

    try:
        season_suffix = _normalize_season_suffix(str(season_raw))
    except ValueError:
        return None

    season_label = season_label_from_suffix(season_suffix)
    stats: dict[str, Any] = {
        "seasons_used": [season_label],
        "teams_by_season": {season_label: row.get("team", "")},
        "season_profile": season_label,
        "stat_profile": "manual_prime" if profile_type == "prime" else "manual_season_pick",
        "data_source": "manual_profiles",
        "manual_profile_type": profile_type,
        "manual_season_suffix": season_suffix,
    }
    for field in STAT_FIELDS:
        if field in row and row[field] not in (None, ""):
            stats[field] = row[field]
    if "positions" in stats and isinstance(stats["positions"], str):
        stats["positions"] = [p.strip() for p in stats["positions"].split(",") if p.strip()]
    return {
        "player_name": name,
        "profile_type": profile_type,
        "season_suffix": season_suffix,
        "season_label": season_label,
        "stats": stats,
    }


def _build_index(profiles: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for profile in profiles:
        name = profile["player_name"]
        for key in _player_keys(name):
            index[(key, profile["profile_type"], profile["season_suffix"])] = profile
    return index


def _normalize_profile_entry(raw: dict[str, Any]) -> dict[str, Any] | None:
    if "stats" in raw and "player_name" in raw:
        stats = dict(raw["stats"])
        profile_type = _normalize_profile_type(str(raw.get("profile_type", "")))
        season_suffix = str(raw.get("season_suffix", stats.get("manual_season_suffix", "")))
        if not profile_type or not season_suffix:
            return None
        try:
            season_suffix = _normalize_season_suffix(season_suffix)
        except ValueError:
            return None
        season_label = season_label_from_suffix(season_suffix)
        return {
            "player_name": str(raw["player_name"]).strip(),
            "profile_type": profile_type,
            "season_suffix": season_suffix,
            "season_label": season_label,
            "stats": stats,
        }
    return _row_to_profile(raw)


def _load_profiles_list() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    # Try loading from database first (only on Render with DATABASE_URL set)
    try:
        import db
        if db.is_db_enabled():
            db_profiles = db.load_all_manual_profiles()
            for db_row in db_profiles:
                built = _normalize_profile_entry(db_row)
                if built:
                    rows.append(built)
            if rows:
                return rows  # If database has data, use it exclusively
    except (ImportError, Exception):
        # Database not available, fall back to JSON/XLSX
        pass

    # Fallback to JSON file
    if MANUAL_PROFILES_FILE.exists():
        try:
            payload = json.loads(MANUAL_PROFILES_FILE.read_text(encoding="utf-8"))
            for row in payload.get("profiles", []):
                if isinstance(row, dict):
                    built = _normalize_profile_entry(row)
                    if built:
                        rows.append(built)
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback to XLSX file
    if MANUAL_PROFILES_XLSX.exists():
        try:
            import pandas as pd

            df = pd.read_excel(MANUAL_PROFILES_XLSX, sheet_name="Profiles")
            for record in df.to_dict(orient="records"):
                built = _row_to_profile(record)
                if built:
                    rows.append(built)
        except Exception:
            pass

    # Legacy seed_seasons.json → season_pick entries.
    # Only fills gaps: a player/profile_type/season already present from
    # manual_profiles.json/XLSX above must win, since _build_index() keeps the
    # last entry for a given key and this fallback used to silently overwrite
    # complete manual profiles with sparser legacy data (e.g. missing aerial
    # duel stats) for the same player/season.
    existing_keys = {
        (key, profile["profile_type"], profile["season_suffix"])
        for profile in rows
        for key in _player_keys(profile["player_name"])
    }

    seed_path = DATA_DIR / "seed_seasons.json"
    if seed_path.exists():
        try:
            seed = json.loads(seed_path.read_text(encoding="utf-8"))
            from player_names import KNOWN_DISPLAY_NAMES

            for pid_str, seasons in seed.items():
                pname = KNOWN_DISPLAY_NAMES.get(int(pid_str), f"id:{pid_str}")
                for suffix, data in seasons.items():
                    row = {"player_name": pname, "profile_type": "season pick", "season_suffix": suffix, **data}
                    built = _row_to_profile(row)
                    if not built:
                        continue
                    keys = {
                        (key, built["profile_type"], built["season_suffix"]) for key in _player_keys(pname)
                    }
                    if keys & existing_keys:
                        continue
                    rows.append(built)
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    return rows


def reload_manual_profiles() -> None:
    global _INDEX, _INDEX_MTIME
    _INDEX = _build_index(_load_profiles_list())
    _INDEX_MTIME = _source_mtime()


def _index() -> dict[tuple[str, str, str], dict[str, Any]]:
    global _INDEX, _INDEX_MTIME
    current = _source_mtime()
    if _INDEX is None or current > _INDEX_MTIME:
        reload_manual_profiles()
    return _INDEX or {}


def _find_profile(
    player_raw: str,
    profile_type: ProfileType,
    season_suffix: str | None = None,
) -> dict[str, Any] | None:
    keys = _player_keys(player_raw)
    idx = _index()
    if season_suffix is not None:
        suf = _normalize_season_suffix(season_suffix)
        for key in keys:
            hit = idx.get((key, profile_type, suf))
            if hit:
                return hit
        return None

    matches = [p for k, p in idx.items() if k[0] in keys and k[1] == profile_type]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    # Multiple prime rows — prefer latest season by suffix
    return sorted(matches, key=lambda p: p["season_suffix"], reverse=True)[0]


def _enrich_with_understat(stats: dict[str, Any], player_name: str, season_suffix: str) -> dict[str, Any]:
    if stats.get("understat_matched"):
        return stats
    from understat_client import merge_understat_for_player_season

    data = dict(stats)
    merge_understat_for_player_season(player_name, data, season_suffix)
    return data


def _enrich_with_fbref(stats: dict[str, Any], player_name: str, season_suffix: str) -> dict[str, Any]:
    if stats.get("fbref_matched"):
        return stats
    src = str(stats.get("data_source", ""))
    if src in ("manual_profiles", "fbref+verified", "fbref+understat", "fbref"):
        return stats
    if stats.get("minutes", 0) > 0 and (
        stats.get("tackles90", 0) > 0 or stats.get("goals90", 0) > 0
    ):
        return stats
    from fbref_client import merge_fbref_for_player_season

    data = dict(stats)
    merge_fbref_for_player_season(player_name, data, season_suffix, overwrite_zeros=True)
    if data.get("fbref_matched"):
        src = data.get("data_source", "")
        if src in ("understat_stub", "manual_profiles", ""):
            data["data_source"] = "fbref+understat" if data.get("understat_matched") else "fbref"
    return data


def _enrich_manual_stats(stats: dict[str, Any], player_name: str, season_suffix: str) -> dict[str, Any]:
    from player_names import apply_known_position_overrides, known_sofascore_id

    data = _enrich_with_fbref(stats, player_name, season_suffix)
    data = _enrich_with_understat(data, player_name, season_suffix)
    pid = data.get("player_id") or known_sofascore_id(player_name)
    apply_known_position_overrides(data, pid)
    return data


def lookup_manual_prime(
    player_raw: str,
    *,
    cache_only: bool = False,
) -> tuple[str, dict[str, Any], str] | None:
    """Return (canonical_name, stats_dict, season_label) for a prime manual row."""
    profile = _find_profile(player_raw, "prime")
    if not profile:
        return None
    name = profile["player_name"]
    if cache_only:
        data = dict(profile["stats"])
    else:
        data = _enrich_manual_stats(dict(profile["stats"]), name, profile["season_suffix"])
    data["stat_profile"] = "prime_season"
    data["prime_season"] = profile["season_label"]
    data["data_source"] = "manual_profiles"
    data["manual_profile_type"] = "prime"
    data["manual_season_suffix"] = profile["season_suffix"]
    return name, data, profile["season_label"]


def lookup_manual_season_pick(
    player_raw: str,
    season_suffix: str,
    *,
    cache_only: bool = False,
) -> tuple[str, dict[str, Any], str] | None:
    """Return (canonical_name, stats_dict, season_label) for a season-pick manual row."""
    suf = _normalize_season_suffix(season_suffix)
    profile = _find_profile(player_raw, "season_pick", season_suffix=suf)
    if not profile:
        return None
    name = profile["player_name"]
    if cache_only:
        data = dict(profile["stats"])
    else:
        data = _enrich_manual_stats(dict(profile["stats"]), name, profile["season_suffix"])
    data["stat_profile"] = "single_season"
    data["data_source"] = "manual_profiles"
    data["manual_profile_type"] = "season_pick"
    data["manual_season_suffix"] = profile["season_suffix"]
    data["season_profile"] = profile["season_label"]
    return name, data, profile["season_label"]


def list_manual_profiles() -> list[dict[str, Any]]:
    return _load_profiles_list()
