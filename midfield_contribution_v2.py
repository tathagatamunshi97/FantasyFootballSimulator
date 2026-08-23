"""
CLOSED RESEARCH ARTIFACT -- not imported by team_ratings.py, lineup_builder.py,
or the match engine, and not intended to be. Investigated whether
team_ratings.py's plain-average midfield score structurally favours 3-back
formations. Conclusion: no. v3 (below) converged to within a few
thousandths of v1's own formation rankings on real curated rosters, flipping
none of its sign preferences; v2's 3 sign flips were traced to its own
categorical job-weight table and a job-score scale mismatch, not a real
correction. The residual small 3-back edge seen in sweeps (~0.001-0.026
overall, most teams) is driven upstream -- by which formation lets
lineup_builder field a genuinely strong CM-profile player in midfield
instead of at fullback -- not by this rating formula. See the comment at
team_ratings.py's `midfield = _avg(...)` line for the production-facing
summary. Kept here only as a record of the methodology, in case a future
session needs to re-derive or re-check this.

Computes alternative "midfield" unit scores (v2, v3) alongside the live
plain-average score (v1), for side-by-side comparison only. See memory:
gated-experiment-workflow.

v2 methodology (agreed with the user before any code was written):
  - Decompose each midfield-eligible player's capability into four jobs
    (progression, creation, shielding, retention), reusing the exact
    sub-terms already inside team_ratings._player_midfield_contrib -- no
    new stat mappings invented.
  - Within each job, weight players by capability^p / sum(capability^p),
    p=1.0 (locked in after an offline gut-check across p in
    {0, 0.5, 1, 1.5, 2} using real curated players -- p=1 penalises a
    genuinely weak extra body without going "too forgiving", see p=2).
  - Combine the four job scores into a unit score using formation-derived
    job weights, built by averaging a per-tag (DM/CM/AM) job-emphasis
    vector across whichever central-mid slots the formation actually uses
    -- an average of vectors that each sum to 1 also sums to 1, so adding
    more midfield slots to a formation cannot mechanically inflate total
    job "importance".

v3 methodology (built after v2 turned out to let the formation's job-tag
table swing a unit score more than intended, diagnosed via a 4-3-3-flat
vs 4-2-3-1 breakdown on a real trio -- see the "Rodri/Bruno/Valverde"
diagnostic in conversation history):
  - Same per-player job capabilities and same p=1 share-weighting within
    each job as v2.
  - Before combining jobs, each job's pooled score is put on a common
    scale via a sigmoid centred on that job's real population mean/std
    (n=77 curated DM/CM/AM players) -- fixes progression's raw units
    running ~3x larger than creation's, which let a small formation-weight
    reallocation swing the unit score disproportionately depending on
    which job absorbed it. Sigmoid chosen over percentile-band min-max
    after testing 6 normalizers (p5-p95, p2-p98, p1-p99, full min-max,
    mean-ratio, sigmoid): the composition-vs-formation separation ratio
    stayed ~4.4-4.8x under ALL of them (so normalization choice mostly
    just rescales, doesn't change that qualitative property), but
    mean-ratio broke on retention's degenerate near-zero population mean
    (most players have 0 retention capability -- dividing by it produced
    wild ratios), and full min-max, while marginally best on this sample,
    is structurally exposed to a single future outlier player redefining
    the whole scale. Sigmoid saturates smoothly and doesn't depend on
    exact percentile cut points.
  - The formation's job-tag weight table is now only a PRIOR (alpha=0.5),
    blended with a personnel-driven "pool_share" (what THESE specific
    players' own capabilities actually support) so the formation doesn't
    unilaterally dictate emphasis -- confirmed via an alpha sweep (0.5
    down to 0.0) that this blend accounts for under 10% of v2's original
    formation-driven swing; most of it traced to the sigmoid normalization
    interacting with legitimate per-slot player_slot_fit() differences
    (e.g. Valverde: CM2 fit=0.62 vs DM1 fit=0.50), not the formation-tag
    table itself.
  - Net effect vs v2 on the same 4-3-3-flat/4-2-3-1 diagnostic: formation
    swing cut from -0.039 to -0.030 (a real reduction, not zero -- a
    player legitimately fitting one slot better than another should still
    matter), composition swing stayed strong at -0.137 (a ~4.5x
    separation, meaning who plays matters far more than the formation
    label).

Run directly for a formation-sensitivity comparison against v1:
    python midfield_contribution_v2.py
"""
from __future__ import annotations

import math
from typing import Any

import team_ratings as tr
from formation_fit import FORMATION_SLOTS
from models import PlayerStats
from slot_roles import slot_role

# Per-tag job-emphasis vectors, each summing to 1.0. Grounded in the
# existing per-slot "profile" stat-weight hints already in
# formation_fit.FORMATION_SLOTS (DM: tackles/interceptions/clearances-heavy;
# CM: passes/tackles balanced with modest key_passes; AM: key_passes/xa-
# heavy) -- not invented from scratch.
_TAG_JOB_WEIGHTS: dict[str, dict[str, float]] = {
    "dm": {"shielding": 0.50, "progression": 0.30, "retention": 0.15, "creation": 0.05},
    "cm": {"progression": 0.35, "shielding": 0.30, "creation": 0.20, "retention": 0.15},
    "am": {"creation": 0.55, "progression": 0.25, "retention": 0.10, "shielding": 0.10},
}

_JOBS = ("progression", "creation", "shielding", "retention")

_MIDFIELD_ROLES = frozenset({"dm", "cm", "am"})

# Affine calibration onto v1's scale, fit against n=130 real samples
# (10 curated teams x 13 formations, production personnel selection).
# v1: mean=0.5361 std=0.0609  v2: mean=0.2246 std=0.0228
# Matches mean AND spread (not just mean) -- percentiles (p10/p50/p90)
# lined up within ~0.01 of v1's after applying this, confirming it's not
# a mean-only coincidence. Individual player scores are NOT forced to
# match v1 -- only the unit's overall numeric range is put on comparable
# footing so the 0.24 weight in `overall` means the same thing for both.
V2_CAL_A = 2.6716
V2_CAL_B = -0.0639


def calibrate_v2(v2_raw: float) -> float:
    return V2_CAL_A * v2_raw + V2_CAL_B


def player_job_capabilities(stats: PlayerStats) -> dict[str, float]:
    """Same sub-terms as team_ratings._player_midfield_contrib, pre-fit,
    pre-blend -- capability only, role suitability applied later."""
    progression = (
        tr._scale(stats.xg_buildup90, 0.55) * 0.28
        + tr._scale(stats.passes_completed90, 65.0) * 0.18
        + tr._scale(stats.pass_pct, 100.0) * 0.12
        + tr._scale(stats.long_balls90, 8.0) * 0.06
        + tr._scale(stats.long_ball_pct, 100.0) * 0.04
    )
    creation = (
        tr._scale(stats.key_passes90, 2.5) * 0.14
        + tr._scale(stats.xa90, 0.55) * 0.12
        + tr._scale(stats.understat_key_passes90, 2.5) * 0.06
    )
    shielding = (
        tr._scale(stats.tackles90, 3.5) * 0.12
        + tr._scale(stats.interceptions90, 2.5) * 0.10
        + tr._duel_def_term(stats)
        + tr._press_resist_contrib(stats, 1.0, for_defence=False)
    )
    turnover_penalty = tr._scale(stats.possession_lost90, 12.0) * 0.22
    retention = max(0.0, 0.22 - turnover_penalty)
    return {
        "progression": progression,
        "creation": creation,
        "shielding": shielding,
        "retention": retention,
    }


def share_weighted_job_score(capabilities: list[float], p: float = 1.0) -> float:
    """Sigma(c_i^p / Sigma c_j^p * c_i). p=0 reduces to a plain average."""
    if not capabilities:
        return 0.0
    if p == 0 or all(c <= 0 for c in capabilities):
        return sum(capabilities) / len(capabilities)
    powed = [c**p if c > 0 else 0.0 for c in capabilities]
    total = sum(powed)
    if total <= 0:
        return sum(capabilities) / len(capabilities)
    weights = [pv / total for pv in powed]
    return sum(w * c for w, c in zip(weights, capabilities))


def formation_job_weights(formation: str) -> dict[str, float]:
    """Average the per-tag job vector across the formation's DM/CM/AM slots."""
    slots = FORMATION_SLOTS.get(formation)
    if not slots:
        return {j: 1.0 / len(_JOBS) for j in _JOBS}
    vectors = []
    for s in slots:
        role = slot_role(s["slot"])
        if role in _MIDFIELD_ROLES:
            vectors.append(_TAG_JOB_WEIGHTS[role])
    if not vectors:
        return {j: 1.0 / len(_JOBS) for j in _JOBS}
    return {j: sum(v[j] for v in vectors) / len(vectors) for j in _JOBS}


def compute_midfield_v1_and_v2(
    team, player_stats: dict[str, PlayerStats], p: float = 1.0
) -> tuple[float, float, dict[str, Any]]:
    """Mirrors the midfield-collection loop in
    team_ratings.compute_unit_ratings_by_slot, but also builds v2 in
    parallel. Returns (v1, v2, debug)."""
    v1_scores: list[float] = []
    job_caps: dict[str, list[float]] = {j: [] for j in _JOBS}
    contributors: list[str] = []

    for slot in team.lineup:
        stats = player_stats.get(slot.player)
        if stats is None:
            continue
        fit = tr._slot_fit(stats, team, slot)
        eff = tr._eff_slot(slot)
        role = slot_role(eff)
        if role not in _MIDFIELD_ROLES:
            continue
        v1_scores.append(tr._player_midfield_contrib(stats, fit))
        caps = player_job_capabilities(stats)
        for j in _JOBS:
            job_caps[j].append(caps[j] * (0.55 + 0.45 * fit))
        contributors.append(slot.player)

    v1 = sum(v1_scores) / len(v1_scores) if v1_scores else 0.28

    weights = formation_job_weights(team.formation)
    job_scores = {j: share_weighted_job_score(job_caps[j], p=p) for j in _JOBS}
    v2 = sum(weights[j] * job_scores[j] for j in _JOBS) if contributors else 0.28

    debug = {"contributors": contributors, "job_scores": job_scores, "weights": weights}
    return v1, v2, debug


# Population stats for sigmoid normalization, computed from n=77 real
# curated DM/CM/AM players (player_names.KNOWN_PLAYER_POSITIONS_BY_NAME).
_POP_JOB_MEAN = {
    "progression": 0.45934166080120953,
    "creation": 0.17131144934732534,
    "shielding": 0.15723152424450992,
    "retention": 0.023867562306752296,
}
_POP_JOB_STD = {
    "progression": 0.10813380719148272,
    "creation": 0.0696297093520366,
    "shielding": 0.04493538120015245,
    "retention": 0.03514046262506709,
}
_SIGMOID_K = 1.0

# Formation-tag weight table counts as only this much of the final
# "opportunity" allocation; the rest comes from what this specific
# personnel pool's own capabilities support (pool_share). See module
# docstring -- an alpha sweep from 1.0 to 0.0 showed this barely moves
# the formation-driven swing, so 0.5 is a defensible middle default
# rather than a load-bearing tuned constant.
V3_OPPORTUNITY_ALPHA = 0.5

# Affine calibration onto v1's scale, fit against the same n=130-sample
# methodology used for v2 (10 curated teams x 13 formations, production
# personnel selection). See calibrate_v2 for why this exists.
# v1: mean=0.5361 std=0.0610  v3: mean=0.4794 std=0.0707 (already much
# closer to v1's native range than v2 was, since sigmoid outputs land
# near [0,1] per job instead of v2's raw sub-term units).
V3_CAL_A = 0.8632
V3_CAL_B = 0.1224


def _sigmoid_normalize(value: float, job: str, k: float = _SIGMOID_K) -> float:
    mean, std = _POP_JOB_MEAN[job], _POP_JOB_STD[job]
    if std <= 0:
        return 0.5
    z = (value - mean) / (k * std)
    return 1.0 / (1.0 + math.exp(-z))


def calibrate_v3(v3_raw: float) -> float:
    return V3_CAL_A * v3_raw + V3_CAL_B


def compute_midfield_v3(
    team, player_stats: dict[str, PlayerStats], p: float = 1.0, alpha: float = V3_OPPORTUNITY_ALPHA
) -> tuple[float, dict[str, Any]]:
    """capability -> fit-adjusted -> share-weighted per job -> sigmoid-
    normalized to a comparable scale -> formation-prior/personnel-driven
    opportunity blend -> weighted sum. Returns (v3_raw, debug)."""
    job_caps_pool: dict[str, list[float]] = {j: [] for j in _JOBS}
    contributors: list[str] = []

    for slot in team.lineup:
        stats = player_stats.get(slot.player)
        if stats is None:
            continue
        eff = tr._eff_slot(slot)
        role = slot_role(eff)
        if role not in _MIDFIELD_ROLES:
            continue
        fit = tr._slot_fit(stats, team, slot)
        caps = player_job_capabilities(stats)
        for j in _JOBS:
            job_caps_pool[j].append(caps[j] * (0.55 + 0.45 * fit))
        contributors.append(slot.player)

    if not contributors:
        return 0.28, {"contributors": [], "raw_job_score": {}, "opportunity": {}}

    raw_job_score = {j: share_weighted_job_score(job_caps_pool[j], p=p) for j in _JOBS}
    common_job_score = {j: _sigmoid_normalize(raw_job_score[j], j) for j in _JOBS}

    prior = formation_job_weights(team.formation)
    total_raw = sum(raw_job_score.values()) or 1.0
    pool_share = {j: raw_job_score[j] / total_raw for j in _JOBS}
    blended = {j: alpha * prior[j] + (1 - alpha) * pool_share[j] for j in _JOBS}
    total_blend = sum(blended.values()) or 1.0
    opportunity = {j: blended[j] / total_blend for j in _JOBS}

    v3 = sum(opportunity[j] * common_job_score[j] for j in _JOBS)
    debug = {
        "contributors": contributors,
        "raw_job_score": raw_job_score,
        "common_job_score": common_job_score,
        "prior": prior,
        "pool_share": pool_share,
        "opportunity": opportunity,
    }
    return v3, debug


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from tools.formation_sweep import sweep as _v1_sweep
    from google_sheets_teams import load_team_by_name
    from web.state import get_stats_store

    teams = [
        "MasterSimulator FC", "Mao De Zong FC", "Sayaninjal FC", "Nesha Korechi FC",
        "Diddy's Didier FC", "Mikel Carrick FC", "Slip & Hop FC", "Council of Kangs",
        "Mid Village FC", "Painchester United",
    ]

    store = get_stats_store()

    def is_back3(f):
        return f.startswith("3-")

    def is_back4(f):
        return f.startswith("4-")

    W_MIDFIELD = 0.24

    for team_name in teams:
        rows = _v1_sweep(team_name)
        team_payload = load_team_by_name(team_name, store=store)
        full_roster = team_payload["sheet_meta"]["full_roster"]
        player_stats = store.cached_stats_map(full_roster)

        adj_rows = []
        for r in rows:
            from models import FantasyTeam

            team_obj = FantasyTeam.from_dict(
                {
                    "name": team_name,
                    "formation": r["formation"],
                    "lineup": [{"slot": row["slot"], "player": row["player"]} for row in r["lineup"]],
                    "bench": [],
                }
            )
            v1, v2, _ = compute_midfield_v1_and_v2(team_obj, player_stats, p=1.0)
            v3_raw, _ = compute_midfield_v3(team_obj, player_stats, p=1.0)
            v3 = calibrate_v3(v3_raw)
            overall_v2 = r["overall"] - W_MIDFIELD * r["midfield"] + W_MIDFIELD * v2
            overall_v3 = r["overall"] - W_MIDFIELD * r["midfield"] + W_MIDFIELD * v3
            adj_rows.append({**r, "midfield_v2": v2, "overall_v2": overall_v2, "midfield_v3": v3, "overall_v3": overall_v3})

        b4_v1 = max([r for r in adj_rows if is_back4(r["formation"])], key=lambda r: r["overall"])
        b3_v1 = max([r for r in adj_rows if is_back3(r["formation"])], key=lambda r: r["overall"])
        b4_v2 = max([r for r in adj_rows if is_back4(r["formation"])], key=lambda r: r["overall_v2"])
        b3_v2 = max([r for r in adj_rows if is_back3(r["formation"])], key=lambda r: r["overall_v2"])
        b4_v3 = max([r for r in adj_rows if is_back4(r["formation"])], key=lambda r: r["overall_v3"])
        b3_v3 = max([r for r in adj_rows if is_back3(r["formation"])], key=lambda r: r["overall_v3"])

        d_v1 = b3_v1["overall"] - b4_v1["overall"]
        d_v2 = b3_v2["overall_v2"] - b4_v2["overall_v2"]
        d_v3 = b3_v3["overall_v3"] - b4_v3["overall_v3"]

        print(f"== {team_name} ==")
        print(f"  v1: best4={b4_v1['formation']:<20} {b4_v1['overall']:.3f}   best3={b3_v1['formation']:<20} {b3_v1['overall']:.3f}   delta={d_v1:+.3f}")
        print(f"  v2: best4={b4_v2['formation']:<20} {b4_v2['overall_v2']:.3f}   best3={b3_v2['formation']:<20} {b3_v2['overall_v2']:.3f}   delta={d_v2:+.3f}")
        print(f"  v3: best4={b4_v3['formation']:<20} {b4_v3['overall_v3']:.3f}   best3={b3_v3['formation']:<20} {b3_v3['overall_v3']:.3f}   delta={d_v3:+.3f}")
        print()
