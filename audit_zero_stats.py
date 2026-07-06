#!/usr/bin/env python3
"""Audit sheet players for zero / weak / missing Understat stats."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from audit_sheet_stats import _classify_player, _is_placeholder_stats
from google_sheets_teams import fetch_teams_dataframe, parse_teams_from_dataframe
from sofascore_client import StatsStore
from stats_resolver import prepare_team_player_stats
from update_sheet_stats import _collect_sheet_players

ROOT = Path(__file__).resolve().parent
OUT_PATH = ROOT / "data" / "zero_stats_audit.json"

CORE_FIELDS = (
    "rating",
    "goals90",
    "assists90",
    "xg90",
    "xa90",
    "key_passes90",
    "dribbles90",
    "tackles90",
    "interceptions90",
)

UNDERSTAT_FIELDS = (
    "understat_xg90",
    "understat_xa90",
    "understat_key_passes90",
    "understat_shots90",
)

ALL_TRACKED = CORE_FIELDS + UNDERSTAT_FIELDS


def _zero_fields(data: dict) -> list[str]:
    return [f for f in ALL_TRACKED if float(data.get(f, 0) or 0) == 0]


def _audit_player(raw: str, store: StatsStore) -> dict:
    info = _classify_player(raw, store)
    cached = info.get("cached_as") or raw
    data = store._cache.get("players", {}).get(cached, {})
    zeros = _zero_fields(data) if data else ALL_TRACKED
    core_zeros = [f for f in zeros if f in CORE_FIELDS]
    us_zeros = [f for f in zeros if f in UNDERSTAT_FIELDS]

    flags: list[str] = []
    if not data:
        flags.append("no_cache")
    if _is_placeholder_stats(data):
        flags.append("stub_profile")
    if float(data.get("rating", 0) or 0) <= 0:
        flags.append("rating_zero")
    if float(data.get("minutes", 0) or 0) <= 0:
        flags.append("minutes_zero")
    if data and all(float(data.get(f, 0) or 0) == 0 for f in ALL_TRACKED[1:]):
        flags.append("all_stats_zero")
    if us_zeros and not data.get("understat_matched") and not data.get("understat_estimated"):
        flags.append("understat_missing")

    cached_map = store.cached_stats_map([raw]).get(raw)
    resolve_weak = bool(
        cached_map and (cached_map.rating <= 0 or cached_map.minutes <= 0)
    )
    if resolve_weak:
        flags.append("cache_only_weak")

    return {
        "raw": raw,
        "resolved": info.get("resolved"),
        "cached_as": cached,
        "status": info.get("status"),
        "flags": flags,
        "zero_fields": zeros,
        "core_zero_count": len(core_zeros),
        "understat_zero_count": len(us_zeros),
        "rating": data.get("rating", 0),
        "minutes": data.get("minutes", 0),
        "understat_matched": data.get("understat_matched", False),
        "understat_estimated": data.get("understat_estimated", False),
        "position": data.get("primary_position", ""),
        "fpl_position": data.get("fpl_position", ""),
    }


def main() -> int:
    print("Fetching Google Sheet teams...", flush=True)
    df = fetch_teams_dataframe()
    rosters = parse_teams_from_dataframe(df)
    players = _collect_sheet_players(rosters)
    store = StatsStore()

    audits = [_audit_player(raw, store) for raw in players]
    flagged = [a for a in audits if a["flags"]]
    rating_zero = [a for a in audits if "rating_zero" in a["flags"]]
    understat_missing = [a for a in audits if "understat_missing" in a["flags"]]
    cache_weak = [a for a in audits if "cache_only_weak" in a["flags"]]
    stubs = [a for a in audits if "stub_profile" in a["flags"]]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sheet_teams": len(rosters),
        "total_unique_players": len(players),
        "flagged_count": len(flagged),
        "rating_zero_count": len(rating_zero),
        "understat_missing_count": len(understat_missing),
        "cache_only_weak_count": len(cache_weak),
        "stub_count": len(stubs),
        "field_zero_totals": {
            f: sum(1 for a in audits if f in a["zero_fields"]) for f in ALL_TRACKED
        },
        "flagged_players": flagged,
        "rating_zero": rating_zero,
        "understat_missing": understat_missing,
        "cache_only_weak": cache_weak,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n=== Zero Stats Audit ===")
    print(f"Sheet players:           {summary['total_unique_players']}")
    print(f"Flagged:                 {summary['flagged_count']}")
    print(f"Rating zero:             {summary['rating_zero_count']}")
    print(f"Understat missing:       {summary['understat_missing_count']}")
    print(f"Cache-only weak resolve: {summary['cache_only_weak_count']}")
    print(f"Stub profiles:           {summary['stub_count']}")
    print(f"\nPer-field zero counts:")
    for f, n in summary["field_zero_totals"].items():
        print(f"  {f}: {n}")
    print(f"\nWritten to: {OUT_PATH}")

    if flagged:
        print("\n--- Flagged players (first 25) ---")
        for p in flagged[:25]:
            print(
                f"  {p['raw']} [{', '.join(p['flags'])}] "
                f"rating={p['rating']} us_est={p.get('understat_estimated')}"
            )

    return 0 if not flagged else 1


if __name__ == "__main__":
    sys.exit(main())
