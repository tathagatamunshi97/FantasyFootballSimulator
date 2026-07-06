"""Simple name-based login and session tokens for the web lab."""
from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_FILE = ROOT / "data" / "sessions.json"

ADMIN_USER = "admin"
MAX_TEAM_SESSIONS = 2
SESSION_TTL_HOURS = 24

_lock = threading.Lock()
_sessions: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _expires_at(created_at: str) -> datetime:
    created = _parse_ts(created_at) or datetime.now(timezone.utc)
    return created + timedelta(hours=SESSION_TTL_HOURS)


def _is_expired(row: dict[str, Any]) -> bool:
    exp = row.get("expires_at")
    if exp:
        parsed = _parse_ts(exp)
        if parsed:
            return datetime.now(timezone.utc) >= parsed
    created = _parse_ts(row.get("created_at"))
    if not created:
        return False
    return datetime.now(timezone.utc) >= created + timedelta(hours=SESSION_TTL_HOURS)


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().split())


def _load_sessions() -> None:
    global _sessions
    if SESSIONS_FILE.exists():
        try:
            _sessions = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            _sessions = {}


def _save_sessions() -> None:
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSIONS_FILE.write_text(json.dumps(_sessions, indent=2), encoding="utf-8")


_load_sessions()


def validate_login(name: str, password: str) -> str | None:
    """
    Allowed logins:
    - admin / admin
    - Google Sheet team name as both username and password (case-insensitive)
    """
    canonical = _normalize_name(name)
    if not canonical:
        return None
    pwd = password.strip()
    if not pwd:
        return None

    if canonical.lower() == ADMIN_USER and pwd.lower() == ADMIN_USER:
        return ADMIN_USER

    if canonical.lower() != pwd.lower():
        return None

    from google_sheets_teams import resolve_sheet_team_name

    sheet_name = resolve_sheet_team_name(canonical)
    if sheet_name:
        return sheet_name
    return None


def _prune_expired_locked() -> None:
    """Remove expired sessions; caller must hold _lock."""
    expired = [tok for tok, row in _sessions.items() if _is_expired(row)]
    if not expired:
        return
    for tok in expired:
        del _sessions[tok]
    _save_sessions()


def _active_sessions_for_user(user: str) -> list[str]:
    """Token ids for non-expired sessions belonging to user."""
    with _lock:
        _prune_expired_locked()
        return [tok for tok, row in _sessions.items() if row.get("user") == user]


def session_limit_error(user: str) -> str | None:
    """Return error message if user cannot open another session."""
    if is_admin_user(user):
        return None
    active = _active_sessions_for_user(user)
    if len(active) >= MAX_TEAM_SESSIONS:
        return (
            f"Maximum {MAX_TEAM_SESSIONS} concurrent logins for this team. "
            "Log out on another device or browser, or wait for inactive sessions to expire "
            f"({SESSION_TTL_HOURS}h)."
        )
    return None


def create_session(user: str) -> str:
    limit_err = session_limit_error(user)
    if limit_err:
        raise ValueError(limit_err)

    token = secrets.token_urlsafe(24)
    created = _now()
    expires = _expires_at(created).isoformat()
    with _lock:
        _prune_expired_locked()
        _sessions[token] = {
            "user": user,
            "created_at": created,
            "expires_at": expires,
        }
        _save_sessions()
    return token


def get_user(token: str | None) -> str | None:
    if not token:
        return None
    with _lock:
        row = _sessions.get(token)
        if not row:
            return None
        if _is_expired(row):
            del _sessions[token]
            _save_sessions()
            return None
    return row["user"]


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with _lock:
        if token in _sessions:
            del _sessions[token]
            _save_sessions()


def active_session_count(user: str) -> int:
    return len(_active_sessions_for_user(user))


def is_admin_user(user: str | None) -> bool:
    return user == ADMIN_USER


def is_team_user(user: str | None) -> bool:
    return bool(user) and user != ADMIN_USER


def user_role(user: str | None) -> str | None:
    if not user:
        return None
    return "admin" if is_admin_user(user) else "team"


def can_run_simulations(user: str | None, *, is_admin_token: bool = False) -> bool:
    """Admin session or SIM_ADMIN_TOKEN may create/run experiments."""
    return is_admin_token or is_admin_user(user)
