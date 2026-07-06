"""Assign formation slots to an unordered list of 11 players."""
from __future__ import annotations

import random
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from formation_fit import FORMATION_SLOTS, player_slot_fit
from models import FantasyTeam, LineupSlot, PlayerStats
from slot_roles import slot_role

_FPL_QUOTAS: dict[str, int] = {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2}


def _slot_order(formation: str) -> list[str]:
    slots = FORMATION_SLOTS.get(formation, FORMATION_SLOTS["4-4-2"])
    return [s["slot"] for s in slots]


def _is_gk(stats: PlayerStats | None) -> bool:
    if stats is None:
        return False
    return stats.fpl_position == "GK" or stats.primary_position.upper() == "GK"


def _player_quality(stats: PlayerStats | None) -> float:
    """Normalize Sofascore rating to 0–1 (typical range ~6.0–8.5)."""
    if stats is None or stats.rating <= 0:
        return 0.05
    return min(1.0, max(0.0, (stats.rating - 6.0) / 2.5))


def _assignment_score(stats: PlayerStats | None, formation: str, slot: str) -> float:
    """Combined slot fit + player quality for optimal XI/slot assignment."""
    if stats is None:
        return 0.0
    fit = player_slot_fit(stats, formation, slot)
    quality = _player_quality(stats)
    # Emphasize fit (wrong-position stars stay penalized); quality breaks close ties.
    return (fit ** 1.35) * (0.30 + 0.70 * quality)


def _hungarian_assign(
    formation: str,
    slots: list[str],
    players: list[str],
    player_stats: dict[str, PlayerStats],
) -> list[tuple[str, str]]:
    """Assign players to slots maximizing total combined fit + quality."""
    if not slots or not players:
        return []

    n_slots = len(slots)
    n_players = len(players)
    cost = np.zeros((n_slots, n_players))
    for i, slot in enumerate(slots):
        for j, player in enumerate(players):
            stats = player_stats.get(player)
            cost[i, j] = -_assignment_score(stats, formation, slot)

    row_ind, col_ind = linear_sum_assignment(cost)
    return [(players[col_ind[i]], slots[row_ind[i]]) for i in range(len(row_ind))]


def _slot_bucket(slot: str) -> str:
    """Map formation slot to broad role bucket for XI selection."""
    role = slot_role(slot)
    if role == "gk":
        return "GK"
    if role in ("centre_back", "fullback"):
        return "DEF"
    if role in ("winger", "striker"):
        return "FWD"
    return "MID"


def _formation_bucket_needs(formation: str) -> dict[str, int]:
    """How many GK/DEF/MID/FWD slots a formation requires."""
    needs: dict[str, int] = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}
    for slot in _slot_order(formation):
        needs[_slot_bucket(slot)] += 1
    return needs


def _best_bucket_score(
    stats: PlayerStats | None,
    formation: str,
    bucket: str,
) -> float:
    if stats is None:
        return 0.0
    slots = [s for s in _slot_order(formation) if _slot_bucket(s) == bucket]
    if not slots:
        return 0.0
    return max(_assignment_score(stats, formation, slot) for slot in slots)


def _eligible_for_bucket(stats: PlayerStats | None, bucket: str) -> bool:
    """FPL bucket must match formation role bucket for XI selection."""
    if stats is None:
        return False
    return _fpl_bucket(stats) == bucket


def _select_xi_by_formation_roles(
    formation: str,
    players: list[str],
    player_stats: dict[str, PlayerStats],
) -> list[str]:
    """
    Pick 11 players matching formation role counts (e.g. 4-3-3 → 1 GK, 4 DEF, 3 MID, 3 FWD).
    Rank within each bucket by best assignment score for that bucket's slots.
    """
    needs = _formation_bucket_needs(formation)
    selected: list[str] = []

    for bucket, quota in needs.items():
        if quota <= 0:
            continue
        ranked = sorted(
            (
                (_best_bucket_score(player_stats.get(p), formation, bucket), p)
                for p in players
                if p not in selected and _eligible_for_bucket(player_stats.get(p), bucket)
            ),
            reverse=True,
        )
        for _, player in ranked[:quota]:
            selected.append(player)

    if len(selected) < 11:
        remaining = [p for p in players if p not in selected]
        ranked = sorted(
            (
                (
                    max(
                        _assignment_score(player_stats.get(p), formation, slot)
                        for slot in _slot_order(formation)
                    ),
                    p,
                )
                for p in remaining
            ),
            reverse=True,
        )
        for _, player in ranked:
            selected.append(player)
            if len(selected) >= 11:
                break

    return selected[:11]


def select_starting_xi(
    formation: str,
    player_names: list[str],
    player_stats: dict[str, PlayerStats],
) -> list[str]:
    """Pick the best 11 from a squad of any size for the given formation."""
    players = [p for p in player_names if p]
    if not players:
        return []

    if len(players) <= 11:
        all_slots = _slot_order(formation)
        pairs = _hungarian_assign(formation, all_slots, players, player_stats)
        return [player for player, _ in pairs if player]

    # Squad > 11: pick role-balanced XI, then confirm via global slot assignment.
    candidates = _select_xi_by_formation_roles(formation, players, player_stats)
    all_slots = _slot_order(formation)
    pairs = _hungarian_assign(formation, all_slots, candidates, player_stats)
    return [player for player, _ in pairs if player]


def assign_lineup_slots(
    formation: str,
    player_names: list[str],
    player_stats: dict[str, PlayerStats],
    *,
    max_players: int | None = 11,
) -> list[tuple[str, str]]:
    """
    Optimal slot assignment (max total fit + quality) via Hungarian algorithm.
    Works for 1–11 players; partial rosters leave other slots empty in the UI.
    When max_players is None, all named players are eligible (for squads > 11).
    """
    players = [p for p in player_names if p]
    if max_players is not None:
        players = players[:max_players]
    if not players:
        return []

    all_slots = _slot_order(formation)
    return _hungarian_assign(formation, all_slots, players, player_stats)


def lineup_from_assignments(
    formation: str,
    assignments: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Build ordered lineup rows (all formation slots) from player-slot pairs."""
    slot_to_player = {slot: player for player, slot in assignments}
    slots = _slot_order(formation)
    return [
        {
            "slot": slot,
            "player": slot_to_player.get(slot, ""),
            "captain": False,
            "vice_captain": False,
        }
        for slot in slots
    ]


def _fpl_bucket(stats: PlayerStats) -> str:
    pos = (stats.fpl_position or stats.primary_position or "MID").upper()
    if pos == "GK":
        return "GK"
    if pos == "DEF":
        return "DEF"
    if pos == "FWD":
        return "FWD"
    return "MID"


def random_squad_players(
    player_stats: dict[str, PlayerStats],
    *,
    count: int = 11,
    seed: int | None = None,
) -> list[str]:
    """Pick *count* distinct players with at least one GK when available."""
    rng = random.Random(seed)
    by_pos: dict[str, list[str]] = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for name, stats in player_stats.items():
        by_pos[_fpl_bucket(stats)].append(name)

    quotas = dict(_FPL_QUOTAS)
    if count != 11:
        order = ["GK", "DEF", "MID", "FWD"]
        quotas = {k: 0 for k in order}
        remaining = count
        if remaining and by_pos["GK"]:
            quotas["GK"] = 1
            remaining -= 1
        for pos in ("DEF", "MID", "FWD"):
            if remaining <= 0:
                break
            share = max(1, round(remaining / (4 - order.index(pos))))
            share = min(share, remaining, len(by_pos[pos]) or share)
            quotas[pos] = share
            remaining -= share
        while remaining > 0:
            for pos in ("DEF", "MID", "FWD"):
                if remaining <= 0:
                    break
                quotas[pos] += 1
                remaining -= 1

    selected: list[str] = []
    for pos, quota in quotas.items():
        pool = by_pos[pos][:]
        rng.shuffle(pool)
        selected.extend(pool[:quota])

    if len(selected) < count:
        leftover = [n for n in player_stats if n not in selected]
        rng.shuffle(leftover)
        selected.extend(leftover[: count - len(selected)])

    if count >= 1 and not any(_fpl_bucket(player_stats[p]) == "GK" for p in selected if p in player_stats):
        gks = by_pos["GK"]
        if gks and selected:
            rng.shuffle(gks)
            selected[0] = gks[0]

    return selected[:count]


def random_lineup(
    formation: str,
    player_stats: dict[str, PlayerStats],
    *,
    count: int = 11,
    seed: int | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Build a random squad and assign formation slots."""
    if formation not in FORMATION_SLOTS:
        formation = "4-3-3"
    players = random_squad_players(player_stats, count=count, seed=seed)
    pairs = assign_lineup_slots(formation, players, player_stats)
    lineup = lineup_from_assignments(formation, pairs)
    return players, lineup


def build_fantasy_team(
    name: str,
    formation: str,
    player_names: list[str],
    player_stats: dict[str, PlayerStats],
    *,
    captain: str | None = None,
    vice_captain: str | None = None,
    bench: list[str] | None = None,
) -> FantasyTeam:
    pairs = assign_lineup_slots(formation, player_names, player_stats)
    lineup = [
        LineupSlot(
            player=player,
            slot=slot,
            is_captain=player == captain,
            is_vice_captain=player == vice_captain,
        )
        for player, slot in pairs
    ]
    return FantasyTeam(name=name, formation=formation, lineup=lineup, bench=bench or [])
