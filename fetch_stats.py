#!/usr/bin/env python3
"""Refresh Sofascore player stats cache via datafc."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sofascore_client import DEFAULT_CACHE, LEAGUES, refresh_cache


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Sofascore stats for 2024-25 and 2025-26 (50/50 blend)"
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE,
        help="Output cache path",
    )
    parser.add_argument(
        "--league",
        action="append",
        dest="leagues",
        metavar="LEAGUE",
        help=(
            "League to fetch (repeatable). Default: top 5 European leagues. "
            "Example: --league 'Premier League'"
        ),
    )
    parser.add_argument(
        "--pl-only",
        action="store_true",
        help="Shortcut for --league 'Premier League' only (faster)",
    )
    args = parser.parse_args()

    if args.pl_only:
        leagues = ("Premier League",)
    elif args.leagues:
        leagues = tuple(args.leagues)
    else:
        leagues = LEAGUES

    print(f"Fetching Sofascore: {', '.join(leagues)}")
    print("Seasons: 2024-25 + 2025-26 (equal weight). Sofascore + Understat enrichment.")

    try:
        cache = refresh_cache(cache_path=args.cache, leagues=leagues)
    except RuntimeError as exc:
        print(f"Fetch failed: {exc}", file=sys.stderr)
        sys.exit(1)

    meta = cache.get("meta", {})
    print(f"Updated {args.cache}")
    print(f"  Players: {meta.get('player_count', 0)}")
    print(f"  Seasons: {meta.get('seasons')}")
    print(f"  Leagues: {meta.get('leagues')}")
    print(f"  Source:  {meta.get('source')}")
    if meta.get("fetch_log"):
        for note in meta["fetch_log"]:
            print(f"  {note}")


if __name__ == "__main__":
    main()
