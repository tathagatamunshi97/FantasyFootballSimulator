#!/usr/bin/env python3
"""CLI for Monte Carlo football match simulation between two lineups."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from excel_loader import load_matchup_from_excel, write_excel_template
from sofascore_client import StatsStore
from formation_fit import supported_formations as list_formations
from match_engine import MatchSimConfig, monte_carlo_matches, simulate_match_once
from models import FantasyTeam

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_EXCEL = DATA_DIR / "team_a_vs_b.xlsx"
DEFAULT_JSON = DATA_DIR / "team_a_vs_b.json"


def load_matchup_json(path: Path) -> tuple[FantasyTeam, FantasyTeam]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return FantasyTeam.from_dict(data["home"]), FantasyTeam.from_dict(data["away"])


def load_input(
    *,
    excel: Path | None,
    matchup: Path | None,
    store: StatsStore,
) -> tuple[FantasyTeam, FantasyTeam]:
    if excel is not None:
        return load_matchup_from_excel(excel, store)
    path = matchup or DEFAULT_JSON
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return load_matchup_from_excel(path, store)
    return load_matchup_json(path)


def collect_player_names(*teams: FantasyTeam) -> list[str]:
    names: list[str] = []
    for t in teams:
        names.extend(s.player for s in t.lineup)
        names.extend(t.bench)
    return list(dict.fromkeys(names))


def print_lineup(team: FantasyTeam) -> None:
    print(f"\n{team.name} ({team.formation})")
    for s in team.lineup:
        print(f"  {s.slot:<5} {s.player}")


def print_formation_fit(label: str, fit: dict) -> None:
    print(f"\n--- {label} ({fit['formation']}) fit: {fit['average_fit']:.2f} ---")
    for row in fit["players"]:
        flag = " !" if row.get("missing_stats") else ""
        print(f"  {row['player']:<28} {row['slot']:<5} fit={row['fit']:.2f}{flag}")


def _format_goal(event) -> str:
    if event.assister:
        return f"{event.minute}' {event.scorer} (assist: {event.assister})"
    return f"{event.minute}' {event.scorer}"


def print_match(result) -> None:
    print(f"\n=== MATCH RESULT ===")
    print(f"{result.home.team}  {result.home.goals} - {result.away.goals}  {result.away.team}")
    print(f"xG:  {result.home.xg:.2f} - {result.away.xg:.2f}")
    for side in (result.home, result.away):
        u = side.units
        print(
            f"  {side.team} units  ATK {u.attack:.2f}  FIN {u.finishing:.2f}  "
            f"CREATE {u.chance_creation:.2f}  MID {u.midfield:.2f}  DEF {u.defence:.2f}  "
            f"MID-DEF {u.midfield_defence:.2f}  TRANS {u.transition_risk:.2f}  GK {u.goalkeeper:.2f}"
        )
    winner = result.winner or "Draw"
    print(f"Outcome: {winner}\n")

    for side in (result.home, result.away):
        if side.scorers:
            print(f"{side.team} goals:")
            for g in side.scorers:
                print(f"  {_format_goal(g)}")
        else:
            print(f"{side.team}: no goals")
        print()


def print_monte_carlo(stats: dict) -> None:
    print(f"\n=== MONTE CARLO MATCH SIMULATION ({stats['simulations']:,} runs) ===")
    print(f"{stats['home_team']} vs {stats['away_team']}\n")

    ur = stats["unit_ratings"]
    print("  Unit ratings (0-1 scale):")
    for label, side in ((stats["home_team"], "home"), (stats["away_team"], "away")):
        u = ur[side]
        gk_note = ""
        if side == "home" and stats.get("home_gk_meta"):
            m = stats["home_gk_meta"]
            gk_note = f"  GK conf={m['confidence']:.2f}" + (" backup" if m["is_backup"] else " starter")
        elif side == "away" and stats.get("away_gk_meta"):
            m = stats["away_gk_meta"]
            gk_note = f"  GK conf={m['confidence']:.2f}" + (" backup" if m["is_backup"] else " starter")
        print(
            f"    {label:<12}  ATK {u['attack']:.2f}  FIN {u['finishing']:.2f}  "
            f"CREATE {u['chance_creation']:.2f}  MID {u['midfield']:.2f}  "
            f"DEF {u['defence']:.2f}  MID-DEF {u['midfield_defence']:.2f}  "
            f"TRANS {u['transition_risk']:.2f}  GK {u['goalkeeper']:.2f}  "
            f"overall {u['overall']:.2f}{gk_note}"
        )
    mb = stats["midfield_battle"]
    print(
        f"\n  Silverware multipliers:  "
        f"{stats['home_team']} x{stats.get('home_trophy_multiplier', 1):.3f}  |  "
        f"{stats['away_team']} x{stats.get('away_trophy_multiplier', 1):.3f}"
    )
    print(
        f"  Midfield battle multipliers:  "
        f"{stats['home_team']} x{mb['home_chance_multiplier']:.2f}  |  "
        f"{stats['away_team']} x{mb['away_chance_multiplier']:.2f}"
    )

    xg = stats["expected_xg"]
    print(f"\nExpected xG per match:  {stats['home_team']} {xg['home']:.2f}  |  {stats['away_team']} {xg['away']:.2f}")
    print()
    print(f"  {stats['home_team']} win:  {stats['home_win_pct']}%")
    print(f"  Draw:              {stats['draw_pct']}%")
    print(f"  {stats['away_team']} win:  {stats['away_win_pct']}%")
    print()
    print(f"  Avg goals:  {stats['home_team']} {stats['home_goals_avg']}  |  {stats['away_team']} {stats['away_goals_avg']}")
    print(f"  Avg total goals:     {stats['total_goals_avg']}")
    print(f"  Both teams score:    {stats['btts_pct']}%")
    print(f"  Over 2.5 goals:      {stats['over_2_5_pct']}%")
    print()
    print("  Most common scorelines:")
    for row in stats["most_common_scorelines"]:
        print(f"    {row['score']:<7} {row['pct']}%")

    print_formation_fit(stats["home_team"], stats["home_formation_fit"])
    print_formation_fit(stats["away_team"], stats["away_formation_fit"])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monte Carlo football match simulator (Sofascore xG + formation fit)"
    )
    parser.add_argument(
        "mode",
        choices=["simulate", "monte-carlo", "formation-fit", "team-profile", "list-formations", "create-template"],
        help="Operation mode",
    )
    parser.add_argument(
        "-e",
        "--excel",
        type=Path,
        default=None,
        help="Excel workbook with Team A / Team B columns",
    )
    parser.add_argument(
        "-m",
        "--matchup",
        type=Path,
        default=None,
        help="JSON matchup file",
    )
    parser.add_argument("-n", "--runs", type=int, default=5000, help="Monte Carlo iterations")
    parser.add_argument("-s", "--seed", type=int, default=None, help="Random seed")
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="Player stats cache JSON",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Save Monte Carlo JSON summary",
    )
    args = parser.parse_args()

    if args.mode == "list-formations":
        print("Supported formations:")
        for f in list_formations():
            print(f"  {f}")
        return

    if args.mode == "create-template":
        out = args.output or DEFAULT_EXCEL
        from build_teams_excel import TEAM_A, TEAM_B

        write_excel_template(out, TEAM_A, TEAM_B)
        print(f"Template written to {out}")
        return

    store = StatsStore(args.cache)
    excel_path = args.excel
    if excel_path is None and args.matchup is None:
        if DEFAULT_EXCEL.exists():
            excel_path = DEFAULT_EXCEL
        elif DEFAULT_JSON.exists():
            args.matchup = DEFAULT_JSON

    home, away = load_input(excel=excel_path, matchup=args.matchup, store=store)
    print_lineup(home)
    print_lineup(away)

    names = collect_player_names(home, away)
    player_stats = store.require(names)

    if args.mode == "formation-fit":
        from formation_fit import team_formation_fit

        home_fit = team_formation_fit(
            home.formation, [(s.player, s.slot) for s in home.lineup], player_stats
        )
        away_fit = team_formation_fit(
            away.formation, [(s.player, s.slot) for s in away.lineup], player_stats
        )
        print_formation_fit(home.name, home_fit)
        print_formation_fit(away.name, away_fit)
        return

    if args.mode == "team-profile":
        from team_profile import build_team_profile, print_team_profile

        print_team_profile(build_team_profile(home, player_stats))
        print_team_profile(build_team_profile(away, player_stats))
        return

    cfg = MatchSimConfig(n_simulations=args.runs, seed=args.seed)

    if args.mode == "simulate":
        import random

        rng = random.Random(cfg.seed)
        result = simulate_match_once(home, away, player_stats, cfg, rng)
        print_match(result)
        return

    stats = monte_carlo_matches(home, away, player_stats, cfg)

    from team_profile import build_team_profile, print_team_profile

    print_team_profile(build_team_profile(home, player_stats))
    print_team_profile(build_team_profile(away, player_stats))
    print_monte_carlo(stats)

    if stats.get("example_match"):
        print_match(stats["example_match"])

    if args.output:
        out = dict(stats)
        ex = out.pop("example_match", None)
        if ex:
            out["example_match"] = {
                "scoreline": ex.scoreline,
                "home_xg": ex.home.xg,
                "away_xg": ex.away.xg,
                "winner": ex.winner,
            }
        args.output.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\nSaved summary to {args.output}")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
