"""Backfill FotMob aerial/duel % and preferred foot into player_stats_cache.json."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from fotmob_client import FOTMOB_STAT_KEYS, merge_fotmob_for_player
from models import _normalize_stat_gaps

DATA_DIR = Path(__file__).resolve().parent / "data"
CACHE_FILE = DATA_DIR / "player_stats_cache.json"
SHEET_AUDIT_FILE = DATA_DIR / "sheet_stats_audit.json"

VERIFY_PLAYERS = (
    "Harry Maguire",
    "Dayot Upamecano",
    "João Palhinha",
    "Mohamed Salah",
    "Achraf Hakimi",
)


def _atomic_write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, ensure_ascii=False)
    tmp = path.with_suffix(".json.tmp")
    last_err: OSError | None = None
    for attempt in range(3):
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(0.75 * (attempt + 1))
        except OSError as exc:
            if getattr(exc, "winerror", None) in (5, 32):
                last_err = exc
                if attempt < 2:
                    time.sleep(0.75 * (attempt + 1))
                    continue
            raise
    if last_err is not None:
        raise last_err


def _sheet_player_names() -> list[str]:
    if not SHEET_AUDIT_FILE.exists():
        return []
    audit = json.loads(SHEET_AUDIT_FILE.read_text(encoding="utf-8"))
    names = [row.get("cached_as") for row in audit.get("full_players", []) if row.get("cached_as")]
    return sorted(set(names))


def backfill(
    *,
    names: tuple[str, ...] | None = None,
    sheet_only: bool = True,
    limit: int | None = None,
    dry_run: bool = False,
    use_cache: bool = True,
) -> dict:
    payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    players: dict[str, dict] = payload.get("players") or payload

    if names:
        targets = list(names)
    elif sheet_only:
        targets = [n for n in _sheet_player_names() if n in players]
    else:
        targets = list(players.keys())
    if limit is not None:
        targets = targets[:limit]

    matched = 0
    failed: list[str] = []
    samples: list[dict] = []
    for name in targets:
        entry = players.get(name)
        if not entry:
            failed.append(name)
            continue
        before = {k: entry.get(k) for k in FOTMOB_STAT_KEYS}
        ok = merge_fotmob_for_player(name, entry, use_cache=use_cache)
        _normalize_stat_gaps(entry)
        after = {k: entry.get(k) for k in FOTMOB_STAT_KEYS}
        if ok:
            matched += 1
        else:
            failed.append(name)
        if name in VERIFY_PLAYERS or name in {n for n in VERIFY_PLAYERS}:
            samples.append({"player": name, **{k: after.get(k) for k in FOTMOB_STAT_KEYS}})

    if not dry_run:
        if "players" in payload:
            payload["players"] = players
            _atomic_write_json(CACHE_FILE, payload)
        else:
            _atomic_write_json(CACHE_FILE, players)

    return {
        "checked": len(targets),
        "matched": matched,
        "failed_count": len(failed),
        "failed": failed[:50],
        "samples": samples,
        "dry_run": dry_run,
        "sheet_only": sheet_only,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all-cache", action="store_true", help="Backfill every cached player, not just sheet audit list")
    parser.add_argument("--no-cache", action="store_true", help="Ignore data/fotmob_cache.json")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--players", nargs="*", default=None)
    args = parser.parse_args()
    report = backfill(
        names=tuple(args.players) if args.players else None,
        sheet_only=not args.all_cache,
        limit=args.limit,
        dry_run=args.dry_run,
        use_cache=not args.no_cache,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
