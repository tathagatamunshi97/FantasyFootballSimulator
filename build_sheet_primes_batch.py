"""Build cache-only prime profiles for all sheet players missing primes."""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from manual_profiles import MANUAL_PROFILES_FILE, lookup_manual_prime, reload_manual_profiles
from models import _normalize_stat_gaps
from player_names import (
    canonical_name,
    known_display_name,
    known_sofascore_id,
    normalize_key,
)
from populate_manual_profiles import _make_profile
from seasonal_stats import normalize_season_input, season_label_from_suffix
from sofascore_client import StatsStore, load_cache

DATA_DIR = Path(__file__).resolve().parent / "data"
SEED_SEASONS_FILE = DATA_DIR / "seed_seasons.json"
REPORT_FILE = DATA_DIR / "_sheet_prime_batch_report.json"


def _profile_key(profile: dict[str, Any]) -> tuple[str, str, str]:
    return (
        normalize_key(canonical_name(profile["player_name"])),
        normalize_key(str(profile.get("profile_type", "")).replace("_", " ")),
        str(profile["season_suffix"]),
    )


def _label_to_suffix(label: str) -> str | None:
    label = str(label).strip()
    m = re.match(r"^(\d{4})-(\d{4})$", label)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if b == a + 1:
            return f"{a % 100:02d}/{b % 100:02d}"
    try:
        return normalize_season_input(label)
    except Exception:
        return None


def _pick_prime_season_label(entry: dict[str, Any]) -> str:
    seasons = [str(s) for s in (entry.get("seasons_used") or []) if s]
    if not seasons:
        return "2024-2025"
    # Prefer last completed season (avoid in-progress 2025-2026 when older exists).
    completed = [s for s in seasons if not s.startswith("2025-")]
    if completed:
        return sorted(completed)[-1]
    return sorted(seasons)[-1]


def _seed_entry_from_stats(stats: dict[str, Any], display_name: str) -> dict[str, Any]:
    entry = {
        k: v
        for k, v in stats.items()
        if k
        not in {
            "stat_profile",
            "prime_season",
            "manual_profile_type",
            "manual_season_suffix",
            "auto_populate_source",
        }
    }
    entry["player_name"] = display_name
    entry.setdefault("stat_profile", "seeded_season")
    return entry


def _load_sheet_players() -> list[str]:
    from google_sheets_teams import list_sheet_teams

    names: list[str] = []
    seen: set[str] = set()
    for t in list_sheet_teams():
        for p in t.get("players") or []:
            raw = str(p).strip()
            if not raw:
                continue
            key = normalize_key(canonical_name(raw))
            if key in seen:
                continue
            seen.add(key)
            names.append(raw)
    return names


def build() -> dict[str, Any]:
    reload_manual_profiles()
    store = StatsStore()
    cache = load_cache()
    players_cache: dict[str, Any] = cache.get("players") or {}

    payload = json.loads(MANUAL_PROFILES_FILE.read_text(encoding="utf-8"))
    profiles: list[dict[str, Any]] = list(payload.get("profiles") or [])
    index = {_profile_key(p): i for i, p in enumerate(profiles)}

    seed: dict[str, Any] = {}
    if SEED_SEASONS_FILE.exists():
        seed = json.loads(SEED_SEASONS_FILE.read_text(encoding="utf-8"))

    report: dict[str, Any] = {"ok": [], "skipped": [], "failed": []}
    sheet_players = _load_sheet_players()
    print(f"Sheet unique players: {len(sheet_players)}")

    for raw in sheet_players:
        if lookup_manual_prime(raw, cache_only=True):
            report["skipped"].append({"player": raw, "reason": "prime exists"})
            continue

        cached_name = store._find_cached_player_name(raw)
        if not cached_name or cached_name not in players_cache:
            report["failed"].append({"player": raw, "error": "not in player_stats_cache"})
            print(f"FAIL {raw.encode('ascii', 'replace').decode()}: not in cache")
            continue

        entry = copy.deepcopy(players_cache[cached_name])
        label = _pick_prime_season_label(entry)
        suffix = _label_to_suffix(label)
        if not suffix:
            report["failed"].append({"player": raw, "error": f"bad season label {label}"})
            continue

        display = known_display_name(raw) or cached_name or canonical_name(raw)
        pid = entry.get("player_id") or known_sofascore_id(raw) or store.cached_player_id(raw)
        if pid:
            entry["player_id"] = int(pid)

        # Narrow teams_by_season / seasons_used to the chosen prime season.
        entry["seasons_used"] = [label]
        tbs = entry.get("teams_by_season") or {}
        if isinstance(tbs, dict) and label in tbs:
            entry["teams_by_season"] = {label: tbs[label]}
        elif isinstance(tbs, dict) and tbs:
            # keep first matching-ish
            entry["teams_by_season"] = {label: next(iter(tbs.values()))}
        else:
            entry["teams_by_season"] = {label: entry.get("team", "")}
        entry["season_profile"] = label
        entry["data_source"] = "player_stats_cache"
        entry["auto_populate_source"] = "player_stats_cache"

        # Write repaired gap fills into the stored prime (not runtime-only).
        _normalize_stat_gaps(entry)
        entry["stat_gaps_backfilled"] = True

        key = (normalize_key(canonical_name(display)), "prime", suffix)
        if key in index or lookup_manual_prime(display, cache_only=True):
            report["skipped"].append({"player": display, "reason": "key exists"})
            continue

        profile = _make_profile(display, "prime", suffix, entry)
        profiles.append(profile)
        index[_profile_key(profile)] = len(profiles) - 1

        if pid:
            seed.setdefault(str(int(pid)), {})[suffix] = _seed_entry_from_stats(entry, display)

        report["ok"].append(
            {
                "player": display,
                "raw": raw,
                "season": suffix,
                "minutes": entry.get("minutes"),
                "pos": entry.get("primary_position"),
                "player_id": pid,
            }
        )
        print(
            f"OK {display.encode('ascii', 'replace').decode()} {suffix} "
            f"min={entry.get('minutes')} pos={entry.get('primary_position')}"
        )

    payload["profiles"] = profiles
    payload["sheet_prime_batch_report"] = {
        "ok_count": len(report["ok"]),
        "fail_count": len(report["failed"]),
        "skip_count": len(report["skipped"]),
        "failed": report["failed"],
    }
    MANUAL_PROFILES_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    SEED_SEASONS_FILE.write_text(json.dumps(seed, indent=2, ensure_ascii=False), encoding="utf-8")
    reload_manual_profiles()
    REPORT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


if __name__ == "__main__":
    r = build()
    print(
        f"\nOK={len(r['ok'])} FAIL={len(r['failed'])} SKIP={len(r['skipped'])}"
    )
    if r["failed"]:
        print("FAILED sample:", r["failed"][:20])
