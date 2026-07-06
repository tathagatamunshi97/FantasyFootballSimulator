"""Load fantasy matchups from Excel workbooks."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from sofascore_client import StatsStore
from formation_fit import supported_formations
from lineup_builder import build_fantasy_team
from models import FantasyTeam
from player_names import normalize_key, resolve_player_name

FORMATION_RE = re.compile(r"^\d-\d-\d(?:-\d)?$")
LABEL_ROWS = {"formation", "captain", "vice captain", "vice-captain", "vc"}


def _cell_str(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _is_formation(value: str) -> bool:
    return bool(FORMATION_RE.match(value.replace(" ", "")))


def _normalize_formation(value: str) -> str:
    text = value.replace(" ", "").strip()
    if text in supported_formations():
        return text
    # Allow 433 -> 4-3-3
    if len(text) == 3 and text.isdigit():
        return f"{text[0]}-{text[1]}-{text[2]}"
    if len(text) == 4 and text.isdigit():
        return f"{text[0]}-{text[1]}-{text[2]}-{text[3]}"
    raise ValueError(f"Unsupported formation '{value}'. Use e.g. 4-3-3, 4-2-3-1")


def _parse_team_column(
    df: pd.DataFrame,
    col: int,
    team_name: str,
    store: StatsStore,
) -> FantasyTeam:
    """Parse one team column from the sheet grid."""
    formation = "4-4-2"
    captain: str | None = None
    vice: str | None = None
    players_raw: list[str] = []

    for row_idx in range(df.shape[0]):
        label = _cell_str(df.iloc[row_idx, 0]).lower() if df.shape[1] > 1 else ""
        value = _cell_str(df.iloc[row_idx, col])

        if not value:
            continue

        if label in LABEL_ROWS or _cell_str(df.iloc[row_idx, 0]).lower() in LABEL_ROWS:
            if "formation" in label or _cell_str(df.iloc[row_idx, 0]).lower() == "formation":
                formation = _normalize_formation(value)
            elif "captain" in label and "vice" not in label:
                captain = resolve_player_name(value, store)
            elif "vice" in label:
                vice = resolve_player_name(value, store)
            continue

        if _is_formation(value) and row_idx <= 2 and not players_raw:
            formation = _normalize_formation(value)
            continue

        if value.lower() in {"team a", "team b"} or value == team_name:
            continue

        players_raw.append(value)

    if len(players_raw) < 11:
        raise ValueError(
            f"Team '{team_name}' needs 11 players in column {col + 1}, found {len(players_raw)}"
        )
    if len(players_raw) > 11:
        players_raw = players_raw[:11]

    resolved = [resolve_player_name(p, store) for p in players_raw]
    stats = store.require(resolved)

    if captain and captain not in resolved:
        captain = None
    if vice and vice not in resolved:
        vice = None

    return build_fantasy_team(
        team_name,
        formation,
        resolved,
        stats,
        captain=captain,
        vice_captain=vice,
    )


def load_matchup_from_excel(
    path: Path | str,
    store: StatsStore,
    *,
    sheet: str | int = 0,
    home_col: int | None = None,
    away_col: int | None = None,
) -> tuple[FantasyTeam, FantasyTeam]:
    """
    Load a two-team matchup from Excel.

    Supported layout (matches Team A | Team B grid):

        |          | Team A   | Team B   |
        | Formation| 4-3-3    | 4-2-3-1  |
        | Captain  | Mbappé   | Bruno F. |  (optional)
        |          | Player 1 | Player 1 |
        |          | ...      | ...      |  (11 players)

    Row labels in column A (Formation, Captain) are optional.
    """
    path = Path(path)
    df = pd.read_excel(path, sheet_name=sheet, header=None)

    if df.empty or df.shape[1] < 2:
        raise ValueError("Excel sheet must have at least two team columns")

    # Detect team name + column indices from first row
    if home_col is None or away_col is None:
        header_row = 0
        candidates: list[tuple[int, str]] = []
        for col in range(df.shape[1]):
            val = _cell_str(df.iloc[header_row, col])
            if val and normalize_key(val) not in LABEL_ROWS:
                candidates.append((col, val))
        if len(candidates) < 2:
            # No header row — use columns 0 and 1
            home_col, away_col = 0, 1
            home_name, away_name = "Team A", "Team B"
            data_start_row = 0
        else:
            home_col, home_name = candidates[0]
            away_col, away_name = candidates[1]
            data_start_row = 1
            df = df.iloc[data_start_row:].reset_index(drop=True)
    else:
        home_name = _cell_str(df.iloc[0, home_col]) or "Team A"
        away_name = _cell_str(df.iloc[0, away_col]) or "Team B"
        df = df.iloc[1:].reset_index(drop=True)

    home = _parse_team_column(df, home_col, home_name, store)
    away = _parse_team_column(df, away_col, away_name, store)
    return home, away


def write_excel_template(path: Path | str, home: dict[str, Any], away: dict[str, Any]) -> None:
    """Write a reusable Excel template for H2H input."""
    rows = [
        ["", home.get("name", "Team A"), away.get("name", "Team B")],
        ["Formation", home.get("formation", "4-3-3"), away.get("formation", "4-2-3-1")],
        ["Captain", home.get("captain", ""), away.get("captain", "")],
        ["Vice Captain", home.get("vice_captain", ""), away.get("vice_captain", "")],
    ]
    home_players = home.get("players", [])
    away_players = away.get("players", [])
    for i in range(max(len(home_players), len(away_players), 11)):
        h = home_players[i] if i < len(home_players) else ""
        a = away_players[i] if i < len(away_players) else ""
        rows.append(["", h, a])

    out = pd.DataFrame(rows)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_excel(path, index=False, header=False, sheet_name="Matchup")
