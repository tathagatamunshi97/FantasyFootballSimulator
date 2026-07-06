"""Backfill manual_profiles.json with FBref (+ Understat) stats."""
from __future__ import annotations

import json
from typing import Any

from fbref_client import build_fbref_season_entry, merge_fbref_for_player_season
from manual_profiles import MANUAL_PROFILES_FILE, reload_manual_profiles
from player_names import canonical_name, known_season_context, known_sofascore_id, normalize_key
from populate_manual_profiles import PRIME_PLAYERS, SEASON_PICKS, _make_profile
from seasonal_stats import season_label_from_suffix
from sofascore_client import _lookup_player_id
from understat_client import merge_understat_for_player_season

MISSING_ONLY = [
    ("Angel Di Maria", "season pick", "13/14"),
]


def _profile_key(name: str, profile_type: str, suffix: str) -> tuple[str, str, str]:
    return (normalize_key(canonical_name(name)), normalize_key(profile_type.replace("_", " ")), suffix)


def _profile_identity(profile: dict[str, Any]) -> tuple[int | str, str, str]:
    stats = profile.get("stats") or {}
    pid = stats.get("player_id") or known_sofascore_id(profile["player_name"])
    ident: int | str = int(pid) if pid else normalize_key(canonical_name(profile["player_name"]))
    return (
        ident,
        normalize_key(str(profile.get("profile_type", "")).replace("_", " ")),
        str(profile["season_suffix"]),
    )


def _profile_score(profile: dict[str, Any]) -> int:
    stats = profile.get("stats") or {}
    score = 0
    if stats.get("fbref_matched"):
        score += 4
    if stats.get("understat_matched"):
        score += 2
    if stats.get("data_source") == "seed_seasons":
        score += 3
    if float(stats.get("goals90") or 0) > 0:
        score += 1
    if float(stats.get("tackles90") or 0) > 0:
        score += 1
    return score


def _dedupe_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[int | str, str, str], dict[str, Any]] = {}
    for profile in profiles:
        key = _profile_identity(profile)
        if key not in best or _profile_score(profile) > _profile_score(best[key]):
            best[key] = profile
    return list(best.values())


def _find_profile_index(
    profiles: list[dict[str, Any]],
    index: dict[tuple[str, str, str], int],
    display_name: str,
    profile_type: str,
    season_suffix: str,
) -> int | None:
    keys = {normalize_key(canonical_name(display_name)), normalize_key(display_name)}
    kid = known_sofascore_id(display_name)
    if kid:
        for i, profile in enumerate(profiles):
            if _profile_identity(profile)[:1] == (kid,) and profile["season_suffix"] == season_suffix:
                ptype = normalize_key(str(profile.get("profile_type", "")).replace("_", " "))
                if ptype == normalize_key(profile_type.replace("_", " ")):
                    return i
    ptype = normalize_key(profile_type.replace("_", " "))
    for name_key in keys:
        hit = index.get((name_key, ptype, season_suffix))
        if hit is not None:
            return hit
    return None


def _enrich_stats(
    stats: dict[str, Any],
    display_name: str,
    season_suffix: str,
) -> tuple[dict[str, Any], list[str]]:
    before = {k: stats.get(k) for k in ("goals90", "tackles90", "shots90", "assists90", "interceptions90")}
    merge_fbref_for_player_season(display_name, stats, season_suffix, overwrite_zeros=True)
    merge_understat_for_player_season(display_name, stats, season_suffix)
    enriched: list[str] = []
    for key in before:
        if before.get(key) in (None, 0, 0.0) and stats.get(key) not in (None, 0, 0.0):
            enriched.append(key)
    if stats.get("fbref_matched"):
        src = stats.get("data_source", "")
        if stats.get("understat_matched"):
            stats["data_source"] = "fbref+understat" if src != "seed_seasons" else src
        elif src in ("understat_stub", ""):
            stats["data_source"] = "fbref"
    return stats, enriched


def enrich() -> dict[str, Any]:
    payload = json.loads(MANUAL_PROFILES_FILE.read_text(encoding="utf-8"))
    profiles: list[dict[str, Any]] = _dedupe_profiles(payload.get("profiles", []))
    index = {
        _profile_key(p["player_name"], p["profile_type"], p["season_suffix"]): i
        for i, p in enumerate(profiles)
    }
    report: dict[str, Any] = {"ok": [], "failed": [], "added": []}

    targets: list[tuple[str, str, str]] = []
    for raw, suffix in SEASON_PICKS:
        targets.append((raw, "season pick", suffix))
    for raw in PRIME_PLAYERS:
        from player_names import KNOWN_PRIME_SEASON_SUFFIX, known_display_name, canonical_name

        kid = known_sofascore_id(raw)
        suffix = KNOWN_PRIME_SEASON_SUFFIX.get(kid or -1, "")
        if suffix:
            targets.append((known_display_name(raw) or canonical_name(raw), "prime", suffix))

    for display_name, profile_type, season_suffix in targets:
        i = _find_profile_index(profiles, index, display_name, profile_type, season_suffix)
        if i is not None:
            profile = profiles[i]
            stats, fields = _enrich_stats(dict(profile["stats"]), profile["player_name"], season_suffix)
            profile["stats"] = stats
            report["ok"].append(
                {
                    "player": profile["player_name"],
                    "season": season_suffix,
                    "type": profile_type,
                    "fbref": stats.get("fbref_matched", False),
                    "understat": stats.get("understat_matched", False),
                    "fields": fields,
                    "goals90": stats.get("goals90"),
                    "tackles90": stats.get("tackles90"),
                }
            )
            print(
                f"OK enrich {profile['player_name']} {season_suffix} "
                f"fbref={stats.get('fbref_matched')} fields={fields}"
            )
            continue

        # Missing profile — try to create from FBref
        try:
            player_id, name = _lookup_player_id(display_name)
        except Exception:
            player_id = known_sofascore_id(display_name)
            name = display_name
        if not player_id:
            report["failed"].append({"player": display_name, "season": season_suffix, "error": "no player id"})
            continue
        ctx = known_season_context(int(player_id), season_suffix)
        if not ctx:
            report["failed"].append({"player": display_name, "season": season_suffix, "error": "no season context"})
            continue
        entry = build_fbref_season_entry(int(player_id), name, season_suffix, ctx)
        if not entry:
            report["failed"].append({"player": display_name, "season": season_suffix, "error": "fbref miss"})
            continue
        stats, fields = _enrich_stats(entry, name, season_suffix)
        profile = _make_profile(name, profile_type, season_suffix, stats)
        profiles.append(profile)
        index[_profile_key(name, profile_type, season_suffix)] = len(profiles) - 1
        report["added"].append(
            {
                "player": name,
                "season": season_suffix,
                "type": profile_type,
                "fbref": True,
                "fields": fields,
            }
        )
        print(f"ADD {name} {season_suffix} fbref+understat fields={fields}")

    payload["profiles"] = _dedupe_profiles(profiles)
    payload["fbref_enrich_report"] = report
    MANUAL_PROFILES_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    reload_manual_profiles()
    return report


if __name__ == "__main__":
    r = enrich()
    print("\n=== FBREF ENRICH SUMMARY ===")
    print(f"enriched: {len(r['ok'])} added: {len(r['added'])} failed: {len(r['failed'])}")
    for row in r["ok"] + r["added"]:
        print(
            f"  {row['player']:22} {row['season']}  fbref={row.get('fbref')}  "
            f"goals90={row.get('goals90')} tackles90={row.get('tackles90')}"
        )
    for row in r["failed"]:
        print(f"  FAIL {row['player']} {row['season']} — {row['error']}")
