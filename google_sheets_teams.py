"""Load fantasy team rosters from a shared Google Sheet (CSV export)."""
from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from formation_fit import DEFAULT_FORMATION, FORMATION_SLOTS, normalize_formation
from lineup_builder import assign_lineup_slots, lineup_from_assignments, select_starting_xi
from player_names import canonical_name, names_loosely_match, normalize_key, resolve_player_name

# Default: user's teams sheet tab
DEFAULT_SPREADSHEET_ID = "1bjdf22AWQfPam1Aakiz4STgt7Gal0I4hCkY11GSroDg"
DEFAULT_TEAMS_GID = "2011460593"

# Round 3 season picks live on a separate sheet tab; keyed by normalized team name.
ROUND3_SEASON_PICKS: dict[str, dict[str, str]] = {
    "subhadro+shubhajit": {"player": "Edinson Cavani", "season": "16/17"},
    "sohom+mayukh": {"player": "Dani Alves", "season": "17/18"},
    "dilshad": {"player": "Marcelo", "season": "16/17"},
    "kp+ss": {"player": "Giovanni Lo Celso", "season": "18/19"},
    "anindo": {"player": "Gonzalo Higuain", "season": "15/16"},
    "kinjal+sayan c": {"player": "Diego Godin", "season": "15/16"},
    "rishav": {"player": "Luis Suarez", "season": "15/16"},
    "ddr": {"player": "Arturo Vidal", "season": "15/16"},
    "moga+sanmitro": {"player": "Angel Di Maria", "season": "13/14"},
    "chintu": {"player": "Fernandinho", "season": "17/18"},
    "rohan + anac": {"player": "Roberto Firmino", "season": "17/18"},
    "ryan": {"player": "Neymar", "season": "14/15"},
    "raktim": {"player": "Alexis Sanchez", "season": "16/17"},
    "sugata": {"player": "Radamel Falcao", "season": "16/17"},
}

# Alternate spellings from sheet / login -> canonical normalized team key in ROUND3_SEASON_PICKS.
TEAM_NAME_ALIASES: dict[str, str] = {
    "subhadro+subhajit": "subhadro+shubhajit",
    "subhadro+shubhajit": "subhadro+shubhajit",
    "rohan+anac": "rohan + anac",
    "rohan + anac": "rohan + anac",
}

_TEAM_NAME_ROW = 1
_PLAYER_START_ROW = 2


@dataclass(frozen=True)
class SheetRoster:
    name: str
    players: list[str]
    budgets: list[float | None]

    @property
    def player_count(self) -> int:
        return len(self.players)


def spreadsheet_config() -> tuple[str, str]:
    sheet_id = os.environ.get("GOOGLE_SHEETS_ID", DEFAULT_SPREADSHEET_ID).strip()
    gid = os.environ.get("GOOGLE_SHEETS_TEAMS_GID", DEFAULT_TEAMS_GID).strip()
    return sheet_id, gid


def sheet_csv_url(spreadsheet_id: str | None = None, gid: str | None = None) -> str:
    sid, g = spreadsheet_config()
    sheet_id = spreadsheet_id or sid
    tab_gid = gid or g
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={tab_gid}"


def fetch_teams_dataframe(
    spreadsheet_id: str | None = None,
    gid: str | None = None,
) -> pd.DataFrame:
    """Download the teams tab as a CSV (sheet must be link-accessible)."""
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    url = sheet_csv_url(spreadsheet_id, gid)
    req = Request(url, headers={"User-Agent": "fantasy-football-simulator/1.0"})
    try:
        with urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8-sig")
    except HTTPError as exc:
        raise RuntimeError(f"Google Sheet HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Google Sheet: {exc.reason}") from exc
    if text.lstrip().startswith("<!DOCTYPE") or text.lstrip().startswith("<html"):
        raise RuntimeError(
            "Google Sheet returned HTML instead of CSV. Share the sheet as "
            "'Anyone with the link can view' or publish the tab."
        )
    return pd.read_csv(io.StringIO(text), header=None)


def _cell_str(df: pd.DataFrame, row: int, col: int) -> str:
    if row >= df.shape[0] or col >= df.shape[1]:
        return ""
    value = df.iloc[row, col]
    if pd.isna(value):
        return ""
    return str(value).strip()


def _parse_budget(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_teams_from_dataframe(df: pd.DataFrame) -> dict[str, SheetRoster]:
    """Parse team columns: name on row 2, players below, optional budget in next column."""
    teams: dict[str, SheetRoster] = {}
    for col in range(df.shape[1]):
        name = _cell_str(df, _TEAM_NAME_ROW, col)
        if not name:
            continue
        players: list[str] = []
        budgets: list[float | None] = []
        for row in range(_PLAYER_START_ROW, df.shape[0]):
            player = _cell_str(df, row, col)
            if not player:
                break
            players.append(player)
            budget = _parse_budget(_cell_str(df, row, col + 1))
            budgets.append(budget)
        if not players:
            continue
        key = _canonical_team_key(name)
        teams[key] = SheetRoster(name=name, players=players, budgets=budgets)
    return teams


def list_sheet_teams(
    spreadsheet_id: str | None = None,
    gid: str | None = None,
) -> list[dict[str, Any]]:
    df = fetch_teams_dataframe(spreadsheet_id, gid)
    rosters = parse_teams_from_dataframe(df)
    out = [
        {
            "name": r.name,
            "player_count": r.player_count,
            "players": r.players,
            "ready": r.player_count >= 11,
        }
        for r in sorted(rosters.values(), key=lambda x: x.name.lower())
    ]
    return out


def _canonical_team_key(team_name: str) -> str:
    key = normalize_key(team_name)
    return TEAM_NAME_ALIASES.get(key, key)


def _find_roster(team_name: str, rosters: dict[str, SheetRoster]) -> SheetRoster | None:
    key = _canonical_team_key(team_name)
    if key in rosters:
        return rosters[key]
    loose = re.sub(r"[^a-z0-9]+", "", key)
    for roster in rosters.values():
        roster_key = _canonical_team_key(roster.name)
        if roster_key == key or normalize_key(roster.name) == key:
            return roster
        if re.sub(r"[^a-z0-9]+", "", roster_key) == loose:
            return roster
    return None


def default_peak_season(roster: SheetRoster) -> dict[str, str]:
    """Round 3 season-pick default when the picked player is on the roster."""
    pick = ROUND3_SEASON_PICKS.get(_canonical_team_key(roster.name))
    if not pick:
        return {"player": "", "season": ""}

    player_raw = pick["player"]
    season = pick["season"]
    for player in roster.players:
        if names_loosely_match(player, player_raw) or names_loosely_match(player, canonical_name(player_raw)):
            return {"player": player, "season": season}
    return {"player": player_raw, "season": season}


def team_payload_from_roster(
    roster: SheetRoster,
    *,
    formation: str = DEFAULT_FORMATION,
    store: Any,
    resolve_names: bool = True,
) -> dict[str, Any]:
    """
    Build a lab experiment team dict from a sheet roster.
    Auto-assigns slots when exactly 11 players; otherwise maps in formation order.
    """
    formation = normalize_formation(formation)
    if formation not in FORMATION_SLOTS:
        formation = DEFAULT_FORMATION

    raw_squad = roster.players[:15]
    full_resolved: list[str] = []
    for raw in raw_squad:
        if resolve_names and store is not None:
            cached = store._find_cached_player_name(raw)
            full_resolved.append(cached if cached else resolve_player_name(raw, store))
        else:
            full_resolved.append(raw)

    starting_pool = full_resolved
    if len(full_resolved) > 11 and store is not None:
        try:
            squad_stats = store.cached_stats_map(full_resolved)
            starting_pool = select_starting_xi(formation, full_resolved, squad_stats)
        except (KeyError, ValueError):
            starting_pool = full_resolved[:11]
    elif len(full_resolved) > 11:
        starting_pool = full_resolved[:11]

    bench_players = [p for p in full_resolved if p not in set(starting_pool)]

    lineup: list[dict[str, Any]] = []

    if starting_pool and store is not None:
        try:
            stats = store.cached_stats_map(starting_pool)
            pairs = assign_lineup_slots(formation, starting_pool, stats)
            lineup = lineup_from_assignments(formation, pairs)
        except (KeyError, ValueError):
            lineup = []
    if not lineup:
        slots = [s["slot"] for s in FORMATION_SLOTS[formation]]
        for i, slot in enumerate(slots):
            player = starting_pool[i] if i < len(starting_pool) else ""
            lineup.append(
                {"slot": slot, "player": player, "captain": False, "vice_captain": False}
            )

    peak_season = default_peak_season(roster)

    return {
        "name": roster.name,
        "formation": formation,
        "lineup": lineup,
        "bench": bench_players,
        "prime_player": "",
        "peak_season": peak_season,
        "sheet_meta": {
            "source": "google_sheets",
            "player_count": roster.player_count,
            "budgets": roster.budgets,
            "ready": roster.player_count >= 11,
            "full_roster": full_resolved,
            "roster_players": starting_pool,
            "bench_players": bench_players,
            "squad_size": len(full_resolved),
            "season_pick": dict(peak_season) if peak_season.get("player") else None,
        },
    }


def load_team_by_name(
    team_name: str,
    *,
    formation: str = DEFAULT_FORMATION,
    store: Any = None,
    spreadsheet_id: str | None = None,
    gid: str | None = None,
) -> dict[str, Any]:
    df = fetch_teams_dataframe(spreadsheet_id, gid)
    rosters = parse_teams_from_dataframe(df)
    roster = _find_roster(team_name, rosters)
    if roster is None:
        known = ", ".join(r.name for r in sorted(rosters.values(), key=lambda x: x.name.lower()))
        raise KeyError(f"Team '{team_name}' not found on sheet. Known teams: {known}")
    return team_payload_from_roster(roster, formation=formation, store=store)


def resolve_sheet_team_name(team_name: str) -> str | None:
    """Return canonical sheet team name if it exists, else None."""
    try:
        df = fetch_teams_dataframe()
        rosters = parse_teams_from_dataframe(df)
    except Exception:
        return None
    roster = _find_roster(team_name, rosters)
    return roster.name if roster else None


def is_sheet_team_payload(team: dict[str, Any]) -> bool:
    """True if team dict came from (or matches) the Google Sheet roster."""
    meta = team.get("sheet_meta") or {}
    if meta.get("source") == "google_sheets":
        return True
    name = (team.get("name") or "").strip()
    if name and resolve_sheet_team_name(name):
        return True
    return False


def load_matchup_by_names(
    team_a_name: str,
    team_b_name: str,
    *,
    formation_a: str = DEFAULT_FORMATION,
    formation_b: str = DEFAULT_FORMATION,
    store: Any = None,
    spreadsheet_id: str | None = None,
    gid: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    df = fetch_teams_dataframe(spreadsheet_id, gid)
    rosters = parse_teams_from_dataframe(df)
    a = _find_roster(team_a_name, rosters)
    b = _find_roster(team_b_name, rosters)
    if a is None:
        raise KeyError(f"Team A '{team_a_name}' not found on sheet.")
    if b is None:
        raise KeyError(f"Team B '{team_b_name}' not found on sheet.")
    return (
        team_payload_from_roster(a, formation=formation_a, store=store),
        team_payload_from_roster(b, formation=formation_b, store=store),
    )
