"""PostgreSQL database abstraction for persistent state storage on Render.

Only active when DATABASE_URL environment variable is set (Render environment).
Falls back to JSON files for local development.
"""
from __future__ import annotations

import json
import os
from typing import Any
from contextlib import contextmanager

# Only import psycopg2 if DATABASE_URL is set (i.e., running on Render)
_DB_URL = os.environ.get("DATABASE_URL", "")
_USE_DB = bool(_DB_URL)

if _USE_DB:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError:
        _USE_DB = False


def is_db_enabled() -> bool:
    """Check if database is enabled (running on Render with DATABASE_URL)."""
    return _USE_DB


def check_connection() -> dict[str, Any]:
    """Diagnostic round-trip: actually run a query, not just check DATABASE_URL is set."""
    if not _USE_DB:
        return {"enabled": False, "ok": False, "message": "DATABASE_URL not set"}
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {"enabled": True, "ok": True, "message": "Connected"}
    except Exception as e:
        return {"enabled": True, "ok": False, "message": f"{type(e).__name__}: {e}"}


@contextmanager
def _get_conn():
    """Context manager for database connections. Only works if DATABASE_URL is set."""
    if not _USE_DB:
        raise RuntimeError("DATABASE_URL not set; database is disabled (local mode)")
    conn = psycopg2.connect(_DB_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist. Only runs on Render (when DATABASE_URL is set)."""
    if not _USE_DB:
        return  # Silently skip if database is disabled

    with _get_conn() as conn:
        with conn.cursor() as cur:
            # Manual profiles table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS manual_profiles (
                    id SERIAL PRIMARY KEY,
                    player_name VARCHAR(255) NOT NULL,
                    profile_type VARCHAR(50) NOT NULL,
                    season_suffix VARCHAR(10) NOT NULL,
                    season_label VARCHAR(20),
                    stats JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(player_name, profile_type, season_suffix)
                )
            """)

            # Team lineups table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS team_lineups (
                    id SERIAL PRIMARY KEY,
                    team_name VARCHAR(255) NOT NULL UNIQUE,
                    formation VARCHAR(50),
                    lineup JSONB,
                    bench JSONB,
                    prime_player VARCHAR(255),
                    peak_season JSONB,
                    finalized BOOLEAN DEFAULT FALSE,
                    finalized_at TIMESTAMP,
                    finalized_round VARCHAR(100),
                    finalized_round_label VARCHAR(100),
                    finalized_snapshot JSONB,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Seed seasons table (player_id -> season -> stats)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS seed_seasons (
                    id SERIAL PRIMARY KEY,
                    player_id INTEGER NOT NULL,
                    season_suffix VARCHAR(10) NOT NULL,
                    stats JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(player_id, season_suffix)
                )
            """)

            # Indexes for common queries
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_manual_profiles_player_type
                ON manual_profiles(player_name, profile_type)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_seed_seasons_player
                ON seed_seasons(player_id)
            """)


# ============================================================================
# Manual Profiles
# ============================================================================

def load_all_manual_profiles() -> list[dict[str, Any]]:
    """Load all manual profiles from database. Returns empty list if database is disabled."""
    if not _USE_DB:
        return []

    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT player_name, profile_type, season_suffix, season_label, stats
                FROM manual_profiles
                ORDER BY player_name, profile_type, season_suffix
            """)
            rows = cur.fetchall()
    return [
        {
            "player_name": r["player_name"],
            "profile_type": r["profile_type"],
            "season_suffix": r["season_suffix"],
            "season_label": r["season_label"],
            "stats": r["stats"],
        }
        for r in rows
    ]


def save_manual_profile(
    player_name: str,
    profile_type: str,
    season_suffix: str,
    season_label: str,
    stats: dict[str, Any],
) -> None:
    """Insert or update a manual profile. No-op if database is disabled."""
    if not _USE_DB:
        return

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO manual_profiles
                (player_name, profile_type, season_suffix, season_label, stats, updated_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (player_name, profile_type, season_suffix)
                DO UPDATE SET stats = EXCLUDED.stats, updated_at = CURRENT_TIMESTAMP
            """, (player_name, profile_type, season_suffix, season_label, json.dumps(stats)))


def delete_manual_profile(
    player_name: str,
    profile_type: str,
    season_suffix: str,
) -> None:
    """Delete a manual profile. No-op if database is disabled."""
    if not _USE_DB:
        return

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM manual_profiles
                WHERE player_name = %s AND profile_type = %s AND season_suffix = %s
            """, (player_name, profile_type, season_suffix))


# ============================================================================
# Team Lineups
# ============================================================================

def load_all_team_lineups() -> dict[str, Any]:
    """Load all team lineups from database, keyed by team name. Returns empty dict if database is disabled."""
    if not _USE_DB:
        return {}

    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM team_lineups ORDER BY team_name")
            rows = cur.fetchall()

    result = {}
    for r in rows:
        result[r["team_name"]] = {
            "team_name": r["team_name"],
            "formation": r["formation"],
            "lineup": r["lineup"] or [],
            "bench": r["bench"] or [],
            "prime_player": r["prime_player"] or "",
            "peak_season": r["peak_season"] or {"player": "", "season": ""},
            "finalized": r["finalized"],
            "finalized_at": r["finalized_at"].isoformat() if r["finalized_at"] else None,
            "finalized_round": r["finalized_round"],
            "finalized_round_label": r["finalized_round_label"],
            "finalized_snapshot": r["finalized_snapshot"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
    return result


def save_team_lineup(team_name: str, lineup_data: dict[str, Any]) -> None:
    """Insert or update a team lineup. No-op if database is disabled."""
    if not _USE_DB:
        return

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO team_lineups
                (team_name, formation, lineup, bench, prime_player, peak_season,
                 finalized, finalized_at, finalized_round, finalized_round_label,
                 finalized_snapshot, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (team_name)
                DO UPDATE SET
                  formation = EXCLUDED.formation,
                  lineup = EXCLUDED.lineup,
                  bench = EXCLUDED.bench,
                  prime_player = EXCLUDED.prime_player,
                  peak_season = EXCLUDED.peak_season,
                  finalized = EXCLUDED.finalized,
                  finalized_at = EXCLUDED.finalized_at,
                  finalized_round = EXCLUDED.finalized_round,
                  finalized_round_label = EXCLUDED.finalized_round_label,
                  finalized_snapshot = EXCLUDED.finalized_snapshot,
                  updated_at = CURRENT_TIMESTAMP
            """, (
                team_name,
                lineup_data.get("formation"),
                json.dumps(lineup_data.get("lineup") or []),
                json.dumps(lineup_data.get("bench") or []),
                lineup_data.get("prime_player") or "",
                json.dumps(lineup_data.get("peak_season") or {"player": "", "season": ""}),
                lineup_data.get("finalized", False),
                lineup_data.get("finalized_at"),
                lineup_data.get("finalized_round"),
                lineup_data.get("finalized_round_label"),
                json.dumps(lineup_data.get("finalized_snapshot")) if lineup_data.get("finalized_snapshot") else None,
            ))


def delete_team_lineup(team_name: str) -> None:
    """Delete a team lineup. No-op if database is disabled."""
    if not _USE_DB:
        return

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM team_lineups WHERE team_name = %s", (team_name,))


# ============================================================================
# Seed Seasons
# ============================================================================

def load_all_seed_seasons() -> dict[str, dict[str, Any]]:
    """Load all seed seasons from database, keyed by player_id then season_suffix. Returns empty dict if database is disabled."""
    if not _USE_DB:
        return {}

    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT player_id, season_suffix, stats
                FROM seed_seasons
                ORDER BY player_id, season_suffix
            """)
            rows = cur.fetchall()

    result: dict[str, dict[str, Any]] = {}
    for r in rows:
        pid_str = str(r["player_id"])
        if pid_str not in result:
            result[pid_str] = {}
        result[pid_str][r["season_suffix"]] = r["stats"]
    return result


def save_seed_season(player_id: int, season_suffix: str, stats: dict[str, Any]) -> None:
    """Insert or update a seed season entry. No-op if database is disabled."""
    if not _USE_DB:
        return

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO seed_seasons (player_id, season_suffix, stats, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (player_id, season_suffix)
                DO UPDATE SET stats = EXCLUDED.stats, updated_at = CURRENT_TIMESTAMP
            """, (player_id, season_suffix, json.dumps(stats)))


def delete_seed_season(player_id: int, season_suffix: str) -> None:
    """Delete a seed season entry. No-op if database is disabled."""
    if not _USE_DB:
        return

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM seed_seasons
                WHERE player_id = %s AND season_suffix = %s
            """, (player_id, season_suffix))

