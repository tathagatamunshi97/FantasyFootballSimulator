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


def _safe_pct(numerator: Any, denominator: Any) -> float | None:
    """A single match's own ratio (e.g. shot conversion), not gated by a
    minimum sample -- unlike tournament.py's leaderboard version, reporting
    "1 goal from 2 shots" for the match that actually happened is normal;
    a qualification minimum only matters when ranking across many matches.
    """
    try:
        num = float(numerator or 0)
        den = float(denominator or 0)
    except (TypeError, ValueError):
        return None
    if den <= 0:
        return None
    return round(num / den * 100, 1)


def _compute_ppda(match_log: dict[str, Any] | None) -> tuple[float | None, float | None]:
    """Same formula as tournament.py's team_ppda_board / web/tournament.py's
    complete_from_board -- opponent's zone-eligible pass attempts over this
    side's own zone-eligible defensive actions. None until a side has made
    at least one qualifying defensive action.
    """
    ml = match_log if isinstance(match_log, dict) else {}
    counts = ml.get("counts") if isinstance(ml.get("counts"), dict) else {}
    hc = counts.get("home") if isinstance(counts.get("home"), dict) else {}
    ac = counts.get("away") if isinstance(counts.get("away"), dict) else {}
    home_actions = float(hc.get("ppda_actions") or 0)
    away_actions = float(ac.get("ppda_actions") or 0)
    home_ppda = round(float(ac.get("ppda_passes") or 0) / home_actions, 1) if home_actions else None
    away_ppda = round(float(hc.get("ppda_passes") or 0) / away_actions, 1) if away_actions else None
    return home_ppda, away_ppda


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
    projection = report["projection"]
    mech = report["mechanics"]
    hxg = float(projection["expected_xg"]["home"])
    axg = float(projection["expected_xg"]["away"])
    xg_diff = axg - hxg

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

    top_reasons = [f["explanation"] for f in ranked[:3]]
    verdict_summary = (
        f"Expected goals: {home_name} {_fmt(hxg)} – {_fmt(axg)} {away_name}. "
        + (top_reasons[0] if top_reasons else "Both squads rate closely across units.")
    )

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

    return {
        "summary": verdict_summary,
        "expected_xg": {"home": hxg, "away": axg, "edge_side": "away" if xg_diff > 0 else "home", "delta": round(abs(xg_diff), 2)},
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
    if (home_b.get("bench_count") or 0) == 0 and (away_b.get("bench_count") or 0) == 0:
        return None

    def _line(side: dict[str, Any], name: str) -> str:
        if not side.get("bench_count"):
            return f"{name}: no bench (11-man squad)."
        standouts = [
            p["player"]
            for p in side.get("players") or []
            if any((p.get("outstanding") or {}).values())
        ]
        if not standouts:
            return f"{name}: {side.get('summary', 'bench present, no standout depth')}."
        names = ", ".join(standouts[:4])
        return f"{name}: {side.get('summary')} Standouts: {names}."

    return {
        "title": "Squad depth",
        "paragraphs": [
            "Non-starters with elite per-90 traits — shown for information only; "
            "bench quality has no effect on ratings or match outcomes.",
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

# Percentile-vs-league tier bands (0-100 scale). Reused across every unit
# and team-composite: percentile is always "higher = better" by construction
# (a lower-is-better raw metric like transition_risk gets inverted before
# this point), unlike the absolute _UNIT_TIER_THRESHOLDS above where every
# metric needed its own hand-tuned cutoff on a different natural scale.
_PERCENTILE_TIER_THRESHOLDS: tuple[float, float, float, float] = (85.0, 65.0, 35.0, 15.0)

# Below this many teams, a percentile is more noise than signal (e.g. "3rd
# of 4" swings wildly on one bad week) -- fall back to the absolute
# thresholds instead of reporting a shaky rank.
_MIN_LEAGUE_SIZE_FOR_PERCENTILE = 4


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _drivers_phrase(rows: list[dict[str, Any]] | None, *, n: int = 2) -> str:
    """'lowest: Kanté (0.31), Vitinha (0.38)' from a breakdown list (already sorted ascending)."""
    if not rows:
        return ""
    picked = rows[:n]
    parts = ", ".join(f"{r['player']} ({r['score']:.2f})" for r in picked)
    return f" — lowest: {parts}"


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


def _unit_tier_label(
    label: str,
    key: str,
    value: float,
    *,
    higher_better: bool = True,
    percentile: float | None = None,
    league_size: int = 0,
    drivers: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if value <= 0.001 and key != "transition_risk":
        return None
    val_txt = f"{value:.2f}"
    if key == "transition_risk":
        val_txt = f"{value:.2f} (lower is safer)"

    use_pct = percentile is not None and league_size >= _MIN_LEAGUE_SIZE_FOR_PERCENTILE
    if use_pct:
        tier = _classify_tier(percentile, _PERCENTILE_TIER_THRESHOLDS, higher_better=True)
        pct_txt = f"{_ordinal(round(percentile))} percentile of {league_size}"
        val_txt = f"{pct_txt}, {val_txt}"
    else:
        thresholds = _UNIT_TIER_THRESHOLDS.get(key, (0.68, 0.58, 0.45, 0.38))
        tier = _classify_tier(value, thresholds, higher_better=higher_better)
    if tier == "balanced":
        return None

    drv_txt = _drivers_phrase(drivers) if tier in ("weakness", "moderate_weakness") else ""
    phrases = {
        "strength": f"Elite {label.lower()} ({val_txt}).",
        "moderate_strength": f"Solid {label.lower()} ({val_txt}).",
        "moderate_weakness": f"Slight {label.lower()} concern ({val_txt}){drv_txt}.",
        "weakness": f"Thin {label.lower()} ({val_txt}){drv_txt}.",
    }
    return _tier_item(tier, phrases[tier])


def _team_tier_label(
    label: str,
    key: str,
    value: float,
    *,
    percentile: float | None = None,
    league_size: int = 0,
    drivers: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    val_txt = f"{value:.2f}"
    use_pct = percentile is not None and league_size >= _MIN_LEAGUE_SIZE_FOR_PERCENTILE
    if use_pct:
        tier = _classify_tier(percentile, _PERCENTILE_TIER_THRESHOLDS, higher_better=True)
        val_txt = f"{_ordinal(round(percentile))} percentile of {league_size}, {val_txt}"
    else:
        thresholds = _TEAM_TIER_THRESHOLDS.get(key, (0.62, 0.54, 0.42, 0.35))
        tier = _classify_tier(value, thresholds)
    if tier == "balanced":
        return None

    drv_txt = _drivers_phrase(drivers) if tier in ("weakness", "moderate_weakness") else ""
    phrases = {
        "strength": f"Team {label.lower()} stands out ({val_txt}).",
        "moderate_strength": f"Team {label.lower()} slightly above average ({val_txt}).",
        "moderate_weakness": f"Team {label.lower()} slightly below average ({val_txt}){drv_txt}.",
        "weakness": f"Team {label.lower()} is a concern ({val_txt}){drv_txt}.",
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
    ranked = sorted(items, key=lambda i: (priority.get(i["tier"], 9), i["text"]))
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
            if area and area in areas_covered:
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
    *,
    percentiles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Per-team strengths, weaknesses, and unit breakdown for squad display."""
    ext = profile["extended"]
    u = ext["units"]
    tc = ext.get("team_composites") or {}
    fb = profile.get("fullbacks") or {}
    fit_players = ext.get("formation_fit_players") or []
    unit_breakdown = u.get("breakdown") or {}
    composite_breakdown = tc.get("breakdown") or {}
    pct_by_key = (percentiles or {}).get("by_key") or {}
    league_size = (percentiles or {}).get("league_size", 0)

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
        item = _unit_tier_label(
            label,
            key,
            val,
            higher_better=higher_better,
            percentile=pct_by_key.get(key),
            league_size=league_size,
            drivers=unit_breakdown.get(key),
        )
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
        item = _team_tier_label(
            label,
            key,
            val,
            percentile=pct_by_key.get(key),
            league_size=league_size,
            drivers=composite_breakdown.get(key),
        )
        if item:
            tier_items.append(item)

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
    elif bench.get("has_standouts"):
        standouts = [
            p["player"]
            for p in bench.get("players") or []
            if any((p.get("outstanding") or {}).values())
        ]
        if standouts:
            tier_items.append(
                _tier_item("moderate_strength", f"Useful bench depth ({', '.join(standouts[:3])}).")
            )

    tier_items = _prioritize_tier_items(tier_items)
    grouped = _group_tier_items(tier_items)
    strengths, weaknesses = _legacy_strengths_weaknesses(grouped)

    defence_bullets: list[str] = []
    cb_players = [p for p in fit_players if str(p.get("slot", "")).endswith("CB")]
    if cb_players:
        cb_names = ", ".join(p["player"] for p in cb_players[:3])
        defence_bullets.append(f"Centre-backs: {cb_names}.")
    if fb.get("fullbacks"):
        fb_names = ", ".join(f"{r['player']} ({r['slot']})" for r in fb["fullbacks"][:2])
        defence_bullets.append(f"Wide defenders: {fb_names}.")
    if defence_bullets:
        sections.append({"title": "Defence", "bullets": defence_bullets})

    depth_bullets: list[str] = []
    if bench_count == 0:
        depth_bullets.append("No bench listed.")
    elif bench.get("has_standouts"):
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
        "team_composites": {k: round(float(v), 3) if isinstance(v, (int, float)) else v for k, v in tc.items()},
        "percentiles": pct_by_key,
        "league_size": league_size,
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
    *,
    percentiles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Public wrapper for single-team squad evaluation."""
    return _analyze_single_squad(team_name, formation, profile, bench, percentiles=percentiles)


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


def build_tactical_matchup(scout_report: dict[str, Any]) -> dict[str, Any]:
    """Turns the scout report's per-area advantage/disadvantage rows into a
    football conclusion, not just a longer list of numbers: your biggest
    edge, their biggest edge, and the two areas most worth building a plan
    around. Pure synthesis of unit_comparisons/team_comparisons the scout
    report already computed -- no new stats.
    """
    rows = (scout_report.get("unit_comparisons") or []) + (scout_report.get("team_comparisons") or [])
    if not rows:
        return {}

    def _gap(r: dict[str, Any]) -> float:
        return abs(float(r.get("my_value") or 0) - float(r.get("opp_value") or 0))

    advantages = sorted((r for r in rows if r["verdict"] == "advantage"), key=_gap, reverse=True)
    disadvantages = sorted((r for r in rows if r["verdict"] == "disadvantage"), key=_gap, reverse=True)

    top_adv = advantages[0] if advantages else None
    top_dis = disadvantages[0] if disadvantages else None

    result: dict[str, Any] = {
        "my_biggest_advantage": top_adv["area"] if top_adv else None,
        "their_biggest_advantage": top_dis["area"] if top_dis else None,
        "exploit_route": None,
        "key_concern": None,
    }
    if top_adv:
        result["exploit_route"] = (
            f"Lean on {top_adv['area'].lower()} — you have a real edge there "
            f"({num_str(top_adv['my_value'])} vs {num_str(top_adv['opp_value'])})."
        )
    if top_dis:
        result["key_concern"] = (
            f"Their {top_dis['area'].lower()} is the bigger threat — "
            f"({num_str(top_dis['opp_value'])} vs {num_str(top_dis['my_value'])}) — plan to limit it."
        )
    # A second-tier advantage/concern rounds the story out without repeating the top one.
    if len(advantages) > 1:
        result["secondary_advantage"] = advantages[1]["area"]
    if len(disadvantages) > 1:
        result["secondary_concern"] = disadvantages[1]["area"]
    return result


def num_str(v: Any) -> str:
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


def normalize_board_events(
    board_events: list[dict[str, Any]] | None,
    match_log: list[dict[str, Any]] | dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Accept a flat event list, or a match_log dict with events/goals from the tactic board."""
    raw: list[Any] = []
    if isinstance(board_events, list) and board_events:
        raw = list(board_events)
    elif isinstance(match_log, dict):
        ev = match_log.get("events")
        goals = match_log.get("goals")
        if isinstance(ev, list) and ev:
            raw = list(ev)
        elif isinstance(goals, list) and goals:
            raw = [
                {
                    "type": "goal",
                    "side": g.get("side"),
                    "minute": g.get("minute"),
                    "player": g.get("player") or g.get("player_short"),
                }
                for g in goals
                if isinstance(g, dict)
            ]
    elif isinstance(match_log, list):
        raw = list(match_log)

    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        et = str(row.get("type") or row.get("event") or "").strip().lower()
        if not et:
            continue
        item = dict(row)
        item["type"] = et
        out.append(item)
    return out


# Back-compat alias used internally
_normalize_board_events = normalize_board_events


def _what_worked_section(
    report: dict[str, Any],
    home_name: str,
    away_name: str,
    home_goals: int,
    away_goals: int,
    events: list[dict[str, Any]],
    match_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Per-team: what worked / what didn't from board counts + unit edges."""
    home_p = report["profiles"]["home"]
    away_p = report["profiles"]["away"]
    hu = _units(home_p)
    au = _units(away_p)
    counts = {}
    if isinstance(match_log, dict):
        counts = match_log.get("counts") or {}
    hc = counts.get("home") if isinstance(counts.get("home"), dict) else {}
    ac = counts.get("away") if isinstance(counts.get("away"), dict) else {}
    home_ppda, away_ppda = _compute_ppda(match_log)

    def _n(bucket: dict, key: str) -> int:
        try:
            return int(bucket.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    def _side_bullets(name: str, side: str, u: dict, c: dict, goals: int, conceded: int, side_ppda: float | None) -> list[str]:
        out: list[str] = []
        shots = _n(c, "shots")
        big = _n(c, "big_chances")
        broken = _n(c, "passes_broken")
        turnovers = _n(c, "turnovers")
        dribbles = _n(c, "dribbles_won")
        offs = _n(c, "offsides")
        poss = _n(c, "possessions")
        saves_against = _n(ac if side == "home" else hc, "saves")
        side_xg = 0.0
        try:
            xg_map = {}
            if isinstance(match_log, dict):
                xg_map = match_log.get("xg") or match_log.get("live_xg") or {}
            if isinstance(xg_map, dict) and xg_map.get(side) is not None:
                side_xg = float(xg_map[side])
            elif c.get("xg") is not None:
                side_xg = float(c.get("xg") or 0)
        except (TypeError, ValueError):
            side_xg = 0.0
        side_poss_pct = None
        try:
            poss_map = {}
            if isinstance(match_log, dict):
                poss_map = match_log.get("possession_pct") or match_log.get("possession") or {}
            if isinstance(poss_map, dict) and poss_map.get(side) is not None:
                side_poss_pct = float(poss_map[side])
        except (TypeError, ValueError):
            side_poss_pct = None

        if goals > conceded:
            out.append(f"Worked: finishing moments — {name} scored {goals} and came out ahead.")
        elif goals and goals == conceded:
            out.append(f"Worked in spells: {name} found the net ({goals}) but could not separate.")
        elif goals == 0 and conceded and big < 2:
            out.append(f"Didn't work: {name} were blanked while conceding {conceded}.")

        if side_xg >= 0.8 and goals == 0:
            out.append(f"Didn't work: ~{side_xg:.2f} xG without converting.")
        elif side_xg >= 1.0 and goals > 0:
            out.append(f"Worked: chance volume (~{side_xg:.2f} xG) backed the attack.")

        # Conversion/passing stats project -- straight off the board counts
        # this session added (shots/big_chances/big_chance_goals/passes).
        shot_conv = _safe_pct(goals, shots)
        if shot_conv is not None and shots >= 3:
            if shot_conv <= 20:
                out.append(f"Didn't work: wasteful in front of goal — {_pct_str(shot_conv)} shot conversion from {shots} shots.")
            elif shot_conv >= 50:
                out.append(f"Worked: clinical finishing — {_pct_str(shot_conv)} shot conversion from {shots} shots.")
        bc_goals = _n(c, "big_chance_goals")
        if big >= 2:
            bc_conv = _safe_pct(bc_goals, big)
            if bc_goals == 0:
                out.append(f"Didn't work: {big} big chances, zero scored — the clearest chances went begging for {name}.")
            elif bc_conv is not None and bc_conv < 40:
                out.append(f"Didn't work: only {_pct_str(bc_conv)} of {big} big chances converted.")
        pass_att = _n(c, "passes_attempted")
        pass_pct = _safe_pct(_n(c, "passes_completed"), pass_att)
        if pass_pct is not None and pass_att >= 20:
            if pass_pct < 70:
                out.append(f"Didn't work: sloppy on the ball — {_pct_str(pass_pct)} pass completion.")
            elif pass_pct >= 88:
                out.append(f"Worked: composed in possession — {_pct_str(pass_pct)} pass completion.")
        if side_ppda is not None:
            if side_ppda <= 8:
                out.append(f"Worked: relentless press — PPDA {side_ppda}, barely let the opponent settle.")
            elif side_ppda >= 15:
                out.append(f"Didn't work: passive press — PPDA {side_ppda}, opponent had time on the ball.")

        if side_poss_pct is not None and side_poss_pct >= 56:
            out.append(f"Worked: possession control ({side_poss_pct:.0f}%).")
        elif side_poss_pct is not None and side_poss_pct <= 44:
            out.append(f"Lived on less of the ball ({side_poss_pct:.0f}%) — transitions mattered more.")

        if broken >= 3:
            out.append(f"Worked: press / interceptions — {broken} passes broken.")
        if turnovers >= 3:
            out.append(f"Didn't work: gave the ball away often ({turnovers} turnovers).")
        if dribbles >= 2:
            out.append(f"Worked: carriers beat the press ({dribbles} dribbles won).")
        if offs >= 2:
            out.append(f"Didn't work: timing — {offs} offsides killed advanced attacks.")
        if poss >= 6 and float(u.get("midfield", 0)) >= float(
            (au if side == "home" else hu).get("midfield", 0)
        ):
            out.append(f"Worked: spell control — {poss} possession phases with a midfield edge.")
        if saves_against >= 2 and goals > 0:
            out.append(f"Note: opposition keeper still made {saves_against} saves against {name}.")
        if not out:
            out.append(f"{name}: no single theme dominated — scoreline and unit stack-up tell most of it.")
        return out

    bullets = (
        [f"— {home_name} —"]
        + _side_bullets(home_name, "home", hu, hc, home_goals, away_goals, home_ppda)
        + [f"— {away_name} —"]
        + _side_bullets(away_name, "away", au, ac, away_goals, home_goals, away_ppda)
    )
    return {
        "title": "What worked / didn't",
        "paragraphs": [
            "Board events and unit edges, split by team — what stuck and what broke down."
        ],
        "bullets": bullets,
    }


def _how_it_unfolded_section(
    home_name: str,
    away_name: str,
    home_goals: int,
    away_goals: int,
    events: list[dict[str, Any]],
    match_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Narrative of possession spells, press, chances, goals, momentum."""
    ml = match_log if isinstance(match_log, dict) else {}
    poss = ml.get("possession_pct") or ml.get("possession") or {}
    xg = ml.get("xg") or ml.get("live_xg") or {}
    counts = ml.get("counts") or {}
    spells = ml.get("spells") if isinstance(ml.get("spells"), list) else []
    mom = ml.get("momentum_final")
    hc = counts.get("home") if isinstance(counts.get("home"), dict) else {}
    ac = counts.get("away") if isinstance(counts.get("away"), dict) else {}

    def _f(d: dict, key: str, default: float = 0.0) -> float:
        try:
            return float(d.get(key) if d.get(key) is not None else default)
        except (TypeError, ValueError):
            return default

    hp = _f(poss, "home")
    ap = _f(poss, "away")
    hx = _f(xg, "home")
    ax = _f(xg, "away")

    paragraphs: list[str] = []
    if hp or ap:
        leader = home_name if hp >= ap else away_name
        paragraphs.append(
            f"Possession: {home_name} {hp:.0f}% – {ap:.0f}% {away_name}. "
            f"{leader} held the ball more across spells."
        )
    if hx or ax:
        paragraphs.append(
            f"Pin-board live xG (official chance volume): {home_name} {hx:.2f} – {ax:.2f} {away_name}."
        )
        if abs(hx - ax) >= 0.75:
            leader = home_name if hx > ax else away_name
            trailer = away_name if hx > ax else home_name
            paragraphs.append(
                f"{leader} created the clearer chances on the board. "
                f"Similar attack units do not guarantee similar xG — chance creation, "
                f"press/resist, box occupation, and spell variance drive volume. "
                f"{trailer}'s lower live xG is the board story, not a scripted score."
            )

    home_ppda, away_ppda = _compute_ppda(ml)
    if home_ppda is not None and away_ppda is not None:
        paragraphs.append(
            f"Pressing intensity (PPDA, lower = more aggressive): {home_name} {home_ppda} – "
            f"{away_ppda} {away_name}."
        )

    goals = [e for e in events if e.get("type") in ("goal", "score")]
    if goals:
        first = goals[0]
        side = first.get("side")
        team = home_name if side == "home" else away_name if side == "away" else "?"
        minute = first.get("minute")
        min_txt = f"{int(minute)}'" if minute is not None else "early"
        paragraphs.append(f"First goal at {min_txt} for {team} set the early momentum.")
        late = [g for g in goals if isinstance(g.get("minute"), (int, float)) and g["minute"] >= 70]
        if late:
            paragraphs.append(
                f"{len(late)} late goal(s) after 70' — the match stretched into the closing spells."
            )

    turnovers = int((hc.get("turnovers") or 0) + (ac.get("turnovers") or 0))
    press_wins = int((hc.get("passes_broken") or 0) + (ac.get("passes_broken") or 0))
    if press_wins or turnovers:
        paragraphs.append(
            f"Press and turnovers shaped the middle: {press_wins} broken passes and "
            f"{turnovers} turnovers across both sides."
        )

    shots_h = int(hc.get("shots") or 0)
    shots_a = int(ac.get("shots") or 0)
    if shots_h or shots_a:
        paragraphs.append(
            f"Chances: {home_name} {shots_h} shots ({int(hc.get('big_chances') or 0)} big) vs "
            f"{away_name} {shots_a} ({int(ac.get('big_chances') or 0)} big)."
        )

    if home_goals > away_goals and hx + 0.15 < ax:
        paragraphs.append(
            f"{home_name} won despite trailing on live xG — clinical finishing or a moment decided it."
        )
    elif away_goals > home_goals and ax + 0.15 < hx:
        paragraphs.append(
            f"{away_name} won despite trailing on live xG — clinical finishing or a moment decided it."
        )
    elif abs(home_goals - away_goals) <= 1 and abs(hx - ax) < 0.25:
        paragraphs.append("A tight contest on both scoreboard and chance quality.")

    if spells:
        home_sp = sum(1 for s in spells if isinstance(s, dict) and s.get("side") == "home")
        away_sp = sum(1 for s in spells if isinstance(s, dict) and s.get("side") == "away")
        avg_dur = sum(float(s.get("duration") or 0) for s in spells if isinstance(s, dict)) / max(
            1, len(spells)
        )
        paragraphs.append(
            f"Possession spells: {home_sp} for {home_name}, {away_sp} for {away_name} "
            f"(avg hold ~{avg_dur:.1f}')."
        )

    if mom is not None:
        try:
            m = float(mom)
            lean = home_name if m > 0.55 else away_name if m < 0.45 else "neither side"
            paragraphs.append(f"Closing momentum lean: {lean} (needle {m:.2f}, 0.5 = even).")
        except (TypeError, ValueError):
            pass

    if not paragraphs:
        paragraphs.append(
            "Board telemetry was thin — unfolding story leans on the pin score and pre-match stack-up."
        )

    bullets: list[str] = []
    for e in events:
        if e.get("type") not in ("goal", "big_chance", "turnover", "offside"):
            continue
        side = e.get("side")
        team = home_name if side == "home" else away_name if side == "away" else ""
        minute = e.get("minute")
        min_txt = f"{int(minute)}'" if minute is not None else ""
        detail = e.get("detail") or e.get("type")
        player = e.get("player_short") or e.get("player") or ""
        bits = [b for b in (min_txt, player, team, str(detail)) if b]
        if bits:
            bullets.append(" · ".join(bits))
    return {
        "title": "How the match unfolded",
        "paragraphs": paragraphs,
        "bullets": bullets[:12],
    }


def _pre_match_stackup_section(
    report: dict[str, Any], home_name: str, away_name: str
) -> dict[str, Any]:
    """Attack / defence / mid / GK / transition / press vs press-resist before kick-off."""
    home_p = report["profiles"]["home"]
    away_p = report["profiles"]["away"]
    hu = _units(home_p)
    au = _units(away_p)
    he = home_p["extended"]
    ae = away_p["extended"]
    press = (report.get("mechanics") or {}).get("press_matchup") or {}

    def _cmp(label: str, hv: float, av: float, *, lower_better: bool = False) -> str:
        edge = _winner_side(hv, av, higher_is_better=not lower_better)
        who = _edge_phrase(edge, home_name, away_name)
        return f"{label}: {home_name} {_fmt(hv)} vs {away_name} {_fmt(av)} — edge: {who}."

    bullets = [
        _cmp("Attack", float(hu.get("attack", 0)), float(au.get("attack", 0))),
        _cmp("Finishing", float(hu.get("finishing", 0)), float(au.get("finishing", 0))),
        _cmp("Chance creation", float(hu.get("chance_creation", 0)), float(au.get("chance_creation", 0))),
        _cmp("Defence", float(hu.get("defence", 0)), float(au.get("defence", 0))),
        _cmp("Midfield", float(hu.get("midfield", 0)), float(au.get("midfield", 0))),
        _cmp("Goalkeeper", float(hu.get("goalkeeper", 0)), float(au.get("goalkeeper", 0))),
        _cmp(
            "Transition risk",
            float(hu.get("transition_risk", 0)),
            float(au.get("transition_risk", 0)),
            lower_better=True,
        ),
        (
            f"Press vs resist: {home_name} press {_fmt(float(he.get('pressing_intensity') or 0))} / "
            f"resist {_fmt(float(he.get('press_resistance') or 0))}; "
            f"{away_name} press {_fmt(float(ae.get('pressing_intensity') or 0))} / "
            f"resist {_fmt(float(ae.get('press_resistance') or 0))}."
        ),
    ]
    aerial_h = float(he.get("aerial_defence") or 0)
    aerial_a = float(ae.get("aerial_defence") or 0)
    if aerial_h or aerial_a:
        bullets.append(_cmp("Aerial defence", aerial_h, aerial_a))

    press_note = _press_matchup_narrative(home_name, away_name, press)
    return {
        "title": "Pre-match stack-up",
        "paragraphs": [
            (
                f"Unit ratings before kick-off for {home_name} vs {away_name}. "
                "Attack unit ≈ finishing + chance creation blend — similar attack scores can still "
                "produce very different board xG when creation, press/resist, or box occupation diverge. "
                "Finishing near 1.00 for both sides means little on its own."
            ),
            press_note,
        ],
        "bullets": bullets,
    }


def _what_happened_section(
    home_name: str,
    away_name: str,
    home_goals: int,
    away_goals: int,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    score_line = f"Final score: {home_name} {home_goals}–{away_goals} {away_name}."
    if home_goals > away_goals:
        outcome = f"{home_name} won on the pin board."
    elif away_goals > home_goals:
        outcome = f"{away_name} won on the pin board."
    else:
        outcome = "The pin board finished level."

    goals = [e for e in events if e.get("type") in ("goal", "score")]
    goal_bullets: list[str] = []
    for g in goals:
        side = g.get("side")
        team = home_name if side == "home" else away_name if side == "away" else str(side or "?")
        minute = g.get("minute")
        player = g.get("player") or g.get("scorer") or g.get("player_short") or "Unknown"
        min_txt = f"{int(minute)}'" if minute is not None else "?"
        xg_bit = g.get("xg")
        extra = f" (xg {float(xg_bit):.2f})" if xg_bit is not None else ""
        goal_bullets.append(f"{min_txt} {player} ({team}){extra}")

    counts: dict[str, int] = {}
    for e in events:
        t = str(e.get("type") or "")
        if t in ("goal", "score"):
            continue
        counts[t] = counts.get(t, 0) + 1

    key_labels = {
        "offside": "offsides disallowed",
        "interception": "passes broken / interceptions",
        "pass_broken": "passes broken / interceptions",
        "dribble_success": "successful dribbles",
        "dribble_beaten": "successful dribbles",
        "dribble_won": "successful dribbles",
        "dribble_failed": "failed dribbles / tackles",
        "dribble_lost": "failed dribbles / tackles",
        "tackle": "tackles won",
        "shot": "shots",
        "save": "saves",
        "miss": "shots off target",
        "big_chance": "big chances",
        "big_chance_missed": "big chances missed",
        "turnover": "turnovers",
        "possession": "possession spells started",
    }
    event_bullets: list[str] = []
    # Merge aliases
    merged: dict[str, int] = {}
    for t, n in counts.items():
        label = key_labels.get(t, t.replace("_", " "))
        merged[label] = merged.get(label, 0) + n
    for label, n in sorted(merged.items(), key=lambda x: -x[1]):
        if n > 0:
            event_bullets.append(f"{n}x {label}")

    paragraphs = [score_line, outcome]
    if not events:
        paragraphs.append(
            "Board event log was sparse — narrative leans on the scoreline and pre-match unit edges."
        )
    elif goal_bullets:
        paragraphs.append(f"Goals ({len(goal_bullets)}): see timeline below.")
    else:
        paragraphs.append("No timed goal events were logged; only the final pin score is known.")

    bullets = goal_bullets + event_bullets
    return {
        "title": "What happened",
        "paragraphs": paragraphs,
        "bullets": bullets,
    }


def _edges_exploited_section(
    report: dict[str, Any],
    home_name: str,
    away_name: str,
    home_goals: int,
    away_goals: int,
    events: list[dict[str, Any]],
    match_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    home_p = report["profiles"]["home"]
    away_p = report["profiles"]["away"]
    hu = _units(home_p)
    au = _units(away_p)
    he = home_p["extended"]
    ae = away_p["extended"]
    press = (report.get("mechanics") or {}).get("press_matchup") or {}

    gd = home_goals - away_goals
    winner_side = "home" if gd > 0 else "away" if gd < 0 else None
    winner_name = home_name if winner_side == "home" else away_name if winner_side == "away" else None

    bullets: list[str] = []

    # Transition / counters
    h_tr = float(hu.get("transition_risk", 0))
    a_tr = float(au.get("transition_risk", 0))
    if winner_side == "home" and a_tr > h_tr + 0.04:
        bullets.append(
            f"{home_name} came out ahead while {away_name} carried higher transition risk "
            f"({a_tr:.2f} vs {h_tr:.2f}) — counters / open space likely mattered."
        )
    elif winner_side == "away" and h_tr > a_tr + 0.04:
        bullets.append(
            f"{away_name} punished {home_name}'s higher transition risk "
            f"({h_tr:.2f} vs {a_tr:.2f})."
        )
    elif abs(h_tr - a_tr) > 0.05 and abs(gd) >= 1:
        riskier = home_name if h_tr > a_tr else away_name
        bullets.append(
            f"{riskier} was the riskier transition side; the scoreline "
            f"({'favoured the more solid side' if (h_tr > a_tr) == (gd < 0) else 'did not clearly punish the risk'})."
        )

    # Attack vs defence mismatch
    h_atk, a_atk = float(hu.get("attack", 0)), float(au.get("attack", 0))
    h_def, a_def = float(hu.get("defence", 0)), float(au.get("defence", 0))
    if winner_side == "home" and h_atk > a_def + 0.05:
        bullets.append(
            f"{home_name}'s attack ({h_atk:.2f}) had a clear edge over {away_name}'s defence ({a_def:.2f})."
        )
    elif winner_side == "away" and a_atk > h_def + 0.05:
        bullets.append(
            f"{away_name}'s attack ({a_atk:.2f}) had a clear edge over {home_name}'s defence ({h_def:.2f})."
        )

    # Press vs resist + board interceptions
    intercepts = sum(
        1
        for e in events
        if e.get("type") in ("interception", "pass_broken", "tackle")
    )
    for side_key, team_name, opp_name in (
        ("home", home_name, away_name),
        ("away", away_name, home_name),
    ):
        row = press.get(side_key) or {}
        if row.get("active") and float(row.get("suppression") or 0) >= 0.03:
            bullets.append(
                f"{team_name}'s press vs {opp_name}'s build-up "
                f"(~{float(row['suppression']) * 100:.1f}% creation trim) was a live edge"
                + (f" — board logged {intercepts} broken passes / wins." if intercepts else ".")
            )

    h_press = float(he.get("pressing_intensity") or 0)
    a_resist = float(ae.get("press_resistance") or 0)
    a_press = float(ae.get("pressing_intensity") or 0)
    h_resist = float(he.get("press_resistance") or 0)
    if h_press > a_resist + 0.06 and (winner_side == "home" or intercepts >= 3):
        bullets.append(
            f"{home_name}'s press ({h_press:.2f}) overmatched {away_name}'s resistance ({a_resist:.2f})."
        )
    if a_press > h_resist + 0.06 and (winner_side == "away" or intercepts >= 3):
        bullets.append(
            f"{away_name}'s press ({a_press:.2f}) overmatched {home_name}'s resistance ({h_resist:.2f})."
        )

    # Real observed pressing (PPDA) from the board -- confirms or
    # contradicts the rating-based press projection above rather than
    # replacing it; the rating is a pre-match proxy, PPDA is what actually
    # happened. Fires independently of whether the rating comparison above
    # triggered, since a close pre-match rating can still diverge sharply
    # from how a match actually played out.
    home_ppda, away_ppda = _compute_ppda(match_log)
    if home_ppda is not None and away_ppda is not None and abs(home_ppda - away_ppda) >= 2.5:
        harder = home_name if home_ppda < away_ppda else away_name
        softer = away_name if home_ppda < away_ppda else home_name
        harder_ppda = min(home_ppda, away_ppda)
        softer_ppda = max(home_ppda, away_ppda)
        rating_agrees = (harder == home_name and h_press >= a_press) or (harder == away_name and a_press >= h_press)
        bullets.append(
            f"On the board, {harder} actually pressed harder (PPDA {harder_ppda} vs {softer}'s {softer_ppda})"
            + (", matching the pre-match press rating." if rating_agrees else " — despite a closer pre-match press rating.")
        )

    # Finishing quality actually observed -- straight off the board counts
    # (see the conversion/passing stats project), not just goals scored.
    counts = match_log.get("counts") if isinstance(match_log, dict) else None
    if isinstance(counts, dict):
        hc2 = counts.get("home") if isinstance(counts.get("home"), dict) else {}
        ac2 = counts.get("away") if isinstance(counts.get("away"), dict) else {}
        h_conv = _safe_pct(home_goals, hc2.get("shots"))
        a_conv = _safe_pct(away_goals, ac2.get("shots"))
        if (
            h_conv is not None
            and a_conv is not None
            and (hc2.get("shots") or 0) >= 2
            and (ac2.get("shots") or 0) >= 2
            and abs(h_conv - a_conv) >= 20
        ):
            if h_conv > a_conv:
                bullets.append(f"{home_name} finished sharper — {_pct_str(h_conv)} shot conversion vs {away_name}'s {_pct_str(a_conv)}.")
            else:
                bullets.append(f"{away_name} finished sharper — {_pct_str(a_conv)} shot conversion vs {home_name}'s {_pct_str(h_conv)}.")

    # Dribbles / beat the press
    drib_ok = sum(
        1 for e in events if e.get("type") in ("dribble_success", "dribble_beaten", "dribble_won")
    )
    if drib_ok >= 2:
        by_side = {"home": 0, "away": 0}
        for e in events:
            if e.get("type") in ("dribble_success", "dribble_beaten", "dribble_won") and e.get("side") in by_side:
                by_side[str(e["side"])] += 1
        lead = "home" if by_side["home"] >= by_side["away"] else "away"
        bullets.append(
            f"Ball carriers beat the press often ({drib_ok} successful dribbles) — "
            f"{home_name if lead == 'home' else away_name} led that duel."
        )

    # Offsides
    offs = sum(1 for e in events if e.get("type") == "offside")
    if offs:
        bullets.append(
            f"{offs} offside whistle(s) killed advanced attacks — high line / timing mattered."
        )

    # Aerial
    aerial_h = float(he.get("aerial_defence") or 0)
    aerial_a = float(ae.get("aerial_defence") or 0)
    if abs(aerial_h - aerial_a) > 0.06 and abs(gd) >= 1:
        aerial_edge = home_name if aerial_h > aerial_a else away_name
        bullets.append(
            f"Aerial defence edge sat with {aerial_edge} "
            f"({max(aerial_h, aerial_a):.2f} vs {min(aerial_h, aerial_a):.2f})."
        )

    # GK
    if winner_side and abs(float(hu.get("goalkeeper", 0)) - float(au.get("goalkeeper", 0))) > 0.05:
        gk_edge = _edge_phrase(
            _winner_side(float(hu["goalkeeper"]), float(au["goalkeeper"])),
            home_name,
            away_name,
        )
        saves = sum(1 for e in events if e.get("type") == "save")
        bullets.append(
            f"GK edge: {gk_edge}"
            + (f" ({saves} saves logged on the board)." if saves else ".")
        )

    if not bullets:
        if winner_name:
            bullets.append(
                f"{winner_name} edged the pin score; unit gaps were modest, so finishing moments "
                "and board variance decided it more than one structural mismatch."
            )
        else:
            bullets.append(
                "Draw on the board — pre-match edges largely cancelled out in the pin contest."
            )

    paras = [
        (
            f"Tying pre-match edges to the {home_goals}–{away_goals} pin result"
            + (" and logged board events." if events else " (inferred from score + unit deltas).")
        )
    ]
    if winner_name:
        paras.append(f"Who came out better: {winner_name}.")

    return {
        "title": "Edges exploited",
        "paragraphs": paras,
        "bullets": bullets[:8],
    }


def enrich_analysis_with_board_result(
    analysis: dict[str, Any],
    report: dict[str, Any],
    *,
    home_goals: int,
    away_goals: int,
    board_events: list[dict[str, Any]] | None = None,
    match_log: list[dict[str, Any]] | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Fold pin-board score + optional event log into a ratings-based matchup analysis.
    Adds Pre-match stack-up, What happened, What worked, How it unfolded, and Edges exploited.
    """
    matchup = report["matchup"]
    home_name = _side_label(matchup, "home")
    away_name = _side_label(matchup, "away")
    events = _normalize_board_events(board_events, match_log)
    ml = match_log if isinstance(match_log, dict) else None

    out = dict(analysis)
    sections = list(analysis.get("sections") or [])

    stack = _pre_match_stackup_section(report, home_name, away_name)
    happened = _what_happened_section(home_name, away_name, home_goals, away_goals, events)
    worked = _what_worked_section(
        report, home_name, away_name, home_goals, away_goals, events, ml
    )
    unfolded = _how_it_unfolded_section(
        home_name, away_name, home_goals, away_goals, events, ml
    )
    exploited = _edges_exploited_section(
        report, home_name, away_name, home_goals, away_goals, events, ml
    )

    # Insert after Verdict (index 0) when present
    insert_at = 1 if sections and (sections[0].get("title") or "") == "Verdict" else 0
    sections[insert_at:insert_at] = [stack, happened, worked, unfolded, exploited]

    # Soften pre-match "favourite" verdict with actual pin outcome
    if home_goals > away_goals:
        pin_winner = home_name
    elif away_goals > home_goals:
        pin_winner = away_name
    else:
        pin_winner = None
    base_summary = analysis.get("summary") or ""
    if pin_winner:
        out["summary"] = (
            f"Pin board: {home_name} {home_goals}–{away_goals} {away_name} — {pin_winner} won. "
            f"Pre-match ratings: {base_summary}"
        )
    else:
        out["summary"] = (
            f"Pin board: {home_name} {home_goals}–{away_goals} {away_name} (draw). "
            f"Pre-match ratings: {base_summary}"
        )

    out["sections"] = sections
    board_xg = None
    if isinstance(ml, dict):
        raw_xg = ml.get("xg") or ml.get("live_xg") or {}
        if isinstance(raw_xg, dict) and (
            raw_xg.get("home") is not None or raw_xg.get("away") is not None
        ):
            try:
                board_xg = {
                    "home": round(float(raw_xg.get("home") or 0), 2),
                    "away": round(float(raw_xg.get("away") or 0), 2),
                }
            except (TypeError, ValueError):
                board_xg = None
    out["board_result"] = {
        "home_goals": int(home_goals),
        "away_goals": int(away_goals),
        "event_count": len(events),
        "engine": "tactic_board",
        "xg": board_xg,
    }
    # Prefer pin-board xG in key factors over the pre-match expected_xg (often ~even).
    if board_xg and isinstance(out.get("key_factors"), list):
        out["key_factors"] = [
            f
            for f in out["key_factors"]
            if "expected" not in str(f.get("factor") or "").lower()
            and "xg" not in str(f.get("factor") or "").lower()
        ]
        out["key_factors"].insert(
            0,
            {
                "factor": "Pin-board live xG",
                "explanation": (
                    f"Official chance volume from the tactic board "
                    f"({home_name} {board_xg['home']:.2f} – {board_xg['away']:.2f} {away_name}). "
                    "Pre-match expected xG is ratings-only and can look even when the board did not."
                ),
                "home": board_xg["home"],
                "away": board_xg["away"],
            },
        )
    if isinstance(ml, dict) and isinstance(out.get("key_factors"), list):
        home_ppda, away_ppda = _compute_ppda(ml)
        if home_ppda is not None and away_ppda is not None:
            out["key_factors"].append(
                {
                    "factor": "Pressing intensity (PPDA)",
                    "explanation": (
                        f"Passes per defensive action in the middle and attacking thirds — "
                        f"{home_name} {home_ppda} vs {away_name} {away_ppda}. Lower means more "
                        "aggressive, higher pressing."
                    ),
                    "home": home_ppda,
                    "away": away_ppda,
                }
            )
    return out


# ---------------------------------------------------------------------------
# Per-match player ratings + Player of the Match
#
# A WhoScored/FotMob-style weighted-events model: start every starter at a
# neutral 6.0 and add/subtract per contribution logged against them in this
# match's own event stream (never season totals — see compute_match_ratings'
# caller, which always scopes `events`/`player_passing` to one result). Every
# weight below is a first-pass, deliberately simple and tunable -- there is
# no "correct" football rating formula, real providers disagree with each
# other too. Clean-sheet/goals-conceded bonuses apply to keeper + defence
# only, matching the real convention every mainstream rating site uses.
# ---------------------------------------------------------------------------

_RATING_BASE = 6.0
_RATING_MIN = 3.0
_RATING_MAX = 10.0

# Slot roles slot_role() can return that count as "defence" for clean-sheet
# purposes (goalkeeper handled separately, always eligible).
_DEFENSIVE_ROLES = {"fullback", "centre_back", "dm"}

# dribble_won/dribble_lost are deliberately NOT in here -- see the capped
# handling below. A real completed match logged 147 dribble_won events out
# of 319 total (46% of everything that happened), so a handful of busy
# players routinely rack up 15-23 of them each; at a flat per-event weight
# that single stat swamped goals/assists/everything else and pushed 8 of 22
# players in one real match to the rating ceiling. Everything else here
# stays uncapped-per-event since none of it appears anywhere near that
# volume in practice.
#
# Tuning pass 2 — real user feedback after watching two live matches: a 10
# should be very rare, and dribbling volume specifically should never be
# what gets a player there (see the even-lower dribble cap below). Goal
# weight raised so a HAT-TRICK is what actually drives a 10 -- one goal
# plus a good all-around game should land closer to 7.5-8, not the ceiling.
# Every other positive weight nudged down to match: no single category
# (shots, key passes, dribbles alone) should be able to carry a player to
# the ceiling by itself anymore, only genuine hat-trick-level standout games.
_RATING_EVENT_WEIGHTS: dict[str, float] = {
    "goal": 1.3,
    "assist": 0.55,  # applied via the goal event's `assist` field, not its own event
    "shot": 0.2,
    "big_chance": 0.2,
    "key_pass": 0.3,
    "big_chance_missed": -0.55,
    "tackle": 0.25,  # dribble_lost credited to the `by` defender
    "interception": 0.2,  # pass_broken credited to the `by` defender
    "save": 0.45,
    "blocked_shot": 0.2,  # credited to the `by` blocker, distinct from the shooter's own shot
    "foul": -0.3,
    "yellow_card": -0.5,
    "red_card": -2.0,
}

# Dribbles should read as flavor ("lots of dribbles" in the highlight text),
# never as a rating driver -- capped low enough that even a 20+ dribble
# match-high barely moves the needle.
_DRIBBLE_WON_WEIGHT = 0.015
_DRIBBLE_WON_CAP = 0.3
_DRIBBLE_LOST_WEIGHT = -0.08
_DRIBBLE_LOST_CAP = 0.4

# (singular, plural) display form per bump() label — kept as an explicit
# table rather than string-manipulation pluralization, since several of
# these put the noun mid-phrase ("big chance missed" -> "big chances
# missed", not "big chance misseds").
_LABEL_DISPLAY: dict[str, tuple[str, str]] = {
    "goal": ("goal", "goals"),
    "comeback goal": ("comeback goal", "comeback goals"),
    "go-ahead goal": ("go-ahead goal", "go-ahead goals"),
    "assist": ("assist", "assists"),
    "comeback assist": ("comeback assist", "comeback assists"),
    "go-ahead assist": ("go-ahead assist", "go-ahead assists"),
    "shot": ("shot", "shots"),
    "key pass": ("key pass", "key passes"),
    "big chance missed": ("big chance missed", "big chances missed"),
    "dribble won": ("dribble won", "dribbles won"),
    "dribble lost": ("dribble lost", "dribbles lost"),
    "tackle won": ("tackle won", "tackles won"),
    "interception": ("interception", "interceptions"),
    "save": ("save", "saves"),
    "shot blocked": ("shot blocked", "shots blocked"),
    "foul conceded": ("foul conceded", "fouls conceded"),
    "yellow card": ("yellow card", "yellow cards"),
    "red card": ("red card", "red cards"),
}

_MAX_HIGHLIGHTS_PER_PLAYER = 4

_PASS_VOLUME_MIN_FOR_ACCURACY_BONUS = 15
_PASS_ACCURACY_BASELINE = 0.80  # completion% above/below this nudges rating
_PASS_ACCURACY_WEIGHT = 2.0
_PASS_ACCURACY_CAP = 0.5
_PROGRESSIVE_PASS_WEIGHT = 0.05
_PROGRESSIVE_PASS_CAP = 0.6
_RESULT_MODIFIER = {"win": 0.3, "draw": 0.0, "loss": -0.2}
_CLEAN_SHEET_BONUS = 0.5

# A perfect 10 should be rare, and real football's own convention is that a
# player on the LOSING side essentially never gets one -- the one common
# exception is a genuine end-to-end thriller, where individual moments can
# stand out even in defeat. Modeled as: losing-side ratings are capped below
# the ceiling, UNLESS this match's combined goals clear the "high volume"
# bar (loosely: a 3+ goal margin game, or a 5+ goal shootout either team
# could have won).
_LOSING_TEAM_RATING_CAP = 9.4
_HIGH_VOLUME_TOTAL_GOALS = 5

# ---------------------------------------------------------------------------
# Impact model — real user feedback, in two rounds. First: raw event
# counting treats every goal and every tackle as equal, but a goal that
# drags your team level from behind (or a defender's stop that specifically
# neuters the match's most dangerous attacker) obviously matters more than
# a stat padded onto an already-decided game. Second round: the RATING
# itself should stay plain event-driven (predictable, transparent -- a goal
# is worth a goal) -- this "impact" signal should only decide ties, not
# change the number everyone sees. So: the two dimensions below are tracked
# in `impact_score` as a pure side-channel, added to contribution_weight/
# highlights for explanation but NEVER added to `scores` (the actual
# rating). Both derived purely from this match's own event stream (no
# season stats needed, keeps this cheap enough to run at match completion —
# see _attach_player_ratings_at_completion):
#
# 1. Scoreline swing — a goal/assist matters more for impact purposes when
#    it changes the game's shape: dragging a trailing side level or ahead
#    ("comeback"), or breaking a tie ("go-ahead"), especially late.
#    Extending an already-won game earns baseline rating only, no impact.
# 2. Threat containment — a tackle/interception/block earns impact credit
#    scaled by how dangerous the specific attacker it stopped was THIS
#    match (their own shots/key passes/dribbles are the proxy for "how live
#    a threat were they today" -- no player-quality database needed); the
#    rating credit itself stays the plain baseline regardless.
#
# `impact` on each rating row is the sum of this extra, rating-invisible
# credit -- a clean, explainable "how much of this player's day came from
# moments that actually swung the match" number, used as the primary
# Player-of-the-Match tie-break below (ahead of plain goals) when two
# players land on the identical rating for very different reasons.
_COMEBACK_GOAL_MULTIPLIER = 1.8  # trailing -> level or ahead
_GO_AHEAD_GOAL_MULTIPLIER = 1.4  # level -> ahead
_TRAILING_GOAL_MULTIPLIER = 1.3  # still trailing afterward, but clawing back
_LATE_GOAL_MINUTE = 80.0
_LATE_GOAL_KICKER = 1.15
_GOAL_SWING_MULTIPLIER_CAP = 2.2

# Threat score (0-1ish, see _threat_score) needed to make containing that
# player "impact" rather than routine defending.
_ELITE_THREAT_THRESHOLD = 0.5
_THREAT_SHOT_WEIGHT = 0.35
_THREAT_KEY_PASS_WEIGHT = 0.3
_THREAT_DRIBBLE_WEIGHT = 0.06
_THREAT_NORMALIZER = 3.0  # raw threat points read as "1.0 = full elite threat"


def _player_side_slot_map(home_team: Any, away_team: Any) -> dict[str, tuple[str, str, str]]:
    """player name -> (team_name, side, slot) for every starter on both sides."""
    out: dict[str, tuple[str, str, str]] = {}
    for side, team in (("home", home_team), ("away", away_team)):
        for row in team.lineup:
            player = (row.player or "").strip()
            if player:
                out[player] = (team.name, side, row.slot)
    return out


def compute_match_ratings(
    home_team: Any,
    away_team: Any,
    events: list[dict[str, Any]],
    player_passing: dict[str, Any] | None,
    *,
    home_goals: int,
    away_goals: int,
) -> dict[str, Any]:
    """Per-player 1-10 match rating + Player of the Match for one match.

    `events` must already be scoped to this single match (normalize_board_events
    output), never a season-wide event stream. `player_passing` is this
    match's own match_log["player_passing"] map, keyed by player name.
    """
    player_map = _player_side_slot_map(home_team, away_team)
    if not player_map:
        return {"ratings": [], "player_of_the_match": None}

    # Counted per (player, label) rather than one raw string per event, so a
    # keeper's 4 saves surfaces as one "4 saves" highlight instead of eating
    # the whole display cap on four identical lines.
    contribution_counts: dict[str, dict[str, int]] = {p: {} for p in player_map}
    contribution_weight: dict[str, dict[str, float]] = {p: {} for p in player_map}
    one_off_notes: dict[str, list[str]] = {p: [] for p in player_map}
    scores: dict[str, float] = {p: _RATING_BASE for p in player_map}
    # Extra credit beyond plain baseline from a swing goal/assist or an
    # elite-threat containment -- see the impact-model comment above
    # _COMEBACK_GOAL_MULTIPLIER. Used as the primary Player-of-the-Match
    # tie-break: two players on the same rating for different reasons, the
    # one whose contribution actually swung the match wins.
    impact_score: dict[str, float] = {p: 0.0 for p in player_map}

    def bump_raw(player: str | None, weight: float, label: str) -> None:
        player = (player or "").strip()
        if not player or player not in scores:
            return
        scores[player] += weight
        contribution_counts[player][label] = contribution_counts[player].get(label, 0) + 1
        contribution_weight[player][label] = contribution_weight[player].get(label, 0.0) + abs(weight)

    def bump(player: str | None, event_key: str, label: str) -> None:
        bump_raw(player, _RATING_EVENT_WEIGHTS[event_key], label)

    # dribble_won/dribble_lost tallied by count only here -- score impact is
    # applied once after the loop, capped (see _DRIBBLE_WON_CAP/_DRIBBLE_LOST_CAP
    # above), since raw per-event weighting is what let a handful of busy
    # players' dribble counts alone push them to the rating ceiling.
    def count_only(player: str | None, label: str) -> None:
        player = (player or "").strip()
        if not player or player not in scores:
            return
        contribution_counts[player][label] = contribution_counts[player].get(label, 0) + 1

    # goal/assist (needs chronological score-state -- see the swing pass
    # below) and tackle/interception/blocked_shot (needs full-match threat
    # scores, which aren't known until every player's shots/key passes/
    # dribbles for the WHOLE match are tallied) are deliberately deferred
    # rather than scored inline here.
    goal_events: list[dict[str, Any]] = []
    defensive_events: list[tuple[str, str | None, str | None]] = []

    for ev in events:
        et = ev.get("type")
        player = ev.get("player")
        if et == "goal":
            goal_events.append(ev)
        elif et in ("shot", "big_chance"):
            bump(player, et, "shot")
        elif et == "key_pass":
            bump(player, "key_pass", "key pass")
        elif et == "big_chance_missed":
            bump(player, "big_chance_missed", "big chance missed")
        elif et == "dribble_won":
            count_only(player, "dribble won")
        elif et == "dribble_lost":
            count_only(player, "dribble lost")
            defensive_events.append(("tackle", ev.get("by"), player))
        elif et == "pass_broken":
            defensive_events.append(("interception", ev.get("by"), ev.get("against_player")))
        elif et == "save":
            bump(player, "save", "save")
        elif et == "blocked_shot":
            defensive_events.append(("blocked_shot", ev.get("by"), player))
        elif et == "foul":
            bump(player, "foul", "foul conceded")
        elif et == "yellow_card":
            bump(player, "yellow_card", "yellow card")
        elif et == "red_card":
            bump(player, "red_card", "red card")

    # Threat score (0-1ish): how live an attacking threat this player was
    # THIS match, from their own shots/key passes/dribbles already tallied
    # above -- the proxy for "how elite were they today" a defender's
    # containment gets measured against (see the impact-model comment).
    def threat_score(player: str | None) -> float:
        player = (player or "").strip()
        if not player:
            return 0.0
        c = contribution_counts.get(player, {})
        raw = (
            c.get("shot", 0) * _THREAT_SHOT_WEIGHT
            + c.get("key pass", 0) * _THREAT_KEY_PASS_WEIGHT
            + c.get("dribble won", 0) * _THREAT_DRIBBLE_WEIGHT
        )
        return min(1.0, raw / _THREAT_NORMALIZER)

    # Goals/assists, chronologically, applying the scoreline-swing multiplier.
    running = {"home": 0, "away": 0}
    for ev in goal_events:
        side = ev.get("side")
        opp_side = "away" if side == "home" else "home"
        team_before = running.get(side, 0)
        opp_before = running.get(opp_side, 0)
        if team_before < opp_before:
            multiplier = (
                _COMEBACK_GOAL_MULTIPLIER if team_before + 1 >= opp_before else _TRAILING_GOAL_MULTIPLIER
            )
            goal_label = "comeback goal" if team_before + 1 >= opp_before else "goal"
            assist_label = "comeback assist" if team_before + 1 >= opp_before else "assist"
        elif team_before == opp_before:
            multiplier = _GO_AHEAD_GOAL_MULTIPLIER
            goal_label = "go-ahead goal"
            assist_label = "go-ahead assist"
        else:
            multiplier = 1.0
            goal_label = "goal"
            assist_label = "assist"
        minute = float(ev.get("minute") or 0)
        if minute >= _LATE_GOAL_MINUTE:
            multiplier *= _LATE_GOAL_KICKER
        multiplier = min(multiplier, _GOAL_SWING_MULTIPLIER_CAP)

        # Real user feedback: the RATING itself goes back to plain event
        # counting (flat baseline weight, no swing multiplier applied to
        # the score) -- only impact_score (the tie-break signal) gets the
        # swing bonus. The descriptive label (goal_label) still reflects
        # what actually happened for the highlight text, it just no longer
        # changes the number.
        scorer = ev.get("player")
        goal_baseline = _RATING_EVENT_WEIGHTS["goal"]
        bump_raw(scorer, goal_baseline, goal_label)
        scorer_key = (scorer or "").strip()
        if scorer_key in impact_score and multiplier > 1.0:
            impact_score[scorer_key] += goal_baseline * (multiplier - 1.0)

        assist = ev.get("assist")
        if assist and assist != scorer:
            assist_baseline = _RATING_EVENT_WEIGHTS["assist"]
            bump_raw(assist, assist_baseline, assist_label)
            assist_key = (assist or "").strip()
            if assist_key in impact_score and multiplier > 1.0:
                impact_score[assist_key] += assist_baseline * (multiplier - 1.0)

        if side in running:
            running[side] += 1

    # Tackles/interceptions/blocks -- rating stays plain baseline (event-
    # driven, same as everything else), same as the goal/assist treatment
    # above: how dangerous the attacker stopped was only feeds impact_score
    # (the tie-break signal, and the "contained X" highlight), never the
    # number itself. Containing a nobody vs. containing this match's most
    # live threat now reads identically in the rating -- only in who wins
    # a tie, and in the highlight text explaining why.
    _DEFENSIVE_LABEL = {"tackle": "tackle won", "interception": "interception", "blocked_shot": "shot blocked"}
    best_contained: dict[str, tuple[float, str]] = {}  # defender -> (threat, attacker) of their best stop
    for kind, defender, attacker in defensive_events:
        base_weight = _RATING_EVENT_WEIGHTS[kind]
        t = threat_score(attacker)
        bump_raw(defender, base_weight, _DEFENSIVE_LABEL[kind])
        defender_key = (defender or "").strip()
        if defender_key in impact_score and t >= _ELITE_THREAT_THRESHOLD:
            impact_score[defender_key] += base_weight * t
            attacker_key = (attacker or "").strip()
            if attacker_key and t > best_contained.get(defender_key, (0.0, ""))[0]:
                best_contained[defender_key] = (t, attacker_key)
    for defender_key, (_t, attacker_key) in best_contained.items():
        one_off_notes[defender_key].append(f"contained {attacker_key}")

    # Capped dribble_won/dribble_lost application (see count_only above) --
    # the weight actually applied becomes this label's sort weight for
    # format_highlights too, so "23 dribbles won" doesn't outrank "1 goal"
    # just because the raw count is bigger than the capped point swing.
    for player in player_map:
        dw = contribution_counts[player].get("dribble won", 0)
        if dw:
            applied = min(_DRIBBLE_WON_CAP, dw * _DRIBBLE_WON_WEIGHT)
            scores[player] += applied
            contribution_weight[player]["dribble won"] = applied
        dl = contribution_counts[player].get("dribble lost", 0)
        if dl:
            applied = max(-_DRIBBLE_LOST_CAP, dl * _DRIBBLE_LOST_WEIGHT)
            scores[player] += applied
            contribution_weight[player]["dribble lost"] = abs(applied)

    for player, row in (player_passing or {}).items():
        if player not in scores or not isinstance(row, dict):
            continue
        attempted = float(row.get("passes_attempted") or 0)
        completed = float(row.get("passes_completed") or 0)
        if attempted >= _PASS_VOLUME_MIN_FOR_ACCURACY_BONUS:
            pct = completed / attempted
            delta = max(
                -_PASS_ACCURACY_CAP,
                min(_PASS_ACCURACY_CAP, (pct - _PASS_ACCURACY_BASELINE) * _PASS_ACCURACY_WEIGHT),
            )
            if abs(delta) >= 0.05:
                scores[player] += delta
                one_off_notes[player].append(
                    f"{completed:.0f}/{attempted:.0f} passing ({pct * 100:.0f}%)"
                )
        progressive = float(row.get("progressive_passes") or 0)
        if progressive:
            bonus = min(_PROGRESSIVE_PASS_CAP, progressive * _PROGRESSIVE_PASS_WEIGHT)
            scores[player] += bonus

    home_result = "win" if home_goals > away_goals else "loss" if home_goals < away_goals else "draw"
    away_result = "win" if away_goals > home_goals else "loss" if away_goals < home_goals else "draw"
    for player, (_team, side, _slot) in player_map.items():
        scores[player] += _RESULT_MODIFIER[home_result if side == "home" else away_result]

    home_clean_sheet = away_goals == 0
    away_clean_sheet = home_goals == 0
    for player, (_team, side, slot) in player_map.items():
        clean = home_clean_sheet if side == "home" else away_clean_sheet
        if not clean:
            continue
        role = slot_role(slot)
        if role == "gk" or role in _DEFENSIVE_ROLES:
            scores[player] += _CLEAN_SHEET_BONUS
            one_off_notes[player].append("clean sheet")

    def format_highlights(player: str) -> list[str]:
        counted = [
            (
                contribution_weight[player][label],
                count,
                f"{count} {_LABEL_DISPLAY[label][1] if count != 1 else _LABEL_DISPLAY[label][0]}",
            )
            for label, count in contribution_counts[player].items()
        ]
        # Highest total point-swing first, so a goal always outranks a
        # passing-accuracy nudge regardless of which fired first in the match.
        counted.sort(key=lambda row: row[0], reverse=True)
        phrases = [row[2] for row in counted] + one_off_notes[player]
        return phrases[:_MAX_HIGHLIGHTS_PER_PLAYER]

    # A losing-side player is capped below the ceiling -- a perfect 10 on
    # the losing team essentially never happens in real football rating
    # conventions -- unless this was itself a high-volume, end-to-end match
    # (see _HIGH_VOLUME_TOTAL_GOALS) where a losing side's standout moments
    # are plausible even in defeat.
    high_volume = (home_goals + away_goals) >= _HIGH_VOLUME_TOTAL_GOALS
    home_lost = home_goals < away_goals
    away_lost = away_goals < home_goals

    # Goals/assists can now land under three different labels each (plain,
    # comeback, go-ahead) depending on the scoreline swing they came with --
    # sum across all of them for the totals shown/used below.
    _GOAL_LABELS = ("goal", "comeback goal", "go-ahead goal")
    _ASSIST_LABELS = ("assist", "comeback assist", "go-ahead assist")

    ratings = []
    for player, (team, side, slot) in player_map.items():
        ceiling = _RATING_MAX
        lost = home_lost if side == "home" else away_lost
        if lost and not high_volume:
            ceiling = _LOSING_TEAM_RATING_CAP
        rating = round(max(_RATING_MIN, min(ceiling, scores[player])), 1)
        goals = sum(contribution_counts[player].get(lbl, 0) for lbl in _GOAL_LABELS)
        assists = sum(contribution_counts[player].get(lbl, 0) for lbl in _ASSIST_LABELS)
        ratings.append(
            {
                "player": player,
                "team": team,
                "side": side,
                "slot": slot,
                "rating": rating,
                "goals": goals,
                "assists": assists,
                "impact": round(impact_score[player], 2),
                "highlights": format_highlights(player),
            }
        )
    # Tie-break for equal ratings (a real 10.0-vs-10.0 tie is exactly the
    # scenario a rare-ceiling formula makes plausible): highest impact first
    # -- the extra credit from a genuine scoreline swing (comeback/go-ahead
    # goal or assist) or containing this match's most dangerous attacker --
    # ahead of plain goal count, since two players can land on the same
    # rating for very different reasons and the more match-defining one
    # should win. Goals, then alphabetical, are just final determinism.
    ratings.sort(key=lambda r: (-r["rating"], -r["impact"], -r["goals"], -(r["goals"] + r["assists"]), r["player"]))

    potm = ratings[0] if ratings else None
    return {"ratings": ratings, "player_of_the_match": potm}
