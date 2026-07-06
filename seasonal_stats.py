"""Fetch single-season and prime-season player stats (2013-14 onward)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from datafc import player_career_stats_data

from models import PlayerStats
from sofascore_client import (
    MIN_MINUTES,
    TOP5_EUROPEAN_LEAGUES,
    StatsStore,
    _career_top5_table_from_api,
    _fetch_player_season_via_career_api,
    _find_player_in_league_season,
    _num,
    _pick_search_player_id,
)
from understat_client import merge_understat_for_player_season, season_start_year_from_suffix
from fbref_client import build_fbref_season_entry, merge_fbref_for_player_season

MIN_PRIME_MINUTES = 900
MIN_SEASON_START_YEAR = 2013
TOP5_TOURNAMENTS = frozenset({"Premier League", "LaLiga", "Serie A", "Bundesliga", "Ligue 1"})
SEED_SEASONS_FILE = Path(__file__).resolve().parent / "data" / "seed_seasons.json"


def list_selectable_seasons() -> list[dict[str, str]]:
    """Seasons from 2013-14 through 2025-26 for UI dropdowns."""
    rows: list[dict[str, str]] = []
    for start in range(MIN_SEASON_START_YEAR, 2026):
        yy = start % 100
        ny = (start + 1) % 100
        suffix = f"{yy:02d}/{ny:02d}"
        label = f"{start}-{start + 1}"
        rows.append(
            {
                "label": label,
                "suffix": suffix,
                "understat": f"{yy:02d}{ny:02d}",
            }
        )
    return rows


def normalize_season_input(raw: str) -> str:
    """Accept '23/24', '2023-24', '2324', '2023/2024' -> Sofascore suffix '23/24'."""
    s = str(raw).strip().replace("–", "-").replace("—", "-")
    if not s:
        raise ValueError("Empty season")
    if "/" in s and len(s.split("/")[0]) <= 2:
        a, b = s.split("/", 1)
        return f"{int(a):02d}/{int(b):02d}"
    if len(s) == 4 and s.isdigit():
        a, b = int(s[:2]), int(s[2:])
        return f"{a:02d}/{b:02d}"
    if "-" in s:
        parts = s.split("-")
        start = int(parts[0])
        if start >= 1900:
            yy, ny = start % 100, (start + 1) % 100
        else:
            yy, ny = int(parts[0]), int(parts[1])
        return f"{yy:02d}/{ny:02d}"
    raise ValueError(f"Unrecognized season format: {raw}")


def season_label_from_suffix(suffix: str) -> str:
    yy = int(suffix.split("/")[0])
    start = 2000 + yy if yy < 50 else 1900 + yy
    return f"{start}-{start + 1}"


def _resolve_player_id(raw_name: str, *, store: StatsStore | None = None) -> int:
    if store is not None:
        pid = store.cached_player_id(raw_name)
        if pid is not None:
            return pid
    from sofascore_client import _lookup_player_id

    cache = store._cache if store is not None else None
    player_id, _ = _lookup_player_id(raw_name, cache=cache)
    return player_id


def _display_name_for_player(raw_name: str, player_id: int) -> str:
    from player_names import canonical_name, known_display_name

    if known_display_name(raw_name):
        return known_display_name(raw_name) or canonical_name(raw_name)
    return canonical_name(raw_name)


def _load_seed_season_entry(player_id: int, season_suffix: str) -> dict[str, Any] | None:
    if not SEED_SEASONS_FILE.exists():
        return None
    try:
        seed = json.loads(SEED_SEASONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    player_seasons = seed.get(str(player_id)) or {}
    data = player_seasons.get(season_suffix)
    return dict(data) if data else None


def _career_league_table(player_id: int, player_name: str) -> pd.DataFrame:
    squad = pd.DataFrame([{"player_id": player_id, "player_name": player_name}])
    try:
        career = player_career_stats_data(squad)
        if career is not None and not career.empty:
            rows = career[career["tournament_name"].isin(TOP5_TOURNAMENTS)].copy()
            if not rows.empty:
                wide = rows.pivot_table(
                    index=["season_name", "tournament_name", "team_name"],
                    columns="stat",
                    values="value",
                    aggfunc="first",
                )
                return wide.reset_index()
    except Exception:
        pass
    return _career_top5_table_from_api(player_id, player_name)


def _season_impact_score(row: pd.Series) -> float:
    minutes = _num(row.get("minutesPlayed"))
    if minutes < MIN_PRIME_MINUTES:
        return -1.0
    start = season_start_year_from_suffix(str(row.get("season_name", "")))
    if start < MIN_SEASON_START_YEAR:
        return -1.0

    per90 = 90.0 / minutes
    xg = _num(row.get("expectedGoals"))
    xa = _num(row.get("expectedAssists"))
    goals = _num(row.get("goals"))
    assists = _num(row.get("assists"))
    kp = _num(row.get("keyPasses"))

    xg90 = xg * per90 if xg > 0 else goals * per90 * 0.82
    xa90 = xa * per90 if xa > 0 else assists * per90 * 0.75
    kp90 = kp * per90

    return xg90 * 0.48 + xa90 * 0.28 + kp90 * 0.12 + (goals * per90) * 0.07 + (assists * per90) * 0.05


def find_prime_season_suffix(player_name: str, *, player_id: int | None = None) -> str:
    """Return season suffix for prime — manual dataset first, then Sofascore career."""
    from manual_profiles import _find_profile

    manual = _find_profile(player_name, "prime")
    if manual is not None:
        return manual["season_suffix"]

    from player_names import KNOWN_PRIME_SEASON_SUFFIX

    pid = player_id or _resolve_player_id(player_name)
    preset = KNOWN_PRIME_SEASON_SUFFIX.get(pid)
    if preset:
        return preset
    table = _career_league_table(pid, player_name)
    if table.empty:
        raise KeyError(f"No top-league career data for {player_name}")

    table = table.copy()
    table["_score"] = table.apply(_season_impact_score, axis=1)
    eligible = table[table["_score"] > 0]
    if eligible.empty:
        raise KeyError(
            f"No eligible prime season for {player_name} "
            f"(need >= {MIN_PRIME_MINUTES} min from {MIN_SEASON_START_YEAR}-{MIN_SEASON_START_YEAR + 1} onward)"
        )
    best = eligible.sort_values("_score", ascending=False).iloc[0]
    return str(best["season_name"])


def fetch_sofascore_season_entry(
    player_id: int,
    season_suffix: str,
    *,
    player_name: str = "",
) -> dict[str, Any] | None:
    season_label = season_label_from_suffix(season_suffix)
    best: dict[str, Any] | None = None
    for league in TOP5_EUROPEAN_LEAGUES:
        try:
            entry = _find_player_in_league_season(
                player_id, league, season_suffix, player_name=player_name
            )
        except Exception:
            continue
        if not entry:
            continue
        entry = dict(entry)
        entry["seasons_used"] = [season_label]
        entry["teams_by_season"] = {season_label: entry.get("team", "")}
        if best is None or entry.get("minutes", 0) > best.get("minutes", 0):
            best = entry
    if best is None and player_name:
        entry = _fetch_player_season_via_career_api(player_id, player_name, season_suffix)
        if entry:
            best = dict(entry)
    return best


def fetch_best_historical_stats(player_raw: str) -> tuple[str, dict[str, Any]]:
    """Load a retired/inactive player's best top-5 league season into the cache."""
    pid = _resolve_player_id(player_raw)
    display_name = _display_name_for_player(player_raw, pid)
    suffix = find_prime_season_suffix(display_name, player_id=pid)
    entry = fetch_sofascore_season_entry(pid, suffix, player_name=display_name)
    if not entry:
        entry = _load_seed_season_entry(pid, suffix)
    if not entry:
        from player_names import known_season_context

        ctx = known_season_context(pid, suffix)
        if ctx:
            entry = build_fbref_season_entry(pid, display_name, suffix, ctx)
    if not entry:
        label = season_label_from_suffix(suffix)
        raise KeyError(f"No top-league stats for {display_name} in {label}")
    if entry.get("minutes", 0) < MIN_MINUTES:
        label = season_label_from_suffix(suffix)
        raise KeyError(f"{display_name} played insufficient minutes in {label}")

    season_label = season_label_from_suffix(suffix)
    data = {k: v for k, v in entry.items() if k != "player_name"}
    data["stat_profile"] = "historical_best"
    data["season_profile"] = season_label
    merge_understat_for_player_season(display_name, data, suffix)
    merge_fbref_for_player_season(display_name, data, suffix)
    return display_name, data


def _season_data_from_local_entry(
    entry: dict[str, Any],
    season_suffix: str,
    *,
    stat_profile: str,
    prime_label: str | None = None,
) -> dict[str, Any]:
    season_label = season_label_from_suffix(season_suffix)
    data = {k: v for k, v in entry.items() if k != "player_name"}
    data["stat_profile"] = stat_profile
    data["season_profile"] = season_label
    if prime_label:
        data["prime_season"] = prime_label
    return data


def build_season_stats_dict(
    player_raw: str,
    season_suffix: str,
    store: StatsStore,
    *,
    cache_only: bool = False,
) -> tuple[str, dict[str, Any], str]:
    """
    Build a full stats dict for one season.
    Manual season-pick dataset first; Sofascore only as fallback.
    Returns (canonical_name, stats_dict, season_label).
    """
    from manual_profiles import lookup_manual_season_pick

    start = season_start_year_from_suffix(season_suffix)
    if start < MIN_SEASON_START_YEAR:
        raise ValueError(f"Season must be {MIN_SEASON_START_YEAR}-{MIN_SEASON_START_YEAR + 1} or later")

    manual = lookup_manual_season_pick(player_raw, season_suffix)
    if manual is not None:
        canon = store.resolve(player_raw)
        data = manual[1]
        return canon, data, manual[2]

    canon = store.resolve(player_raw)
    season_label = season_label_from_suffix(season_suffix)
    pid = store.cached_player_id(player_raw) if cache_only else _resolve_player_id(player_raw, store=store)
    entry = _load_seed_season_entry(pid, season_suffix) if pid else None
    if not entry and not cache_only:
        display_name = _display_name_for_player(player_raw, pid)
        try:
            entry = fetch_sofascore_season_entry(pid, season_suffix, player_name=display_name)
        except Exception:
            entry = None
        if not entry:
            from player_names import known_season_context

            ctx = known_season_context(pid, season_suffix)
            if ctx:
                entry = build_fbref_season_entry(pid, display_name, season_suffix, ctx)
        if not entry:
            entry = _load_seed_season_entry(pid, season_suffix)
    if not entry and cache_only:
        cached = _prime_stats_from_cache(store, player_raw, season_suffix)
        if cached is not None:
            return cached
        raise KeyError(f"No cached stats for {player_raw} in {season_label}")
    if not entry:
        raise KeyError(f"No top-league stats for {player_raw} in {season_label}")

    if entry.get("minutes", 0) < MIN_MINUTES:
        raise KeyError(f"{player_raw} played insufficient minutes in {season_label}")

    data = _season_data_from_local_entry(entry, season_suffix, stat_profile="single_season")
    if not cache_only:
        merge_understat_for_player_season(canon, data, season_suffix)
        merge_fbref_for_player_season(canon, data, season_suffix)
    return canon, data, season_label


def _prime_stats_from_cache(
    store: StatsStore,
    player_raw: str,
    suffix: str,
) -> tuple[str, dict[str, Any], str] | None:
    """Use blended cache stats as prime fallback when season fetch is blocked."""
    cached_name = store._find_cached_player_name(player_raw)
    if not cached_name:
        return None
    entry = (store._cache.get("players") or {}).get(cached_name)
    if not entry:
        return None
    canon = store.resolve(player_raw)
    season_label = season_label_from_suffix(suffix)
    data = dict(entry)
    data["stat_profile"] = "prime_season"
    data["prime_season"] = season_label
    data["season_profile"] = season_label
    return canon, data, season_label


def build_prime_stats_dict(
    player_raw: str,
    store: StatsStore,
    *,
    cache_only: bool = False,
) -> tuple[str, dict[str, Any], str]:
    """Use manual prime profile when available; Sofascore only as fallback."""
    from manual_profiles import lookup_manual_prime

    manual = lookup_manual_prime(player_raw)
    if manual is not None:
        canon = store.resolve(player_raw)
        data = manual[1]
        return canon, data, manual[2]

    if cache_only:
        pid = store.cached_player_id(player_raw)
        suffix: str | None = None
        if pid is not None:
            from player_names import KNOWN_PRIME_SEASON_SUFFIX

            suffix = KNOWN_PRIME_SEASON_SUFFIX.get(pid)
            entry = _load_seed_season_entry(pid, suffix) if suffix else None
            if entry:
                canon = store.resolve(player_raw)
                label = season_label_from_suffix(suffix)
                data = _season_data_from_local_entry(
                    entry, suffix, stat_profile="prime_season", prime_label=label
                )
                return canon, data, label
        cached = _prime_stats_from_cache(store, player_raw, suffix or "24/25")
        if cached is not None:
            return cached
        raise KeyError(f"No cached stats for prime player {player_raw}")

    pid = _resolve_player_id(player_raw, store=store)
    suffix = find_prime_season_suffix(player_raw, player_id=pid)
    entry = _load_seed_season_entry(pid, suffix)
    if entry:
        canon = store.resolve(player_raw)
        season_label = season_label_from_suffix(suffix)
        data = {k: v for k, v in entry.items() if k != "player_name"}
        data["stat_profile"] = "prime_season"
        data["prime_season"] = season_label
        data["season_profile"] = season_label
        merge_understat_for_player_season(canon, data, suffix)
        merge_fbref_for_player_season(canon, data, suffix)
        return canon, data, season_label
    try:
        canon, data, label = build_season_stats_dict(player_raw, suffix, store)
    except (KeyError, ValueError, RuntimeError):
        cached = _prime_stats_from_cache(store, player_raw, suffix)
        if cached is None:
            raise
        canon, data, label = cached
    data["stat_profile"] = "prime_season"
    data["prime_season"] = label
    return canon, data, label
