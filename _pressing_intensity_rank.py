#!/usr/bin/env python3
"""Rank tournament teams by pressing_intensity (TeamComposites)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from google_sheets_teams import fetch_teams_dataframe, parse_teams_from_dataframe, team_payload_from_roster
from models import FantasyTeam
from sofascore_client import StatsStore
from stats_resolver import prepare_match_player_stats
from team_ratings import compute_team_composites, compute_unit_ratings_by_slot

FORMATION = "4-3-3"


def top_contributors(team: FantasyTeam, player_stats: dict, n: int = 3) -> str:
    """Rank XI by tackles90 + interceptions90 (pressing volume signal)."""
    scored: list[tuple[float, str, str, float]] = []
    for slot in team.lineup:
        st = player_stats[slot.player]
        vol = float(st.tackles90) + float(st.interceptions90)
        if vol <= 0:
            continue
        duel = float(st.duels_won_pct) if st.duels_won_pct > 0 else 0.0
        scored.append((vol, slot.slot, slot.player, duel))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return "-"
    parts = []
    for vol, slot, name, duel in scored[:n]:
        if duel > 0:
            parts.append(f"{name} ({slot} T+I {vol:.1f}, duel% {duel:.0f})")
        else:
            parts.append(f"{name} ({slot} T+I {vol:.1f})")
    return ", ".join(parts)


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
                    "pressing_intensity": tc.pressing_intensity,
                    "drivers": top_contributors(team, ps),
                    "formation": payload.get("formation", FORMATION),
                    "peak_season": peak_note,
                    "lineup_source": "sheet roster + auto XI/slots (4-3-3)",
                }
            )
        except Exception as exc:
            errors.append(f"{roster.name}: {exc}")

    rows.sort(key=lambda r: -r["pressing_intensity"])

    lines: list[str] = []
    lines.append("## Tournament pressing intensity ranking (higher = more intense)\n")
    lines.append(
        "Formula: `pressing_base = scale(avg(tackles90+interceptions90), 4.5)` then "
        "`pressing_intensity = clamp(pressing_base * 0.72 + scale(avg_duel_won_pct, 100) * 0.28)` "
        "when duel% available (else full weight on pressing_base). Full XI average.\n"
    )
    lines.append(
        f"**Lineup source:** Google Sheets roster → auto starting XI + slot assign "
        f"for formation **{FORMATION}**; Round-3 peak seasons via `default_peak_season` "
        "(same path as `_press_resistance_rank.py` / `_transition_risk_rank.py`). Not manual lineups.\n"
    )
    lines.append("| Rank | Team | Pressing intensity | Top contributors (T+I) |")
    lines.append("| ---: | --- | ---: | --- |")
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r['team']} | {r['pressing_intensity']:.3f} | {r['drivers']} |"
        )

    if errors:
        lines.append("\n### Errors\n")
        for e in errors:
            lines.append(f"- {e}")

    text = "\n".join(lines) + "\n"
    print(text)

    out_md = ROOT / "_pressing_intensity_rank_out.md"
    out_json = ROOT / "_pressing_intensity_rank_out.json"
    out_md.write_text(text, encoding="utf-8")
    out_json.write_text(
        json.dumps(
            {
                "formation": FORMATION,
                "lineup_source": "google_sheets auto XI/slots",
                "metric": "pressing_intensity",
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
