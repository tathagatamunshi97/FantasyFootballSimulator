#!/usr/bin/env python3
"""Migrate existing JSON data to PostgreSQL database.

Run this once after setting DATABASE_URL to backfill the database with
existing data from manual_profiles.json, team_lineups.json, and seed_seasons.json.

Usage:
    python migrate_to_db.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import db


def migrate_manual_profiles() -> int:
    """Migrate manual_profiles.json → database."""
    data_dir = Path(__file__).resolve().parent / "data"
    profiles_file = data_dir / "manual_profiles.json"

    if not profiles_file.exists():
        print("ℹ️  manual_profiles.json not found, skipping.")
        return 0

    try:
        payload = json.loads(profiles_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to read manual_profiles.json: {e}")
        return 0

    count = 0
    for row in payload.get("profiles", []):
        if not isinstance(row, dict):
            continue
        player_name = str(row.get("player_name", "")).strip()
        profile_type = str(row.get("profile_type", "")).strip()
        season_suffix = str(row.get("season_suffix", "")).strip()
        season_label = str(row.get("season_label", "")).strip()
        stats = row.get("stats") or {}

        if not (player_name and profile_type and season_suffix):
            continue

        try:
            db.save_manual_profile(player_name, profile_type, season_suffix, season_label, stats)
            count += 1
        except Exception as e:
            print(f"⚠️  Failed to save {player_name}: {e}")

    print(f"✓ Migrated {count} manual profiles to database")
    return count


def migrate_team_lineups() -> int:
    """Migrate team_lineups.json → database."""
    data_dir = Path(__file__).resolve().parent / "data"
    lineups_file = data_dir / "team_lineups.json"

    if not lineups_file.exists():
        print("ℹ️  team_lineups.json not found, skipping.")
        return 0

    try:
        store = json.loads(lineups_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to read team_lineups.json: {e}")
        return 0

    count = 0
    for team_name, lineup_data in store.items():
        try:
            db.save_team_lineup(team_name, lineup_data)
            count += 1
        except Exception as e:
            print(f"⚠️  Failed to save lineup for {team_name}: {e}")

    print(f"✓ Migrated {count} team lineups to database")
    return count


def migrate_seed_seasons() -> int:
    """Migrate seed_seasons.json → database."""
    data_dir = Path(__file__).resolve().parent / "data"
    seed_file = data_dir / "seed_seasons.json"

    if not seed_file.exists():
        print("ℹ️  seed_seasons.json not found, skipping.")
        return 0

    try:
        seed_data = json.loads(seed_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to read seed_seasons.json: {e}")
        return 0

    count = 0
    for pid_str, seasons in seed_data.items():
        try:
            player_id = int(pid_str)
        except (ValueError, TypeError):
            continue

        for season_suffix, stats in seasons.items():
            try:
                db.save_seed_season(player_id, str(season_suffix), stats)
                count += 1
            except Exception as e:
                print(f"⚠️  Failed to save seed for player {player_id} season {season_suffix}: {e}")

    print(f"✓ Migrated {count} seed season entries to database")
    return count


def main() -> None:
    """Run all migrations."""
    print("=" * 60)
    print("Migrating JSON data to PostgreSQL database")
    print("=" * 60)

    try:
        db.init_db()
        print("✓ Database tables initialized")
    except Exception as e:
        print(f"❌ Failed to initialize database: {e}")
        sys.exit(1)

    print()
    manual_count = migrate_manual_profiles()
    print()
    lineups_count = migrate_team_lineups()
    print()
    seed_count = migrate_seed_seasons()

    print()
    print("=" * 60)
    print(f"Migration complete!")
    print(f"  - Manual profiles: {manual_count}")
    print(f"  - Team lineups: {lineups_count}")
    print(f"  - Seed seasons: {seed_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
