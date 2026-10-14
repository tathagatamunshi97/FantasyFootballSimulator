"""Scenario-modelling scorelines for Team Lab friendlies (explicit admin request).

A matching entry makes the live tactic board steer a friendly to an exact 90'
score: the match still plays organically (chances, shots and xG come from the
teams), but which shots go in is adjusted so the final lands on the target.
See scenarioScore in web/static/tactic_board.js.

Only web/experiments.py (Team Lab live matches, no tournament) reads this.
Tournament fixtures -- league, cup and their friendlies -- never get a
scenario, and the engine ignores one on any league/knockout board anyway.

Each entry names the home team, the away team, or both:
  * both    -> only that exact fixture
  * home    -> any friendly where that team is at home
  * away    -> any friendly where that team is away
An exact home+away entry wins over a single-team one. An entry with neither
team set is a placeholder and never matches. Team names are matched
accent/case-insensitively; goals are (home_goals, away_goals) for the match
as played, whoever is home.
"""
from __future__ import annotations

from typing import Any

from player_names import normalize_key

FRIENDLY_SCENARIOS: list[dict[str, Any]] = [
    # Placeholder -- fill in "home", "away" or both to activate, e.g.
    #   {"home": "Sayaninjal FC", "away": "Nesha Korechi FC", "home_goals": 4, "away_goals": 2},
    {"home": "Sayaninjal FC", "away": "Nesha Korechi FC", "home_goals": 4, "away_goals": 2},
    {"home": "MasterSimulator FC", "away": "Slip & Hop FC", "home_goals": 5, "away_goals": 2},
    {"home": "MasterSimulator FC", "away": "Council of Kangs", "home_goals": 3, "away_goals": 1},
    {"home": "Diddy's Didier FC", "away": "MasterSimulator FC", "home_goals": 2, "away_goals": 7},
]


def _key(name: Any) -> str | None:
    text = str(name or "").strip()
    return normalize_key(text) if text else None


def scenario_score_for(home: str, away: str) -> dict[str, int] | None:
    """{"home": n, "away": m} for this friendly, or None if nothing matches."""
    h, a = _key(home), _key(away)
    best: tuple[int, dict[str, int]] | None = None
    for entry in FRIENDLY_SCENARIOS:
        eh, ea = _key(entry.get("home")), _key(entry.get("away"))
        if eh is None and ea is None:
            continue
        if (eh is not None and eh != h) or (ea is not None and ea != a):
            continue
        try:
            score = {"home": int(entry["home_goals"]), "away": int(entry["away_goals"])}
        except (KeyError, TypeError, ValueError):
            continue
        if not all(0 <= v <= 15 for v in score.values()):
            continue
        specificity = (eh is not None) + (ea is not None)
        if best is None or specificity > best[0]:
            best = (specificity, score)
    return best[1] if best else None
