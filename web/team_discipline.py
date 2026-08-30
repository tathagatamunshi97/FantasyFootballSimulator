"""Season-long yellow-card accumulation -> 1-match suspension.

Deliberately JIT (just-in-time), not event-driven: every check recomputes a
team's card totals fresh from the tournament's full match history (via
tournament.aggregate_player_tallies) rather than trusting an incrementally
maintained counter. This makes the system self-healing against admin result
corrections, and — just as importantly — correct from the very first check
even for matches played before this feature existed, with no backfill
migration required: the first time a team's lineup is saved/finalized after
this ships, a player who already had 5+ cards from history is caught
immediately, exactly as if the threshold had just been crossed.

Only outfield/roster-level bookkeeping: this module knows nothing about the
live match engine (no dependency on tactic_board.js's card events) — it
only reads the same aggregated event log tournament.py already exposes.
"""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DISCIPLINE_PATH = ROOT / "data" / "team_discipline.json"

_lock = threading.Lock()

SUSPENSION_THRESHOLD = 5


def _load_all() -> dict[str, Any]:
    """Load all discipline records from the JSON store.

    JSON-file only for v1 (no DB-backed path yet) -- team_lineups.py's own
    _save_all already treats DB failure as non-fatal (print-only), so this
    can follow the same durability tier once validated; not needed to ship
    the mechanic correctly today.
    """
    if not DISCIPLINE_PATH.exists():
        return {}
    try:
        return json.loads(DISCIPLINE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(data: dict[str, Any]) -> None:
    """Save all discipline records. Never raises -- a save failure here must
    never be able to fail an unrelated lineup save/finalize request."""
    try:
        DISCIPLINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        DISCIPLINE_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception as exc:
        print(f"team_discipline: save failed: {exc}")


def _player_key(team: str, player: str) -> str:
    return f"{team}\0{player}"


def _sync_and_get_suspended(t: dict[str, Any], team_name: str, round_key: str | None) -> set[str]:
    """Recompute `team_name`'s card totals from `t`'s full match history,
    record any newly-crossed 5-card tier as a suspension pinned to
    `round_key` (the round currently being checked -- always the team's
    actual current immediate round in normal use), lazily clear any
    previously-recorded suspension whose round has since been played (its
    stored round_key no longer equals the current one), and return the set
    of player names still suspended for `round_key`.

    Deliberately doesn't retract an already-recorded suspension if a result
    correction lowers a player's total back down -- a v1 simplification,
    corrections-after-suspension-triggered are rare and this avoids
    unwinding a ban a team may have already served around.
    """
    if not round_key or round_key == "ready":
        return set()
    tournament_id = t.get("id")
    if not tournament_id:
        return set()

    from web.tournament import aggregate_player_tallies

    totals: dict[str, int] = {}
    for row in aggregate_player_tallies(t):
        if str(row.get("team") or "") != team_name:
            continue
        player = str(row.get("player") or "").strip()
        if player:
            totals[player] = int(row.get("cards") or 0)

    with _lock:
        store = _load_all()
        bucket = store.setdefault(tournament_id, {})
        changed = False
        suspended: set[str] = set()

        for player, total in totals.items():
            key = _player_key(team_name, player)
            record = bucket.get(key) or {"tiers_served": 0, "suspensions": []}
            tiers_served = int(record.get("tiers_served") or 0)
            current_tier = total // SUSPENSION_THRESHOLD

            pending = [s for s in record["suspensions"] if not s.get("served")]
            recorded_tiers = tiers_served + len(pending)
            if current_tier > recorded_tiers:
                for _ in range(current_tier - recorded_tiers):
                    record["suspensions"].append({"round_key": round_key, "served": False})
                changed = True
                pending = [s for s in record["suspensions"] if not s.get("served")]

            for susp in pending:
                if susp.get("round_key") == round_key:
                    suspended.add(player)
                else:
                    # A pending suspension's flagged round no longer matches
                    # the team's current round -- that round has been played
                    # (a team's immediate round only ever advances forward),
                    # so the suspension has been served.
                    susp["served"] = True
                    record["tiers_served"] = tiers_served + 1
                    changed = True

            bucket[key] = record

        if changed:
            store[tournament_id] = bucket
            _save_all(store)

    return suspended


def get_suspended_players(team_name: str) -> set[str]:
    """Players on `team_name` currently suspended (card accumulation) for
    their team's next fixture. Fail-open: any lookup error returns an empty
    set rather than blocking an unrelated lineup save.
    """
    name = team_name.strip()
    if not name:
        return set()
    try:
        from web.tournament import find_active_tournament_for_team, get_team_immediate_round

        t = find_active_tournament_for_team(name)
        if not t:
            return set()
        round_key = get_team_immediate_round(name, tournament=t).get("round_key")
        return _sync_and_get_suspended(t, name, round_key)
    except Exception as exc:
        print(f"team_discipline: get_suspended_players({team_name!r}) failed, defaulting to none suspended: {exc}")
        return set()


def team_discipline_snapshot(tournament_id: str, team_name: str) -> list[dict[str, Any]]:
    """Read-only: this team's suspension history in this tournament (for a
    future Squad Hub UI surface -- not wired into any endpoint yet)."""
    store = _load_all()
    bucket = store.get(tournament_id) or {}
    out = []
    for key, record in bucket.items():
        try:
            team, player = key.split("\0", 1)
        except ValueError:
            continue
        if team != team_name:
            continue
        out.append({"player": player, **copy.deepcopy(record)})
    return out
