#!/usr/bin/env python3
"""Rank tournament teams by UnitRatings.midfield (engine midfield unit)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from formation_fit import player_slot_fit
from google_sheets_teams import fetch_teams_dataframe, parse_teams_from_dataframe, team_payload_from_roster
from models import FantasyTeam
from slot_roles import slot_role, slot_unit_weights
from sofascore_client import StatsStore
from stats_resolver import prepare_match_player_stats
from team_ratings import (
    _player_midfield_contrib,
    compute_team_composites,
    compute_unit_ratings_by_slot,
)

FORMATION = "4-3-3"
MID_ROLE_ORDER = ("dm", "cm", "am")
MID_LABEL = {"dm": "DM", "cm": "CM", "am": "AM"}


def midfield_trio(team: FantasyTeam) -> str:
    by_role: dict[str, list[str]] = {r: [] for r in MID_ROLE_ORDER}
    for s in team.lineup:
        role = slot_role(s.slot)
        if role in by_role and s.player:
            by_role[role].append(s.player)
    parts: list[str] = []
    for role in MID_ROLE_ORDER:
        names = by_role[role]
        if names:
            parts.append(f"{MID_LABEL[role]}: {', '.join(names)}")
    if parts:
        return "; ".join(parts)
    # fallback: any CM1/CM2 style
    cms = [f"{s.slot}: {s.player}" for s in team.lineup if slot_role(s.slot) == "cm"]
    return "; ".join(cms) if cms else "-"


def mid_slot_scores(team: FantasyTeam, player_stats: dict) -> str:
    """Per-midfielder weighted midfield contrib for the trio."""
    scored: list[tuple[str, str, float]] = []
    for s in team.lineup:
        role = slot_role(s.slot)
        if role not in MID_ROLE_ORDER:
            continue
        st = player_stats[s.player]
        fit = player_slot_fit(st, team.formation, s.slot)
        w = slot_unit_weights(s.slot, st.fpl_position)
        val = _player_midfield_contrib(st, fit) * w.midfield
        scored.append((MID_LABEL[role], s.player, val))
    if not scored:
        return "-"
    return ", ".join(f"{name} ({lab} {val:.2f})" for lab, name, val in scored)


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
                    "midfield": units.midfield,
                    "midfield_defence": units.midfield_defence,
                    "midfield_control": tc.midfield_control,
                    "chance_creation": units.chance_creation,
                    "trio": midfield_trio(team),
                    "trio_scores": mid_slot_scores(team, ps),
                    "formation": payload.get("formation", FORMATION),
                    "peak_season": peak_note,
                    "lineup_source": "sheet roster + auto XI/slots (4-3-3)",
                }
            )
        except Exception as exc:
            errors.append(f"{roster.name}: {exc}")

    rows.sort(key=lambda r: -r["midfield"])

    lines: list[str] = []
    lines.append("## Tournament midfield ranking (higher = better)\n")
    lines.append(
        "**Primary sort key:** `UnitRatings.midfield` — mean across non-GK XI of "
        "`_player_midfield_contrib × slot midfield weight` "
        "(progression + creation + defensive mid work − turnover penalty, × slot fit). "
        "This is the engine's midfield unit used in overall strength / midfield battle.\n"
    )
    lines.append(
        "**Secondary columns:** `midfield_defence` (ball-winning shield unit), "
        "`midfield_control` (TeamComposites blend of midfield + possession + mid-def).\n"
    )
    lines.append(
        f"**Lineup source:** Google Sheets roster → auto starting XI + slot assign "
        f"for formation **{FORMATION}** (normalizes to attacking 4-3-3: DM/CM/AM); "
        "Round-3 peak seasons via `default_peak_season` "
        "(same path as press resistance / pressing intensity). Not manual lineups.\n"
    )
    lines.append(
        "| Rank | Team | Midfield | Mid-def | Mid control | Midfield trio |"
    )
    lines.append("| ---: | --- | ---: | ---: | ---: | --- |")
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r['team']} | {r['midfield']:.3f} | {r['midfield_defence']:.3f} | "
            f"{r['midfield_control']:.3f} | {r['trio']} |"
        )

    lines.append("\n### Per-slot midfield contrib (trio)\n")
    lines.append("| Team | DM / CM / AM scores |")
    lines.append("| --- | --- |")
    for r in rows:
        lines.append(f"| {r['team']} | {r['trio_scores']} |")

    if errors:
        lines.append("\n### Errors\n")
        for e in errors:
            lines.append(f"- {e}")

    text = "\n".join(lines) + "\n"
    print(text)

    out_md = ROOT / "_midfield_rank_out.md"
    out_json = ROOT / "_midfield_rank_out.json"
    out_md.write_text(text, encoding="utf-8")
    out_json.write_text(
        json.dumps(
            {
                "formation": FORMATION,
                "lineup_source": "google_sheets auto XI/slots",
                "primary_metric": "UnitRatings.midfield",
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
