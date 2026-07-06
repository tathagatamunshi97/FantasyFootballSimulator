#!/usr/bin/env python3
"""Enrich player positions in player_stats_cache.json from multi-source history."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fbref_client import fetch_fbref_season_index, lookup_fbref_player, season_label_from_suffix
from player_names import (
    KNOWN_PLAYER_POSITIONS,
    KNOWN_PLAYER_PRIMARY,
    canonical_name,
    known_sofascore_id,
    normalize_key,
)
from position_enrichment import enrich_entry_positions, positions_changed
from sofascore_client import StatsStore, load_cache, save_cache

ROOT = Path(__file__).resolve().parent
AUDIT_PATH = ROOT / "data" / "sheet_stats_audit.json"
MANUAL_PROFILES_PATH = ROOT / "data" / "manual_profiles.json"
SEED_PLAYERS_PATH = ROOT / "data" / "seed_players.json"
SEED_SEASONS_PATH = ROOT / "data" / "seed_seasons.json"
REPORT_PATH = ROOT / "data" / "position_enrichment_report.json"


def suffix_from_season_label(label: str) -> str:
    parts = str(label).split("-")
    if len(parts) != 2:
        return ""
    start = int(parts[0])
    yy = start % 100
    ny = (start + 1) % 100
    return f"{yy:02d}/{ny:02d}"


def _load_sheet_players() -> list[dict[str, str]]:
    if AUDIT_PATH.exists():
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        rows = audit.get("full_players") or []
        if rows:
            return rows
    try:
        from google_sheets_teams import fetch_teams_dataframe, parse_teams_from_dataframe
        from update_sheet_stats import _collect_sheet_players

        df = fetch_teams_dataframe()
        rosters = parse_teams_from_dataframe(df)
        return [{"raw": name, "cached_as": name} for name in _collect_sheet_players(rosters)]
    except Exception:
        return []


def _index_manual_profiles() -> dict[str, list[dict[str, Any]]]:
    if not MANUAL_PROFILES_PATH.exists():
        return {}
    payload = json.loads(MANUAL_PROFILES_PATH.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for profile in payload.get("profiles", []):
        key = normalize_key(profile.get("player_name", ""))
        stats = profile.get("stats") or {}
        if stats:
            out[key].append(stats)
    return out


def _index_seed_players() -> dict[str, dict[str, Any]]:
    if not SEED_PLAYERS_PATH.exists():
        return {}
    payload = json.loads(SEED_PLAYERS_PATH.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for name, stats in (payload.get("players") or {}).items():
        out[normalize_key(name)] = stats
        pid = stats.get("player_id")
        if pid:
            out[f"id:{pid}"] = stats
    return out


def _index_seed_seasons() -> dict[int, list[dict[str, Any]]]:
    if not SEED_SEASONS_PATH.exists():
        return {}
    payload = json.loads(SEED_SEASONS_PATH.read_text(encoding="utf-8"))
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for pid_raw, seasons in payload.items():
        try:
            pid = int(pid_raw)
        except (TypeError, ValueError):
            continue
        for stats in seasons.values():
            if isinstance(stats, dict):
                out[pid].append(stats)
    return out


def _season_league_pairs(
    entry: dict[str, Any],
    player_id: int | None,
    manual_stats: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    league = str(entry.get("league") or "").strip()
    for label in entry.get("seasons_used") or []:
        suffix = suffix_from_season_label(str(label))
        if suffix and league:
            pairs.add((suffix, league))
    if player_id:
        from player_names import KNOWN_SEASON_CONTEXT

        for suffix, ctx in KNOWN_SEASON_CONTEXT.get(player_id, {}).items():
            if ctx.get("league"):
                pairs.add((suffix, str(ctx["league"])))
    for stats in manual_stats:
        suffix = ""
        for label in stats.get("seasons_used") or []:
            suffix = suffix_from_season_label(str(label))
        if not suffix and stats.get("season_profile"):
            suffix = suffix_from_season_label(str(stats["season_profile"]))
        league_name = str(stats.get("league") or league).strip()
        if suffix and league_name:
            pairs.add((suffix, league_name))
    teams_by_season = entry.get("teams_by_season") or {}
    for label in entry.get("seasons_used") or []:
        suffix = suffix_from_season_label(str(label))
        if suffix and not league and teams_by_season.get(label):
            # league may be missing; caller will skip unresolved leagues
            pass
    return sorted(pairs)


def _build_fbref_indexes(
    pairs: set[tuple[str, str]],
    *,
    use_fbref: bool,
) -> dict[tuple[str, str], dict[tuple[str, str], dict[str, Any]]]:
    indexes: dict[tuple[str, str], dict[tuple[str, str], dict[str, Any]]] = {}
    if not use_fbref:
        return indexes
    for suffix, league in sorted(pairs):
        key = (suffix, league)
        if key in indexes:
            continue
        try:
            indexes[key] = fetch_fbref_season_index(suffix, league=league)
            print(f"  FBref index loaded: {league} {suffix} ({len(indexes[key])} rows)", flush=True)
        except Exception as exc:
            print(f"  FBref index skip {league} {suffix}: {exc}", flush=True)
            indexes[key] = {}
    return indexes


def _fbref_hits_for_player(
    display_name: str,
    entry: dict[str, Any],
    pairs: list[tuple[str, str]],
    indexes: dict[tuple[str, str], dict[tuple[str, str], dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    hits: list[tuple[str, dict[str, Any]]] = []
    team = str(entry.get("team") or "")
    teams_by_season = entry.get("teams_by_season") or {}
    for suffix, league in pairs:
        index = indexes.get((suffix, league)) or {}
        if not index:
            continue
        season_label = season_label_from_suffix(suffix)
        lookup_team = teams_by_season.get(season_label, team)
        hit = lookup_fbref_player(index, display_name, lookup_team)
        if hit is None and lookup_team != team:
            hit = lookup_fbref_player(index, display_name, team)
        if hit:
            hits.append((season_label, hit))
    return hits


def _weak_position_data(entry: dict[str, Any]) -> bool:
    positions = entry.get("positions") or []
    primary = str(entry.get("primary_position", ""))
    if len(positions) <= 1 and primary in {"CM", "CB", "MF"}:
        return True
    if primary == "CM" and entry.get("fpl_position") == "DEF":
        return True
    return False


def enrich_all(*, use_fbref: bool = True, dry_run: bool = False) -> dict[str, Any]:
    sheet_rows = _load_sheet_players()
    if not sheet_rows:
        raise RuntimeError("No sheet players found (audit file missing and sheet fetch failed)")

    manual_by_name = _index_manual_profiles()
    seed_by_key = _index_seed_players()
    seed_seasons_by_id = _index_seed_seasons()
    store = StatsStore()
    cache = store._cache

    all_pairs: set[tuple[str, str]] = set()
    player_jobs: list[dict[str, Any]] = []

    for row in sheet_rows:
        raw = row.get("raw", "")
        cached_as = row.get("cached_as") or store._find_cached_player_name(raw)
        if not cached_as:
            player_jobs.append({"raw": raw, "cached_as": None, "entry": None})
            continue
        entry = dict((cache.get("players") or {}).get(cached_as, {}))
        if not entry:
            player_jobs.append({"raw": raw, "cached_as": cached_as, "entry": None})
            continue
        display = canonical_name(cached_as)
        pid = entry.get("player_id") or known_sofascore_id(display) or known_sofascore_id(raw)
        if pid is not None:
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                pid = None
        manual_stats = manual_by_name.get(normalize_key(display), [])
        pairs = _season_league_pairs(entry, pid, manual_stats)
        all_pairs.update(pairs)
        player_jobs.append(
            {
                "raw": raw,
                "cached_as": cached_as,
                "display": display,
                "entry": entry,
                "player_id": pid,
                "manual_stats": manual_stats,
                "pairs": pairs,
            }
        )

    print(f"Building FBref indexes for {len(all_pairs)} season/league pairs...", flush=True)
    fbref_indexes = _build_fbref_indexes(all_pairs, use_fbref=use_fbref)

    updates: list[dict[str, Any]] = []
    weak_after: list[dict[str, str]] = []

    for job in player_jobs:
        cached_as = job.get("cached_as")
        entry = job.get("entry")
        if not cached_as or not entry:
            updates.append({"raw": job["raw"], "status": "missing_cache"})
            continue

        pid = job.get("player_id")
        known_override = KNOWN_PLAYER_PRIMARY.get(pid) if pid else None
        seed_entry = seed_by_key.get(f"id:{pid}") if pid else None
        if seed_entry is None:
            seed_entry = seed_by_key.get(normalize_key(job.get("display", cached_as)))
        seed_season_entries = seed_seasons_by_id.get(pid, []) if pid else []
        sofascore_bucket = KNOWN_PLAYER_POSITIONS.get(pid) if pid else None

        fbref_hits = _fbref_hits_for_player(
            job.get("display", cached_as),
            entry,
            job.get("pairs", []),
            fbref_indexes,
        )

        before = {
            "primary_position": entry.get("primary_position"),
            "fpl_position": entry.get("fpl_position"),
            "positions": list(entry.get("positions") or []),
        }
        enriched = enrich_entry_positions(
            entry,
            manual_stats=job.get("manual_stats"),
            seed_entry=seed_entry,
            seed_season_entries=seed_season_entries,
            fbref_season_hits=fbref_hits,
            sofascore_bucket=sofascore_bucket,
            known_override=known_override,
        )
        after = {
            "primary_position": enriched["primary_position"],
            "fpl_position": enriched["fpl_position"],
            "positions": enriched["positions"],
        }

        changed = positions_changed(before, after)
        if changed and not dry_run:
            entry.update(enriched)
            cache.setdefault("players", {})[cached_as] = entry

        record = {
            "raw": job["raw"],
            "cached_as": cached_as,
            "player_id": pid,
            "changed": changed,
            "before": before,
            "after": after,
            "fbref_seasons": len(fbref_hits),
            "sources": {
                "manual_profiles": len(job.get("manual_stats") or []),
                "seed_player": bool(seed_entry),
                "seed_seasons": len(seed_season_entries),
                "known_override": bool(known_override),
                "sofascore_bucket": sofascore_bucket,
            },
        }
        updates.append(record)
        if _weak_position_data(after):
            weak_after.append({"raw": job["raw"], "cached_as": cached_as, **after})

    changed_count = sum(1 for u in updates if u.get("changed"))
    if not dry_run and changed_count:
        meta = cache.setdefault("meta", {})
        meta["position_enriched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        save_cache(cache, store.cache_path)
        store.reload()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "use_fbref": use_fbref,
        "sheet_players": len(sheet_rows),
        "updated_count": changed_count,
        "unchanged_count": len(updates) - changed_count,
        "missing_cache_count": sum(1 for u in updates if u.get("status") == "missing_cache"),
        "weak_after_count": len(weak_after),
        "weak_after": weak_after,
        "sample_updates": [u for u in updates if u.get("changed")][:10],
        "updates": updates,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich player positions from multi-source history")
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not write cache")
    parser.add_argument("--skip-fbref", action="store_true", help="Cache/seed/manual only (no FBref fetch)")
    args = parser.parse_args()

    report = enrich_all(use_fbref=not args.skip_fbref, dry_run=args.dry_run)
    print("\n=== Position Enrichment Report ===")
    print(f"Sheet players:     {report['sheet_players']}")
    print(f"Updated:           {report['updated_count']}")
    print(f"Unchanged:         {report['unchanged_count']}")
    print(f"Missing cache:     {report['missing_cache_count']}")
    print(f"Weak after:        {report['weak_after_count']}")
    print(f"Report:            {REPORT_PATH}")

    samples = [
        u for u in report["updates"]
        if u.get("cached_as") in {"Ángel Di María", "Rodri", "Marc Cucurella", "Rúben Dias", "Reece James"}
        or u.get("raw") in {"Angel Di Maria", "Rodri", "Cucurella", "Ruben Dias", "Reece James"}
    ]
    if samples:
        print("\n--- Sample before/after ---")
        for row in samples:
            print(f"{row.get('cached_as') or row.get('raw')}:")
            print(f"  before: {row.get('before')}")
            print(f"  after:  {row.get('after')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
