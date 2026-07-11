#!/usr/bin/env python3
"""Rank tournament teams by press_resistance (TeamComposites)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from formation_fit import player_slot_fit
from google_sheets_teams import fetch_teams_dataframe, parse_teams_from_dataframe, team_payload_from_roster
from models import FantasyTeam
from sofascore_client import StatsStore
from stats_resolver import prepare_match_player_stats
from team_ratings import _player_press_resistance, compute_team_composites, compute_unit_ratings_by_slot

FORMATION = "4-3-3"


def top_contributors(team: FantasyTeam, player_stats: dict, n: int = 3) -> str:
    scored: list[tuple[float, str, str]] = []
    for slot in team.lineup:
        st = player_stats[slot.player]
        if st.fpl_position not in ("DEF", "MID"):
            continue
        fit = player_slot_fit(st, team.formation, slot.slot)
        pr = _player_press_resistance(st, fit)
        if pr <= 0:
            continue
        scored.append((pr, slot.slot, slot.player))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return "-"
    return ", ".join(f"{name} ({slot} {val:.2f})" for val, slot, name in scored[:n])


def main() -> None:
    store = StatsStore()
    df = fetch_teams_dataframe()
    rosters = parse_teams_from_dataframe(df)
    rows: list[dict] = []
    errors: list[str] = []

    for roster in sorted(rosters.values(), key=lambda r: r.name.lower()):
        try:
            payload = team_payload_from_roster(roster, formation=FORMATION, store=store)
            if not payload.get("prime_player"):
                payload["prime_player"] = ""
            ps, _, _ = prepare_match_player_stats(payload, payload, store)
            team = FantasyTeam.from_dict(payload)
            units = compute_unit_ratings_by_slot(team, ps)
            tc = compute_team_composites(team, ps, units=units)
            peak = payload.get("peak_season") or {}
            peak_note = ""
            if peak.get("player") and peak.get("season"):
                peak_note = f"{peak['player']} @ {peak['season']}"
            rows.append(
                {
                    "team": roster.name,
                    "press_resistance": tc.press_resistance,
                    "drivers": top_contributors(team, ps),
                    "formation": payload.get("formation", FORMATION),
                    "peak_season": peak_note,
                    "lineup_source": "sheet roster + auto XI/slots (4-3-3)",
                }
            )
        except Exception as exc:
            errors.append(f"{roster.name}: {exc}")

    rows.sort(key=lambda r: -r["press_resistance"])

    lines: list[str] = []
    lines.append("## Tournament press resistance ranking (higher = better)\n")
    lines.append(
        "Formula: mean of DEF/MID XI `_player_press_resistance` = "
        "`scale(dribbles90, 2.5) * scale(dribble_pct, 100) * (0.55 + 0.45 * slot_fit)` "
        "(FWD/GK excluded from the average).\n"
    )
    lines.append(
        f"**Lineup source:** Google Sheets roster → auto starting XI + slot assign "
        f"for formation **{FORMATION}**; Round-3 peak seasons via `default_peak_season` "
        "(same path as `_transition_risk_rank.py`). Not manual lineups.\n"
    )
    lines.append("| Rank | Team | Press resistance | Top contributors (slot score) |")
    lines.append("| ---: | --- | ---: | --- |")
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r['team']} | {r['press_resistance']:.3f} | {r['drivers']} |"
        )

    if errors:
        lines.append("\n### Errors\n")
        for e in errors:
            lines.append(f"- {e}")

    text = "\n".join(lines) + "\n"
    print(text)

    out_md = ROOT / "_press_resistance_rank_out.md"
    out_json = ROOT / "_press_resistance_rank_out.json"
    out_md.write_text(text, encoding="utf-8")
    out_json.write_text(
        json.dumps(
            {
                "formation": FORMATION,
                "lineup_source": "google_sheets auto XI/slots",
                "metric": "press_resistance",
                "higher_is_better": True,
                "teams": rows,
                "errors": errors,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {out_md.name} and {out_json.name}", file=sys.stderr)


if __name__ == "__main__":
    main()
