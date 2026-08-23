"""Squad evaluation and limited opponent scouting without running simulations."""
from __future__ import annotations

import copy
import time
from typing import Any

from analysis_explainer import analyze_team_squad, build_scout_report, build_tactical_matchup
from bench_impact import bench_impact_for_team
from models import FantasyTeam
from report_builder import (
    extended_metrics,
    fullback_profile,
    team_payload_dict,
)
from slot_roles import effective_slot_name, slot_role
from stats_resolver import prepare_team_player_stats
from team_ratings import compute_team_composites, compute_unit_ratings_by_slot, team_composites_dict
from web.team_lineups import apply_lineup_config, apply_saved_lineup

# Unit/team-composite keys benchmarked against the rest of the league.
# (label, key, higher_better) -- mirrors the pairs analysis_explainer.py
# already walks for tiering, so percentile and absolute-threshold tiering
# stay in sync about which metrics get a percentile at all.
_LEAGUE_UNIT_KEYS: tuple[tuple[str, bool], ...] = (
    ("attack", True),
    ("finishing", True),
    ("chance_creation", True),
    ("midfield", True),
    ("defence", True),
    ("midfield_defence", True),
    ("transition_risk", False),
    ("goalkeeper", True),
)
_LEAGUE_COMPOSITE_KEYS: tuple[str, ...] = (
    "creativity",
    "midfield_control",
    "possession_control",
    "finishing_threat",
    "defensive_solidity",
    "attacking_effectiveness",
    "pressing_intensity",
    "press_resistance",
    "transition_threat",
    "aerial_defence",
)

_LEAGUE_SNAPSHOT_CACHE: dict[str, Any] = {"at": 0.0, "data": {}}
_LEAGUE_SNAPSHOT_TTL_S = 300.0  # benchmark field refreshes at most every 5 min


def _apply_name_map(team: dict[str, Any], name_map: dict[str, str]) -> dict[str, Any]:
    out = copy.deepcopy(team)
    for row in out.get("lineup", []):
        raw = row.get("player", "")
        if raw in name_map:
            row["player"] = name_map[raw]
    for i, bp in enumerate(out.get("bench") or []):
        if bp in name_map:
            out["bench"][i] = name_map[bp]
    meta = out.get("sheet_meta") or {}
    if meta.get("full_roster"):
        meta["full_roster"] = [name_map.get(p, p) for p in meta["full_roster"]]
    if meta.get("bench_players"):
        meta["bench_players"] = [name_map.get(p, p) for p in meta["bench_players"]]
    if meta.get("roster_players"):
        meta["roster_players"] = [name_map.get(p, p) for p in meta["roster_players"]]
    out["sheet_meta"] = meta
    return out


def _validate_lineup(lineup: list[dict[str, Any]]) -> None:
    """A blank slot or the same player in two slots both used to reach
    report_builder.extended_metrics' stats[slot.player] lookup unguarded,
    raising a bare KeyError('') that renders in the API response as the
    unhelpful literal string "''" -- catch both here first with a message
    that actually says what's wrong. The frontend also validates this
    before submitting; this is the same check for any other caller.
    """
    seen: dict[str, str] = {}
    for row in lineup:
        slot = row.get("slot") or "?"
        player = (row.get("player") or "").strip()
        if not player:
            raise ValueError(f"Slot {slot} has no player assigned.")
        if player in seen:
            raise ValueError(f"{player} is assigned to two slots ({seen[player]} and {slot}).")
        seen[player] = slot


def _ratings_only(fantasy: FantasyTeam, player_stats: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Units + team composites, skipping the narrative/bench pipeline.

    Used for the league-wide benchmark field and the what-if comparator,
    where only the numbers are needed -- running the full
    build_squad_evaluation per team (bench impact, formation fit text,
    tier phrasing) for every squad in the tournament would be wasted work.
    """
    units = compute_unit_ratings_by_slot(fantasy, player_stats)
    composites = compute_team_composites(fantasy, player_stats, units=units)
    units_dict = {
        "attack": units.attack,
        "finishing": units.finishing,
        "chance_creation": units.chance_creation,
        "midfield": units.midfield,
        "defence": units.defence,
        "midfield_defence": units.midfield_defence,
        "transition_risk": units.transition_risk,
        "goalkeeper": units.goalkeeper,
        "overall": units.overall,
    }
    return units_dict, team_composites_dict(composites)


def compute_league_snapshot(store: Any, *, force: bool = False) -> dict[str, dict[str, Any]]:
    """Units + team composites for every roster-ready sheet team.

    Best-effort and cached (5 min TTL): a team that fails to resolve
    (incomplete roster, no cached stats for its players) is silently
    skipped rather than failing the whole snapshot -- one broken squad
    elsewhere in the sheet shouldn't take down everyone else's benchmark.
    """
    now = time.time()
    if not force and now - _LEAGUE_SNAPSHOT_CACHE["at"] < _LEAGUE_SNAPSHOT_TTL_S:
        return _LEAGUE_SNAPSHOT_CACHE["data"]

    from google_sheets_teams import list_sheet_teams, load_team_by_name

    snapshot: dict[str, dict[str, Any]] = {}
    try:
        teams = list_sheet_teams()
    except Exception:
        return _LEAGUE_SNAPSHOT_CACHE["data"] or snapshot

    for t in teams:
        name = t.get("name")
        if not name or not t.get("ready"):
            continue
        try:
            team_dict = load_team_by_name(name, store=store)
            team_dict = apply_saved_lineup(team_dict)
            player_stats, name_map = prepare_team_player_stats(team_dict, store, cache_only=True)
            resolved = _apply_name_map(team_dict, name_map)
            fantasy = FantasyTeam.from_dict(resolved)
            units_dict, composites_dict = _ratings_only(fantasy, player_stats)
            snapshot[name] = {"units": units_dict, "team_composites": composites_dict}
        except Exception:
            continue

    _LEAGUE_SNAPSHOT_CACHE["at"] = now
    _LEAGUE_SNAPSHOT_CACHE["data"] = snapshot
    return snapshot


def _percentile_rank(value: float, population: list[float], *, higher_better: bool = True) -> float:
    """0-100: what share of the league this value is at or ahead of (self included)."""
    if not population:
        return 50.0
    if higher_better:
        rank = sum(1 for v in population if v <= value)
    else:
        rank = sum(1 for v in population if v >= value)
    return round(100.0 * rank / len(population), 1)


def compute_percentiles(
    units: dict[str, Any], team_composites: dict[str, Any], snapshot: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """This team's percentile rank vs. the league snapshot, per unit/composite key."""
    if not snapshot:
        return {}
    percentiles: dict[str, float] = {}
    for key, higher_better in _LEAGUE_UNIT_KEYS:
        pop = [s["units"][key] for s in snapshot.values() if key in s.get("units", {})]
        val = units.get(key)
        if val is None or not pop:
            continue
        percentiles[key] = _percentile_rank(float(val), pop, higher_better=higher_better)
    for key in _LEAGUE_COMPOSITE_KEYS:
        pop = [s["team_composites"][key] for s in snapshot.values() if key in s.get("team_composites", {})]
        val = team_composites.get(key)
        if val is None or not pop:
            continue
        percentiles[key] = _percentile_rank(float(val), pop, higher_better=True)
    return {"by_key": percentiles, "league_size": len(snapshot)}


def build_squad_evaluation(
    team_dict: dict[str, Any],
    store: Any,
    *,
    use_saved_lineup: bool = True,
    benchmark: bool = True,
) -> dict[str, Any]:
    """Full squad strengths/weaknesses for one team using saved lineup when available."""
    if use_saved_lineup:
        team_dict = apply_saved_lineup(team_dict)
    _validate_lineup(team_dict.get("lineup") or [])
    player_stats, name_map = prepare_team_player_stats(team_dict, store, cache_only=True)
    resolved = _apply_name_map(team_dict, name_map)
    fantasy = FantasyTeam.from_dict(resolved)
    profile = {
        "extended": extended_metrics(fantasy, player_stats),
        "fullbacks": fullback_profile(fantasy, player_stats),
    }
    starting_xi = [slot.player for slot in fantasy.lineup if slot.player]
    bench = bench_impact_for_team(fantasy.name, starting_xi, [], fantasy.bench, player_stats)

    percentiles: dict[str, Any] = {}
    if benchmark:
        try:
            snapshot = compute_league_snapshot(store)
            percentiles = compute_percentiles(
                profile["extended"]["units"], profile["extended"]["team_composites"], snapshot
            )
        except Exception:
            percentiles = {}

    evaluation = analyze_team_squad(fantasy.name, fantasy.formation, profile, bench, percentiles=percentiles)
    return {
        "team": team_payload_dict(resolved),
        "evaluation": evaluation,
    }


def build_opponent_scout(
    my_team_dict: dict[str, Any],
    opponent_team_dict: dict[str, Any],
    store: Any,
    *,
    opponent_formation: str | None = None,
    opponent_lineup: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Limited scout report comparing opponent to your squad.

    By default scouts the opponent's actual saved lineup. Pass
    opponent_formation/opponent_lineup to scout a hypothetical XI instead
    (e.g. "what if they play their best XI") -- the scouting side sets
    this up themselves, it isn't the opponent's real plan.
    """
    my_bundle = build_squad_evaluation(my_team_dict, store)
    opp_dict = opponent_team_dict
    use_saved = True
    if opponent_lineup:
        opp_dict = copy.deepcopy(opponent_team_dict)
        opp_dict["formation"] = opponent_formation or opp_dict.get("formation")
        opp_dict["lineup"] = opponent_lineup
        use_saved = False
    opp_bundle = build_squad_evaluation(opp_dict, store, use_saved_lineup=use_saved)
    report = build_scout_report(
        my_bundle["evaluation"],
        opp_bundle["evaluation"],
        my_team=my_bundle["team"],
        opponent_team=opp_bundle["team"],
    )
    report["opponent_lineup_is_custom"] = not use_saved
    report["tactical_matchup"] = build_tactical_matchup(report)
    try:
        report["key_battles"] = build_key_battles(my_team_dict, opp_bundle["team"], store)
    except Exception:
        report["key_battles"] = []
    return report


# Which of the opponent's roles is the natural marker for one of mine, in
# priority order -- e.g. a winger is most often faced by the same-side
# fullback, but a centre-back can also be dragged wide. Deliberately
# role-based (not literal slot-name/side matching, which would need a much
# larger per-formation mapping table for comparable payoff).
_BATTLE_COUNTER_ROLES: dict[str, tuple[str, ...]] = {
    "striker": ("centre_back",),
    "winger": ("fullback", "centre_back"),
    "am": ("dm", "cm"),
    "cm": ("cm", "dm"),
    "dm": ("am", "cm"),
    "fullback": ("winger", "am"),
    "centre_back": ("striker", "winger"),
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _battle_attack_score(stats: Any) -> float:
    """0-1: ball-carrying + creation + finishing threat, from stats already
    loaded for the unit ratings -- not a new sub-metric system."""
    dribble = (stats.dribbles90 / 3.0) * ((stats.dribble_pct or 50.0) / 100.0)
    creation = (stats.key_passes90 + stats.xa90 * 2.0) / 3.0
    finishing = (stats.npxg90 or stats.xg90) / 0.6
    return _clamp01(dribble * 0.35 + creation * 0.35 + finishing * 0.30)


def _battle_defence_score(stats: Any) -> float:
    """0-1: containment threat -- tackling/interceptions plus duel win rate."""
    tackling = (stats.tackles90 + stats.interceptions90) / 4.0
    duels = (stats.duels_won_pct or 50.0) / 100.0
    return _clamp01(tackling * 0.6 + duels * 0.4)


# Which formula scores a role's OWN threat in a battle -- a striker/winger/AM
# is scored on attacking threat, a fullback/centre-back on containment, a
# CM/DM (genuinely two-way in this taxonomy) on a blend of both. Applied per
# player based on *their* role, never assumed from which side of "mine vs
# theirs" they're on -- a CB marking a winger must score the CB on defence
# and the winger on attack, not the reverse.
_ATTACK_STANCE_ROLES = frozenset({"striker", "winger", "am"})
_DEFEND_STANCE_ROLES = frozenset({"fullback", "centre_back", "dm"})


def _battle_score(role: str, stats: Any) -> float:
    if role in _ATTACK_STANCE_ROLES:
        return _battle_attack_score(stats)
    if role in _DEFEND_STANCE_ROLES:
        return _battle_defence_score(stats)
    return round((_battle_attack_score(stats) + _battle_defence_score(stats)) / 2.0, 3)


def build_key_battles(
    my_team_dict: dict[str, Any],
    opponent_team_dict: dict[str, Any],
    store: Any,
    *,
    max_battles: int = 6,
) -> list[dict[str, Any]]:
    """Pairs each of your starting XI (outfield) against the opponent most
    likely to actually face them -- role-based, e.g. a winger against the
    same flank's fullback -- and reads an advantage/even/disadvantage off
    real per-90 stats already loaded for the unit ratings. A deliberate
    simplification (attacker's ball-carrying/creation/finishing vs
    defender's tackling/duels), not a claim of tactical precision --
    see GPT's own "specific matchup dimensions" idea, scoped to what's
    already computed rather than a new sub-rating system.
    """
    my_resolved = apply_saved_lineup(copy.deepcopy(my_team_dict))
    my_stats_map, my_name_map = prepare_team_player_stats(my_resolved, store, cache_only=True)
    opp_stats_map, opp_name_map = prepare_team_player_stats(opponent_team_dict, store, cache_only=True)

    def _side_players(team_dict: dict[str, Any], name_map: dict[str, str], stats_map: dict[str, Any]):
        rows = []
        for row in team_dict.get("lineup", []):
            raw = (row.get("player") or "").strip()
            slot = (row.get("slot") or "").strip()
            if not raw or not slot or slot.upper() == "GK":
                continue
            resolved = name_map.get(raw, raw)
            stats = stats_map.get(resolved)
            if not stats:
                continue
            role_filter = (row.get("role_filter") or "").strip()
            eff = effective_slot_name(slot, role_filter or None)
            rows.append({"slot": slot, "player": resolved, "role": slot_role(eff), "stats": stats})
        return rows

    mine = _side_players(my_resolved, my_name_map, my_stats_map)
    theirs = _side_players(opponent_team_dict, opp_name_map, opp_stats_map)

    used_opp: set[str] = set()
    battles: list[dict[str, Any]] = []
    for m in mine:
        candidates = [
            t
            for t in theirs
            if t["role"] in _BATTLE_COUNTER_ROLES.get(m["role"], ()) and t["player"] not in used_opp
        ]
        if not candidates:
            continue
        opp = candidates[0]
        used_opp.add(opp["player"])

        my_score = _battle_score(m["role"], m["stats"])
        opp_score = _battle_score(opp["role"], opp["stats"])
        edge = round(my_score - opp_score, 3)
        if edge >= 0.15:
            verdict = "advantage"
        elif edge <= -0.15:
            verdict = "disadvantage"
        else:
            verdict = "even"

        battles.append(
            {
                "my_player": m["player"],
                "my_slot": m["slot"],
                "my_role": m["role"],
                "opp_player": opp["player"],
                "opp_slot": opp["slot"],
                "opp_role": opp["role"],
                "verdict": verdict,
                "edge": edge,
                "my_score": round(my_score, 3),
                "opp_score": round(opp_score, 3),
            }
        )

    battles.sort(key=lambda b: abs(b["edge"]), reverse=True)
    return battles[:max_battles]


def simulate_lineup_swap(
    team_dict: dict[str, Any],
    store: Any,
    *,
    slot: str,
    new_player: str,
    lineup_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Units/team-composite deltas from swapping one player into one slot.

    Compares a base lineup against a hypothetical one-slot substitution
    (e.g. a bench player replacing a starter) -- both computed through the
    same rating engine, so the deltas are apples-to-apples. ``lineup_config``
    is the just-tested (possibly unsaved) formation/lineup from the editor;
    without it, falls back to the saved lineup on disk. The two can name
    different slots for the same formation family (e.g. a single "CM" vs
    "CM1"/"CM2"), so comparing against whichever one the slot dropdown was
    actually built from is what keeps the two in sync.
    """
    base_dict = (
        apply_lineup_config(copy.deepcopy(team_dict), lineup_config)
        if lineup_config
        else apply_saved_lineup(copy.deepcopy(team_dict))
    )
    swapped_dict = copy.deepcopy(base_dict)
    out_player = None
    found = False
    for row in swapped_dict.get("lineup", []):
        if row.get("slot") == slot:
            out_player = row.get("player")
            row["player"] = new_player
            found = True
            break
    if not found:
        raise ValueError(f"Slot '{slot}' not found in this team's lineup.")
    if out_player == new_player:
        raise ValueError(f"{new_player} is already in slot {slot}.")
    _validate_lineup(swapped_dict["lineup"])

    def _rate(td: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        player_stats, name_map = prepare_team_player_stats(td, store, cache_only=True)
        resolved = _apply_name_map(td, name_map)
        fantasy = FantasyTeam.from_dict(resolved)
        return _ratings_only(fantasy, player_stats)

    base_units, base_composites = _rate(base_dict)
    new_units, new_composites = _rate(swapped_dict)

    def _deltas(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, b in before.items():
            if not isinstance(b, (int, float)):
                continue
            a = float(after.get(key, 0))
            out[key] = {"before": round(float(b), 3), "after": round(a, 3), "delta": round(a - float(b), 3)}
        return out

    return {
        "slot": slot,
        "out_player": out_player,
        "in_player": new_player,
        "units": _deltas(base_units, new_units),
        "team_composites": _deltas(base_composites, new_composites),
    }


def compare_lineups(
    team_dict: dict[str, Any],
    store: Any,
    *,
    lineup_a: dict[str, Any],
    lineup_b: dict[str, Any],
) -> dict[str, Any]:
    """Units/team-composite deltas between two full hypothetical lineups of the
    same squad -- e.g. a possession-heavy XI vs a direct/transition XI.
    Neither has to be the saved lineup; both are computed through the same
    rating engine so "which lineup is better" reads off a real number, not
    a guess.
    """

    def _build(cfg: dict[str, Any]) -> dict[str, Any]:
        td = copy.deepcopy(team_dict)
        td["formation"] = cfg.get("formation") or td.get("formation")
        td["lineup"] = cfg.get("lineup") or []
        _validate_lineup(td["lineup"])
        return td

    def _rate(td: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        player_stats, name_map = prepare_team_player_stats(td, store, cache_only=True)
        resolved = _apply_name_map(td, name_map)
        fantasy = FantasyTeam.from_dict(resolved)
        return _ratings_only(fantasy, player_stats)

    def _deltas(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, b in before.items():
            if not isinstance(b, (int, float)):
                continue
            a = float(after.get(key, 0))
            out[key] = {"before": round(float(b), 3), "after": round(a, 3), "delta": round(a - float(b), 3)}
        return out

    team_a = _build(lineup_a)
    team_b = _build(lineup_b)
    units_a, composites_a = _rate(team_a)
    units_b, composites_b = _rate(team_b)

    overall_delta = round(float(units_b.get("overall", 0)) - float(units_a.get("overall", 0)), 3)
    if overall_delta >= 0.02:
        verdict = "Lineup B rates stronger overall."
    elif overall_delta <= -0.02:
        verdict = "Lineup A rates stronger overall."
    else:
        verdict = "The two lineups rate about even overall — the difference is which units it's stronger/weaker in."

    return {
        "formation_a": team_a["formation"],
        "formation_b": team_b["formation"],
        "verdict": verdict,
        "units": _deltas(units_a, units_b),
        "team_composites": _deltas(composites_a, composites_b),
    }
