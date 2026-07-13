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
# Shared team accounts: allow a few devices; over-cap logins drop the oldest
# session instead of returning 429 (two people on the same credentials).
MAX_TEAM_SESSIONS = 3
SESSION_TTL_HOURS = 24
MIN_PASSWORD_LEN = 6
_PBKDF2_ITERATIONS = 260_000

_lock = threading.Lock()
_sessions: dict[str, dict[str, Any]] = {}
_passwords: dict[str, dict[str, Any]] = {}
_passwords_mtime: float | None = None
_sessions_mtime: float | None = None


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
    global _sessions, _sessions_mtime
    if SESSIONS_FILE.exists():
        try:
            _sessions = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
            _sessions_mtime = SESSIONS_FILE.stat().st_mtime
        except (json.JSONDecodeError, OSError):
            _sessions = {}
            _sessions_mtime = None
    else:
        _sessions = {}
        _sessions_mtime = None


def _maybe_reload_sessions() -> None:
    """Pick up external edits to sessions.json without a process restart."""
    global _sessions, _sessions_mtime
    try:
        if not SESSIONS_FILE.exists():
            if _sessions:
                _sessions = {}
                _sessions_mtime = None
            return
        mtime = SESSIONS_FILE.stat().st_mtime
        if _sessions_mtime is not None and mtime <= _sessions_mtime:
            return
        _sessions = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
        _sessions_mtime = mtime
    except (json.JSONDecodeError, OSError):
        return


def _save_sessions() -> None:
    global _sessions_mtime
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSIONS_FILE.write_text(json.dumps(_sessions, indent=2), encoding="utf-8")
    try:
        _sessions_mtime = SESSIONS_FILE.stat().st_mtime
    except OSError:
        _sessions_mtime = None


_R2_PASSWORDS_KEY = "auth/team_passwords.json"


def _load_passwords() -> None:
    global _passwords, _passwords_mtime

    # R2 is the durable source on Render; local JSON is dev fallback + backup.
    try:
        import r2_storage
        if r2_storage.is_r2_enabled():
            data = r2_storage.load_json_blob(_R2_PASSWORDS_KEY)
            if data is not None:
                _passwords = data
                _passwords_mtime = None
                return
    except (ImportError, Exception):
        pass

    if PASSWORDS_FILE.exists():
        try:
            _passwords = json.loads(PASSWORDS_FILE.read_text(encoding="utf-8"))
            _passwords_mtime = PASSWORDS_FILE.stat().st_mtime
        except (json.JSONDecodeError, OSError):
            _passwords = {}
            _passwords_mtime = None
    else:
        _passwords = {}
        _passwords_mtime = None


def _maybe_reload_passwords() -> None:
    """Pick up external edits to team_passwords.json without a process restart.

    Local-file-mtime based, so it's only meaningful when R2 isn't the source of
    truth — otherwise it would clobber the R2-loaded state with a stale local
    copy the first time it runs (mtime tracking starts at None for R2 loads).
    """
    global _passwords, _passwords_mtime
    try:
        import r2_storage
        if r2_storage.is_r2_enabled():
            return
    except (ImportError, Exception):
        pass
    try:
        if not PASSWORDS_FILE.exists():
            if _passwords:
                _passwords = {}
                _passwords_mtime = None
            return
        mtime = PASSWORDS_FILE.stat().st_mtime
        if _passwords_mtime is not None and mtime <= _passwords_mtime:
            return
        _passwords = json.loads(PASSWORDS_FILE.read_text(encoding="utf-8"))
        _passwords_mtime = mtime
    except (json.JSONDecodeError, OSError):
        return


def _save_passwords() -> None:
    global _passwords_mtime

    try:
        import r2_storage
        if r2_storage.is_r2_enabled():
            r2_storage.save_json_blob(_R2_PASSWORDS_KEY, _passwords)
    except (ImportError, Exception):
        pass

    PASSWORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PASSWORDS_FILE.write_text(json.dumps(_passwords, indent=2), encoding="utf-8")
    try:
        _passwords_mtime = PASSWORDS_FILE.stat().st_mtime
    except OSError:
        _passwords_mtime = None


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
        _maybe_reload_passwords()
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
        _maybe_reload_passwords()
        if team in _passwords:
            raise ValueError("Password already set. Contact admin to reset.")
        _passwords[team] = _hash_password(pwd)
        _save_passwords()


def reset_team_password(team: str) -> bool:
    """Clear stored password so the team must set a new one on next login."""
    with _lock:
        _maybe_reload_passwords()
        if team not in _passwords:
            return False
        del _passwords[team]
        _save_passwords()
        return True


def force_set_team_password(team: str, new_password: str) -> None:
    """Admin/ops: set or replace a team password hash (does not create a session)."""
    pwd = new_password.strip()
    if len(pwd) < MIN_PASSWORD_LEN:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    with _lock:
        _maybe_reload_passwords()
        _passwords[team] = _hash_password(pwd)
        _save_passwords()


def list_team_password_status() -> list[dict[str, Any]]:
    """All sheet teams with whether a password has been configured."""
    from google_sheets_teams import list_sheet_teams

    teams = list_sheet_teams()
    with _lock:
        _maybe_reload_passwords()
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
        _maybe_reload_passwords()
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
        _maybe_reload_sessions()
        _prune_expired_locked()
        return [tok for tok, row in _sessions.items() if row.get("user") == user]


def session_limit_error(user: str) -> str | None:
    """Deprecated: logins no longer hard-reject at the per-team cap.

    Kept for API compatibility; always returns None. New logins succeed and
    ``create_session`` evicts the oldest session(s) when over ``MAX_TEAM_SESSIONS``.
    """
    return None


def _session_created_sort_key(row: dict[str, Any]) -> datetime:
    return _parse_ts(row.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)


def create_session(user: str) -> str:
    """Create a session. For team users, evict oldest sessions when at/over cap."""
    token = secrets.token_urlsafe(24)
    created = _now()
    expires = _expires_at(created).isoformat()
    with _lock:
        _maybe_reload_sessions()
        _prune_expired_locked()
        if not is_admin_user(user):
            owned = [(tok, row) for tok, row in _sessions.items() if row.get("user") == user]
            owned.sort(key=lambda item: _session_created_sort_key(item[1]))
            # Leave room for this login: at most MAX_TEAM_SESSIONS active after insert.
            while len(owned) >= MAX_TEAM_SESSIONS:
                old_tok, _ = owned.pop(0)
                del _sessions[old_tok]
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
        _maybe_reload_sessions()
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
        _maybe_reload_sessions()
        if token in _sessions:
            del _sessions[token]
            _save_sessions()


def clear_all_sessions() -> int:
    """Revoke every active session token. Returns count cleared."""
    with _lock:
        _maybe_reload_sessions()
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
