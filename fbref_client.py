"""Fetch historical player-season stats from FBref via soccerdata."""
from __future__ import annotations

from typing import Any

import pandas as pd
import soccerdata as sd

from understat_client import _lookup_understat, normalize_name, normalize_team

FBREF_LEAGUES = [
    "ENG-Premier League",
    "ESP-La Liga",
    "ITA-Serie A",
    "GER-Bundesliga",
    "FRA-Ligue 1",
]

LEAGUE_TO_FBREF: dict[str, str] = {
    "Premier League": "ENG-Premier League",
    "LaLiga": "ESP-La Liga",
    "Ligue 1": "FRA-Ligue 1",
    "Serie A": "ITA-Serie A",
    "Bundesliga": "GER-Bundesliga",
}

FBREF_TO_LEAGUE = {v: k for k, v in LEAGUE_TO_FBREF.items()}

MIN_MINUTES = 180
STAT_TYPES = ("standard", "shooting", "misc")


def season_label_from_suffix(suffix: str) -> str:
    yy = int(suffix.split("/")[0])
    start = 2000 + yy if yy < 50 else 1900 + yy
    return f"{start}-{start + 1}"

_fbref_league_cache: dict[tuple[str, str], dict[tuple[str, str], dict[str, Any]]] = {}


def _resolve_league(
    data: dict[str, Any],
    season_suffix: str,
    *,
    display_name: str = "",
    player_id: int | None = None,
) -> str | None:
    league = str(data.get("league") or "").strip()
    if league in LEAGUE_TO_FBREF:
        return league
    if player_id is None and display_name:
        from player_names import known_sofascore_id

        player_id = known_sofascore_id(display_name)
    if player_id:
        from player_names import known_season_context

        ctx = known_season_context(int(player_id), season_suffix)
        if ctx and ctx.get("league") in LEAGUE_TO_FBREF:
            return str(ctx["league"])
    return None


def _flat_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.reset_index()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [
            "_".join(str(part) for part in col if str(part)).strip("_")
            for col in out.columns
        ]
    return out


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _per90(total: float, minutes: float) -> float:
    if minutes <= 0:
        return 0.0
    return total * 90.0 / minutes


def _col(row: pd.Series, *candidates: str) -> Any:
    for name in candidates:
        if name in row.index:
            val = row[name]
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                return val
    return None


def _row_to_fbref_entry(row: pd.Series, league_name: str) -> dict[str, Any]:
    minutes = _num(_col(row, "Playing Time_Min", "Min"))
    if minutes < MIN_MINUTES:
        return {}

    games = int(_num(_col(row, "Playing Time_MP", "MP")))
    starts = int(_num(_col(row, "Playing Time_Starts", "Starts")))
    goals = _num(_col(row, "Performance_Gls", "Standard_Gls"))
    assists = _num(_col(row, "Performance_Ast"))
    goals90 = _num(_col(row, "Per 90 Minutes_Gls"))
    assists90 = _num(_col(row, "Per 90 Minutes_Ast"))
    if goals90 <= 0:
        goals90 = _per90(goals, minutes)
    if assists90 <= 0:
        assists90 = _per90(assists, minutes)

    shots90 = _num(_col(row, "Standard_Sh/90"))
    if shots90 <= 0:
        shots90 = _per90(_num(_col(row, "Standard_Sh")), minutes)
    sot90 = _num(_col(row, "Standard_SoT/90"))
    if sot90 <= 0:
        sot90 = _per90(_num(_col(row, "Standard_SoT")), minutes)

    tackles90 = _per90(_num(_col(row, "Performance_TklW")), minutes)
    interceptions90 = _per90(_num(_col(row, "Performance_Int")), minutes)
    yellow90 = _per90(_num(_col(row, "Performance_CrdY")), minutes)
    red90 = _per90(_num(_col(row, "Performance_CrdR")), minutes)

    pos_raw = str(_col(row, "pos") or "M")
    fpl_pos, primary, positions = _map_fbref_position(pos_raw)

    rating = min(8.5, max(6.2, 6.5 + goals90 * 0.75 + assists90 * 0.45 + tackles90 * 0.08))

    return {
        "team": str(_col(row, "team") or ""),
        "league": league_name,
        "pos_raw": pos_raw,
        "primary_position": primary,
        "fpl_position": fpl_pos,
        "positions": positions,
        "minutes": minutes,
        "games": max(games, 1),
        "starts": max(starts, 1),
        "goals90": goals90,
        "assists90": assists90,
        "shots90": shots90,
        "shots_on_target90": sot90,
        "tackles90": tackles90,
        "interceptions90": interceptions90,
        "clearances90": 0.0,
        "dribbles90": 0.0,
        "key_passes90": 0.0,
        "passes_completed90": 0.0,
        "pass_pct": 0.0,
        "yellow_cards90": yellow90,
        "red_cards90": red90,
        "rating": round(rating, 2),
        "fbref_matched": True,
    }


def _map_fbref_position(pos_raw: str) -> tuple[str, str, list[str]]:
    from position_enrichment import infer_fpl_from_primary, parse_fbref_positions, pick_primary_position
    from collections import Counter

    positions = parse_fbref_positions(pos_raw)
    primary = pick_primary_position(Counter({p: 1.0 for p in positions}))
    fpl = infer_fpl_from_primary(primary, positions)
    return fpl, primary, positions


def _merge_stat_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    base = frames[0]
    keys = [k for k in ("team", "player") if k in base.columns]
    if len(keys) < 2:
        return base
    for extra in frames[1:]:
        if not all(k in extra.columns for k in keys):
            continue
        overlap = [c for c in extra.columns if c in base.columns and c not in keys]
        base = base.merge(extra.drop(columns=overlap, errors="ignore"), on=keys, how="left")
    return base


def _build_fbref_index_for_leagues(
    season_label: str,
    fbref_leagues: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for fbref_league in fbref_leagues:
        cache_key = (season_label, fbref_league)
        if cache_key in _fbref_league_cache:
            merged.update(_fbref_league_cache[cache_key])
            continue

        league_name = FBREF_TO_LEAGUE[fbref_league]
        reader = sd.FBref(leagues=[fbref_league], seasons=[season_label])
        frames: list[pd.DataFrame] = []
        for stat_type in STAT_TYPES:
            try:
                raw = reader.read_player_season_stats(stat_type=stat_type)
            except Exception:
                continue
            if raw is None or raw.empty:
                continue
            frames.append(_flat_df(raw))
        league_index: dict[tuple[str, str], dict[str, Any]] = {}
        if frames:
            table = _merge_stat_frames(frames)
            for _, row in table.iterrows():
                entry = _row_to_fbref_entry(row, league_name)
                if not entry:
                    continue
                player = normalize_name(str(row.get("player", "")))
                team = normalize_team(str(row.get("team", "")))
                if not player:
                    continue
                key = (player, team)
                if key not in league_index or entry["minutes"] > league_index[key]["minutes"]:
                    league_index[key] = entry
        _fbref_league_cache[cache_key] = league_index
        merged.update(league_index)
    return merged


def _build_fbref_index(season_label: str, league: str) -> dict[tuple[str, str], dict[str, Any]]:
    if league not in LEAGUE_TO_FBREF:
        return {}
    return _build_fbref_index_for_leagues(season_label, [LEAGUE_TO_FBREF[league]])


def fetch_fbref_season_index(
    season_suffix: str,
    league: str | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    if not league or league not in LEAGUE_TO_FBREF:
        return {}
    season_label = season_label_from_suffix(season_suffix)
    return _build_fbref_index(season_label, league)


def lookup_fbref_player(
    index: dict[tuple[str, str], dict[str, Any]],
    display_name: str,
    team: str,
) -> dict[str, Any] | None:
    hit = _lookup_understat(index, display_name, team)  # same fuzzy name+team logic
    return dict(hit) if hit else None


FBREF_STAT_KEYS = frozenset(
    {
        "minutes",
        "games",
        "starts",
        "goals90",
        "assists90",
        "shots90",
        "shots_on_target90",
        "tackles90",
        "interceptions90",
        "clearances90",
        "dribbles90",
        "key_passes90",
        "passes_completed90",
        "pass_pct",
        "yellow_cards90",
        "red_cards90",
        "rating",
        "primary_position",
        "fpl_position",
        "positions",
        "league",
        "team",
    }
)


def _should_fill(data: dict[str, Any], key: str) -> bool:
    if key not in data:
        return True
    value = data[key]
    if value is None:
        return True
    if isinstance(value, (int, float)) and value == 0:
        return True
    if key == "rating" and value == 7.0:
        return True
    return False


def merge_fbref_for_player_season(
    display_name: str,
    data: dict[str, Any],
    season_suffix: str,
    *,
    overwrite_zeros: bool = True,
    player_id: int | None = None,
) -> None:
    """Attach FBref season stats in-place (fills missing/zero Sofascore fields)."""
    league = _resolve_league(
        data, season_suffix, display_name=display_name, player_id=player_id
    )
    if not league:
        data.setdefault("fbref_matched", False)
        return
    data.setdefault("league", league)
    index = fetch_fbref_season_index(season_suffix, league=league)
    hit = lookup_fbref_player(index, display_name, str(data.get("team", "")))
    if hit is None:
        data.setdefault("fbref_matched", False)
        return

    data["fbref_matched"] = True
    for key, value in hit.items():
        if key not in FBREF_STAT_KEYS:
            continue
        if overwrite_zeros or _should_fill(data, key):
            data[key] = value


def build_fbref_season_entry(
    player_id: int,
    display_name: str,
    season_suffix: str,
    ctx: dict[str, str],
) -> dict[str, Any] | None:
    """Build a full season stats dict from FBref (fallback when Sofascore unavailable)."""
    from models import SOFASCORE_POSITION_TO_FPL, SOFASCORE_POSITION_TO_PRIMARY
    from player_names import KNOWN_PLAYER_POSITIONS, KNOWN_PLAYER_PRIMARY, apply_known_position_overrides

    index = fetch_fbref_season_index(season_suffix, league=ctx.get("league"))
    hit = lookup_fbref_player(index, display_name, ctx["team"])
    if hit is None:
        return None

    season_label = season_label_from_suffix(season_suffix)
    apply_known_position_overrides(hit, player_id)
    pos = KNOWN_PLAYER_POSITIONS.get(player_id, "M")
    if player_id in KNOWN_PLAYER_POSITIONS and player_id not in KNOWN_PLAYER_PRIMARY:
        fpl = SOFASCORE_POSITION_TO_FPL[pos]
        primary = SOFASCORE_POSITION_TO_PRIMARY[pos]
    elif hit.get("primary_position") and hit.get("fpl_position"):
        fpl = hit["fpl_position"]
        primary = hit["primary_position"]
    elif hit.get("fpl_position"):
        fpl = hit["fpl_position"]
        primary = hit.get("primary_position") or SOFASCORE_POSITION_TO_PRIMARY.get(pos, "CM")
    else:
        fpl = SOFASCORE_POSITION_TO_FPL[pos]
        primary = SOFASCORE_POSITION_TO_PRIMARY[pos]

    entry: dict[str, Any] = {
        **hit,
        "team": ctx["team"],
        "league": ctx.get("league") or hit.get("league", ""),
        "fpl_position": fpl,
        "primary_position": primary,
        "positions": hit.get("positions") or [primary],
        "player_id": player_id,
        "seasons_used": [season_label],
        "teams_by_season": {season_label: ctx["team"]},
        "season_profile": season_label,
        "data_source": "fbref",
        "fbref_matched": True,
    }
    return entry
