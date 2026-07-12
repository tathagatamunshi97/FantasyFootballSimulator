"""Active tournament fixture broadcast session (board live match → result).

Persists to ``data/matchday_session.json`` so a process restart can restore
score/events for an in-progress (or just-finished) Matchday. On Render free
tier the disk is still ephemeral across *redeploys*, but this survives OOM /
health-check restarts within the same instance.

Hot path: GET polls serve a prebuilt ``_poll_cache`` (no deepcopy / no disk).
"""
from __future__ import annotations

import copy
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SESSION_FILE = ROOT / "data" / "matchday_session.json"
# Throttle board-frame disk writes (frames can publish many times per second).
_PERSIST_MIN_INTERVAL_S = 2.0

_lock = threading.Lock()
_session: dict[str, Any] | None = None
_frame_seq = 0
_last_persist_mono = 0.0
# Ready-to-serve GET /api/matchday payload. Updated on publish / mutations.
_poll_cache: dict[str, Any] = {"active": False, "redirect": False, "session": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_persist_payload(payload: dict[str, Any] | None) -> None:
    """Disk write — must NOT hold ``_lock`` (avoids starving poll readers)."""
    global _last_persist_mono
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        if payload is None:
            if SESSION_FILE.exists():
                SESSION_FILE.unlink()
        else:
            tmp = SESSION_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(SESSION_FILE)
        _last_persist_mono = time.monotonic()
    except OSError as exc:
        print(f"Matchday: failed to persist session: {exc}")


def _snapshot_for_persist_locked() -> dict[str, Any] | None:
    """Build persist payload while holding lock. Caller writes outside lock."""
    if _session is None:
        return None
    return {
        "session": copy.deepcopy(_session),
        "frame_seq": _frame_seq,
        "persisted_at": _now(),
    }


def _should_persist_locked(*, force: bool = False) -> bool:
    if force:
        return True
    return (time.monotonic() - _last_persist_mono) >= _PERSIST_MIN_INTERVAL_S


def _persist_locked(*, force: bool = False) -> dict[str, Any] | None:
    """If a write is due, return snapshot to persist *outside* the lock. Else None.

    Caller must hold ``_lock``. Prefer::

        snap = _persist_locked(force=...)
        # release lock
        if snap is not False:  # use sentinel
    """
    if not _should_persist_locked(force=force):
        return False  # type: ignore[return-value]  # sentinel: skip
    return _snapshot_for_persist_locked()


def _flush_persist(snap: dict[str, Any] | None | bool) -> None:
    """Write snap from ``_persist_locked``; ``False`` means skip."""
    if snap is False:
        return
    _write_persist_payload(snap)


def _build_public_session_locked() -> dict[str, Any] | None:
    """Public poll view. Caller holds ``_lock``. No deepcopy — shares nested refs."""
    s = _session
    if not s:
        return None
    phase = s.get("phase")
    board = s.get("board")
    # Live polls: omit bulky roster trees when board payload is present (viewers use board).
    include_rosters = phase in ("setup", "result") or not board
    out: dict[str, Any] = {
        "active": True,
        "phase": phase,
        "engine": s.get("engine") or "monte_carlo",
        "fixture_id": s.get("fixture_id"),
        "tournament_id": s.get("tournament_id"),
        "tournament_name": s.get("tournament_name"),
        "stage": s.get("stage"),
        "home": s.get("home"),
        "away": s.get("away"),
        "is_knockout": bool(s.get("is_knockout")),
        "seed": s.get("seed"),
        "board": board,
        "board_state": s.get("board_state"),
        "frame": s.get("board_state"),
        "frame_seq": s.get("frame_seq", 0),
        "experiment_id": s.get("experiment_id"),
        "running": s.get("running", False),
        "message": s.get("message"),
        "result": s.get("result"),
        "started_at": s.get("started_at"),
        "updated_at": s.get("updated_at"),
        "restored": bool(s.get("restored")),
    }
    if include_rosters:
        out["team_a"] = s.get("team_a")
        out["team_b"] = s.get("team_b")
    return out


def _refresh_poll_cache_locked() -> None:
    """Rebuild ``_poll_cache`` from ``_session``. Caller holds ``_lock``."""
    global _poll_cache
    pub = _build_public_session_locked()
    if not pub:
        _poll_cache = {"active": False, "redirect": False, "session": None}
        return
    _poll_cache = {
        "active": True,
        "redirect": pub.get("phase") in ("setup", "running", "live"),
        "session": pub,
    }


def _patch_poll_cache_frame_locked() -> None:
    """Cheap update after board-state publish. Caller holds ``_lock``."""
    if not _session:
        _refresh_poll_cache_locked()
        return
    sess = _poll_cache.get("session")
    if not isinstance(sess, dict):
        _refresh_poll_cache_locked()
        return
    sess["board_state"] = _session.get("board_state")
    sess["frame"] = _session.get("board_state")
    sess["frame_seq"] = _session.get("frame_seq", 0)
    sess["message"] = _session.get("message")
    sess["phase"] = _session.get("phase")
    sess["running"] = _session.get("running", False)
    sess["updated_at"] = _session.get("updated_at")
    _poll_cache["active"] = True
    _poll_cache["redirect"] = sess.get("phase") in ("setup", "running", "live")


def restore_from_disk() -> bool:
    """Load incomplete/recent Matchday session after process start. Returns True if restored."""
    global _session, _frame_seq, _last_persist_mono
    if not SESSION_FILE.exists():
        return False
    try:
        payload = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Matchday: could not restore session file: {exc}")
        return False

    stored = payload.get("session") if isinstance(payload, dict) else None
    if not isinstance(stored, dict):
        return False

    phase = stored.get("phase")
    # Restore live/setup/running; also keep a finished result so viewers still see FT after restart.
    if phase not in ("setup", "running", "live", "result"):
        return False

    snap: dict[str, Any] | None | bool = False
    with _lock:
        _session = stored
        _session["restored"] = True
        _frame_seq = int(payload.get("frame_seq") or stored.get("frame_seq") or 0)
        if phase in ("setup", "running", "live"):
            base = (_session.get("message") or "Matchday").split("(restored")[0].strip()
            _session["message"] = (
                f"{base} (restored after server restart — score/events from last snapshot)."
            )
            _session["updated_at"] = _now()
        _refresh_poll_cache_locked()
        snap = _persist_locked(force=True)
        _last_persist_mono = time.monotonic()
    _flush_persist(snap)

    home = stored.get("home")
    away = stored.get("away")
    print(f"Matchday: restored {phase} session {home} vs {away} (frame {_frame_seq}).")
    return True


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


def active_status() -> dict[str, Any]:
    """Cheap poll payload: shallow copy of cached status (no session deepcopy)."""
    with _lock:
        cache = _poll_cache
        session = cache.get("session")
        return {
            "active": bool(cache.get("active")),
            "redirect": bool(cache.get("redirect")),
            "session": dict(session) if isinstance(session, dict) else None,
        }


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
    snap: dict[str, Any] | None | bool = False
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
        _refresh_poll_cache_locked()
        snap = _persist_locked(force=True)
    _flush_persist(snap)
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
    snap: dict[str, Any] | None | bool = False
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
        _refresh_poll_cache_locked()
        snap = _persist_locked(force=True)
    _flush_persist(snap)
    return active_status()


def set_board_live(message: str = "Live on Matchday — pin goals are official.") -> None:
    global _session
    snap: dict[str, Any] | None | bool = False
    with _lock:
        if not _session:
            raise ValueError("No active matchday session.")
        if _session.get("engine") != "tactic_board":
            raise ValueError("Active session is not a tactic-board match.")
        _session["phase"] = "live"
        _session["running"] = True
        _session["message"] = message
        _session["updated_at"] = _now()
        _refresh_poll_cache_locked()
        snap = _persist_locked(force=True)
    _flush_persist(snap)


def publish_board_state(state: dict[str, Any]) -> int:
    """Host publishes a compact pitch snapshot for all Matchday viewers. Returns frame seq."""
    global _session, _frame_seq
    snap: dict[str, Any] | None | bool = False
    seq = 0
    with _lock:
        if not _session:
            return 0
        if _session.get("phase") not in ("setup", "live"):
            return int(_session.get("frame_seq") or 0)
        frame = state.get("frame") if isinstance(state.get("frame"), dict) else state
        if not isinstance(frame, dict):
            return int(_session.get("frame_seq") or 0)
        # Drop legacy momentum from host frames (UI removed; shrink poll JSON).
        frame = {k: v for k, v in frame.items() if k != "momentum"}
        _frame_seq += 1
        frame = {**frame, "seq": _frame_seq}
        had_frame = _session.get("board_state") is not None
        _session["board_state"] = frame
        _session["frame_seq"] = _frame_seq
        _session["updated_at"] = _now()
        status = frame.get("status")
        force_persist = (not had_frame) or status in ("ht", "ft", "ft_et", "et_ht", "et", "pens")
        if status in ("live", "ht", "ft_et", "et_ht", "et", "pens") and _session.get("phase") == "setup":
            _session["phase"] = "live"
            _session["running"] = True
            _session["message"] = "Live on Matchday — pin goals are official."
            force_persist = True
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
        # Drop roster trees from live poll cache once; otherwise patch frame fields only.
        cached = _poll_cache.get("session")
        if (
            _session.get("phase") == "live"
            and isinstance(cached, dict)
            and ("team_a" in cached or "team_b" in cached)
        ):
            _refresh_poll_cache_locked()
        else:
            _patch_poll_cache_frame_locked()
        # Deepcopy for disk only when due — write happens outside the lock.
        snap = _persist_locked(force=force_persist)
        seq = _frame_seq
    _flush_persist(snap)
    return seq


def set_running(experiment_id: str, message: str = "Running simulation…") -> None:
    global _session
    snap: dict[str, Any] | None | bool = False
    with _lock:
        if not _session:
            raise ValueError("No active matchday session.")
        _session["phase"] = "running"
        _session["running"] = True
        _session["experiment_id"] = experiment_id
        _session["message"] = message
        _session["updated_at"] = _now()
        _refresh_poll_cache_locked()
        snap = _persist_locked(force=True)
    _flush_persist(snap)


def update_message(message: str) -> None:
    global _session
    snap: dict[str, Any] | None | bool = False
    with _lock:
        if _session:
            _session["message"] = message
            _session["updated_at"] = _now()
            _refresh_poll_cache_locked()
            snap = _persist_locked(force=True)
    _flush_persist(snap)


def set_result(result: dict[str, Any], *, experiment_id: str | None = None) -> None:
    global _session
    snap: dict[str, Any] | None | bool = False
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
        _refresh_poll_cache_locked()
        snap = _persist_locked(force=True)
    _flush_persist(snap)


def clear_session() -> None:
    global _session, _frame_seq
    snap: dict[str, Any] | None | bool = False
    with _lock:
        _session = None
        _frame_seq = 0
        _refresh_poll_cache_locked()
        snap = _persist_locked(force=True)
    _flush_persist(snap)


def clear_if_references(
    *,
    tournament_id: str | None = None,
    experiment_id: str | None = None,
) -> bool:
    """Clear active session when it points at a deleted tournament or experiment."""
    global _session, _frame_seq
    snap: dict[str, Any] | None | bool = False
    cleared = False
    with _lock:
        if not _session:
            return False
        if tournament_id and _session.get("tournament_id") == tournament_id:
            _session = None
            _frame_seq = 0
            cleared = True
        elif experiment_id and _session.get("experiment_id") == experiment_id:
            _session = None
            _frame_seq = 0
            cleared = True
        if cleared:
            _refresh_poll_cache_locked()
            snap = _persist_locked(force=True)
    if cleared:
        _flush_persist(snap)
    return cleared


def require_active_session() -> dict[str, Any]:
    s = get_session()
    if not s:
        raise ValueError("No active matchday session.")
    return s
