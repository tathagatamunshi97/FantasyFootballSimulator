"""Data models for fantasy football Monte Carlo simulation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FplPosition = Literal["GK", "DEF", "MID", "FWD"]

SOFASCORE_POSITION_TO_FPL: dict[str, FplPosition] = {
    "G": "GK",
    "D": "DEF",
    "M": "MID",
    "F": "FWD",
}

SOFASCORE_POSITION_TO_PRIMARY: dict[str, str] = {
    "G": "GK",
    "D": "CB",
    "M": "CM",
    "F": "ST",
}


@dataclass
class PlayerStats:
    """Blended per-90 stats from Sofascore (last two league seasons)."""

    player: str
    team: str = ""
    primary_position: str = "MF"
    fpl_position: FplPosition = "MID"
    positions: list[str] = field(default_factory=list)
    minutes: float = 0.0
    games: int = 0
    starts: int = 0
    goals90: float = 0.0
    assists90: float = 0.0
    xg90: float = 0.0
    xa90: float = 0.0
    shots90: float = 0.0
    shots_on_target90: float = 0.0
    key_passes90: float = 0.0
    tackles90: float = 0.0
    interceptions90: float = 0.0
    clearances90: float = 0.0
    dribbles90: float = 0.0
    dribble_pct: float = 0.0
    passes_completed90: float = 0.0
    pass_pct: float = 0.0
    long_balls90: float = 0.0
    long_ball_pct: float = 0.0
    big_chances_created90: float = 0.0
    big_chances_missed90: float = 0.0
    possession_lost90: float = 0.0
    penalty_goals90: float = 0.0
    npxg90: float = 0.0
    xg_chain90: float = 0.0
    xg_buildup90: float = 0.0
    understat_key_passes90: float = 0.0
    understat_xa90: float = 0.0
    understat_shots90: float = 0.0
    understat_xg90: float = 0.0
    understat_matched: bool = False
    saves90: float = 0.0
    goals_prevented90: float = 0.0
    goals_conceded90: float = 0.0
    clean_sheet_pct: float = 0.0
    yellow_cards90: float = 0.0
    red_cards90: float = 0.0
    rating: float = 0.0
    seasons_used: list[str] = field(default_factory=list)
    teams_by_season: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> PlayerStats:
        payload = dict(data)
        _normalize_stat_gaps(payload)
        pos = payload.get("primary_position", "MF")
        fpl = payload.get("fpl_position") or _infer_fpl_position(pos)
        seasons = list(payload.get("seasons_used", []))
        teams_by_season = dict(payload.get("teams_by_season", {}))
        if not teams_by_season and payload.get("team") and seasons:
            teams_by_season = {s: payload["team"] for s in seasons}
        return cls(
            player=name,
            team=payload.get("team", ""),
            primary_position=pos,
            fpl_position=fpl,
            positions=payload.get("positions", [pos]),
            minutes=float(payload.get("minutes", 0)),
            games=int(payload.get("games", 0)),
            starts=int(payload.get("starts", 0)),
            goals90=float(payload.get("goals90", 0)),
            assists90=float(payload.get("assists90", 0)),
            xg90=float(payload.get("xg90", 0)),
            xa90=float(payload.get("xa90", 0)),
            shots90=float(payload.get("shots90", 0)),
            shots_on_target90=float(payload.get("shots_on_target90", 0)),
            key_passes90=float(payload.get("key_passes90", 0)),
            tackles90=float(payload.get("tackles90", 0)),
            interceptions90=float(payload.get("interceptions90", 0)),
            clearances90=float(payload.get("clearances90", 0)),
            dribbles90=float(payload.get("dribbles90", 0)),
            dribble_pct=float(payload.get("dribble_pct", 0)),
            passes_completed90=float(payload.get("passes_completed90", 0)),
            pass_pct=float(payload.get("pass_pct", 0)),
            long_balls90=float(payload.get("long_balls90", 0)),
            long_ball_pct=float(payload.get("long_ball_pct", 0)),
            big_chances_created90=float(payload.get("big_chances_created90", 0)),
            big_chances_missed90=float(payload.get("big_chances_missed90", 0)),
            possession_lost90=float(payload.get("possession_lost90", 0)),
            penalty_goals90=float(payload.get("penalty_goals90", 0)),
            npxg90=float(payload.get("npxg90", 0)),
            xg_chain90=float(payload.get("xg_chain90", 0)),
            xg_buildup90=float(payload.get("xg_buildup90", 0)),
            understat_key_passes90=float(payload.get("understat_key_passes90", 0)),
            understat_xa90=float(payload.get("understat_xa90", 0)),
            understat_shots90=float(payload.get("understat_shots90", 0)),
            understat_xg90=float(payload.get("understat_xg90", 0)),
            understat_matched=bool(payload.get("understat_matched", False)),
            saves90=float(payload.get("saves90", 0)),
            goals_prevented90=float(payload.get("goals_prevented90", 0)),
            goals_conceded90=float(payload.get("goals_conceded90", 0)),
            clean_sheet_pct=float(payload.get("clean_sheet_pct", 0)),
            yellow_cards90=float(payload.get("yellow_cards90", 0)),
            red_cards90=float(payload.get("red_cards90", 0)),
            rating=float(payload.get("rating", 0)),
            seasons_used=seasons,
            teams_by_season=teams_by_season,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "team": self.team,
            "primary_position": self.primary_position,
            "fpl_position": self.fpl_position,
            "positions": self.positions,
            "minutes": self.minutes,
            "games": self.games,
            "starts": self.starts,
            "goals90": self.goals90,
            "assists90": self.assists90,
            "xg90": self.xg90,
            "xa90": self.xa90,
            "shots90": self.shots90,
            "shots_on_target90": self.shots_on_target90,
            "key_passes90": self.key_passes90,
            "tackles90": self.tackles90,
            "interceptions90": self.interceptions90,
            "clearances90": self.clearances90,
            "dribbles90": self.dribbles90,
            "passes_completed90": self.passes_completed90,
            "pass_pct": self.pass_pct,
            "saves90": self.saves90,
            "goals_prevented90": self.goals_prevented90,
            "goals_conceded90": self.goals_conceded90,
            "clean_sheet_pct": self.clean_sheet_pct,
            "yellow_cards90": self.yellow_cards90,
            "red_cards90": self.red_cards90,
            "rating": self.rating,
            "seasons_used": self.seasons_used,
        }


def _infer_fpl_position(primary: str) -> FplPosition:
    p = primary.upper()
    if p == "GK":
        return "GK"
    if p in {"DF", "CB", "LB", "RB", "WB", "DEF"}:
        return "DEF"
    if p in {"FW", "ST", "CF", "FWD", "RW", "LW", "RM", "LM"}:
        return "FWD"
    return "MID"


def _normalize_stat_gaps(data: dict[str, Any]) -> None:
    """Backfill zero Sofascore/FBref fields from Understat and known overrides."""
    from player_names import apply_known_position_overrides

    player_id = data.get("player_id")
    if player_id is not None:
        apply_known_position_overrides(data, int(player_id))

    if not data.get("key_passes90") and data.get("understat_key_passes90"):
        data["key_passes90"] = data["understat_key_passes90"]
    if not data.get("xa90") and data.get("understat_xa90"):
        data["xa90"] = data["understat_xa90"]
    if not data.get("shots90") and data.get("understat_shots90"):
        data["shots90"] = data["understat_shots90"]
    if not data.get("xg90") and data.get("understat_xg90"):
        data["xg90"] = data["understat_xg90"]

    positions = {str(p).upper() for p in data.get("positions", [])}
    primary = str(data.get("primary_position", "")).upper()
    is_winger = primary in {"RW", "LW", "RM", "LM"} or bool(positions & {"RW", "LW", "RM", "LM"})
    if is_winger and not data.get("dribbles90"):
        kp = float(data.get("key_passes90", 0))
        ast = float(data.get("assists90", 0))
        data["dribbles90"] = min(3.0, kp * 0.32 + ast * 0.55)


@dataclass
class LineupSlot:
    player: str
    slot: str
    is_captain: bool = False
    is_vice_captain: bool = False


@dataclass
class FantasyTeam:
    name: str
    formation: str
    lineup: list[LineupSlot]
    bench: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FantasyTeam:
        lineup = [
            LineupSlot(
                player=row["player"],
                slot=row["slot"],
                is_captain=bool(row.get("captain", False)),
                is_vice_captain=bool(row.get("vice_captain", False)),
            )
            for row in data["lineup"]
        ]
        return cls(
            name=data["name"],
            formation=data.get("formation", "4-4-2"),
            lineup=lineup,
            bench=list(data.get("bench", [])),
        )

