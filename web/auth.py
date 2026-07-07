"""Simple name-based login and session tokens for the web lab."""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from web.state import get_admin_token

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_FILE = ROOT / "data" / "sessions.json"
PASSWORDS_FILE = ROOT / "data" / "team_passwords.json"

ADMIN_USER = "admin"
MAX_TEAM_SESSIONS = 2
SESSION_TTL_HOURS = 24
MIN_PASSWORD_LEN = 6
_PBKDF2_ITERATIONS = 260_000

_lock = threading.Lock()
_sessions: dict[str, dict[str, Any]] = {}
_passwords: dict[str, dict[str, Any]] = {}


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


def _load_passwords() -> None:
    global _passwords
    if PASSWORDS_FILE.exists():
        try:
            _passwords = json.loads(PASSWORDS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            _passwords = {}


def _save_passwords() -> None:
    PASSWORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PASSWORDS_FILE.write_text(json.dumps(_passwords, indent=2), encoding="utf-8")


_load_sessions()
_load_passwords()


def _hash_password(password: str, *, salt: bytes | None = None) -> dict[str, Any]:
    if salt is None:
        salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
    )
    return {
        "hash": digest.hex(),
        "salt": salt.hex(),
        "iterations": _PBKDF2_ITERATIONS,
    }


def _verify_password(password: str, stored: dict[str, Any]) -> bool:
    try:
        salt = bytes.fromhex(stored["salt"])
        iterations = int(stored.get("iterations") or _PBKDF2_ITERATIONS)
    except (KeyError, TypeError, ValueError):
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return secrets.compare_digest(digest.hex(), stored.get("hash", ""))


def resolve_sheet_team(name: str) -> str | None:
    """Return canonical Google Sheet team name, or None if not on sheet."""
    canonical = _normalize_name(name)
    if not canonical:
        return None
    from google_sheets_teams import resolve_sheet_team_name

    return resolve_sheet_team_name(canonical)


def team_has_password(team: str) -> bool:
    with _lock:
        return team in _passwords


def set_team_password(team: str, new_password: str, confirm_password: str) -> None:
    """First-time password setup for a sheet team (no existing password)."""
    pwd = new_password.strip()
    confirm = confirm_password.strip()
    if len(pwd) < MIN_PASSWORD_LEN:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    if pwd != confirm:
        raise ValueError("Passwords do not match.")
    with _lock:
        if team in _passwords:
            raise ValueError("Password already set. Contact admin to reset.")
        _passwords[team] = _hash_password(pwd)
        _save_passwords()


def reset_team_password(team: str) -> bool:
    """Clear stored password so the team must set a new one on next login."""
    with _lock:
        if team not in _passwords:
            return False
        del _passwords[team]
        _save_passwords()
        return True


def list_team_password_status() -> list[dict[str, Any]]:
    """All sheet teams with whether a password has been configured."""
    from google_sheets_teams import list_sheet_teams

    teams = list_sheet_teams()
    with _lock:
        configured = set(_passwords.keys())
    return [
        {
            "name": t["name"],
            "has_password": t["name"] in configured,
            "ready": t.get("ready", False),
            "player_count": t.get("player_count", 0),
        }
        for t in teams
    ]


def attempt_login(name: str, password: str) -> dict[str, Any]:
    """
    Login attempt result:
    - status ok: authenticated user string in ``user``
    - status needs_password_setup: valid sheet team without password yet
    - status invalid: bad credentials or unknown team
    """
    canonical = _normalize_name(name)
    if not canonical:
        return {"status": "invalid"}

    pwd = password.strip()
    if not pwd:
        return {"status": "invalid"}

    if canonical.lower() == ADMIN_USER:
        expected = get_admin_token()
        if expected and secrets.compare_digest(pwd, expected):
            return {"status": "ok", "user": ADMIN_USER}
        return {"status": "invalid"}

    sheet_name = resolve_sheet_team(canonical)
    if not sheet_name:
        return {"status": "invalid"}

    if not team_has_password(sheet_name):
        return {"status": "needs_password_setup", "user": sheet_name}

    with _lock:
        stored = _passwords.get(sheet_name)
    if stored and _verify_password(pwd, stored):
        return {"status": "ok", "user": sheet_name}
    return {"status": "invalid"}


def validate_login(name: str, password: str) -> str | None:
    """Return authenticated username, or None."""
    result = attempt_login(name, password)
    if result["status"] == "ok":
        return result["user"]
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


def clear_all_sessions() -> int:
    """Revoke every active session token. Returns count cleared."""
    with _lock:
        count = len(_sessions)
        _sessions.clear()
        _save_sessions()
    return count


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
