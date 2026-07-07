"""Generate human-readable matchup analysis explaining simulation outcomes."""
from __future__ import annotations

from typing import Any, Literal

from slot_roles import slot_role

Tier = Literal["strength", "moderate_strength", "balanced", "moderate_weakness", "weakness"]


def _side_label(matchup: dict, side: str) -> str:
    return matchup[side]["name"]


def _units(profile: dict) -> dict[str, float]:
    return profile["extended"]["units"]


def _delta(home: float, away: float) -> float:
    return round(away - home, 3)


def _winner_side(home: float, away: float, *, higher_is_better: bool = True) -> str | None:
    d = away - home if higher_is_better else home - away
    if abs(d) < 0.03:
        return None
    return "away" if d > 0 else "home"


def _pct_str(v: float) -> str:
    return f"{v:.1f}%"


def _fmt(v: float, d: int = 2) -> str:
    return f"{v:.{d}f}"


def _edge_phrase(side: str | None, home: str, away: str) -> str:
    if side is None:
        return "even"
    return away if side == "away" else home


def _rank_factors(factors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(factors, key=lambda f: abs(f.get("impact", 0)), reverse=True)


def build_matchup_analysis(report: dict[str, Any]) -> dict[str, Any]:
    """Turn a simulation report into structured explanation for the web UI."""
    matchup = report["matchup"]
    home_name = _side_label(matchup, "home")
    away_name = _side_label(matchup, "away")
    home_p = report["profiles"]["home"]
    away_p = report["profiles"]["away"]
    hu = _units(home_p)
    au = _units(away_p)
    mc = report["monte_carlo"]
    mech = report["mechanics"]
    hxg = float(mc["expected_xg"]["home"])
    axg = float(mc["expected_xg"]["away"])
    xg_diff = axg - hxg

    home_win = float(mc["home_win_pct"])
    away_win = float(mc["away_win_pct"])
    draw = float(mc["draw_pct"])

    if away_win > home_win + 4:
        favorite, fav_pct, underdog, und_pct = away_name, away_win, home_name, home_win
        fav_side = "away"
    elif home_win > away_win + 4:
        favorite, fav_pct, underdog, und_pct = home_name, home_win, away_name, away_win
        fav_side = "home"
    else:
        favorite, fav_pct, underdog, und_pct = None, max(home_win, away_win), None, min(home_win, away_win)
        fav_side = "drawish"

    factors: list[dict[str, Any]] = []

    fin_edge = _winner_side(hu["finishing"], au["finishing"])
    fin_d = _delta(hu["finishing"], au["finishing"])
    factors.append(
        {
            "factor": "Finishing quality",
            "edge": fin_edge,
            "home": hu["finishing"],
            "away": au["finishing"],
            "delta": fin_d,
            "impact": abs(fin_d) * 1.4,
            "explanation": (
                f"{_edge_phrase(fin_edge, home_name, away_name)} converts chances better "
                f"(finishing {hu['finishing']:.2f} vs {au['finishing']:.2f})."
            ),
        }
    )

    cre_edge = _winner_side(hu["chance_creation"], au["chance_creation"])
    cre_d = _delta(hu["chance_creation"], au["chance_creation"])
    factors.append(
        {
            "factor": "Chance creation",
            "edge": cre_edge,
            "home": hu["chance_creation"],
            "away": au["chance_creation"],
            "delta": cre_d,
            "impact": abs(cre_d) * 1.3,
            "explanation": (
                f"{_edge_phrase(cre_edge, home_name, away_name)} builds more volume "
                f"(creation {hu['chance_creation']:.2f} vs {au['chance_creation']:.2f})."
            ),
        }
    )

    gk_edge = _winner_side(hu["goalkeeper"], au["goalkeeper"])
    gk_d = _delta(hu["goalkeeper"], au["goalkeeper"])
    factors.append(
        {
            "factor": "Goalkeeper",
            "edge": gk_edge,
            "home": hu["goalkeeper"],
            "away": au["goalkeeper"],
            "delta": gk_d,
            "impact": abs(gk_d) * 1.0,
            "explanation": (
                f"{_edge_phrase(gk_edge, home_name, away_name)} has the stronger keeper "
                f"({hu['goalkeeper']:.2f} vs {au['goalkeeper']:.2f}), shifting expected goals against."
            ),
        }
    )

    def_edge = _winner_side(hu["defence"], au["defence"])
    def_d = _delta(hu["defence"], au["defence"])
    factors.append(
        {
            "factor": "Back-line defence",
            "edge": def_edge,
            "home": hu["defence"],
            "away": au["defence"],
            "delta": def_d,
            "impact": abs(def_d) * 1.0,
            "explanation": (
                f"{_edge_phrase(def_edge, home_name, away_name)} defends better in the back line "
                f"({hu['defence']:.2f} vs {au['defence']:.2f})."
            ),
        }
    )

    middef_edge = _winner_side(hu["midfield_defence"], au["midfield_defence"])
    middef_d = _delta(hu["midfield_defence"], au["midfield_defence"])
    factors.append(
        {
            "factor": "Midfield shield",
            "edge": middef_edge,
            "home": hu["midfield_defence"],
            "away": au["midfield_defence"],
            "delta": middef_d,
            "impact": abs(middef_d) * 0.9,
            "explanation": (
                f"{_edge_phrase(middef_edge, home_name, away_name)} shields the defence better "
                f"(mid-def {hu['midfield_defence']:.2f} vs {au['midfield_defence']:.2f})."
            ),
        }
    )

    trans_edge = _winner_side(hu["transition_risk"], au["transition_risk"], higher_is_better=False)
    trans_d = _delta(hu["transition_risk"], au["transition_risk"])
    factors.append(
        {
            "factor": "Transition risk",
            "edge": trans_edge,
            "home": hu["transition_risk"],
            "away": au["transition_risk"],
            "delta": trans_d,
            "impact": abs(trans_d) * 1.1,
            "explanation": (
                f"{_edge_phrase(trans_edge, home_name, away_name)} is more exposed on the counter "
                f"(transition risk {hu['transition_risk']:.2f} vs {au['transition_risk']:.2f} "
                f"— lower is safer)."
            ),
        }
    )

    h_tc = home_p["extended"].get("team_composites") or {}
    a_tc = away_p["extended"].get("team_composites") or {}
    press_edge = _winner_side(
        float(h_tc.get("pressing_intensity", 0)) - float(a_tc.get("press_resistance", 0)),
        float(a_tc.get("pressing_intensity", 0)) - float(h_tc.get("press_resistance", 0)),
    )
    press_d = _delta(
        float(h_tc.get("pressing_intensity", 0)) - float(a_tc.get("press_resistance", 0)),
        float(a_tc.get("pressing_intensity", 0)) - float(h_tc.get("press_resistance", 0)),
    )
    if abs(press_d) >= 0.04:
        factors.append(
            {
                "factor": "Press vs build-up",
                "edge": press_edge,
                "home": round(float(h_tc.get("pressing_intensity", 0)), 3),
                "away": round(float(a_tc.get("press_resistance", 0)), 3),
                "delta": press_d,
                "impact": abs(press_d) * 0.85,
                "explanation": (
                    f"{_edge_phrase(press_edge, home_name, away_name)} can disrupt the other's build-up "
                    f"(press intensity vs press-resistance edge {press_d:+.2f})."
                ),
            }
        )

    poss_edge = _winner_side(
        home_p["extended"]["possession_control"],
        away_p["extended"]["possession_control"],
    )
    poss_d = _delta(
        home_p["extended"]["possession_control"],
        away_p["extended"]["possession_control"],
    )
    factors.append(
        {
            "factor": "Possession control",
            "edge": poss_edge,
            "home": home_p["extended"]["possession_control"],
            "away": away_p["extended"]["possession_control"],
            "delta": poss_d,
            "impact": abs(poss_d) * 0.7,
            "explanation": (
                f"{_edge_phrase(poss_edge, home_name, away_name)} controls the ball better "
                f"({home_p['extended']['possession_control']:.2f} vs {away_p['extended']['possession_control']:.2f})."
            ),
        }
    )

    fit_edge = _winner_side(
        home_p["extended"]["formation_fit"],
        away_p["extended"]["formation_fit"],
    )
    fit_d = _delta(home_p["extended"]["formation_fit"], away_p["extended"]["formation_fit"])
    factors.append(
        {
            "factor": "Formation fit",
            "edge": fit_edge,
            "home": home_p["extended"]["formation_fit"],
            "away": away_p["extended"]["formation_fit"],
            "delta": fit_d,
            "impact": abs(fit_d) * 0.8,
            "explanation": (
                f"{_edge_phrase(fit_edge, home_name, away_name)} fits the chosen shape better "
                f"(avg fit {home_p['extended']['formation_fit']:.2f} vs {away_p['extended']['formation_fit']:.2f})."
            ),
        }
    )

    ranked = _rank_factors(factors)[:6]

    h_sup = float(mech["home_attacks_vs_away_defence"])
    a_sup = float(mech["away_attacks_vs_home_defence"])
    h_mid = float(mech["midfield_battle"]["home_multiplier"])
    a_mid = float(mech["midfield_battle"]["away_multiplier"])

    h_raw = home_p["extended"]["xg_split"]
    a_raw = away_p["extended"]["xg_split"]

    if favorite:
        margin = "clear" if fav_pct - und_pct > 12 else "moderate" if fav_pct - und_pct > 6 else "slight"
        verdict_summary = (
            f"{favorite} is favoured ({_pct_str(fav_pct)} win vs {_pct_str(und_pct)} for {underdog}, "
            f"{_pct_str(draw)} draw). Expected goals: {home_name} {_fmt(hxg)} – {_fmt(axg)} {away_name}."
        )
    else:
        margin = "balanced"
        verdict_summary = (
            f"Very balanced matchup ({_pct_str(home_win)} / {_pct_str(draw)} / {_pct_str(away_win)}). "
            f"Expected goals: {home_name} {_fmt(hxg)} – {_fmt(axg)} {away_name}."
        )

    top_reasons = [f["explanation"] for f in ranked[:3]]

    season_notes = _season_override_notes(report, home_name, away_name)
    if season_notes:
        sections_season = {
            "title": "Season profiles (prime / pick-season)",
            "paragraphs": season_notes,
            "bullets": [
                "Prime player: entire stat line replaced by their best top-league season (2014-15+).",
                "Pick-season player: stats replaced by the chosen season only (not blended with current form).",
            ],
        }
    else:
        sections_season = None

    sections: list[dict[str, Any]] = [
        {
            "title": "Verdict",
            "paragraphs": [verdict_summary],
            "bullets": top_reasons,
        },
        {
            "title": "Expected goals pipeline",
            "paragraphs": [
                (
                    f"The engine splits attack into finishing and chance-creation channels (xA / xG-buildup / "
                    f"xG-chain credit all outfield positions), then applies opponent suppression "
                    f"(back line 54%, mid shield 32%, GK 14%) and midfield battle modifiers."
                ),
                (
                    f"{home_name} raw attack xG: {_fmt(h_raw['finishing'])} finishing + "
                    f"{_fmt(h_raw['creation'])} creation = {_fmt(h_raw['total_raw'])} before suppression. "
                    f"When {away_name} defends, suppression factor is {_fmt(a_sup, 3)} "
                    f"(DEF {au['defence']:.2f}, mid-def {au['midfield_defence']:.2f}, "
                    f"GK {au['goalkeeper']:.2f}, transition risk {au['transition_risk']:.2f})."
                ),
                (
                    f"{away_name} raw attack xG: {_fmt(a_raw['finishing'])} + {_fmt(a_raw['creation'])} = "
                    f"{_fmt(a_raw['total_raw'])}. {home_name} suppression when defending: {_fmt(h_sup, 3)} "
                    f"(transition risk {hu['transition_risk']:.2f})."
                ),
                (
                    f"Midfield battle multipliers: {home_name} ×{_fmt(h_mid, 3)}, "
                    f"{away_name} ×{_fmt(a_mid, 3)}. "
                    f"Net xG edge: {away_name if xg_diff > 0 else home_name} by {_fmt(abs(xg_diff))}."
                ),
            ],
            "bullets": [],
        },
        {
            "title": "Defensive structure & transitions",
            "paragraphs": [
                (
                    f"{home_name} xGA suppression: {home_p['extended']['xga_suppression']:.3f} "
                    f"(base without transition penalty: {home_p['fullbacks']['xga_suppression_base']:.3f}). "
                    f"{away_name}: {away_p['extended']['xga_suppression']:.3f} "
                    f"(base {away_p['fullbacks']['xga_suppression_base']:.3f})."
                ),
                _fullback_narrative(home_name, home_p["fullbacks"]),
                _fullback_narrative(away_name, away_p["fullbacks"]),
                _wide_matchup_narrative(home_name, away_name, mech.get("wide_matchup") or {}),
                _press_matchup_narrative(home_name, away_name, mech.get("press_matchup") or {}),
            ],
            "bullets": [],
        },
        {
            "title": "Formation & squad fit",
            "paragraphs": [
                _fit_narrative(home_name, matchup["home"]["formation"], home_p),
                _fit_narrative(away_name, matchup["away"]["formation"], away_p),
            ],
            "bullets": [],
        },
    ]
    if sections_season:
        sections.insert(1, sections_season)

    bench_section = _bench_depth_section(report, home_name, away_name)
    if bench_section:
        insert_at = 2 if sections_season else 1
        sections.insert(insert_at, bench_section)

    top_score = ""
    if mc.get("scorelines"):
        top = mc["scorelines"][0]
        top_score = f"Most common scoreline: {top['score']} ({_pct_str(top['pct'])})."
    sections.append(
        {
            "title": "Monte Carlo interpretation",
            "paragraphs": [
                (
                    f"Across {mc['simulations']:,} neutral-venue runs, average scoreline tendency is "
                    f"{_fmt(mc['home_goals_avg'])}–{_fmt(mc['away_goals_avg'])}. "
                    f"Both teams score {_pct_str(mc['btts_pct'])} of the time; over 2.5 goals "
                    f"{_pct_str(mc['over_2_5_pct'])}."
                ),
                top_score or "Outcome spread follows Poisson variance around the expected xG means.",
            ],
            "bullets": [
                f"Trophy boost: {home_name} ×{mc['home_trophy_multiplier']:.3f}, "
                f"{away_name} ×{mc['away_trophy_multiplier']:.3f} (applied in simulation units).",
            ],
        }
    )

    return {
        "favorite": favorite,
        "favorite_side": fav_side,
        "margin": margin,
        "summary": verdict_summary,
        "expected_xg": {"home": hxg, "away": axg, "edge_side": "away" if xg_diff > 0 else "home", "delta": round(abs(xg_diff), 2)},
        "outcomes": {
            "home_win_pct": home_win,
            "draw_pct": draw,
            "away_win_pct": away_win,
        },
        "key_factors": ranked,
        "head_to_head": {
            k: {"home": f["home"], "away": f["away"], "edge": f["edge"]}
            for k, f in zip(
                ["finishing", "chance_creation", "goalkeeper", "defence", "midfield_defence", "transition_risk", "possession", "formation_fit"],
                factors,
            )
        },
        "mechanics_summary": {
            "home_attacks_vs_away_defence": h_sup,
            "away_attacks_vs_home_defence": a_sup,
            "midfield_battle": mech["midfield_battle"],
            "press_matchup": mech.get("press_matchup") or {},
        },
        "sections": sections,
    }


def _bench_depth_section(
    report: dict[str, Any], home_name: str, away_name: str
) -> dict[str, Any] | None:
    bench = report.get("bench_impact") or {}
    home_b = bench.get("home") or {}
    away_b = bench.get("away") or {}
    if not home_b.get("contributed") and not away_b.get("contributed"):
        if (home_b.get("bench_count") or 0) == 0 and (away_b.get("bench_count") or 0) == 0:
            return None

    def _line(side: dict[str, Any], name: str) -> str:
        if not side.get("bench_count"):
            return f"{name}: no bench (11-man squad)."
        if not side.get("contributed"):
            return f"{name}: {side.get('summary', 'bench present but no depth boost applied')}."
        boosts = side.get("boosts") or {}
        standouts = [
            p["player"]
            for p in side.get("players") or []
            if any((p.get("outstanding") or {}).values())
        ]
        names = ", ".join(standouts[:4]) if standouts else "depth"
        return (
            f"{name}: {side.get('summary')} Standouts: {names}. "
            f"Boosts — attack +{boosts.get('attack', 0) * 100:.1f}%, "
            f"creation +{boosts.get('creation', 0) * 100:.1f}%, "
            f"defence +{boosts.get('defence', 0) * 100:.1f}%."
        )

    return {
        "title": "Squad depth (bench impact)",
        "paragraphs": [
            "Non-starters with elite per-90 traits add a small squad-depth multiplier to unit ratings "
            "(capped at ~5% total; bench cannot dominate outcomes).",
            _line(home_b, home_name),
            _line(away_b, away_name),
        ],
        "bullets": [],
    }


def _season_override_notes(report: dict[str, Any], home_name: str, away_name: str) -> list[str]:
    ov = report.get("season_overrides") or {}
    lines: list[str] = []
    for side_key, team_name in (("team_a", home_name), ("team_b", away_name)):
        side = ov.get(side_key) or {}
        prime = side.get("prime")
        peak = side.get("peak_season")
        if prime:
            lines.append(
                f"{team_name} prime: {prime.get('resolved_name', prime.get('requested'))} "
                f"uses peak season {prime.get('season')} (stats fully replaced)."
            )
        if peak:
            lines.append(
                f"{team_name} pick-season: {peak.get('resolved_name', peak.get('requested'))} "
                f"uses {peak.get('season')} only (stats fully replaced)."
            )
    return lines


def _wide_matchup_narrative(home_name: str, away_name: str, wide: dict[str, Any]) -> str:
    parts: list[str] = []
    for side_key, team_name, opp_name in (
        ("home", home_name, away_name),
        ("away", away_name, home_name),
    ):
        row = wide.get(side_key) or {}
        if not row.get("active"):
            continue
        boost_pct = float(row.get("boost", 0)) * 100
        parts.append(
            f"Opposition wing threat vs leaky fullbacks: {team_name}'s wide attack gets a "
            f"+{boost_pct:.1f}% xG edge (winger threat {float(row.get('winger_threat', 0)):.2f}, "
            f"{opp_name} transition risk {float(row.get('transition_risk', 0)):.2f})."
        )
    if not parts:
        return (
            "Wide overload matchup: no extra wing boost — either wing threat or fullback "
            "transition vulnerability is below the activation threshold."
        )
    return " ".join(parts)


def _press_matchup_narrative(home_name: str, away_name: str, press: dict[str, Any]) -> str:
    parts: list[str] = []
    for side_key, team_name, opp_name in (
        ("home", home_name, away_name),
        ("away", away_name, home_name),
    ):
        row = press.get(side_key) or {}
        if not row.get("active"):
            continue
        sup_pct = float(row.get("suppression", 0)) * 100
        parts.append(
            f"Press vs build-up: {team_name}'s press trims {opp_name}'s chance creation by "
            f"~{sup_pct:.1f}% (press {float(row.get('pressing_intensity', 0)):.2f} vs "
            f"resistance {float(row.get('press_resistance', 0)):.2f})."
        )
    if not parts:
        return (
            "Press matchup: evenly matched or strong press-resistance on both sides — "
            "no extra xG suppression from the press battle."
        )
    return " ".join(parts)


def _fullback_narrative(team_name: str, fb: dict[str, Any]) -> str:
    rows = fb.get("fullbacks") or []
    if not rows:
        return f"{team_name} has no wide fullback slots in this formation."
    names = ", ".join(
        f"{r['player']} ({r['slot']}, exposure {r['attack_exposure']:.2f})" for r in rows
    )
    return (
        f"{team_name} fullbacks: {names}. Team transition risk {fb['transition_risk']:.3f} — "
        f"high attacking fullbacks increase counter vulnerability when midfield cover is thin."
    )


def _fit_narrative(team_name: str, formation: str, profile: dict[str, Any]) -> str:
    ext = profile["extended"]
    players = ext.get("formation_fit_players") or []
    weak = [p for p in players if p.get("fit", 1) < 0.55]
    weak_txt = ""
    if weak:
        weak_txt = " Weak slots: " + ", ".join(f"{p['player']} ({p['slot']}, fit {p['fit']:.2f})" for p in weak[:3]) + "."
    return (
        f"{team_name} ({formation}): average formation fit {ext['formation_fit']:.2f}. "
        f"Chance creation index {ext['chance_creation']:.2f}, possession {ext['possession_control']:.2f}."
        f"{weak_txt}"
    )


def _rate_label(value: float, *, high: float = 0.62, low: float = 0.48) -> str | None:
    if value >= high:
        return "strength"
    if value <= low:
        return "weakness"
    return None


# Unit-specific tier thresholds (strength_hi, mod_strength, mod_weakness, weakness_lo).
# Attack-style units use 0–1 scale; midfield/defence slot units use lower absolute ranges.
_UNIT_TIER_THRESHOLDS: dict[str, tuple[float, float, float, float]] = {
    "attack": (0.72, 0.62, 0.48, 0.40),
    "finishing": (0.72, 0.62, 0.48, 0.40),
    "chance_creation": (0.68, 0.58, 0.44, 0.36),
    "goalkeeper": (0.68, 0.58, 0.42, 0.35),
    "midfield": (0.36, 0.32, 0.27, 0.23),
    "defence": (0.26, 0.22, 0.17, 0.14),
    "midfield_defence": (0.18, 0.15, 0.11, 0.08),
    "transition_risk": (0.84, 0.78, 0.66, 0.58),  # inverted: lower risk is better
}

_TEAM_TIER_THRESHOLDS: dict[str, tuple[float, float, float, float]] = {
    "creativity": (0.62, 0.54, 0.42, 0.35),
    "midfield_control": (0.58, 0.50, 0.40, 0.33),
    "possession_control": (0.62, 0.54, 0.42, 0.35),
    "finishing_threat": (0.62, 0.54, 0.42, 0.35),
    "defensive_solidity": (0.58, 0.50, 0.40, 0.33),
    "attacking_effectiveness": (0.62, 0.54, 0.42, 0.35),
}

_CRITICAL_SLOTS = frozenset(
    {"GK", "RB", "LB", "RWB", "LWB", "CB1", "CB2", "CB3", "DM", "DM1", "DM2", "ST", "ST1", "ST2"}
)


def _classify_tier(
    value: float,
    thresholds: tuple[float, float, float, float],
    *,
    higher_better: bool = True,
) -> Tier:
    hi, mod_hi, mod_lo, lo = thresholds
    v = value if higher_better else 1.0 - value
    if v >= hi:
        return "strength"
    if v >= mod_hi:
        return "moderate_strength"
    if v <= lo:
        return "weakness"
    if v <= mod_lo:
        return "moderate_weakness"
    return "balanced"


def _tier_label_text(tier: Tier) -> str:
    return {
        "strength": "Strength",
        "moderate_strength": "Moderate strength",
        "balanced": "Balanced",
        "moderate_weakness": "Moderate weakness",
        "weakness": "Weakness",
    }[tier]


def _tier_item(tier: Tier, text: str) -> dict[str, str]:
    return {"tier": tier, "text": text}


def _slot_fit_tier(fit: float) -> Tier | None:
    if fit < 0.42:
        return "weakness"
    if fit < 0.50:
        return "moderate_weakness"
    if fit >= 0.72:
        return "strength"
    if fit >= 0.62:
        return "moderate_strength"
    return None


def _slot_area_label(slot: str) -> str:
    role = slot_role(slot)
    if role in {"fullback", "centre_back"}:
        return "defence"
    if role in {"dm", "cm", "am"}:
        return "midfield"
    if role in {"winger", "striker", "am"}:
        return "attack"
    if role == "gk":
        return "goalkeeper"
    return "formation fit"


def _collect_slot_fit_labels(fit_players: list[dict[str, Any]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for p in fit_players:
        fit = float(p.get("fit", 1))
        tier = _slot_fit_tier(fit)
        if tier is None:
            continue
        slot = p.get("slot", "?")
        player = p.get("player", "?")
        area = _slot_area_label(slot)
        if tier == "weakness":
            text = f"Misfit at {slot}: {player} (fit {fit:.2f}) — glaring {area} concern."
        elif tier == "moderate_weakness":
            text = f"Awkward at {slot}: {player} (fit {fit:.2f}) — slight {area} concern."
        elif tier == "strength":
            text = f"Elite fit at {slot}: {player} (fit {fit:.2f})."
        else:
            text = f"Good fit at {slot}: {player} (fit {fit:.2f})."
        items.append(_tier_item(tier, text))
    return items


def _unit_tier_label(label: str, key: str, value: float, *, higher_better: bool = True) -> dict[str, str] | None:
    if value <= 0.001 and key != "transition_risk":
        return None
    thresholds = _UNIT_TIER_THRESHOLDS.get(key, (0.68, 0.58, 0.45, 0.38))
    tier = _classify_tier(value, thresholds, higher_better=higher_better)
    if tier == "balanced":
        return None
    val_txt = f"{value:.2f}"
    if key == "transition_risk":
        val_txt = f"{value:.2f} (lower is safer)"
    phrases = {
        "strength": f"Elite {label.lower()} ({val_txt}).",
        "moderate_strength": f"Solid {label.lower()} ({val_txt}).",
        "moderate_weakness": f"Slight {label.lower()} concern ({val_txt}).",
        "weakness": f"Thin {label.lower()} ({val_txt}).",
    }
    return _tier_item(tier, phrases[tier])


def _team_tier_label(label: str, key: str, value: float) -> dict[str, str] | None:
    thresholds = _TEAM_TIER_THRESHOLDS.get(key, (0.62, 0.54, 0.42, 0.35))
    tier = _classify_tier(value, thresholds)
    if tier == "balanced":
        return None
    val_txt = f"{value:.2f}"
    phrases = {
        "strength": f"Team {label.lower()} stands out ({val_txt}).",
        "moderate_strength": f"Team {label.lower()} slightly above average ({val_txt}).",
        "moderate_weakness": f"Team {label.lower()} slightly below average ({val_txt}).",
        "weakness": f"Team {label.lower()} is a concern ({val_txt}).",
    }
    return _tier_item(tier, phrases[tier])


def _group_tier_items(items: list[dict[str, str]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {
        "strength": [],
        "moderate_strength": [],
        "balanced": [],
        "moderate_weakness": [],
        "weakness": [],
    }
    for item in items:
        grouped[item["tier"]].append(item["text"])
    return grouped


def _prioritize_tier_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep the most actionable labels — slot-fit and glaring issues first."""
    priority = {"weakness": 0, "moderate_weakness": 1, "strength": 2, "moderate_strength": 3, "balanced": 4}
    ranked = sorted(items, key=lambda i: (priority.get(i["tier"], 9), "misfit" not in i["text"].lower(), i["text"]))
    kept: list[dict[str, str]] = []
    areas_covered: set[str] = set()

    def _area_key(text: str) -> str | None:
        lower = text.lower()
        for area in ("defence", "midfield", "attack", "goalkeeper", "creation", "finishing", "transition"):
            if area in lower:
                return area
        return None

    for item in ranked:
        tier = item["tier"]
        if tier in {"weakness", "moderate_weakness"}:
            if len([k for k in kept if k["tier"] in {"weakness", "moderate_weakness"}]) >= 6:
                continue
            area = _area_key(item["text"])
            if area and area in areas_covered and "misfit" not in item["text"].lower():
                continue
            if area:
                areas_covered.add(area)
        if tier in {"strength", "moderate_strength"}:
            if len([k for k in kept if k["tier"] in {"strength", "moderate_strength"}]) >= 5:
                continue
        kept.append(item)
    return kept


def _legacy_strengths_weaknesses(grouped: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    strengths = grouped["strength"] + grouped["moderate_strength"]
    weaknesses = grouped["weakness"] + grouped["moderate_weakness"]
    if not strengths:
        strengths = ["Balanced squad without a standout elite unit — outcomes depend on matchups."]
    if not weaknesses:
        weaknesses = ["No glaring structural weaknesses detected."]
    return strengths[:6], weaknesses[:6]


def _analyze_single_squad(
    team_name: str,
    formation: str,
    profile: dict[str, Any],
    bench: dict[str, Any] | None,
) -> dict[str, Any]:
    """Per-team strengths, weaknesses, and unit breakdown for squad display."""
    ext = profile["extended"]
    u = ext["units"]
    tc = ext.get("team_composites") or {}
    fb = profile.get("fullbacks") or {}
    fit_players = ext.get("formation_fit_players") or []

    tier_items: list[dict[str, str]] = []
    sections: list[dict[str, Any]] = []

    for label, key, higher_better in (
        ("Attack", "attack", True),
        ("Finishing", "finishing", True),
        ("Chance creation", "chance_creation", True),
        ("Midfield", "midfield", True),
        ("Defence", "defence", True),
        ("Midfield shield", "midfield_defence", True),
        ("Goalkeeper", "goalkeeper", True),
        ("Transition safety", "transition_risk", False),
    ):
        val = float(u.get(key, 0))
        if key == "transition_risk" and val <= 0.001 and not fb.get("fullbacks"):
            continue
        item = _unit_tier_label(label, key, val, higher_better=higher_better)
        if item:
            tier_items.append(item)

    for label, key in (
        ("Creativity", "creativity"),
        ("Midfield control", "midfield_control"),
        ("Possession control", "possession_control"),
        ("Finishing threat", "finishing_threat"),
        ("Defensive solidity", "defensive_solidity"),
        ("Press resistance", "press_resistance"),
        ("Pressing intensity", "pressing_intensity"),
    ):
        val = float(tc.get(key, 0))
        item = _team_tier_label(label, key, val)
        if item:
            tier_items.append(item)

    tier_items.extend(_collect_slot_fit_labels(fit_players))

    if u.get("gk_is_backup"):
        tier_items.append(_tier_item("weakness", "Starting goalkeeper profile looks like a backup/low-minutes option."))

    if float(u.get("transition_risk", 0)) >= 0.38:
        fb_note = ""
        if fb.get("fullbacks"):
            top_exposure = max((r.get("attack_exposure", 0) for r in fb["fullbacks"]), default=0)
            if top_exposure >= 0.45:
                fb_note = " — elite opposition wingers can exploit wide overloads."
        tier_items.append(
            _tier_item(
                "weakness",
                f"High transition risk ({u['transition_risk']:.2f}) — vulnerable on the counter{fb_note}",
            )
        )
    elif float(u.get("transition_risk", 0)) >= 0.28:
        tier_items.append(
            _tier_item("moderate_weakness", f"Elevated transition risk ({u['transition_risk']:.2f}).")
        )

    bench = bench or {}
    bench_count = bench.get("bench_count") or 0
    if bench_count == 0:
        tier_items.append(_tier_item("moderate_weakness", "No squad depth on the bench."))
    elif bench.get("contributed"):
        standouts = [
            p["player"]
            for p in bench.get("players") or []
            if any((p.get("outstanding") or {}).values())
        ]
        if standouts:
            tier_items.append(
                _tier_item("moderate_strength", f"Useful bench depth ({', '.join(standouts[:3])}).")
            )

    if ext["formation_fit"] >= 0.72:
        tier_items.append(
            _tier_item("strength", f"Players suit the {formation} shape (avg fit {ext['formation_fit']:.2f}).")
        )

    tier_items = _prioritize_tier_items(tier_items)
    grouped = _group_tier_items(tier_items)
    strengths, weaknesses = _legacy_strengths_weaknesses(grouped)

    attack_bullets = [
        f"Attacking effectiveness {ext['attacking_effectiveness']:.2f} (whole XI).",
        f"Unit attack {u['attack']:.2f}; finishing {u['finishing']:.2f}; creation {u['chance_creation']:.2f}.",
        f"Raw xG split: finishing {ext['xg_split']['finishing']:.2f} + creation {ext['xg_split']['creation']:.2f}.",
    ]
    sections.append({"title": "Attack", "bullets": attack_bullets})

    mid_bullets = [
        f"Midfield unit (DM/CM/AM slots) {u['midfield']:.2f}; team midfield control {tc.get('midfield_control', 0):.2f}.",
        f"Possession control {ext['possession_control']:.2f}; pass completion avg {ext.get('avg_pass_pct', 0):.1f}%.",
        f"Pressing intensity {ext.get('pressing_intensity', 0):.2f}; press resistance {ext.get('press_resistance', tc.get('press_resistance', 0)):.2f}.",
    ]
    sections.append({"title": "Midfield", "bullets": mid_bullets})

    def_bullets = [
        f"Back-line unit {u['defence']:.2f}; midfield shield {u['midfield_defence']:.2f}.",
        f"Team defensive solidity {tc.get('defensive_solidity', 0):.2f}; aerial defence {tc.get('aerial_defence', 0):.2f}; xGA suppression {ext['xga_suppression']:.3f}.",
        f"Transition risk {u['transition_risk']:.2f} (lower is safer).",
    ]
    if fb.get("fullbacks"):
        fb_names = ", ".join(f"{r['player']} ({r['slot']})" for r in fb["fullbacks"][:2])
        def_bullets.append(f"Wide defenders: {fb_names}.")
    sections.append({"title": "Defence", "bullets": def_bullets})

    weak_slots = [p for p in fit_players if p.get("fit", 1) < 0.55]
    fit_bullets = [
        f"Average formation fit {ext['formation_fit']:.2f} in {formation}.",
    ]
    if weak_slots:
        weak_txt = ", ".join(f"{p['player']} at {p['slot']} (fit {p['fit']:.2f})" for p in weak_slots[:4])
        fit_bullets.append(f"Misplaced or awkward slots: {weak_txt}.")
    else:
        fit_bullets.append("No major formation-fit concerns in the starting XI.")
    sections.append({"title": "Formation fit", "bullets": fit_bullets})

    depth_bullets: list[str] = []
    if bench_count == 0:
        depth_bullets.append("No bench listed — depth multiplier not applied.")
    elif bench.get("contributed"):
        boosts = bench.get("boosts") or {}
        depth_bullets.append(bench.get("summary") or "Bench adds a small depth boost.")
        depth_bullets.append(
            f"Depth boosts: attack +{boosts.get('attack', 0) * 100:.1f}%, "
            f"creation +{boosts.get('creation', 0) * 100:.1f}%, "
            f"defence +{boosts.get('defence', 0) * 100:.1f}%."
        )
        standouts = [
            p["player"]
            for p in bench.get("players") or []
            if any((p.get("outstanding") or {}).values())
        ]
        if standouts:
            depth_bullets.append(f"Standout bench options: {', '.join(standouts[:4])}.")
    else:
        depth_bullets.append(bench.get("summary") or "Bench present but no elite depth traits detected.")
    sections.append({"title": "Squad depth", "bullets": depth_bullets})

    team_profile_bullets = [
        f"Creativity {tc.get('creativity', 0):.2f} · Midfield control {tc.get('midfield_control', 0):.2f} · "
        f"Possession {tc.get('possession_control', 0):.2f}.",
        f"Finishing threat {tc.get('finishing_threat', 0):.2f} · Defensive solidity {tc.get('defensive_solidity', 0):.2f}.",
        f"Pressing {tc.get('pressing_intensity', 0):.2f} · Press resistance {tc.get('press_resistance', 0):.2f} · "
        f"Team profile overall {tc.get('overall', 0):.2f}.",
    ]
    sections.append({"title": "Team profile", "bullets": team_profile_bullets})

    summary_parts = grouped["strength"][:1] + grouped["weakness"][:1]
    summary = f"{team_name}: " + ("; ".join(summary_parts) if summary_parts else "Balanced profile across units.")

    return {
        "name": team_name,
        "formation": formation,
        "summary": summary,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "tier_labels": grouped,
        "sections": sections,
        "units": {k: round(float(v), 3) if isinstance(v, (int, float)) else v for k, v in u.items()},
        "team_composites": {k: round(float(v), 3) for k, v in tc.items()},
    }


def build_squad_strengths_report(report: dict[str, Any]) -> dict[str, Any]:
    """Highlight each side's squad strengths and weaknesses."""
    matchup = report["matchup"]
    bench = report.get("bench_impact") or {}
    return {
        "home": _analyze_single_squad(
            matchup["home"]["name"],
            matchup["home"]["formation"],
            report["profiles"]["home"],
            bench.get("home"),
        ),
        "away": _analyze_single_squad(
            matchup["away"]["name"],
            matchup["away"]["formation"],
            report["profiles"]["away"],
            bench.get("away"),
        ),
    }


def analyze_team_squad(
    team_name: str,
    formation: str,
    profile: dict[str, Any],
    bench: dict[str, Any] | None,
) -> dict[str, Any]:
    """Public wrapper for single-team squad evaluation."""
    return _analyze_single_squad(team_name, formation, profile, bench)


_SCOUT_COMPARE_UNITS: tuple[tuple[str, str, bool], ...] = (
    ("Attack", "attack", True),
    ("Finishing", "finishing", True),
    ("Chance creation", "chance_creation", True),
    ("Midfield (slots)", "midfield", True),
    ("Defence", "defence", True),
    ("Midfield shield", "midfield_defence", True),
    ("Goalkeeper", "goalkeeper", True),
    ("Transition safety", "transition_risk", False),
)

_SCOUT_COMPARE_TEAM: tuple[tuple[str, str, bool], ...] = (
    ("Creativity", "creativity", True),
    ("Midfield control", "midfield_control", True),
    ("Possession control", "possession_control", True),
    ("Finishing threat", "finishing_threat", True),
    ("Defensive solidity", "defensive_solidity", True),
    ("Pressing intensity", "pressing_intensity", True),
    ("Press resistance", "press_resistance", True),
)


def _scout_compare_block(
    label: str,
    my_vals: dict[str, float],
    opp_vals: dict[str, float],
    fields: tuple[tuple[str, str, bool], ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for area, key, higher_better in fields:
        my_v = float(my_vals.get(key, 0))
        opp_v = float(opp_vals.get(key, 0))
        edge = _scout_edge(my_v, opp_v, higher_better=higher_better)
        rows.append(
            {
                "area": area,
                "verdict": edge,
                "my_value": round(my_v, 3),
                "opp_value": round(opp_v, 3),
                "summary": _scout_verdict_text(area, edge),
            }
        )
    return rows


def _scout_edge(my_val: float, opp_val: float, *, higher_better: bool = True) -> str:
    diff = (my_val - opp_val) if higher_better else (opp_val - my_val)
    if diff >= 0.06:
        return "advantage"
    if diff <= -0.06:
        return "disadvantage"
    return "even"


def _scout_verdict_text(area: str, edge: str) -> str:
    area_l = area.lower()
    if edge == "advantage":
        return f"Your {area_l} profile looks stronger than theirs."
    if edge == "disadvantage":
        return f"Their {area_l} looks stronger than yours."
    return f"{area} looks evenly matched."


def build_scout_report(
    my_eval: dict[str, Any],
    opponent_eval: dict[str, Any],
    *,
    my_team: dict[str, Any],
    opponent_team: dict[str, Any],
) -> dict[str, Any]:
    """
    Limited opponent scout: expected lineup/shape and comparative unit scouting.
    No score predictions, win probabilities, or xG totals.
    """
    my_u = my_eval.get("units") or {}
    opp_u = opponent_eval.get("units") or {}
    my_tc = my_eval.get("team_composites") or {}
    opp_tc = opponent_eval.get("team_composites") or {}

    unit_comparisons = _scout_compare_block("units", my_u, opp_u, _SCOUT_COMPARE_UNITS)
    team_comparisons = _scout_compare_block("team", my_tc, opp_tc, _SCOUT_COMPARE_TEAM)

    opp_meta = opponent_team.get("sheet_meta") or {}
    roster = opp_meta.get("full_roster") or []
    bench = opponent_team.get("bench") or opp_meta.get("bench_players") or []

    scout_notes: list[str] = []
    opp_tiers = opponent_eval.get("tier_labels") or {}
    for s in (opp_tiers.get("strength") or [])[:2]:
        scout_notes.append(f"They look strong: {s.rstrip('.')}.")
    for s in (opp_tiers.get("moderate_strength") or [])[:1]:
        scout_notes.append(f"Solid area: {s.rstrip('.')}.")
    for w in (opp_tiers.get("weakness") or [])[:2]:
        scout_notes.append(f"Possible weakness: {w.rstrip('.')}.")
    for w in (opp_tiers.get("moderate_weakness") or [])[:1]:
        scout_notes.append(f"Slight concern: {w.rstrip('.')}.")

    fit_section = next(
        (sec for sec in (opponent_eval.get("sections") or []) if sec.get("title") == "Formation fit"),
        None,
    )
    if fit_section and fit_section.get("bullets"):
        scout_notes.append(fit_section["bullets"][0])

    my_press = float(my_tc.get("pressing_intensity", 0))
    my_resist = float(my_tc.get("press_resistance", 0))
    opp_press = float(opp_tc.get("pressing_intensity", 0))
    opp_resist = float(opp_tc.get("press_resistance", 0))
    if opp_press - my_resist >= 0.06:
        scout_notes.append(
            f"Their press ({opp_press:.2f}) may trouble your build-up (your press-resistance {my_resist:.2f})."
        )
    elif my_press - opp_resist >= 0.06:
        scout_notes.append(
            f"Your press ({my_press:.2f}) can disrupt their build-up (their press-resistance {opp_resist:.2f})."
        )

    return {
        "limited": True,
        "my_team": my_team.get("name") or my_eval.get("name"),
        "opponent": opponent_team.get("name") or opponent_eval.get("name"),
        "formation": opponent_team.get("formation") or opponent_eval.get("formation"),
        "expected_lineup": opponent_team.get("lineup") or [],
        "opponent_units": opp_u,
        "opponent_team_composites": opp_tc,
        "my_units": my_u,
        "my_team_composites": my_tc,
        "roster_overview": {
            "starting_xi": [
                (row.get("player") or "").strip()
                for row in (opponent_team.get("lineup") or [])
                if (row.get("player") or "").strip()
            ],
            "bench": list(bench),
            "squad_size": opp_meta.get("squad_size") or len(roster) or len(bench) + 11,
        },
        "unit_comparisons": unit_comparisons,
        "team_comparisons": team_comparisons,
        "comparisons": unit_comparisons,
        "scout_notes": scout_notes[:6],
        "summary": (
            f"Scout report on {opponent_eval.get('name')}: "
            f"expected {opponent_eval.get('formation')} shape. "
            "Unit ratings (slot-pure) and team profile (whole XI) shown separately — "
            "no simulated scorelines or win odds."
        ),
    }
