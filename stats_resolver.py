"""Resolve lineup stats with prime / pick-season overrides per team."""
from __future__ import annotations

import copy
from typing import Any

from models import PlayerStats
from seasonal_stats import (
    build_prime_stats_dict,
    build_season_stats_dict,
    normalize_season_input,
    season_label_from_suffix,
)
from sofascore_client import StatsStore


def _lineup_names(team: dict[str, Any]) -> set[str]:
    return {(row.get("player") or "").strip() for row in team.get("lineup", []) if row.get("player")}


def validate_season_overrides(team: dict[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    names = _lineup_names(team)
    prime = (team.get("prime_player") or "").strip()
    peak = team.get("peak_season") or {}
    peak_player = (peak.get("player") or "").strip()
    peak_season_raw = (peak.get("season") or "").strip()

    if prime and prime not in names:
        errors.append(f"{label}: prime player must be in the lineup.")
    if peak_player and peak_player not in names:
        errors.append(f"{label}: peak-season player must be in the lineup.")
    if peak_player and not peak_season_raw:
        errors.append(f"{label}: peak-season player requires a season.")
    if peak_season_raw and not peak_player:
        errors.append(f"{label}: peak season requires a player.")
    if prime and peak_player and prime == peak_player:
        errors.append(f"{label}: prime and peak-season must be different players.")
    if peak_season_raw:
        try:
            suffix = normalize_season_input(peak_season_raw)
            season_label_from_suffix(suffix)
        except ValueError as exc:
            errors.append(f"{label}: {exc}")
    return errors


def _apply_override(
    store: StatsStore,
    player_stats: dict[str, PlayerStats],
    raw_name: str,
    builder,
    meta: dict[str, Any],
) -> None:
    canon, data, season_label = builder(raw_name, store)
    player_stats[canon] = PlayerStats.from_dict(canon, data)
    meta["resolved_name"] = canon
    meta["season"] = season_label
    if data.get("data_source") == "manual_profiles":
        meta["source"] = "manual_profiles"
        meta["profile_type"] = data.get("manual_profile_type", "")


def _team_player_names(team: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for row in team.get("lineup", []):
        p = (row.get("player") or "").strip()
        if p:
            names.append(p)
    for p in team.get("bench") or []:
        if p and str(p).strip():
            names.append(str(p).strip())
    meta = team.get("sheet_meta") or {}
    for p in meta.get("full_roster") or meta.get("bench_players") or []:
        if p and str(p).strip() and str(p).strip() not in names:
            names.append(str(p).strip())
    return names


def prepare_match_player_stats(
    team_a: dict[str, Any],
    team_b: dict[str, Any],
    store: StatsStore,
) -> tuple[dict[str, PlayerStats], dict[str, Any], dict[str, str]]:
    """
    Build player stats for a matchup.
    Default: blended recent cache. Prime / peak-season slots replace stats entirely.
    Includes bench / full squad names when present on sheet teams.
    """
    all_names: list[str] = []
    for team in (team_a, team_b):
        all_names.extend(_team_player_names(team))

    name_map = store.ensure_players(all_names)
    player_stats: dict[str, PlayerStats] = copy.deepcopy(
        {name_map[raw]: store.players[name_map[raw]] for raw in all_names}
    )

    overrides: dict[str, Any] = {"team_a": {}, "team_b": {}}

    for side_key, team in (("team_a", team_a), ("team_b", team_b)):
        prime = (team.get("prime_player") or "").strip()
        if prime:
            meta: dict[str, Any] = {"type": "prime", "requested": prime}
            try:
                _apply_override(
                    store,
                    player_stats,
                    prime,
                    lambda r, s: build_prime_stats_dict(r, s),
                    meta,
                )
                overrides[side_key]["prime"] = meta
            except (KeyError, ValueError) as exc:
                raise ValueError(f"{team.get('name', side_key)} prime player: {exc}") from exc

        peak = team.get("peak_season") or {}
        peak_player = (peak.get("player") or "").strip()
        peak_season_raw = (peak.get("season") or "").strip()
        if peak_player and peak_season_raw:
            suffix = normalize_season_input(peak_season_raw)
            meta = {
                "type": "peak_season",
                "requested": peak_player,
                "season_input": peak_season_raw,
            }
            try:
                _apply_override(
                    store,
                    player_stats,
                    peak_player,
                    lambda r, s, suf=suffix: build_season_stats_dict(r, suf, s),
                    meta,
                )
                overrides[side_key]["peak_season"] = meta
            except (KeyError, ValueError) as exc:
                raise ValueError(
                    f"{team.get('name', side_key)} peak-season ({peak_season_raw}): {exc}"
                ) from exc

    return player_stats, overrides, name_map


def prepare_team_player_stats(
    team: dict[str, Any],
    store: StatsStore,
) -> tuple[dict[str, PlayerStats], dict[str, str]]:
    """Load player stats for a single team dict (sheet roster or lab payload)."""
    all_names = _team_player_names(team)
    name_map = store.ensure_players(all_names)
    player_stats: dict[str, PlayerStats] = copy.deepcopy(
        {name_map[raw]: store.players[name_map[raw]] for raw in all_names}
    )

    prime = (team.get("prime_player") or "").strip()
    if prime:
        meta: dict[str, Any] = {"type": "prime", "requested": prime}
        _apply_override(
            store,
            player_stats,
            prime,
            lambda r, s: build_prime_stats_dict(r, s),
            meta,
        )

    peak = team.get("peak_season") or {}
    peak_player = (peak.get("player") or "").strip()
    peak_season_raw = (peak.get("season") or "").strip()
    if peak_player and peak_season_raw:
        suffix = normalize_season_input(peak_season_raw)
        meta = {
            "type": "peak_season",
            "requested": peak_player,
            "season_input": peak_season_raw,
        }
        _apply_override(
            store,
            player_stats,
            peak_player,
            lambda r, s, suf=suffix: build_season_stats_dict(r, suf, s),
            meta,
        )

    return player_stats, name_map
