"""FastAPI web server — multi-user experiments, viewer, admin."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from web import auth, experiments, state as sim_state, tournament

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
    formation: str = "4-3-3"
    players: list[str] = Field(default_factory=list)


class LineupRandomRequest(BaseModel):
    formation: str = "4-3-3"
    count: int = Field(default=11, ge=1, le=11)
    seed: int | None = None


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
def health() -> dict:
    return {"ok": True, "version": "2.1", "sheets_api": True}


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
                "or admin / admin."
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
    formation: str = "4-3-3",
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
    _require_sim_builder(x_session_token, x_admin_token)
    from formation_fit import FORMATION_SLOTS, team_formation_fit
    from lineup_builder import assign_lineup_slots, lineup_from_assignments

    formation = body.formation if body.formation in FORMATION_SLOTS else "4-3-3"
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

    formation = body.formation if body.formation in FORMATION_SLOTS else "4-3-3"
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


@app.get("/api/matchday")
def matchday_experiments(
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Admin matchday simulation history (admin session or SIM_ADMIN_TOKEN only)."""
    _require_admin_session_or_token(x_session_token, x_admin_token)
    return {"experiments": experiments.list_matchday_experiments()}


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


@app.get("/api/experiments/{exp_id}")
def get_experiment(
    exp_id: str,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    exp = experiments.load_experiment(exp_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    _require_admin_session_or_token(x_session_token, x_admin_token)
    return {"experiment": exp}


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
            detail=f"Squad evaluation failed: {exc}",
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
            detail=f"Scout report failed: {exc}",
        ) from exc
    return {"scout": report}


@app.get("/api/admin/experiments")
def admin_experiments(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _check_admin(x_admin_token)
    return {"experiments": experiments.list_experiments()}


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


@app.get("/api/tournament/{tournament_id}")
def get_tournament_api(tournament_id: str) -> dict:
    t = tournament.load_tournament(tournament_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return {"tournament": t}


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
    if not payload:
        raise HTTPException(status_code=400, detail="Provide group_count or teams_per_group")
    try:
        t = tournament.update_settings(tournament_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tournament": t}


@app.on_event("startup")
def _clear_sessions_on_startup() -> None:
    """Revoke all sessions on server start so deploys force re-login."""
    cleared = auth.clear_all_sessions()
    if cleared:
        print(f"Sessions: cleared {cleared} active session(s) on startup.")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
