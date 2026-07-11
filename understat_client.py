"""Supplement player cache with Understat xGChain / xGBuildup / npxG via soccerdata."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd
import soccerdata as sd

UNDERSTAT_LEAGUES = [
    "ENG-Premier League",
    "ESP-La Liga",
    "ITA-Serie A",
    "GER-Bundesliga",
    "FRA-Ligue 1",
]
UNDERSTAT_SEASONS = ("2425", "2526")
MIN_MINUTES = 180

_understat_season_cache: dict[str, dict[tuple[str, str], dict[str, float]]] = {}


def season_start_year_from_suffix(suffix: str) -> int:
    """Sofascore '23/24' -> calendar start year 2023; '14/15' -> 2014."""
    yy = int(str(suffix).split("/")[0])
    return 2000 + yy if yy < 50 else 1900 + yy


def understat_code_from_suffix(suffix: str) -> str:
    """Sofascore '23/24' -> Understat '2324'."""
    a, b = suffix.split("/")
    return f"{int(a):02d}{int(b):02d}"


def _build_understat_index(df: pd.DataFrame) -> dict[tuple[str, str], dict[str, float]]:
    merged: dict[tuple[str, str], dict[str, float]] = {}
    if df is None or df.empty:
        return merged
    df = df.reset_index()
    for _, row in df.iterrows():
        minutes = _num(row.get("minutes"))
        if minutes < MIN_MINUTES:
            continue
        player = normalize_name(str(row.get("player", "")))
        team = normalize_team(str(row.get("team", "")))
        if not player:
            continue
        merged[(player, team)] = {
            "minutes": minutes,
            "npxg90": _per90(_num(row.get("np_xg")), minutes),
            "xg_chain90": _per90(_num(row.get("xg_chain")), minutes),
            "xg_buildup90": _per90(_num(row.get("xg_buildup")), minutes),
            "understat_xg90": _per90(_num(row.get("xg")), minutes),
            "understat_xa90": _per90(_num(row.get("xa")), minutes),
            "understat_key_passes90": _per90(_num(row.get("key_passes")), minutes),
            "understat_shots90": _per90(_num(row.get("shots")), minutes),
        }
    return merged


def _is_chrome_missing(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "chrome not found" in msg or "install it first" in msg


def fetch_understat_season_index(season_suffix: str) -> dict[tuple[str, str], dict[str, float]]:
    code = understat_code_from_suffix(season_suffix)
    if code in _understat_season_cache:
        return _understat_season_cache[code]
    try:
        reader = sd.Understat(leagues=UNDERSTAT_LEAGUES, seasons=[code])
        df = reader.read_player_season_stats()
    except Exception as exc:
        if _is_chrome_missing(exc):
            _understat_season_cache[code] = {}
            return {}
        raise
    index = _build_understat_index(df)
    _understat_season_cache[code] = index
    return index


def merge_understat_for_player_season(
    display_name: str,
    data: dict[str, Any],
    season_suffix: str,
) -> None:
    """Attach Understat fields for one season in-place."""
    try:
        index = fetch_understat_season_index(season_suffix)
    except Exception as exc:
        if _is_chrome_missing(exc):
            data["understat_matched"] = False
            return
        raise
    hit = _lookup_understat(index, display_name, str(data.get("team", "")))
    if hit is None:
        data["understat_matched"] = False
        return
    data["understat_matched"] = True
    if hit.get("minutes"):
        data["minutes"] = hit["minutes"]
    for k, v in hit.items():
        if k in UNDERSTAT_ONLY_KEYS:
            data[k] = v
    if data.get("npxg90", 0) > 0 and data.get("xg90", 0) == 0:
        data["xg90"] = data["npxg90"]


def _nfkd(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in text if not unicodedata.combining(c))


def normalize_name(name: str) -> str:
    text = _nfkd(name).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # N'Golo Kante -> n golo kante; collapse split particles for Understat keys
    text = text.replace("n golo kante", "ngolo kante")
    return text


def normalize_team(team: str) -> str:
    text = normalize_name(team)
    for old, new in (
        ("manchester city", "man city"),
        ("manchester united", "man united"),
        ("manchester utd", "man united"),
        ("man utd", "man united"),
        ("real madrid cf", "real madrid"),
        ("atletico madrid", "atletico"),
        ("athletic club", "athletic bilbao"),
        ("inter milan", "inter"),
        ("paris saint germain", "psg"),
        ("paris s g", "psg"),
        ("paris sg", "psg"),
        ("as monaco", "monaco"),
        ("ssc napoli", "napoli"),
        ("real betis", "betis"),
        ("fc barcelona", "barcelona"),
        ("fc bayern munchen", "bayern"),
        ("bayern munchen", "bayern"),
        ("newcastle united", "newcastle"),
        ("nottingham forest", "nott m forest"),
        ("tottenham hotspur", "tottenham"),
        ("wolverhampton wanderers", "wolves"),
        ("internazionale", "inter"),
        ("olympique lyonnais", "lyon"),
        ("olympique marseille", "marseille"),
    ):
        text = text.replace(old, new)
    return text


def _per90(total: float, minutes: float) -> float:
    if minutes <= 0:
        return 0.0
    return total * 90.0 / minutes


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def fetch_understat_blended() -> dict[tuple[str, str], dict[str, float]]:
    """
    Return {(norm_player, norm_team): per90 understat stats} blended 50/50 across seasons.
  """
    try:
        reader = sd.Understat(leagues=UNDERSTAT_LEAGUES, seasons=list(UNDERSTAT_SEASONS))
        df = reader.read_player_season_stats()
    except Exception as exc:
        if _is_chrome_missing(exc):
            return {}
        raise
    if df is None or df.empty:
        return {}

    df = df.reset_index()
    col_map = {
        "player": "player",
        "team": "team",
        "season": "season",
        "minutes": "minutes",
        "xg": "xg",
        "np_xg": "np_xg",
        "xa": "xa",
        "xg_chain": "xg_chain",
        "xg_buildup": "xg_buildup",
        "key_passes": "key_passes",
        "shots": "shots",
    }
    for src, dst in list(col_map.items()):
        if src not in df.columns and dst in df.columns:
            col_map[src] = dst

    merged: dict[tuple[str, str], dict[str, dict[str, float]]] = {}
    for _, row in df.iterrows():
        minutes = _num(row.get("minutes"))
        if minutes < MIN_MINUTES:
            continue
        player = normalize_name(str(row.get("player", "")))
        team = normalize_team(str(row.get("team", "")))
        season = str(row.get("season", ""))
        if not player:
            continue
        entry = {
            "minutes": minutes,
            "npxg90": _per90(_num(row.get("np_xg")), minutes),
            "xg_chain90": _per90(_num(row.get("xg_chain")), minutes),
            "xg_buildup90": _per90(_num(row.get("xg_buildup")), minutes),
            "understat_xg90": _per90(_num(row.get("xg")), minutes),
            "understat_xa90": _per90(_num(row.get("xa")), minutes),
            "understat_key_passes90": _per90(_num(row.get("key_passes")), minutes),
            "understat_shots90": _per90(_num(row.get("shots")), minutes),
        }
        key = (player, team)
        merged.setdefault(key, {})[season] = entry

    out: dict[tuple[str, str], dict[str, float]] = {}
    for key, seasons in merged.items():
        keys = sorted(seasons.keys())
        if not keys:
            continue
        if len(keys) == 1:
            out[key] = seasons[keys[0]]
            continue
        a, b = seasons[keys[0]], seasons[keys[1]]
        w = 0.5
        out[key] = {k: w * a[k] + w * b[k] for k in a}
    return out


def _strip_disambiguation(display_name: str) -> str:
    if " (" in display_name:
        return display_name.rsplit(" (", 1)[0]
    return display_name


def _lookup_understat(
    index: dict[tuple[str, str], dict[str, float]],
    player_name: str,
    team: str,
) -> dict[str, float] | None:
    base = normalize_name(_strip_disambiguation(player_name))
    team_n = normalize_team(team)

    if (base, team_n) in index:
        return index[(base, team_n)]

    # Extended name on same team (e.g. "kylian mbappe" -> "kylian mbappe lottin")
    base_tokens = set(base.split())
    team_hits: list[tuple[tuple[str, str], dict[str, float]]] = []
    for key, value in index.items():
        if key[1] != team_n:
            continue
        player_tokens = set(key[0].split())
        if base_tokens <= player_tokens or player_tokens <= base_tokens:
            team_hits.append((key, value))
    if len(team_hits) == 1:
        return team_hits[0][1]
    if len(team_hits) > 1:
        team_hits.sort(key=lambda x: abs(len(x[0][0].split()) - len(base.split())))
        return team_hits[0][1]

    # Same player name, closest team token overlap
    candidates = [(k, v) for k, v in index.items() if k[0] == base]
    if len(candidates) == 1:
        return candidates[0][1]
    if candidates:
        def team_score(t: str) -> int:
            ta = set(team_n.split())
            tb = set(t.split())
            return len(ta & tb)

        candidates.sort(key=lambda x: team_score(x[0][1]), reverse=True)
        if team_score(candidates[0][0][1]) > 0:
            return candidates[0][1]
        return None

    # Last name match — require team overlap when multiple hits
    parts = base.split()
    if len(parts) >= 2:
        last = parts[-1]
        last_hits = [(k, v) for k, v in index.items() if k[0].endswith(last) and last in k[0]]
        if len(last_hits) == 1:
            return last_hits[0][1]
        if last_hits:
            def team_score_key(k: tuple[str, str]) -> int:
                return len(set(team_n.split()) & set(k[1].split()))

            last_hits.sort(key=lambda x: team_score_key(x[0]), reverse=True)
            if team_score_key(last_hits[0][0]) > 0:
                return last_hits[0][1]
    return None


UNDERSTAT_ONLY_KEYS = frozenset(
    {
        "npxg90",
        "xg_chain90",
        "xg_buildup90",
        "understat_xg90",
        "understat_xa90",
        "understat_key_passes90",
        "understat_shots90",
    }
)


def merge_understat_into_players(
    players: dict[str, dict[str, Any]],
    *,
    verbose: bool = True,
) -> tuple[int, int]:
    """Attach Understat fields to existing Sofascore player dicts in-place."""
    try:
        index = fetch_understat_blended()
    except Exception as exc:
        if _is_chrome_missing(exc):
            if verbose:
                print("  Understat: skipped (Chrome unavailable)", flush=True)
            return 0, len(players)
        raise
    if not index:
        if verbose:
            print("  Understat: no data returned", flush=True)
        return 0, len(players)

    matched = 0
    for name, data in players.items():
        hit = _lookup_understat(index, name, str(data.get("team", "")))
        if hit is None:
            data["understat_matched"] = False
            continue
        matched += 1
        data["understat_matched"] = True
        for k, v in hit.items():
            if k in UNDERSTAT_ONLY_KEYS:
                data[k] = v
        if data.get("npxg90", 0) > 0 and data.get("xg90", 0) == 0:
            data["xg90"] = data["npxg90"]

    if verbose:
        print(f"  Understat: matched {matched}/{len(players)} cached players", flush=True)
    return matched, len(players)
