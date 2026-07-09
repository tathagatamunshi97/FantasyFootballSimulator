#!/usr/bin/env python3
"""Rank tournament teams by transition_risk with defensive quartets."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from formation_fit import player_slot_fit
from google_sheets_teams import fetch_teams_dataframe, parse_teams_from_dataframe, team_payload_from_roster
from models import FantasyTeam
from slot_roles import CENTRE_BACK_SLOTS, FULLBACK_SLOTS, slot_role
from sofascore_client import StatsStore
from stats_resolver import prepare_match_player_stats
from team_ratings import compute_unit_ratings_by_slot

DEF_SLOT_ORDER = ("RB", "RWB", "CB1", "CB2", "CB3", "LB", "LWB")
MID_ROLES = ("dm", "cm", "am")


def defensive_quartet(team: FantasyTeam) -> list[tuple[str, str]]:
    by_slot = {s.slot.upper(): s.player for s in team.lineup}
    out: list[tuple[str, str]] = []
    for slot in DEF_SLOT_ORDER:
        if slot in by_slot and by_slot[slot]:
            out.append((slot, by_slot[slot]))
    if len(out) >= 4:
        return out[:4]
    # fallback: any fullback + centre_back from lineup order
    extras: list[tuple[str, str]] = []
    for s in team.lineup:
        su = s.slot.upper()
        role = slot_role(s.slot)
        if role in ("fullback", "centre_back") or su in FULLBACK_SLOTS or su in CENTRE_BACK_SLOTS:
            if (su, s.player) not in out and all(su != x[0] for x in out):
                extras.append((su, s.player))
    merged = out + [e for e in extras if e not in out]
    return merged[:4]


def format_quartet(pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return "—"
    parts = []
    for slot, name in pairs:
        label = slot
        if slot.startswith("CB"):
            label = "CB"
        parts.append(f"{label}: {name}")
    return ", ".join(parts)


def midfield_cover(team: FantasyTeam) -> str:
    bits: list[str] = []
    for role_key, label in (("dm", "DM"), ("cm", "CM"), ("am", "AM")):
        names = [s.player for s in team.lineup if slot_role(s.slot) == role_key]
        if names:
            bits.append(f"{label}: {', '.join(names)}")
    return "; ".join(bits) if bits else "—"


def kinjal_match(name: str) -> bool:
    n = name.lower().replace(" ", "")
    return "kinjal" in n and "sayan" in n


def main() -> None:
    store = StatsStore()
    df = fetch_teams_dataframe()
    rosters = parse_teams_from_dataframe(df)
    rows: list[dict] = []
    errors: list[str] = []

    for roster in sorted(rosters.values(), key=lambda r: r.name.lower()):
        try:
            payload = team_payload_from_roster(roster, formation="4-3-3", store=store)
            if not payload.get("prime_player"):
                payload["prime_player"] = ""
            ps, _, _ = prepare_match_player_stats(payload, payload, store)
            team = FantasyTeam.from_dict(payload)
            units = compute_unit_ratings_by_slot(team, ps)
            quartet = defensive_quartet(team)
            rows.append(
                {
                    "team": roster.name,
                    "transition_risk": units.transition_risk,
                    "quartet": format_quartet(quartet),
                    "mid_cover": midfield_cover(team),
                    "formation": payload.get("formation", ""),
                    "kinjal": kinjal_match(roster.name),
                }
            )
        except Exception as exc:
            errors.append(f"{roster.name}: {exc}")

    rows.sort(key=lambda r: r["transition_risk"])

    print("## Tournament transition risk ranking (lower = safer)\n")
    print(
        "Formula: max fullback/wingback exposure × uncovered shielding; "
        "mid cover is formation-aware (equal three-mid block, dual-DM blend, or DM-heavy default).\n"
    )
    print("| Rank | Team | Transition risk | Defensive quartet |")
    print("| ---: | --- | ---: | --- |")
    kinjal_rank = None
    for i, r in enumerate(rows, 1):
        team_cell = r["team"]
        if r["kinjal"]:
            kinjal_rank = i
            team_cell = f"**{team_cell}**"
        print(f"| {i} | {team_cell} | {r['transition_risk']:.3f} | {r['quartet']} |")

    if kinjal_rank is not None:
        tr = next(x["transition_risk"] for x in rows if x["kinjal"])
        print(f"\n**Kinjal+Sayan C** rank: **#{kinjal_rank}** of {len(rows)} (transition_risk **{tr:.3f}**).")
    else:
        print("\n_Kinjal+Sayan C not found in sheet rosters._")

    print("\n### Midfield cover (optional)\n")
    print("| Team | DM / CM / AM |")
    print("| --- | --- |")
    for r in rows:
        print(f"| {r['team']} | {r['mid_cover']} |")

    if errors:
        print("\n### Errors\n")
        for e in errors:
            print(f"- {e}")


if __name__ == "__main__":
    main()
