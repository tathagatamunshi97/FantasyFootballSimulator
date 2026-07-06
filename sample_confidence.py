"""Minutes- and role-based confidence for regressing small-sample stats."""
from __future__ import annotations

import math

from models import PlayerStats

# ~34 league games × 90 — full starter workload across a blended two-season window
FULL_STARTER_MINUTES = 3060
MIN_TRUSTED_MINUTES = 2200

LEAGUE_GK_BASELINE = {
    "goals_prevented90": 0.045,
    "saves90": 2.4,
    "goals_conceded90": 1.05,
    "rating": 6.85,
    "pass_pct": 74.0,
}

LEAGUE_OUTFIELD_BASELINE = {
    "xg90": 0.08,
    "xa90": 0.08,
    "xg_buildup90": 0.25,
    "rating": 6.75,
}


def minute_confidence(minutes: float, *, full: float = FULL_STARTER_MINUTES) -> float:
    """0-1 trust from minutes played (concave — low samples regress harder)."""
    if minutes <= 0:
        return 0.0
    return min(1.0, (minutes / full) ** 0.62)


def starter_confidence(stats: PlayerStats) -> float:
    """Blend minutes with start rate when game counts are available."""
    m_conf = minute_confidence(stats.minutes)
    if stats.games <= 0:
        return m_conf
    start_rate = min(1.0, stats.starts / stats.games)
    games_conf = min(1.0, stats.games / 32.0)
    return m_conf * (0.65 + 0.35 * start_rate) * (0.7 + 0.3 * games_conf)


def shrink_value(value: float, baseline: float, confidence: float) -> float:
    return confidence * value + (1.0 - confidence) * baseline


def gk_sample_confidence(stats: PlayerStats) -> float:
    return starter_confidence(stats)


def is_backup_goalkeeper(stats: PlayerStats) -> bool:
    return stats.minutes < MIN_TRUSTED_MINUTES


def shrink_gk_stats(stats: PlayerStats) -> dict[str, float]:
    conf = gk_sample_confidence(stats)
    return {
        "goals_prevented90": shrink_value(
            stats.goals_prevented90, LEAGUE_GK_BASELINE["goals_prevented90"], conf
        ),
        "saves90": shrink_value(stats.saves90, LEAGUE_GK_BASELINE["saves90"], conf),
        "goals_conceded90": shrink_value(
            stats.goals_conceded90, LEAGUE_GK_BASELINE["goals_conceded90"], conf
        ),
        "rating": shrink_value(stats.rating, LEAGUE_GK_BASELINE["rating"], conf),
        "pass_pct": shrink_value(stats.pass_pct, LEAGUE_GK_BASELINE["pass_pct"], conf),
        "confidence": conf,
    }


def reliability_multiplier(minutes: float) -> float:
    """
    Proven #1 keepers with large samples get a modest boost.
    Backups with <2,200 blended minutes do not.
    """
    if minutes < MIN_TRUSTED_MINUTES:
        return 0.92 + 0.08 * minute_confidence(minutes, full=MIN_TRUSTED_MINUTES)
    extra = min(1.0, (minutes - MIN_TRUSTED_MINUTES) / (FULL_STARTER_MINUTES - MIN_TRUSTED_MINUTES))
    return 1.0 + 0.14 * extra


def outfield_confidence(stats: PlayerStats) -> float:
    return starter_confidence(stats)


def shrink_outfield_metric(value: float, key: str, stats: PlayerStats) -> float:
    baseline = LEAGUE_OUTFIELD_BASELINE.get(key, 0.0)
    return shrink_value(value, baseline, outfield_confidence(stats))
