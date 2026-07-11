"""Active tournament fixture broadcast session (board live match → result)."""
from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any

_lock = threading.Lock()
_session: dict[str, Any] | None = None
_frame_seq = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_session() -> dict[str, Any] | None:
    with _lock:
        return copy.deepcopy(_session) if _session else None


def is_active() -> bool:
    with _lock:
        return _session is not None


def should_redirect() -> bool:
    """Clients should redirect to /matchday while a live board (or legacy sim) is on."""
    with _lock:
        if not _session:
            return False
        return _session.get("phase") in ("setup", "running", "live")


def _public_session() -> dict[str, Any] | None:
    s = get_session()
    if not s:
        return None
    return {
        "active": True,
        "phase": s.get("phase"),
        "engine": s.get("engine") or "monte_carlo",
        "fixture_id": s.get("fixture_id"),
        "tournament_id": s.get("tournament_id"),
        "tournament_name": s.get("tournament_name"),
        "stage": s.get("stage"),
        "home": s.get("home"),
        "away": s.get("away"),
        "team_a": s.get("team_a"),
        "team_b": s.get("team_b"),
        "is_knockout": bool(s.get("is_knockout")),
        "seed": s.get("seed"),
        "board": s.get("board"),
        "board_state": s.get("board_state"),
        "frame": s.get("board_state"),
        "frame_seq": s.get("frame_seq", 0),
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
    board: dict[str, Any] | None = None,
    is_knockout: bool = False,
    engine: str | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Open a Matchday session (Monte Carlo setup, or tactic-board when ``board`` is set)."""
    if board is not None or engine == "tactic_board":
        if board is None:
            raise ValueError("Tactic-board matchday requires a board payload.")
        resolved_seed = int(seed) if seed is not None else abs(hash(f"{tournament_id}:{fixture_id}")) % (2**31)
        return start_board_session(
            tournament_id=tournament_id,
            tournament_name=tournament_name,
            fixture_id=fixture_id,
            stage=stage,
            home=home,
            away=away,
            team_a=team_a,
            team_b=team_b,
            board=board,
            seed=resolved_seed,
            is_knockout=is_knockout,
        )

    global _session, _frame_seq
    with _lock:
        if _session and _session.get("phase") in ("setup", "running", "live"):
            raise ValueError(
                f"Matchday session already active for {_session.get('home')} vs {_session.get('away')}. "
                "Wait for it to finish or clear it first."
            )
        _frame_seq = 0
        _session = {
            "engine": "monte_carlo",
            "tournament_id": tournament_id,
            "tournament_name": tournament_name,
            "fixture_id": fixture_id,
            "stage": stage,
            "home": home,
            "away": away,
            "team_a": copy.deepcopy(team_a),
            "team_b": copy.deepcopy(team_b),
            "is_knockout": False,
            "seed": None,
            "board": None,
            "board_state": None,
            "frame_seq": 0,
            "phase": "setup",
            "running": False,
            "experiment_id": None,
            "message": "Teams can review lineups. Admin: start simulation when ready.",
            "result": None,
            "started_at": _now(),
            "updated_at": _now(),
        }
    return active_status()


def start_board_session(
    *,
    tournament_id: str,
    tournament_name: str,
    fixture_id: str,
    stage: str,
    home: str,
    away: str,
    team_a: dict[str, Any],
    team_b: dict[str, Any],
    board: dict[str, Any],
    seed: int,
    is_knockout: bool = False,
) -> dict[str, Any]:
    """Start a shared tactic-board Matchday broadcast (setup → live → result)."""
    global _session, _frame_seq
    with _lock:
        if _session and _session.get("phase") in ("setup", "running", "live"):
            raise ValueError(
                f"Matchday session already active for {_session.get('home')} vs {_session.get('away')}. "
                "Wait for it to finish or dismiss the result first."
            )
        _frame_seq = 0
        _session = {
            "engine": "tactic_board",
            "tournament_id": tournament_id,
            "tournament_name": tournament_name,
            "fixture_id": fixture_id,
            "stage": stage,
            "home": home,
            "away": away,
            "team_a": copy.deepcopy(team_a),
            "team_b": copy.deepcopy(team_b),
            "is_knockout": bool(is_knockout),
            "seed": int(seed),
            "board": copy.deepcopy(board),
            "board_state": None,
            "frame_seq": 0,
            "phase": "setup",
            "running": False,
            "experiment_id": None,
            "message": "Pre-match on Matchday — review lineups. Admin starts the live pin match.",
            "result": None,
            "started_at": _now(),
            "updated_at": _now(),
        }
    return active_status()


def set_board_live(message: str = "Live on Matchday — pin goals are official.") -> None:
    global _session
    with _lock:
        if not _session:
            raise ValueError("No active matchday session.")
        if _session.get("engine") != "tactic_board":
            raise ValueError("Active session is not a tactic-board match.")
        _session["phase"] = "live"
        _session["running"] = True
        _session["message"] = message
        _session["updated_at"] = _now()


def publish_board_state(state: dict[str, Any]) -> int:
    """Host publishes a compact pitch snapshot for all Matchday viewers. Returns frame seq."""
    global _session, _frame_seq
    with _lock:
        if not _session:
            return 0
        if _session.get("phase") not in ("setup", "live"):
            return int(_session.get("frame_seq") or 0)
        frame = state.get("frame") if isinstance(state.get("frame"), dict) else state
        if not isinstance(frame, dict):
            return int(_session.get("frame_seq") or 0)
        _frame_seq += 1
        frame = {**frame, "seq": _frame_seq}
        _session["board_state"] = copy.deepcopy(frame)
        _session["frame_seq"] = _frame_seq
        _session["updated_at"] = _now()
        status = frame.get("status")
        if status in ("live", "ht", "ft_et", "et_ht", "et", "pens") and _session.get("phase") == "setup":
            _session["phase"] = "live"
            _session["running"] = True
            _session["message"] = "Live on Matchday — pin goals are official."
        elif status == "ht":
            _session["message"] = f"Half time {frame.get('score') or '—'}"
        elif status == "ft_et":
            _session["message"] = f"Full time {frame.get('score') or '—'} — extra time"
        elif status == "et_ht":
            _session["message"] = f"ET half-time {frame.get('score') or '—'}"
        elif status == "et":
            _session["message"] = f"Extra time {frame.get('score') or '—'}"
        elif status == "pens":
            pens = ""
            if frame.get("pensHome") is not None and frame.get("pensAway") is not None:
                pens = f" {frame.get('pensHome')}–{frame.get('pensAway')}"
            _session["message"] = f"Penalties{pens} ({frame.get('score') or '—'})"
        elif status == "ft":
            disp = frame.get("scoreDisplay") or frame.get("score") or "—"
            _session["message"] = f"Full time {disp} — saving…"
        elif status == "live":
            minute = float(frame.get("minute") or 0)
            if minute >= 90:
                _session["message"] = (
                    f"Extra time {frame.get('score') or '—'} ({int(minute)}')"
                )
            elif _session.get("phase") == "live" and not (_session.get("message") or "").startswith("Live"):
                pass
        return _frame_seq

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
        _session["board_state"] = None
        if experiment_id:
            _session["experiment_id"] = experiment_id
        score = result.get("score", "—")
        winner = result.get("winner")
        if winner and (result.get("decided_by") or _session.get("is_knockout")):
            _session["message"] = f"Full time: {score} — {winner} advances"
        else:
            _session["message"] = f"Full time: {score}"
        _session["updated_at"] = _now()


def clear_session() -> None:
    global _session, _frame_seq
    with _lock:
        _session = None
        _frame_seq = 0


def clear_if_references(
    *,
    tournament_id: str | None = None,
    experiment_id: str | None = None,
) -> bool:
    """Clear active session when it points at a deleted tournament or experiment."""
    global _session, _frame_seq
    with _lock:
        if not _session:
            return False
        if tournament_id and _session.get("tournament_id") == tournament_id:
            _session = None
            _frame_seq = 0
            return True
        if experiment_id and _session.get("experiment_id") == experiment_id:
            _session = None
            _frame_seq = 0
            return True
        return False


def require_active_session() -> dict[str, Any]:
    s = get_session()
    if not s:
        raise ValueError("No active matchday session.")
    return s
