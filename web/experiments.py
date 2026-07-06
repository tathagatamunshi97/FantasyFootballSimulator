"""Per-user experiment storage and background simulation runs."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MATCHDAY_WATCH_HOURS = 24

from formation_fit import FORMATION_SLOTS, supported_formations
from models import FantasyTeam
from report_builder import build_report
from stats_resolver import prepare_match_player_stats, validate_season_overrides

from web.state import get_stats_store

ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = ROOT / "data" / "experiments"

_lock = threading.Lock()
_running_ids: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _experiment_path(exp_id: str) -> Path:
    return EXPERIMENTS_DIR / f"{exp_id}.json"


def _default_experiment(
    exp_id: str,
    user: str,
    payload: dict[str, Any],
    *,
    matchday: bool = False,
    tournament: dict[str, Any] | None = None,
) -> dict[str, Any]:
    exp: dict[str, Any] = {
        "id": exp_id,
        "user": user,
        "matchday": matchday,
        "created_at": _now(),
        "updated_at": _now(),
        "status": "queued",
        "message": "Queued for simulation.",
        "running": False,
        "simulations": payload.get("simulations", 10000),
        "seed": payload.get("seed"),
        "team_a": payload["team_a"],
        "team_b": payload["team_b"],
        "report": None,
    }
    if tournament:
        exp["tournament_id"] = tournament.get("tournament_id")
        exp["tournament_name"] = tournament.get("tournament_name")
        exp["match_id"] = tournament.get("match_id")
        exp["stage"] = tournament.get("stage")
    return exp


def is_matchday_experiment(exp: dict[str, Any]) -> bool:
    """Only tournament fixture broadcasts appear on matchday (not ad-hoc lab sims)."""
    return bool(exp.get("tournament_id") and exp.get("match_id"))


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def can_team_view_experiment(exp: dict[str, Any]) -> bool:
    """Team users may watch live or recently finished admin/matchday broadcasts."""
    if not is_matchday_experiment(exp):
        return False
    if exp.get("running") or exp.get("status") in ("running", "queued"):
        return True
    updated = _parse_ts(exp.get("updated_at"))
    if not updated:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MATCHDAY_WATCH_HOURS)
    return updated >= cutoff


def validate_team_payload(team: dict[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    name = (team.get("name") or "").strip()
    if not name:
        errors.append(f"{label}: team name is required.")
    formation = team.get("formation") or "4-4-2"
    if formation not in FORMATION_SLOTS:
        errors.append(f"{label}: unsupported formation {formation}.")
    expected_slots = [s["slot"] for s in FORMATION_SLOTS.get(formation, [])]
    lineup = team.get("lineup") or []
    if len(lineup) != len(expected_slots):
        errors.append(f"{label}: lineup must have {len(expected_slots)} players for {formation}.")
    seen_slots: set[str] = set()
    players: list[str] = []
    for row in lineup:
        slot = row.get("slot")
        player = (row.get("player") or "").strip()
        if not player:
            errors.append(f"{label}: missing player for slot {slot}.")
        if slot in seen_slots:
            errors.append(f"{label}: duplicate slot {slot}.")
        seen_slots.add(slot)
        players.append(player)
    if expected_slots and seen_slots != set(expected_slots):
        errors.append(f"{label}: slots must be {', '.join(expected_slots)}.")
    return errors


def _normalize_team_overrides(team: dict[str, Any]) -> dict[str, Any]:
    """Clear peak-season season when no player is selected (default lab UI state)."""
    out = json.loads(json.dumps(team))
    if not (out.get("prime_player") or "").strip():
        out["prime_player"] = ""
    peak = out.get("peak_season") or {}
    if not (peak.get("player") or "").strip():
        out["peak_season"] = {"player": "", "season": ""}
    return out


def simulation_permission_errors(user: str, *, is_admin: bool) -> list[str]:
    """Only admin session users or SIM_ADMIN_TOKEN may create simulations."""
    from web.auth import can_run_simulations

    if can_run_simulations(user, is_admin_token=is_admin):
        return []
    return [
        "Creating simulations requires admin access. "
        "Squad logins can view squad evaluation and scout opponents at /squad."
    ]


def validate_matchup_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    team_a = _normalize_team_overrides(payload.get("team_a") or {})
    team_b = _normalize_team_overrides(payload.get("team_b") or {})
    payload["team_a"] = team_a
    payload["team_b"] = team_b
    errors.extend(validate_team_payload(team_a, "Team A"))
    errors.extend(validate_team_payload(team_b, "Team B"))
    errors.extend(validate_season_overrides(team_a, "Team A"))
    errors.extend(validate_season_overrides(team_b, "Team B"))
    a_name = (team_a.get("name") or "").strip().lower()
    b_name = (team_b.get("name") or "").strip().lower()
    if a_name and b_name and a_name == b_name:
        errors.append("Team A and Team B must have different names.")
    a_players = {r.get("player") for r in team_a.get("lineup", [])}
    b_players = {r.get("player") for r in team_b.get("lineup", [])}
    overlap = a_players & b_players
    if overlap:
        errors.append(f"Players cannot appear on both teams: {', '.join(sorted(overlap))}.")
    sims = int(payload.get("simulations", 10000))
    if sims < 100 or sims > 100_000:
        errors.append("Simulations must be between 100 and 100,000.")
    return errors


def _apply_name_map(payload: dict[str, Any], name_map: dict[str, str]) -> dict[str, Any]:
    out = json.loads(json.dumps(payload))
    for side in ("team_a", "team_b"):
        team = out[side]
        for row in team.get("lineup", []):
            raw = row.get("player", "")
            if raw in name_map:
                row["player"] = name_map[raw]
        for i, bp in enumerate(team.get("bench") or []):
            if bp in name_map:
                team["bench"][i] = name_map[bp]
        meta = team.get("sheet_meta") or {}
        if meta.get("full_roster"):
            meta["full_roster"] = [name_map.get(p, p) for p in meta["full_roster"]]
        if meta.get("bench_players"):
            meta["bench_players"] = [name_map.get(p, p) for p in meta["bench_players"]]
        if meta.get("roster_players"):
            meta["roster_players"] = [name_map.get(p, p) for p in meta["roster_players"]]
        team["sheet_meta"] = meta
        prime = (team.get("prime_player") or "").strip()
        if prime and prime in name_map:
            team["prime_player"] = name_map[prime]
        peak = team.get("peak_season") or {}
        pp = (peak.get("player") or "").strip()
        if pp and pp in name_map:
            peak["player"] = name_map[pp]
            team["peak_season"] = peak
    return out


def _lineup_player_names(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for side in ("team_a", "team_b"):
        team = payload.get(side, {})
        for row in team.get("lineup", []):
            p = (row.get("player") or "").strip()
            if p:
                names.append(p)
        for p in team.get("bench") or []:
            if p and str(p).strip():
                names.append(str(p).strip())
        meta = team.get("sheet_meta") or {}
        for p in meta.get("full_roster") or meta.get("bench_players") or []:
            if p and str(p).strip():
                names.append(str(p).strip())
    return names


def _to_fantasy_teams(payload: dict[str, Any]) -> tuple[FantasyTeam, FantasyTeam]:
    home = FantasyTeam.from_dict(payload["team_a"])
    away = FantasyTeam.from_dict(payload["team_b"])
    return home, away


def save_experiment(exp: dict[str, Any]) -> None:
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    exp["updated_at"] = _now()
    _experiment_path(exp["id"]).write_text(
        json.dumps(exp, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_experiment(exp_id: str) -> dict[str, Any] | None:
    path = _experiment_path(exp_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def list_experiments(*, user: str | None = None) -> list[dict[str, Any]]:
    if not EXPERIMENTS_DIR.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in EXPERIMENTS_DIR.glob("*.json"):
        try:
            exp = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if user and exp.get("user") != user:
            continue
        rows.append(_summary(exp))
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows


def _summary(exp: dict[str, Any]) -> dict[str, Any]:
    mc = (exp.get("report") or {}).get("monte_carlo") or {}
    exg = mc.get("expected_xg") or {}
    top_scores = (mc.get("scorelines") or [])[:3]
    return {
        "id": exp["id"],
        "user": exp.get("user"),
        "matchday": is_matchday_experiment(exp),
        "tournament_id": exp.get("tournament_id"),
        "tournament_name": exp.get("tournament_name"),
        "match_id": exp.get("match_id"),
        "stage": exp.get("stage"),
        "created_at": exp.get("created_at"),
        "updated_at": exp.get("updated_at"),
        "status": exp.get("status"),
        "message": exp.get("message"),
        "running": exp.get("running", False),
        "simulations": exp.get("simulations"),
        "team_a_name": exp.get("team_a", {}).get("name"),
        "team_b_name": exp.get("team_b", {}).get("name"),
        "team_a_formation": exp.get("team_a", {}).get("formation"),
        "team_b_formation": exp.get("team_b", {}).get("formation"),
        "expected_xg_home": exg.get("home"),
        "expected_xg_away": exg.get("away"),
        "home_win_pct": mc.get("home_win_pct"),
        "draw_pct": mc.get("draw_pct"),
        "away_win_pct": mc.get("away_win_pct"),
        "top_scorelines": [{"score": r.get("score"), "pct": r.get("pct")} for r in top_scores],
    }


def list_matchday_experiments(*, limit: int = 20, watch_only: bool = False) -> list[dict[str, Any]]:
    """Deprecated — matchday uses active session API. Returns empty list."""
    return []


def start_matchday_run(
    user: str,
    payload: dict[str, Any],
    *,
    run_fn,
    tournament: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a matchday experiment and run ``run_fn(exp)`` in a background thread."""
    exp_id = uuid.uuid4().hex[:12]
    exp = _default_experiment(exp_id, user, payload, matchday=True, tournament=tournament)

    with _lock:
        if exp_id in _running_ids:
            raise RuntimeError("Experiment already running.")
        _running_ids.add(exp_id)

    exp["status"] = "running"
    exp["running"] = True
    exp["message"] = f"Running {exp['simulations']:,} simulations…"
    save_experiment(exp)

    def _job() -> None:
        try:
            run_fn(exp)
        except Exception as exc:
            exp["status"] = "error"
            exp["running"] = False
            exp["message"] = str(exc)
            save_experiment(exp)
        finally:
            with _lock:
                _running_ids.discard(exp_id)

    threading.Thread(target=_job, daemon=True).start()
    return _summary(exp) | {"id": exp_id}


def is_experiment_running(exp_id: str) -> bool:
    with _lock:
        return exp_id in _running_ids


def delete_experiment(exp_id: str) -> dict[str, Any]:
    from web import matchday_session

    exp = load_experiment(exp_id)
    if not exp:
        raise KeyError("Experiment not found")
    if is_experiment_running(exp_id):
        raise ValueError("Cannot delete a running experiment")
    _experiment_path(exp_id).unlink(missing_ok=True)
    matchday_session.clear_if_references(experiment_id=exp_id)
    return {"id": exp_id, "user": exp.get("user")}


def create_and_run_experiment(
    user: str,
    payload: dict[str, Any],
    *,
    is_admin: bool = False,
) -> dict[str, Any]:
    errors = validate_matchup_payload(payload)
    errors.extend(simulation_permission_errors(user, is_admin=is_admin))
    if errors:
        raise ValueError("; ".join(errors))

    exp_id = uuid.uuid4().hex[:12]
    exp = _default_experiment(exp_id, user, payload, matchday=False)

    with _lock:
        if exp_id in _running_ids:
            raise RuntimeError("Experiment already running.")
        _running_ids.add(exp_id)

    exp["status"] = "running"
    exp["running"] = True
    exp["message"] = f"Running {exp['simulations']:,} simulations…"
    save_experiment(exp)

    def _job() -> None:
        try:
            store = get_stats_store()
            exp["message"] = "Loading player stats (fetching new players / season profiles)…"
            save_experiment(exp)
            player_stats, season_overrides, name_map = prepare_match_player_stats(
                payload["team_a"], payload["team_b"], store
            )
            resolved_payload = _apply_name_map(payload, name_map)
            exp["team_a"] = resolved_payload["team_a"]
            exp["team_b"] = resolved_payload["team_b"]
            home, away = _to_fantasy_teams(resolved_payload)
            exp["message"] = f"Running {exp['simulations']:,} simulations…"
            save_experiment(exp)
            report = build_report(
                home,
                away,
                player_stats,
                n_simulations=int(exp["simulations"]),
                seed=exp.get("seed"),
                season_overrides=season_overrides,
            )
            exp["status"] = "ready"
            exp["running"] = False
            exp["message"] = f"Completed {exp['simulations']:,} simulations."
            exp["report"] = report
            save_experiment(exp)
        except Exception as exc:
            exp["status"] = "error"
            exp["running"] = False
            exp["message"] = str(exc)
            save_experiment(exp)
        finally:
            with _lock:
                _running_ids.discard(exp_id)

    threading.Thread(target=_job, daemon=True).start()
    return _summary(exp) | {"id": exp_id}


def formation_meta() -> dict[str, Any]:
    return {
        "formations": supported_formations(),
        "slots": {f: [s["slot"] for s in FORMATION_SLOTS[f]] for f in supported_formations()},
    }


def player_catalog() -> list[dict[str, Any]]:
    store = get_stats_store()
    rows = []
    for name, p in sorted(store.players.items()):
        rows.append(
            {
                "name": name,
                "team": p.team,
                "position": p.fpl_position,
                "primary": p.primary_position,
                "minutes": round(p.minutes, 0),
            }
        )
    return rows
