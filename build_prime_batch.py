"""Build cache-only prime profiles for Round 3 prime picks (merge into manual_profiles + seed_seasons)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from manual_profiles import MANUAL_PROFILES_FILE, reload_manual_profiles
from player_names import canonical_name, known_display_name, known_sofascore_id, normalize_key
from populate_manual_profiles import _fetch_season, _make_profile

DATA_DIR = Path(__file__).resolve().parent / "data"
SEED_SEASONS_FILE = DATA_DIR / "seed_seasons.json"

# (lookup_name, prime_suffix, display_name_override)
PRIME_TARGETS: list[tuple[str, str, str | None]] = [
    ("Ruben Dias", "20/21", "Rúben Dias"),
    ("Rodri", "23/24", None),
    ("Cole Palmer", "23/24", None),
    ("Carvajal", "16/17", None),
    ("Casemiro", "17/18", None),
    ("Mohamed Salah", "17/18", None),
    ("Sergio Ramos", "14/15", None),
    ("Antoine Griezmann", "15/16", None),
    ("Antonio Rüdiger", "21/22", None),
    ("Harry Maguire", "18/19", None),
    ("Luka Modrić", "17/18", None),
    ("Aymeric Laporte", "20/21", None),
    ("Manuel Neuer", "13/14", None),
    ("David Alaba", "19/20", "Alaba"),
    ("Kevin De Bruyne", "19/20", None),
]


def _profile_key(profile: dict[str, Any]) -> tuple[str, str, str]:
    return (
        normalize_key(canonical_name(profile["player_name"])),
        normalize_key(str(profile.get("profile_type", "")).replace("_", " ")),
        str(profile["season_suffix"]),
    )


def _load_seed() -> dict[str, dict[str, Any]]:
    if not SEED_SEASONS_FILE.exists():
        return {}
    return json.loads(SEED_SEASONS_FILE.read_text(encoding="utf-8"))


def _seed_entry_from_stats(stats: dict[str, Any], display_name: str) -> dict[str, Any]:
    entry = {k: v for k, v in stats.items() if k not in {"stat_profile", "prime_season", "manual_profile_type", "manual_season_suffix", "auto_populate_source"}}
    entry["player_name"] = display_name
    entry.setdefault("stat_profile", "seeded_season")
    return entry


def build(*, try_sofascore: bool = False) -> dict[str, Any]:
    if not try_sofascore:
        import seasonal_stats as ss
        import sofascore_client as sc

        def _noop(*_a, **_k):
            return None

        ss.fetch_sofascore_season_entry = _noop  # type: ignore[assignment]
        sc._fetch_player_season_via_career_api = _noop  # type: ignore[assignment]

    existing_payload = json.loads(MANUAL_PROFILES_FILE.read_text(encoding="utf-8"))
    profiles: list[dict[str, Any]] = list(existing_payload.get("profiles") or [])
    index = {_profile_key(p): i for i, p in enumerate(profiles)}

    seed = _load_seed()
    report: dict[str, Any] = {"ok": [], "failed": [], "skipped": []}

    for lookup, suffix, display_override in PRIME_TARGETS:
        kid = known_sofascore_id(lookup)
        display = display_override or known_display_name(lookup) or canonical_name(lookup)
        key = (normalize_key(canonical_name(display)), "prime", suffix)
        if key in index:
            report["skipped"].append({"player": display, "season": suffix})
            continue

        result = _fetch_season(lookup, suffix, player_id=kid, display_name=display)
        if result[0] is None:
            report["failed"].append({"player": display, "season": suffix, "error": result[1]})
            print(f"FAIL {display} {suffix}: {result[1]}")
            continue

        name, stats, source = result
        if display_override:
            name = display_override
        profile = _make_profile(name, "prime", suffix, stats)
        profiles.append(profile)
        index[_profile_key(profile)] = len(profiles) - 1

        pid = stats.get("player_id") or kid
        if pid:
            seed.setdefault(str(int(pid)), {})[suffix] = _seed_entry_from_stats(stats, name)

        report["ok"].append({"player": name, "season": suffix, "source": source, "minutes": stats.get("minutes"), "rating": stats.get("rating")})
        print(f"OK {name.encode('ascii', 'replace').decode()} {suffix} src={source} min={stats.get('minutes')} rating={stats.get('rating')}")

        existing_payload["profiles"] = profiles
        existing_payload["prime_batch_report"] = report
        MANUAL_PROFILES_FILE.write_text(json.dumps(existing_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        SEED_SEASONS_FILE.write_text(json.dumps(seed, indent=2, ensure_ascii=False), encoding="utf-8")

    existing_payload["profiles"] = profiles
    existing_payload["prime_batch_report"] = report
    MANUAL_PROFILES_FILE.write_text(json.dumps(existing_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    SEED_SEASONS_FILE.write_text(json.dumps(seed, indent=2, ensure_ascii=False), encoding="utf-8")
    reload_manual_profiles()
    return report


if __name__ == "__main__":
    r = build(try_sofascore=False)
    print(f"\nOK={len(r['ok'])} FAIL={len(r['failed'])} SKIP={len(r['skipped'])}")
