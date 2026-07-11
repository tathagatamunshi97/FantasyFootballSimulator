"""Build missing prime profiles offline: clone season picks + Stones/Ozil without Chrome."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from manual_profiles import MANUAL_PROFILES_FILE, lookup_manual_prime, reload_manual_profiles
from player_names import canonical_name, known_display_name, known_sofascore_id, normalize_key
from populate_manual_profiles import _entry_to_stats, _make_profile, _build_understat_stub
from seasonal_stats import season_label_from_suffix

DATA_DIR = Path(__file__).resolve().parent / "data"
SEED_SEASONS_FILE = DATA_DIR / "seed_seasons.json"


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


def _save(payload: dict[str, Any], seed: dict[str, Any], report: dict[str, Any]) -> None:
    payload["prime_clone_batch_report"] = report
    MANUAL_PROFILES_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    SEED_SEASONS_FILE.write_text(json.dumps(seed, indent=2, ensure_ascii=False), encoding="utf-8")
    reload_manual_profiles()


def _ozil_prime_stats() -> dict[str, Any]:
    """Arsenal 2015/16 PL — FBref summary (no live scrape)."""
    minutes = 3035.0
    games = 35
    goals = 6.0
    assists = 19.0
    season_label = "2015-2016"
    stats: dict[str, Any] = {
        "team": "Arsenal",
        "league": "Premier League",
        "primary_position": "CAM",
        "fpl_position": "MID",
        "positions": ["CAM", "RW", "LW"],
        "player_id": 16176,
        "minutes": minutes,
        "games": games,
        "starts": 35,
        "goals90": goals * 90.0 / minutes,
        "assists90": assists * 90.0 / minutes,
        "xg90": 0.18,  # FBref npxG/90 approx from season table
        "xa90": 0.56,
        "shots90": 1.89,
        "shots_on_target90": 0.0,
        "key_passes90": 0.0,
        "tackles90": 0.0,
        "interceptions90": 0.0,
        "clearances90": 0.0,
        "dribbles90": 0.0,
        "passes_completed90": 0.0,
        "pass_pct": 86.0,
        "rating": 7.4,
        "yellow_cards90": 4 * 90.0 / minutes,
        "red_cards90": 0.0,
        "saves90": 0.0,
        "goals_prevented90": 0.0,
        "goals_conceded90": 0.0,
        "clean_sheet_pct": 0.0,
        "fbref_matched": True,
        "understat_matched": False,
        "data_source": "fbref_verified_manual",
        "auto_populate_source": "fbref_verified_manual",
        "seasons_used": [season_label],
        "teams_by_season": {season_label: "Arsenal"},
        "season_profile": season_label,
        "pos_raw": "MF",
    }
    # Enrich from Understat cache if available (no Chrome).
    try:
        from player_names import known_season_context

        ctx = known_season_context(16176, "15/16")
        if ctx:
            stub = _build_understat_stub(16176, "Mesut Özil", "15/16", ctx)
            if stub:
                for k, v in stub.items():
                    if k.startswith("understat_") or k in {
                        "npxg90",
                        "xg_chain90",
                        "xg_buildup90",
                        "understat_matched",
                        "xg90",
                        "xa90",
                        "shots90",
                        "key_passes90",
                    }:
                        if v not in (None, 0, 0.0) or k == "understat_matched":
                            stats[k] = v
    except Exception:
        pass
    return stats


def _stones_prime_from_sources() -> dict[str, Any] | None:
    """Prefer seed/cache; else Understat stub for Man City 24/25."""
    from seasonal_stats import _load_seed_season_entry
    from player_names import known_season_context

    seed = _load_seed_season_entry(152077, "24/25")
    if seed and float(seed.get("minutes") or 0) >= 180:
        stats = _entry_to_stats(dict(seed), "24/25")
        stats["data_source"] = "seed_seasons"
        stats["auto_populate_source"] = "seed_seasons"
        stats["player_id"] = 152077
        return stats

    ctx = known_season_context(152077, "24/25") or {
        "team": "Manchester City",
        "league": "Premier League",
    }
    stub = _build_understat_stub(152077, "John Stones", "24/25", ctx)
    if stub:
        stub["primary_position"] = "CB"
        stub["fpl_position"] = "DEF"
        stub["positions"] = ["CB"]
        stub["data_source"] = "understat_stub"
        stub["auto_populate_source"] = "understat_stub"
        return stub
    return None


def build() -> dict[str, Any]:
    # Hard-disable Sofascore + FBref Chrome paths used by populate helpers.
    import populate_manual_profiles as pmp
    import seasonal_stats as ss
    import fbref_client as fc

    def _noop(*_a, **_k):
        return None

    pmp.fetch_sofascore_season_entry = _noop  # type: ignore[assignment]
    ss.fetch_sofascore_season_entry = _noop  # type: ignore[assignment]
    fc.build_fbref_season_entry = _noop  # type: ignore[assignment]
    fc.merge_fbref_for_player_season = lambda *a, **k: None  # type: ignore[assignment]

    reload_manual_profiles()
    payload = json.loads(MANUAL_PROFILES_FILE.read_text(encoding="utf-8"))
    profiles: list[dict[str, Any]] = list(payload.get("profiles") or [])
    index = {_profile_key(p): i for i, p in enumerate(profiles)}
    seed = _load_seed()
    report: dict[str, Any] = {"cloned": [], "ok": [], "failed": [], "skipped": []}

    # 1) Clone all season picks -> primes
    season_picks = [
        p
        for p in list(profiles)
        if normalize_key(str(p.get("profile_type", "")).replace("_", " "))
        in {"season pick", "season_pick"}
    ]
    for pick in season_picks:
        name = pick["player_name"]
        suffix = pick["season_suffix"]
        key = (normalize_key(canonical_name(name)), "prime", suffix)
        if key in index or lookup_manual_prime(name):
            report["skipped"].append({"player": name, "season": suffix, "reason": "exists"})
            continue
        prime = copy.deepcopy(pick)
        prime["profile_type"] = "prime"
        stats = dict(prime.get("stats") or {})
        stats["stat_profile"] = "manual_prime"
        stats["manual_profile_type"] = "prime"
        stats["manual_season_suffix"] = suffix
        stats.setdefault("prime_season", season_label_from_suffix(suffix))
        prime["stats"] = stats
        profiles.append(prime)
        index[_profile_key(prime)] = len(profiles) - 1
        report["cloned"].append({"player": name, "season": suffix, "id": stats.get("player_id")})
        print(f"CLONE {name.encode('ascii', 'replace').decode()} {suffix}")

    payload["profiles"] = profiles
    _save(payload, seed, report)
    print(f"Saved after clone: {len(report['cloned'])} primes")

    # 2) Extra primes
    extras: list[tuple[str, str, dict[str, Any] | None]] = []

    if not lookup_manual_prime("John Stones"):
        stones = _stones_prime_from_sources()
        extras.append(("John Stones", "24/25", stones))
    else:
        report["skipped"].append({"player": "John Stones", "season": "24/25", "reason": "exists"})

    if not lookup_manual_prime("Mesut Ozil") and not lookup_manual_prime("Mesut Özil"):
        extras.append(("Mesut Özil", "15/16", _ozil_prime_stats()))
    else:
        report["skipped"].append({"player": "Mesut Özil", "season": "15/16", "reason": "exists"})

    for display, suffix, stats in extras:
        if stats is None:
            report["failed"].append({"player": display, "season": suffix, "error": "no offline stats"})
            print(f"FAIL {display} {suffix}: no offline stats")
            continue
        key = (normalize_key(canonical_name(display)), "prime", suffix)
        if key in index:
            report["skipped"].append({"player": display, "season": suffix, "reason": "key exists"})
            continue
        profile = _make_profile(display, "prime", suffix, stats)
        profiles.append(profile)
        index[_profile_key(profile)] = len(profiles) - 1
        pid = stats.get("player_id") or known_sofascore_id(display)
        if pid:
            seed.setdefault(str(int(pid)), {})[suffix] = _seed_entry_from_stats(stats, display)
        report["ok"].append(
            {
                "player": display,
                "season": suffix,
                "source": stats.get("auto_populate_source"),
                "minutes": stats.get("minutes"),
            }
        )
        print(
            f"OK {display.encode('ascii', 'replace').decode()} {suffix} "
            f"src={stats.get('auto_populate_source')} min={stats.get('minutes')}"
        )

    payload["profiles"] = profiles
    _save(payload, seed, report)
    return report


if __name__ == "__main__":
    r = build()
    print(
        f"\nCLONE={len(r['cloned'])} OK={len(r['ok'])} "
        f"FAIL={len(r['failed'])} SKIP={len(r['skipped'])}"
    )
    if r["failed"]:
        print("FAILED:", r["failed"])
