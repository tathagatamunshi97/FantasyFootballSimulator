"""Assign formation slots to an unordered list of 11 players."""
from __future__ import annotations

import random
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from formation_fit import FORMATION_SLOTS, player_slot_fit
from models import FantasyTeam, LineupSlot, PlayerStats

_FPL_QUOTAS: dict[str, int] = {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2}


def _slot_order(formation: str) -> list[str]:
    slots = FORMATION_SLOTS.get(formation, FORMATION_SLOTS["4-4-2"])
    return [s["slot"] for s in slots]


def _is_gk(stats: PlayerStats | None) -> bool:
    if stats is None:
        return False
    return stats.fpl_position == "GK" or stats.primary_position.upper() == "GK"


def select_starting_xi(
    formation: str,
    player_names: list[str],
    player_stats: dict[str, PlayerStats],
) -> list[str]:
    """Pick the best 11 from a squad of any size (uses optimal slot assignment)."""
    pairs = assign_lineup_slots(formation, player_names, player_stats, max_players=None)
    return [player for player, _ in pairs if player]


def assign_lineup_slots(
    formation: str,
    player_names: list[str],
    player_stats: dict[str, PlayerStats],
    *,
    max_players: int | None = 11,
) -> list[tuple[str, str]]:
    """
    Optimal slot assignment (max total fit) via Hungarian algorithm.
    Works for 1–11 players; partial rosters leave other slots empty in the UI.
    GK slot stays empty unless a goalkeeper is in the squad.
    When max_players is None, all named players are eligible (for squads > 11).
    """
    players = [p for p in player_names if p]
    if max_players is not None:
        players = players[:max_players]
    if not players:
        return []

    all_slots = _slot_order(formation)
    assignments: list[tuple[str, str]] = []
    remaining_players = players[:]
    remaining_slots = all_slots[:]

    gk_players = [p for p in remaining_players if _is_gk(player_stats.get(p))]
    if "GK" in remaining_slots:
        if gk_players:
            gk = gk_players[0]
            assignments.append((gk, "GK"))
            remaining_players.remove(gk)
        remaining_slots = [s for s in remaining_slots if s != "GK"]

    if not remaining_players or not remaining_slots:
        return assignments

    n_slots = len(remaining_slots)
    n_players = len(remaining_players)
    cost = np.zeros((n_slots, n_players))
    for i, slot in enumerate(remaining_slots):
        for j, player in enumerate(remaining_players):
            stats = player_stats.get(player)
            if stats is None:
                cost[i, j] = 0.0
            else:
                cost[i, j] = -player_slot_fit(stats, formation, slot)

    row_ind, col_ind = linear_sum_assignment(cost)
    assignments.extend(
        (remaining_players[col_ind[i]], remaining_slots[row_ind[i]]) for i in range(len(col_ind))
    )
    return assignments


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
