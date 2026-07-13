"""FastAPI web server — multi-user experiments, viewer, admin."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from formation_fit import DEFAULT_FORMATION, normalize_formation
from web import auth, experiments, matchday_session, state as sim_state, team_lineups, tournament

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Football Match Simulator",
    description="Monte Carlo H2H simulator with per-user experiments",
    version="2.1",
)


class LoginRequest(BaseModel):
    name: str
    password: str


class SetPasswordRequest(BaseModel):
    name: str
    new_password: str
    confirm_password: str


class TeamPasswordResetRequest(BaseModel):
    team_name: str


class RunRequest(BaseModel):
    simulations: int = Field(default=10000, ge=100, le=100_000)
    seed: int | None = None


class ExperimentRequest(BaseModel):
    team_a: dict[str, Any]
    team_b: dict[str, Any]
    simulations: int = Field(default=10000, ge=100, le=100_000)
    seed: int | None = None


class PlayerEnsureRequest(BaseModel):
    names: list[str] = Field(default_factory=list)


class LineupAssignRequest(BaseModel):
    formation: str = DEFAULT_FORMATION
    players: list[str] = Field(default_factory=list)


class LineupRandomRequest(BaseModel):
    formation: str = DEFAULT_FORMATION
    count: int = Field(default=11, ge=1, le=11)
    seed: int | None = None


class LineupSaveRequest(BaseModel):
    formation: str = DEFAULT_FORMATION
    lineup: list[dict[str, Any]] = Field(default_factory=list)
    prime_player: str = ""
    peak_season: dict[str, str] | None = None


class TournamentCreateRequest(BaseModel):
    name: str = "Fantasy Tournament"
    team_names: list[str] = Field(default_factory=list)
    settings: dict[str, Any] | None = None


class TournamentTeamsRequest(BaseModel):
    team_names: list[str] = Field(default_factory=list)


class TournamentDrawRequest(BaseModel):
    seed: int | None = None


class TournamentStatusRequest(BaseModel):
    status: str


class TournamentSettingsRequest(BaseModel):
    group_count: int | None = None
    teams_per_group: int | None = None
    advance_per_group: int | None = None


class TournamentMatchOverrideRequest(BaseModel):
    home_goals: int
    away_goals: int
    winner: str | None = None
    board_events: list[dict] | None = None
    match_log: list[dict] | dict | None = None
    decided_by: str | None = None
    ft_home_goals: int | None = None
    ft_away_goals: int | None = None
    pens_home: int | None = None
    pens_away: int | None = None
    score_display: str | None = None


def _session_user(x_session_token: str | None) -> str:
    user = auth.get_user(x_session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def _check_admin(token: str | None) -> None:
    expected = sim_state.get_admin_token()
    if not token or token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")


def _is_admin(token: str | None) -> bool:
    return bool(token and token == sim_state.get_admin_token())


def _is_admin_session(user: str | None) -> bool:
    return auth.is_admin_user(user)


def _require_sim_builder(
    x_session_token: str | None,
    x_admin_token: str | None = None,
) -> str:
    """Session required; only admin users may use lab/sim-building APIs."""
    user = _session_user(x_session_token)
    if not auth.can_run_simulations(user, is_admin_token=_is_admin(x_admin_token)):
        raise HTTPException(
            status_code=403,
            detail="Simulation building requires admin access. Squad logins: use /squad.",
        )
    return user


def _require_admin_session(x_session_token: str | None) -> str:
    """Logged-in admin user only (not SIM_ADMIN_TOKEN)."""
    user = _session_user(x_session_token)
    if not _is_admin_session(user):
        raise HTTPException(
            status_code=403,
            detail="Admin login required. Team users: use /squad for squad evaluation and scouting.",
        )
    return user


def _require_admin_session_or_token(
    x_session_token: str | None,
    x_admin_token: str | None = None,
) -> None:
    """Admin session or SIM_ADMIN_TOKEN may view simulation history."""
    user = auth.get_user(x_session_token)
    if _is_admin_session(user) or _is_admin(x_admin_token):
        return
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    raise HTTPException(
        status_code=403,
        detail="Simulation history is admin-only. Team users: use /squad.",
    )


def _session_user_or_admin(
    x_session_token: str | None,
    x_admin_token: str | None,
) -> str:
    """Accept logged-in user or valid admin token (returns username or 'admin')."""
    user = auth.get_user(x_session_token)
    if user:
        return user
    if _is_admin(x_admin_token):
        return "admin"
    raise HTTPException(status_code=401, detail="Login or admin token required")


@app.get("/api/health")
async def health() -> dict:
    """Render health probe — must stay on the event loop and answer in ms.

    Never touch Matchday locks, deepcopy, disk, or enrich. Sync Matchday work
    runs in the threadpool; this async route is not starved by that queue.
    """
    return {"ok": True}


@app.post("/api/login")
def login(body: LoginRequest) -> dict:
    result = auth.attempt_login(body.name, body.password)
    if result["status"] == "needs_password_setup":
        return {
            "needs_password_setup": True,
            "user": result["user"],
        }
    if result["status"] != "ok":
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid login. Use your Google Sheet team name and password, "
                "or admin with the SIM_ADMIN_TOKEN password."
            ),
        )
    user = result["user"]
    try:
        token = auth.create_session(user)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"token": token, "user": user}


@app.post("/api/set-password")
def set_password(body: SetPasswordRequest) -> dict:
    team = auth.resolve_sheet_team(body.name)
    if not team:
        raise HTTPException(status_code=400, detail="Unknown team — must match a Google Sheet team name.")
    if auth.team_has_password(team):
        raise HTTPException(
            status_code=400,
            detail="Password already set for this team. Contact admin to reset.",
        )
    try:
        auth.set_team_password(team, body.new_password, body.confirm_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        token = auth.create_session(team)
    except ValueError as exc:
        auth.reset_team_password(team)
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"token": token, "user": team, "message": "Password set. You are now logged in."}


@app.post("/api/logout")
def logout(x_session_token: str | None = Header(default=None, alias="X-Session-Token")) -> dict:
    auth.revoke_session(x_session_token)
    return {"ok": True}


@app.get("/api/session")
def session(x_session_token: str | None = Header(default=None, alias="X-Session-Token")) -> dict:
    user = auth.get_user(x_session_token)
    role = auth.user_role(user)
    return {
        "logged_in": bool(user),
        "user": user,
        "role": role,
        "can_simulate": auth.can_run_simulations(user),
        "max_team_sessions": auth.MAX_TEAM_SESSIONS,
        "active_sessions": auth.active_session_count(user) if user else 0,
    }


@app.get("/api/meta")
def meta() -> dict:
    from report_builder import load_matchup, team_lineup_dict
    from seasonal_stats import list_selectable_seasons

    home, away = load_matchup()
    default_a = team_lineup_dict(home) | {
        "formation": home.formation,
        "prime_player": "",
        "peak_season": {"player": "", "season": ""},
    }
    default_b = team_lineup_dict(away) | {
        "formation": away.formation,
        "prime_player": "",
        "peak_season": {"player": "", "season": ""},
    }
    return {
        "formations": experiments.formation_meta(),
        "players": experiments.player_catalog(),
        "seasons": list_selectable_seasons(),
        "default_matchup": {
            "team_a": default_a,
            "team_b": default_b,
        },
    }


@app.get("/api/sheets/config")
def sheets_config() -> dict:
    from google_sheets_teams import sheet_csv_url, spreadsheet_config

    sheet_id, gid = spreadsheet_config()
    return {
        "spreadsheet_id": sheet_id,
        "gid": gid,
        "csv_url": sheet_csv_url(sheet_id, gid),
    }


@app.get("/api/sheets/teams")
def sheets_teams(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """List fantasy teams from the configured Google Sheet (admin only)."""
    _check_admin(x_admin_token)
    from google_sheets_teams import list_sheet_teams

    try:
        teams = list_sheet_teams()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"teams": teams}


@app.get("/api/sheets/team")
def sheets_team(
    name: str,
    formation: str = DEFAULT_FORMATION,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Load one team roster from the Google Sheet by name (admin only)."""
    _check_admin(x_admin_token)
    from google_sheets_teams import load_team_by_name

    store = sim_state.get_stats_store()
    try:
        team = load_team_by_name(name, formation=formation, store=store)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"team": team}


@app.post("/api/lineup/assign")
def assign_lineup(
    body: LineupAssignRequest,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Assign formation slots to an unordered player list using position + stats fit."""
    user = auth.get_user(x_session_token)
    if not user and not _is_admin(x_admin_token):
        raise HTTPException(status_code=401, detail="Login required")
    if not (auth.is_team_user(user) or _is_admin_session(user) or _is_admin(x_admin_token)):
        raise HTTPException(status_code=403, detail="Login required for lineup assignment.")
    from formation_fit import FORMATION_SLOTS, team_formation_fit
    from lineup_builder import assign_lineup_slots, lineup_from_assignments

    formation = normalize_formation(body.formation)
    players = [p.strip() for p in body.players if p and p.strip()]
    if not players:
        slots = [s["slot"] for s in FORMATION_SLOTS[formation]]
        return {
            "formation": formation,
            "lineup": [{"slot": s, "player": "", "captain": False, "vice_captain": False} for s in slots],
            "fit": None,
        }
    store = sim_state.get_stats_store()
    try:
        store.ensure_players(players)
        stats = store.require(players)
        pairs = assign_lineup_slots(formation, players, stats)
        lineup = lineup_from_assignments(formation, pairs)
        fit = team_formation_fit(formation, pairs, stats)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"formation": formation, "lineup": lineup, "fit": fit}


@app.post("/api/lineup/random")
def random_lineup_api(
    body: LineupRandomRequest,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Pick random players from the catalog (1 GK when possible) and assign slots."""
    _require_sim_builder(x_session_token, x_admin_token)
    from formation_fit import FORMATION_SLOTS
    from lineup_builder import random_lineup

    formation = normalize_formation(body.formation)
    store = sim_state.get_stats_store()
    catalog = store.players
    if not catalog:
        raise HTTPException(status_code=503, detail="Player catalog is empty")
    players, lineup = random_lineup(
        formation,
        catalog,
        count=body.count,
        seed=body.seed,
    )
    return {"formation": formation, "players": players, "lineup": lineup}


@app.post("/api/players/ensure")
def ensure_players(
    body: PlayerEnsureRequest,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Resolve player names and fetch missing stats from Sofascore."""
    _require_sim_builder(x_session_token, x_admin_token)
    store = sim_state.get_stats_store()
    try:
        mapping = store.ensure_players(body.names)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"players": mapping}


def _enrich_matchday_status(status: dict[str, Any]) -> dict[str, Any]:
    session = status.get("session")
    if not session:
        return status
    # Live board polls: skip tournament file + lineup I/O — frames are what matter.
    phase = session.get("phase")
    if phase in ("live", "running"):
        return status
    out = dict(status)
    sess = dict(session)
    teams_meta: dict[str, Any] = {}
    for side in ("home", "away"):
        name = sess.get(side)
        if not name:
            continue
        round_ctx = tournament.get_team_immediate_round(name)
        ls = team_lineups.lineup_status(name, immediate_round_key=round_ctx.get("round_key"))
        teams_meta[name] = {
            "finalized": ls["locked"],
            "finalized_round": ls.get("finalized_round"),
            "can_edit": ls["can_edit"],
            "immediate_round": round_ctx,
        }
    sess["teams_meta"] = teams_meta
    out["session"] = sess
    return out


@app.get("/api/matchday/active")
def matchday_active(
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Poll for active tournament fixture broadcast. Clients redirect when redirect=true."""
    user = auth.get_user(x_session_token)
    if not user and not _is_admin(x_admin_token):
        raise HTTPException(status_code=401, detail="Login required")
    return _enrich_matchday_status(matchday_session.active_status())


@app.get("/api/matchday")
def matchday_session_api(
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Current matchday session state (setup → running → result)."""
    user = auth.get_user(x_session_token)
    if not user and not _is_admin(x_admin_token):
        raise HTTPException(status_code=401, detail="Login required")
    return _enrich_matchday_status(matchday_session.active_status())


@app.post("/api/matchday/run")
def matchday_run_simulation(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Admin starts live tactic board (or legacy Monte Carlo if no board payload)."""
    _check_admin(x_admin_token)
    try:
        session = matchday_session.require_active_session()
        if session.get("board") or session.get("engine") == "tactic_board":
            matchday_session.set_board_live()
            return _enrich_matchday_status(matchday_session.active_status()) | {
                "status": "live",
                "engine": "tactic_board",
            }
        return tournament.execute_matchday_simulation()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Matchday run failed: {exc}") from exc


@app.post("/api/matchday/kickoff")
def matchday_board_kickoff(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Admin starts the live tactic-board phase on Matchday."""
    _check_admin(x_admin_token)
    try:
        matchday_session.set_board_live()
        return _enrich_matchday_status(matchday_session.active_status())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/matchday/board-state")
def matchday_publish_board_state(
    body: dict,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Host publishes live pitch snapshot for Matchday viewers."""
    _check_admin(x_admin_token)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid board state")
    try:
        seq = matchday_session.publish_board_state(body)
        return {"ok": True, "seq": seq}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/matchday/complete")
def matchday_complete_from_board(
    body: dict,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Persist FT pin score for the active Matchday fixture."""
    _check_admin(x_admin_token)
    try:
        session = matchday_session.require_active_session()
        return tournament.complete_from_board(
            session["tournament_id"],
            session["fixture_id"],
            int(body.get("home_goals", 0)),
            int(body.get("away_goals", 0)),
            winner=body.get("winner"),
            board_events=body.get("board_events"),
            match_log=body.get("match_log"),
            decided_by=body.get("decided_by"),
            ft_home_goals=body.get("ft_home_goals"),
            ft_away_goals=body.get("ft_away_goals"),
            pens_home=body.get("pens_home"),
            pens_away=body.get("pens_away"),
            score_display=body.get("score_display"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Matchday complete failed: {exc}") from exc


@app.post("/api/matchday/dismiss")
def matchday_dismiss(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Admin clears the result-phase matchday session."""
    _check_admin(x_admin_token)
    matchday_session.clear_session()
    return {"ok": True}


@app.get("/api/my-lineup")
def get_my_lineup(
    team: str | None = None,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Get saved lineup config + sheet roster for squad hub."""
    user = _session_user(x_session_token)
    is_admin = _is_admin(x_admin_token)
    if not (auth.is_team_user(user) or _is_admin_session(user) or is_admin):
        raise HTTPException(status_code=403, detail="Lineup access requires team or admin login.")

    team_name = _resolve_squad_team_name(user, team=team, is_admin_token=is_admin)
    if auth.is_team_user(user) and team_name.lower() != user.lower():
        raise HTTPException(status_code=403, detail="You can only edit your own lineup.")

    sheet_payload = _load_sheet_team_payload(team_name)
    meta = sheet_payload.get("sheet_meta") or {}
    roster = meta.get("full_roster") or meta.get("roster_players") or []
    saved = team_lineups.get_team_lineup(team_name)
    round_ctx = tournament.get_team_immediate_round(team_name)
    status = team_lineups.lineup_status(team_name, immediate_round_key=round_ctx.get("round_key"))

    if saved:
        lineup_config = saved
    else:
        lineup_config = {
            "team_name": team_name,
            "formation": normalize_formation(sheet_payload.get("formation") or DEFAULT_FORMATION),
            "lineup": sheet_payload.get("lineup") or [],
            "prime_player": sheet_payload.get("prime_player") or "",
            "peak_season": sheet_payload.get("peak_season") or {"player": "", "season": ""},
            "updated_at": None,
        }

    # Live slot fits (current formation_fit) — never serve a cached fit number here.
    slot_fits: dict[str, float] = {}
    try:
        from formation_fit import team_formation_fit
        from models import FantasyTeam
        from stats_resolver import prepare_team_player_stats

        draft = {
            "name": team_name,
            "formation": lineup_config.get("formation") or DEFAULT_FORMATION,
            "lineup": lineup_config.get("lineup") or [],
            "prime_player": lineup_config.get("prime_player") or "",
            "peak_season": lineup_config.get("peak_season") or {"player": "", "season": ""},
            "bench": sheet_payload.get("bench") or [],
            "sheet_meta": sheet_payload.get("sheet_meta") or {},
        }
        store = sim_state.get_stats_store()
        player_stats, name_map = prepare_team_player_stats(draft, store, cache_only=True)
        resolved = dict(draft)
        for row in resolved.get("lineup") or []:
            raw = row.get("player") or ""
            if raw in name_map:
                row["player"] = name_map[raw]
        fantasy = FantasyTeam.from_dict(resolved)
        fit_info = team_formation_fit(
            fantasy.formation,
            [(s.player, s.slot, s.role_filter or "") for s in fantasy.lineup],
            player_stats,
        )
        for row in fit_info.get("players") or []:
            slot = row.get("slot")
            if slot:
                slot_fits[str(slot)] = float(row.get("fit") or 0)
    except Exception:
        slot_fits = {}

    return {
        "team_name": team_name,
        "roster": roster,
        "saved": bool(saved),
        "lineup": lineup_config,
        "slot_fits": slot_fits,
        "finalized": status["finalized"],
        "finalized_at": status["finalized_at"],
        "finalized_round": status["finalized_round"],
        "locked": status["locked"],
        "can_edit": status["can_edit"],
        "immediate_round": round_ctx,
        "sheet_meta": {
            "player_count": meta.get("player_count"),
            "ready": meta.get("ready"),
            "squad_size": meta.get("squad_size"),
            "season_pick": meta.get("season_pick"),
        },
    }


@app.put("/api/my-lineup")
def put_my_lineup(
    body: LineupSaveRequest,
    team: str | None = None,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Save team's lineup configuration from squad hub."""
    user = _session_user(x_session_token)
    is_admin = _is_admin(x_admin_token)
    if not (auth.is_team_user(user) or _is_admin_session(user) or is_admin):
        raise HTTPException(status_code=403, detail="Lineup save requires team or admin login.")

    team_name = _resolve_squad_team_name(user, team=team, is_admin_token=is_admin)
    if auth.is_team_user(user) and team_name.lower() != user.lower():
        raise HTTPException(status_code=403, detail="You can only save your own lineup.")

    peak = body.peak_season or {"player": "", "season": ""}
    try:
        saved = team_lineups.save_team_lineup(
            team_name,
            {
                "formation": body.formation,
                "lineup": body.lineup,
                "prime_player": body.prime_player,
                "peak_season": peak,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "lineup": saved}


@app.post("/api/my-lineup/finalize")
def finalize_my_lineup(
    body: LineupSaveRequest | None = None,
    team: str | None = None,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Lock saved lineup for the team's immediate tournament round."""
    user = _session_user(x_session_token)
    is_admin = _is_admin(x_admin_token)
    if not (auth.is_team_user(user) or _is_admin_session(user) or is_admin):
        raise HTTPException(status_code=403, detail="Finalize requires team or admin login.")

    team_name = _resolve_squad_team_name(user, team=team, is_admin_token=is_admin)
    if auth.is_team_user(user) and team_name.lower() != user.lower():
        raise HTTPException(status_code=403, detail="You can only finalize your own lineup.")

    round_ctx = tournament.get_team_immediate_round(team_name)
    round_key = round_ctx.get("round_key") or "ready"
    config = None
    if body is not None:
        peak = body.peak_season or {"player": "", "season": ""}
        config = {
            "formation": body.formation,
            "lineup": body.lineup,
            "prime_player": body.prime_player,
            "peak_season": peak,
        }
    try:
        saved = team_lineups.finalize_team_lineup(
            team_name,
            config,
            round_key=round_key,
            round_label=round_ctx.get("label"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    status = team_lineups.lineup_status(team_name, immediate_round_key=round_key)
    return {
        "ok": True,
        "lineup": saved,
        "finalized": True,
        "locked": status["locked"],
        "immediate_round": round_ctx,
    }


@app.post("/api/my-squad/test")
def test_my_squad_api(
    body: LineupSaveRequest,
    team: str | None = None,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Evaluate draft lineup from the form without saving or finalizing."""
    user = _session_user(x_session_token)
    is_admin = _is_admin(x_admin_token)
    if not (auth.is_team_user(user) or _is_admin_session(user) or is_admin):
        raise HTTPException(status_code=403, detail="Squad test requires team or admin login.")

    team_name = _resolve_squad_team_name(user, team=team, is_admin_token=is_admin)
    if auth.is_team_user(user) and team_name.lower() != user.lower():
        raise HTTPException(status_code=403, detail="You can only test your own squad.")

    from squad_intel import build_squad_evaluation

    team_payload = _load_sheet_team_payload(team_name)
    peak = body.peak_season or {"player": "", "season": ""}
    draft = {
        "formation": body.formation,
        "lineup": body.lineup,
        "prime_player": body.prime_player,
        "peak_season": peak,
    }
    try:
        team_lineups._build_record_payload(team_name, draft)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    team_payload = team_lineups.apply_lineup_config(team_payload, draft)
    store = sim_state.get_stats_store()
    try:
        result = build_squad_evaluation(team_payload, store, use_saved_lineup=False)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Squad evaluation failed: {_format_squad_eval_error(exc)}",
        ) from exc
    return {"squad": result, "draft": True}


def _can_view_experiment(
    exp: dict[str, Any],
    user: str | None,
    *,
    is_admin_token: bool,
) -> bool:
    if _is_admin_session(user) or is_admin_token:
        return True
    if not user:
        return False
    return experiments.can_team_view_experiment(exp)


@app.get("/api/experiments")
def my_experiments(
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _require_admin_session_or_token(x_session_token, x_admin_token)
    user = auth.get_user(x_session_token)
    if _is_admin_session(user):
        return {"experiments": experiments.list_experiments(user=user)}
    return {"experiments": experiments.list_experiments()}


@app.post("/api/experiments")
def create_experiment(
    body: ExperimentRequest,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    user = _session_user(x_session_token)
    is_admin = _is_admin(x_admin_token)
    if not auth.can_run_simulations(user, is_admin_token=is_admin):
        raise HTTPException(
            status_code=403,
            detail=(
                "Creating simulations requires admin access. "
                "Squad logins can view squad evaluation and scout opponents at /squad."
            ),
        )
    try:
        summary = experiments.create_and_run_experiment(
            user,
            {
                "team_a": body.team_a,
                "team_b": body.team_b,
                "simulations": body.simulations,
                "seed": body.seed,
            },
            is_admin=is_admin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"experiment": summary}


@app.delete("/api/experiments/{exp_id}")
def delete_experiment_api(
    exp_id: str,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _require_admin_session_or_token(x_session_token, x_admin_token)
    try:
        result = experiments.delete_experiment(exp_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, **result}


@app.get("/api/experiments/{exp_id}")
def get_experiment(
    exp_id: str,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    exp = experiments.load_experiment(exp_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    user = auth.get_user(x_session_token)
    is_admin_token = _is_admin(x_admin_token)
    if not user and not is_admin_token:
        raise HTTPException(status_code=401, detail="Login required")
    if not _can_view_experiment(exp, user, is_admin_token=is_admin_token):
        raise HTTPException(
            status_code=403,
            detail="This simulation is not available. Watch live matches on /matchday.",
        )
    return {"experiment": exp}


def _format_squad_eval_error(exc: Exception) -> str:
    msg = str(exc).strip()
    if "Chrome not found" in msg:
        return (
            "Squad evaluation attempted a live stats fetch (Chrome/soccerdata). "
            "This should use cached stats only — please report if you see this."
        )
    if isinstance(exc, KeyError):
        detail = msg.strip("'")
        if detail.startswith(("No cached stats", "No top-league stats", "Missing player")):
            return detail
        return f"Missing player stats: {detail}"
    return msg


def _load_sheet_team_payload(team_name: str) -> dict[str, Any]:
    from google_sheets_teams import load_team_by_name

    store = sim_state.get_stats_store()
    try:
        return load_team_by_name(team_name, store=store)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _resolve_squad_team_name(
    session_user: str,
    *,
    team: str | None,
    is_admin_token: bool,
) -> str:
    if team and (_is_admin_session(session_user) or is_admin_token):
        return team.strip()
    if auth.is_team_user(session_user):
        return session_user
    if team:
        return team.strip()
    if _is_admin_session(session_user):
        raise HTTPException(status_code=400, detail="Provide ?team= for squad evaluation.")
    raise HTTPException(status_code=403, detail="Not a sheet team login.")


@app.get("/api/squad/opponents")
def squad_opponents(
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """List Google Sheet teams available for scouting."""
    user = _session_user(x_session_token)
    from google_sheets_teams import list_sheet_teams

    try:
        teams = list_sheet_teams()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    my_team: str | None = None
    if auth.is_team_user(user):
        my_team = user
        teams = [t for t in teams if t["name"].lower() != user.lower()]
    elif not (_is_admin_session(user) or _is_admin(x_admin_token)):
        raise HTTPException(status_code=403, detail="Squad access requires team or admin login.")

    return {"my_team": my_team, "teams": teams}


@app.get("/api/my-squad")
def my_squad_api(
    team: str | None = None,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Full squad evaluation for the logged-in sheet team (admin may pass ?team=)."""
    user = _session_user(x_session_token)
    is_admin = _is_admin(x_admin_token)
    if not (auth.is_team_user(user) or _is_admin_session(user) or is_admin):
        raise HTTPException(status_code=403, detail="Squad evaluation requires team or admin login.")

    team_name = _resolve_squad_team_name(user, team=team, is_admin_token=is_admin)
    if auth.is_team_user(user) and team_name.lower() != user.lower():
        raise HTTPException(status_code=403, detail="You can only view your own squad evaluation.")

    from squad_intel import build_squad_evaluation

    team_payload = _load_sheet_team_payload(team_name)
    store = sim_state.get_stats_store()
    try:
        result = build_squad_evaluation(team_payload, store)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Squad evaluation failed: {_format_squad_eval_error(exc)}",
        ) from exc
    return {"squad": result}


@app.get("/api/scout/{opponent_name}")
def scout_opponent_api(
    opponent_name: str,
    my_team: str | None = None,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Limited opponent scout report (comparative, no score predictions)."""
    user = _session_user(x_session_token)
    is_admin = _is_admin(x_admin_token)
    if not (auth.is_team_user(user) or _is_admin_session(user) or is_admin):
        raise HTTPException(status_code=403, detail="Scouting requires team or admin login.")

    my_team_name = _resolve_squad_team_name(user, team=my_team, is_admin_token=is_admin)
    if auth.is_team_user(user) and my_team_name.lower() != user.lower():
        raise HTTPException(status_code=403, detail="You can only scout from your own squad perspective.")
    if opponent_name.strip().lower() == my_team_name.lower():
        raise HTTPException(status_code=400, detail="Cannot scout your own team — use /api/my-squad.")

    from squad_intel import build_opponent_scout

    my_payload = _load_sheet_team_payload(my_team_name)
    opp_payload = _load_sheet_team_payload(opponent_name)
    store = sim_state.get_stats_store()
    try:
        report = build_opponent_scout(my_payload, opp_payload, store)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Scout report failed: {_format_squad_eval_error(exc)}",
        ) from exc
    return {"scout": report}


@app.get("/api/admin/experiments")
def admin_experiments(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    return {"experiments": experiments.list_experiments()}


@app.get("/api/admin/team-lineups")
def admin_team_lineups(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    return {"teams": team_lineups.list_team_lineups()}


@app.post("/api/admin/team-lineups/unfinalize-all")
def admin_unfinalize_all_lineups(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> dict:
    _require_admin_session_or_token(x_session_token, x_admin_token)
    cleared = team_lineups.clear_all_finalize_locks()
    return {
        "ok": True,
        "cleared": cleared,
        "message": f"Unfinalized {cleared} team lineup(s).",
    }


@app.post("/api/admin/team-lineups/{team_name}/unfinalize")
def admin_unfinalize_lineup(
    team_name: str,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> dict:
    _require_admin_session_or_token(x_session_token, x_admin_token)
    record = team_lineups.admin_unfinalize_team_lineup(team_name)
    if not record:
        raise HTTPException(status_code=404, detail="No saved lineup for that team.")
    return {"ok": True, "lineup": record}


@app.get("/api/admin/team-passwords")
def admin_team_passwords(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    return {"teams": auth.list_team_password_status()}


@app.post("/api/admin/team-passwords/reset")
def admin_reset_team_password(
    body: TeamPasswordResetRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    team = auth.resolve_sheet_team(body.team_name)
    if not team:
        raise HTTPException(status_code=400, detail="Unknown team.")
    if not auth.reset_team_password(team):
        raise HTTPException(status_code=404, detail="Team has no password set.")
    return {"ok": True, "team": team, "message": f"Password reset for {team}. Team must set a new password on next login."}


@app.post("/api/admin/sessions/clear")
def admin_clear_sessions(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Revoke all user session tokens (forces re-login everywhere)."""
    _check_admin(x_admin_token)
    cleared = auth.clear_all_sessions()
    return {"ok": True, "cleared": cleared, "message": f"Revoked {cleared} session(s)."}


@app.post("/api/admin/experiments")
def admin_create_experiment(
    body: ExperimentRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Run a new experiment as admin (no user session required)."""
    _check_admin(x_admin_token)
    try:
        summary = experiments.create_and_run_experiment(
            "admin",
            {
                "team_a": body.team_a,
                "team_b": body.team_b,
                "simulations": body.simulations,
                "seed": body.seed,
            },
            is_admin=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"experiment": summary}


@app.get("/api/state")
def get_state() -> dict:
    """Legacy global state endpoint."""
    return sim_state.load_state()


@app.post("/api/run")
def run_monte_carlo(
    body: RunRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    if sim_state.is_running():
        raise HTTPException(status_code=409, detail="Simulation already in progress")

    def _job() -> None:
        try:
            sim_state.run_simulation(n_simulations=body.simulations, seed=body.seed)
        except Exception:
            pass

    threading.Thread(target=_job, daemon=True).start()
    return {
        "started": True,
        "simulations": body.simulations,
        "message": "Simulation started.",
    }


@app.get("/")
def landing_page() -> FileResponse:
    return FileResponse(STATIC / "landing.html")


@app.get("/home")
def home_page() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/login")
def login_page() -> FileResponse:
    return FileResponse(STATIC / "login.html")


@app.get("/lab")
def lab_page() -> FileResponse:
    return FileResponse(STATIC / "lab.html")


@app.get("/squad")
def squad_page() -> FileResponse:
    return FileResponse(STATIC / "squad.html")


@app.get("/matchday")
def matchday_page() -> FileResponse:
    return FileResponse(STATIC / "matchday.html")


@app.get("/experiment/{exp_id}")
def experiment_page(exp_id: str) -> FileResponse:
    return FileResponse(STATIC / "experiment.html")


@app.get("/admin")
def admin_page() -> FileResponse:
    return FileResponse(STATIC / "admin.html")


@app.get("/tournament")
def tournament_page() -> FileResponse:
    return FileResponse(STATIC / "tournament.html")


@app.get("/tournament/admin")
def tournament_admin_page() -> RedirectResponse:
    return RedirectResponse(url="/admin#tournament", status_code=302)


@app.get("/api/tournament")
def list_tournaments_api() -> dict:
    """Public read — tournament viewer does not require user login."""
    return {"tournaments": tournament.list_tournaments()}


@app.delete("/api/tournament/{tournament_id}")
def delete_tournament_api(
    tournament_id: str,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _require_admin_session_or_token(x_session_token, x_admin_token)
    try:
        result = tournament.delete_tournament(tournament_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, **result}


@app.get("/api/tournament/{tournament_id}")
def get_tournament_api(tournament_id: str) -> dict:
    t = tournament.load_tournament(tournament_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return {"tournament": tournament.tournament_for_api(t)}


@app.get("/api/tournament/{tournament_id}/matches/{match_id}/analysis")
def get_tournament_match_analysis_api(tournament_id: str, match_id: str):
    """Return match analysis, or 202 while a background build is in progress.

    First click starts the job (does not hold the HTTP request for Monte Carlo).
    Poll this endpoint until ``status`` is ``ready``.
    """
    try:
        payload = tournament.get_match_analysis(tournament_id, match_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.get("status") == "generating":
        return JSONResponse(payload, status_code=202)
    if payload.get("status") == "error":
        raise HTTPException(
            status_code=500,
            detail=payload.get("message") or "Analysis generation failed",
        )
    return payload


@app.post("/api/tournament/{tournament_id}/matches/{match_id}/analysis")
def generate_tournament_match_analysis_api(
    tournament_id: str,
    match_id: str,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    """Admin backfill: start a background rebuild (does not change score)."""
    _check_admin(x_admin_token)
    try:
        payload = tournament.generate_match_analysis(tournament_id, match_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analysis generation failed: {exc}") from exc
    if payload.get("status") == "generating":
        return JSONResponse(payload, status_code=202)
    if payload.get("status") == "error":
        raise HTTPException(
            status_code=500,
            detail=payload.get("message") or "Analysis generation failed",
        )
    return payload


@app.post("/api/tournament")
def create_tournament_api(
    body: TournamentCreateRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    try:
        t = tournament.create_tournament(body.name, body.team_names, body.settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tournament": t}


@app.post("/api/tournament/{tournament_id}/teams")
def set_tournament_teams_api(
    tournament_id: str,
    body: TournamentTeamsRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    try:
        t = tournament.set_teams(tournament_id, body.team_names)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tournament": t}


@app.post("/api/tournament/{tournament_id}/group-draw")
def tournament_group_draw_api(
    tournament_id: str,
    body: TournamentDrawRequest | None = None,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    seed = body.seed if body else None
    try:
        t = tournament.perform_group_draw(tournament_id, seed=seed)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tournament": t}


@app.post("/api/tournament/{tournament_id}/group-fixtures")
def tournament_group_fixtures_api(
    tournament_id: str,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    try:
        t = tournament.generate_group_fixtures(tournament_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tournament": t}


@app.post("/api/tournament/{tournament_id}/matches/{match_id}/run")
def run_group_match_api(
    tournament_id: str,
    match_id: str,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    try:
        return tournament.run_group_match(tournament_id, match_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Match run failed: {exc}") from exc


@app.post("/api/tournament/{tournament_id}/matches/{match_id}/complete-from-board")
def complete_match_from_board_api(
    tournament_id: str,
    match_id: str,
    body: TournamentMatchOverrideRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Save official result from the interactive tactic-board pin score."""
    _check_admin(x_admin_token)
    try:
        return tournament.complete_from_board(
            tournament_id,
            match_id,
            home_goals=body.home_goals,
            away_goals=body.away_goals,
            winner=body.winner,
            board_events=body.board_events,
            match_log=body.match_log,
            decided_by=body.decided_by,
            ft_home_goals=body.ft_home_goals,
            ft_away_goals=body.ft_away_goals,
            pens_home=body.pens_home,
            pens_away=body.pens_away,
            score_display=body.score_display,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/tournament/{tournament_id}/knockout/generate")
def generate_knockout_api(
    tournament_id: str,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    try:
        t = tournament.generate_knockout_bracket(tournament_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tournament": t}


@app.post("/api/tournament/{tournament_id}/knockout/matches/{match_id}/run")
def run_knockout_match_api(
    tournament_id: str,
    match_id: str,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    try:
        return tournament.run_knockout_match(tournament_id, match_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Match run failed: {exc}") from exc


@app.post("/api/tournament/{tournament_id}/knockout/matches/{match_id}/complete-from-board")
def complete_knockout_from_board_api(
    tournament_id: str,
    match_id: str,
    body: TournamentMatchOverrideRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Save official knockout result from the interactive tactic-board pin score."""
    _check_admin(x_admin_token)
    try:
        return tournament.complete_from_board(
            tournament_id,
            match_id,
            home_goals=body.home_goals,
            away_goals=body.away_goals,
            winner=body.winner,
            board_events=body.board_events,
            match_log=body.match_log,
            decided_by=body.decided_by,
            ft_home_goals=body.ft_home_goals,
            ft_away_goals=body.ft_away_goals,
            pens_home=body.pens_home,
            pens_away=body.pens_away,
            score_display=body.score_display,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/tournament/{tournament_id}/matches/{match_id}/accept")
def accept_match_result_api(
    tournament_id: str,
    match_id: str,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    try:
        return tournament.accept_match_result(tournament_id, match_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/tournament/{tournament_id}/matches/{match_id}/override")
def override_match_result_api(
    tournament_id: str,
    match_id: str,
    body: TournamentMatchOverrideRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    try:
        return tournament.override_match_result(
            tournament_id,
            match_id,
            home_goals=body.home_goals,
            away_goals=body.away_goals,
            winner=body.winner,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/tournament/{tournament_id}/status")
def patch_tournament_status_api(
    tournament_id: str,
    body: TournamentStatusRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    try:
        t = tournament.set_status(tournament_id, body.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tournament": t}


@app.patch("/api/tournament/{tournament_id}/settings")
def patch_tournament_settings_api(
    tournament_id: str,
    body: TournamentSettingsRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    payload: dict[str, Any] = {}
    if body.group_count is not None:
        payload["group_count"] = body.group_count
    if body.teams_per_group is not None:
        payload["teams_per_group"] = body.teams_per_group
    if body.advance_per_group is not None:
        payload["advance_per_group"] = body.advance_per_group
    if not payload:
        raise HTTPException(
            status_code=400,
            detail="Provide group_count, teams_per_group, or advance_per_group",
        )
    try:
        t = tournament.update_settings(tournament_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tournament": t}


@app.on_event("startup")
def _startup() -> None:
    """Revoke login sessions on start; restore Matchday snapshot if one was mid-match; init database if on Render."""
    # Initialize database tables if DATABASE_URL is set (running on Render)
    try:
        import db
        if db.is_db_enabled():
            db.init_db()
            print("Database: tables initialized successfully (PostgreSQL enabled)")
        else:
            print("Database: disabled (not on Render) — using JSON files locally")
    except (ImportError, Exception) as e:
        print(f"Database: init warning: {e}")

    cleared = auth.clear_all_sessions()
    if cleared:
        print(f"Sessions: cleared {cleared} active session(s) on startup.")
    if matchday_session.restore_from_disk():
        print("Matchday: active session restored from data/matchday_session.json")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
