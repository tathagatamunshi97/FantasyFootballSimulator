"""Tournament storage, draw, fixtures, and match simulation."""
from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models import FantasyTeam
from report_builder import build_report
from stats_resolver import prepare_match_player_stats

from web.experiments import _apply_name_map, validate_team_payload
from web.state import get_stats_store

ROOT = Path(__file__).resolve().parent.parent
TOURNAMENTS_DIR = ROOT / "data" / "tournaments"

GROUP_LETTERS = "ABCDEFGHIJKLMNOPQR"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tournament_path(tournament_id: str) -> Path:
    return TOURNAMENTS_DIR / f"{tournament_id}.json"


def _empty_table(teams: list[str]) -> dict[str, dict[str, int]]:
    return {
        t: {"played": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "gd": 0, "pts": 0}
        for t in teams
    }


def _default_settings(team_count: int) -> dict[str, Any]:
    if team_count <= 0:
        return {
            "group_count": 1,
            "teams_per_group": 1,
            "advance_per_group": 1,
            "knockout_format": "single_elim",
            "simulations_per_match": 10000,
        }
    if team_count <= 4:
        return {
            "group_count": 1,
            "teams_per_group": team_count,
            "advance_per_group": min(2, team_count),
            "knockout_format": "single_elim",
            "simulations_per_match": 10000,
        }
    group_count = 4
    while team_count % group_count != 0 and group_count < team_count:
        group_count += 1
    if team_count % group_count != 0:
        group_count = _best_group_count(team_count)
    teams_per_group = team_count // group_count
    advance = 2 if teams_per_group >= 4 else 1
    return {
        "group_count": group_count,
        "teams_per_group": teams_per_group,
        "advance_per_group": advance,
        "knockout_format": "single_elim",
        "simulations_per_match": 10000,
    }


def _best_group_count(n: int) -> int:
    for g in (8, 6, 4, 3, 2):
        if n >= g and n % g == 0:
            return g
    return max(1, min(4, n))


def valid_group_counts(team_count: int) -> list[int]:
    """Divisors of team_count where each group has at least 2 teams."""
    if team_count < 4:
        return [1] if team_count >= 2 else []
    return [g for g in range(1, team_count + 1) if team_count % g == 0 and team_count // g >= 2]


def _validate_group_settings(team_count: int, group_count: int) -> None:
    if group_count < 1:
        raise ValueError("group_count must be at least 1")
    if group_count > team_count:
        raise ValueError(f"Cannot have more groups ({group_count}) than teams ({team_count})")
    if team_count % group_count != 0:
        raise ValueError(
            f"{team_count} teams do not divide evenly into {group_count} groups"
        )
    per_group = team_count // group_count
    if per_group < 2:
        raise ValueError(f"Each group needs at least 2 teams (would be {per_group})")


def _settings_from_group_count(team_count: int, group_count: int) -> dict[str, Any]:
    _validate_group_settings(team_count, group_count)
    teams_per_group = team_count // group_count
    advance = 2 if teams_per_group >= 4 else 1
    return {
        "group_count": group_count,
        "teams_per_group": teams_per_group,
        "advance_per_group": advance,
        "knockout_format": "single_elim",
        "simulations_per_match": 10000,
    }


def _round_robin_fixtures(teams: list[str], group_key: str) -> list[dict[str, Any]]:
    n = len(teams)
    if n < 2:
        return []
    slots = list(teams)
    if n % 2 == 1:
        slots.append("__BYE__")
    count = len(slots)
    half = count // 2
    fixtures: list[dict[str, Any]] = []
    match_num = 0
    rounds = count - 1 if count > 1 else 0
    for rnd in range(rounds):
        for i in range(half):
            home = slots[i]
            away = slots[count - 1 - i]
            if home != "__BYE__" and away != "__BYE__":
                match_num += 1
                fixtures.append(
                    {
                        "id": f"g{group_key}-{match_num}",
                        "home": home,
                        "away": away,
                        "round": rnd + 1,
                        "played": False,
                        "result_id": None,
                    }
                )
        slots = [slots[0]] + [slots[-1]] + slots[1:-1]
    return fixtures


def _sort_standings(table: dict[str, dict[str, int]]) -> list[str]:
    return sorted(
        table.keys(),
        key=lambda t: (-table[t]["pts"], -table[t]["gd"], -table[t]["gf"], t.lower()),
    )


def _default_tournament(name: str, team_names: list[str], settings: dict[str, Any] | None) -> dict[str, Any]:
    tid = uuid.uuid4().hex[:12]
    teams = [t.strip() for t in team_names if t and t.strip()]
    cfg = settings or _default_settings(len(teams))
    return {
        "id": tid,
        "name": name.strip() or f"Tournament {tid[:6]}",
        "status": "draft",
        "created_at": _now(),
        "updated_at": _now(),
        "team_names": teams,
        "settings": cfg,
        "groups": {},
        "knockout": {"format": cfg.get("knockout_format", "single_elim"), "rounds": []},
        "match_results": {},
    }


def save_tournament(t: dict[str, Any]) -> None:
    TOURNAMENTS_DIR.mkdir(parents=True, exist_ok=True)
    t["updated_at"] = _now()
    _tournament_path(t["id"]).write_text(
        json.dumps(t, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_tournament(tournament_id: str) -> dict[str, Any] | None:
    path = _tournament_path(tournament_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _summary(t: dict[str, Any]) -> dict[str, Any]:
    played = sum(1 for r in t.get("match_results", {}).values())
    return {
        "id": t["id"],
        "name": t.get("name"),
        "status": t.get("status"),
        "team_count": len(t.get("team_names") or []),
        "created_at": t.get("created_at"),
        "updated_at": t.get("updated_at"),
        "matches_played": played,
    }


def list_tournaments() -> list[dict[str, Any]]:
    if not TOURNAMENTS_DIR.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in TOURNAMENTS_DIR.glob("*.json"):
        try:
            t = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        rows.append(_summary(t))
    rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return rows


def create_tournament(
    name: str,
    team_names: list[str] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    t = _default_tournament(name, team_names or [], settings)
    save_tournament(t)
    return t


def set_teams(tournament_id: str, team_names: list[str]) -> dict[str, Any]:
    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    if t["status"] not in ("draft", "group_draw"):
        raise ValueError("Cannot change teams after group draw")
    teams = [x.strip() for x in team_names if x and x.strip()]
    if len(teams) < 2:
        raise ValueError("At least 2 teams required")
    t["team_names"] = teams
    prev_gc = (t.get("settings") or {}).get("group_count")
    try:
        t["settings"] = _settings_from_group_count(len(teams), int(prev_gc))
    except (TypeError, ValueError):
        t["settings"] = _default_settings(len(teams))
    if settings := t.get("settings"):
        t["knockout"]["format"] = settings.get("knockout_format", "single_elim")
    t["groups"] = {}
    save_tournament(t)
    return t


def perform_group_draw(tournament_id: str, *, seed: int | None = None) -> dict[str, Any]:
    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    teams = list(t["team_names"])
    if len(teams) < 2:
        raise ValueError("Need at least 2 teams for draw")
    cfg = t["settings"]
    g_count = int(cfg["group_count"])
    per_group = int(cfg["teams_per_group"])
    expected = g_count * per_group
    if len(teams) != expected:
        raise ValueError(
            f"Team count ({len(teams)}) does not match group layout "
            f"({g_count} groups × {per_group} teams = {expected}). "
            "Adjust group settings before running the draw."
        )

    rng = random.Random(seed)
    pool = teams[:]
    rng.shuffle(pool)

    groups: dict[str, Any] = {}
    idx = 0
    for gi in range(g_count):
        key = GROUP_LETTERS[gi]
        group_teams = pool[idx : idx + per_group]
        idx += per_group
        groups[key] = {
            "teams": group_teams,
            "fixtures": [],
            "table": _empty_table(group_teams),
        }

    t["groups"] = groups
    t["status"] = "group_draw"
    save_tournament(t)
    return t


def generate_group_fixtures(tournament_id: str) -> dict[str, Any]:
    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    if not t.get("groups"):
        raise ValueError("Run group draw first")
    for key, group in t["groups"].items():
        group["fixtures"] = _round_robin_fixtures(group["teams"], key)
        group["table"] = _empty_table(group["teams"])
    t["status"] = "group_stage"
    save_tournament(t)
    return t


def _find_fixture(t: dict[str, Any], match_id: str) -> tuple[str, dict[str, Any]] | None:
    for gkey, group in t.get("groups", {}).items():
        for fx in group.get("fixtures", []):
            if fx["id"] == match_id:
                return gkey, fx
    for rnd in t.get("knockout", {}).get("rounds", []):
        for tie in rnd.get("ties", []):
            if tie.get("id") == match_id:
                return "knockout", tie
    return None


def _load_teams_for_match(home_name: str, away_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    from google_sheets_teams import load_team_by_name

    store = get_stats_store()
    for name in (home_name, away_name):
        draft = load_team_by_name(name, formation="4-3-3", store=store)
        meta = draft.get("sheet_meta") or {}
        if not meta.get("ready"):
            count = meta.get("player_count", "?")
            raise ValueError(
                f"Team '{draft.get('name')}' has {count}/11 players on the sheet. "
                "Each team needs at least 11 players."
            )
        roster = meta.get("full_roster") or meta.get("roster_players") or [
            (r.get("player") or "").strip()
            for r in draft.get("lineup", [])
            if (r.get("player") or "").strip()
        ]
        if roster:
            store.ensure_players(roster)

    team_a = load_team_by_name(home_name, formation="4-3-3", store=store)
    team_b = load_team_by_name(away_name, formation="4-3-3", store=store)
    for label, payload in (("Home", team_a), ("Away", team_b)):
        errors = validate_team_payload(payload, label)
        if errors:
            meta = payload.get("sheet_meta") or {}
            hint = ""
            if meta.get("ready") and any("GK" in e for e in errors):
                hint = " Roster has 11 names but formation fit found no goalkeeper — add a GK to the sheet."
            raise ValueError("; ".join(errors) + hint)
    return team_a, team_b


def _resolve_winner(
    home_name: str,
    away_name: str,
    home_goals: int,
    away_goals: int,
    report: dict[str, Any],
    *,
    require_winner: bool,
) -> str | None:
    if home_goals > away_goals:
        return home_name
    if away_goals > home_goals:
        return away_name
    if not require_winner:
        return None
    mc = report.get("monte_carlo") or {}
    h_pct = mc.get("home_win_pct") or 0
    a_pct = mc.get("away_win_pct") or 0
    if h_pct > a_pct:
        return home_name
    if a_pct > h_pct:
        return away_name
    exg = mc.get("expected_xg") or {}
    if (exg.get("home") or 0) >= (exg.get("away") or 0):
        return home_name
    return away_name


def _run_simulation(
    home_name: str,
    away_name: str,
    match_id: str,
    n_simulations: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    team_a, team_b = _load_teams_for_match(home_name, away_name)
    store = get_stats_store()
    player_stats, season_overrides, name_map = prepare_match_player_stats(team_a, team_b, store)
    resolved = _apply_name_map({"team_a": team_a, "team_b": team_b}, name_map)
    home = FantasyTeam.from_dict(resolved["team_a"])
    away = FantasyTeam.from_dict(resolved["team_b"])
    seed = abs(hash(match_id)) % (2**31)
    report = build_report(
        home,
        away,
        player_stats,
        n_simulations=n_simulations,
        seed=seed,
        include_single_match=True,
        season_overrides=season_overrides,
    )
    sample = report.get("sample_match") or {}
    home_goals = int(sample.get("home", {}).get("goals", 0))
    away_goals = int(sample.get("away", {}).get("goals", 0))
    snapshot = {
        "score": f"{home_goals}-{away_goals}",
        "home_goals": home_goals,
        "away_goals": away_goals,
        "expected_xg": report.get("monte_carlo", {}).get("expected_xg"),
        "home_win_pct": report.get("monte_carlo", {}).get("home_win_pct"),
        "away_win_pct": report.get("monte_carlo", {}).get("away_win_pct"),
        "draw_pct": report.get("monte_carlo", {}).get("draw_pct"),
        "simulations": n_simulations,
    }
    return report, snapshot


def _apply_group_result(
    table: dict[str, dict[str, int]],
    home: str,
    away: str,
    hg: int,
    ag: int,
) -> None:
    for team in (home, away):
        table[team]["played"] += 1
    table[home]["gf"] += hg
    table[home]["ga"] += ag
    table[away]["gf"] += ag
    table[away]["ga"] += hg
    if hg > ag:
        table[home]["w"] += 1
        table[home]["pts"] += 3
        table[away]["l"] += 1
    elif ag > hg:
        table[away]["w"] += 1
        table[away]["pts"] += 3
        table[home]["l"] += 1
    else:
        table[home]["d"] += 1
        table[away]["d"] += 1
        table[home]["pts"] += 1
        table[away]["pts"] += 1
    for team in (home, away):
        table[team]["gd"] = table[team]["gf"] - table[team]["ga"]


def run_group_match(tournament_id: str, match_id: str) -> dict[str, Any]:
    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    found = _find_fixture(t, match_id)
    if not found or found[0] == "knockout":
        raise KeyError(f"Group fixture '{match_id}' not found")
    gkey, fx = found
    if fx.get("played"):
        raise ValueError(f"Match {match_id} already played")

    n_sims = int(t["settings"].get("simulations_per_match", 10000))
    report, snapshot = _run_simulation(fx["home"], fx["away"], match_id, n_sims)
    winner = _resolve_winner(
        fx["home"], fx["away"], snapshot["home_goals"], snapshot["away_goals"], report, require_winner=False
    )

    result_id = match_id
    t["match_results"][result_id] = {
        "match_id": match_id,
        "stage": "group",
        "group": gkey,
        "home": fx["home"],
        "away": fx["away"],
        **snapshot,
        "winner": winner,
        "played_at": _now(),
    }

    fx["played"] = True
    fx["result_id"] = result_id
    fx["score"] = snapshot["score"]
    fx["winner"] = winner

    _apply_group_result(
        t["groups"][gkey]["table"],
        fx["home"],
        fx["away"],
        snapshot["home_goals"],
        snapshot["away_goals"],
    )
    save_tournament(t)
    return {"tournament": _summary(t) | {"id": t["id"]}, "result": t["match_results"][result_id]}


def _qualified_teams(t: dict[str, Any]) -> list[tuple[str, str, int]]:
    """Return list of (team, group_key, rank) for qualifiers."""
    advance = int(t["settings"].get("advance_per_group", 2))
    out: list[tuple[str, str, int]] = []
    for gkey, group in sorted(t.get("groups", {}).items()):
        ranked = _sort_standings(group["table"])
        for rank, team in enumerate(ranked[:advance], start=1):
            out.append((team, gkey, rank))
    return out


def _knockout_round_names(n_teams: int) -> list[str]:
    if n_teams <= 2:
        return ["Final"]
    if n_teams <= 4:
        return ["SF", "Final"]
    if n_teams <= 8:
        return ["QF", "SF", "Final"]
    return ["R16", "QF", "SF", "Final"]


def _pair_crossover(qualifiers: list[tuple[str, str, int]]) -> list[tuple[str, str]]:
    by_group: dict[str, list[tuple[str, int]]] = {}
    for team, gkey, rank in qualifiers:
        by_group.setdefault(gkey, []).append((team, rank))
    groups = sorted(by_group.keys())
    pairs: list[tuple[str, str]] = []
    if len(groups) >= 2:
        half = len(groups) // 2
        for i in range(half):
            g1 = groups[i]
            g2 = groups[len(groups) - 1 - i]
            r1 = sorted(by_group[g1], key=lambda x: x[1])
            r2 = sorted(by_group[g2], key=lambda x: x[1])
            if r1 and r2:
                pairs.append((r1[0][0], r2[-1][0]))
                if len(r1) > 1 and len(r2) > 1:
                    pairs.append((r2[0][0], r1[-1][0]))
    if not pairs:
        teams = [q[0] for q in qualifiers]
        for i in range(0, len(teams) - 1, 2):
            pairs.append((teams[i], teams[i + 1]))
    return pairs


def generate_knockout_bracket(tournament_id: str) -> dict[str, Any]:
    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    if t["status"] not in ("group_stage", "knockout"):
        raise ValueError("Complete group stage before knockout")

    qualifiers = _qualified_teams(t)
    if len(qualifiers) < 2:
        raise ValueError("Not enough qualified teams")

    pairs = _pair_crossover(qualifiers)
    n_first = len(pairs) * 2
    round_names = _knockout_round_names(n_first)
    first_name = round_names[0]

    ties: list[dict[str, Any]] = []
    for i, (home, away) in enumerate(pairs, start=1):
        ties.append(
            {
                "id": f"ko-{first_name.lower()}-{i}",
                "home": home,
                "away": away,
                "played": False,
                "winner": None,
                "score": None,
                "result_id": None,
                "feeds": None,
            }
        )

    rounds_out: list[dict[str, Any]] = [{"name": first_name, "ties": ties}]
    prev_ids = [tie["id"] for tie in ties]
    for rname in round_names[1:]:
        next_ties: list[dict[str, Any]] = []
        for j in range(0, len(prev_ids), 2):
            feeds = prev_ids[j : j + 2]
            next_ties.append(
                {
                    "id": f"ko-{rname.lower()}-{j // 2 + 1}",
                    "home": None,
                    "away": None,
                    "played": False,
                    "winner": None,
                    "score": None,
                    "result_id": None,
                    "feeds": feeds,
                }
            )
        rounds_out.append({"name": rname, "ties": next_ties})
        prev_ids = [tie["id"] for tie in next_ties]

    t["knockout"] = {
        "format": t["settings"].get("knockout_format", "single_elim"),
        "rounds": rounds_out,
    }
    t["status"] = "knockout"
    save_tournament(t)
    return t


def _advance_knockout_winner(t: dict[str, Any], tie: dict[str, Any], winner: str) -> None:
    tie_id = tie["id"]
    for rnd in t["knockout"]["rounds"]:
        for nxt in rnd.get("ties", []):
            feeds = nxt.get("feeds") or []
            if tie_id not in feeds:
                continue
            idx = feeds.index(tie_id)
            if idx == 0:
                nxt["home"] = winner
            else:
                nxt["away"] = winner


def run_knockout_match(tournament_id: str, match_id: str) -> dict[str, Any]:
    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    found = _find_fixture(t, match_id)
    if not found or found[0] != "knockout":
        raise KeyError(f"Knockout fixture '{match_id}' not found")
    _, tie = found
    if tie.get("played"):
        raise ValueError(f"Match {match_id} already played")
    if not tie.get("home") or not tie.get("away"):
        raise ValueError(f"Match {match_id} is not ready (missing teams)")

    n_sims = int(t["settings"].get("simulations_per_match", 10000))
    report, snapshot = _run_simulation(tie["home"], tie["away"], match_id, n_sims)
    winner = _resolve_winner(
        tie["home"],
        tie["away"],
        snapshot["home_goals"],
        snapshot["away_goals"],
        report,
        require_winner=True,
    )
    if not winner:
        winner = tie["home"]

    result_id = match_id
    t["match_results"][result_id] = {
        "match_id": match_id,
        "stage": "knockout",
        "home": tie["home"],
        "away": tie["away"],
        **snapshot,
        "winner": winner,
        "played_at": _now(),
    }

    tie["played"] = True
    tie["result_id"] = result_id
    tie["score"] = snapshot["score"]
    tie["winner"] = winner
    _advance_knockout_winner(t, tie, winner)

    all_done = all(
        tie.get("played")
        for rnd in t["knockout"]["rounds"]
        for tie in rnd.get("ties", [])
        if tie.get("home") and tie.get("away")
    )
    if all_done:
        t["status"] = "complete"
    save_tournament(t)
    return {"tournament": _summary(t) | {"id": t["id"]}, "result": t["match_results"][result_id]}


def set_status(tournament_id: str, status: str) -> dict[str, Any]:
    allowed = {"draft", "group_draw", "group_stage", "knockout", "complete"}
    if status not in allowed:
        raise ValueError(f"Invalid status: {status}")
    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    t["status"] = status
    save_tournament(t)
    return t


def update_settings(tournament_id: str, settings: dict[str, Any]) -> dict[str, Any]:
    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    if t["status"] != "draft":
        raise ValueError("Settings can only be changed in draft status")
    team_count = len(t.get("team_names") or [])
    if team_count < 2:
        raise ValueError("Add at least 2 teams before configuring groups")

    merged = {**t["settings"], **settings}
    if "group_count" in settings:
        merged = _settings_from_group_count(team_count, int(settings["group_count"]))
        merged["simulations_per_match"] = int(
            settings.get("simulations_per_match")
            or t["settings"].get("simulations_per_match", 10000)
        )
        merged["knockout_format"] = settings.get("knockout_format") or t["settings"].get(
            "knockout_format", "single_elim"
        )
    elif "teams_per_group" in settings:
        per_group = int(settings["teams_per_group"])
        if per_group < 2:
            raise ValueError("Each group needs at least 2 teams")
        if team_count % per_group != 0:
            raise ValueError(
                f"{team_count} teams do not divide evenly into groups of {per_group}"
            )
        merged = _settings_from_group_count(team_count, team_count // per_group)
        merged["simulations_per_match"] = int(
            settings.get("simulations_per_match")
            or t["settings"].get("simulations_per_match", 10000)
        )
        merged["knockout_format"] = settings.get("knockout_format") or t["settings"].get(
            "knockout_format", "single_elim"
        )
    else:
        _validate_group_settings(team_count, int(merged.get("group_count", 1)))

    t["settings"] = merged
    t["knockout"]["format"] = merged.get("knockout_format", "single_elim")
    save_tournament(t)
    return t
