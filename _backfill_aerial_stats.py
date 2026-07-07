"""Backfill FBref aerial/defence fields into player_stats_cache.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fbref_client import FBREF_STAT_KEYS, merge_fbref_for_player_season, season_label_from_suffix
from models import _normalize_stat_gaps

DATA_DIR = Path(__file__).resolve().parent / "data"
CACHE_FILE = DATA_DIR / "player_stats_cache.json"

VERIFY_PLAYERS = (
    "Harry Maguire",
    "Dayot Upamecano",
    "João Palhinha",
)

AERIAL_KEYS = (
    "clearances90",
    "blocks90",
    "ball_recoveries90",
    "aerials_won90",
    "aerials_lost90",
    "aerials_won_pct",
    "aerials_source",
)


def _season_suffixes(entry: dict) -> list[str]:
    out: list[str] = []
    for label in entry.get("seasons_used") or []:
        parts = str(label).split("-")
        if len(parts) != 2:
            continue
        start = int(parts[0])
        yy = start % 100
        out.append(f"{yy:02d}/{(start + 1) % 100:02d}")
    return out


def backfill(
    *,
    names: tuple[str, ...] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    players: dict[str, dict] = payload.get("players") or payload
    targets = list(names) if names else list(players.keys())
    if limit is not None:
        targets = targets[:limit]

    updated = 0
    samples: list[dict] = []
    for name in targets:
        entry = players.get(name)
        if not entry:
            continue
        before = {k: entry.get(k) for k in AERIAL_KEYS}
        for suffix in _season_suffixes(entry) or ["24/25"]:
            merge_fbref_for_player_season(name, entry, suffix, overwrite_zeros=True)
        _normalize_stat_gaps(entry)
        after = {k: entry.get(k) for k in AERIAL_KEYS}
        if after != before:
            updated += 1
        if name in VERIFY_PLAYERS:
            samples.append({"player": name, **after})

    if not dry_run:
        if "players" in payload:
            payload["players"] = players
            CACHE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            CACHE_FILE.write_text(json.dumps(players, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"updated": updated, "checked": len(targets), "samples": samples, "dry_run": dry_run}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--players", nargs="*", default=None)
    args = parser.parse_args()
    report = backfill(names=tuple(args.players) if args.players else None, limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
