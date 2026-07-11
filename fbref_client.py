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
DEFENSE_STAT_TYPE = "defense"
AERIAL_CLEARANCE_RATIO: dict[str, float] = {
    "GK": 0.10,
    "DEF": 0.48,
    "MID": 0.22,
    "FWD": 0.12,
}
DEFAULT_AERIAL_WON_PCT = 55.0


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


def _simplify_column_name(name: str) -> str:
    text = str(name)
    if "_level_0_" in text:
        return text.rsplit("_level_0_", 1)[-1]
    return text


def _flat_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.reset_index()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [
            "_".join(str(part) for part in col if str(part)).strip("_")
            for col in out.columns
        ]
    for col in list(out.columns):
        short = _simplify_column_name(col)
        if short != col and short not in out.columns:
            out[short] = out[col]
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
    suffixes = {_simplify_column_name(name) for name in candidates}
    for col in row.index:
        short = _simplify_column_name(col)
        if short in suffixes or str(col).endswith(tuple(candidates)):
            val = row[col]
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                return val
    return None


def _estimate_aerial_stats(
    clearances90: float,
    fpl_pos: str,
) -> tuple[float, float, float]:
    if clearances90 <= 0:
        return 0.0, 0.0, 0.0
    ratio = AERIAL_CLEARANCE_RATIO.get(fpl_pos, 0.20)
    won90 = clearances90 * ratio
    pct = DEFAULT_AERIAL_WON_PCT
    lost90 = won90 * (100.0 - pct) / pct if pct > 0 else 0.0
    return won90, lost90, pct


def _resolve_aerial_stats(
    row: pd.Series,
    minutes: float,
    *,
    clearances90: float,
    fpl_pos: str,
) -> tuple[float, float, float, str]:
    aerials_won = _num(_col(
        row,
        "Aerial Duels_Won",
        "aerials_won",
        "Performance_Won",
        "Won",
    ))
    aerials_lost = _num(_col(
        row,
        "Aerial Duels_Lost",
        "aerials_lost",
        "Performance_Lost",
        "Lost",
    ))
    aerials_won_pct = _num(_col(
        row,
        "Aerial Duels_Won%",
        "aerials_won_pct",
        "Performance_Won%",
        "Won%",
    ), default=-1.0)

    if aerials_won > 0 or aerials_lost > 0:
        won90 = _per90(aerials_won, minutes)
        lost90 = _per90(aerials_lost, minutes)
        if aerials_won_pct < 0 and aerials_won + aerials_lost > 0:
            aerials_won_pct = aerials_won / (aerials_won + aerials_lost) * 100.0
        return won90, lost90, max(aerials_won_pct, 0.0), "fbref"

    won90, lost90, pct = _estimate_aerial_stats(clearances90, fpl_pos)
    if won90 > 0:
        return won90, lost90, pct, "estimated"
    return 0.0, 0.0, 0.0, ""


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

    tklw = _num(_col(row, "Performance_TklW", "Tackles_TklW"))
    if tklw <= 0:
        tklw = _num(_col(row, "Tackles_TklW"))
    tackles90 = _per90(tklw, minutes)
    interceptions90 = _per90(_num(_col(row, "Performance_Int", "Int")), minutes)
    yellow90 = _per90(_num(_col(row, "Performance_CrdY")), minutes)
    red90 = _per90(_num(_col(row, "Performance_CrdR")), minutes)

    clearances90 = _per90(_num(_col(row, "Clr", "clearances")), minutes)
    blocks90 = _per90(_num(_col(row, "Blocks_Blocks", "Blocks")), minutes)
    if clearances90 <= 0:
        tkl_won = _num(_col(row, "Tackles_TklW", "Performance_TklW"))
        clearances90 = max(clearances90, _per90(tkl_won, minutes) * 3.0)
    ball_recoveries90 = _per90(
        _num(_col(row, "Performance_Recov", "Aerial Duels_Recov", "Recov", "ball_recoveries")),
        minutes,
    )

    pos_raw = str(_col(row, "pos") or "M")
    fpl_pos, primary, positions = _map_fbref_position(pos_raw)
    aerials_won90, aerials_lost90, aerials_won_pct, aerials_source = _resolve_aerial_stats(
        row,
        minutes,
        clearances90=clearances90,
        fpl_pos=fpl_pos,
    )

    rating = min(8.5, max(6.2, 6.5 + goals90 * 0.75 + assists90 * 0.45 + tackles90 * 0.08))

    entry: dict[str, Any] = {
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
        "clearances90": clearances90,
        "blocks90": blocks90,
        "ball_recoveries90": ball_recoveries90,
        "aerials_won90": aerials_won90,
        "aerials_lost90": aerials_lost90,
        "aerials_won_pct": aerials_won_pct,
        "dribbles90": 0.0,
        "key_passes90": 0.0,
        "passes_completed90": 0.0,
        "pass_pct": 0.0,
        "yellow_cards90": yellow90,
        "red_cards90": red90,
        "rating": round(rating, 2),
        "fbref_matched": True,
    }
    if aerials_source:
        entry["aerials_source"] = aerials_source
    return entry


def _map_fbref_position(pos_raw: str) -> tuple[str, str, list[str]]:
    from position_enrichment import infer_fpl_from_primary, parse_fbref_positions, pick_primary_position
    from collections import Counter

    positions = parse_fbref_positions(pos_raw)
    primary = pick_primary_position(Counter({p: 1.0 for p in positions}))
    fpl = infer_fpl_from_primary(primary, positions)
    return fpl, primary, positions


def _read_defense_player_frame(
    reader: sd.FBref,
    lkey: str,
    skey: str,
    season: Any,
) -> pd.DataFrame | None:
    """FBref defensive-actions table (clearances/blocks) — not exposed by soccerdata stat_type."""
    from lxml import etree, html
    from soccerdata._common import standardize_colnames
    from soccerdata.fbref import _fix_nation_col, _parse_table

    filepath = reader.data_dir / f"players_{lkey}_{skey}_defense.html"
    url = (
        "https://fbref.com"
        + "/".join(season.url.split("/")[:-1])
        + "/defense/"
        + season.url.split("/")[-1]
    )
    try:
        content = reader.get(url, filepath)
    except Exception:
        return None
    tree = html.parse(content)
    try:
        (el,) = tree.xpath("//comment()[contains(.,'div_stats_defense')]")
    except ValueError:
        return None
    parser = etree.HTMLParser(recover=True)
    tables = etree.fromstring(el.text, parser).xpath("//table[contains(@id, 'stats_defense')]")
    if not tables:
        return None
    df_table = _parse_table(tables[0])
    df_table = _fix_nation_col(df_table)
    out = (
        df_table.rename(columns={"Squad": "team"})
        .pipe(standardize_colnames, cols=["Player", "Nation", "Pos", "Age", "Born"])
        .reset_index(drop=True)
    )
    return _flat_df(out)


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
        try:
            reader = sd.FBref(leagues=[fbref_league], seasons=[season_label])
            try:
                seasons = reader.read_seasons()
            except (ValueError, Exception):
                seasons = pd.DataFrame()
            frames: list[pd.DataFrame] = []
            for stat_type in STAT_TYPES:
                try:
                    raw = reader.read_player_season_stats(stat_type=stat_type)
                except Exception:
                    continue
                if raw is None or raw.empty:
                    continue
                frames.append(_flat_df(raw))
            for (lkey, skey), season in seasons.iterrows():
                defense = _read_defense_player_frame(reader, lkey, skey, season)
                if defense is not None and not defense.empty:
                    frames.append(defense)
                    break
        except Exception as exc:
            from understat_client import _is_chrome_missing

            if _is_chrome_missing(exc):
                _fbref_league_cache[cache_key] = {}
                continue
            raise
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
        "blocks90",
        "ball_recoveries90",
        "aerials_won90",
        "aerials_lost90",
        "aerials_won_pct",
        "aerials_source",
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
        if (
            isinstance(value, (int, float))
            and value == 0
            and isinstance(data.get(key), (int, float))
            and float(data.get(key) or 0) > 0
        ):
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
