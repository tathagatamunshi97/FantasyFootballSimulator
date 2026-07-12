"""Minutes- and role-based confidence for regressing small-sample stats."""
from __future__ import annotations

from typing import Any

from models import PlayerStats

# ~34 league games × 90 — full starter workload across a blended two-season window
FULL_STARTER_MINUTES = 3060
MIN_TRUSTED_MINUTES = 2200

# Bayesian credibility prior strength for normal (non-prime / non-peak) per-90 rates.
# c = m / (m + m0); m0 ≈ one season of substantial play (~11 full matches).
CREDIBILITY_M0 = 1000.0

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

# Prime / peak-season pick profiles stay undamped (raw peak rates).
_UNDAMPED_STAT_PROFILES = frozenset(
    {
        "prime_season",
        "manual_prime",
        "manual_season_pick",
        "single_season",
        "historical_best",
    }
)
_UNDAMPED_MANUAL_TYPES = frozenset({"prime", "season_pick"})

# Rate stats shrunk toward role priors. Not minutes/games/starts or binary flags.
RATE_STAT_FIELDS: tuple[str, ...] = (
    "goals90",
    "assists90",
    "xg90",
    "xa90",
    "shots90",
    "shots_on_target90",
    "key_passes90",
    "tackles90",
    "interceptions90",
    "clearances90",
    "blocks90",
    "ball_recoveries90",
    "aerials_won90",
    "aerials_lost90",
    "aerials_won_pct",
    "duels_won_pct",
    "dribbles90",
    "dribble_pct",
    "passes_completed90",
    "pass_pct",
    "long_balls90",
    "long_ball_pct",
    "big_chances_created90",
    "big_chances_missed90",
    "possession_lost90",
    "penalty_goals90",
    "npxg90",
    "xg_chain90",
    "xg_buildup90",
    "understat_key_passes90",
    "understat_xa90",
    "understat_shots90",
    "understat_xg90",
    "saves90",
    "goals_prevented90",
    "goals_conceded90",
    "clean_sheet_pct",
    "yellow_cards90",
    "red_cards90",
    "rating",
)

# Role medians from cache players with ≥1500' (sparse roles hand-tuned).
_ROLE_PER90_PRIORS: dict[str, dict[str, float]] = {
    "GK": {
        "goals90": 0.0,
        "assists90": 0.0,
        "xg90": 0.0,
        "xa90": 0.002,
        "shots90": 0.0,
        "shots_on_target90": 0.0,
        "key_passes90": 0.03,
        "tackles90": 0.02,
        "interceptions90": 0.0,
        "clearances90": 1.0,
        "blocks90": 0.0,
        "ball_recoveries90": 0.0,
        "aerials_won90": 0.09,
        "aerials_lost90": 0.07,
        "aerials_won_pct": 55.0,
        "duels_won_pct": 50.0,
        "dribbles90": 0.0,
        "dribble_pct": 0.0,
        "passes_completed90": 22.0,
        "pass_pct": 69.0,
        "long_balls90": 8.5,
        "long_ball_pct": 40.0,
        "big_chances_created90": 0.02,
        "big_chances_missed90": 0.0,
        "possession_lost90": 12.0,
        "penalty_goals90": 0.0,
        "npxg90": 0.0,
        "xg_chain90": 0.12,
        "xg_buildup90": 0.12,
        "understat_key_passes90": 0.03,
        "understat_xa90": 0.002,
        "understat_shots90": 0.0,
        "understat_xg90": 0.0,
        "saves90": 2.9,
        "goals_prevented90": 0.045,
        "goals_conceded90": 1.05,
        "clean_sheet_pct": 30.0,
        "yellow_cards90": 0.05,
        "red_cards90": 0.0,
        "rating": 6.95,
    },
    "CB": {
        "goals90": 0.03,
        "assists90": 0.03,
        "xg90": 0.04,
        "xa90": 0.04,
        "shots90": 0.50,
        "shots_on_target90": 0.15,
        "key_passes90": 0.35,
        "tackles90": 1.60,
        "interceptions90": 1.05,
        "clearances90": 4.0,
        "blocks90": 0.40,
        "ball_recoveries90": 4.0,
        "aerials_won90": 2.40,
        "aerials_lost90": 1.40,
        "aerials_won_pct": 58.0,
        "duels_won_pct": 55.0,
        "dribbles90": 0.25,
        "dribble_pct": 55.0,
        "passes_completed90": 41.0,
        "pass_pct": 86.0,
        "long_balls90": 4.0,
        "long_ball_pct": 50.0,
        "big_chances_created90": 0.05,
        "big_chances_missed90": 0.05,
        "possession_lost90": 8.0,
        "penalty_goals90": 0.0,
        "npxg90": 0.04,
        "xg_chain90": 0.28,
        "xg_buildup90": 0.23,
        "understat_key_passes90": 0.35,
        "understat_xa90": 0.04,
        "understat_shots90": 0.50,
        "understat_xg90": 0.04,
        "saves90": 0.0,
        "goals_prevented90": 0.0,
        "goals_conceded90": 0.0,
        "clean_sheet_pct": 0.0,
        "yellow_cards90": 0.18,
        "red_cards90": 0.01,
        "rating": 6.85,
    },
    "FB": {
        "goals90": 0.06,
        "assists90": 0.10,
        "xg90": 0.06,
        "xa90": 0.10,
        "shots90": 0.70,
        "shots_on_target90": 0.20,
        "key_passes90": 0.90,
        "tackles90": 1.90,
        "interceptions90": 0.95,
        "clearances90": 2.10,
        "blocks90": 0.25,
        "ball_recoveries90": 4.5,
        "aerials_won90": 1.00,
        "aerials_lost90": 0.90,
        "aerials_won_pct": 52.0,
        "duels_won_pct": 52.0,
        "dribbles90": 0.80,
        "dribble_pct": 52.0,
        "passes_completed90": 38.0,
        "pass_pct": 82.0,
        "long_balls90": 2.5,
        "long_ball_pct": 45.0,
        "big_chances_created90": 0.12,
        "big_chances_missed90": 0.05,
        "possession_lost90": 10.0,
        "penalty_goals90": 0.0,
        "npxg90": 0.06,
        "xg_chain90": 0.45,
        "xg_buildup90": 0.35,
        "understat_key_passes90": 0.90,
        "understat_xa90": 0.10,
        "understat_shots90": 0.70,
        "understat_xg90": 0.06,
        "saves90": 0.0,
        "goals_prevented90": 0.0,
        "goals_conceded90": 0.0,
        "clean_sheet_pct": 0.0,
        "yellow_cards90": 0.18,
        "red_cards90": 0.01,
        "rating": 6.85,
    },
    "DM": {
        "goals90": 0.06,
        "assists90": 0.06,
        "xg90": 0.06,
        "xa90": 0.08,
        "shots90": 0.90,
        "shots_on_target90": 0.25,
        "key_passes90": 0.90,
        "tackles90": 2.20,
        "interceptions90": 1.20,
        "clearances90": 1.80,
        "blocks90": 0.30,
        "ball_recoveries90": 6.0,
        "aerials_won90": 1.20,
        "aerials_lost90": 1.00,
        "aerials_won_pct": 52.0,
        "duels_won_pct": 54.0,
        "dribbles90": 0.50,
        "dribble_pct": 55.0,
        "passes_completed90": 45.0,
        "pass_pct": 86.0,
        "long_balls90": 3.5,
        "long_ball_pct": 55.0,
        "big_chances_created90": 0.10,
        "big_chances_missed90": 0.05,
        "possession_lost90": 8.5,
        "penalty_goals90": 0.0,
        "npxg90": 0.06,
        "xg_chain90": 0.40,
        "xg_buildup90": 0.35,
        "understat_key_passes90": 0.90,
        "understat_xa90": 0.08,
        "understat_shots90": 0.90,
        "understat_xg90": 0.06,
        "saves90": 0.0,
        "goals_prevented90": 0.0,
        "goals_conceded90": 0.0,
        "clean_sheet_pct": 0.0,
        "yellow_cards90": 0.22,
        "red_cards90": 0.01,
        "rating": 6.90,
    },
    "CM": {
        "goals90": 0.10,
        "assists90": 0.10,
        "xg90": 0.10,
        "xa90": 0.11,
        "shots90": 1.20,
        "shots_on_target90": 0.35,
        "key_passes90": 1.10,
        "tackles90": 1.75,
        "interceptions90": 0.80,
        "clearances90": 1.20,
        "blocks90": 0.20,
        "ball_recoveries90": 5.0,
        "aerials_won90": 0.60,
        "aerials_lost90": 0.70,
        "aerials_won_pct": 48.0,
        "duels_won_pct": 50.0,
        "dribbles90": 0.70,
        "dribble_pct": 55.0,
        "passes_completed90": 33.0,
        "pass_pct": 83.0,
        "long_balls90": 2.5,
        "long_ball_pct": 55.0,
        "big_chances_created90": 0.15,
        "big_chances_missed90": 0.08,
        "possession_lost90": 10.0,
        "penalty_goals90": 0.0,
        "npxg90": 0.09,
        "xg_chain90": 0.42,
        "xg_buildup90": 0.26,
        "understat_key_passes90": 1.10,
        "understat_xa90": 0.11,
        "understat_shots90": 1.20,
        "understat_xg90": 0.10,
        "saves90": 0.0,
        "goals_prevented90": 0.0,
        "goals_conceded90": 0.0,
        "clean_sheet_pct": 0.0,
        "yellow_cards90": 0.18,
        "red_cards90": 0.01,
        "rating": 6.90,
    },
    "AM": {
        "goals90": 0.18,
        "assists90": 0.18,
        "xg90": 0.18,
        "xa90": 0.18,
        "shots90": 1.80,
        "shots_on_target90": 0.65,
        "key_passes90": 1.60,
        "tackles90": 1.10,
        "interceptions90": 0.45,
        "clearances90": 0.50,
        "blocks90": 0.10,
        "ball_recoveries90": 4.0,
        "aerials_won90": 0.40,
        "aerials_lost90": 0.55,
        "aerials_won_pct": 42.0,
        "duels_won_pct": 48.0,
        "dribbles90": 1.20,
        "dribble_pct": 52.0,
        "passes_completed90": 28.0,
        "pass_pct": 80.0,
        "long_balls90": 1.5,
        "long_ball_pct": 50.0,
        "big_chances_created90": 0.28,
        "big_chances_missed90": 0.15,
        "possession_lost90": 11.0,
        "penalty_goals90": 0.02,
        "npxg90": 0.16,
        "xg_chain90": 0.55,
        "xg_buildup90": 0.28,
        "understat_key_passes90": 1.60,
        "understat_xa90": 0.18,
        "understat_shots90": 1.80,
        "understat_xg90": 0.18,
        "saves90": 0.0,
        "goals_prevented90": 0.0,
        "goals_conceded90": 0.0,
        "clean_sheet_pct": 0.0,
        "yellow_cards90": 0.14,
        "red_cards90": 0.005,
        "rating": 6.95,
    },
    "W": {
        "goals90": 0.25,
        "assists90": 0.18,
        "xg90": 0.22,
        "xa90": 0.18,
        "shots90": 2.20,
        "shots_on_target90": 0.85,
        "key_passes90": 1.50,
        "tackles90": 1.00,
        "interceptions90": 0.40,
        "clearances90": 0.50,
        "blocks90": 0.08,
        "ball_recoveries90": 3.5,
        "aerials_won90": 0.50,
        "aerials_lost90": 0.80,
        "aerials_won_pct": 40.0,
        "duels_won_pct": 46.0,
        "dribbles90": 1.40,
        "dribble_pct": 48.0,
        "passes_completed90": 22.0,
        "pass_pct": 76.0,
        "long_balls90": 1.0,
        "long_ball_pct": 45.0,
        "big_chances_created90": 0.25,
        "big_chances_missed90": 0.18,
        "possession_lost90": 12.0,
        "penalty_goals90": 0.02,
        "npxg90": 0.20,
        "xg_chain90": 0.55,
        "xg_buildup90": 0.25,
        "understat_key_passes90": 1.50,
        "understat_xa90": 0.18,
        "understat_shots90": 2.20,
        "understat_xg90": 0.22,
        "saves90": 0.0,
        "goals_prevented90": 0.0,
        "goals_conceded90": 0.0,
        "clean_sheet_pct": 0.0,
        "yellow_cards90": 0.12,
        "red_cards90": 0.005,
        "rating": 6.95,
    },
    "ST": {
        "goals90": 0.34,
        "assists90": 0.12,
        "xg90": 0.34,
        "xa90": 0.09,
        "shots90": 2.40,
        "shots_on_target90": 0.98,
        "key_passes90": 1.10,
        "tackles90": 0.80,
        "interceptions90": 0.25,
        "clearances90": 0.75,
        "blocks90": 0.08,
        "ball_recoveries90": 2.5,
        "aerials_won90": 0.70,
        "aerials_lost90": 1.10,
        "aerials_won_pct": 40.0,
        "duels_won_pct": 42.0,
        "dribbles90": 0.80,
        "dribble_pct": 48.0,
        "passes_completed90": 16.0,
        "pass_pct": 74.0,
        "long_balls90": 0.8,
        "long_ball_pct": 50.0,
        "big_chances_created90": 0.18,
        "big_chances_missed90": 0.35,
        "possession_lost90": 11.0,
        "penalty_goals90": 0.04,
        "npxg90": 0.30,
        "xg_chain90": 0.55,
        "xg_buildup90": 0.16,
        "understat_key_passes90": 1.10,
        "understat_xa90": 0.09,
        "understat_shots90": 2.40,
        "understat_xg90": 0.34,
        "saves90": 0.0,
        "goals_prevented90": 0.0,
        "goals_conceded90": 0.0,
        "clean_sheet_pct": 0.0,
        "yellow_cards90": 0.14,
        "red_cards90": 0.005,
        "rating": 6.90,
    },
}


def minute_confidence(minutes: float, *, full: float = FULL_STARTER_MINUTES) -> float:
    """0-1 trust from minutes played (concave — low samples regress harder)."""
    if minutes <= 0:
        return 0.0
    return min(1.0, (minutes / full) ** 0.62)


def credibility_weight(minutes: float, *, m0: float = CREDIBILITY_M0) -> float:
    """
    Bayesian credibility for per-90 rates: c = m / (m + m0).

    Missing / non-positive minutes → c = 0 (full prior). Conservative choice:
    unknown sample size is treated as zero credibility rather than skipping.
    """
    m = float(minutes or 0.0)
    if m <= 0 or m0 <= 0:
        return 0.0
    return m / (m + m0)


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


def role_bucket(primary_position: str, fpl_position: str = "") -> str:
    """Map primary / FPL position to a prior bucket."""
    p = (primary_position or "").strip().upper()
    f = (fpl_position or "").strip().upper()
    if p == "GK" or f == "GK":
        return "GK"
    if p in {"LB", "RB", "WB", "LWB", "RWB"}:
        return "FB"
    if p == "CB":
        return "CB"
    if p == "DM":
        return "DM"
    if p in {"AM", "CAM"}:
        return "AM"
    if p in {"RW", "LW", "RM", "LM"}:
        return "W"
    if p in {"ST", "CF", "FW"} or f == "FWD":
        return "ST"
    if f == "DEF":
        return "CB"
    return "CM"


def role_bucket_for_stats(data: dict[str, Any]) -> str:
    """
    Role bucket for credibility priors.

    Sofascore often tags AMs/wingers as CM/MF. Shrinking their xG/shots toward
    CM priors (xg≈0.10) makes sheet attackers look like non-finishers. Promote
    the prior bucket from the attack profile when the tag is a midfield bucket.
    """
    primary = str(data.get("primary_position") or "MF")
    fpl = str(data.get("fpl_position") or "")
    base = role_bucket(primary, fpl)
    if base != "CM":
        return base

    xg = float(data.get("xg90") or data.get("npxg90") or data.get("understat_xg90") or 0)
    shots = float(data.get("shots90") or data.get("understat_shots90") or 0)
    sot = float(data.get("shots_on_target90") or 0)
    xa = float(data.get("xa90") or data.get("understat_xa90") or 0)
    kp = float(data.get("key_passes90") or data.get("understat_key_passes90") or 0)
    dribbles = float(data.get("dribbles90") or 0)
    goals = float(data.get("goals90") or 0)

    # Out-and-out finisher profile stuck in midfield tag
    if xg >= 0.28 or goals >= 0.28 or (shots >= 2.5 and (xg >= 0.18 or sot >= 1.0)):
        return "ST"
    # Wide attacker / carrier
    if dribbles >= 1.35 and shots >= 1.4 and (xg >= 0.12 or xa >= 0.12 or goals >= 0.12):
        return "W"
    # Creator / CAM
    if (kp >= 1.35 or xa >= 0.16) and (xg >= 0.10 or shots >= 1.3 or dribbles >= 1.0):
        return "AM"
    return "CM"


def role_priors(primary_position: str, fpl_position: str = "") -> dict[str, float]:
    return _ROLE_PER90_PRIORS[role_bucket(primary_position, fpl_position)]


def is_undamped_profile(data: dict[str, Any]) -> bool:
    """True for prime / peak-season pick payloads (leave raw per-90s)."""
    if data.get("skip_credibility_dampening") or data.get("credibility_damped"):
        return True
    manual = str(data.get("manual_profile_type") or "").strip().lower()
    if manual in _UNDAMPED_MANUAL_TYPES:
        return True
    profile = str(data.get("stat_profile") or "").strip().lower()
    return profile in _UNDAMPED_STAT_PROFILES


def apply_credibility_dampening(data: dict[str, Any]) -> dict[str, Any]:
    """
    Shrink per-90 rate stats toward role priors by minutes credibility.

    adjusted = c * per90 + (1 - c) * prior,  c = m / (m + m0), m0 = CREDIBILITY_M0.

    Skips primes and peak-season picks. Missing minutes → c = 0 (full prior).
    Idempotent via credibility_damped flag.
    """
    if is_undamped_profile(data):
        return data

    minutes = float(data.get("minutes") or 0.0)
    c = credibility_weight(minutes)
    primary = str(data.get("primary_position") or "MF")
    fpl = str(data.get("fpl_position") or "")
    bucket = role_bucket_for_stats(data)
    priors = _ROLE_PER90_PRIORS[bucket]

    for field in RATE_STAT_FIELDS:
        if field not in data or data[field] in (None, ""):
            continue
        prior = float(priors.get(field, LEAGUE_OUTFIELD_BASELINE.get(field, 0.0)))
        raw = float(data[field])
        data[field] = shrink_value(raw, prior, c)

    data["credibility_damped"] = True
    data["credibility_weight"] = round(c, 4)
    data["credibility_m0"] = CREDIBILITY_M0
    data["credibility_role"] = bucket
    data["credibility_role_declared"] = role_bucket(primary, fpl)
    return data
