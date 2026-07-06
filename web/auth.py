"""Simple name-based login and session tokens for the web lab."""
from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_FILE = ROOT / "data" / "sessions.json"

_lock = threading.Lock()
_sessions: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    """Password must match the display name (case-insensitive). Returns canonical name."""
    canonical = _normalize_name(name)
    if not canonical:
        return None
    if canonical.lower() != password.strip().lower():
        return None
    return canonical


def create_session(user: str) -> str:
    token = secrets.token_urlsafe(24)
    with _lock:
        _sessions[token] = {"user": user, "created_at": _now()}
        _save_sessions()
    return token


def get_user(token: str | None) -> str | None:
    if not token:
        return None
    with _lock:
        row = _sessions.get(token)
    return row["user"] if row else None


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with _lock:
        if token in _sessions:
            del _sessions[token]
            _save_sessions()
