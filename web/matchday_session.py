"""Active tournament fixture broadcast session (setup → running → result)."""
from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any

_lock = threading.Lock()
_session: dict[str, Any] | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_session() -> dict[str, Any] | None:
    with _lock:
        return copy.deepcopy(_session) if _session else None


def is_active() -> bool:
    with _lock:
        return _session is not None


def should_redirect() -> bool:
    """Clients should redirect to /matchday while session is in setup or running."""
    with _lock:
        if not _session:
            return False
        return _session.get("phase") in ("setup", "running")


def _public_session() -> dict[str, Any] | None:
    s = get_session()
    if not s:
        return None
    return {
        "active": True,
        "phase": s.get("phase"),
        "fixture_id": s.get("fixture_id"),
        "tournament_id": s.get("tournament_id"),
        "tournament_name": s.get("tournament_name"),
        "stage": s.get("stage"),
        "home": s.get("home"),
        "away": s.get("away"),
        "team_a": s.get("team_a"),
        "team_b": s.get("team_b"),
        "experiment_id": s.get("experiment_id"),
        "running": s.get("running", False),
        "message": s.get("message"),
        "result": s.get("result"),
        "started_at": s.get("started_at"),
        "updated_at": s.get("updated_at"),
    }


def active_status() -> dict[str, Any]:
    s = _public_session()
    if not s:
        return {"active": False, "redirect": False, "session": None}
    return {"active": True, "redirect": should_redirect(), "session": s}


def start_session(
    *,
    tournament_id: str,
    tournament_name: str,
    fixture_id: str,
    stage: str,
    home: str,
    away: str,
    team_a: dict[str, Any],
    team_b: dict[str, Any],
) -> dict[str, Any]:
    global _session
    with _lock:
        if _session and _session.get("phase") in ("setup", "running"):
            raise ValueError(
                f"Matchday session already active for {_session.get('home')} vs {_session.get('away')}. "
                "Wait for it to finish or clear it first."
            )
        _session = {
            "tournament_id": tournament_id,
            "tournament_name": tournament_name,
            "fixture_id": fixture_id,
            "stage": stage,
            "home": home,
            "away": away,
            "team_a": copy.deepcopy(team_a),
            "team_b": copy.deepcopy(team_b),
            "phase": "setup",
            "running": False,
            "experiment_id": None,
            "message": "Teams can review lineups. Admin: start simulation when ready.",
            "result": None,
            "started_at": _now(),
            "updated_at": _now(),
        }
    return active_status()


def set_running(experiment_id: str, message: str = "Running simulation…") -> None:
    global _session
    with _lock:
        if not _session:
            raise ValueError("No active matchday session.")
        _session["phase"] = "running"
        _session["running"] = True
        _session["experiment_id"] = experiment_id
        _session["message"] = message
        _session["updated_at"] = _now()


def update_message(message: str) -> None:
    global _session
    with _lock:
        if _session:
            _session["message"] = message
            _session["updated_at"] = _now()


def set_result(result: dict[str, Any], *, experiment_id: str | None = None) -> None:
    global _session
    with _lock:
        if not _session:
            return
        _session["phase"] = "result"
        _session["running"] = False
        _session["result"] = copy.deepcopy(result)
        if experiment_id:
            _session["experiment_id"] = experiment_id
        _session["message"] = f"Full time: {result.get('score', '—')}"
        _session["updated_at"] = _now()


def clear_session() -> None:
    global _session
    with _lock:
        _session = None


def clear_if_references(
    *,
    tournament_id: str | None = None,
    experiment_id: str | None = None,
) -> bool:
    """Clear active session when it points at a deleted tournament or experiment."""
    global _session
    with _lock:
        if not _session:
            return False
        if tournament_id and _session.get("tournament_id") == tournament_id:
            _session = None
            return True
        if experiment_id and _session.get("experiment_id") == experiment_id:
            _session = None
            return True
        return False


def require_active_session() -> dict[str, Any]:
    s = get_session()
    if not s:
        raise ValueError("No active matchday session.")
    return s
