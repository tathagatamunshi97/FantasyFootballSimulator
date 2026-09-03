"""Season-long discipline -> 1-match suspension.

Two independent triggers, both JIT (just-in-time), not event-driven: every
check recomputes a team's card totals fresh from the tournament's full match
history (via tournament.aggregate_player_tallies) rather than trusting an
incrementally maintained counter. This makes the system self-healing against
admin result corrections, and — just as importantly — correct from the very
first check even for matches played before this feature existed, with no
backfill migration required: the first time a team's lineup is saved/
finalized after this ships, a player who already crossed a threshold from
history is caught immediately, exactly as if it had just happened.

  1. Yellow-card accumulation: every 5th yellow (career-in-tournament, not
     per-match) earns a 1-match ban.
  2. Red card: every single red card (straight or second-yellow) earns its
     own immediate 1-match ban, independent of the yellow count -- a red
     card doesn't also need to cross a yellow tier to matter.

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
    record any newly-crossed 5-yellow tier AND any new red card as a
    suspension pinned to `round_key` (the round currently being checked --
    always the team's actual current immediate round in normal use), lazily
    clear any previously-recorded suspension whose round has since been
    played (its stored round_key no longer equals the current one), and
    return the set of player names still suspended for `round_key`.

    The two triggers are tracked as separate running counts on the same
    per-player record (`tiers_served` for yellow tiers, `red_cards_served`
    for red cards) so a player who both crosses a yellow tier and picks up
    a red card in the same match correctly earns two independent bans, not
    one double-counted as the other.

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

    totals: dict[str, dict[str, int]] = {}
    for row in aggregate_player_tallies(t):
        if str(row.get("team") or "") != team_name:
            continue
        player = str(row.get("player") or "").strip()
        if player:
            totals[player] = {
                "cards": int(row.get("cards") or 0),
                "red_cards": int(row.get("red_cards") or 0),
            }

    with _lock:
        store = _load_all()
        bucket = store.setdefault(tournament_id, {})
        changed = False
        suspended: set[str] = set()

        for player, counts in totals.items():
            key = _player_key(team_name, player)
            record = bucket.get(key) or {"tiers_served": 0, "red_cards_served": 0, "suspensions": []}
            tiers_served = int(record.get("tiers_served") or 0)
            red_cards_served = int(record.get("red_cards_served") or 0)
            current_tier = counts["cards"] // SUSPENSION_THRESHOLD
            current_reds = counts["red_cards"]

            def _pending(reason: str) -> list[dict[str, Any]]:
                return [
                    s
                    for s in record["suspensions"]
                    if not s.get("served") and s.get("reason", "yellow_accumulation") == reason
                ]

            pending_yellow = _pending("yellow_accumulation")
            recorded_tiers = tiers_served + len(pending_yellow)
            if current_tier > recorded_tiers:
                for _ in range(current_tier - recorded_tiers):
                    record["suspensions"].append(
                        {"round_key": round_key, "served": False, "reason": "yellow_accumulation"}
                    )
                changed = True
                pending_yellow = _pending("yellow_accumulation")

            pending_red = _pending("red_card")
            recorded_reds = red_cards_served + len(pending_red)
            if current_reds > recorded_reds:
                for _ in range(current_reds - recorded_reds):
                    record["suspensions"].append(
                        {"round_key": round_key, "served": False, "reason": "red_card"}
                    )
                changed = True
                pending_red = _pending("red_card")

            for susp in pending_yellow:
                if susp.get("round_key") == round_key:
                    suspended.add(player)
                else:
                    # A pending suspension's flagged round no longer matches
                    # the team's current round -- that round has been played
                    # (a team's immediate round only ever advances forward),
                    # so the suspension has been served.
                    susp["served"] = True
                    record["tiers_served"] = tiers_served + 1
                    tiers_served += 1
                    changed = True

            for susp in pending_red:
                if susp.get("round_key") == round_key:
                    suspended.add(player)
                else:
                    susp["served"] = True
                    record["red_cards_served"] = red_cards_served + 1
                    red_cards_served += 1
                    changed = True

            bucket[key] = record

        if changed:
            store[tournament_id] = bucket
            _save_all(store)

    return suspended


def sync_after_match(t: dict[str, Any], team_name: str) -> None:
    """Force the discipline check to run for `team_name` right after one of
    their matches completes, instead of only ever discovering a trigger the
    next time someone happens to save/finalize a lineup.

    The JIT design in get_suspended_players() is otherwise blind to timing:
    it only updates state when called, so if nobody saves a lineup during
    the round immediately after a card trigger (e.g. that round's lineup
    was already locked in advance of the match that produced the card),
    the trigger goes undiscovered until whatever later round the team next
    happens to save a lineup for -- banning them a round or more late
    instead of the one that should have been affected. Calling this right
    after complete_from_board stores a result means get_team_immediate_round
    already reflects that match as played, so a newly-crossed threshold
    always gets pinned to the correct next fixture, independent of when the
    team next touches their lineup. Fail-open, matching every other
    function in this module -- a sync hiccup must never break match
    completion.
    """
    try:
        from web.tournament import get_team_immediate_round

        round_key = get_team_immediate_round(team_name, tournament=t).get("round_key")
        _sync_and_get_suspended(t, team_name, round_key)
    except Exception as exc:
        print(f"team_discipline: sync_after_match({team_name!r}) failed: {exc}")


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


def clear_pending_suspensions(tournament_id: str, team_name: str, player_name: str) -> int:
    """Admin correction: mark every currently-unserved suspension for this
    player as served, without requiring the round it's pinned to be played.

    Exists for exactly the case sync_after_match's fix can't retroactively
    repair: a suspension recorded before the fix shipped, already pinned to
    the wrong (too-late) round because its correct round already passed
    unenforced. Continuing to enforce it against a later round extends the
    punishment past what the 1-match rule actually calls for, so this lets
    an admin clear it explicitly rather than leaving it to self-heal into
    the wrong outcome. Not needed for anything sync_after_match itself
    creates going forward -- those are pinned correctly at the moment they're
    recorded, with no reason to ever need a manual clear.
    """
    with _lock:
        store = _load_all()
        bucket = store.get(tournament_id) or {}
        key = _player_key(team_name, player_name)
        record = bucket.get(key)
        if not record:
            return 0
        cleared = 0
        for susp in record.get("suspensions") or []:
            if not susp.get("served"):
                susp["served"] = True
                susp["cleared_by_admin"] = True
                cleared += 1
                # Must bump the same served-counter _sync_and_get_suspended
                # itself would have bumped -- otherwise the next sync sees
                # current_tier/current_reds (computed fresh from the card
                # totals, unaffected by this admin action) still ahead of
                # tiers_served/red_cards_served and creates a *new*
                # suspension to make up the apparent gap, re-triggering the
                # very ban this call just cleared.
                reason = susp.get("reason", "yellow_accumulation")
                if reason == "red_card":
                    record["red_cards_served"] = int(record.get("red_cards_served") or 0) + 1
                else:
                    record["tiers_served"] = int(record.get("tiers_served") or 0) + 1
        if cleared:
            store[tournament_id] = bucket
            _save_all(store)
        return cleared


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
