"""Fetch FBref stats including defense table; save JSON."""
from __future__ import annotations

import json
import sys

import pandas as pd
import soccerdata as sd

from fbref_client import (
    FBREF_LEAGUES,
    FBREF_TO_LEAGUE,
    LEAGUE_TO_FBREF,
    _col,
    _flat_df,
    _merge_stat_frames,
    _num,
    _per90,
    _row_to_fbref_entry,
    season_label_from_suffix,
)
from player_names import known_sofascore_id, known_season_context, KNOWN_PRIME_SEASON_SUFFIX
from understat_client import _lookup_understat, normalize_name, normalize_team

STAT_TYPES = ("standard", "shooting", "misc", "defense")

SEASON_PICKS = [
    ("Edinson Cavani", "16/17"),
    ("Dani Alves", "17/18"),
    ("Marcelo", "16/17"),
    ("Giovanni Lo Celso", "18/19"),
    ("Gonzalo Higuaín", "15/16"),
    ("Diego Godín", "15/16"),
    ("Luis Suárez", "15/16"),
    ("Arturo Vidal", "15/16"),
    ("Ángel Di María", "13/14"),
    ("Fernandinho", "17/18"),
    ("Roberto Firmino", "17/18"),
    ("Neymar", "14/15"),
    ("Alexis Sánchez", "16/17"),
    ("Radamel Falcao", "16/17"),
    ("Riyad Mahrez", "22/23"),
]

PRIME_OVERRIDES = {12994: "14/15", 149734: "21/22"}

PRIME_PLAYERS = [
    "N'Golo Kanté", "Rúben Dias", "Rodri", "Cole Palmer", "Carvajal",
    "Cristiano Ronaldo", "Lionel Messi", "Casemiro", "Mohamed Salah",
    "Sergio Ramos", "Antoine Griezmann", "Antonio Rüdiger", "Harry Maguire",
    "Luka Modrić", "Aymeric Laporte", "Manuel Neuer", "Alaba",
]


def fetch_entry(name: str, pid: int | None, suffix: str) -> dict | None:
    ctx = known_season_context(pid or -1, suffix) or {}
    league = ctx.get("league")
    if not league or league not in LEAGUE_TO_FBREF:
        return None
    season_label = season_label_from_suffix(suffix)
    fbref_league = LEAGUE_TO_FBREF[league]
    reader = sd.FBref(leagues=[fbref_league], seasons=[season_label])
    frames = []
    for stat_type in STAT_TYPES:
        try:
            raw = reader.read_player_season_stats(stat_type=stat_type)
        except Exception:
            continue
        if raw is not None and not raw.empty:
            frames.append(_flat_df(raw))
    if not frames:
        return None
    table = _merge_stat_frames(frames)
    team_norm = normalize_team(ctx.get("team", ""))
    index = {}
    for _, row in table.iterrows():
        entry = _row_to_fbref_entry(row, league)
        if not entry:
            continue
        player = normalize_name(str(row.get("player", "")))
        team = normalize_team(str(row.get("team", "")))
        if not player:
            continue
        key = (player, team)
        if key not in index or entry["minutes"] > index[key]["minutes"]:
            index[key] = entry
    hit = _lookup_understat(index, name, team_norm)
    if hit:
        hit["player_id"] = pid
        return hit
    return None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    results = {}
    targets = [(n, s, "season") for n, s in SEASON_PICKS]
    for name in PRIME_PLAYERS:
        pid = known_sofascore_id(name)
        suffix = PRIME_OVERRIDES.get(pid) or KNOWN_PRIME_SEASON_SUFFIX.get(pid or -1)
        if suffix:
            targets.append((name, suffix, "prime"))

    for name, suffix, kind in targets:
        pid = known_sofascore_id(name)
        key = f"{name}|{kind}|{suffix}"
        try:
            e = fetch_entry(name, pid, suffix)
            results[key] = e
            if e:
                print(
                    f"OK {key}: min={e['minutes']} g90={e['goals90']:.3f} "
                    f"a90={e['assists90']:.3f} tac={e['tackles90']:.2f} "
                    f"int={e['interceptions90']:.2f} pos={e['primary_position']}"
                )
            else:
                print(f"MISS {key}")
        except Exception as ex:
            print(f"ERR {key}: {ex}")
            results[key] = None

    with open("_fetch_all_stats_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print("saved _fetch_all_stats_results.json")


if __name__ == "__main__":
    main()
