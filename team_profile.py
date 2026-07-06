"""Print aggregated statistical profiles for a fantasy XI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from formation_fit import team_formation_fit
from models import FantasyTeam, PlayerStats
from team_ratings import UnitRatings, compute_unit_ratings
from trophy_bonus import TeamTrophyProfile, team_trophy_profile


@dataclass
class TeamStatProfile:
    name: str
    formation: str
    units: UnitRatings
    trophy: TeamTrophyProfile
    formation_fit: dict[str, Any]
    aggregates: dict[str, float]
    players: list[dict[str, Any]]


def _line_avg(players: list[PlayerStats], attr: str) -> float:
    vals = [float(getattr(p, attr, 0) or 0) for p in players]
    return sum(vals) / len(vals) if vals else 0.0


def build_team_profile(
    team: FantasyTeam,
    player_stats: dict[str, PlayerStats],
) -> TeamStatProfile:
    lineup_stats = [player_stats[s.player] for s in team.lineup]
    units = compute_unit_ratings(team, player_stats)
    trophy = team_trophy_profile(team, player_stats)
    fit = team_formation_fit(
        team.formation,
        [(s.player, s.slot) for s in team.lineup],
        player_stats,
    )

    gks = [p for p in lineup_stats if p.fpl_position == "GK"]
    defs = [p for p in lineup_stats if p.fpl_position == "DEF"]
    mids = [p for p in lineup_stats if p.fpl_position == "MID"]
    fwds = [p for p in lineup_stats if p.fpl_position == "FWD"]

    aggregates = {
        "avg_xg90": _line_avg(lineup_stats, "xg90"),
        "avg_npxg90": _line_avg(lineup_stats, "npxg90"),
        "avg_xa90": _line_avg(lineup_stats, "xa90"),
        "avg_xg_buildup90": _line_avg(lineup_stats, "xg_buildup90"),
        "avg_xg_chain90": _line_avg(lineup_stats, "xg_chain90"),
        "avg_shots90": _line_avg(lineup_stats, "shots90"),
        "avg_key_passes90": _line_avg(lineup_stats, "key_passes90"),
        "avg_big_chances_created90": _line_avg(lineup_stats, "big_chances_created90"),
        "avg_tackles90": _line_avg(lineup_stats, "tackles90"),
        "avg_interceptions90": _line_avg(lineup_stats, "interceptions90"),
        "avg_pass_pct": _line_avg(lineup_stats, "pass_pct"),
        "avg_possession_lost90": _line_avg(lineup_stats, "possession_lost90"),
        "fwd_xg90": _line_avg(fwds, "xg90"),
        "mid_xg_buildup90": _line_avg(mids + defs, "xg_buildup90"),
        "def_tackles90": _line_avg(defs, "tackles90"),
        "gk_goals_prevented90": _line_avg(gks, "goals_prevented90"),
        "trophy_multiplier": trophy.multiplier,
    }

    player_rows: list[dict[str, Any]] = []
    for slot in team.lineup:
        p = player_stats[slot.player]
        tp = next(t for t in trophy.players if t.player == slot.player)
        player_rows.append(
            {
                "player": slot.player,
                "slot": slot.slot,
                "team": p.team,
                "xg90": round(p.xg90, 2),
                "npxg90": round(p.npxg90, 2),
                "xa90": round(p.xa90, 2),
                "xg_buildup90": round(p.xg_buildup90, 2),
                "rating": round(p.rating, 2),
                "minutes": int(p.minutes),
                "trophy_bonus": tp.bonus,
                "trophy_notes": tp.details,
            }
        )

    return TeamStatProfile(
        name=team.name,
        formation=team.formation,
        units=units,
        trophy=trophy,
        formation_fit=fit,
        aggregates=aggregates,
        players=player_rows,
    )


def print_team_profile(profile: TeamStatProfile) -> None:
    u = profile.units
    a = profile.aggregates
    print(f"\n{'='*64}")
    print(f"{profile.name}  |  {profile.formation}")
    print(f"{'='*64}")
    print(
        f"Units (0-1):  ATK {u.attack:.2f}  (fin {u.finishing:.2f}  create {u.chance_creation:.2f})  "
        f"MID {u.midfield:.2f}  DEF {u.defence:.2f}  MID-DEF {u.midfield_defence:.2f}  "
        f"GK {u.goalkeeper:.2f}  trans-risk {u.transition_risk:.2f}  overall {u.overall:.2f}"
    )
    if u.gk_is_backup:
        print(f"  GK note: backup profile (confidence {u.gk_confidence:.2f})")
    print(
        f"Silverware boost: x{a['trophy_multiplier']:.3f}  "
        f"(avg player bonus {profile.trophy.lineup_bonus:.3f})"
    )
    print(f"Formation fit: {profile.formation_fit['average_fit']:.2f}")
    print("\nSquad averages (per 90, blended seasons):")
    print(
        f"  xG {a['avg_xg90']:.2f}  npxG {a['avg_npxg90']:.2f}  xA {a['avg_xa90']:.2f}  "
        f"xGBuildup {a['avg_xg_buildup90']:.2f}  xGChain {a['avg_xg_chain90']:.2f}"
    )
    print(
        f"  Shots {a['avg_shots90']:.2f}  Key passes {a['avg_key_passes90']:.2f}  "
        f"Big chances {a['avg_big_chances_created90']:.2f}"
    )
    print(
        f"  Tackles {a['avg_tackles90']:.2f}  Interceptions {a['avg_interceptions90']:.2f}  "
        f"Pass% {a['avg_pass_pct']:.1f}  Poss lost {a['avg_possession_lost90']:.1f}"
    )
    print(
        f"Line groups — FWD xG {a['fwd_xg90']:.2f}  "
        f"MID/DEF buildup {a['mid_xg_buildup90']:.2f}  "
        f"DEF tackles {a['def_tackles90']:.2f}  "
        f"GK prevented {a['gk_goals_prevented90']:.3f}"
    )
    print("\nPlayers:")
    for row in profile.players:
        trophy = f"  +{row['trophy_bonus']:.3f}" if row["trophy_bonus"] else ""
        print(
            f"  {row['player']:<28} {row['slot']:<5}  "
            f"xG {row['xg90']:.2f}  xA {row['xa90']:.2f}  "
            f"build {row['xg_buildup90']:.2f}  min {row['minutes']}{trophy}"
        )
        for note in row["trophy_notes"]:
            if "Limited" not in note and "No title" not in note:
                print(f"      · {note}")
