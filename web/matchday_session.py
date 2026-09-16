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
# Full-engine-state checkpoints (see publish_checkpoint) are far heavier than
# a display frame and only exist for disconnect recovery, so they're saved
# much less often than the ~220ms board-state stream.
_CHECKPOINTS_DIR = ROOT / "data" / "matchday_checkpoints"
_CHECKPOINT_MIN_INTERVAL_S = 12.0

_lock = threading.Lock()
_session: dict[str, Any] | None = None
_frame_seq = 0
_last_checkpoint_mono = 0.0
# Recorded highlight-clip replays (friendly matches only) -- a bundled
# buildup-to-event recording, published once per resolved event, kept
# separate from _frame_seq/board_state (the continuous per-tick position
# stream). See publish_highlight_clip().
_highlight_seq = 0
_MAX_HIGHLIGHT_CLIPS = 5
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
        "engine": s.get("engine") or "tactic_board",
        "fixture_id": s.get("fixture_id"),
        "tournament_id": s.get("tournament_id"),
        "tournament_name": s.get("tournament_name"),
        "stage": s.get("stage"),
        "home": s.get("home"),
        "away": s.get("away"),
        "is_knockout": bool(s.get("is_knockout")),
        "is_league": bool(s.get("is_league")),
        "is_final": bool(s.get("is_final")),
        "is_experiment": bool(s.get("is_experiment")),
        "agg_context": s.get("agg_context"),
        "seed": s.get("seed"),
        "board": board,
        "board_state": s.get("board_state"),
        "frame": s.get("board_state"),
        "frame_seq": s.get("frame_seq", 0),
        "highlight_clips": s.get("highlight_clips") or [],
        "highlight_seq": s.get("highlight_seq", 0),
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
    is_league: bool = False,
    is_final: bool = False,
    is_experiment: bool = False,
    agg_context: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Start a shared tactic-board Matchday broadcast (setup → live → result).

    ``is_league`` marks a real league/group-table fixture (round-robin, not
    a one-off Team Lab/friendly matchup) — gets the same small home push as
    a knockout tie.

    ``is_final`` marks the Final round of a knockout bracket — conventionally
    a neutral-venue match, so the live engine excludes it from the home push
    even though ``is_knockout`` is still true.

    ``is_experiment`` marks an ad-hoc Team Lab experiment rather than a
    tournament fixture — ``fixture_id`` then holds the experiment's own id,
    and completion routes to experiments.complete_experiment_from_board
    instead of tournament.complete_from_board (see /api/matchday/complete).

    ``agg_context`` (leg 2 of a two-legged knockout tie only) carries the
    aggregate goals each side enters this leg with — {"enteringAggHome":
    int, "enteringAggAway": int} — so the live board can trigger extra time
    off the aggregate/away-goals rule instead of this leg's own scoreline.
    """
    global _session, _frame_seq, _highlight_seq
    snap: dict[str, Any] | None | bool = False
    with _lock:
        if _session and _session.get("phase") in ("setup", "running", "live"):
            raise ValueError(
                f"Matchday session already active for {_session.get('home')} vs {_session.get('away')}. "
                "Wait for it to finish or dismiss the result first."
            )
        _frame_seq = 0
        _highlight_seq = 0
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
            "is_league": bool(is_league),
            "is_final": bool(is_final),
            "is_experiment": bool(is_experiment),
            "agg_context": dict(agg_context) if agg_context else None,
            "seed": int(seed),
            "board": copy.deepcopy(board),
            "board_state": None,
            "frame_seq": 0,
            "highlight_clips": [],
            "highlight_seq": 0,
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


def publish_highlight_clip(clip: dict[str, Any]) -> int:
    """Host publishes one finished buildup-to-event recording (friendlies only).

    Unlike ``publish_board_state`` (a per-tick position stream where an
    overwrite is fine -- the newest frame always supersedes an older one),
    every clip is a distinct event a viewer should see, so this appends
    rather than overwrites, capped at the most recent ``_MAX_HIGHLIGHT_CLIPS``.
    Returns the clip's assigned seq.
    """
    global _session, _highlight_seq
    snap: dict[str, Any] | None | bool = False
    seq = 0
    with _lock:
        if not _session:
            return 0
        if _session.get("phase") not in ("setup", "live"):
            return int(_session.get("highlight_seq") or 0)
        _highlight_seq += 1
        stamped = {**clip, "seq": _highlight_seq}
        clips = list(_session.get("highlight_clips") or [])
        clips.append(stamped)
        if len(clips) > _MAX_HIGHLIGHT_CLIPS:
            clips = clips[-_MAX_HIGHLIGHT_CLIPS:]
        _session["highlight_clips"] = clips
        _session["highlight_seq"] = _highlight_seq
        _session["updated_at"] = _now()
        # Clip publishes are rare (a handful per match) unlike the 220ms
        # board-state hot path, so always take the full-rebuild path rather
        # than extending _patch_poll_cache_frame_locked's own explicit
        # whitelist for something this infrequent.
        _refresh_poll_cache_locked()
        # A highlight is a meaningful moment, worth not losing on a crash/
        # restart the same way phase transitions already force-persist.
        snap = _persist_locked(force=True)
        seq = _highlight_seq
    _flush_persist(snap)
    return seq


def _checkpoint_path(fixture_id: str) -> Path:
    return _CHECKPOINTS_DIR / f"{fixture_id}.json"


def _save_checkpoint_blob(fixture_id: str, checkpoint: dict[str, Any]) -> None:
    """Dual-write (R2 best-effort + disk), overwritten in place per fixture --
    same idea as tournament.py's match-trace blobs, but this one is mutated
    repeatedly for one fixture rather than written once and kept forever."""
    try:
        import r2_storage

        if r2_storage.is_r2_enabled():
            r2_storage.save_json_blob(f"matchday_checkpoints/{fixture_id}.json", checkpoint)
    except Exception:
        pass
    try:
        path = _checkpoint_path(fixture_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        print(f"Matchday: failed to save checkpoint for {fixture_id}: {exc}")


def _load_checkpoint_blob(fixture_id: str) -> dict[str, Any] | None:
    try:
        import r2_storage

        if r2_storage.is_r2_enabled():
            data = r2_storage.load_json_blob(f"matchday_checkpoints/{fixture_id}.json")
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    path = _checkpoint_path(fixture_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _delete_checkpoint_blob(fixture_id: str) -> None:
    try:
        import r2_storage

        if r2_storage.is_r2_enabled():
            r2_storage.delete_json_blob(f"matchday_checkpoints/{fixture_id}.json")
    except Exception:
        pass
    try:
        path = _checkpoint_path(fixture_id)
        if path.exists():
            path.unlink()
    except OSError:
        pass


def publish_checkpoint(body: dict[str, Any]) -> dict[str, Any]:
    """Host periodically posts a full engine-state snapshot (getEngineState()
    on the live tactic board) so a disconnected host can be recovered close
    to where the match left off, instead of "Resume hosting" restarting the
    whole fixture from kickoff. Deliberately separate from publish_board_state
    (the ~220ms display-frame stream): this is heavier and only needed for
    recovery, so it's throttled server-side too (in case a client bug bypasses
    its own throttle) and the write happens outside the lock, same pattern as
    _flush_persist.
    """
    global _last_checkpoint_mono
    checkpoint = body.get("checkpoint")
    if not isinstance(checkpoint, dict):
        return {"ok": False, "reason": "no checkpoint payload"}
    with _lock:
        if not _session or _session.get("phase") not in ("setup", "live"):
            return {"ok": False, "reason": "no active live session"}
        fixture_id = _session.get("fixture_id")
        if not fixture_id:
            return {"ok": False, "reason": "no fixture id"}
        now = time.monotonic()
        if not body.get("force") and (now - _last_checkpoint_mono) < _CHECKPOINT_MIN_INTERVAL_S:
            return {"ok": True, "skipped": True}
        _last_checkpoint_mono = now
    _save_checkpoint_blob(fixture_id, checkpoint)
    return {"ok": True}


def get_checkpoint() -> dict[str, Any] | None:
    """Latest checkpoint for the currently active fixture, if any.

    Falls back to the lightweight board_state frame (always saved, even for
    matches that started before this feature shipped, or that disconnected
    before the first ~15s checkpoint interval elapsed) wrapped as a
    ``legacyFrame`` -- tactic_board.js's applyResumeState recognizes that
    shape and does a best-effort reconstruction (score/clock/goals/cards/
    positions, not the deep per-pin tactical state a real checkpoint has).
    Still far better than "Resume hosting" restarting from a cold kickoff.
    """
    with _lock:
        if not _session:
            return None
        fixture_id = _session.get("fixture_id")
        board_state = _session.get("board_state")
    if not fixture_id:
        return None
    saved = _load_checkpoint_blob(fixture_id)
    if saved:
        return saved
    if isinstance(board_state, dict):
        return {"v": 0, "legacyFrame": board_state}
    return None


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
    fixture_id = None
    with _lock:
        if not _session:
            return
        fixture_id = _session.get("fixture_id")
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
    if fixture_id:
        _delete_checkpoint_blob(fixture_id)


def clear_session() -> None:
    global _session, _frame_seq, _highlight_seq
    snap: dict[str, Any] | None | bool = False
    fixture_id = _session.get("fixture_id") if _session else None
    with _lock:
        _session = None
        _frame_seq = 0
        _highlight_seq = 0
        _refresh_poll_cache_locked()
        snap = _persist_locked(force=True)
    _flush_persist(snap)
    if fixture_id:
        _delete_checkpoint_blob(fixture_id)


def clear_if_references(
    *,
    tournament_id: str | None = None,
    experiment_id: str | None = None,
) -> bool:
    """Clear active session when it points at a deleted tournament or experiment."""
    global _session, _frame_seq, _highlight_seq
    snap: dict[str, Any] | None | bool = False
    cleared = False
    with _lock:
        if not _session:
            return False
        if tournament_id and _session.get("tournament_id") == tournament_id:
            _session = None
            _frame_seq = 0
            _highlight_seq = 0
            cleared = True
        elif experiment_id and _session.get("experiment_id") == experiment_id:
            _session = None
            _frame_seq = 0
            _highlight_seq = 0
            cleared = True
        if cleared:
            _refresh_poll_cache_locked()
            snap = _persist_locked(force=True)
    if cleared:
        _flush_persist(snap)
    return cleared


def restore_session(data: dict[str, Any]) -> dict[str, Any]:
    """Disaster recovery: reconstruct an active session from a previously
    backed-up ``/api/matchday`` response -- e.g. one an admin copied out of
    their browser before a Render redeploy wiped the in-memory session (this
    module's own disk persistence doesn't survive that; see the module
    docstring). Accepts the same shape ``_build_public_session_locked``
    produces, so a raw saved GET response's ``session`` value can be passed
    straight through. Deliberately refuses to run over an already-active
    session -- this is a manual last-resort tool, never something that
    should silently clobber a real live match.
    """
    global _session, _frame_seq, _highlight_seq
    if not isinstance(data, dict):
        raise ValueError("Invalid session payload")
    fixture_id = data.get("fixture_id")
    tournament_id = data.get("tournament_id")
    board = data.get("board")
    if not fixture_id or not tournament_id or not isinstance(board, dict):
        raise ValueError("Session payload missing fixture_id/tournament_id/board")
    board_state = data.get("board_state") or data.get("frame")
    snap: dict[str, Any] | None | bool = False
    with _lock:
        if _session and _session.get("phase") in ("setup", "running", "live"):
            raise ValueError(
                f"A session is already active for {_session.get('home')} vs {_session.get('away')}. "
                "Dismiss or complete it before restoring another."
            )
        frame_seq = int(data.get("frame_seq") or (board_state or {}).get("seq") or 0)
        _frame_seq = frame_seq
        _highlight_seq = int(data.get("highlight_seq") or 0)
        _session = {
            "engine": data.get("engine") or "tactic_board",
            "tournament_id": tournament_id,
            "tournament_name": data.get("tournament_name"),
            "fixture_id": fixture_id,
            "stage": data.get("stage"),
            "home": data.get("home"),
            "away": data.get("away"),
            "team_a": data.get("team_a"),
            "team_b": data.get("team_b"),
            "is_knockout": bool(data.get("is_knockout")),
            "is_league": bool(data.get("is_league")),
            "is_final": bool(data.get("is_final")),
            "is_experiment": bool(data.get("is_experiment")),
            "agg_context": data.get("agg_context"),
            "seed": data.get("seed"),
            "board": board,
            "board_state": board_state,
            "frame_seq": frame_seq,
            "highlight_clips": data.get("highlight_clips") or [],
            "highlight_seq": _highlight_seq,
            "phase": "live",
            "running": True,
            "experiment_id": data.get("experiment_id"),
            "message": f"Restored after a redeploy — {data.get('home')} vs {data.get('away')}.",
            "result": None,
            "started_at": data.get("started_at") or _now(),
            "updated_at": _now(),
            "restored": True,
        }
        _refresh_poll_cache_locked()
        snap = _persist_locked(force=True)
    _flush_persist(snap)
    # A restore means this backed-up board_state is the new ground truth --
    # any checkpoint blob already saved for this fixture (e.g. from an
    # earlier, now-abandoned live session that had already started posting
    # its own getEngineState() snapshots) is now stale and would otherwise
    # shadow this fresh data in get_checkpoint(), which checks the saved
    # blob before ever falling back to board_state. Real user report: a
    # restore's board_state showed correct stats/xG to viewers (who read it
    # directly) while "Resume hosting" pulled a stale, stats-poor checkpoint
    # from a prior resume attempt instead.
    _delete_checkpoint_blob(fixture_id)
    return active_status()


def require_active_session() -> dict[str, Any]:
    s = get_session()
    if not s:
        raise ValueError("No active matchday session.")
    return s
