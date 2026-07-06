"""Generate human-readable matchup analysis explaining simulation outcomes."""
from __future__ import annotations

from typing import Any


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
            "impact": abs(gk_d) * 1.5,
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
                    f"The engine splits attack into finishing and chance-creation channels, then applies "
                    f"opponent suppression and midfield battle modifiers."
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
