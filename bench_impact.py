"""Squad depth: identify bench players with standout per-90 traits.

Informational only -- bench composition has no effect on unit ratings,
expected xG, or match outcomes."""
from __future__ import annotations

from typing import Any

from models import PlayerStats

# Relative threshold: bench player must exceed this percentile among bench peers
BENCH_PEER_PERCENTILE = 0.75

# Absolute elite per-90 floors (any one metric in category triggers "outstanding")
ELITE_ATTACK = {"xg90": 0.45, "npxg90": 0.40, "goals90": 0.45, "shots90": 3.5}
ELITE_CREATIVE = {"xa90": 0.35, "key_passes90": 2.2, "xg_buildup90": 0.45, "big_chances_created90": 0.85}
ELITE_DEFENCE = {"tackles90": 2.8, "interceptions90": 2.0, "clearances90": 5.5, "goals_prevented90": 0.08}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _scale(value: float, cap: float) -> float:
    if cap <= 0:
        return 0.0
    return _clamp(value / cap)


def _percentile_rank(value: float, peers: list[float]) -> float:
    if not peers:
        return 0.0
    below = sum(1 for p in peers if p < value)
    return below / len(peers)


def _attack_score(stats: PlayerStats) -> float:
    return (
        _scale(stats.xg90, 0.85) * 0.30
        + _scale(stats.npxg90 or stats.xg90, 0.75) * 0.25
        + _scale(stats.goals90, 0.55) * 0.25
        + _scale(stats.shots90, 4.0) * 0.20
    )


def _creative_score(stats: PlayerStats) -> float:
    return (
        _scale(stats.xa90, 0.55) * 0.28
        + _scale(stats.key_passes90, 2.5) * 0.27
        + _scale(stats.xg_buildup90, 0.55) * 0.25
        + _scale(stats.big_chances_created90, 1.2) * 0.20
    )


def _defence_score(stats: PlayerStats) -> float:
    if stats.fpl_position == "GK":
        return _scale(stats.goals_prevented90, 0.12) * 0.55 + _scale(max(0.0, 1.25 - stats.goals_conceded90), 1.25) * 0.45
    return (
        _scale(stats.tackles90, 3.5) * 0.30
        + _scale(stats.interceptions90, 2.5) * 0.30
        + _scale(stats.clearances90, 6.0) * 0.25
        + _scale(stats.goals_prevented90, 0.12) * 0.15
    )


def _absolute_outstanding(stats: PlayerStats, category: str) -> bool:
    thresholds = {
        "attacking": ELITE_ATTACK,
        "creative": ELITE_CREATIVE,
        "defensive": ELITE_DEFENCE,
    }.get(category, {})
    values = {
        "xg90": stats.xg90,
        "npxg90": stats.npxg90 or stats.xg90,
        "goals90": stats.goals90,
        "shots90": stats.shots90,
        "xa90": stats.xa90,
        "key_passes90": stats.key_passes90,
        "xg_buildup90": stats.xg_buildup90,
        "big_chances_created90": stats.big_chances_created90,
        "tackles90": stats.tackles90,
        "interceptions90": stats.interceptions90,
        "clearances90": stats.clearances90,
        "goals_prevented90": stats.goals_prevented90,
    }
    for metric, floor in thresholds.items():
        if values.get(metric, 0.0) >= floor:
            return True
    return False


def identify_bench(starting_xi: list[str], full_squad: list[str]) -> list[str]:
    starters = {p.strip() for p in starting_xi if p and p.strip()}
    return [p for p in full_squad if p and p.strip() and p.strip() not in starters]


def compute_bench_impact(
    starting_xi: list[str],
    full_squad: list[str],
    player_stats: dict[str, PlayerStats],
) -> dict[str, Any]:
    """
    Score bench players for standout per-90 traits, purely for display.

    Returns a dict with bench_players, per-player scores, has_standouts, and
    a summary string. Does not compute or apply any rating adjustment.
    """
    bench = identify_bench(starting_xi, full_squad)
    empty: dict[str, Any] = {
        "bench_count": 0,
        "bench_players": [],
        "starting_xi": list(starting_xi),
        "full_squad_size": len([p for p in full_squad if p and p.strip()]),
        "players": [],
        "has_standouts": False,
        "summary": "No bench players — squad has 11 or fewer.",
    }
    if not bench:
        return empty

    scored: list[dict[str, Any]] = []
    attack_scores: list[float] = []
    creative_scores: list[float] = []
    defence_scores: list[float] = []

    for name in bench:
        stats = player_stats.get(name)
        if stats is None:
            continue
        a = _attack_score(stats)
        c = _creative_score(stats)
        d = _defence_score(stats)
        attack_scores.append(a)
        creative_scores.append(c)
        defence_scores.append(d)
        scored.append(
            {
                "player": name,
                "fpl_position": stats.fpl_position,
                "scores": {"attacking": round(a, 3), "creative": round(c, 3), "defensive": round(d, 3)},
                "traits": {
                    "xg90": round(stats.xg90, 3),
                    "npxg90": round(stats.npxg90 or stats.xg90, 3),
                    "goals90": round(stats.goals90, 3),
                    "shots90": round(stats.shots90, 3),
                    "xa90": round(stats.xa90, 3),
                    "key_passes90": round(stats.key_passes90, 3),
                    "xg_buildup90": round(stats.xg_buildup90, 3),
                    "big_chances_created90": round(stats.big_chances_created90, 3),
                    "tackles90": round(stats.tackles90, 3),
                    "interceptions90": round(stats.interceptions90, 3),
                    "clearances90": round(stats.clearances90, 3),
                    "goals_prevented90": round(stats.goals_prevented90, 3),
                },
            }
        )

    if not scored:
        empty["bench_players"] = bench
        empty["bench_count"] = len(bench)
        empty["summary"] = f"{len(bench)} bench player(s) but no stats available."
        return empty

    for row in scored:
        stats = player_stats[row["player"]]
        a, c, d = row["scores"]["attacking"], row["scores"]["creative"], row["scores"]["defensive"]
        out_a = _absolute_outstanding(stats, "attacking") or _percentile_rank(a, attack_scores) >= BENCH_PEER_PERCENTILE
        out_c = _absolute_outstanding(stats, "creative") or _percentile_rank(c, creative_scores) >= BENCH_PEER_PERCENTILE
        out_d = _absolute_outstanding(stats, "defensive") or _percentile_rank(d, defence_scores) >= BENCH_PEER_PERCENTILE
        row["outstanding"] = {"attacking": out_a, "creative": out_c, "defensive": out_d}

    standouts = [r["player"] for r in scored if any(r["outstanding"].values())]
    has_standouts = bool(standouts)
    summary = (
        f"{len(bench)} on bench; {len(standouts)} with standout quality."
        if has_standouts
        else f"{len(bench)} on bench; no standout depth."
    )

    return {
        "bench_count": len(bench),
        "bench_players": bench,
        "starting_xi": list(starting_xi),
        "full_squad_size": len([p for p in full_squad if p and p.strip()]),
        "players": scored,
        "has_standouts": has_standouts,
        "summary": summary,
    }


def bench_impact_for_team(
    team_name: str,
    starting_xi: list[str],
    full_squad: list[str],
    bench: list[str],
    player_stats: dict[str, PlayerStats],
) -> dict[str, Any]:
    """Convenience wrapper: resolve squad from bench + starters and tag with team name."""
    squad = full_squad if full_squad else starting_xi + bench
    result = compute_bench_impact(starting_xi, squad, player_stats)
    result["team"] = team_name
    return result
