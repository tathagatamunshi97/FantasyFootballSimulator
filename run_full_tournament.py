#!/usr/bin/env python3
"""Run a complete 14-team tournament simulation through to the final."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))

from google_sheets_teams import list_sheet_teams, load_team_by_name
from formation_fit import DEFAULT_FORMATION
from models import FantasyTeam
from report_builder import build_report
from stats_resolver import prepare_match_player_stats
from web.experiments import _apply_name_map, validate_team_payload
from web.state import get_stats_store
from web import tournament as tmod

OUTPUT_DIR = ROOT / "data"
DRAW_SEED = 42


def _now_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _load_sheet_teams(home_name: str, away_name: str) -> tuple[dict, dict]:
    """Load teams from Google Sheet with default formation + peak seasons (no saved lineups)."""
    store = get_stats_store()
    for name in (home_name, away_name):
        draft = load_team_by_name(name, formation=DEFAULT_FORMATION, store=store)
        meta = draft.get("sheet_meta") or {}
        if not meta.get("ready"):
            count = meta.get("player_count", "?")
            raise ValueError(
                f"Team '{draft.get('name')}' has {count}/11 players on the sheet."
            )
        roster = meta.get("full_roster") or meta.get("roster_players") or [
            (r.get("player") or "").strip()
            for r in draft.get("lineup", [])
            if (r.get("player") or "").strip()
        ]
        if roster:
            store.ensure_players(roster)
    team_a = load_team_by_name(home_name, formation=DEFAULT_FORMATION, store=store)
    team_b = load_team_by_name(away_name, formation=DEFAULT_FORMATION, store=store)
    for label, payload in (("Home", team_a), ("Away", team_b)):
        errors = validate_team_payload(payload, label)
        if errors:
            raise ValueError("; ".join(errors))
    return team_a, team_b


def _run_match_simulation(home_name: str, away_name: str, match_id: str, n_sims: int) -> tuple[dict, dict]:
    """Monte Carlo match using sheet defaults (skips squad-hub saved lineups)."""
    team_a, team_b = _load_sheet_teams(home_name, away_name)
    store = get_stats_store()
    player_stats, season_overrides, name_map = prepare_match_player_stats(team_a, team_b, store)
    resolved = _apply_name_map({"team_a": team_a, "team_b": team_b}, name_map)
    home = FantasyTeam.from_dict(resolved["team_a"])
    away = FantasyTeam.from_dict(resolved["team_b"])
    seed = abs(hash(match_id)) % (2**31)
    report = build_report(
        home,
        away,
        player_stats,
        n_simulations=n_sims,
        seed=seed,
        include_single_match=True,
        season_overrides=season_overrides,
    )
    home_goals, away_goals, score_str = tmod._score_from_report(report)
    mc = report.get("monte_carlo") or {}
    top_scorelines = mc.get("most_common_scorelines") or mc.get("scorelines") or []
    snapshot = {
        "score": score_str,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "expected_xg": mc.get("expected_xg"),
        "home_win_pct": mc.get("home_win_pct"),
        "away_win_pct": mc.get("away_win_pct"),
        "draw_pct": mc.get("draw_pct"),
        "simulations": n_sims,
        "mode_scoreline": top_scorelines[0] if top_scorelines else None,
        "top_scorelines": top_scorelines[:5],
    }
    return report, snapshot


def _play_group_match(t: dict, gkey: str, fx: dict, n_sims: int) -> None:
    report, snapshot = _run_match_simulation(fx["home"], fx["away"], fx["id"], n_sims)
    winner = tmod._resolve_winner(
        fx["home"], fx["away"], snapshot["home_goals"], snapshot["away_goals"], report, require_winner=False
    )
    result_id = fx["id"]
    t["match_results"][result_id] = {
        "match_id": fx["id"],
        "stage": "group",
        "group": gkey,
        "home": fx["home"],
        "away": fx["away"],
        **snapshot,
        **tmod._analysis_payload_from_report(report),
        "winner": winner,
        "played_at": tmod._now(),
    }
    fx["played"] = True
    fx["result_id"] = result_id
    fx["score"] = snapshot["score"]
    fx["winner"] = winner
    tmod._apply_group_result(
        t["groups"][gkey]["table"],
        fx["home"],
        fx["away"],
        snapshot["home_goals"],
        snapshot["away_goals"],
    )


def _play_knockout_match(t: dict, tie: dict, n_sims: int) -> None:
    report, snapshot = _run_match_simulation(tie["home"], tie["away"], tie["id"], n_sims)
    winner = tmod._resolve_winner(
        tie["home"], tie["away"], snapshot["home_goals"], snapshot["away_goals"], report, require_winner=True
    )
    if not winner:
        winner = tie["home"]
    result_id = tie["id"]
    t["match_results"][result_id] = {
        "match_id": tie["id"],
        "stage": "knockout",
        "home": tie["home"],
        "away": tie["away"],
        **snapshot,
        **tmod._analysis_payload_from_report(report),
        "winner": winner,
        "played_at": tmod._now(),
    }
    tie["played"] = True
    tie["result_id"] = result_id
    tie["score"] = snapshot["score"]
    tie["winner"] = winner
    tmod._advance_knockout_winner(t, tie, winner)


def _detect_upsets(t: dict, team_strength: dict[str, float]) -> list[dict]:
    upsets: list[dict] = []
    for res in t.get("match_results", {}).values():
        home = res["home"]
        away = res["away"]
        winner = res.get("winner")
        if not winner or winner not in (home, away):
            continue
        h_str = team_strength.get(home, 0)
        a_str = team_strength.get(away, 0)
        if h_str == 0 and a_str == 0:
            continue
        fav = home if h_str >= a_str else away
        dog = away if fav == home else home
        fav_str = max(h_str, a_str)
        dog_str = min(h_str, a_str)
        if winner == dog and fav_str - dog_str >= 0.03:
            upsets.append(
                {
                    "match_id": res["match_id"],
                    "stage": res.get("stage"),
                    "group": res.get("group"),
                    "home": home,
                    "away": away,
                    "score": res.get("score"),
                    "winner": winner,
                    "underdog": dog,
                    "favorite": fav,
                    "strength_gap": round(fav_str - dog_str, 4),
                    "home_win_pct": res.get("home_win_pct"),
                    "away_win_pct": res.get("away_win_pct"),
                }
            )
    return sorted(upsets, key=lambda u: -u["strength_gap"])


def _estimate_strength(team_names: list[str]) -> dict[str, float]:
    """Pre-tournament strength from transition_risk rank proxy (lower risk = stronger)."""
    from formation_fit import DEFAULT_FORMATION
    from google_sheets_teams import fetch_teams_dataframe, parse_teams_from_dataframe, team_payload_from_roster
    from models import FantasyTeam
    from stats_resolver import prepare_match_player_stats
    from team_ratings import compute_team_composites, compute_unit_ratings_by_slot
    from web.state import get_stats_store

    store = get_stats_store()
    df = fetch_teams_dataframe()
    rosters = parse_teams_from_dataframe(df)
    roster_by_name = {r.name: r for r in rosters.values()}
    out: dict[str, float] = {}
    for name in team_names:
        roster = roster_by_name.get(name)
        if not roster:
            continue
        try:
            payload = team_payload_from_roster(roster, formation=DEFAULT_FORMATION, store=store)
            ps, _, _ = prepare_match_player_stats(payload, payload, store)
            team = FantasyTeam.from_dict(payload)
            units = compute_unit_ratings_by_slot(team, ps)
            comp = compute_team_composites(team, ps, units=units)
            out[name] = round(
                0.35 * units.attack + 0.25 * units.midfield + 0.25 * units.defence + 0.15 * comp.overall, 4
            )
        except Exception:
            out[name] = 0.0
    return out


def _format_markdown(result: dict) -> str:
    lines = [
        f"# {result['name']}",
        "",
        f"**Champion:** {result['champion']}",
        f"**Runner-up:** {result.get('runner_up', '—')}",
        f"**Completed:** {result['completed_at']}",
        f"**Simulations per match:** {result['settings']['simulations_per_match']:,}",
        "",
        "## Group stage",
    ]
    for gkey, group in sorted(result.get("groups", {}).items()):
        lines.append(f"### Group {gkey}")
        lines.append("")
        lines.append("| Team | P | W | D | L | GF | GA | GD | Pts |")
        lines.append("|------|---|---|---|---|----|----|----|-----|")
        table = group["table"]
        ranked = sorted(
            table.keys(),
            key=lambda t: (-table[t]["pts"], -table[t]["gd"], -table[t]["gf"], t.lower()),
        )
        for team in ranked:
            r = table[team]
            lines.append(
                f"| {team} | {r['played']} | {r['w']} | {r['d']} | {r['l']} | "
                f"{r['gf']} | {r['ga']} | {r['gd']:+d} | {r['pts']} |"
            )
        lines.append("")
        lines.append("**Fixtures:**")
        for fx in group.get("fixtures", []):
            status = fx["score"] if fx.get("played") else "—"
            lines.append(f"- {fx['home']} vs {fx['away']}: **{status}** (R{fx['round']})")
        lines.append("")

    lines.append("## Knockout")
    lines.append("")
    for rnd in result.get("knockout", {}).get("rounds", []):
        lines.append(f"### {rnd.get('label', rnd.get('name'))}")
        for tie in rnd.get("ties", []):
            if tie.get("home") and tie.get("away"):
                score = tie.get("score") or "—"
                w = f" → **{tie['winner']}**" if tie.get("winner") else ""
                lines.append(f"- {tie['home']} vs {tie['away']}: **{score}**{w}")
        lines.append("")

    final = result.get("final", {})
    if final:
        lines.extend(
            [
                "## Final",
                "",
                f"**{final['home']} {final['score']} {final['away']}**",
                f"- Winner: **{final['winner']}**",
            ]
        )
        if final.get("expected_xg"):
            exg = final["expected_xg"]
            lines.append(f"- xG: {exg.get('home', '—')} – {exg.get('away', '—')}")
        lines.append("")

    upsets = result.get("upsets") or []
    if upsets:
        lines.append("## Notable upsets")
        lines.append("")
        for u in upsets:
            lines.append(
                f"- **{u['underdog']}** beat **{u['favorite']}** ({u['score']}) "
                f"[{u.get('stage', '')}{' G' + u['group'] if u.get('group') else ''}] "
                f"— strength gap {u['strength_gap']:.3f}"
            )
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    t0 = time.time()
    teams_info = list_sheet_teams()
    team_names = [t["name"] for t in teams_info if t.get("ready")]
    not_ready = [t["name"] for t in teams_info if not t.get("ready")]

    if len(team_names) < 14:
        print(f"ERROR: Only {len(team_names)} ready teams (need 14). Not ready: {not_ready}")
        return 1
    if len(team_names) > 14:
        team_names = team_names[:14]
        print(f"Note: Using first 14 ready teams of {len(teams_info)} on sheet")

    settings = {
        "group_count": 2,
        "teams_per_group": 7,
        "advance_per_group": 2,
        "knockout_format": "single_elim",
        "simulations_per_match": 10000,
    }

    print(f"Loading strength ratings for {len(team_names)} teams…")
    strength = _estimate_strength(team_names)

    name = f"14-Team Full Sim {_now_label()}"
    t = tmod.create_tournament(name, team_names, settings)
    tid = t["id"]
    print(f"Created tournament {tid}: {name}")

    t = tmod.set_teams(tid, team_names)
    t = tmod.perform_group_draw(tid, seed=DRAW_SEED)
    t = tmod.generate_group_fixtures(tid)
    n_sims = int(t["settings"]["simulations_per_match"])

    group_matches = []
    for gkey, group in sorted(t["groups"].items()):
        for fx in group["fixtures"]:
            group_matches.append((gkey, fx))

    print(f"Group stage: {len(group_matches)} matches × {n_sims:,} sims…")
    for i, (gkey, fx) in enumerate(group_matches, 1):
        m0 = time.time()
        print(f"  [{i}/{len(group_matches)}] {fx['home']} vs {fx['away']} …", flush=True)
        _play_group_match(t, gkey, fx, n_sims)
        print(f"    -> {fx['score']} ({time.time() - m0:.1f}s)", flush=True)
        if i % 7 == 0:
            tmod.save_tournament(t)
    tmod.save_tournament(t)

    print("Generating knockout bracket…")
    t = tmod.generate_knockout_bracket(tid)

    print(f"Knockout: {len(t['knockout']['rounds'])} rounds x {n_sims:,} sims…")
    for rnd in t["knockout"]["rounds"]:
        rname = rnd["name"]
        for tie in rnd["ties"]:
            if not tie.get("home") or not tie.get("away") or tie.get("played"):
                continue
            m0 = time.time()
            print(f"  {rname}: {tie['home']} vs {tie['away']} …", flush=True)
            _play_knockout_match(t, tie, n_sims)
            print(f"    -> {tie['score']} - {tie['winner']} ({time.time() - m0:.1f}s)", flush=True)
            tmod.save_tournament(t)
    t["status"] = "complete"
    tmod.save_tournament(t)

    # Champion from final
    final_round = t["knockout"]["rounds"][-1]
    final_tie = final_round["ties"][0]
    champion = final_tie["winner"]
    runner_up = final_tie["away"] if champion == final_tie["home"] else final_tie["home"]

    final_res = t["match_results"].get(final_tie["id"], {})
    upsets = _detect_upsets(t, strength)

    result = {
        "tournament_id": tid,
        "name": t["name"],
        "completed_at": tmod._now(),
        "elapsed_seconds": round(time.time() - t0, 1),
        "team_names": team_names,
        "not_ready_teams": not_ready,
        "settings": settings,
        "draw_seed": DRAW_SEED,
        "groups": t["groups"],
        "knockout": t["knockout"],
        "match_results": t["match_results"],
        "champion": champion,
        "runner_up": runner_up,
        "final": {
            "home": final_tie["home"],
            "away": final_tie["away"],
            "score": final_tie["score"],
            "winner": champion,
            "expected_xg": final_res.get("expected_xg"),
            "home_win_pct": final_res.get("home_win_pct"),
            "draw_pct": final_res.get("draw_pct"),
            "away_win_pct": final_res.get("away_win_pct"),
            "mode_scoreline": final_res.get("mode_scoreline"),
        },
        "upsets": upsets,
        "pre_tournament_strength": strength,
    }

    stamp = _now_label()
    json_path = OUTPUT_DIR / f"tournament_14team_{stamp}.json"
    md_path = OUTPUT_DIR / f"tournament_14team_{stamp}.md"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_format_markdown(result), encoding="utf-8")

    print()
    print("=" * 60)
    print(f"CHAMPION: {champion}")
    print(f"FINAL: {final_tie['home']} {final_tie['score']} {final_tie['away']}")
    if final_res.get("expected_xg"):
        exg = final_res["expected_xg"]
        print(f"xG: {exg.get('home')} – {exg.get('away')}")
    print(f"Upsets: {len(upsets)}")
    for u in upsets[:5]:
        print(f"  * {u['underdog']} beat {u['favorite']} ({u['score']})")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    print(f"Total time: {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
