"""Cross-tournament purse ledger for the League+Cup format.

Only the starting purse (each team's "BUDGET LEFT" from the roster
workbook) is ever persisted, and only once, frozen on first read. Every
tournament's contribution to a team's purse -- league results, cup
qualification, playoff, cup-tie outcomes -- is recomputed fresh from that
tournament's current state on every call, the same JIT (just-in-time)
philosophy team_discipline.py already established for the 5-yellow
suspension rule: this makes the system self-healing against admin result
corrections with no clawback code needed, and correct from the very first
check even for matches played before this feature existed (no backfill
migration required -- a tournament's fixtures/ties already show `played:
true` in its stored state; recomputing from that state picks them up
exactly as if they'd just been played).

"Carried over for tournament renewals" falls out of this design for free:
a team's total purse is its frozen starting budget plus the summed
contribution of every League+Cup tournament it has ever appeared in. A
new tournament (a "renewal") is just one more tournament in that sum --
no explicit renewal event or migration step is needed.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PURSE_PATH = ROOT / "data" / "team_purse.json"

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_all() -> dict[str, Any]:
    if not PURSE_PATH.exists():
        return {}
    try:
        return json.loads(PURSE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(data: dict[str, Any]) -> None:
    """Never raises -- a save failure here must never fail an unrelated
    tournament-fetch request."""
    try:
        PURSE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PURSE_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception as exc:
        print(f"team_purse: save failed: {exc}")


def get_starting_purse(team_name: str) -> float:
    """This team's frozen starting purse. Reads and freezes it from the
    roster workbook's BUDGET LEFT value on first call for this team;
    every later call returns the same frozen value regardless of what the
    workbook says by then (the workbook is a live-replaceable snapshot --
    see google_sheets_teams.py's own module docstring -- so a later season's
    re-auction must not silently rewrite an already-running purse)."""
    with _lock:
        store = _load_all()
        record = store.get(team_name)
        if record is not None:
            return float(record.get("starting_purse") or 0.0)

    try:
        import google_sheets_teams

        value = google_sheets_teams.get_team_budget_left(team_name)
    except Exception as exc:
        print(f"team_purse: get_team_budget_left({team_name!r}) failed: {exc}")
        value = None
    starting = float(value) if value is not None else 0.0

    with _lock:
        store = _load_all()
        if team_name not in store:
            store[team_name] = {"starting_purse": starting, "frozen_at": _now()}
            _save_all(store)
        return float(store[team_name].get("starting_purse") or 0.0)


def _league_contribution(t: dict[str, Any], team: str) -> int:
    total = 0
    for fx in (t.get("league") or {}).get("fixtures") or []:
        if not fx.get("played") or team not in (fx.get("home"), fx.get("away")):
            continue
        is_home = fx.get("home") == team
        team_goals = fx.get("home_goals") if is_home else fx.get("away_goals")
        opp_goals = fx.get("away_goals") if is_home else fx.get("home_goals")
        if team_goals is None or opp_goals is None:
            continue
        if team_goals > opp_goals:
            total += 100
        elif team_goals == opp_goals:
            total += 50
    return total


def _qualification_contribution(t: dict[str, Any], team: str) -> int:
    """Top-6-after-GW9 direct cup qualification, +50. Derived as "every
    team minus whichever 4 appear across the 2 playoff ties" rather than
    re-sorting the league table, which keeps evolving through GW10-18
    after the cup has already started -- the 4 playoff participants are
    locked in permanently the moment the playoff ties are created and
    never change, so this has no staleness risk."""
    ties = ((t.get("cup") or {}).get("playoff") or {}).get("ties") or []
    if not ties:
        return 0  # GW9 hasn't completed yet -- top 6 not yet knowable
    participants = {ti.get(side) for ti in ties for side in ("home", "away") if ti.get(side)}
    return 50 if team not in participants else 0


def _playoff_contribution(t: dict[str, Any], team: str) -> int:
    ties = ((t.get("cup") or {}).get("playoff") or {}).get("ties") or []
    return 25 if any(ti.get("played") and ti.get("winner") == team for ti in ties) else 0


def _cup_round_contribution(t: dict[str, Any], team: str) -> int:
    """The actual cup bracket (R8/SF/Final) only -- deliberately excludes
    the playoff ties, which already carry their own +25 qualification-only
    bonus above and are kept structurally separate (t["cup"]["playoff"]
    vs. t["cup"]["rounds"]) in the tournament data itself."""
    total = 0
    for rnd in (t.get("cup") or {}).get("rounds") or []:
        for ti in rnd.get("ties") or []:
            if not ti.get("played"):
                continue
            if ti.get("winner") == team:
                total += 50
            elif team in (ti.get("home"), ti.get("away")):
                total -= 25
    return total


def tournament_contribution(t: dict[str, Any], team: str) -> dict[str, int]:
    """Pure function of tournament state -- no I/O, always safe to call
    freely and repeatedly."""
    league_bonus = _league_contribution(t, team)
    qualification_bonus = _qualification_contribution(t, team)
    playoff_bonus = _playoff_contribution(t, team)
    cup_bonus = _cup_round_contribution(t, team)
    return {
        "league_bonus": league_bonus,
        "qualification_bonus": qualification_bonus,
        "playoff_bonus": playoff_bonus,
        "cup_bonus": cup_bonus,
        "subtotal": league_bonus + qualification_bonus + playoff_bonus + cup_bonus,
    }


def purse_table_for_tournament(t: dict[str, Any]) -> dict[str, Any]:
    """Every team's full purse breakdown for tournament `t` -- starting
    purse, every OTHER League+Cup tournament this team has ever been part
    of (summed), and this tournament's own contribution."""
    team_names = [str(n) for n in (t.get("team_names") or [])]
    this_id = t.get("id")

    # Sum every other League+Cup tournament's contribution per team.
    # Tournaments as the outer loop, teams as the inner loop, so each
    # other tournament document is loaded and scanned once, not once per
    # team.
    prior_totals: dict[str, int] = {name: 0 for name in team_names}
    try:
        from web import tournament as tmod

        for summary in tmod.list_tournaments():
            other_id = summary.get("id")
            if not other_id or other_id == this_id:
                continue
            other_t = tmod.load_tournament(other_id)
            if not other_t or other_t.get("format") != "league_cup":
                continue
            other_teams = set(other_t.get("team_names") or [])
            for name in team_names:
                if name in other_teams:
                    prior_totals[name] += tournament_contribution(other_t, name)["subtotal"]
    except Exception as exc:
        print(f"team_purse: prior-tournament scan failed: {exc}")

    rows = []
    for name in team_names:
        starting = get_starting_purse(name)
        prior = prior_totals.get(name, 0)
        this_tournament = tournament_contribution(t, name)
        total = starting + prior + this_tournament["subtotal"]
        rows.append({
            "team": name,
            "starting_purse": starting,
            "league_bonus": this_tournament["league_bonus"],
            "qualification_bonus": this_tournament["qualification_bonus"],
            "playoff_bonus": this_tournament["playoff_bonus"],
            "cup_bonus": this_tournament["cup_bonus"],
            "this_tournament_total": this_tournament["subtotal"],
            "prior_tournaments_total": prior,
            "total_purse": total,
        })
    rows.sort(key=lambda r: r["total_purse"], reverse=True)
    return {"teams": rows}
