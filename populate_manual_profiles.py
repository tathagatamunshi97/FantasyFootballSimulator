"""Auto-fetch stats into manual_profiles.json (Sofascore → seed → Understat fallback)."""
from __future__ import annotations

import json
import time
from typing import Any

from manual_profiles import MANUAL_PROFILES_FILE, reload_manual_profiles
from models import SOFASCORE_POSITION_TO_FPL, SOFASCORE_POSITION_TO_PRIMARY
from player_names import (
    KNOWN_PLAYER_POSITIONS,
    KNOWN_PRIME_SEASON_SUFFIX,
    canonical_name,
    known_display_name,
    known_season_context,
    known_sofascore_id,
)
from seasonal_stats import (
    _load_seed_season_entry,
    fetch_sofascore_season_entry,
    find_prime_season_suffix,
    season_label_from_suffix,
)
from sofascore_client import _lookup_player_id
from fbref_client import build_fbref_season_entry, merge_fbref_for_player_season
from understat_client import merge_understat_for_player_season

SEASON_PICKS: list[tuple[str, str]] = [
    ("Edinson Cavani", "16/17"),
    ("Dani Alves", "17/18"),
    ("Marcelo", "16/17"),
    ("Giovanni Lo Celso", "18/19"),
    ("Gonzalo Higuain", "15/16"),
    ("Diego Godin", "15/16"),
    ("Luis Suarez", "15/16"),
    ("Arturo Vidal", "15/16"),
    ("Angel Di Maria", "13/14"),
    ("Fernandinho", "17/18"),
    ("Roberto Firmino", "17/18"),
    ("Neymar", "14/15"),
    ("Alexis Sanchez", "16/17"),
    ("Radamel Falcao", "16/17"),
    ("Riyad Mahrez", "22/23"),
]

PRIME_PLAYERS: list[str] = [
    "Cristiano Ronaldo",
    "Ngolo Kante",
    "Lionel Messi",
]


def _entry_to_stats(entry: dict[str, Any], season_suffix: str) -> dict[str, Any]:
    season_label = season_label_from_suffix(season_suffix)
    data = {k: v for k, v in entry.items() if k != "player_name"}
    data.setdefault("seasons_used", [season_label])
    data.setdefault("teams_by_season", {season_label: data.get("team", "")})
    data["season_profile"] = season_label
    return data


def _sofascore_pos(player_id: int) -> str:
    return KNOWN_PLAYER_POSITIONS.get(player_id, "M")


def _build_understat_stub(
    player_id: int,
    display_name: str,
    season_suffix: str,
    ctx: dict[str, str],
) -> dict[str, Any] | None:
    """Minimal profile from Understat when Sofascore is unavailable."""
    pos = _sofascore_pos(player_id)
    fpl = SOFASCORE_POSITION_TO_FPL[pos]
    primary = SOFASCORE_POSITION_TO_PRIMARY[pos]
    season_label = season_label_from_suffix(season_suffix)
    stats: dict[str, Any] = {
        "team": ctx["team"],
        "league": ctx["league"],
        "primary_position": primary,
        "fpl_position": fpl,
        "positions": [primary],
        "player_id": player_id,
        "minutes": 0,
        "games": 0,
        "starts": 0,
        "goals90": 0.0,
        "assists90": 0.0,
        "xg90": 0.0,
        "xa90": 0.0,
        "shots90": 0.0,
        "shots_on_target90": 0.0,
        "key_passes90": 0.0,
        "tackles90": 0.0,
        "interceptions90": 0.0,
        "clearances90": 0.0,
        "dribbles90": 0.0,
        "passes_completed90": 0.0,
        "rating": 7.0,
        "data_source": "understat_stub",
        "seasons_used": [season_label],
        "teams_by_season": {season_label: ctx["team"]},
        "season_profile": season_label,
    }
    merge_understat_for_player_season(display_name, stats, season_suffix)
    if not stats.get("understat_matched"):
        return None

    minutes = float(stats.get("minutes") or 0)
    if minutes > 0:
        stats["games"] = max(1, int(round(minutes / 85)))
        stats["starts"] = stats["games"]
    stats["xg90"] = float(stats.get("npxg90") or stats.get("understat_xg90") or 0)
    stats["xa90"] = float(stats.get("understat_xa90") or 0)
    stats["shots90"] = float(stats.get("understat_shots90") or 0)
    stats["key_passes90"] = float(stats.get("understat_key_passes90") or 0)
    return stats


def _fetch_season(
    player_raw: str,
    season_suffix: str,
    *,
    player_id: int | None = None,
    display_name: str | None = None,
) -> tuple[str, dict[str, Any], str] | tuple[None, str]:
    """
    Resolve one season profile.
    Returns (display_name, stats, source_tag) or (None, error).
    """
    try:
        if player_id is None or display_name is None:
            player_id, display_name = _lookup_player_id(player_raw)
    except Exception as exc:
        kid = known_sofascore_id(player_raw)
        if kid is None:
            return None, f"id lookup: {exc}"
        player_id = kid
        display_name = known_display_name(player_raw) or canonical_name(player_raw)

    entry: dict[str, Any] | None = None
    source = ""

    seed = _load_seed_season_entry(player_id, season_suffix)
    if seed:
        entry = dict(seed)
        source = "seed_seasons"

    if not entry:
        try:
            fetched = fetch_sofascore_season_entry(player_id, season_suffix, player_name=display_name)
            if fetched:
                entry = fetched
                source = "sofascore"
        except Exception as exc:
            if "403" not in str(exc):
                pass  # try fallbacks below

    if not entry:
        ctx = known_season_context(player_id, season_suffix)
        if ctx:
            fbref_entry = build_fbref_season_entry(player_id, display_name, season_suffix, ctx)
            if fbref_entry:
                entry = fbref_entry
                source = "fbref"

    if not entry:
        ctx = known_season_context(player_id, season_suffix)
        if ctx:
            stub = _build_understat_stub(player_id, display_name, season_suffix, ctx)
            if stub:
                entry = stub
                source = "understat_stub"

    if not entry:
        return None, "no stats (sofascore blocked, no seed, fbref/understat miss)"

    stats = _entry_to_stats(entry, season_suffix)
    if source not in ("understat_stub", "fbref"):
        merge_fbref_for_player_season(display_name, stats, season_suffix)
        merge_understat_for_player_season(display_name, stats, season_suffix)
    elif source == "fbref":
        merge_understat_for_player_season(display_name, stats, season_suffix)
    elif source == "understat_stub":
        merge_fbref_for_player_season(display_name, stats, season_suffix)
    stats["data_source"] = source
    stats["auto_populate_source"] = source
    return display_name, stats, source


def _make_profile(
    player_name: str,
    profile_type: str,
    season_suffix: str,
    stats: dict[str, Any],
) -> dict[str, Any]:
    return {
        "player_name": player_name,
        "profile_type": profile_type,
        "season_suffix": season_suffix,
        "stats": stats,
    }


def populate(*, try_sofascore: bool = True) -> dict[str, Any]:
    profiles: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "season_pick_ok": [],
        "season_pick_failed": [],
        "prime_ok": [],
        "prime_failed": [],
        "notes": [
            "Sofascore API is often 403 rate-limited; seed_seasons.json, FBref, and Understat used as fallback.",
            "FBref fills goals/tackles/shots; Understat adds xG-chain; passes/dribbles may stay zero.",
        ],
    }

    if not try_sofascore:
        import seasonal_stats as ss
        import sofascore_client as sc

        def _noop(*_a, **_k):
            return None

        ss.fetch_sofascore_season_entry = _noop  # type: ignore[assignment]
        sc._fetch_player_season_via_career_api = _noop  # type: ignore[assignment]

    for raw, suffix in SEASON_PICKS:
        result = _fetch_season(raw, suffix)
        if result[0] is None:
            report["season_pick_failed"].append({"player": raw, "season": suffix, "error": result[1]})
            print(f"FAIL season pick {raw} {suffix}: {result[1]}")
        else:
            name, stats, source = result
            profiles.append(_make_profile(name, "season pick", suffix, stats))
            report["season_pick_ok"].append(
                {
                    "player": name,
                    "season": suffix,
                    "team": stats.get("team"),
                    "source": source,
                    "understat": stats.get("understat_matched", False),
                    "fbref": stats.get("fbref_matched", False),
                }
            )
            print(
                f"OK season pick {name} {suffix} | {stats.get('team')} | "
                f"src={source} understat={stats.get('understat_matched')}"
            )
        time.sleep(0.5)

    for raw in PRIME_PLAYERS:
        try:
            player_id, display_name = _lookup_player_id(raw)
            suffix = find_prime_season_suffix(display_name, player_id=player_id)
        except Exception as exc:
            kid = known_sofascore_id(raw)
            if kid and kid in KNOWN_PRIME_SEASON_SUFFIX:
                suffix = KNOWN_PRIME_SEASON_SUFFIX[kid]
                display_name = known_display_name(raw) or canonical_name(raw)
                player_id = kid
            else:
                report["prime_failed"].append({"player": raw, "error": str(exc)})
                print(f"FAIL prime {raw}: {exc}")
                continue

        result = _fetch_season(raw, suffix, player_id=player_id, display_name=display_name)
        if result[0] is None:
            report["prime_failed"].append({"player": raw, "season": suffix, "error": result[1]})
            print(f"FAIL prime {raw} {suffix}: {result[1]}")
        else:
            name, stats, source = result
            profiles.append(_make_profile(name, "prime", suffix, stats))
            report["prime_ok"].append(
                {
                    "player": name,
                    "season": suffix,
                    "team": stats.get("team"),
                    "source": source,
                    "understat": stats.get("understat_matched", False),
                    "fbref": stats.get("fbref_matched", False),
                }
            )
            print(
                f"OK prime {name} {suffix} | {stats.get('team')} | "
                f"src={source} understat={stats.get('understat_matched')}"
            )
        time.sleep(0.5)

    payload = {"profiles": profiles, "auto_populate_report": report}
    MANUAL_PROFILES_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    reload_manual_profiles()
    return report


if __name__ == "__main__":
    r = populate(try_sofascore=False)
    print("\n=== SUMMARY ===")
    print(f"season picks OK: {len(r['season_pick_ok'])} failed: {len(r['season_pick_failed'])}")
    print(f"prime OK: {len(r['prime_ok'])} failed: {len(r['prime_failed'])}")
    for row in r["season_pick_ok"] + r["prime_ok"]:
        print(f"  {row['player']:22} {row['season']}  {row['source']:14}  understat={row['understat']}")
    for row in r["season_pick_failed"] + r["prime_failed"]:
        print(f"  FAIL {row.get('player')} {row.get('season', '')} — {row.get('error')}")
