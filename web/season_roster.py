"""Multi-season project -- per-tournament roster store for Season 2+.

Season 1 (and every legacy tournament) keeps reading team rosters straight
off the live data/teams_sheet.xlsx exactly as before (google_sheets_teams.py
is untouched as a read path for those). Starting with a tournament created
via league_cup.advance_to_next_season, a team's roster instead lives here --
seeded once from its prior-season roster at cutover, then mutated only
through release_player (and, later, auction/transfer wins). This is the seam
that makes rosters actually owned by the app instead of a hand-edited Excel
file for every season after the first.

Same _lock + _load_all/_save_all skeleton as team_lineups.py/team_purse.py,
plus the R2-blob-with-local-fallback durability layer tournament.py's own
match-trace persistence already uses (team_purse.py's plain-local-file
pattern is fine for a value that's cheaply re-derivable from the xlsx on
loss; a team's actual roster assignment is not, so this gets the sturdier
persistence).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ROSTERS_PATH = ROOT / "data" / "season_rosters.json"
_R2_KEY = "season_rosters.json"

_lock = threading.Lock()


def _load_all() -> dict[str, Any]:
    try:
        import r2_storage

        if r2_storage.is_r2_enabled():
            data = r2_storage.load_json_blob(_R2_KEY)
            if isinstance(data, dict):
                return data
    except (ImportError, Exception):
        pass
    if not ROSTERS_PATH.exists():
        return {}
    try:
        return json.loads(ROSTERS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(data: dict[str, Any]) -> None:
    """Never raises -- a save failure here must never fail an unrelated request."""
    try:
        import r2_storage

        if r2_storage.is_r2_enabled():
            r2_storage.save_json_blob(_R2_KEY, data)
    except Exception as exc:
        print(f"season_roster: R2 save failed: {exc}")
    try:
        ROSTERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        ROSTERS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        print(f"season_roster: local JSON save failed: {exc}")


def seed_season_roster(tournament_id: str, team_name: str, players: list[str]) -> None:
    """Freeze this team's starting Season-N+ roster. Only ever called once,
    at advance_to_next_season time -- a second call for the same team would
    silently discard any releases already recorded, so callers must not
    call this after the season has started."""
    with _lock:
        store = _load_all()
        bucket = store.setdefault(tournament_id, {})
        bucket[team_name] = [p for p in players if p and str(p).strip()]
        _save_all(store)


def has_season_roster(tournament_id: str, team_name: str) -> bool:
    """True if this team's roster for this tournament is app-owned (seeded
    via seed_season_roster) rather than falling back to the live xlsx."""
    with _lock:
        store = _load_all()
    return team_name in (store.get(tournament_id) or {})


def get_season_roster(tournament_id: str, team_name: str) -> list[str] | None:
    """None means "not seeded for this tournament" -- callers fall back to
    the xlsx roster, exactly as every tournament did before this module
    existed."""
    with _lock:
        store = _load_all()
    bucket = store.get(tournament_id) or {}
    roster = bucket.get(team_name)
    return list(roster) if roster is not None else None


def release_player(tournament_id: str, team_name: str, player_name: str) -> None:
    """Remove player_name from team_name's Season-N+ roster. Raises
    ValueError if this tournament has no seeded roster for that team, or
    the player isn't on it -- app.py turns that into a 400, same convention
    team_lineups.py's validation already established."""
    with _lock:
        store = _load_all()
        bucket = store.get(tournament_id) or {}
        roster = bucket.get(team_name)
        if roster is None:
            raise ValueError(f"{team_name} has no season roster for tournament {tournament_id}.")
        if player_name not in roster:
            raise ValueError(f"{player_name} is not on {team_name}'s roster.")
        roster.remove(player_name)
        bucket[team_name] = roster
        store[tournament_id] = bucket
        _save_all(store)


def list_season_teams(tournament_id: str) -> list[str]:
    """Every team with a seeded roster in this tournament (i.e. every
    continuing team from the season-advance action -- new teams are
    deliberately never seeded, see advance_to_next_season)."""
    with _lock:
        store = _load_all()
    return sorted((store.get(tournament_id) or {}).keys())
