"""Load fantasy team rosters from the season's static Excel workbook.

Was a live Google Sheets CSV export; moved to a static .xlsx (season 2,
auction-format league) because converting the source sheet to Google
Sheets risks mangling its formulas. The workbook lives at
data/teams_sheet.xlsx -- replace that file when the roster changes, no
code changes needed. Cache invalidates on the file's mtime, so a
replacement is picked up on the very next request, not after a delay.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from formation_fit import DEFAULT_FORMATION, FORMATION_SLOTS, normalize_formation
from lineup_builder import assign_lineup_slots, lineup_from_assignments, select_starting_xi
from player_names import canonical_name, names_loosely_match, normalize_key, resolve_player_name

# The season's roster workbook. TEAMS_XLSX_PATH env var overrides for testing.
DEFAULT_TEAMS_XLSX_PATH = Path(__file__).resolve().parent / "data" / "teams_sheet.xlsx"
DEFAULT_TEAMS_SHEET_NAME = "TeamSheet"

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

# TeamSheet layout: team display name on row 0, a "PlayerName"/"Amount"
# header pair on row 1 marking each team's two-column block (with a blank
# spacer column between blocks), players from row 2 down until the first
# blank cell. Below the player rows, column 0 carries a few summary-row
# labels (TOTAL SPENT / BUDGET LEFT / Players Bought / MAX BID for a
# player) whose values sit in each team's own Amount column at that same
# row -- found by label text, not a fixed row offset, same philosophy as
# _PLAYER_HEADER_TEXT below, so an extra/removed summary row doesn't need
# a code change.
_TEAM_NAME_ROW = 0
_HEADER_ROW = 1
_PLAYER_START_ROW = 2
_PLAYER_HEADER_TEXT = "playername"
_BUDGET_LEFT_LABEL = "budget left"


@dataclass(frozen=True)
class SheetRoster:
    name: str
    players: list[str]
    budgets: list[float | None]
    budget_left: float | None = None

    @property
    def player_count(self) -> int:
        return len(self.players)


def teams_source_path() -> Path:
    override = os.environ.get("TEAMS_XLSX_PATH", "").strip()
    return Path(override) if override else DEFAULT_TEAMS_XLSX_PATH


def spreadsheet_config() -> tuple[str, str]:
    """(workbook path, sheet tab name) -- kept as a 2-tuple for callers built
    around the old (spreadsheet_id, gid) shape; the values just mean
    something different now."""
    return str(teams_source_path()), DEFAULT_TEAMS_SHEET_NAME


def sheet_csv_url(spreadsheet_id: str | None = None, gid: str | None = None) -> str | None:
    """No CSV export URL for a local workbook -- kept for import compatibility."""
    return None


# Cache invalidates on the workbook's mtime rather than a TTL: a burst of
# calls in one request (loading both teams for a match) only reads the file
# once, but replacing data/teams_sheet.xlsx is picked up on the very next
# call instead of waiting out a fixed window.
_sheet_cache: dict[str, tuple[float, pd.DataFrame]] = {}


def fetch_teams_dataframe(
    spreadsheet_id: str | None = None,
    gid: str | None = None,
) -> pd.DataFrame:
    """Read the TeamSheet tab of the season's static workbook.

    spreadsheet_id/gid are accepted (and ignored) only so old call sites
    built for the Google Sheets days don't need touching.
    """
    path = teams_source_path()
    if not path.exists():
        raise RuntimeError(
            f"Teams workbook not found at {path}. Copy the season's .xlsx there "
            "(or set TEAMS_XLSX_PATH)."
        )
    mtime = path.stat().st_mtime
    cache_key = str(path)
    hit = _sheet_cache.get(cache_key)
    if hit is not None and hit[0] == mtime:
        return hit[1]

    try:
        df = pd.read_excel(path, sheet_name=DEFAULT_TEAMS_SHEET_NAME, header=None, engine="calamine")
    except Exception as exc:
        raise RuntimeError(f"Could not read '{DEFAULT_TEAMS_SHEET_NAME}' tab from {path}: {exc}") from exc
    _sheet_cache[cache_key] = (mtime, df)
    return df


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


def _find_label_row(df: pd.DataFrame, label: str, *, col: int = 0) -> int | None:
    """Row index of the first cell in `col` whose text matches `label`
    case-insensitively, or None if not found."""
    for row in range(df.shape[0]):
        if _cell_str(df, row, col).strip().lower() == label:
            return row
    return None


def parse_teams_from_dataframe(df: pd.DataFrame) -> dict[str, SheetRoster]:
    """Parse team blocks: each team owns a (PlayerName, Amount) column pair,
    detected by the "PlayerName" header on row 1 rather than a fixed column
    stride, so an extra/removed team or a wider spacer column doesn't need a
    code change. Team display name sits directly above its header, on row 0.
    """
    teams: dict[str, SheetRoster] = {}
    budget_left_row = _find_label_row(df, _BUDGET_LEFT_LABEL)
    for col in range(df.shape[1]):
        header = _cell_str(df, _HEADER_ROW, col)
        if header.strip().lower() != _PLAYER_HEADER_TEXT:
            continue
        name = _cell_str(df, _TEAM_NAME_ROW, col)
        if not name:
            continue
        amount_col = col + 1
        players: list[str] = []
        budgets: list[float | None] = []
        for row in range(_PLAYER_START_ROW, df.shape[0]):
            player = _cell_str(df, row, col)
            if not player:
                break
            players.append(player)
            budgets.append(_parse_budget(_cell_str(df, row, amount_col)))
        if not players:
            continue
        budget_left = (
            _parse_budget(_cell_str(df, budget_left_row, amount_col))
            if budget_left_row is not None
            else None
        )
        key = _canonical_team_key(name)
        teams[key] = SheetRoster(name=name, players=players, budgets=budgets, budget_left=budget_left)
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

    # No cap here -- the old 15-player sheet made [:15] a no-op safety net,
    # but this season's rosters are 18 players and a hardcoded 15 would
    # silently drop the last 3 off every squad.
    raw_squad = roster.players
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
            "source": "excel_workbook",
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


def get_team_budget_left(team_name: str) -> float | None:
    """This team's 'BUDGET LEFT' value from the roster workbook (purse
    system's starting purse), or None if the team/value isn't found."""
    try:
        df = fetch_teams_dataframe()
        rosters = parse_teams_from_dataframe(df)
    except Exception:
        return None
    roster = _find_roster(team_name, rosters)
    return roster.budget_left if roster else None


def is_sheet_team_payload(team: dict[str, Any]) -> bool:
    """True if team dict came from (or matches) the workbook roster."""
    meta = team.get("sheet_meta") or {}
    if meta.get("source") == "excel_workbook":
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
