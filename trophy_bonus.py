"""League / UCL silverware bonuses for players with meaningful minutes."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from models import FantasyTeam, PlayerStats

MIN_MAJOR_MINUTES = 900  # ~10 full league matches in one season

# Domestic champions (top 5 leagues), 2024-25 and 2025-26
LEAGUE_CHAMPIONS: dict[str, list[str]] = {
    "2024-2025": [
        "liverpool",
        "barcelona",
        "bayern",
        "napoli",
        "paris saint germain",
    ],
    "2025-2026": [
        "arsenal",
        "barcelona",
        "bayern",
        "inter",
        "paris saint germain",
    ],
}

UCL_WINNERS: dict[str, str] = {
    "2024-2025": "paris saint germain",
    "2025-2026": "paris saint germain",
}

UCL_FINALISTS: dict[str, str] = {
    "2024-2025": "inter",
    "2025-2026": "arsenal",
}

# Transfers / blended-cache mismatches (display name -> season club)
PLAYER_CLUB_OVERRIDES: dict[str, dict[str, str]] = {
    "Trent Alexander-Arnold": {
        "2024-2025": "Liverpool",
        "2025-2026": "Liverpool",
    },
}


def _nfkd(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in text if not unicodedata.combining(c))


def normalize_club(name: str) -> str:
    text = _nfkd(name).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for old, new in (
        ("fc barcelona", "barcelona"),
        ("fc bayern munchen", "bayern"),
        ("bayern munchen", "bayern"),
        ("fc bayern munich", "bayern"),
        ("paris saint germain", "paris saint germain"),
        ("manchester city", "man city"),
        ("internazionale", "inter"),
        ("inter milan", "inter"),
        ("ssc napoli", "napoli"),
        ("real madrid cf", "real madrid"),
        ("liverpool fc", "liverpool"),
        ("arsenal fc", "arsenal"),
        ("ac milan", "milan"),
    ):
        if old in text:
            text = text.replace(old, new)
    return text


@dataclass
class PlayerTrophyProfile:
    player: str
    bonus: float
    details: list[str] = field(default_factory=list)


@dataclass
class TeamTrophyProfile:
    multiplier: float
    lineup_bonus: float
    players: list[PlayerTrophyProfile]


def _clubs_by_season(player: str, stats: PlayerStats) -> dict[str, str]:
    override = PLAYER_CLUB_OVERRIDES.get(player, {})
    stored = stats.teams_by_season or {}
    seasons = stats.seasons_used or sorted(stored.keys())
    out: dict[str, str] = {}
    for season in seasons:
        out[season] = override.get(season) or stored.get(season) or stats.team
    return out


def _season_minutes(stats: PlayerStats) -> float:
    n = len(stats.seasons_used) or 1
    return stats.minutes / n


def player_trophy_bonus(player: str, stats: PlayerStats) -> PlayerTrophyProfile:
    clubs = _clubs_by_season(player, stats)
    minutes_per_season = _season_minutes(stats)
    part_factor = min(1.0, minutes_per_season / MIN_MAJOR_MINUTES)
    if part_factor < 0.35:
        return PlayerTrophyProfile(player=player, bonus=0.0, details=["Limited minutes — no silverware boost"])

    bonus = 0.0
    details: list[str] = []

    for season, club in clubs.items():
        club_n = normalize_club(club)
        season_bonus = 0.0

        if club_n in LEAGUE_CHAMPIONS.get(season, []):
            season_bonus += 0.045
            details.append(f"{season}: league winner ({club})")
        if club_n == normalize_club(UCL_WINNERS.get(season, "")):
            season_bonus += 0.055
            details.append(f"{season}: UCL winner ({club})")
        elif club_n == normalize_club(UCL_FINALISTS.get(season, "")):
            season_bonus += 0.025
            details.append(f"{season}: UCL finalist ({club})")

        bonus += season_bonus * part_factor

    bonus = min(0.18, bonus)
    if not details:
        details = ["No title/finalist club in window"]
    return PlayerTrophyProfile(player=player, bonus=round(bonus, 4), details=details)


def team_trophy_profile(
    team: FantasyTeam,
    player_stats: dict[str, PlayerStats],
) -> TeamTrophyProfile:
    profiles = [
        player_trophy_bonus(slot.player, player_stats[slot.player])
        for slot in team.lineup
    ]
    lineup_bonus = sum(p.bonus for p in profiles) / len(profiles) if profiles else 0.0
    multiplier = 1.0 + lineup_bonus
    return TeamTrophyProfile(
        multiplier=round(multiplier, 4),
        lineup_bonus=round(lineup_bonus, 4),
        players=profiles,
    )


def apply_trophy_multiplier(units: Any, multiplier: float) -> Any:
    """Scale unit ratings by team silverware multiplier (cap at 1.0 per unit)."""
    from team_ratings import UnitRatings

    return UnitRatings(
        attack=round(min(1.0, units.attack * multiplier), 3),
        finishing=round(min(1.0, units.finishing * multiplier), 3),
        chance_creation=round(min(1.0, units.chance_creation * multiplier), 3),
        midfield=round(min(1.0, units.midfield * multiplier), 3),
        defence=round(min(1.0, units.defence * multiplier), 3),
        midfield_defence=round(min(1.0, units.midfield_defence * multiplier), 3),
        transition_risk=units.transition_risk,
        goalkeeper=round(min(1.0, units.goalkeeper * multiplier), 3),
        overall=round(min(1.0, units.overall * multiplier), 3),
        gk_confidence=units.gk_confidence,
        gk_is_backup=units.gk_is_backup,
    )
