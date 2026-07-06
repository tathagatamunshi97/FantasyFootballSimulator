"""Load and refresh player stats from Sofascore via datafc."""
from __future__ import annotations

import json
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd
from datafc import league_player_stats_data, search_data, seasons_data

from models import SOFASCORE_POSITION_TO_FPL, SOFASCORE_POSITION_TO_PRIMARY, PlayerStats

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_CACHE = DATA_DIR / "player_stats_cache.json"
SEED_PLAYERS_FILE = DATA_DIR / "seed_players.json"

# Avoid Sofascore search API for league resolution (rate-limited frequently).
DEFAULT_TOURNAMENT_IDS: dict[str, int] = {
    "Premier League": 17,
    "LaLiga": 8,
    "Ligue 1": 34,
    "Serie A": 23,
    "Bundesliga": 35,
    "Saudi Pro League": 955,
    "MLS": 242,
}

LEAGUES = (
    "Premier League",
    "LaLiga",
    "Ligue 1",
    "Serie A",
    "Bundesliga",
    "Saudi Pro League",
    "MLS",
)
TOP5_EUROPEAN_LEAGUES = (
    "Premier League",
    "LaLiga",
    "Ligue 1",
    "Serie A",
    "Bundesliga",
)
SEASON_SUFFIXES = ("24/25", "25/26")
CALENDAR_YEAR_LEAGUES = frozenset({"MLS"})
MIN_MINUTES = 180

_STORE_LOCK = threading.Lock()

SOFASCORE_FIELDS = [
    "goals",
    "assists",
    "expectedGoals",
    "expectedAssists",
    "totalShots",
    "shotsOnTarget",
    "keyPasses",
    "tackles",
    "interceptions",
    "clearances",
    "successfulDribbles",
    "successfulDribblesPercentage",
    "accuratePasses",
    "accuratePassesPercentage",
    "accurateLongBalls",
    "accurateLongBallsPercentage",
    "saves",
    "goalsPrevented",
    "bigChancesCreated",
    "bigChancesMissed",
    "possessionLost",
    "penaltyGoals",
    "freeKickGoal",
    "yellowCards",
    "redCards",
    "rating",
    "minutesPlayed",
    "appearances",
]

_TOURNAMENT_IDS: dict[str, int] | None = None


def _nfkd(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _tournament_ids() -> dict[str, int]:
    global _TOURNAMENT_IDS
    if _TOURNAMENT_IDS is not None:
        return _TOURNAMENT_IDS
    mapping: dict[str, int] = dict(DEFAULT_TOURNAMENT_IDS)
    for league in LEAGUES:
        if league in mapping:
            continue
        hits = search_data(league, entity_type="tournament")
        exact = hits[hits["entity_name"] == league]
        if exact.empty:
            exact = hits.head(1)
        if exact.empty:
            raise RuntimeError(f"Could not resolve Sofascore tournament: {league}")
        mapping[league] = int(exact.iloc[0]["entity_id"])
    _TOURNAMENT_IDS = mapping
    return mapping


def _season_id(tournament_id: int, league: str, suffix: str) -> int:
    seasons = seasons_data(tournament_id)
    match = seasons[seasons["season_name"].str.contains(suffix, regex=False, na=False)]
    if match.empty and league in CALENDAR_YEAR_LEAGUES:
        yy = int(suffix.split("/")[0])
        start_year = 2000 + yy if yy < 50 else 1900 + yy
        for year in (start_year, start_year + 1):
            match = seasons[seasons["season_name"].str.contains(str(year), regex=False, na=False)]
            if not match.empty:
                break
    if match.empty:
        raise RuntimeError(f"Season {suffix} not found for {league} (tournament {tournament_id})")
    return int(match.iloc[0]["season_id"])


def _estimate_clean_sheet_pct(row: dict[str, Any]) -> float:
    fpl = row.get("fpl_position", "MID")
    if fpl == "GK":
        gp = _num(row.get("goals_prevented90"))
        return max(10.0, min(50.0, 28.0 + gp * 12.0))
    if fpl == "DEF":
        def_rate = (
            _num(row.get("tackles90")) * 0.35
            + _num(row.get("interceptions90")) * 0.45
            + _num(row.get("clearances90")) * 0.12
        )
        return max(8.0, min(45.0, 12.0 + def_rate * 4.5))
    if fpl == "MID":
        return max(5.0, min(25.0, 8.0 + _num(row.get("tackles90")) * 2.0))
    return 0.0


def _per90(total: float, minutes: float) -> float:
    if minutes <= 0:
        return 0.0
    return total * 90.0 / minutes


def _row_to_entry(row: pd.Series, sofascore_pos: str, season_label: str) -> dict[str, Any]:
    minutes = _num(row.get("minutesPlayed"))
    if minutes < MIN_MINUTES:
        return {}

    appearances = int(_num(row.get("appearances")))
    fpl_pos = SOFASCORE_POSITION_TO_FPL[sofascore_pos]
    primary = SOFASCORE_POSITION_TO_PRIMARY[sofascore_pos]
    p90 = lambda key: _per90(_num(row.get(key)), minutes)

    goals_prevented90 = p90("goalsPrevented")
    entry: dict[str, Any] = {
        "team": str(row.get("team_name", "")),
        "primary_position": primary,
        "fpl_position": fpl_pos,
        "positions": [primary],
        "minutes": minutes,
        "games": appearances,
        "starts": max(1, int(appearances * 0.88)),
        "goals90": p90("goals"),
        "assists90": p90("assists"),
        "xg90": p90("expectedGoals"),
        "xa90": p90("expectedAssists"),
        "shots90": p90("totalShots"),
        "shots_on_target90": p90("shotsOnTarget"),
        "key_passes90": p90("keyPasses"),
        "tackles90": p90("tackles"),
        "interceptions90": p90("interceptions"),
        "clearances90": p90("clearances"),
        "dribbles90": p90("successfulDribbles"),
        "dribble_pct": _num(row.get("successfulDribblesPercentage")),
        "passes_completed90": p90("accuratePasses"),
        "pass_pct": _num(row.get("accuratePassesPercentage")),
        "long_balls90": p90("accurateLongBalls"),
        "long_ball_pct": _num(row.get("accurateLongBallsPercentage")),
        "big_chances_created90": p90("bigChancesCreated"),
        "big_chances_missed90": p90("bigChancesMissed"),
        "possession_lost90": p90("possessionLost"),
        "penalty_goals90": p90("penaltyGoals"),
        "saves90": p90("saves"),
        "goals_prevented90": goals_prevented90,
        "goals_conceded90": max(0.4, 1.1 - goals_prevented90 * 0.35) if fpl_pos == "GK" else 0.0,
        "yellow_cards90": p90("yellowCards"),
        "red_cards90": p90("redCards"),
        "rating": _num(row.get("rating"), default=6.5),
        "seasons_used": [season_label],
        "player_id": int(_num(row.get("player_id"))),
        "player_name": str(row.get("player_name", "")).strip(),
        "league": str(row.get("league", "")),
    }
    entry["clean_sheet_pct"] = _estimate_clean_sheet_pct(entry)
    return entry


def _fetch_league_season(league: str, season_suffix: str) -> dict[int, dict[str, Any]]:
    tournament_id = _tournament_ids()[league]
    season_id = _season_id(tournament_id, league, season_suffix)
    season_label = f"20{season_suffix[:2]}-20{season_suffix[3:]}"
    players: dict[int, dict[str, Any]] = {}

    for sofascore_pos in ("G", "D", "M", "F"):
        df = league_player_stats_data(
            tournament_id=tournament_id,
            season_id=season_id,
            accumulation="total",
            max_players=1000,
            fields=SOFASCORE_FIELDS,
            position=sofascore_pos,
            order="-minutesPlayed",
        )
        if df is None or df.empty:
            continue
        df = df.copy()
        df["league"] = league
        for _, row in df.iterrows():
            pid = int(_num(row.get("player_id")))
            if pid <= 0:
                continue
            entry = _row_to_entry(row, sofascore_pos, season_label)
            if not entry:
                continue
            existing = players.get(pid)
            if existing is None or entry["minutes"] > existing["minutes"]:
                players[pid] = entry
    return players


def _pick_search_player_id(query: str, hits: pd.DataFrame) -> int | None:
    if hits is None or hits.empty:
        return None
    from player_names import normalize_key

    q = normalize_key(query)
    positioned = hits[hits["position"].notna() & (hits["position"].astype(str).str.len() > 0)]
    pool = positioned if not positioned.empty else hits
    pool_sorted = pool.sort_values("score", ascending=False)
    top_score = float(_num(pool_sorted.iloc[0].get("score"))) if not pool_sorted.empty else 0.0

    for _, row in pool.iterrows():
        if normalize_key(str(row.get("entity_name", ""))) == q:
            row_score = float(_num(row.get("score")))
            # Single-word queries can exact-match a different namesake (e.g. "Kante").
            if len(q.split()) > 1 or row_score >= top_score * 0.25:
                return int(_num(row.get("entity_id")))
            break

    best = pool_sorted.iloc[0]
    pid = int(_num(best.get("entity_id")))
    return pid if pid > 0 else None


def _sofascore_position_code(raw_name: str, player_id: int) -> str:
    from player_names import KNOWN_PLAYER_POSITIONS

    if player_id in KNOWN_PLAYER_POSITIONS:
        return KNOWN_PLAYER_POSITIONS[player_id]
    try:
        hits = search_data(raw_name.strip(), entity_type="player")
        if hits is not None and not hits.empty:
            match = hits[hits["entity_id"] == player_id]
            row = match.iloc[0] if not match.empty else hits.sort_values("score", ascending=False).iloc[0]
            pos = str(row.get("position", "M")).strip().upper()
            if pos in SOFASCORE_POSITION_TO_FPL:
                return pos
            fpl_to_code = {"GK": "G", "DEF": "D", "MID": "M", "FWD": "F"}
            if pos in fpl_to_code:
                return fpl_to_code[pos]
    except Exception:
        pass
    return "M"


def _season_suffix_matches(season_name: str, suffix: str) -> bool:
    return suffix in str(season_name)


def _fetch_career_season_index(player_id: int) -> list[dict[str, Any]]:
    from datafc.utils._client import SofascoreClient
    from datafc.utils._config import API_URLS

    base = API_URLS["sofascore"]
    rows: list[dict[str, Any]] = []
    with SofascoreClient(rate_limit=2.0) as client:
        try:
            payload = client.get(f"{base}/api/v1/player/{player_id}/statistics/seasons")
        except Exception:
            return rows
        for entry in payload.get("uniqueTournamentSeasons", []):
            tournament = entry.get("uniqueTournament", {})
            tournament_name = str(tournament.get("name", ""))
            tournament_id = int(tournament.get("id") or 0)
            for season in entry.get("seasons", []):
                season_id = int(season.get("id") or 0)
                if tournament_id <= 0 or season_id <= 0:
                    continue
                rows.append(
                    {
                        "tournament_name": tournament_name,
                        "tournament_id": tournament_id,
                        "season_name": str(season.get("year", "")),
                        "season_id": season_id,
                    }
                )
    return rows


def _fetch_player_season_via_career_api(
    player_id: int,
    player_name: str,
    season_suffix: str,
    *,
    league: str | None = None,
) -> dict[str, Any] | None:
    """Fetch one season via Sofascore player career endpoint (works for retired players)."""
    from datafc.utils._client import SofascoreClient
    from datafc.utils._config import API_URLS

    season_label = f"20{season_suffix[:2]}-20{season_suffix[3:]}"
    sofascore_pos = _sofascore_position_code(player_name, player_id)
    base = API_URLS["sofascore"]
    allowed = {league} if league else set(TOP5_EUROPEAN_LEAGUES)

    index = _fetch_career_season_index(player_id)
    with SofascoreClient(rate_limit=2.0) as client:
        for item in index:
            if item["tournament_name"] not in allowed:
                continue
            if not _season_suffix_matches(item["season_name"], season_suffix):
                continue
            try:
                stats_data = client.get(
                    f"{base}/api/v1/player/{player_id}"
                    f"/unique-tournament/{item['tournament_id']}"
                    f"/season/{item['season_id']}/statistics/overall"
                )
            except Exception:
                continue
            stats = stats_data.get("statistics") or {}
            team = stats_data.get("team") or {}
            row = pd.Series(
                {
                    **{k: stats.get(k) for k in SOFASCORE_FIELDS},
                    "player_id": player_id,
                    "player_name": player_name,
                    "team_name": team.get("name", ""),
                    "league": item["tournament_name"],
                }
            )
            entry = _row_to_entry(row, sofascore_pos, season_label)
            if entry:
                entry["seasons_used"] = [season_label]
                entry["teams_by_season"] = {season_label: entry.get("team", "")}
                return entry
    return None


def _career_top5_table_from_api(player_id: int, player_name: str) -> pd.DataFrame:
    """Build a wide career table for top-5 leagues using direct Sofascore player API."""
    from datafc.utils._client import SofascoreClient
    from datafc.utils._config import API_URLS

    base = API_URLS["sofascore"]
    records: list[dict[str, Any]] = []
    index = _fetch_career_season_index(player_id)
    with SofascoreClient(rate_limit=2.0) as client:
        for item in index:
            if item["tournament_name"] not in TOP5_EUROPEAN_LEAGUES:
                continue
            try:
                stats_data = client.get(
                    f"{base}/api/v1/player/{player_id}"
                    f"/unique-tournament/{item['tournament_id']}"
                    f"/season/{item['season_id']}/statistics/overall"
                )
            except Exception:
                continue
            stats = stats_data.get("statistics") or {}
            team = stats_data.get("team") or {}
            for stat_name, stat_value in stats.items():
                if isinstance(stat_value, (dict, list)):
                    continue
                records.append(
                    {
                        "season_name": item["season_name"],
                        "tournament_name": item["tournament_name"],
                        "team_name": team.get("name", ""),
                        "stat": stat_name,
                        "value": stat_value,
                    }
                )
    if not records:
        return pd.DataFrame()
    long_df = pd.DataFrame(records)
    wide = long_df.pivot_table(
        index=["season_name", "tournament_name", "team_name"],
        columns="stat",
        values="value",
        aggfunc="first",
    )
    return wide.reset_index()


def _find_player_in_league_season(
    player_id: int, league: str, season_suffix: str, *, player_name: str = ""
) -> dict[str, Any] | None:
    tournament_id = _tournament_ids()[league]
    season_id = _season_id(tournament_id, league, season_suffix)
    season_label = f"20{season_suffix[:2]}-20{season_suffix[3:]}"

    for sofascore_pos in ("G", "D", "M", "F"):
        df = league_player_stats_data(
            tournament_id=tournament_id,
            season_id=season_id,
            accumulation="total",
            max_players=1000,
            fields=SOFASCORE_FIELDS,
            position=sofascore_pos,
            order="-minutesPlayed",
        )
        if df is None or df.empty:
            continue
        match = df[df["player_id"] == player_id]
        if match.empty:
            continue
        row = match.iloc[0].copy()
        row["league"] = league
        entry = _row_to_entry(row, sofascore_pos, season_label)
        if entry:
            return entry
    if player_name:
        return _fetch_player_season_via_career_api(
            player_id, player_name, season_suffix, league=league
        )
    return None


def _fetch_player_season_stats(player_id: int) -> dict[str, dict[str, Any]]:
    """Scan supported leagues for this player's 24/25 and 25/26 stats."""
    season_stats: dict[str, dict[str, Any]] = {}
    target_seasons = {f"20{s[:2]}-20{s[3:]}" for s in SEASON_SUFFIXES}

    for league in LEAGUES:
        for suffix in SEASON_SUFFIXES:
            season_label = f"20{suffix[:2]}-20{suffix[3:]}"
            if season_label in season_stats:
                continue
            try:
                entry = _find_player_in_league_season(player_id, league, suffix)
            except Exception:
                continue
            if entry:
                season_stats[season_label] = entry
        if target_seasons.issubset(season_stats.keys()):
            break
    return season_stats


def _cache_key_for_player(name: str, team: str, existing_keys: set[str]) -> str:
    if name in existing_keys:
        return name
    same_base = [k for k in existing_keys if k == name or k.startswith(f"{name} (")]
    return _display_name(name, team, disambiguate=len(same_base) > 0)


def _cached_display_name(raw_name: str, cache: dict[str, Any] | None = None) -> str | None:
    """Return the cache key for a player when already in player_stats_cache."""
    from player_names import canonical_name, fuzzy_surname_match, names_loosely_match

    if cache is None:
        cache = load_cache()
    players = cache.get("players") or {}
    if not players:
        return None

    canon = canonical_name(raw_name)
    norm = _nfkd(canon).lower()
    if canon in players:
        return canon
    for name in players:
        if _nfkd(name).lower() == norm:
            return name
        if names_loosely_match(name, raw_name) or names_loosely_match(name, canon):
            return name
    fuzzy = fuzzy_surname_match(raw_name, list(players.keys()))
    return fuzzy


def _player_id_from_cache(raw_name: str, cache: dict[str, Any] | None = None) -> int | None:
    """Resolve Sofascore player id from cache / known ids — no network search."""
    from player_names import known_sofascore_id

    known_id = known_sofascore_id(raw_name)
    if known_id is not None:
        return known_id

    cached_name = _cached_display_name(raw_name, cache)
    if cached_name is None:
        return None
    if cache is None:
        cache = load_cache()
    pid = (cache.get("players") or {}).get(cached_name, {}).get("player_id")
    if pid:
        return int(pid)
    return None


def _lookup_player_id(raw_name: str, *, cache: dict[str, Any] | None = None) -> tuple[int, str]:
    """Resolve Sofascore player id and display name, with known-id / cache fallback."""
    from player_names import canonical_name, known_display_name, known_sofascore_id

    search_name = canonical_name(raw_name)
    known_id = known_sofascore_id(raw_name)
    if known_id is not None:
        return known_id, known_display_name(raw_name) or search_name

    cached_id = _player_id_from_cache(raw_name, cache)
    if cached_id is not None:
        display = _cached_display_name(raw_name, cache) or search_name
        return cached_id, display

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            hits = search_data(search_name, entity_type="player")
            player_id = _pick_search_player_id(search_name, hits)
            if player_id is None:
                raise KeyError(f"Player not found on Sofascore: {search_name}")
            if hits is not None and not hits.empty:
                match = hits[hits["entity_id"] == player_id]
                row = match.iloc[0] if not match.empty else hits.sort_values("score", ascending=False).iloc[0]
                display = str(row.get("entity_name", search_name)).strip()
            else:
                display = search_name
            return player_id, display
        except Exception as exc:
            last_exc = exc
            fallback_id = known_sofascore_id(raw_name)
            if fallback_id is not None:
                return fallback_id, known_display_name(raw_name) or search_name
            if attempt < 2 and "403" in str(exc):
                time.sleep(3 * (attempt + 1))
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise KeyError(f"Player not found on Sofascore: {search_name}")


def fetch_player_from_sofascore(raw_name: str) -> tuple[str, dict[str, Any]]:
    """Search Sofascore and pull blended stats for one player. Returns (cache_key, data)."""
    player_id, display_name = _lookup_player_id(raw_name)

    season_stats = _fetch_player_season_stats(player_id)
    if not season_stats:
        raise KeyError(
            f"No stats for '{display_name}' in supported leagues (Sofascore id {player_id}). "
            "Player may be outside the cached leagues or below minutes threshold."
        )

    blended = blend_seasons(season_stats)
    blended["player_name"] = blended.get("player_name") or display_name
    return blended["player_name"], blended


def _display_name(name: str, team: str, disambiguate: bool) -> str:
    if not disambiguate:
        return name
    short = team.split()[-1] if team else team
    if team and short:
        return f"{name} ({team})"
    return name


def _build_players_index(
    blended_by_id: dict[int, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Map display names to stats; append team when names collide across players."""
    by_name: dict[str, list[dict[str, Any]]] = {}
    for data in blended_by_id.values():
        name = data.get("player_name") or ""
        if not name:
            continue
        by_name.setdefault(name, []).append(data)

    players_out: dict[str, dict[str, Any]] = {}
    for name, entries in by_name.items():
        disambiguate = len(entries) > 1
        for data in entries:
            key = _display_name(name, data.get("team", ""), disambiguate)
            players_out[key] = {k: v for k, v in data.items() if k != "player_name"}
    return players_out


def blend_seasons(season_stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    keys = sorted(season_stats.keys())
    if not keys:
        return {}
    if len(keys) == 1:
        out = dict(season_stats[keys[0]])
        out["seasons_used"] = keys
        out["teams_by_season"] = {keys[0]: out.get("team", "")}
        return out

    w = 0.5
    a, b = season_stats[keys[0]], season_stats[keys[1]]
    numeric = [
        "goals90", "assists90", "xg90", "xa90", "shots90", "shots_on_target90",
        "key_passes90", "tackles90", "interceptions90", "clearances90", "dribbles90",
        "dribble_pct", "passes_completed90", "pass_pct", "long_balls90", "long_ball_pct",
        "big_chances_created90", "big_chances_missed90", "possession_lost90", "penalty_goals90",
        "saves90", "goals_prevented90", "goals_conceded90",
        "clean_sheet_pct", "yellow_cards90", "red_cards90", "rating",
        "npxg90", "xg_chain90", "xg_buildup90", "understat_key_passes90",
    ]
    out: dict[str, Any] = {
        "team": b.get("team") or a.get("team", ""),
        "player_name": b.get("player_name") or a.get("player_name", ""),
        "primary_position": a.get("primary_position", b.get("primary_position", "MF")),
        "fpl_position": a.get("fpl_position", b.get("fpl_position", "MID")),
        "positions": list(dict.fromkeys((a.get("positions") or []) + (b.get("positions") or []))),
        "minutes": w * _num(a.get("minutes")) + w * _num(b.get("minutes")),
        "games": int(w * _num(a.get("games")) + w * _num(b.get("games"))),
        "starts": int(w * _num(a.get("starts")) + w * _num(b.get("starts"))),
        "seasons_used": keys,
        "teams_by_season": {k: season_stats[k].get("team", "") for k in keys},
    }
    for k in numeric:
        out[k] = w * _num(a.get(k)) + w * _num(b.get(k))
    return out


def refresh_cache(
    *,
    leagues: tuple[str, ...] = LEAGUES,
    season_suffixes: tuple[str, ...] = SEASON_SUFFIXES,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """Pull Sofascore league player stats and write blended cache JSON."""
    merged: dict[int, dict[str, dict[str, Any]]] = {}
    log: list[str] = []

    for league in leagues:
        for suffix in season_suffixes:
            season_label = f"20{suffix[:2]}-20{suffix[3:]}"
            try:
                batch = _fetch_league_season(league, suffix)
                for pid, entry in batch.items():
                    merged.setdefault(pid, {})[season_label] = entry
                log.append(f"{league} {suffix}: {len(batch)} players")
                print(f"  {league} {suffix}: {len(batch)} players", flush=True)
            except Exception as exc:
                log.append(f"{league} {suffix}: ERROR {exc}")
                print(f"  {league} {suffix}: FAILED ({exc})", flush=True)

    if not merged:
        raise RuntimeError("No Sofascore data fetched. Check network access.")

    blended_by_id = {pid: blend_seasons(seasons) for pid, seasons in merged.items()}
    players_out = _build_players_index(blended_by_id)

    from understat_client import merge_understat_into_players

    merge_understat_into_players(players_out)

    cache = {
        "players": players_out,
        "meta": {
            "source": "sofascore+understat",
            "seasons": [f"20{s[:2]}-20{s[3:]}" for s in season_suffixes],
            "leagues": list(leagues),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "player_count": len(players_out),
            "fetch_log": log,
        },
    }
    save_cache(cache, cache_path)
    return cache


def load_cache(path: Path | None = None) -> dict[str, Any]:
    cache_path = path or DEFAULT_CACHE
    if not cache_path.exists():
        return {"players": {}, "meta": {"source": "empty"}}
    return json.loads(cache_path.read_text(encoding="utf-8"))


def merge_seed_players(cache: dict[str, Any]) -> bool:
    """Insert bundled player snapshots when missing (survives Sofascore rate limits)."""
    if not SEED_PLAYERS_FILE.exists():
        return False
    try:
        seed = json.loads(SEED_PLAYERS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    players = cache.setdefault("players", {})
    changed = False
    for name, data in (seed.get("players") or {}).items():
        if name not in players:
            players[name] = data
            changed = True
    if changed:
        meta = cache.setdefault("meta", {})
        meta["seed_merged_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return changed


def load_seed_player(raw: str) -> tuple[str, dict[str, Any]] | None:
    """Return bundled stats for a player when Sofascore is unavailable."""
    if not SEED_PLAYERS_FILE.exists():
        return None
    try:
        seed = json.loads(SEED_PLAYERS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    players = seed.get("players") or {}
    from player_names import canonical_name, known_sofascore_id, names_loosely_match

    canon = canonical_name(raw)
    if canon in players:
        return canon, dict(players[canon])
    kid = known_sofascore_id(raw)
    for name, data in players.items():
        if names_loosely_match(name, raw) or names_loosely_match(name, canon):
            return name, dict(data)
        if kid is not None and data.get("player_id") == kid:
            return name, dict(data)
    return None


def save_cache(data: dict[str, Any], path: Path | None = None) -> None:
    cache_path = path or DEFAULT_CACHE
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class StatsStore:
    """Player stats backed by Sofascore cache JSON."""

    def __init__(self, cache_path: Path | None = None) -> None:
        self.cache_path = cache_path or DEFAULT_CACHE
        self._cache = load_cache(self.cache_path)
        if merge_seed_players(self._cache):
            save_cache(self._cache, self.cache_path)
        self._players: dict[str, PlayerStats] = {
            name: PlayerStats.from_dict(name, data)
            for name, data in self._cache.get("players", {}).items()
        }
        self._norm_index = {_nfkd(name).lower(): name for name in self._players}

    @property
    def players(self) -> dict[str, PlayerStats]:
        return self._players

    def resolve(self, raw: str) -> str:
        from player_names import resolve_player_name

        return resolve_player_name(raw, self)

    def _add_player_to_cache(self, cache_key: str, data: dict[str, Any]) -> None:
        stored = {k: v for k, v in data.items() if k != "player_name"}
        self._cache.setdefault("players", {})[cache_key] = stored
        meta = self._cache.setdefault("meta", {})
        meta["player_count"] = len(self._cache["players"])
        meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_cache(self._cache, self.cache_path)
        self._players[cache_key] = PlayerStats.from_dict(cache_key, stored)
        self._norm_index[_nfkd(cache_key).lower()] = cache_key

    def cached_player_id(self, raw: str) -> int | None:
        """Return Sofascore player id from cache / known ids without network search."""
        return _player_id_from_cache(raw, self._cache)

    def _find_cached_player_name(self, raw: str) -> str | None:
        from player_names import canonical_name, fuzzy_surname_match, known_sofascore_id, names_loosely_match

        canon = self.resolve(raw)
        if canon in self._players:
            return canon
        norm = _nfkd(canon).lower()
        if norm in self._norm_index:
            return self._norm_index[norm]
        for name in self._players:
            if names_loosely_match(name, raw) or names_loosely_match(name, canon):
                return name
        fuzzy = fuzzy_surname_match(raw, list(self._players.keys()))
        if fuzzy:
            return fuzzy
        kid = known_sofascore_id(raw)
        if kid is not None:
            for name, data in self._cache.get("players", {}).items():
                if data.get("player_id") == kid:
                    return name
        seed = load_seed_player(raw)
        if seed is not None:
            return seed[0]
        return None

    def fetch_and_cache(self, raw: str) -> str:
        """Fetch one player from Sofascore, merge Understat, persist to cache."""
        with _STORE_LOCK:
            cached = self._find_cached_player_name(raw)
            if cached is not None:
                if cached not in self._players:
                    data = self._cache.get("players", {}).get(cached, {})
                    if data:
                        self._players[cached] = PlayerStats.from_dict(cached, data)
                        self._norm_index[_nfkd(cached).lower()] = cached
                return cached

            seed_hit = load_seed_player(raw)
            if seed_hit is not None:
                cache_key, blended = seed_hit
                from understat_client import merge_understat_into_players

                merge_understat_into_players({cache_key: blended})
                self._add_player_to_cache(cache_key, blended)
                print(f"  Loaded from seed: {cache_key}", flush=True)
                return cache_key

            canon = self.resolve(raw)
            if canon in self._players:
                return canon

            print(f"  Fetching stats for: {raw}", flush=True)
            search_name = canon if canon != raw.strip() else raw
            blended: dict[str, Any] | None = None
            try:
                _, blended = fetch_player_from_sofascore(search_name)
            except KeyError:
                blended = None
            except Exception as exc:
                if "403" not in str(exc):
                    raise
                blended = None
            if blended is None:
                from seasonal_stats import fetch_best_historical_stats

                _, blended = fetch_best_historical_stats(search_name)
                print(f"  Using best historical top-league season for: {search_name}", flush=True)
            from understat_client import merge_understat_into_players

            name = blended.get("player_name") or raw
            team = blended.get("team", "")
            cache_key = _cache_key_for_player(name, team, set(self._players.keys()))
            merge_understat_into_players({cache_key: blended})
            self._add_player_to_cache(cache_key, blended)
            print(f"  Cached as: {cache_key}", flush=True)
            return cache_key

    def ensure_one(self, raw: str) -> str:
        """Resolve name; fetch from Sofascore when missing from cache."""
        cached = self._find_cached_player_name(raw)
        if cached is not None:
            if cached not in self._players:
                data = self._cache.get("players", {}).get(cached, {})
                if data:
                    self._players[cached] = PlayerStats.from_dict(cached, data)
                    self._norm_index[_nfkd(cached).lower()] = cached
            return cached
        return self.fetch_and_cache(raw)

    def ensure_players(self, names: list[str]) -> dict[str, str]:
        """Ensure all players exist in cache. Returns raw -> canonical name map."""
        mapping: dict[str, str] = {}
        for raw in names:
            if not raw or not str(raw).strip():
                continue
            mapping[raw] = self.ensure_one(str(raw).strip())
        return mapping

    def require(self, names: list[str]) -> dict[str, PlayerStats]:
        keys = [self.ensure_one(raw) for raw in names]
        return {k: self._players[k] for k in keys}

    def cached_stats_map(self, names: list[str]) -> dict[str, PlayerStats]:
        """Return stats from cache only — no Sofascore/network fetch (fast lineup assign)."""
        out: dict[str, PlayerStats] = {}
        for raw in names:
            if not raw or not str(raw).strip():
                continue
            canon = str(raw).strip()
            cached = self._find_cached_player_name(canon)
            if cached:
                if cached in self._players:
                    out[canon] = self._players[cached]
                    continue
                data = self._cache.get("players", {}).get(cached, {})
                if data:
                    out[canon] = PlayerStats.from_dict(cached, data)
                    continue
            if canon in self._players:
                out[canon] = self._players[canon]
            else:
                out[canon] = PlayerStats.from_dict(
                    canon,
                    {"primary_position": "MF", "fpl_position": "MID", "positions": ["MF"]},
                )
        return out

    def reload(self) -> None:
        self._cache = load_cache(self.cache_path)
        self._players = {
            name: PlayerStats.from_dict(name, data)
            for name, data in self._cache.get("players", {}).items()
        }
        self._norm_index = {_nfkd(name).lower(): name for name in self._players}
