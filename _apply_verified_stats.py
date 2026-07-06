"""Apply verified FBref stats to manual_profiles.json and seed_seasons.json."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from player_names import (
    KNOWN_PLAYER_PRIMARY,
    apply_known_position_overrides,
    known_sofascore_id,
)
from seasonal_stats import season_label_from_suffix

ROOT = Path(__file__).resolve().parent
MANUAL = ROOT / "data" / "manual_profiles.json"
SEED = ROOT / "data" / "seed_seasons.json"
FETCH = ROOT / "_fetch_all_stats_results.json"
NOTES = ROOT / "data" / "validation_notes.json"

# Verified defensive stats when FBref misc table is empty (soccerdata limitation).
MANUAL_DEFENSE_OVERRIDES: dict[str, dict[str, float]] = {
    "Arturo Vidal|season|15/16": {"tackles90": 3.52, "interceptions90": 1.67},
    "Sergio Ramos|prime|14/15": {"tackles90": 1.12, "interceptions90": 1.12},
}

PROFILE_KEY_MAP: dict[tuple[str, str], str | None] = {
    ("Edinson Cavani", "season pick"): "Edinson Cavani|season|16/17",
    ("Dani Alves", "season pick"): "Dani Alves|season|17/18",
    ("Marcelo", "season pick"): "Marcelo|season|16/17",
    ("Giovanni Lo Celso", "season pick"): "Giovanni Lo Celso|season|18/19",
    ("Gonzalo Higuaín", "season pick"): None,
    ("Diego Godín", "season pick"): "Diego Godín|season|15/16",
    ("Luis Suárez", "season pick"): "Luis Suárez|season|15/16",
    ("Arturo Vidal", "season pick"): "Arturo Vidal|season|15/16",
    ("Ángel Di María", "season pick"): "Ángel Di María|season|13/14",
    ("Fernandinho", "season pick"): "Fernandinho|season|17/18",
    ("Roberto Firmino", "season pick"): "Roberto Firmino|season|17/18",
    ("Neymar", "season pick"): "Neymar|season|14/15",
    ("Alexis Sánchez", "season pick"): "Alexis Sánchez|season|16/17",
    ("Radamel Falcao", "season pick"): "Radamel Falcao|season|16/17",
    ("Riyad Mahrez", "season pick"): "Riyad Mahrez|season|22/23",
    ("Cristiano Ronaldo", "prime"): "Cristiano Ronaldo|prime|14/15",
    ("N'Golo Kanté", "prime"): "N'Golo Kanté|prime|16/17",
    ("Lionel Messi", "prime"): "Lionel Messi|prime|14/15",
    ("Rúben Dias", "prime"): "Rúben Dias|prime|20/21",
    ("Rodri", "prime"): "Rodri|prime|23/24",
    ("Cole Palmer", "prime"): "Cole Palmer|prime|23/24",
    ("Carvajal", "prime"): "Carvajal|prime|16/17",
    ("Casemiro", "prime"): "Casemiro|prime|17/18",
    ("Mohamed Salah", "prime"): "Mohamed Salah|prime|17/18",
    ("Sergio Ramos", "prime"): "Sergio Ramos|prime|14/15",
    ("Antoine Griezmann", "prime"): "Antoine Griezmann|prime|15/16",
    ("Antonio Rüdiger", "prime"): "Antonio Rüdiger|prime|21/22",
    ("Harry Maguire", "prime"): "Harry Maguire|prime|18/19",
    ("Luka Modrić", "prime"): "Luka Modrić|prime|17/18",
    ("Aymeric Laporte", "prime"): "Aymeric Laporte|prime|21/22",
    ("Manuel Neuer", "prime"): "Manuel Neuer|prime|13/14",
    ("Alaba", "prime"): "Alaba|prime|19/20",
}

SEASON_SUFFIX_UPDATES = {
    ("Lionel Messi", "prime"): "14/15",
    ("Aymeric Laporte", "prime"): "21/22",
}

TRACK_KEYS = (
    "minutes", "games", "starts", "goals90", "assists90", "tackles90",
    "interceptions90", "shots90", "shots_on_target90", "primary_position",
    "season_suffix", "team", "league",
)


def _round_stats(entry: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(entry)
    for k, v in out.items():
        if isinstance(v, float) and k.endswith("90"):
            out[k] = round(v, 2) if k in ("goals90", "assists90") else v
    return out


def _merge_entry(base: dict[str, Any], fetched: dict[str, Any], pid: int | None) -> dict[str, Any]:
    out = deepcopy(base)
    for k, v in fetched.items():
        if k in ("player_id", "fbref_matched"):
            out[k] = v
            continue
        if k in (
            "minutes", "games", "starts", "goals90", "assists90", "shots90",
            "shots_on_target90", "tackles90", "interceptions90", "yellow_cards90",
            "red_cards90", "rating", "team", "league", "pos_raw",
            "primary_position", "fpl_position", "positions",
        ):
            if k.endswith("90") and isinstance(v, (int, float)) and v == 0 and out.get(k, 0) not in (0, 0.0, None):
                continue
            out[k] = v
    apply_known_position_overrides(out, pid)
    season_label = out.get("season_profile") or out.get("seasons_used", [""])[0]
    if fetched.get("team"):
        out.setdefault("teams_by_season", {})[season_label] = fetched["team"]
    out["data_source"] = "fbref+verified"
    out["fbref_matched"] = True
    return out


def main() -> None:
    fetched_all = json.loads(FETCH.read_text(encoding="utf-8"))
    manual = json.loads(MANUAL.read_text(encoding="utf-8"))
    seed = json.loads(SEED.read_text(encoding="utf-8"))

    changes: list[dict[str, Any]] = []
    notes: dict[str, Any] = {"sources": {}, "unverified": [], "corrections": []}

    for prof in manual["profiles"]:
        name = prof["player_name"]
        ptype = prof["profile_type"]
        suffix = prof.get("season_suffix", "")
        key = (name, ptype)
        fetch_key = PROFILE_KEY_MAP.get(key)

        new_suffix = SEASON_SUFFIX_UPDATES.get((name, ptype))
        if new_suffix:
            prof["season_suffix"] = new_suffix
            suffix = new_suffix
            season_label = season_label_from_suffix(new_suffix)
            prof["stats"]["seasons_used"] = [season_label]
            prof["stats"]["season_profile"] = season_label

        if fetch_key is None:
            if name == "Gonzalo Higuaín":
                notes["unverified"].append({
                    "player": name,
                    "season": suffix,
                    "reason": "FBref name mismatch; retained Transfermarkt/Wikipedia seeded stats (36g/35apps Serie A)",
                    "source": "Transfermarkt + Wikipedia 15/16 Napoli",
                })
            continue

        fetched = fetched_all.get(fetch_key)
        if not fetched:
            notes["unverified"].append({"player": name, "season": suffix, "reason": "no fetch result"})
            continue

        if fetch_key in MANUAL_DEFENSE_OVERRIDES:
            fetched = {**fetched, **MANUAL_DEFENSE_OVERRIDES[fetch_key]}

        pid = fetched.get("player_id") or known_sofascore_id(name)
        before = {k: prof["stats"].get(k) for k in TRACK_KEYS if k in prof["stats"] or k == "season_suffix"}
        before["season_suffix"] = prof.get("season_suffix")

        prof["stats"] = _merge_entry(prof["stats"], fetched, pid)
        if new_suffix:
            prof["stats"]["teams_by_season"] = {
                season_label_from_suffix(new_suffix): fetched.get("team", prof["stats"].get("team", ""))
            }

        after = {k: prof["stats"].get(k) for k in TRACK_KEYS if k in prof["stats"] or k == "season_suffix"}
        after["season_suffix"] = prof.get("season_suffix")

        delta = {k: {"before": before.get(k), "after": after.get(k)} for k in set(before) | set(after) if before.get(k) != after.get(k)}
        if delta:
            changes.append({"player": name, "type": ptype, "season": prof["season_suffix"], "delta": delta})

        notes["sources"][f"{name} ({ptype} {prof['season_suffix']})"] = (
            "FBref via soccerdata"
            + (" + footballcalculator.co.uk defense" if fetch_key in MANUAL_DEFENSE_OVERRIDES else "")
        )

        if ptype == "prime" and pid:
            seed_entry = _round_stats(prof["stats"])
            seed_entry["player_name"] = name
            seed_entry["stat_profile"] = "seeded_season"
            pid_key = str(pid)
            if pid_key not in seed:
                seed[pid_key] = {}
            # Drop stale prime season keys for this player.
            keep_suffix = prof["season_suffix"]
            seed[pid_key] = {keep_suffix: seed_entry}

    # Mahrez note: goals90 0.23 is correct per FBref (5g/1920min), not 0.51
    notes["corrections"].append({
        "player": "Riyad Mahrez",
        "note": "Prior audit suggested g90~0.51; FBref confirms 5 goals in 1920 PL minutes = 0.23 g90 (verified correct)",
        "source": "FBref 2022-23 Premier League",
    })
    notes["corrections"].append({
        "player": "Lionel Messi",
        "note": "Prime season changed 20/21 -> 14/15 (43g+18a in 3375 La Liga minutes, true peak)",
        "source": "FBref + StatMuse + LaLiga official",
    })
    notes["corrections"].append({
        "player": "Aymeric Laporte",
        "note": "Prime season changed 20/21 (16 apps injury year) -> 21/22 (33 apps, 4g, 2828 min)",
        "source": "FBref + Transfermarkt + Wikipedia",
    })

    MANUAL.write_text(json.dumps(manual, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    SEED.write_text(json.dumps(seed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    NOTES.write_text(json.dumps({"changes": changes, **notes}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Updated {len(changes)} profiles")
    print(f"Wrote {NOTES}")


if __name__ == "__main__":
    main()
