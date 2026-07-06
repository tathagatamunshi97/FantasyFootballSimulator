"""Persist and serve latest simulation state for the web dashboard."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from report_builder import build_report, load_matchup
from sofascore_client import StatsStore

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "data" / "web_state.json"

_lock = threading.Lock()
_running = False
_stats_store: StatsStore | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_admin_token() -> str:
    return os.environ.get("SIM_ADMIN_TOKEN", "changeme")


def _default_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "message": "No simulation has been run yet.",
        "updated_at": None,
        "running": False,
        "report": None,
    }


def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return _default_state()


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def get_stats_store() -> StatsStore:
    global _stats_store
    if _stats_store is None:
        _stats_store = StatsStore()
    return _stats_store


def reload_stats_store() -> StatsStore:
    """Reload player cache from disk (e.g. after seed merge)."""
    global _stats_store
    _stats_store = StatsStore()
    return _stats_store


def is_running() -> bool:
    with _lock:
        return _running


def run_simulation(*, n_simulations: int = 10000, seed: int | None = None) -> dict[str, Any]:
    global _running
    with _lock:
        if _running:
            raise RuntimeError("A simulation is already running.")
        _running = True

    state = load_state()
    state["status"] = "running"
    state["running"] = True
    state["message"] = f"Running {n_simulations:,} Monte Carlo simulations…"
    state["updated_at"] = _now()
    save_state(state)

    try:
        home, away = load_matchup()
        store = get_stats_store()
        report = build_report(
            home,
            away,
            store.players,
            n_simulations=n_simulations,
            seed=seed,
        )
        result = {
            "status": "ready",
            "message": f"Completed {n_simulations:,} simulations.",
            "updated_at": _now(),
            "running": False,
            "report": report,
        }
        save_state(result)
        return result
    except Exception as exc:
        err = {
            "status": "error",
            "message": str(exc),
            "updated_at": _now(),
            "running": False,
            "report": state.get("report"),
        }
        save_state(err)
        raise
    finally:
        with _lock:
            _running = False
