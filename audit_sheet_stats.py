#!/usr/bin/env python3
"""Audit stats coverage for all players on Google Sheet teams."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from google_sheets_teams import fetch_teams_dataframe, parse_teams_from_dataframe
from player_names import ALIASES, normalize_key, resolve_player_name
from sofascore_client import StatsStore

ROOT = Path(__file__).resolve().parent
OUT_PATH = ROOT / "data" / "sheet_stats_audit.json"


def _is_placeholder_stats(data: dict) -> bool:
    """Detect cached_stats_map fallback: MF-only stub with no real data."""
    pos = data.get("primary_position", "MF")
    positions = data.get("positions") or [pos]
    minutes = float(data.get("minutes", 0) or 0)
    games = int(data.get("games", 0) or 0)
    seasons = data.get("seasons_used") or []
    team = (data.get("team") or "").strip()
    return (
        pos == "MF"
        and positions == ["MF"]
        and minutes == 0
        and games == 0
        and not seasons
        and not team
    )


def _ambiguous_matches(raw: str, store: StatsStore) -> list[str]:
    key = normalize_key(raw)
    matches = [
        name
        for name in store.players
        if normalize_key(name).startswith(key) or key.startswith(normalize_key(name))
    ]
    return sorted(set(matches))


def _classify_player(raw: str, store: StatsStore) -> dict:
    key = normalize_key(raw)
    alias_hit = key in ALIASES
    alias_target = ALIASES.get(key)

    try:
        resolved = resolve_player_name(raw, store)
    except ValueError as exc:
        return {
            "raw": raw,
            "status": "resolve_error",
            "error": str(exc),
            "alias_hit": alias_hit,
        }

    cached_name = store._find_cached_player_name(raw)
    cache_data = store._cache.get("players", {}).get(cached_name, {}) if cached_name else {}

    ambiguous = _ambiguous_matches(raw, store) if not alias_hit and not cached_name else []
    # Flag when prefix logic would have multiple candidates and we didn't alias
    if len(ambiguous) > 1 and cached_name is None:
        ambiguous_flag = True
    elif len(ambiguous) > 1 and cached_name and cached_name not in ambiguous:
        ambiguous_flag = False
    else:
        ambiguous_flag = len(ambiguous) > 1 and not alias_hit

    if cached_name is None:
        status = "missing"
        if alias_hit and alias_target and alias_target not in store.players:
            status = "alias_not_in_cache"
        elif ambiguous_flag:
            status = "ambiguous_missing"
        elif resolved == raw.strip() and not alias_hit:
            status = "unresolved_missing"
    elif _is_placeholder_stats(cache_data):
        status = "weak_placeholder"
    elif float(cache_data.get("minutes", 0) or 0) <= 0 and int(cache_data.get("games", 0) or 0) <= 0:
        status = "weak_no_minutes"
    else:
        status = "full"

    return {
        "raw": raw,
        "resolved": resolved,
        "cached_as": cached_name,
        "status": status,
        "alias_hit": alias_hit,
        "alias_target": alias_target,
        "ambiguous_candidates": ambiguous if ambiguous_flag else [],
        "team": cache_data.get("team", ""),
        "position": cache_data.get("primary_position", ""),
        "minutes": cache_data.get("minutes", 0),
        "games": cache_data.get("games", 0),
    }


def main() -> int:
    print("Fetching Google Sheet teams...", flush=True)
    df = fetch_teams_dataframe()
    rosters = parse_teams_from_dataframe(df)
    store = StatsStore()

    team_reports: list[dict] = []
    all_raw: dict[str, dict] = {}  # raw -> classification (first seen)

    for roster in sorted(rosters.values(), key=lambda r: r.name.lower()):
        team_missing: list[dict] = []
        for raw in roster.players:
            info = _classify_player(raw, store)
            if info["raw"] not in all_raw:
                all_raw[info["raw"]] = info
            if info["status"] != "full":
                team_missing.append(info)

        team_reports.append(
            {
                "team": roster.name,
                "player_count": len(roster.players),
                "full_count": len(roster.players) - len(team_missing),
                "missing_count": len(team_missing),
                "missing_players": team_missing,
            }
        )

    unique = list(all_raw.values())
    full = [p for p in unique if p["status"] == "full"]
    missing = [p for p in unique if p["status"] != "full"]
    alias_failures = [
        p for p in unique
        if p.get("alias_hit") and p["status"] != "full"
    ]
    nickname_failures = [
        p for p in unique
        if not p.get("alias_hit")
        and p["status"] in ("unresolved_missing", "ambiguous_missing", "missing")
        and len(p["raw"].split()) <= 2
    ]
    ambiguous = [p for p in unique if p.get("ambiguous_candidates")]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sheet_teams": len(rosters),
        "total_unique_players": len(unique),
        "full_stats_count": len(full),
        "missing_or_weak_count": len(missing),
        "alias_failures_count": len(alias_failures),
        "nickname_failures_count": len(nickname_failures),
        "ambiguous_count": len(ambiguous),
        "teams": team_reports,
        "missing_or_weak": missing,
        "alias_failures": alias_failures,
        "nickname_failures": nickname_failures,
        "ambiguous": ambiguous,
        "full_players": [{"raw": p["raw"], "cached_as": p.get("cached_as")} for p in full],
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n=== Sheet Stats Audit ===")
    print(f"Teams on sheet:        {summary['sheet_teams']}")
    print(f"Unique players:        {summary['total_unique_players']}")
    print(f"Full stats in cache:   {summary['full_stats_count']}")
    print(f"Missing / weak:        {summary['missing_or_weak_count']}")
    print(f"Alias failures:        {summary['alias_failures_count']}")
    print(f"Nickname failures:     {summary['nickname_failures_count']}")
    print(f"Ambiguous matches:     {summary['ambiguous_count']}")
    print(f"\nWritten to: {OUT_PATH}")

    print("\n--- Per-team breakdown ---")
    for t in team_reports:
        flag = "OK" if t["missing_count"] == 0 else f"{t['missing_count']} missing"
        print(f"  {t['team']}: {t['player_count']} players — {flag}")

    if missing:
        print("\n--- Missing / weak players ---")
        for p in sorted(missing, key=lambda x: (x["status"], x["raw"].lower())):
            extra = ""
            if p.get("cached_as"):
                extra = f" -> {p['cached_as']}"
            elif p.get("resolved"):
                extra = f" (resolved: {p['resolved']})"
            amb = p.get("ambiguous_candidates") or []
            amb_txt = f" [candidates: {', '.join(amb[:5])}]" if amb else ""
            print(f"  [{p['status']}] {p['raw']}{extra}{amb_txt}")

    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
