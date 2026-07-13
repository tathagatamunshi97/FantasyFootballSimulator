"""Tournament storage, draw, fixtures, and match simulation."""
from __future__ import annotations

import json
import random
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models import FantasyTeam
from report_builder import build_board_result_report, build_report, extended_metrics, team_lineup_dict
from stats_resolver import prepare_match_player_stats
from team_profile import build_team_profile

from web.experiments import _apply_name_map, validate_team_payload
from web import matchday_session
from web.state import get_stats_store
from web.team_lineups import apply_team_lineup, clear_all_finalize_locks

ROOT = Path(__file__).resolve().parent.parent
TOURNAMENTS_DIR = ROOT / "data" / "tournaments"

GROUP_LETTERS = "ABCDEFGHIJKLMNOPQR"
VALID_KNOCKOUT_SIZES = (2, 4, 8, 16)
ROUND_LABELS = {
    "R16": "Round of 16",
    "QF": "Quarter-finals",
    "SF": "Semi-finals",
    "Final": "Final",
}


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
    advance = _default_advance_per_group(group_count, teams_per_group)
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


def valid_advance_per_group_options(group_count: int, teams_per_group: int) -> list[int]:
    """Values of advance_per_group that yield a valid single-elimination bracket."""
    return [
        a
        for a in range(1, teams_per_group + 1)
        if group_count * a in VALID_KNOCKOUT_SIZES
    ]


def _default_advance_per_group(group_count: int, teams_per_group: int) -> int:
    opts = valid_advance_per_group_options(group_count, teams_per_group)
    if not opts:
        return min(2, teams_per_group) if teams_per_group >= 4 else 1
    if 2 in opts:
        return 2
    return opts[-1]


def _validate_advance_per_group(
    group_count: int, teams_per_group: int, advance: int
) -> None:
    if advance < 1:
        raise ValueError("advance_per_group must be at least 1")
    if advance > teams_per_group:
        raise ValueError(
            f"Cannot advance {advance} teams from groups of {teams_per_group}"
        )
    total = group_count * advance
    if total not in VALID_KNOCKOUT_SIZES:
        raise ValueError(
            f"{advance} per group → {total} knockout teams; "
            "must be 2, 4, 8, or 16 for a single-elimination bracket"
        )


def knockout_bracket_preview(group_count: int, advance_per_group: int) -> dict[str, Any]:
    """Preview knockout size and round names for admin UI."""
    total = group_count * advance_per_group
    short_names = _knockout_round_short_names(total)
    return {
        "group_count": group_count,
        "advance_per_group": advance_per_group,
        "knockout_teams": total,
        "rounds": [
            {"name": s, "label": ROUND_LABELS.get(s, s)} for s in short_names
        ],
    }


def _settings_from_group_count(
    team_count: int,
    group_count: int,
    advance_per_group: int | None = None,
) -> dict[str, Any]:
    _validate_group_settings(team_count, group_count)
    teams_per_group = team_count // group_count
    if advance_per_group is not None:
        try:
            _validate_advance_per_group(group_count, teams_per_group, advance_per_group)
            advance = advance_per_group
        except ValueError:
            advance = _default_advance_per_group(group_count, teams_per_group)
    else:
        advance = _default_advance_per_group(group_count, teams_per_group)
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
        "player_tallies": [],
        "top_goalscorers": [],
        "top_assisters": [],
    }


def save_tournament(t: dict[str, Any]) -> None:
    TOURNAMENTS_DIR.mkdir(parents=True, exist_ok=True)
    t["updated_at"] = _now()

    # Save to R2 if enabled (primary storage on Render)
    try:
        import r2_storage
        if r2_storage.is_r2_enabled():
            r2_storage.save_tournament_metadata(t["id"], t)
    except (ImportError, Exception):
        pass

    # Always save to JSON as fallback
    _tournament_path(t["id"]).write_text(
        json.dumps(t, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_tournament(tournament_id: str) -> dict[str, Any] | None:
    # Try R2 first (if enabled)
    try:
        import r2_storage
        if r2_storage.is_r2_enabled():
            data = r2_storage.load_tournament_metadata(tournament_id)
            if data:
                return data
    except (ImportError, Exception):
        pass

    # Fall back to JSON
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
    rows: list[dict[str, Any]] = []

    # Try R2 first (if enabled)
    try:
        import r2_storage
        if r2_storage.is_r2_enabled():
            tournament_ids = r2_storage.list_tournament_ids()
            for tournament_id in tournament_ids:
                t = load_tournament(tournament_id)
                if t:
                    rows.append(_summary(t))
            if rows:
                rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
                return rows
    except (ImportError, Exception):
        pass

    # Fall back to JSON directory
    if not TOURNAMENTS_DIR.exists():
        return []
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
    # Round keys reuse group:X:N across tournaments — clear old finalize locks
    # so squads are editable for the new competition.
    clear_all_finalize_locks()
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
    # Regenerated fixtures restart at matchday 1 with the same round_key shape
    # (group:A:1, …). Clear finalize locks so prior-tournament locks do not stick.
    clear_all_finalize_locks()
    return t


ACTIVE_TOURNAMENT_STATUSES = ("group_stage", "knockout")


def fixture_round_key(stage_key: str, fx: dict[str, Any], *, knockout_round_name: str | None = None) -> str:
    if stage_key == "knockout":
        label = knockout_round_name or fx.get("round") or "KO"
        return f"knockout:{label}"
    return f"group:{stage_key}:{int(fx.get('round') or 1)}"


def find_active_tournament_for_team(team_name: str) -> dict[str, Any] | None:
    """Most recently updated in-progress tournament containing the team."""
    needle = team_name.strip().lower()
    candidates: list[dict[str, Any]] = []

    for summary in list_tournaments():
        try:
            t = load_tournament(summary["id"])
            if not t:
                continue
            if t.get("status") not in ACTIVE_TOURNAMENT_STATUSES:
                continue
            names = [n.strip().lower() for n in t.get("team_names") or []]
            if needle in names:
                candidates.append(t)
        except Exception as exc:
            # One malformed tournament document must not break lookups for every team.
            print(f"Tournament: skipping malformed tournament {summary.get('id')!r}: {exc}")
            continue

    if not candidates:
        return None
    candidates.sort(key=lambda row: row.get("updated_at") or "", reverse=True)
    return candidates[0]


_READY_ROUND = {
    "round_key": "ready",
    "label": "Ready (no active tournament)",
    "tournament_id": None,
    "tournament_name": None,
}


def get_team_immediate_round(team_name: str, tournament: dict[str, Any] | None = None) -> dict[str, Any]:
    """Round context a team should finalize for (next unplayed group matchday or KO tie).

    Never raises — a malformed tournament document must degrade to "ready" rather
    than break squad-hub lineup loading/saving for every team.
    """
    try:
        t = tournament or find_active_tournament_for_team(team_name)
        if not t:
            return dict(_READY_ROUND)

        name = team_name.strip()
        best: dict[str, Any] | None = None

        for gkey, group in (t.get("groups") or {}).items():
            for fx in group.get("fixtures") or []:
                if fx.get("played"):
                    continue
                if name not in (fx.get("home"), fx.get("away")):
                    continue
                rnd = int(fx.get("round") or 1)
                if best is None or rnd < best["round"]:
                    best = {
                        "round_key": fixture_round_key(gkey, fx),
                        "label": f"Group {gkey.upper()} · Matchday {rnd}",
                        "round": rnd,
                        "stage": "group",
                        "group": gkey,
                        "tournament_id": t["id"],
                        "tournament_name": t.get("name"),
                    }

        if best:
            return best

        for rnd in (t.get("knockout") or {}).get("rounds") or []:
            rname = rnd.get("name") or rnd.get("short") or "KO"
            for tie in rnd.get("ties") or []:
                if tie.get("played"):
                    continue
                if name not in (tie.get("home"), tie.get("away")):
                    continue
                return {
                    "round_key": fixture_round_key("knockout", tie, knockout_round_name=rname),
                    "label": str(rname),
                    "round": rname,
                    "stage": "knockout",
                    "tournament_id": t["id"],
                    "tournament_name": t.get("name"),
                }

        return {
            "round_key": "ready",
            "label": "Awaiting next stage",
            "tournament_id": t.get("id"),
            "tournament_name": t.get("name"),
        }
    except Exception as exc:
        print(f"Tournament: get_team_immediate_round({team_name!r}) failed, defaulting to ready: {exc}")
        return dict(_READY_ROUND)


def resolve_fixture_round_key(
    tournament_id: str | None,
    match_id: str | None,
    *,
    home_name: str | None = None,
    away_name: str | None = None,
) -> str | None:
    """Round key for a tournament fixture (by id or home/away pairing)."""
    tournaments: list[dict[str, Any]] = []
    if tournament_id:
        t = load_tournament(tournament_id)
        if t:
            tournaments.append(t)
    else:
        if not TOURNAMENTS_DIR.exists():
            return None
        for path in TOURNAMENTS_DIR.glob("*.json"):
            try:
                tournaments.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue

    for t in tournaments:
        if match_id:
            found = _find_fixture(t, match_id)
            if found:
                stage_key, fx = found
                if stage_key == "knockout":
                    for rnd in (t.get("knockout") or {}).get("rounds") or []:
                        for tie in rnd.get("ties") or []:
                            if tie.get("id") == match_id:
                                rname = rnd.get("name") or rnd.get("short") or "KO"
                                return fixture_round_key("knockout", tie, knockout_round_name=rname)
                return fixture_round_key(stage_key, fx)

        if home_name and away_name:
            for gkey, group in (t.get("groups") or {}).items():
                for fx in group.get("fixtures") or []:
                    if fx.get("home") == home_name and fx.get("away") == away_name:
                        return fixture_round_key(gkey, fx)
            for rnd in (t.get("knockout") or {}).get("rounds") or []:
                rname = rnd.get("name") or rnd.get("short") or "KO"
                for tie in rnd.get("ties") or []:
                    if tie.get("home") == home_name and tie.get("away") == away_name:
                        return fixture_round_key("knockout", tie, knockout_round_name=rname)
    return None


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


def _load_teams_for_match(
    home_name: str,
    away_name: str,
    *,
    tournament_id: str | None = None,
    match_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from formation_fit import DEFAULT_FORMATION
    from google_sheets_teams import load_team_by_name

    store = get_stats_store()
    for name in (home_name, away_name):
        draft = load_team_by_name(name, formation=DEFAULT_FORMATION, store=store)
        meta = draft.get("sheet_meta") or {}
        if not meta.get("ready"):
            count = meta.get("player_count", "?")
            raise ValueError(
                f"Team '{draft.get('name')}' has {count}/11 players on the sheet. "
                "Each team needs at least 11 players."
            )
        # Warm from disk/seed only — never live-fetch (Render has no Chrome).
        roster = meta.get("full_roster") or meta.get("roster_players") or [
            (r.get("player") or "").strip()
            for r in draft.get("lineup", [])
            if (r.get("player") or "").strip()
        ]
        if roster:
            store.cached_stats_map(roster)

    round_key = resolve_fixture_round_key(
        tournament_id,
        match_id,
        home_name=home_name,
        away_name=away_name,
    )
    home_round = round_key or get_team_immediate_round(home_name).get("round_key")
    away_round = round_key or get_team_immediate_round(away_name).get("round_key")

    team_a = apply_team_lineup(
        load_team_by_name(home_name, formation=DEFAULT_FORMATION, store=store),
        round_key=home_round,
    )
    team_b = apply_team_lineup(
        load_team_by_name(away_name, formation=DEFAULT_FORMATION, store=store),
        round_key=away_round,
    )
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


def _score_from_report(report: dict[str, Any]) -> tuple[int, int, str]:
    """Official fixture score = most common Monte Carlo scoreline."""
    mc = report.get("monte_carlo") or {}
    scorelines = mc.get("most_common_scorelines") or mc.get("scorelines") or []
    if scorelines:
        top = scorelines[0]
        score_str = str(top.get("score") or "0-0")
        parts = score_str.split("-")
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1]), score_str
            except ValueError:
                pass
    sample = report.get("sample_match") or {}
    home_goals = int(sample.get("home", {}).get("goals", 0))
    away_goals = int(sample.get("away", {}).get("goals", 0))
    return home_goals, away_goals, f"{home_goals}-{away_goals}"


_ANALYSIS_RESULT_KEYS = ("analysis", "squad_analysis", "analysis_matchup")
_BOARD_LOG_KEYS = ("board_events", "match_log")
# Bump when formation_fit / slot-fit narrative must invalidate persisted match analysis.
_FIT_FORMULA_VERSION = 3

# Background analysis builds — avoid holding HTTP past Render's proxy timeout (~30s).
_analysis_jobs: dict[str, dict[str, Any]] = {}
_analysis_jobs_lock = threading.Lock()


def _analysis_job_key(tournament_id: str, match_id: str) -> str:
    return f"{tournament_id}:{match_id}"


def _analysis_payload_from_report(report: dict[str, Any]) -> dict[str, Any]:
    """Persistable analysis fields — same payloads lab experiments store on the report."""
    return {
        "analysis": report.get("analysis"),
        "squad_analysis": report.get("squad_analysis"),
        "analysis_matchup": report.get("matchup"),
        "fit_formula_version": _FIT_FORMULA_VERSION,
    }


def _result_has_analysis(result: dict[str, Any] | None) -> bool:
    return bool(result and isinstance(result.get("analysis"), dict) and result["analysis"])


def _analysis_needs_rebuild(result: dict[str, Any] | None) -> bool:
    if not _result_has_analysis(result):
        return True
    return int((result or {}).get("fit_formula_version") or 0) < _FIT_FORMULA_VERSION


def match_result_for_api(result: dict[str, Any]) -> dict[str, Any]:
    """Strip heavy analysis blobs from list/poll payloads; expose has_analysis flag."""
    skip = set(_ANALYSIS_RESULT_KEYS) | set(_BOARD_LOG_KEYS)
    out = {k: v for k, v in result.items() if k not in skip}
    out["has_analysis"] = _result_has_analysis(result)
    return out


def _board_events_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull match events from a stored result (board_events or match_log)."""
    events = result.get("board_events")
    if isinstance(events, list):
        return [e for e in events if isinstance(e, dict)]
    log = result.get("match_log")
    if isinstance(log, dict):
        if isinstance(log.get("events"), list):
            return [e for e in log["events"] if isinstance(e, dict)]
        goals = log.get("goals")
        if isinstance(goals, list):
            out: list[dict[str, Any]] = []
            for g in goals:
                if isinstance(g, dict):
                    out.append({"type": "goal", **g})
            return out
    return []


def _bump_player_tally(
    tallies: dict[str, dict[str, Any]],
    *,
    player: str,
    team: str,
    field: str,
) -> None:
    key = f"{team}\0{player}"
    row = tallies.get(key)
    if not row:
        row = {"player": player, "team": team, "goals": 0, "assists": 0}
        tallies[key] = row
    row[field] = int(row.get(field) or 0) + 1


def aggregate_player_tallies(t: dict[str, Any]) -> list[dict[str, Any]]:
    """Sum goals/assists per player across all completed matches with board events."""
    tallies: dict[str, dict[str, Any]] = {}
    for result in (t.get("match_results") or {}).values():
        if not isinstance(result, dict):
            continue
        home = result.get("home")
        away = result.get("away")
        for ev in _board_events_from_result(result):
            side = ev.get("side")
            team = home if side == "home" else away if side == "away" else None
            if not team:
                continue
            if ev.get("type") != "goal":
                continue
            player = str(ev.get("player") or "").strip()
            if player:
                _bump_player_tally(tallies, player=player, team=str(team), field="goals")
            # Assist attributed on the goal event (last passer before shot).
            assist = str(ev.get("assist") or ev.get("assist_player") or "").strip()
            if assist and assist != player:
                _bump_player_tally(tallies, player=assist, team=str(team), field="assists")
    return sorted(
        tallies.values(),
        key=lambda r: (-int(r["goals"]), -int(r["assists"]), str(r["player"]).lower()),
    )


def player_leaderboards(t: dict[str, Any], *, limit: int = 10) -> dict[str, Any]:
    """Top goalscorers / assisters for tournament API + persisted state."""
    tallies = aggregate_player_tallies(t)
    scorers = sorted(
        [r for r in tallies if int(r.get("goals") or 0) > 0],
        key=lambda r: (-int(r["goals"]), str(r["player"]).lower()),
    )
    assisters = sorted(
        [r for r in tallies if int(r.get("assists") or 0) > 0],
        key=lambda r: (-int(r["assists"]), str(r["player"]).lower()),
    )

    def _top(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(rows) <= limit:
            return rows
        return rows[:limit]

    return {
        "player_tallies": tallies,
        "top_goalscorers": _top(scorers),
        "top_assisters": _top(assisters),
    }


def _refresh_player_tallies(t: dict[str, Any]) -> None:
    """Persist leaderboard snapshot on the tournament document."""
    boards = player_leaderboards(t)
    t["player_tallies"] = boards["player_tallies"]
    t["top_goalscorers"] = boards["top_goalscorers"]
    t["top_assisters"] = boards["top_assisters"]


def tournament_for_api(t: dict[str, Any]) -> dict[str, Any]:
    mrs = t.get("match_results") or {}
    boards = player_leaderboards(t)
    return {
        **t,
        "match_results": {k: match_result_for_api(v) for k, v in mrs.items()},
        **boards,
    }


def _import_analysis_from_experiment(result: dict[str, Any]) -> bool:
    """Copy analysis from the linked experiment report if still available."""
    eid = result.get("experiment_id")
    if not eid:
        return False
    from web import experiments

    exp = experiments.load_experiment(str(eid))
    report = (exp or {}).get("report") or {}
    if not isinstance(report.get("analysis"), dict) or not report["analysis"]:
        return False
    result.update(_analysis_payload_from_report(report))
    return True


def _run_simulation(
    home_name: str,
    away_name: str,
    match_id: str,
    n_simulations: int,
    *,
    team_a: dict[str, Any] | None = None,
    team_b: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if team_a is None or team_b is None:
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
    home_goals, away_goals, score_str = _score_from_report(report)
    mc = report.get("monte_carlo") or {}
    top_scorelines = mc.get("most_common_scorelines") or mc.get("scorelines") or []
    snapshot = {
        "score": score_str,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "expected_xg": mc.get("expected_xg"),
        "home_win_pct": mc.get("home_win_pct"),
        "away_win_pct": mc.get("away_win_pct"),
        "draw_pct": mc.get("draw_pct"),
        "simulations": n_simulations,
        "mode_scoreline": top_scorelines[0] if top_scorelines else None,
        "top_scorelines": top_scorelines[:5],
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


def _finalize_experiment_from_report(exp: dict[str, Any], report: dict[str, Any]) -> None:
    from web import experiments

    exp["status"] = "ready"
    exp["running"] = False
    exp["message"] = f"Completed {exp['simulations']:,} simulations."
    exp["report"] = report
    experiments.save_experiment(exp)


def _run_group_match_job(
    tournament_id: str,
    match_id: str,
    exp: dict[str, Any],
) -> None:
    from web import experiments

    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    found = _find_fixture(t, match_id)
    if not found or found[0] == "knockout":
        raise KeyError(f"Group fixture '{match_id}' not found")
    gkey, fx = found
    if fx.get("played"):
        raise ValueError(f"Match {match_id} already played")

    n_sims = int(exp["simulations"])
    exp["message"] = "Loading player stats…"
    experiments.save_experiment(exp)

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
        **_analysis_payload_from_report(report),
        "engine_home_goals": snapshot["home_goals"],
        "engine_away_goals": snapshot["away_goals"],
        "winner": winner,
        "manually_overridden": False,
        "admin_accepted": False,
        "played_at": _now(),
        "experiment_id": exp["id"],
    }

    fx["played"] = True
    fx["result_id"] = result_id
    fx["score"] = snapshot["score"]
    fx["winner"] = winner
    fx["experiment_id"] = exp["id"]

    _apply_group_result(
        t["groups"][gkey]["table"],
        fx["home"],
        fx["away"],
        snapshot["home_goals"],
        snapshot["away_goals"],
    )
    save_tournament(t)
    _finalize_experiment_from_report(exp, report)
    matchday_session.set_result(
        {
            "score": snapshot["score"],
            "home_goals": snapshot["home_goals"],
            "away_goals": snapshot["away_goals"],
            "winner": winner,
            "home_win_pct": snapshot.get("home_win_pct"),
            "draw_pct": snapshot.get("draw_pct"),
            "away_win_pct": snapshot.get("away_win_pct"),
            "mode_scoreline": snapshot.get("mode_scoreline"),
            "top_scorelines": snapshot.get("top_scorelines"),
            "experiment_id": exp["id"],
        },
        experiment_id=exp["id"],
    )


def _run_knockout_match_job(
    tournament_id: str,
    match_id: str,
    exp: dict[str, Any],
) -> None:
    from web import experiments

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

    n_sims = int(exp["simulations"])
    exp["message"] = "Loading player stats…"
    experiments.save_experiment(exp)

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
        **_analysis_payload_from_report(report),
        "engine_home_goals": snapshot["home_goals"],
        "engine_away_goals": snapshot["away_goals"],
        "winner": winner,
        "manually_overridden": False,
        "admin_accepted": False,
        "played_at": _now(),
        "experiment_id": exp["id"],
    }

    tie["played"] = True
    tie["result_id"] = result_id
    tie["score"] = snapshot["score"]
    tie["winner"] = winner
    tie["experiment_id"] = exp["id"]
    _advance_knockout_winner(t, tie, winner)

    all_done = all(
        t2.get("played")
        for rnd in t["knockout"]["rounds"]
        for t2 in rnd.get("ties", [])
        if t2.get("home") and t2.get("away")
    )
    if all_done:
        t["status"] = "complete"
    save_tournament(t)
    _finalize_experiment_from_report(exp, report)
    matchday_session.set_result(
        {
            "score": snapshot["score"],
            "home_goals": snapshot["home_goals"],
            "away_goals": snapshot["away_goals"],
            "winner": winner,
            "home_win_pct": snapshot.get("home_win_pct"),
            "draw_pct": snapshot.get("draw_pct"),
            "away_win_pct": snapshot.get("away_win_pct"),
            "mode_scoreline": snapshot.get("mode_scoreline"),
            "top_scorelines": snapshot.get("top_scorelines"),
            "experiment_id": exp["id"],
        },
        experiment_id=exp["id"],
    )


def _preflight_match_stats(team_a: dict[str, Any], team_b: dict[str, Any]) -> None:
    """Fail fast before starting a background run if stats cannot be loaded."""
    store = get_stats_store()
    try:
        # Always cache/manual-only on tournament hosts (no Chrome on Render).
        prepare_match_player_stats(team_a, team_b, store, cache_only=True)
    except Exception as exc:
        msg = str(exc).strip()
        if "Chrome not found" in msg or "Install it first" in msg.lower():
            raise ValueError(
                "Cannot load player stats for this fixture: a live stats scrape "
                "was attempted but Chrome is unavailable. Ensure prime/peak "
                "players have manual profiles (or clear the prime) and redeploy."
            ) from exc
        raise ValueError(f"Cannot load player stats for this fixture: {exc}") from exc


def start_matchday_session(tournament_id: str, match_id: str) -> dict[str, Any]:
    """Create a live matchday broadcast session for a tournament fixture (setup phase)."""
    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    found = _find_fixture(t, match_id)
    if not found:
        raise KeyError(f"Fixture '{match_id}' not found")
    stage_key, fx = found
    if fx.get("played"):
        raise ValueError(f"Match {match_id} already played")
    if stage_key == "knockout" and (not fx.get("home") or not fx.get("away")):
        raise ValueError(f"Match {match_id} is not ready (missing teams)")

    home = fx["home"]
    away = fx["away"]
    team_a, team_b = _load_teams_for_match(home, away, tournament_id=tournament_id, match_id=match_id)
    _preflight_match_stats(team_a, team_b)
    stage = f"group_{stage_key}" if stage_key != "knockout" else "knockout"

    status = matchday_session.start_session(
        tournament_id=tournament_id,
        tournament_name=t.get("name") or "Tournament",
        fixture_id=match_id,
        stage=stage,
        home=home,
        away=away,
        team_a=team_a,
        team_b=team_b,
    )
    return {
        "tournament": _summary(t) | {"id": t["id"]},
        "matchday": status,
        "status": "setup",
    }


def execute_matchday_simulation() -> dict[str, Any]:
    """Run Monte Carlo simulation for the active matchday session (admin, run phase)."""
    from web import experiments

    session = matchday_session.require_active_session()
    if session.get("phase") not in ("setup", "running"):
        raise ValueError(f"Cannot run simulation in phase '{session.get('phase')}'.")
    if session.get("running"):
        raise ValueError("Simulation already running.")

    tournament_id = session["tournament_id"]
    match_id = session["fixture_id"]
    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")

    team_a, team_b = _load_teams_for_match(
        session["home"],
        session["away"],
        tournament_id=tournament_id,
        match_id=match_id,
    )
    _preflight_match_stats(team_a, team_b)
    n_sims = int(t["settings"].get("simulations_per_match", 10000))
    payload = {"team_a": team_a, "team_b": team_b, "simulations": n_sims}

    found = _find_fixture(t, match_id)
    if not found:
        raise KeyError(f"Fixture '{match_id}' not found")
    stage_key, _ = found
    stage = f"group_{stage_key}" if stage_key != "knockout" else "knockout"

    if stage_key == "knockout":
        run_fn = lambda exp: _run_knockout_match_job(tournament_id, match_id, exp)
    else:
        run_fn = lambda exp: _run_group_match_job(tournament_id, match_id, exp)

    summary = experiments.start_matchday_run(
        "admin",
        payload,
        tournament={
            "tournament_id": tournament_id,
            "tournament_name": t.get("name"),
            "match_id": match_id,
            "stage": stage,
        },
        run_fn=run_fn,
    )
    matchday_session.set_running(summary["id"])
    return {
        "experiment": summary,
        "matchday": matchday_session.active_status(),
        "status": "running",
    }


def _board_side_payload(team: FantasyTeam, player_stats: dict[str, Any]) -> dict[str, Any]:
    """Lineup + per-player board stats + unit ratings for the tactic board."""
    profile = build_team_profile(team, player_stats)
    extended = extended_metrics(team, player_stats)
    by_name = {p["player"]: p for p in profile.players}
    lineup = []
    for row in team_lineup_dict(team)["lineup"]:
        st = by_name.get(row["player"]) or {}
        lineup.append(
            {
                **row,
                "stats": {
                    "dribbles90": st.get("dribbles90", 0),
                    "dribble_pct": st.get("dribble_pct", 50),
                    "key_passes90": st.get("key_passes90", 0),
                    "xa90": st.get("xa90", 0),
                    "xg90": st.get("xg90", 0),
                    "npxg90": st.get("npxg90", 0),
                    "goals90": st.get("goals90", 0),
                    "shots90": st.get("shots90", 0),
                    "shots_on_target90": st.get("shots_on_target90", 0),
                    "understat_shots90": st.get("understat_shots90", 0),
                    "aerials_won90": st.get("aerials_won90", 0),
                    "aerials_won_pct": st.get("aerials_won_pct", 0),
                    "tackles90": st.get("tackles90", 0),
                    "interceptions90": st.get("interceptions90", 0),
                    "pass_pct": st.get("pass_pct", 75),
                },
            }
        )
    return {
        "name": team.name,
        "formation": team.formation,
        "lineup": lineup,
        "_unit": {
            "pressing_intensity": extended.get("pressing_intensity"),
            "press_resistance": extended.get("press_resistance"),
            "attacking_effectiveness": extended.get("attacking_effectiveness"),
            "finishing_threat": extended.get("finishing_threat"),
            "defensive_unit": extended.get("defensive_unit"),
            "xga_suppression": extended.get("xga_suppression"),
            "chance_creation": extended.get("chance_creation"),
            "possession_control": extended.get("possession_control"),
            "aerial_defence": extended.get("aerial_defence"),
            "attack": extended.get("attack") or (extended.get("units") or {}).get("attack"),
            "defence": extended.get("defence") or (extended.get("units") or {}).get("defence"),
            "midfield": extended.get("midfield") or (extended.get("units") or {}).get("midfield"),
            "midfield_defence": (extended.get("units") or {}).get("midfield_defence"),
            "finishing": (extended.get("units") or {}).get("finishing"),
            "goalkeeper": (extended.get("units") or {}).get("goalkeeper"),
        },
    }


def prepare_board_match(tournament_id: str, match_id: str) -> dict[str, Any]:
    """Load teams + stats, open Matchday session, redirect everyone to /matchday."""
    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    found = _find_fixture(t, match_id)
    if not found:
        raise KeyError(f"Fixture '{match_id}' not found")
    stage_key, fx = found
    if fx.get("played"):
        raise ValueError(f"Match {match_id} already played")
    if stage_key == "knockout" and (not fx.get("home") or not fx.get("away")):
        raise ValueError(f"Match {match_id} is not ready (missing teams)")

    home = fx["home"]
    away = fx["away"]
    team_a, team_b = _load_teams_for_match(
        home, away, tournament_id=tournament_id, match_id=match_id
    )
    _preflight_match_stats(team_a, team_b)
    store = get_stats_store()
    player_stats, _season_overrides, name_map = prepare_match_player_stats(
        team_a, team_b, store, cache_only=True
    )
    resolved = _apply_name_map({"team_a": team_a, "team_b": team_b}, name_map)
    home_team = FantasyTeam.from_dict(resolved["team_a"])
    away_team = FantasyTeam.from_dict(resolved["team_b"])
    home_payload = _board_side_payload(home_team, player_stats)
    away_payload = _board_side_payload(away_team, player_stats)
    stage = f"group_{stage_key}" if stage_key != "knockout" else "knockout"
    board = {
        "match_id": match_id,
        "home": home_payload,
        "away": away_payload,
        "unit_home": home_payload.get("_unit") or {},
        "unit_away": away_payload.get("_unit") or {},
    }
    # Prefer board payloads as the public XI on Matchday
    seed = abs(hash(f"{tournament_id}:{match_id}")) % (2**31)
    status = matchday_session.start_board_session(
        tournament_id=tournament_id,
        tournament_name=t.get("name") or "Tournament",
        fixture_id=match_id,
        stage=stage,
        home=home,
        away=away,
        team_a=home_payload,
        team_b=away_payload,
        board=board,
        seed=seed,
        is_knockout=stage_key == "knockout",
    )
    return {
        "status": "board_ready",
        "engine": "tactic_board",
        "redirect": "/matchday",
        "tournament_id": tournament_id,
        "match_id": match_id,
        "stage": stage,
        "stage_key": stage_key,
        "is_knockout": stage_key == "knockout",
        "home": home,
        "away": away,
        "board": board,
        "matchday": status,
        "tournament": _summary(t) | {"id": t["id"]},
    }


def _format_knockout_score(
    home_goals: int,
    away_goals: int,
    *,
    decided_by: str | None = None,
    pens_home: int | None = None,
    pens_away: int | None = None,
    score_display: str | None = None,
) -> str:
    """Human-readable KO scoreline: FT, AET, or pens."""
    if score_display and str(score_display).strip():
        return str(score_display).strip()
    base = f"{int(home_goals)}-{int(away_goals)}"
    if decided_by == "pens" and pens_home is not None and pens_away is not None:
        return f"{base} ({int(pens_home)}-{int(pens_away)} pens)"
    if decided_by == "aet":
        return f"{base} AET"
    return base


def complete_from_board(
    tournament_id: str,
    match_id: str,
    home_goals: int,
    away_goals: int,
    winner: str | None = None,
    board_events: list[dict[str, Any]] | None = None,
    match_log: list[dict[str, Any]] | dict[str, Any] | None = None,
    *,
    decided_by: str | None = None,
    ft_home_goals: int | None = None,
    ft_away_goals: int | None = None,
    pens_home: int | None = None,
    pens_away: int | None = None,
    score_display: str | None = None,
) -> dict[str, Any]:
    """Persist official result from the tactic-board pin score (skips Monte Carlo)."""
    if home_goals < 0 or away_goals < 0:
        raise ValueError("Goals must be non-negative")

    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    found = _find_fixture(t, match_id)
    if not found:
        raise KeyError(f"Fixture '{match_id}' not found")
    stage_key, fx = found
    if fx.get("played"):
        raise ValueError(f"Match {match_id} already played")
    if stage_key == "knockout" and (not fx.get("home") or not fx.get("away")):
        raise ValueError(f"Match {match_id} is not ready (missing teams)")

    is_knockout = stage_key == "knockout"
    home = fx["home"]
    away = fx["away"]

    decided = (decided_by or "").strip().lower() or None
    if decided not in (None, "ft", "aet", "pens"):
        decided = None

    ph = int(pens_home) if pens_home is not None else None
    pa = int(pens_away) if pens_away is not None else None
    ft_h = int(ft_home_goals) if ft_home_goals is not None else None
    ft_a = int(ft_away_goals) if ft_away_goals is not None else None

    if winner is not None:
        winner = str(winner).strip()
        if winner and winner not in (home, away):
            raise ValueError(f"Winner must be '{home}' or '{away}'")

    if is_knockout:
        if home_goals != away_goals:
            resolved = home if home_goals > away_goals else away
            if winner in (home, away) and winner != resolved:
                raise ValueError(
                    f"Winner '{winner}' does not match scoreline {home_goals}-{away_goals}"
                )
            winner = resolved
            if not decided:
                decided = "aet" if (ft_h is not None and ft_a is not None and (ft_h != home_goals or ft_a != away_goals)) else "ft"
        elif decided == "pens" and ph is not None and pa is not None:
            if ph == pa:
                raise ValueError("Penalty shoot-out must have a winner")
            winner = home if ph > pa else away
        elif winner in (home, away):
            if not decided:
                decided = "pens" if ph is not None and pa is not None else "aet"
        else:
            # Legacy fallback — prefer home if board omitted pens winner
            winner = home
            if not decided:
                decided = "pens" if ph is not None else "aet"
    else:
        if home_goals > away_goals:
            winner = home
        elif away_goals > home_goals:
            winner = away
        else:
            winner = None
        decided = None

    stored_events: list[dict[str, Any]] | None = None
    stored_log: dict[str, Any] | list[dict[str, Any]] | None = None
    if isinstance(board_events, list) and board_events:
        stored_events = [e for e in board_events if isinstance(e, dict)]
    if isinstance(match_log, dict) and match_log:
        stored_log = match_log
        if not stored_events and isinstance(match_log.get("events"), list):
            stored_events = [e for e in match_log["events"] if isinstance(e, dict)]
    elif isinstance(match_log, list) and match_log:
        stored_events = stored_events or [e for e in match_log if isinstance(e, dict)]
        stored_log = {"events": stored_events, "goals": [e for e in stored_events if e.get("type") == "goal"]}

    if is_knockout:
        score = _format_knockout_score(
            home_goals,
            away_goals,
            decided_by=decided,
            pens_home=ph,
            pens_away=pa,
            score_display=score_display,
        )
    else:
        score = f"{home_goals}-{away_goals}"

    result_id = match_id
    result: dict[str, Any] = {
        "match_id": match_id,
        "stage": "knockout" if is_knockout else "group",
        "home": home,
        "away": away,
        "score": score,
        "home_goals": int(home_goals),
        "away_goals": int(away_goals),
        "engine": "tactic_board",
        "engine_home_goals": int(home_goals),
        "engine_away_goals": int(away_goals),
        "winner": winner,
        "manually_overridden": False,
        "admin_accepted": True,
        "admin_reviewed_at": _now(),
        "played_at": _now(),
        "simulations": 0,
    }
    if is_knockout and decided:
        result["decided_by"] = decided
    if ft_h is not None and ft_a is not None:
        result["ft_home_goals"] = ft_h
        result["ft_away_goals"] = ft_a
    if decided == "pens" and ph is not None and pa is not None:
        result["pens_home"] = ph
        result["pens_away"] = pa
    if stored_events:
        result["board_events"] = stored_events
    if stored_log is not None:
        result["match_log"] = stored_log
        if isinstance(stored_log, dict):
            live_xg = stored_log.get("xg") or stored_log.get("live_xg")
            if isinstance(live_xg, dict) and (
                live_xg.get("home") is not None or live_xg.get("away") is not None
            ):
                result["expected_xg"] = {
                    "home": round(float(live_xg.get("home") or 0), 2),
                    "away": round(float(live_xg.get("away") or 0), 2),
                }
            poss = stored_log.get("possession_pct") or stored_log.get("possession")
            if isinstance(poss, dict):
                result["possession_pct"] = {
                    "home": round(float(poss.get("home") or 0), 1),
                    "away": round(float(poss.get("away") or 0), 1),
                }
    elif stored_events:
        result["match_log"] = {
            "events": stored_events,
            "goals": [e for e in stored_events if e.get("type") == "goal"],
        }
    if not is_knockout:
        result["group"] = stage_key

    t["match_results"][result_id] = result
    fx["played"] = True
    fx["result_id"] = result_id
    fx["score"] = score
    fx["winner"] = winner
    if is_knockout and decided:
        fx["decided_by"] = decided

    if is_knockout:
        _advance_knockout_winner(t, fx, winner)
        all_done = all(
            t2.get("played")
            for rnd in t["knockout"]["rounds"]
            for t2 in rnd.get("ties", [])
            if t2.get("home") and t2.get("away")
        )
        t["status"] = "complete" if all_done else "knockout"
    else:
        _apply_group_result(
            t["groups"][stage_key]["table"],
            home,
            away,
            int(home_goals),
            int(away_goals),
        )
        if t.get("status") == "group_draw":
            t["status"] = "group_stage"

    # Analysis is deferred — built on first "See analysis" / Generate click, not at FT.
    _refresh_player_tallies(t)
    save_tournament(t)

    md_result: dict[str, Any] = {
        "match_id": match_id,
        "score": score,
        "home_goals": int(home_goals),
        "away_goals": int(away_goals),
        "winner": winner,
        "home": home,
        "away": away,
        "engine": "tactic_board",
        "tournament_id": tournament_id,
        "expected_xg": result.get("expected_xg"),
        "possession_pct": result.get("possession_pct"),
        "has_analysis": False,
    }
    if decided:
        md_result["decided_by"] = decided
    if ft_h is not None and ft_a is not None:
        md_result["ft_home_goals"] = ft_h
        md_result["ft_away_goals"] = ft_a
    if decided == "pens" and ph is not None and pa is not None:
        md_result["pens_home"] = ph
        md_result["pens_away"] = pa
    matchday_session.set_result(md_result)

    return {
        "tournament": tournament_for_api(t),
        "match": fx,
        "result": match_result_for_api(result),
        "stage": stage_key,
        "status": "complete",
        "engine": "tactic_board",
        "has_analysis": False,
        "analysis_ready": False,
        "matchday": matchday_session.active_status(),
    }


def _build_and_attach_board_analysis(
    t: dict[str, Any],
    result: dict[str, Any],
    *,
    tournament_id: str,
    match_id: str,
) -> dict[str, Any]:
    """Build ratings + board-event analysis and persist onto the match result."""
    home = result.get("home")
    away = result.get("away")
    if not home or not away:
        raise ValueError("Missing team names for analysis")

    team_a, team_b = _load_teams_for_match(
        home, away, tournament_id=tournament_id, match_id=match_id
    )
    store = get_stats_store()
    player_stats, season_overrides, name_map = prepare_match_player_stats(
        team_a, team_b, store, cache_only=True
    )
    resolved = _apply_name_map({"team_a": team_a, "team_b": team_b}, name_map)
    home_team = FantasyTeam.from_dict(resolved["team_a"])
    away_team = FantasyTeam.from_dict(resolved["team_b"])
    seed = abs(hash(match_id)) % (2**31)
    events = result.get("board_events")
    log = result.get("match_log")
    report = build_board_result_report(
        home_team,
        away_team,
        player_stats,
        home_goals=int(result.get("home_goals") or 0),
        away_goals=int(result.get("away_goals") or 0),
        board_events=events if isinstance(events, list) else None,
        match_log=log if isinstance(log, (list, dict)) else None,
        n_simulations=800,
        seed=seed,
        season_overrides=season_overrides,
    )
    result.update(_analysis_payload_from_report(report))
    return _analysis_response(result, match_id)


def run_group_match(tournament_id: str, match_id: str) -> dict[str, Any]:
    """Prepare interactive tactic-board match (official score from pins, not Monte Carlo)."""
    return prepare_board_match(tournament_id, match_id)


def run_knockout_match(tournament_id: str, match_id: str) -> dict[str, Any]:
    """Prepare interactive tactic-board knockout match (official score from pins)."""
    return prepare_board_match(tournament_id, match_id)


def _qualified_teams(t: dict[str, Any]) -> list[tuple[str, str, int]]:
    """Return list of (team, group_key, rank) for qualifiers."""
    advance = int(t["settings"].get("advance_per_group", 2))
    out: list[tuple[str, str, int]] = []
    for gkey, group in sorted(t.get("groups", {}).items()):
        ranked = _sort_standings(group["table"])
        for rank, team in enumerate(ranked[:advance], start=1):
            out.append((team, gkey, rank))
    return out


def _knockout_round_short_names(n_teams: int) -> list[str]:
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
            n = min(len(r1), len(r2))
            for j in range(n):
                pairs.append((r1[j][0], r2[n - 1 - j][0]))
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

    cfg = t["settings"]
    g_count = int(cfg["group_count"])
    per_group = int(cfg["teams_per_group"])
    advance = int(cfg.get("advance_per_group", 2))
    _validate_advance_per_group(g_count, per_group, advance)

    qualifiers = _qualified_teams(t)
    expected = g_count * advance
    if len(qualifiers) != expected:
        raise ValueError(
            f"Expected {expected} qualifiers ({advance} per group × {g_count} groups), "
            f"got {len(qualifiers)}"
        )

    pairs = _pair_crossover(qualifiers)
    n_first = len(pairs) * 2
    if n_first not in VALID_KNOCKOUT_SIZES:
        raise ValueError(f"Invalid knockout bracket size: {n_first} teams")
    round_names = _knockout_round_short_names(n_first)
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

    rounds_out: list[dict[str, Any]] = [
        {
            "name": first_name,
            "label": ROUND_LABELS.get(first_name, first_name),
            "ties": ties,
        }
    ]
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
        rounds_out.append(
            {
                "name": rname,
                "label": ROUND_LABELS.get(rname, rname),
                "ties": next_ties,
            }
        )
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


def _knockout_downstream_played(t: dict[str, Any], tie_id: str) -> bool:
    for rnd in t.get("knockout", {}).get("rounds", []):
        for nxt in rnd.get("ties", []):
            feeds = nxt.get("feeds") or []
            if tie_id in feeds and nxt.get("played"):
                return True
    return False


def _recompute_group_table(t: dict[str, Any], gkey: str) -> None:
    group = t["groups"][gkey]
    table = _empty_table(list(group.get("teams") or []))
    for fx in group.get("fixtures") or []:
        if not fx.get("played"):
            continue
        rid = fx.get("result_id") or fx.get("id")
        result = (t.get("match_results") or {}).get(rid) if rid else None
        if not result:
            continue
        _apply_group_result(
            table,
            fx["home"],
            fx["away"],
            int(result.get("home_goals", 0)),
            int(result.get("away_goals", 0)),
        )
    group["table"] = table


def _ensure_engine_score(result: dict[str, Any]) -> None:
    """Preserve original engine scoreline once for audit."""
    if "engine_home_goals" not in result:
        result["engine_home_goals"] = int(result.get("home_goals", 0))
    if "engine_away_goals" not in result:
        result["engine_away_goals"] = int(result.get("away_goals", 0))


def _tiebreak_report_from_result(result: dict[str, Any]) -> dict[str, Any]:
    """Minimal report so knockout draw overrides can reuse MC tiebreak."""
    return {
        "monte_carlo": {
            "home_win_pct": result.get("home_win_pct") or 0,
            "away_win_pct": result.get("away_win_pct") or 0,
            "expected_xg": result.get("expected_xg") or {},
        }
    }


def _analysis_response(result: dict[str, Any], match_id: str) -> dict[str, Any]:
    return {
        "match_id": match_id,
        "home": result.get("home"),
        "away": result.get("away"),
        "score": result.get("score"),
        "winner": result.get("winner"),
        "analysis": result.get("analysis"),
        "squad_analysis": result.get("squad_analysis"),
        "matchup": result.get("analysis_matchup"),
        "has_analysis": _result_has_analysis(result),
        "experiment_id": result.get("experiment_id"),
        "status": "ready",
    }


def _generating_analysis_response(
    result: dict[str, Any],
    match_id: str,
    *,
    message: str = "Generating analysis…",
) -> dict[str, Any]:
    return {
        "match_id": match_id,
        "home": result.get("home"),
        "away": result.get("away"),
        "score": result.get("score"),
        "winner": result.get("winner"),
        "analysis": None,
        "squad_analysis": None,
        "matchup": None,
        "has_analysis": False,
        "experiment_id": result.get("experiment_id"),
        "status": "generating",
        "message": message,
    }


def _error_analysis_response(
    result: dict[str, Any] | None,
    match_id: str,
    message: str,
) -> dict[str, Any]:
    return {
        "match_id": match_id,
        "home": (result or {}).get("home"),
        "away": (result or {}).get("away"),
        "score": (result or {}).get("score"),
        "winner": (result or {}).get("winner"),
        "analysis": None,
        "squad_analysis": None,
        "matchup": None,
        "has_analysis": False,
        "experiment_id": (result or {}).get("experiment_id"),
        "status": "error",
        "message": message,
    }


def _load_played_match_result(
    tournament_id: str, match_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return (tournament, fixture, result) for a completed match."""
    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    found = _find_fixture(t, match_id)
    if not found:
        raise KeyError(f"Fixture '{match_id}' not found")
    _, fx = found
    if not fx.get("played"):
        raise ValueError(f"Match {match_id} has not been played yet")
    result_id = fx.get("result_id") or match_id
    result = (t.get("match_results") or {}).get(result_id)
    if not result:
        raise KeyError(f"Result for '{match_id}' not found")
    return t, fx, result


def _build_and_persist_match_analysis(
    tournament_id: str,
    match_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """CPU-heavy build + disk persist. Run only from a background thread."""
    t, fx, result = _load_played_match_result(tournament_id, match_id)

    # Board-official matches: always (re)build ratings + board narrative when forced
    # or when missing/stale.
    if result.get("engine") == "tactic_board":
        if force or _analysis_needs_rebuild(result):
            _build_and_attach_board_analysis(
                t, result, tournament_id=tournament_id, match_id=match_id
            )
            result["fit_formula_version"] = _FIT_FORMULA_VERSION
            save_tournament(t)
        return _analysis_response(result, match_id)

    if not _result_has_analysis(result) and _import_analysis_from_experiment(result):
        save_tournament(t)
        return _analysis_response(result, match_id)

    if (
        not force
        and _result_has_analysis(result)
        and not _analysis_needs_rebuild(result)
    ):
        return _analysis_response(result, match_id)

    home = result.get("home") or fx.get("home")
    away = result.get("away") or fx.get("away")
    if not home or not away:
        raise ValueError(f"Match {match_id} is missing team names")

    n_sims = int(
        result.get("simulations")
        or (t.get("settings") or {}).get("simulations_per_match")
        or 10000
    )
    team_a, team_b = _load_teams_for_match(
        home, away, tournament_id=tournament_id, match_id=match_id
    )
    report, _snapshot = _run_simulation(
        home, away, match_id, n_sims, team_a=team_a, team_b=team_b
    )
    result.update(_analysis_payload_from_report(report))
    save_tournament(t)
    return _analysis_response(result, match_id)


def _start_analysis_job(
    tournament_id: str,
    match_id: str,
    result: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Start (or join) a background analysis build; return generating/error payload."""
    key = _analysis_job_key(tournament_id, match_id)
    with _analysis_jobs_lock:
        job = _analysis_jobs.get(key)
        if job and job.get("status") == "generating":
            return _generating_analysis_response(result, match_id)
        if job and job.get("status") == "error" and not force:
            # Surface once, then clear so the next click can retry.
            message = str(job.get("error") or "Analysis generation failed")
            _analysis_jobs.pop(key, None)
            return _error_analysis_response(result, match_id, message)
        _analysis_jobs[key] = {
            "status": "generating",
            "force": force,
            "started_at": _now(),
            "error": None,
        }

    def _job() -> None:
        try:
            _build_and_persist_match_analysis(
                tournament_id, match_id, force=force
            )
            with _analysis_jobs_lock:
                _analysis_jobs[key] = {
                    "status": "ready",
                    "finished_at": _now(),
                    "error": None,
                }
        except Exception as exc:
            with _analysis_jobs_lock:
                _analysis_jobs[key] = {
                    "status": "error",
                    "finished_at": _now(),
                    "error": str(exc),
                }

    threading.Thread(target=_job, daemon=True, name=f"analysis-{key}").start()
    return _generating_analysis_response(result, match_id)


def get_match_analysis(tournament_id: str, match_id: str) -> dict[str, Any]:
    """Return persisted analysis, or start a background build (status=generating)."""
    t, _fx, result = _load_played_match_result(tournament_id, match_id)

    if not _result_has_analysis(result):
        if _import_analysis_from_experiment(result):
            save_tournament(t)

    key = _analysis_job_key(tournament_id, match_id)
    with _analysis_jobs_lock:
        job = dict(_analysis_jobs.get(key) or {})

    if job.get("status") == "generating":
        # If we already have text (stale refresh in flight), keep serving it.
        if _result_has_analysis(result):
            return _analysis_response(result, match_id)
        return _generating_analysis_response(result, match_id)

    if job.get("status") == "error":
        message = str(job.get("error") or "Analysis generation failed")
        with _analysis_jobs_lock:
            _analysis_jobs.pop(key, None)
        if _result_has_analysis(result):
            # Prefer stale narrative over failing the view after a failed refresh.
            return _analysis_response(result, match_id)
        return _error_analysis_response(result, match_id, message)

    if job.get("status") == "ready":
        with _analysis_jobs_lock:
            _analysis_jobs.pop(key, None)
        # Reload — worker persisted to disk after the in-memory snapshot above.
        t, _fx, result = _load_played_match_result(tournament_id, match_id)

    if _result_has_analysis(result) and not _analysis_needs_rebuild(result):
        return _analysis_response(result, match_id)

    if _result_has_analysis(result) and _analysis_needs_rebuild(result):
        # Serve current text immediately; refresh fit formula in the background.
        _start_analysis_job(tournament_id, match_id, result, force=False)
        return _analysis_response(result, match_id)

    return _start_analysis_job(tournament_id, match_id, result, force=False)


def generate_match_analysis(tournament_id: str, match_id: str) -> dict[str, Any]:
    """Admin backfill: start a background rebuild (does not change the score)."""
    _t, _fx, result = _load_played_match_result(tournament_id, match_id)
    return _start_analysis_job(tournament_id, match_id, result, force=True)


def accept_match_result(tournament_id: str, match_id: str) -> dict[str, Any]:
    """Admin accepts the engine scoreline without changing it."""
    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    found = _find_fixture(t, match_id)
    if not found:
        raise KeyError(f"Fixture '{match_id}' not found")
    stage_key, fx = found
    if not fx.get("played"):
        raise ValueError(f"Match {match_id} has not been played yet")
    result_id = fx.get("result_id") or match_id
    result = (t.get("match_results") or {}).get(result_id)
    if not result:
        raise KeyError(f"Result for '{match_id}' not found")

    _ensure_engine_score(result)
    result["admin_accepted"] = True
    result["admin_reviewed_at"] = _now()
    if not result.get("manually_overridden"):
        result["manually_overridden"] = False
    if not _result_has_analysis(result):
        _import_analysis_from_experiment(result)
    save_tournament(t)
    return {
        "tournament": tournament_for_api(t),
        "match": fx,
        "result": match_result_for_api(result),
        "stage": stage_key,
    }


def override_match_result(
    tournament_id: str,
    match_id: str,
    home_goals: int,
    away_goals: int,
    winner: str | None = None,
) -> dict[str, Any]:
    """Admin overrides a completed match score and refreshes standings / KO advancement."""
    if home_goals < 0 or away_goals < 0:
        raise ValueError("Goals must be non-negative")

    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")
    found = _find_fixture(t, match_id)
    if not found:
        raise KeyError(f"Fixture '{match_id}' not found")
    stage_key, fx = found
    if not fx.get("played"):
        raise ValueError(f"Match {match_id} has not been played yet")

    is_knockout = stage_key == "knockout"
    if not is_knockout and (t.get("knockout") or {}).get("rounds"):
        raise ValueError(
            "Cannot override group results after the knockout bracket is generated"
        )
    if is_knockout and _knockout_downstream_played(t, match_id):
        raise ValueError(
            f"Cannot override {match_id}: a later knockout match that depends on it "
            "has already been played"
        )

    result_id = fx.get("result_id") or match_id
    result = (t.get("match_results") or {}).get(result_id)
    if not result:
        raise KeyError(f"Result for '{match_id}' not found")

    home = fx["home"]
    away = fx["away"]
    _ensure_engine_score(result)

    if winner is not None:
        winner = str(winner).strip()
        if winner and winner not in (home, away):
            raise ValueError(f"Winner must be '{home}' or '{away}'")

    if is_knockout:
        if home_goals == away_goals:
            if winner in (home, away):
                resolved = winner
            else:
                resolved = _resolve_winner(
                    home,
                    away,
                    home_goals,
                    away_goals,
                    _tiebreak_report_from_result(result),
                    require_winner=True,
                )
                if not resolved:
                    raise ValueError(
                        "Knockout override is a draw — pass winner (home or away team name) "
                        "or keep a non-draw scoreline"
                    )
        else:
            resolved = home if home_goals > away_goals else away
            if winner in (home, away) and winner != resolved:
                raise ValueError(
                    f"Winner '{winner}' does not match scoreline {home_goals}-{away_goals}"
                )
        winner = resolved
    else:
        if home_goals > away_goals:
            winner = home
        elif away_goals > home_goals:
            winner = away
        else:
            winner = None

    score = f"{home_goals}-{away_goals}"
    result["home_goals"] = int(home_goals)
    result["away_goals"] = int(away_goals)
    result["score"] = score
    result["winner"] = winner
    result["manually_overridden"] = True
    result["admin_accepted"] = True
    result["overridden_at"] = _now()
    result["admin_reviewed_at"] = result["overridden_at"]

    fx["score"] = score
    fx["winner"] = winner

    if is_knockout:
        _advance_knockout_winner(t, fx, winner)
        all_done = all(
            t2.get("played")
            for rnd in t["knockout"]["rounds"]
            for t2 in rnd.get("ties", [])
            if t2.get("home") and t2.get("away")
        )
        t["status"] = "complete" if all_done else "knockout"
    else:
        _recompute_group_table(t, stage_key)

    save_tournament(t)
    return {
        "tournament": tournament_for_api(t),
        "match": fx,
        "result": match_result_for_api(result),
        "stage": stage_key,
    }


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
    if t["status"] not in ("draft", "group_draw", "group_stage"):
        raise ValueError("Settings can only be changed before knockout stage")
    if (t.get("knockout") or {}).get("rounds"):
        raise ValueError("Cannot change settings after knockout bracket is generated")
    team_count = len(t.get("team_names") or [])
    if team_count < 2:
        raise ValueError("Add at least 2 teams before configuring groups")

    prev = t.get("settings") or {}
    advance_hint = settings.get("advance_per_group", prev.get("advance_per_group"))

    if "group_count" in settings:
        merged = _settings_from_group_count(
            team_count,
            int(settings["group_count"]),
            advance_per_group=int(advance_hint) if advance_hint is not None else None,
        )
    elif "teams_per_group" in settings:
        per_group = int(settings["teams_per_group"])
        if per_group < 2:
            raise ValueError("Each group needs at least 2 teams")
        if team_count % per_group != 0:
            raise ValueError(
                f"{team_count} teams do not divide evenly into groups of {per_group}"
            )
        merged = _settings_from_group_count(
            team_count,
            team_count // per_group,
            advance_per_group=int(advance_hint) if advance_hint is not None else None,
        )
    elif "advance_per_group" in settings:
        merged = {**prev}
        g_count = int(merged.get("group_count", 1))
        per_group = int(merged.get("teams_per_group", team_count))
        advance = int(settings["advance_per_group"])
        _validate_advance_per_group(g_count, per_group, advance)
        merged["advance_per_group"] = advance
    else:
        merged = {**prev, **settings}
        _validate_group_settings(team_count, int(merged.get("group_count", 1)))

    merged["simulations_per_match"] = int(
        settings.get("simulations_per_match")
        or prev.get("simulations_per_match", 10000)
    )
    merged["knockout_format"] = settings.get("knockout_format") or prev.get(
        "knockout_format", "single_elim"
    )

    t["settings"] = merged
    t["knockout"]["format"] = merged.get("knockout_format", "single_elim")
    save_tournament(t)
    return t


def delete_tournament(tournament_id: str) -> dict[str, Any]:
    t = load_tournament(tournament_id)
    if not t:
        raise KeyError("Tournament not found")

    # Delete from R2 if enabled
    try:
        import r2_storage
        if r2_storage.is_r2_enabled():
            r2_storage.delete_tournament_metadata(tournament_id)
    except (ImportError, Exception):
        pass

    # Delete from JSON
    _tournament_path(tournament_id).unlink(missing_ok=True)
    matchday_session.clear_if_references(tournament_id=tournament_id)
    return {"id": tournament_id, "name": t.get("name")}
