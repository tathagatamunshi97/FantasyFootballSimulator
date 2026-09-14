"""Multi-season project -- the Season-2+ auction/transfer pool: every player
who has left a team (released by a continuing team, or carried in wholesale
from a removed team) since a season-store tournament began. Stats are
deliberately NOT snapshotted into a pool entry -- player stats are already
keyed by name only, independent of team (see sofascore_client.StatsStore /
manual_profiles.py), so list_pool() enriches at read time from the live
cache, matching this codebase's "recompute derived data, store only the raw
fact" convention (zone_breakdown, shots, purse contributions all do this).

Same store skeleton as season_roster.py -- see that module's docstring for
why this gets the R2-blob-with-local-fallback treatment rather than
team_purse.py's plain-local-file pattern.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
POOL_PATH = ROOT / "data" / "transfer_pool.json"
_R2_KEY = "transfer_pool.json"

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_all() -> dict[str, Any]:
    try:
        import r2_storage

        if r2_storage.is_r2_enabled():
            data = r2_storage.load_json_blob(_R2_KEY)
            if isinstance(data, dict):
                return data
    except (ImportError, Exception):
        pass
    if not POOL_PATH.exists():
        return {}
    try:
        return json.loads(POOL_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(data: dict[str, Any]) -> None:
    """Never raises -- a save failure here must never fail an unrelated request."""
    try:
        import r2_storage

        if r2_storage.is_r2_enabled():
            r2_storage.save_json_blob(_R2_KEY, data)
    except Exception as exc:
        print(f"transfer_pool: R2 save failed: {exc}")
    try:
        POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
        POOL_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        print(f"transfer_pool: local JSON save failed: {exc}")


def add_to_pool(tournament_id: str, player: str, source_team: str, reason: str) -> None:
    """reason: "released" (an owner let one player go) or "team_removed"
    (their whole squad was dropped into the pool by advance_to_next_season)."""
    if reason not in ("released", "team_removed"):
        raise ValueError(f"Unknown pool reason: {reason!r}")
    with _lock:
        store = _load_all()
        rows = store.setdefault(tournament_id, [])
        rows.append(
            {"player": player, "source_team": source_team, "released_at": _now(), "reason": reason}
        )
        _save_all(store)


def list_pool(tournament_id: str) -> list[dict[str, Any]]:
    """Every pool entry for this tournament, each enriched with a light
    stats summary for auction-evaluation display. Best-effort: a player
    whose stats can't be resolved still appears, just without the summary,
    same fail-open convention the rest of this app's stats lookups use."""
    with _lock:
        store = _load_all()
    rows = [dict(r) for r in store.get(tournament_id) or []]
    if not rows:
        return rows

    try:
        from web.state import get_stats_store

        store_obj = get_stats_store()
        names = [r["player"] for r in rows]
        stats_map = store_obj.cached_stats_map(names)
    except Exception:
        stats_map = {}

    for row in rows:
        stats = stats_map.get(row["player"])
        if stats is None:
            row["stats_summary"] = None
            continue
        row["stats_summary"] = {
            "primary_position": stats.primary_position,
            "fpl_position": stats.fpl_position,
            "minutes": stats.minutes,
            "goals90": round(getattr(stats, "goals90", 0.0) or 0.0, 2),
            "xg90": round(getattr(stats, "xg90", 0.0) or 0.0, 2),
            "xa90": round(getattr(stats, "xa90", 0.0) or 0.0, 2),
            "seasons_used": stats.seasons_used,
        }
    return rows


def remove_from_pool(tournament_id: str, player: str) -> None:
    """Drop a player once they're picked up (auction win / transfer) --
    not used by this phase (no auction exists yet) but provided now so
    Phase 2 doesn't need to touch this module's storage shape."""
    with _lock:
        store = _load_all()
        rows = store.get(tournament_id) or []
        store[tournament_id] = [r for r in rows if r.get("player") != player]
        _save_all(store)
