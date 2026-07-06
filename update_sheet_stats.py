#!/usr/bin/env python3
"""Audit Google Sheet player stats and update missing / weak cache entries."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from audit_sheet_stats import OUT_PATH as AUDIT_PATH, _classify_player, _is_placeholder_stats
from google_sheets_teams import fetch_teams_dataframe, parse_teams_from_dataframe
from player_names import ALIASES, normalize_key
from sofascore_client import StatsStore, merge_seed_players, save_cache
from seasonal_stats import fetch_best_historical_stats

ROOT = Path(__file__).resolve().parent
REPORT_PATH = ROOT / "data" / "sheet_stats_update_report.json"


def _collect_sheet_players(rosters: dict) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for roster in rosters.values():
        for raw in roster.players:
            key = str(raw).strip()
            if key and key not in seen:
                seen.add(key)
                names.append(key)
    return sorted(names, key=str.lower)


def _purge_placeholder(store: StatsStore, raw: str) -> bool:
    """Remove stub cache entry so fetch can retry from seed / APIs."""
    cached = store._find_cached_player_name(raw)
    if not cached:
        return False
    data = (store._cache.get("players") or {}).get(cached, {})
    if not _is_placeholder_stats(data):
        return False
    store._cache.get("players", {}).pop(cached, None)
    store._players.pop(cached, None)
    store._norm_index.pop(normalize_key(cached), None)
    meta = store._cache.setdefault("meta", {})
    meta["player_count"] = len(store._cache.get("players", {}))
    meta["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_cache(store._cache, store.cache_path)
    return True


def _try_update_player(store: StatsStore, raw: str) -> dict:
    before = _classify_player(raw, store)
    if before["status"] == "full":
        return {"raw": raw, "action": "skipped_ok", "before": before["status"], "after": "full"}

    purged = _purge_placeholder(store, raw)
    if purged:
        if merge_seed_players(store._cache):
            save_cache(store._cache, store.cache_path)
        store.reload()

    source = "cache"
    error = ""
    try:
        cached_key = store.ensure_one(raw)
        after_info = _classify_player(raw, store)
        if after_info["status"] == "full":
            source = "seed" if purged else "ensure_one"
            return {
                "raw": raw,
                "action": "updated",
                "before": before["status"],
                "after": after_info["status"],
                "cached_as": cached_key,
                "source": source,
            }

        if purged or after_info["status"] in ("weak_placeholder", "weak_no_minutes", "missing"):
            _purge_placeholder(store, raw)
            store.reload()
            _, blended = fetch_best_historical_stats(raw)
            cache_key = blended.get("player_name") or raw
            from understat_client import merge_understat_into_players

            merge_understat_into_players({cache_key: blended})
            store._add_player_to_cache(cache_key, blended)
            after_info = _classify_player(raw, store)
            if after_info["status"] == "full":
                return {
                    "raw": raw,
                    "action": "updated",
                    "before": before["status"],
                    "after": after_info["status"],
                    "cached_as": cache_key,
                    "source": "historical",
                }
    except Exception as exc:
        error = str(exc)

    after_info = _classify_player(raw, store)
    return {
        "raw": raw,
        "action": "failed" if after_info["status"] != "full" else "updated",
        "before": before["status"],
        "after": after_info["status"],
        "cached_as": after_info.get("cached_as"),
        "source": source,
        "error": error,
    }


def main() -> int:
    print("Fetching Google Sheet teams...", flush=True)
    df = fetch_teams_dataframe()
    rosters = parse_teams_from_dataframe(df)
    players = _collect_sheet_players(rosters)
    store = StatsStore()

    before_all = [_classify_player(raw, store) for raw in players]
    before_full = sum(1 for p in before_all if p["status"] == "full")
    before_missing = [p for p in before_all if p["status"] != "full"]

    print(f"\nBefore: {before_full}/{len(players)} players with full stats", flush=True)
    if before_missing:
        print("Players needing update:", flush=True)
        for p in before_missing:
            print(f"  [{p['status']}] {p['raw']}", flush=True)

    updates: list[dict] = []
    for raw in players:
        info = before_all[players.index(raw)] if raw in players else _classify_player(raw, store)
        if info["status"] == "full":
            continue
        print(f"\nUpdating: {raw}", flush=True)
        result = _try_update_player(store, raw)
        updates.append(result)
        print(
            f"  -> {result['action']} ({result.get('before')} -> {result.get('after')})"
            f"{': ' + result['error'] if result.get('error') else ''}",
            flush=True,
        )

    store.reload()
    after_all = [_classify_player(raw, StatsStore()) for raw in players]
    after_full = sum(1 for p in after_all if p["status"] == "full")
    still_missing = [p for p in after_all if p["status"] != "full"]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sheet_teams": len(rosters),
        "total_unique_players": len(players),
        "before_full_count": before_full,
        "after_full_count": after_full,
        "fixed_count": sum(1 for u in updates if u.get("action") == "updated"),
        "still_missing_count": len(still_missing),
        "updates": updates,
        "still_missing": still_missing,
        "aliases_in_use": [
            {"raw": raw, "target": ALIASES[normalize_key(raw)]}
            for raw in players
            if normalize_key(raw) in ALIASES
        ],
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Estimate missing Understat fields and enforce minimum ratings in cache
    from understat_estimation import apply_estimates_to_cache

    sheet_cached = {
        store._find_cached_player_name(raw) or raw for raw in players
    }
    est_report = apply_estimates_to_cache(store._cache, sheet_names=sheet_cached)
    save_cache(store._cache, store.cache_path)
    store.reload()
    report["understat_estimation"] = {
        "understat_fixed": est_report["understat_fixed"],
        "rating_fixed": est_report["rating_fixed"],
        "ratios": {k: round(v, 4) for k, v in est_report["ratios"].items()},
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Refresh audit artifacts
    from audit_sheet_stats import main as audit_main
    from audit_zero_stats import main as zero_audit_main

    audit_main()
    zero_audit_main()

    print(f"\n=== Sheet Stats Update Report ===")
    print(f"Teams on sheet:        {report['sheet_teams']}")
    print(f"Unique players:        {report['total_unique_players']}")
    print(f"Full stats before:     {report['before_full_count']}")
    print(f"Full stats after:      {report['after_full_count']}")
    print(f"Fixed this run:        {report['fixed_count']}")
    print(f"Understat estimated:   {report['understat_estimation']['understat_fixed']}")
    print(f"Rating defaults:       {report['understat_estimation']['rating_fixed']}")
    print(f"Still missing / weak:  {report['still_missing_count']}")
    print(f"\nWritten to: {REPORT_PATH}")
    print(f"Audit refreshed: {AUDIT_PATH}")

    if still_missing:
        print("\n--- Still missing / weak ---")
        for p in still_missing:
            print(f"  [{p['status']}] {p['raw']}")

    return 0 if not still_missing else 1


if __name__ == "__main__":
    sys.exit(main())
