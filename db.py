"""Structured persistent state storage, backed by Cloudflare R2.

Formerly PostgreSQL-backed; Render's free-tier Postgres database expired
(a known 90-day limit), so this now stores the same 3 collections
(manual_profiles, team_lineups, seed_seasons) as JSON blobs in R2 via
r2_storage.py, behind the exact same public function signatures so no
caller needed to change. Falls back to local JSON files (handled by each
caller, not here) when R2 is not configured.
"""
from __future__ import annotations

import time
from typing import Any

import r2_storage

_MANUAL_PROFILES_KEY = "db/manual_profiles.json"
_TEAM_LINEUPS_KEY = "db/team_lineups.json"
_SEED_SEASONS_KEY = "db/seed_seasons.json"

# Short in-process cache over R2 reads. A single R2 blob fetch is a real
# network round-trip (unlike the old Postgres query it replaced), and some
# callers load the same blob multiple times per request -- e.g.
# apply_team_lineup() calls get_team_lineup() once per team, so preparing
# a single match previously meant 2 separate full-blob R2 fetches with no
# caching at all. A few seconds of staleness is a non-issue for these
# collections; writes update the cache directly (not just invalidate it)
# so a save is immediately visible to the next read.
_CACHE_TTL_S = 8.0
_cache: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str) -> Any:
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.monotonic() - ts > _CACHE_TTL_S:
        return None
    return value


def _cache_put(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)


def _load_blob_cached(key: str) -> Any:
    cached = _cache_get(key)
    if cached is not None:
        return cached
    value = r2_storage.load_json_blob(key)
    if value is not None:
        _cache_put(key, value)
    return value


def _save_blob(key: str, value: Any) -> None:
    r2_storage.save_json_blob(key, value)
    _cache_put(key, value)


def is_db_enabled() -> bool:
    """Check if the (R2-backed) database is enabled."""
    return r2_storage.is_r2_enabled()


def check_connection() -> dict[str, Any]:
    """Diagnostic round-trip: actually write/read/delete a test blob, not just check config."""
    if not is_db_enabled():
        return {"enabled": False, "ok": False, "message": "R2 not configured"}

    import time

    test_key = "_healthcheck/db_ping.json"
    payload = {"ts": time.time()}
    try:
        if not r2_storage.save_json_blob(test_key, payload):
            return {"enabled": True, "ok": False, "bucket": None, "message": "Failed to write test blob"}
        readback = r2_storage.load_json_blob(test_key)
        r2_storage.delete_json_blob(test_key)
        if not readback or readback.get("ts") != payload["ts"]:
            return {"enabled": True, "ok": False, "message": "Read-back value did not match what was written"}
        return {"enabled": True, "ok": True, "message": "Connected"}
    except Exception as e:
        return {"enabled": True, "ok": False, "message": f"{type(e).__name__}: {e}"}


def init_db() -> None:
    """Ensure the 3 backing blobs exist. Silently skips if R2 is disabled."""
    if not is_db_enabled():
        return

    if r2_storage.load_json_blob(_MANUAL_PROFILES_KEY) is None:
        r2_storage.save_json_blob(_MANUAL_PROFILES_KEY, {"profiles": []})
    if r2_storage.load_json_blob(_TEAM_LINEUPS_KEY) is None:
        r2_storage.save_json_blob(_TEAM_LINEUPS_KEY, {})
    if r2_storage.load_json_blob(_SEED_SEASONS_KEY) is None:
        r2_storage.save_json_blob(_SEED_SEASONS_KEY, {})


# ============================================================================
# Manual Profiles
# ============================================================================

def load_all_manual_profiles() -> list[dict[str, Any]]:
    """Load all manual profiles. Returns empty list if R2 is disabled."""
    if not is_db_enabled():
        return []
    blob = _load_blob_cached(_MANUAL_PROFILES_KEY)
    profiles = (blob or {}).get("profiles", [])
    return sorted(
        profiles, key=lambda r: (r.get("player_name", ""), r.get("profile_type", ""), r.get("season_suffix", ""))
    )


def save_manual_profile(
    player_name: str,
    profile_type: str,
    season_suffix: str,
    season_label: str,
    stats: dict[str, Any],
) -> None:
    """Insert or update a manual profile. No-op if R2 is disabled."""
    if not is_db_enabled():
        return

    blob = _load_blob_cached(_MANUAL_PROFILES_KEY) or {"profiles": []}
    profiles = blob.setdefault("profiles", [])
    entry = {
        "player_name": player_name,
        "profile_type": profile_type,
        "season_suffix": season_suffix,
        "season_label": season_label,
        "stats": stats,
    }
    for i, row in enumerate(profiles):
        if (
            row.get("player_name") == player_name
            and row.get("profile_type") == profile_type
            and row.get("season_suffix") == season_suffix
        ):
            profiles[i] = entry
            break
    else:
        profiles.append(entry)
    _save_blob(_MANUAL_PROFILES_KEY, blob)


def delete_manual_profile(
    player_name: str,
    profile_type: str,
    season_suffix: str,
) -> None:
    """Delete a manual profile. No-op if R2 is disabled."""
    if not is_db_enabled():
        return

    blob = _load_blob_cached(_MANUAL_PROFILES_KEY)
    if not blob:
        return
    profiles = blob.get("profiles", [])
    blob["profiles"] = [
        row
        for row in profiles
        if not (
            row.get("player_name") == player_name
            and row.get("profile_type") == profile_type
            and row.get("season_suffix") == season_suffix
        )
    ]
    _save_blob(_MANUAL_PROFILES_KEY, blob)


# ============================================================================
# Team Lineups
# ============================================================================

def load_all_team_lineups() -> dict[str, Any]:
    """Load all team lineups, keyed by team name. Returns empty dict if R2 is disabled."""
    if not is_db_enabled():
        return {}
    return _load_blob_cached(_TEAM_LINEUPS_KEY) or {}


def save_team_lineup(team_name: str, lineup_data: dict[str, Any]) -> None:
    """Insert or update a team lineup. No-op if R2 is disabled."""
    if not is_db_enabled():
        return

    blob = _load_blob_cached(_TEAM_LINEUPS_KEY) or {}
    blob[team_name] = lineup_data
    _save_blob(_TEAM_LINEUPS_KEY, blob)


def delete_team_lineup(team_name: str) -> None:
    """Delete a team lineup. No-op if R2 is disabled."""
    if not is_db_enabled():
        return

    blob = _load_blob_cached(_TEAM_LINEUPS_KEY)
    if not blob or team_name not in blob:
        return
    del blob[team_name]
    _save_blob(_TEAM_LINEUPS_KEY, blob)


# ============================================================================
# Seed Seasons
# ============================================================================

def load_all_seed_seasons() -> dict[str, dict[str, Any]]:
    """Load all seed seasons, keyed by player_id then season_suffix. Returns empty dict if R2 is disabled."""
    if not is_db_enabled():
        return {}
    return _load_blob_cached(_SEED_SEASONS_KEY) or {}


def save_seed_season(player_id: int, season_suffix: str, stats: dict[str, Any]) -> None:
    """Insert or update a seed season entry. No-op if R2 is disabled."""
    if not is_db_enabled():
        return

    blob = _load_blob_cached(_SEED_SEASONS_KEY) or {}
    pid_str = str(player_id)
    blob.setdefault(pid_str, {})[season_suffix] = stats
    _save_blob(_SEED_SEASONS_KEY, blob)


def delete_seed_season(player_id: int, season_suffix: str) -> None:
    """Delete a seed season entry. No-op if R2 is disabled."""
    if not is_db_enabled():
        return

    blob = _load_blob_cached(_SEED_SEASONS_KEY)
    if not blob:
        return
    pid_str = str(player_id)
    if pid_str in blob and season_suffix in blob[pid_str]:
        del blob[pid_str][season_suffix]
        if not blob[pid_str]:
            del blob[pid_str]
        _save_blob(_SEED_SEASONS_KEY, blob)
