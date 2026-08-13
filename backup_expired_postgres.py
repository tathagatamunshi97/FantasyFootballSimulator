#!/usr/bin/env python3
"""One-off: best-effort pull of existing data out of the (expired) Postgres
database before cutting over to the R2-backed db.py.

Connects directly via psycopg2 to DATABASE_URL — bypassing db.py, which no
longer talks to Postgres after the R2 migration — and dumps all 3 tables to
a timestamped local backup under data/postgres_backup_<timestamp>/. If the
database is unreachable (already fully expired), prints a clear message and
exits 0 without touching anything else; this is safe to run even if the DB
is already gone.

Usage:
    python backup_expired_postgres.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ℹ️  DATABASE_URL not set locally — nothing to back up from here.")
        print("    Run this with the Render DATABASE_URL set in the environment.")
        return

    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError:
        print("❌ psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)

    print("=" * 60)
    print("Attempting to connect to (possibly expired) Postgres database")
    print("=" * 60)

    try:
        conn = psycopg2.connect(db_url, connect_timeout=10)
    except Exception as e:
        print(f"⚠️  Could not connect: {type(e).__name__}: {e}")
        print("    Database is likely already fully expired. Nothing to recover.")
        return

    print("✓ Connected — pulling data out before it's gone.")

    out_dir = (
        Path(__file__).resolve().parent
        / "data"
        / f"postgres_backup_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    def _serialize(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    def _dump_table(table: str, columns: list[str]) -> int:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"SELECT {', '.join(columns)} FROM {table}")
                rows = cur.fetchall()
        except Exception as e:
            print(f"⚠️  Failed to read table '{table}' (may not exist): {e}")
            return 0

        records = [{k: _serialize(v) for k, v in dict(row).items()} for row in rows]
        out_path = out_dir / f"{table}.json"
        out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"✓ Backed up {len(records)} rows from '{table}' -> {out_path}")
        return len(records)

    manual_count = _dump_table(
        "manual_profiles",
        ["player_name", "profile_type", "season_suffix", "season_label", "stats"],
    )
    lineup_count = _dump_table(
        "team_lineups",
        [
            "team_name", "formation", "lineup", "bench", "prime_player", "peak_season",
            "finalized", "finalized_at", "finalized_round", "finalized_round_label",
            "finalized_snapshot", "updated_at",
        ],
    )
    seed_count = _dump_table("seed_seasons", ["player_id", "season_suffix", "stats"])

    conn.close()

    print()
    print("=" * 60)
    print(f"Backup complete: {out_dir}")
    print(f"  - manual_profiles: {manual_count} rows")
    print(f"  - team_lineups: {lineup_count} rows")
    print(f"  - seed_seasons: {seed_count} rows")
    print("=" * 60)
    print()
    print("Next step: review the backup, merge anything real into the local")
    print("data/*.json fallback files if needed, then run migrate_to_db.py")
    print("(now R2-backed) to push it into R2.")


if __name__ == "__main__":
    main()
