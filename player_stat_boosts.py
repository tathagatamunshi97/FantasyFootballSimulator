"""League-specific per-player stat multipliers (explicit admin request).

Applied by stats_resolver to the per-match *copy* of each player's stats
(never to the shared stats cache), after any prime/peak-season override, so a
boosted player is boosted regardless of where their base stats came from.

Only volume/quality output rates are scaled up. Percentages (pass_pct,
dribble_pct, duels_won_pct, aerials_won_pct, clean_sheet_pct) and ratings are
left alone -- "double" a 60% pass accuracy has no meaning and would just
clamp at a perfect 100% -- and mistake rates are *divided* by the factor so a
boosted player is better on both sides of the ledger. Discipline (cards) and
identity/position fields are untouched.
"""
from __future__ import annotations

from typing import Any

from player_names import normalize_key

# Multiplier per player. Keys are matched accent/case-insensitively.
PLAYER_STAT_BOOSTS: dict[str, float] = {
    "Eden Hazard": 2.0,
    "Luis Suárez": 2.0,
    "Lamine Yamal": 2.0,
    "Reece James": 2.0,
    "Yahia Fofana": 2.0,
    "Marc Guéhi": 2.0,
    "Mamadou Sangare": 2.0,
    # Nerfs: a factor below 1 scales output rates down and mistake rates up;
    # exactly 0 floors every output stat and percentage (see _FLOOR).
    "Matz Sels": 0.0,
}

_BOOST_BY_KEY = {normalize_key(name): factor for name, factor in PLAYER_STAT_BOOSTS.items()}

# Scaled UP by the factor.
_SCALE_UP_FIELDS = (
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
    "dribbles90",
    "passes_completed90",
    "long_balls90",
    "big_chances_created90",
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
)

# Scaled DOWN (divided) -- these are things a better player does *less* of.
_SCALE_DOWN_FIELDS = (
    "big_chances_missed90",
    "possession_lost90",
    "goals_conceded90",
)


# Percentages/rating: only touched when a player's factor is exactly 0.
_FLOOR_ONLY_FIELDS = (
    "aerials_won_pct",
    "duels_won_pct",
    "dribble_pct",
    "pass_pct",
    "long_ball_pct",
    "clean_sheet_pct",
    "rating",
)

# A factor of exactly 0 floors stats to this instead of a literal 0: the
# engine's mergeStats treats 0 in many fields (shots, xG, dribble %, ...) as
# "missing data" and substitutes the *role average*, which would turn a
# deliberately-worthless player into an average one. Anything > 0 is read
# as real data. Mistake-rate fields (_SCALE_DOWN_FIELDS) are left as-is at
# factor 0 -- lowering them would make the player better, not worse.
_FLOOR = 0.001


def boost_factor(player_name: str) -> float:
    return _BOOST_BY_KEY.get(normalize_key(str(player_name or "").strip()), 1.0)


def apply_stat_boosts(player_stats: dict[str, Any]) -> None:
    """Mutate ``player_stats`` (name -> PlayerStats, already per-match copies)."""
    for ps in player_stats.values():
        factor = boost_factor(getattr(ps, "player", ""))
        if factor == 1.0:
            continue
        if factor == 0.0:
            for field_name in _SCALE_UP_FIELDS + _FLOOR_ONLY_FIELDS:
                setattr(ps, field_name, _FLOOR)
            continue
        for field_name in _SCALE_UP_FIELDS:
            setattr(ps, field_name, float(getattr(ps, field_name, 0.0) or 0.0) * factor)
        for field_name in _SCALE_DOWN_FIELDS:
            setattr(ps, field_name, float(getattr(ps, field_name, 0.0) or 0.0) / factor)
