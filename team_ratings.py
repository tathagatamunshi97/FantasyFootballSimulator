"""Build attack / midfield / defence / GK unit ratings from blended player stats.

Calibration (v2.3):
- Progressive pool (xA, xG-buildup, xG-chain, key passes) split: 38% attack, 58% creation
  (96% total — avoids full double-count while crediting all positions).
- GK suppression: back line 54%, mid shield 32%, GK 14% (was 24%); GK rating compressed
  toward league avg 0.40 with 55% deviation retention.
- Overall rating GK weight 10% (was 14%).
"""

from __future__ import annotations



from dataclasses import dataclass, field
from typing import Any



from formation_fit import FORMATION_SLOTS, get_slot_definition, normalize_formation, player_slot_fit

from models import FantasyTeam, PlayerStats

from sample_confidence import (

    MIN_TRUSTED_MINUTES,

    is_backup_goalkeeper,

    reliability_multiplier,

    shrink_gk_stats,

)

from slot_roles import (
    FULLBACK_SLOTS,
    WINGER_SLOTS,
    effective_slot_name,
    slot_role,
    slot_unit_weights,
)


def _eff_slot(slot) -> str:
    """Formation slot remapped by optional role_filter for engine weights/roles."""
    return effective_slot_name(slot.slot, getattr(slot, "role_filter", "") or "")


def _slot_fit(stats: PlayerStats, team: FantasyTeam, slot) -> float:
    return player_slot_fit(
        stats, team.formation, slot.slot, role_filter=getattr(slot, "role_filter", "") or None
    )

# Slot-role buckets for unit ratings (only relevant players per unit).
_ATTACK_ROLES = frozenset({"winger", "striker", "am"})
_FINISHING_ROLES = frozenset({"winger", "striker", "am"})
_CREATION_ROLES = frozenset({"winger", "striker", "am", "cm", "fullback"})
_MIDFIELD_ROLES = frozenset({"dm", "cm", "am"})
_DEFENCE_ROLES = frozenset({"fullback", "centre_back"})
_MIDDEF_ROLES = frozenset({"dm", "cm"})


# --- calibration constants (documented for tuning) ---
LEAGUE_GK_RATING = 0.40
GK_DEVIATION_SCALE = 0.55  # retain 55% of deviation from league avg in suppression
DEFENCE_W, MIDDEF_W, GK_W = 0.54, 0.32, 0.14  # suppression blend (was 0.50/0.26/0.24)
PROGRESSIVE_ATTACK_SHARE = 0.38
PROGRESSIVE_CREATION_SHARE = 0.58
DUEL_DEF_WEIGHT = 0.12
AERIAL_DEF_WEIGHT = 0.10
PRESS_RESIST_DEF_WEIGHT = 0.08
PRESS_RESIST_MID_WEIGHT = 0.06
PRESS_XG_SUPPRESS_MIN = 0.03
PRESS_XG_SUPPRESS_MAX = 0.08
DUEL_CREATION_SUPPRESS_MAX = 0.04
_BACKLINE_POSITIONS = frozenset({"CB", "LB", "RB"})
_PRESS_CARRY_POSITIONS = frozenset({"CB", "LB", "RB", "DM", "CM"})
# Fullback/winger combination bonus: _fullback_attack_exposure already exists as a
# transition-risk *cost*; this is its bounded creation-rating *upside*, paid only
# when the wide player ahead of the fullback is a genuine threat (so a fullback
# doesn't get free credit just for bombing forward with no one to combine with).
FULLBACK_WINGER_COMBO_WEIGHT = 0.18





@dataclass

class UnitRatings:

    attack: float

    midfield: float

    defence: float

    goalkeeper: float

    overall: float

    finishing: float = 0.0

    chance_creation: float = 0.0

    midfield_defence: float = 0.0

    transition_risk: float = 0.0

    gk_confidence: float = 1.0

    gk_is_backup: bool = False

    # Per-player contributions behind each unit score, weakest first --
    # only populated by compute_unit_ratings_by_slot (the by-slot loop has
    # a real player/slot to attach to each score; compute_unit_ratings's
    # whole-XI loop is kept lean since nothing currently reads this from
    # there). {"finishing": [{"player":..., "slot":..., "score":...}, ...]}
    breakdown: dict[str, list[dict[str, Any]]] = field(default_factory=dict)





def _avg(values: list[float], default: float = 0.5) -> float:

    return sum(values) / len(values) if values else default





def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:

    return max(lo, min(hi, x))





_LEGEND_INFLATION = 1.2


def _legend_multiplier(stats: PlayerStats) -> float:
    """1.2x on every unit contribution for the 25 curated auction legends,
    across every unit (attack/creation/midfield/defence/gk) -- applied at
    the final contribution score, after fit and stat-profile math, not to
    the underlying stats themselves."""
    from manual_profiles import is_legend_name

    return _LEGEND_INFLATION if is_legend_name(stats.player) else 1.0


def _scale_uncapped(value: float, cap: float) -> float:
    """Same reference-point normalization as _scale, but no ceiling -- a
    player at 2x the reference rate scores 2.0, not clamped to 1.0. Used
    where an elite outlier (e.g. Doku's 5.26 dribbles90 against a 3.0
    reference) should keep earning credit past the "typical elite" mark,
    not get treated the same as someone who just touches it."""
    if cap <= 0:
        return 0.0
    return max(0.0, value / cap)


def _scale(value: float, cap: float) -> float:

    if cap <= 0:

        return 0.0

    return _clamp(value / cap)





def _player_progressive_raw(stats: PlayerStats) -> float:
    """xA / xG-buildup / xG-chain / key-pass involvement — shared across attack & creation."""
    xa = max(stats.xa90, stats.understat_xa90 or 0.0)
    kp = max(stats.key_passes90, stats.understat_key_passes90 or 0.0)
    return (
        _scale(xa, 0.55) * 0.24
        + _scale(stats.xg_buildup90, 0.55) * 0.28
        + _scale(stats.xg_chain90, 0.9) * 0.24
        + _scale(kp, 2.5) * 0.14
        + _scale(stats.assists90, 0.45) * 0.10
    )


def _player_attack_contrib(stats: PlayerStats, fit: float) -> float:
    """Finishing / shooting threat plus progressive involvement in attack chains."""
    # Uncapped: an elite outlier keeps earning credit past the reference
    # rate instead of saturating alongside anyone who merely reaches it
    # (e.g. Doku's 5.26 dribbles90 vs a 3.0 reference used to score
    # identically to a 3.0-dribbles90 player -- it no longer does).
    xg = stats.npxg90 or stats.xg90
    finisher = (
        _scale_uncapped(xg, 0.72) * 0.36
        + _scale_uncapped(stats.xg90, 0.72) * 0.16
        + _scale_uncapped(stats.shots90, 3.6) * 0.13
        + _scale_uncapped(stats.shots_on_target90, 2.2) * 0.09
        + _scale_uncapped(stats.big_chances_created90, 1.2) * 0.07
        + _scale_uncapped(max(0.0, stats.big_chances_created90 - stats.big_chances_missed90), 1.0) * 0.04
    )
    # Missing dribble% used to zero the carry term for sparse primes.
    drib_pct = stats.dribble_pct if stats.dribble_pct > 0 else 50.0
    carry = _scale_uncapped(stats.dribbles90, 3.0) * 0.10 * _scale_uncapped(drib_pct, 100.0)
    progressive = _player_progressive_raw(stats) * PROGRESSIVE_ATTACK_SHARE
    return (finisher + carry + progressive) * (0.55 + 0.45 * fit)





def _player_chance_creation_contrib(stats: PlayerStats, fit: float) -> float:
    """Chance creation: crosses, key passes, pre-assist buildup (progressive pool + big chances)."""
    progressive = _player_progressive_raw(stats) * PROGRESSIVE_CREATION_SHARE
    raw = (
        progressive
        + _scale(stats.big_chances_created90, 1.2) * 0.22
        + _scale(max(0.0, stats.big_chances_created90 - stats.big_chances_missed90), 1.0) * 0.06
    )
    return raw * (0.55 + 0.45 * fit)





def _duel_def_term(stats: PlayerStats, weight: float = DUEL_DEF_WEIGHT) -> float:
    """FotMob duel win rate — skip GKs / missing data (no penalty)."""
    if stats.fpl_position == "GK" or stats.duels_won_pct <= 0:
        return 0.0
    return _scale(stats.duels_won_pct, 100.0) * weight


def _aerial_def_term(stats: PlayerStats, weight: float = AERIAL_DEF_WEIGHT) -> float:
    """Modest aerial signal for CB/LB/RB from FotMob."""
    pos = (stats.primary_position or "").upper()
    roles = {p.upper() for p in (stats.positions or [])}
    if pos not in _BACKLINE_POSITIONS and not roles & _BACKLINE_POSITIONS:
        return 0.0
    if stats.aerials_won90 <= 0 and stats.aerials_won_pct <= 0:
        return 0.0
    win_rate = _scale(stats.aerials_won_pct, 100.0) if stats.aerials_won_pct > 0 else 0.55
    volume = _scale(stats.aerials_won90, 2.5)
    return (volume * 0.58 + win_rate * 0.42) * weight


def _player_press_resistance(stats: PlayerStats, fit: float) -> float:
    """Carry under pressure proxy — Sofascore dribbles90 × dribble success %."""
    if stats.fpl_position not in ("DEF", "MID"):
        return 0.0
    raw = _scale(stats.dribbles90, 2.5) * _scale(stats.dribble_pct, 100.0)
    return _clamp(raw) * (0.55 + 0.45 * fit)


def _press_resist_contrib(stats: PlayerStats, fit: float, *, for_defence: bool) -> float:
    pos = (stats.primary_position or "").upper()
    roles = {p.upper() for p in (stats.positions or [])}
    if not (pos in _PRESS_CARRY_POSITIONS or roles & _PRESS_CARRY_POSITIONS):
        return 0.0
    weight = PRESS_RESIST_DEF_WEIGHT if for_defence else PRESS_RESIST_MID_WEIGHT
    return _player_press_resistance(stats, fit) * weight


def _player_midfield_contrib(stats: PlayerStats, fit: float) -> float:

    progression = (

        _scale(stats.xg_buildup90, 0.55) * 0.28

        + _scale(stats.passes_completed90, 65.0) * 0.18

        + _scale(stats.pass_pct, 100.0) * 0.12

        + _scale(stats.long_balls90, 8.0) * 0.06

        + _scale(stats.long_ball_pct, 100.0) * 0.04

    )

    creation = (

        _scale(stats.key_passes90, 2.5) * 0.14

        + _scale(stats.xa90, 0.55) * 0.12

        + _scale(stats.understat_key_passes90, 2.5) * 0.06

    )

    defence = (

        _scale(stats.tackles90, 3.5) * 0.12

        + _scale(stats.interceptions90, 2.5) * 0.10

        + _duel_def_term(stats)

        + _press_resist_contrib(stats, fit, for_defence=False)

    )

    turnover_penalty = _scale(stats.possession_lost90, 12.0) * 0.22

    return _clamp((progression + creation + defence - turnover_penalty) * (0.55 + 0.45 * fit))





def _player_midfield_defence_contrib(stats: PlayerStats, fit: float) -> float:

    """Ball-winning / screening — used for midfield shield and transition cover."""

    raw = (

        _scale(stats.tackles90, 3.5) * 0.32

        + _scale(stats.interceptions90, 2.5) * 0.30

        + _scale(stats.clearances90, 6.0) * 0.18

        + _scale(stats.xg_buildup90, 0.4) * 0.05

        + _scale(max(0.0, 12.0 - stats.possession_lost90), 12.0) * 0.15

        + _duel_def_term(stats)

        + _press_resist_contrib(stats, fit, for_defence=False)

    )

    return raw * (0.6 + 0.4 * fit)





def _player_defence_contrib(stats: PlayerStats, fit: float) -> float:
    # Effectiveness-weighted, not activity-weighted -- the original version
    # (tackles 28% / interceptions 30% / clearances 22%) rewarded event
    # volume almost exclusively, which structurally penalises a defender
    # whose positioning prevents the danger in the first place (e.g. Van
    # Dijk: 71% duel win, 73% aerial win, but low tackle/interception
    # counts because he doesn't need to intervene as often). Verified via a
    # direct sensitivity test across 8 real centre-backs: re-weighting
    # toward duels/aerials moved a positioning-style defender up 2 full
    # ranks without disturbing a genuinely elite volume defender's own top
    # ranking -- confirming the old weights were under-crediting duel/
    # aerial dominance, not just reordering noise. Weights below are
    # proportionally rescaled from that tested "effectiveness" scheme
    # (tackles 15 / interceptions 15 / clearances 10 / duels 25 / aerial 20,
    # +15 for a "defensive outcomes" component) to still sum to 1.0 after
    # dropping the outcomes term -- goals-conceded-while-on-pitch isn't
    # tracked for outfield players (sofascore_client.py hardcodes it to 0.0
    # for everyone except goalkeepers) and no team-possession stat exists
    # anywhere in this data model to normalize busy-vs-quiet defenders, so
    # there's no real data to back that slice yet.
    raw = (
        _scale(stats.tackles90, 3.5) * 0.176
        + _scale(stats.interceptions90, 2.5) * 0.176
        + _scale(stats.clearances90, 6.0) * 0.118
        + _scale(stats.xg_buildup90, 0.4) * 0.05
        + _duel_def_term(stats, weight=0.294)
        + _aerial_def_term(stats, weight=0.235)
        + _press_resist_contrib(stats, fit, for_defence=True)
        # Direct penalty, not a positive addend blended into the weights
        # above: goals_conceded90 is FotMob's "goals conceded while on
        # pitch" (real per-90 team-outcome data, backfilled into the
        # cache for outfielders -- Sofascore hardcodes this to 0.0 for
        # non-GKs and FBref's equivalent was CAPTCHA-blocked when tried).
        # It's on a different scale than the 0-1 activity terms above, so
        # it's subtracted at its own raw per-90 rate instead of forced
        # through scale().
        - stats.goals_conceded90 * 0.15
    )
    return raw * (0.6 + 0.4 * fit)





def _fullback_attack_exposure(stats: PlayerStats, fit: float) -> float:

    """How much a fullback joins the attack (drives transition vulnerability)."""

    join_attack = (

        _scale(stats.xa90, 0.55) * 0.22

        + _scale(stats.key_passes90, 2.5) * 0.18

        + _scale(stats.xg_chain90, 0.9) * 0.15

        + _scale(stats.shots90, 4.0) * 0.12

        + _scale(stats.dribbles90, 3.0) * 0.10

        + _scale(stats.big_chances_created90, 1.2) * 0.15

    )

    return join_attack * (0.55 + 0.45 * fit)


def _wide_side(slot: str) -> str | None:
    """L/R side for a fullback or winger slot, else None (formations name slots by side)."""
    su = slot.upper()
    if su in FULLBACK_SLOTS or su in WINGER_SLOTS:
        if su.startswith("L"):
            return "L"
        if su.startswith("R"):
            return "R"
    return None


_LONE_WIDE_MID_DEFENCE_WEIGHT = 0.40
_WINGBACK_DEFENCE_WEIGHT = 0.60


def _is_lone_wide_mid(formation: str, slot_name: str) -> bool:
    """True if slot_name is RM/LM and this formation has no separate
    RB/LB/RWB/LWB on the same side -- this player is the only body
    covering that flank (e.g. 3-4-3(2), 3-4-1-2, 3-4-2-1), not a winger
    playing ahead of a real fullback (e.g. 4-4-2's RM/LM)."""
    su = slot_name.upper()
    if su not in {"RM", "LM"}:
        return False
    side = "R" if su == "RM" else "L"
    slots = FORMATION_SLOTS.get(normalize_formation(formation)) or []
    for s in slots:
        other = str(s.get("slot", "")).upper()
        if other in FULLBACK_SLOTS and other.startswith(side):
            return False
    return True


def _is_double_pivot_cm(formation: str, slot_name: str) -> bool:
    """True if slot_name is CM and this formation's central-mid structure
    is a genuine double pivot: exactly one DM + one CM screening behind a
    dedicated AM (e.g. 3-4-1-2 (normal)) -- not a CM in a 3-central-mid
    formation (4-3-3, 3-4-1-2 flat's DM1/DM2) or a DM+CM pairing with no
    AM ahead (4-4-2, 3-4-3(1)/(2)), where the CM is a genuine box-to-box
    role, not a pure screener paired 1-for-1 with a DM."""
    if slot_name.strip().upper() != "CM":
        return False
    slots = FORMATION_SLOTS.get(normalize_formation(formation)) or []
    dm_count = sum(1 for s in slots if slot_role(s.get("slot", "")) == "dm")
    cm_count = sum(1 for s in slots if slot_role(s.get("slot", "")) == "cm")
    am_count = sum(1 for s in slots if slot_role(s.get("slot", "")) == "am")
    return dm_count == 1 and cm_count == 1 and am_count >= 1


def _is_advanced_cm(formation: str, slot_name: str) -> bool:
    """True if slot_name is a CM (CM1/CM2, ...) in a formation fielding
    2+ CM slots -- e.g. 4-3-3 flat's CM1/CM2, 4-3-2-1's CM1/CM2, 4-3-1-2
    diamond, 3-5-2. A genuine central-mid pair/trio (as opposed to a
    single CM screening 1-for-1 with a DM, see _is_double_pivot_cm) isn't
    a pure holding unit -- each of them structurally shares the
    box-to-box/final-third duty, whether or not the formation also
    fields an AM (4-3-2-1 has two AMs *and* this CM pair; both still
    count). A single-CM formation (4-4-2, 3-4-3(1)/(2)) doesn't get this
    unconditional credit -- that lone CM still earns attack weight only
    if their own output profile clears the stat gate below."""
    su = slot_name.strip().upper()
    if not su.startswith("CM"):
        return False
    slots = FORMATION_SLOTS.get(normalize_formation(formation)) or []
    cm_count = sum(1 for s in slots if slot_role(s.get("slot", "")) == "cm")
    return cm_count >= 2


def _fullback_winger_combo_bonus(
    fb_stats: PlayerStats,
    fb_fit: float,
    winger: tuple[PlayerStats, float] | None,
) -> float:
    """Bounded creation-rating credit for a fullback overlapping/underlapping with a
    genuinely threatening winger on the same flank — combination play, not just any
    fullback pushing forward. Scales with both the fullback's own forward involvement
    (_fullback_attack_exposure) and the winger's actual creative threat, so a fullback
    paired with a purely defensive wide player earns little or nothing.
    """
    if winger is None:
        return 0.0
    winger_stats, winger_fit = winger
    exposure = _fullback_attack_exposure(fb_stats, fb_fit)
    winger_threat = _clamp(_player_chance_creation_contrib(winger_stats, winger_fit))
    return exposure * winger_threat * FULLBACK_WINGER_COMBO_WEIGHT


def _fullback_winger_partners(
    team: FantasyTeam,
    player_stats: dict[str, PlayerStats],
) -> dict[str, tuple[PlayerStats, float]]:
    """Map side ('L'/'R') -> (winger stats, fit) for wingers in the lineup, for the
    fullback-winger combination bonus. Formation-agnostic: no-winger formations
    (e.g. 3-5-2) simply yield no partner, so the bonus is 0 for those fullbacks.
    """
    partners: dict[str, tuple[PlayerStats, float]] = {}
    for slot in team.lineup:
        eff = _eff_slot(slot)
        if slot_role(eff) != "winger":
            continue
        side = _wide_side(eff)
        if side is None:
            continue
        stats = player_stats[slot.player]
        fit = _slot_fit(stats, team, slot)
        partners[side] = (stats, fit)
    return partners


def _player_gk_contrib(stats: PlayerStats, fit: float) -> tuple[float, float, bool]:

    shrunk = shrink_gk_stats(stats)

    conf = shrunk["confidence"]

    backup = is_backup_goalkeeper(stats)



    gp_weight = 0.22 if stats.minutes >= MIN_TRUSTED_MINUTES else 0.08

    rating_norm = _clamp((shrunk["rating"] - 6.2) / 1.2)

    conceded_norm = _clamp((1.25 - shrunk["goals_conceded90"]) / 1.25)

    gp_norm = _scale(shrunk["goals_prevented90"], 0.12)



    raw = (

        gp_norm * gp_weight

        + rating_norm * 0.30

        + conceded_norm * 0.32

        + _scale(shrunk["pass_pct"], 100.0) * 0.08

    )

    raw *= 0.6 + 0.4 * fit



    league_avg = 0.40

    regressed = conf * raw + (1.0 - conf) * league_avg

    regressed *= reliability_multiplier(stats.minutes)



    if backup:

        regressed = min(regressed, league_avg + 0.05 * conf)

        regressed *= 0.90



    return regressed, conf, backup





TWO_DM_FORMATIONS = frozenset({"3-4-1-2 (flat)", "4-2-3-1"})
THREE_BACK_FORMATIONS = frozenset(
    {"3-4-1-2 (flat)", "3-4-1-2 (normal)", "3-5-2", "3-4-3(1)", "3-4-3(2)", "3-4-2-1"}
)
# Wingbacks push higher than fullbacks, but a third centre-back holds the line behind them.
THREE_AT_BACK_EXPOSURE_SCALE = 0.66
THREE_AT_BACK_CB_COVER_BLEND = 0.28
THREE_AT_BACK_CB_SCREEN_WEIGHT = 0.48
THREE_AT_BACK_NON_DEF_WIDE_SCALE = 0.62
# LM/RM (attacking wide) push higher than LWB/RWB (balanced wingbacks).
ATTACKING_WIDE_MID_TRANSITION_SCALE = 1.18
BALANCED_WINGBACK_TRANSITION_SCALE = 0.95
# Kept for legacy transition-shield fallback; all current 3-back shapes now include a DM.
_NO_DM_THREE_BACK = frozenset()


def _count_centre_backs(team: FantasyTeam) -> int:
    return sum(1 for s in team.lineup if slot_role(s.slot) == "centre_back")


def _transition_cb_screen(team: FantasyTeam, player_stats: dict[str, PlayerStats]) -> float:
    """Screening from the back-three — compensates for advanced wingbacks."""
    scores: list[float] = []
    for slot in team.lineup:
        if slot_role(slot.slot) != "centre_back":
            continue
        stats = player_stats[slot.player]
        fit = player_slot_fit(stats, team.formation, slot.slot)
        scores.append(_player_defence_contrib(stats, fit) * THREE_AT_BACK_CB_SCREEN_WEIGHT)
    return _avg(scores, 0.38)


def _midfield_shield_best_slots(team: FantasyTeam, player_stats: dict[str, PlayerStats]) -> float:
    """Best-case DM/CM/AM screening for each midfielder — used for 4-back baseline ceiling."""
    by_player: list[float] = []
    for slot in team.lineup:
        if slot_role(_eff_slot(slot)) not in ("dm", "cm", "am"):
            continue
        stats = player_stats[slot.player]
        best = 0.0
        for probe in ("DM", "CM", "AM"):
            fit = player_slot_fit(stats, "4-3-3 attacking", probe)
            w = slot_unit_weights(probe, stats.fpl_position)
            best = max(best, _player_midfield_defence_contrib(stats, fit) * w.midfield_defence)
        by_player.append(best)
    by_player.sort(reverse=True)
    dm = by_player[0] if by_player else 0.38
    cm = by_player[1] if len(by_player) > 1 else 0.38
    am = by_player[2] if len(by_player) > 2 else 0.0
    return 0.68 * dm + 0.32 * cm + 0.14 * am


def _four_back_transition_baseline(
    team: FantasyTeam,
    player_stats: dict[str, PlayerStats],
) -> float:
    """Nominal 4-back transition risk using DEF players at RB/LB — ceiling for 3-at-the-back."""
    formation = normalize_formation(team.formation)
    fb_exposure: list[float] = []
    all_def_wide: list[float] = []
    seen: set[str] = set()
    for slot in team.lineup:
        stats = player_stats[slot.player]
        if stats.fpl_position != "DEF" or slot.player in seen:
            continue
        seen.add(slot.player)
        role = slot_role(slot.slot)
        exp_rb = _fullback_attack_exposure(stats, player_slot_fit(stats, "4-3-3 attacking", "RB"))
        exp_lb = _fullback_attack_exposure(stats, player_slot_fit(stats, "4-3-3 attacking", "LB"))
        wide_exp = max(exp_rb, exp_lb)
        all_def_wide.append(wide_exp)
        if role != "centre_back" and (
            role == "fullback" or _counts_as_transition_exposure(formation, slot.slot, role)
        ):
            fb_exposure.append(wide_exp)
    if not fb_exposure:
        fb_exposure = all_def_wide
    if not fb_exposure:
        return 0.48
    exposure = max(fb_exposure)
    cover = _midfield_shield_best_slots(team, player_stats)
    uncovered = max(0.08, 1.0 - cover * 0.95)
    return _clamp(exposure * uncovered * 1.35, 0.0, 0.48)


def _slot_has_wingback_tag(formation: str, slot: str) -> bool:
    slot_def = get_slot_definition(formation, slot)
    if slot_def is None:
        return False
    return "WB" in {t.upper() for t in slot_def.get("tags", [])}


def _counts_as_transition_exposure(formation: str, slot: str, role: str) -> bool:
    su = slot.upper()
    if su in FULLBACK_SLOTS or role == "fullback":
        return True
    if _slot_has_wingback_tag(formation, slot):
        return True
    return False


def _transition_mid_cover(
    formation: str,
    dm_cover: list[float],
    cm_cover: list[float],
    am_cover: list[float],
) -> float:
    """Formation-aware midfield shield for transition risk."""
    formation = normalize_formation(formation)
    dm_avg = _avg(dm_cover, 0.38)
    cm_avg = _avg(cm_cover, 0.38)
    am_avg = _avg(am_cover, 0.0)

    if formation == "4-3-3 flat":
        # Flat three: DM anchor plus CM pair shares the AM screening weight (no #10).
        cms = cm_cover if cm_cover else [cm_avg]
        return 0.68 * dm_avg + (0.32 + 0.14) * (sum(cms) / len(cms))

    if formation in THREE_BACK_FORMATIONS and dm_cover:
        # 3-at-the-back with a DM pivot: same DM-heavy shield as 4-3-3 attacking.
        return 0.68 * dm_avg + 0.32 * cm_avg + 0.14 * am_avg

    if formation in _NO_DM_THREE_BACK and not dm_cover and cm_cover:
        # No dedicated DM: lean on the best central screener in the midfield three/four.
        best = max(cm_cover)
        avg = sum(cm_cover) / len(cm_cover)
        return 0.55 * best + 0.45 * avg

    if formation == "4-3-1-2 diamond":
        shield = list(dm_cover) + list(cm_cover) + list(am_cover)
        if shield:
            return sum(shield) / len(shield)
        return 0.38

    if formation in {"4-3-3 attacking", "4-3-2-1", "4-2-2-2"}:
        return 0.68 * dm_avg + 0.32 * cm_avg + 0.14 * am_avg

    if formation in TWO_DM_FORMATIONS or len(dm_cover) >= 2:
        rest = list(cm_cover) + list(am_cover)
        if rest:
            return 0.55 * dm_avg + 0.45 * (sum(rest) / len(rest))
        return dm_avg

    if len(dm_cover) + len(cm_cover) >= 3 and not am_cover:
        shield = list(dm_cover) + list(cm_cover)
        return sum(shield) / len(shield)

    return 0.68 * dm_avg + 0.32 * cm_avg


def _compute_transition_risk(

    team: FantasyTeam,

    player_stats: dict[str, PlayerStats],

) -> float:

    """

    Attacking fullbacks / wingbacks increase transition exposure when midfield cannot cover.

    High creation wide defenders (e.g. Dumfries) push forward; central mids must shield the space.

    """

    formation = normalize_formation(team.formation)
    fb_exposure: list[float] = []
    dm_cover: list[float] = []
    cm_cover: list[float] = []
    am_cover: list[float] = []

    cb_count = _count_centre_backs(team)

    for slot in team.lineup:
        stats = player_stats[slot.player]
        eff = _eff_slot(slot)
        fit = _slot_fit(stats, team, slot)
        role = slot_role(eff)

        if _counts_as_transition_exposure(formation, eff, role):
            exp = _fullback_attack_exposure(stats, fit)
            su = eff.upper()
            if su in {"LM", "RM"}:
                # Attacking wide mids get forward more → higher transition risk.
                exp *= ATTACKING_WIDE_MID_TRANSITION_SCALE
            elif su in {"LWB", "RWB"}:
                # Balanced wingbacks: contribute both ways, less aggressive push.
                exp *= BALANCED_WINGBACK_TRANSITION_SCALE
            if cb_count >= 3 and stats.fpl_position != "DEF":
                exp *= THREE_AT_BACK_NON_DEF_WIDE_SCALE
            fb_exposure.append(exp)
        if role == "dm":
            w = slot_unit_weights(eff, stats.fpl_position)
            dm_cover.append(_player_midfield_defence_contrib(stats, fit) * w.midfield_defence)
        if role == "cm":
            w = slot_unit_weights(eff, stats.fpl_position)
            cm_cover.append(_player_midfield_defence_contrib(stats, fit) * w.midfield_defence)
        if role == "am":
            w = slot_unit_weights(eff, stats.fpl_position)
            am_cover.append(_player_midfield_defence_contrib(stats, fit) * w.midfield_defence)

    if not fb_exposure:
        return 0.0

    # The most aggressive wide defender drives transition exposure (not the pair average).
    exposure = max(fb_exposure)
    cover = _transition_mid_cover(formation, dm_cover, cm_cover, am_cover)
    if cb_count >= 3:
        cb_screen = _transition_cb_screen(team, player_stats)
        cover = (1.0 - THREE_AT_BACK_CB_COVER_BLEND) * cover + THREE_AT_BACK_CB_COVER_BLEND * cb_screen
        exposure *= THREE_AT_BACK_EXPOSURE_SCALE
    uncovered = max(0.08, 1.0 - cover * 0.95)
    risk = _clamp(exposure * uncovered * 1.35, 0.0, 0.48)
    if cb_count >= 3:
        has_def_at_wide = any(
            player_stats[s.player].fpl_position == "DEF"
            and (
                slot_role(_eff_slot(s)) == "fullback"
                or _counts_as_transition_exposure(formation, _eff_slot(s), slot_role(_eff_slot(s)))
            )
            for s in team.lineup
        )
        if has_def_at_wide:
            baseline = _four_back_transition_baseline(team, player_stats)
            risk = min(risk, baseline)
    return risk





def compute_unit_ratings(

    team: FantasyTeam,

    player_stats: dict[str, PlayerStats],

) -> UnitRatings:

    finishing_scores: list[float] = []

    creation_scores: list[float] = []

    midfield_scores: list[float] = []

    defence_scores: list[float] = []

    midfield_defence_scores: list[float] = []

    gk_scores: list[float] = []

    gk_conf = 1.0

    gk_backup = False

    wide_partners = _fullback_winger_partners(team, player_stats)



    for slot in team.lineup:

        stats = player_stats[slot.player]

        fit = _slot_fit(stats, team, slot)
        eff = _eff_slot(slot)

        weights = slot_unit_weights(eff, stats.fpl_position)



        if stats.fpl_position == "GK":

            score, conf, backup = _player_gk_contrib(stats, fit)

            gk_scores.append(score)

            gk_conf = conf

            gk_backup = backup

            continue



        finishing_scores.append(_player_attack_contrib(stats, fit) * weights.attack)

        creation = _player_chance_creation_contrib(stats, fit)
        if slot_role(eff) == "fullback":
            side = _wide_side(eff)
            creation += _fullback_winger_combo_bonus(stats, fit, wide_partners.get(side) if side else None)
        creation_scores.append(creation * weights.creation)

        midfield_scores.append(_player_midfield_contrib(stats, fit) * weights.midfield)

        defence_scores.append(_player_defence_contrib(stats, fit) * weights.defence)

        midfield_defence_scores.append(

            _player_midfield_defence_contrib(stats, fit) * weights.midfield_defence

        )



    finishing_top = sorted(finishing_scores, reverse=True)[:5]

    creation_top = sorted(creation_scores, reverse=True)[:5]

    # Average top finishers (not /2) — /2 saturated almost every squad at 1.00 after atk-fin.
    finishing = _clamp(sum(finishing_top) / 3.0 if finishing_top else 0.0)

    chance_creation = _clamp(sum(creation_top) / 3.0 if creation_top else 0.0)

    attack = _clamp(0.56 * finishing + 0.44 * chance_creation)



    midfield = _avg(midfield_scores)

    defence = _avg(defence_scores)

    midfield_defence = _avg(midfield_defence_scores)

    goalkeeper = _avg(gk_scores, default=0.5)

    transition_risk = _compute_transition_risk(team, player_stats)



    overall = (

        0.30 * attack

        + 0.24 * midfield

        + 0.22 * defence

        + 0.10 * goalkeeper

        + 0.12 * midfield_defence

        + 0.04 * (1.0 - transition_risk)

    )

    return UnitRatings(

        attack=round(attack, 3),

        finishing=round(finishing, 3),

        chance_creation=round(chance_creation, 3),

        midfield=round(midfield, 3),

        defence=round(defence, 3),

        midfield_defence=round(midfield_defence, 3),

        transition_risk=round(transition_risk, 3),

        goalkeeper=round(goalkeeper, 3),

        overall=round(overall, 3),

        gk_confidence=round(gk_conf, 3),

        gk_is_backup=gk_backup,

    )


def _top_n_avg(scores: list[float], n: int, *, divisor: float | None = None) -> float:
    if not scores:
        return 0.0
    top = sorted(scores, reverse=True)[:n]
    total = sum(top)
    if divisor is not None:
        return _clamp(total / divisor)
    return _clamp(_avg(top))


def compute_unit_ratings_by_slot(
    team: FantasyTeam,
    player_stats: dict[str, PlayerStats],
) -> UnitRatings:
    """Unit ratings from slot-relevant players only (no whole-XI dilution)."""
    finishing_scores: list[float] = []
    creation_scores: list[float] = []
    attack_scores: list[float] = []
    midfield_scores: list[float] = []
    defence_scores: list[float] = []
    midfield_defence_scores: list[float] = []
    gk_scores: list[float] = []
    gk_conf = 1.0
    gk_backup = False
    wide_partners = _fullback_winger_partners(team, player_stats)

    # Parallel to the *_scores lists above -- who contributed each score, so
    # a report can name the actual players behind a low unit rating instead
    # of just showing the averaged number. Only populated here (not in
    # compute_unit_ratings's whole-XI loop, which nothing currently reads
    # a breakdown from).
    breakdown: dict[str, list[dict[str, Any]]] = {
        "finishing": [],
        "chance_creation": [],
        "attack": [],
        "midfield": [],
        "defence": [],
        "midfield_defence": [],
    }

    for slot in team.lineup:
        stats = player_stats[slot.player]
        fit = _slot_fit(stats, team, slot)
        eff = _eff_slot(slot)
        role = slot_role(eff)
        legend_mult = _legend_multiplier(stats)

        if stats.fpl_position == "GK" or role == "gk":
            score, conf, backup = _player_gk_contrib(stats, fit)
            score *= legend_mult
            gk_scores.append(score)
            gk_conf = conf
            gk_backup = backup
            continue

        if role in _FINISHING_ROLES:
            score = _player_attack_contrib(stats, fit) * legend_mult
            finishing_scores.append(score)
            breakdown["finishing"].append({"player": slot.player, "slot": slot.slot, "score": round(score, 3)})
        if role in _CREATION_ROLES:
            creation = _player_chance_creation_contrib(stats, fit)
            if role == "fullback":
                side = _wide_side(eff)
                creation += _fullback_winger_combo_bonus(stats, fit, wide_partners.get(side) if side else None)
            creation *= legend_mult
            creation_scores.append(creation)
            breakdown["chance_creation"].append(
                {"player": slot.player, "slot": slot.slot, "score": round(creation, 3)}
            )
        if role in _ATTACK_ROLES:
            # Winger/striker get full weight -- attack is unambiguously
            # their primary job. AM is discounted to 0.75: still a
            # dedicated advanced-playmaking slot (full, unconditional
            # credit unlike CM), but genuinely a notch behind a real
            # winger/striker's end product, not equal to it. RM/LM are
            # discounted further, to 0.7 -- they split real defensive
            # duty for that flank (see _LONE_WIDE_MID_DEFENCE_WEIGHT
            # below), so their attacking output isn't the same full-time
            # threat as an RW/LW who starts every phase already advanced.
            is_wide_mid = slot.slot.strip().upper() in {"RM", "LM"}
            if role == "am":
                role_weight = 0.75
            elif is_wide_mid:
                role_weight = 0.7
            else:
                role_weight = 1.0
            atk_score = (
                0.56 * _player_attack_contrib(stats, fit) + 0.44 * _player_chance_creation_contrib(stats, fit)
            ) * role_weight * legend_mult
            attack_scores.append(atk_score)
            breakdown["attack"].append({"player": slot.player, "slot": slot.slot, "score": round(atk_score, 3)})
        elif role == "cm":
            # A CM (never DM -- DM's job stays defensive regardless of
            # output profile, no attack credit at all) whose own output
            # profiles as genuinely attacking (same screen-vs-create
            # signal used to gate DM eligibility elsewhere) contributes
            # to attack too, at 0.6.
            # A CM screening in a genuine double pivot (paired 1-for-1
            # with a DM behind a dedicated AM, e.g. 3-4-1-2 normal) gets
            # no attack credit regardless of their own output profile --
            # that shape asks them to hold, not join the final third.
            # A CM in a formation fielding 2+ CM slots (4-3-3's CM1/CM2,
            # 4-3-2-1's CM1/CM2, 4-3-1-2 diamond, 3-5-2) structurally
            # shares the final-third duty instead of pure screening --
            # exposed higher up by the shape itself, so they earn the
            # bonus unconditionally, whether or not the formation also
            # fields an AM. A single-CM formation (4-4-2, 3-4-3(1)/(2))
            # still needs its lone CM's own output to clear the bar.
            is_advanced = _is_advanced_cm(team.formation, slot.slot)
            if _is_double_pivot_cm(team.formation, slot.slot):
                screen_signal = create_signal = 0.0
            else:
                screen_signal = stats.tackles90 / 3.5 + stats.interceptions90 / 2.5 + stats.duels_won_pct / 100.0
                create_signal = stats.key_passes90 / 2.5 + stats.xa90 / 0.55
            if is_advanced or create_signal > screen_signal:
                atk_score = (
                    0.56 * _player_attack_contrib(stats, fit) + 0.44 * _player_chance_creation_contrib(stats, fit)
                ) * 0.60 * legend_mult
                attack_scores.append(atk_score)
                breakdown["attack"].append({"player": slot.player, "slot": slot.slot, "score": round(atk_score, 3)})
        if role in _MIDFIELD_ROLES:
            score = _player_midfield_contrib(stats, fit) * legend_mult
            midfield_scores.append(score)
            breakdown["midfield"].append({"player": slot.player, "slot": slot.slot, "score": round(score, 3)})
        if role in _DEFENCE_ROLES:
            # RWB/LWB carry the same last-line duty as a plain RB/LB when
            # summed into a fixed-reference total, but their real emphasis
            # skews more attacking (see slot_roles.py's wing-back weights)
            # -- discounted, not full weight, so a back-3 fielding 2
            # wing-backs on top of 3 CBs doesn't just add 2 full extra
            # bodies' worth of defence on top of a back-4's 4.
            w = _WINGBACK_DEFENCE_WEIGHT if slot.slot.upper() in {"RWB", "LWB"} else 1.0
            score = _player_defence_contrib(stats, fit) * w * legend_mult
            defence_scores.append(score)
            breakdown["defence"].append({"player": slot.player, "slot": slot.slot, "score": round(score, 3)})
        elif role == "winger" and _is_lone_wide_mid(team.formation, slot.slot):
            # RM/LM with no fullback behind them (e.g. 3-4-3(2), 3-4-1-2,
            # 3-4-2-1) carry real, if reduced, defensive responsibility for
            # that flank -- unlike a winger playing ahead of a genuine
            # fullback (4-4-2), where the fullback covers instead. Blended
            # in at a reduced weight, not full fullback weight: they start
            # too high up the pitch to recover as completely as a real
            # wing-back.
            score = _player_defence_contrib(stats, fit) * _LONE_WIDE_MID_DEFENCE_WEIGHT * legend_mult
            defence_scores.append(score)
            breakdown["defence"].append({"player": slot.player, "slot": slot.slot, "score": round(score, 3)})
        if role in _MIDDEF_ROLES:
            w = 1.0 if role == "dm" else 0.72
            score = _player_midfield_defence_contrib(stats, fit) * w * legend_mult
            midfield_defence_scores.append(score)
            breakdown["midfield_defence"].append({"player": slot.player, "slot": slot.slot, "score": round(score, 3)})

    for rows in breakdown.values():
        rows.sort(key=lambda r: r["score"])

    # Summative, not averaged -- every unit is now summative, per explicit
    # instruction: a genuine extra finishing/creation threat should add
    # real credit on top of the primary contributors, not get diluted.
    finishing = sum(finishing_scores) if finishing_scores else 0.5
    chance_creation = sum(creation_scores) if creation_scores else 0.5
    # Summative, not averaged: same reasoning as defence/midfield_defence --
    # a formation genuinely fielding more attacking threats (e.g. an AM on
    # top of both wingers and the striker, or a CM earning the 80% attack
    # bonus above) should add real credit on top of what a leaner shape
    # provides, not get diluted toward whichever contributor is weakest.
    # Raw sum, not normalized by a reference count -- runs on a materially
    # larger scale than the old top-3 average, so `overall`'s attack weight
    # is rescaled down accordingly below.
    attack = sum(attack_scores) if attack_scores else 0.56 * finishing + 0.44 * chance_creation
    # Summative, not averaged -- same reasoning as attack/defence: a
    # genuine extra body (a 3rd competent central mid on top of a
    # DM/CM pair, e.g. 4-3-3 flat's DM+CM1+CM2 vs a 2-man 3-4-3(2) pivot)
    # should add real coverage, possession retention, and progression
    # credit on top of what the primary pair already provides, not get
    # diluted toward whichever of the three is weakest. Raw sum, not
    # normalized by a reference count -- runs on a materially larger
    # scale than the old average, so `overall`'s midfield weight is
    # rescaled down accordingly below.
    #
    # NOTE: this reverses an earlier closed investigation
    # (midfield_contribution_v2.py) that deliberately kept midfield as a
    # plain average specifically to avoid rewarding body count over
    # quality. That conclusion no longer applies now that summative
    # aggregation is the deliberate, explicit design for every unit.
    midfield = sum(midfield_scores) if midfield_scores else 0.28
    # Summative, not averaged: a genuine extra body (3 CBs + 2 discounted
    # wing-backs vs a plain back-4; or a 3rd screening midfielder on top
    # of a DM/CM pair) should add real credit on top of what the primary
    # contributors already provide, not get diluted toward a weak one or
    # inflated purely by outnumbering a leaner shape. Raw sum, not
    # averaged and not normalized by a reference count -- this runs on a
    # materially larger scale than the old average, so `overall`'s weights
    # for defence/midfield_defence are rescaled down accordingly below.
    defence = sum(defence_scores) if defence_scores else 0.18
    midfield_defence = sum(midfield_defence_scores) if midfield_defence_scores else 0.12
    goalkeeper = sum(gk_scores) if gk_scores else 0.5  # summative; XI always fields exactly one keeper so no scale change
    transition_risk = _compute_transition_risk(team, player_stats)

    # attack/defence/midfield_defence are now raw summative sums (no
    # averaging), so every one of them runs on a materially larger scale
    # than its old averaged/top-N form -- overall's weights are rescaled
    # down per-unit to compensate, not reused as-is. Measured across the
    # curated league: attack's sum runs ~4x its old top-3-average scale;
    # midfield's sum runs ~5x its old plain-average scale (a formation
    # can field 2-5 midfield-role bodies, vs attack's/finishing's usual
    # top-3 ceiling). goalkeeper is unaffected -- an XI always fields
    # exactly one keeper, so sum == the old average. midfield_defence
    # gets less than a pure proportional rescale on top of its own
    # factor, per explicit guidance that mid-defence should carry a
    # smaller share of overall than defence/midfield do.
    overall = (
        0.15 * attack
        + 0.06 * midfield
        + 0.075 * defence
        + 0.10 * goalkeeper
        + 0.03 * midfield_defence
        + 0.04 * (1.0 - transition_risk)
    )
    return UnitRatings(
        attack=round(attack, 3),
        finishing=round(finishing, 3),
        chance_creation=round(chance_creation, 3),
        midfield=round(midfield, 3),
        defence=round(defence, 3),
        midfield_defence=round(midfield_defence, 3),
        transition_risk=round(transition_risk, 3),
        goalkeeper=round(goalkeeper, 3),
        overall=round(overall, 3),
        breakdown=breakdown,
        gk_confidence=round(gk_conf, 3),
        gk_is_backup=gk_backup,
    )


@dataclass
class TeamComposites:
    """Whole-XI composite scores (team shape / profile, not slot-pure units)."""

    creativity: float
    midfield_control: float
    possession_control: float
    finishing_threat: float
    defensive_solidity: float
    attacking_effectiveness: float
    pressing_intensity: float
    press_resistance: float
    transition_threat: float
    aerial_defence: float
    overall: float

    # Per-player contributions behind press_resistance, weakest first --
    # the only team-composite with an obvious per-player decomposition
    # (the others blend whole-line stat averages, not an averaged list of
    # individual scores in the same shape). See UnitRatings.breakdown.
    breakdown: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def compute_team_composites(
    team: FantasyTeam,
    player_stats: dict[str, PlayerStats],
    *,
    units: UnitRatings | None = None,
) -> TeamComposites:
    """Composite team-profile metrics across the full starting XI."""
    lineup_stats = [player_stats[s.player] for s in team.lineup]
    defs = [p for p in lineup_stats if p.fpl_position == "DEF"]
    mids = [p for p in lineup_stats if p.fpl_position == "MID"]
    fwds = [p for p in lineup_stats if p.fpl_position == "FWD"]
    mid_line = mids + defs

    if units is None:
        units = compute_unit_ratings_by_slot(team, player_stats)

    creativity = _clamp(
        _scale(_avg([p.key_passes90 for p in lineup_stats]), 2.0) * 0.22
        + _scale(_avg([p.xa90 for p in lineup_stats]), 0.45) * 0.22
        + _scale(_avg([p.big_chances_created90 for p in lineup_stats]), 0.9) * 0.22
        + _scale(_avg([p.xg_chain90 for p in lineup_stats]), 0.85) * 0.18
        + _scale(_avg([p.understat_key_passes90 for p in lineup_stats]), 2.0) * 0.16
    )
    possession_control = _clamp(
        _scale(_avg([p.passes_completed90 for p in mid_line + defs]), 55.0) * 0.30
        + _scale(_avg([p.pass_pct for p in lineup_stats]), 100.0) * 0.25
        + _scale(_avg([p.xg_buildup90 for p in mid_line]), 0.65) * 0.25
        + _scale(12.0 - _avg([p.possession_lost90 for p in mid_line]), 12.0) * 0.20
    )
    midfield_control = _clamp(
        0.45 * units.midfield
        + 0.30 * possession_control
        + 0.15 * units.midfield_defence
        + 0.10 * _scale(_avg([p.tackles90 + p.interceptions90 for p in mids]), 4.5)
    )
    finishing_threat = _clamp(
        _scale(_avg([p.xg90 for p in fwds]), 0.72) * 0.30
        + _scale(_avg([p.npxg90 for p in fwds]), 0.65) * 0.20
        + _scale(_avg([p.shots90 for p in fwds]), 3.6) * 0.15
        + _scale(_avg([p.shots_on_target90 for p in fwds]), 2.0) * 0.10
        + units.finishing * 0.25
    )
    duel_bearers = [p for p in defs + mids if p.duels_won_pct > 0]
    avg_duel_pct = _avg([p.duels_won_pct for p in duel_bearers], default=0.0) if duel_bearers else 0.0
    press_resist_scores: list[float] = []
    press_resist_breakdown: list[dict[str, Any]] = []
    for slot in team.lineup:
        st = player_stats[slot.player]
        if st.fpl_position in ("DEF", "MID"):
            fit = player_slot_fit(st, team.formation, slot.slot)
            score = _player_press_resistance(st, fit)
            press_resist_scores.append(score)
            press_resist_breakdown.append({"player": slot.player, "slot": slot.slot, "score": round(score, 3)})
    press_resist_breakdown.sort(key=lambda r: r["score"])
    press_resistance = _clamp(_avg(press_resist_scores, default=0.0))
    attacking_effectiveness = _clamp(
        _scale(_avg([p.xg90 for p in fwds]), 0.85) * 0.30
        + _scale(_avg([p.npxg90 for p in fwds]), 0.75) * 0.20
        + _scale(_avg([p.shots90 for p in fwds]), 4.0) * 0.15
        + _scale(_avg([p.shots_on_target90 for p in fwds]), 2.0) * 0.10
        + units.attack * 0.25
    )
    defensive_solidity = _clamp(
        _scale(_avg([p.tackles90 for p in defs]), 2.5) * 0.25
        + _scale(_avg([p.interceptions90 for p in defs]), 1.8) * 0.25
        + _scale(_avg([p.clearances90 for p in defs]), 5.0) * 0.20
        + units.defence * 0.20
        + units.goalkeeper * 0.10
        + (_scale(avg_duel_pct, 100.0) * 0.06 if avg_duel_pct > 0 else 0.0)
    )
    pressing_base = _scale(_avg([p.tackles90 + p.interceptions90 for p in lineup_stats]), 4.5)
    pressing_intensity = _clamp(
        pressing_base * (0.72 if avg_duel_pct > 0 else 1.0)
        + (_scale(avg_duel_pct, 100.0) * 0.28 if avg_duel_pct > 0 else 0.0)
    )
    transition_threat = _clamp(_scale(_avg([p.dribbles90 for p in fwds + mids]), 2.5))
    aerial_signals = []
    for p in defs:
        if p.aerials_won90 > 0:
            win_rate = p.aerials_won_pct / 100.0 if p.aerials_won_pct > 0 else 0.55
            aerial_signals.append(p.aerials_won90 * max(0.45, win_rate))
        else:
            aerial_signals.append(p.clearances90 * 0.45)
    aerial_defence = _clamp(
        _scale(_avg(aerial_signals), 2.8) * 0.65
        + _scale(_avg([p.clearances90 for p in defs]), 5.5) * 0.35
    )
    defensive_solidity = _clamp(
        defensive_solidity * 0.92 + aerial_defence * 0.08
    )

    overall = (
        0.18 * creativity
        + 0.16 * midfield_control
        + 0.14 * possession_control
        + 0.16 * finishing_threat
        + 0.14 * defensive_solidity
        + 0.12 * attacking_effectiveness
        + 0.10 * (1.0 - units.transition_risk)
    )
    return TeamComposites(
        creativity=round(creativity, 3),
        midfield_control=round(midfield_control, 3),
        possession_control=round(possession_control, 3),
        finishing_threat=round(finishing_threat, 3),
        defensive_solidity=round(defensive_solidity, 3),
        attacking_effectiveness=round(attacking_effectiveness, 3),
        pressing_intensity=round(pressing_intensity, 3),
        press_resistance=round(press_resistance, 3),
        transition_threat=round(transition_threat, 3),
        aerial_defence=round(aerial_defence, 3),
        overall=round(overall, 3),
        breakdown={"press_resistance": press_resist_breakdown},
    )


def team_composites_dict(c: TeamComposites) -> dict[str, float]:
    return {
        "creativity": c.creativity,
        "midfield_control": c.midfield_control,
        "possession_control": c.possession_control,
        "finishing_threat": c.finishing_threat,
        "defensive_solidity": c.defensive_solidity,
        "attacking_effectiveness": c.attacking_effectiveness,
        "pressing_intensity": c.pressing_intensity,
        "press_resistance": c.press_resistance,
        "transition_threat": c.transition_threat,
        "aerial_defence": c.aerial_defence,
        "overall": c.overall,
        "breakdown": c.breakdown,
    }


def midfield_battle_multiplier(home_mid: float, away_mid: float) -> tuple[float, float]:

    """Return chance multipliers from midfield dominance (-8% to +8% approx)."""

    delta = home_mid - away_mid

    home_mult = 1.0 + 0.10 * max(-0.8, min(0.8, delta))

    away_mult = 1.0 - 0.10 * max(-0.8, min(0.8, delta))

    return home_mult, away_mult





def _effective_gk_rating(goalkeeper_rating: float) -> float:
    """Compress GK deviation from league average to limit match-swing impact."""
    return LEAGUE_GK_RATING + GK_DEVIATION_SCALE * (goalkeeper_rating - LEAGUE_GK_RATING)


def defence_suppression(

    defence_rating: float,

    goalkeeper_rating: float,

    midfield_defence_rating: float,

    transition_risk: float = 0.0,

) -> float:

    """

    Multiplier applied to opponent attack xG (lower = better defence).

    Back line + GK + midfield shield; transition risk weakens structural defence.

    """

    combined = (

        DEFENCE_W * defence_rating

        + MIDDEF_W * midfield_defence_rating

        + GK_W * _effective_gk_rating(goalkeeper_rating)

    )

    combined *= max(0.68, 1.0 - transition_risk * 0.32)

    return 1.0 / (1.0 + combined * 0.95)




def press_xg_suppression(
    presser_pressing: float,
    builder_press_resistance: float,
    *,
    duel_win_pct: float = 0.0,
) -> dict[str, float | bool]:
    """
    Multiplier on opponent xG when presser presses vs builder build-up.
    Layered on top of defence_suppression — does not replace it.
    """
    press_edge = presser_pressing - builder_press_resistance
    if press_edge <= 0.02:
        mult = 1.0
        active = False
        suppression = 0.0
    else:
        scaled = min(1.0, press_edge / 0.35)
        suppression = PRESS_XG_SUPPRESS_MIN + scaled * (PRESS_XG_SUPPRESS_MAX - PRESS_XG_SUPPRESS_MIN)
        if duel_win_pct > 0:
            suppression += min(
                DUEL_CREATION_SUPPRESS_MAX,
                _scale(duel_win_pct, 100.0) * DUEL_CREATION_SUPPRESS_MAX * 0.65,
            )
        suppression = min(PRESS_XG_SUPPRESS_MAX + DUEL_CREATION_SUPPRESS_MAX, suppression)
        mult = 1.0 - suppression
        active = suppression > 0.005
    return {
        "multiplier": round(mult, 4),
        "suppression": round(suppression, 4),
        "press_edge": round(press_edge, 3),
        "pressing_intensity": round(presser_pressing, 3),
        "press_resistance": round(builder_press_resistance, 3),
        "active": active,
    }




def attack_to_xg(finishing_rating: float, *, base: float = 2.05) -> float:

    """Map 0-1 finishing rating to expected goals from shots."""

    return max(0.35, base * (0.42 + 0.88 * finishing_rating))





def creation_to_xg(chance_creation_rating: float, *, base: float = 2.05) -> float:

    """Additional xG from chance creation (crosses, key passes, cut-backs)."""

    return max(0.0, base * 0.36 * chance_creation_rating * 0.50)





def combined_attack_xg(units: UnitRatings) -> float:

    """Total offensive xG before opponent suppression and midfield battle."""

    return attack_to_xg(units.finishing) + creation_to_xg(units.chance_creation)





def _winger_threat_score(stats: PlayerStats, fit: float) -> float:

    raw = (

        _scale(stats.dribbles90, 3.0) * 0.28

        + _scale(stats.xg90 or stats.npxg90, 1.0) * 0.22

        + _scale(stats.key_passes90 or stats.understat_key_passes90, 2.5) * 0.18

        + _scale(stats.xa90 or stats.understat_xa90, 0.6) * 0.16

        + _scale(stats.shots90 or stats.understat_shots90, 4.0) * 0.10

        + _scale(stats.big_chances_created90, 1.2) * 0.06

    )

    return _clamp(raw * (0.55 + 0.45 * fit))





def _side_wide_coverage(
    defend_team: FantasyTeam, player_stats: dict[str, PlayerStats], side: str
) -> float | None:
    """Defensive coverage strength on one flank -- a genuine fullback
    (full defence weight) vs. a lone wide-mid/wing-back (reduced weight,
    per _LONE_WIDE_MID_DEFENCE_WEIGHT) vs. nothing defensively relevant on
    that side at all (None). Lower = more exploitable."""
    for slot in defend_team.lineup:
        su = slot.slot.upper()
        if not su.startswith(side):
            continue
        eff = _eff_slot(slot)
        role = slot_role(eff)
        stats = player_stats.get(slot.player)
        if stats is None:
            continue
        fit = _slot_fit(stats, defend_team, slot)
        if role == "fullback":
            return _player_defence_contrib(stats, fit)
        if role == "winger" and _is_lone_wide_mid(defend_team.formation, su):
            return _player_defence_contrib(stats, fit) * _LONE_WIDE_MID_DEFENCE_WEIGHT
    return None


def compute_wide_matchup_modifier(
    attack_team: FantasyTeam,
    defend_team: FantasyTeam,
    player_stats: dict[str, PlayerStats],
    defend_transition_risk: float,
) -> dict[str, float | bool]:
    """
    Modest xG boost when elite opposition wingers face a high transition-risk back line.
    Capped so wide overloads do not dominate the simulation.

    Amplified further, side-for-side, when the specific flank facing the
    threat is covered by a lone wide-mid/wing-back rather than a genuine
    fullback -- real tactical analysis identifies exactly this (a back-3's
    sole wide body getting isolated and overrun) as THE defining risk of
    back-3 shapes, not a generic team-wide vulnerability. Matched by side
    so a strong left winger specifically exploits a weak right flank, not
    whichever flank happens to be weakest overall.
    """
    side_threats: dict[str, float] = {"L": 0.0, "R": 0.0}
    for slot in attack_team.lineup:
        if slot.slot.upper() not in WINGER_SLOTS and slot_role(slot.slot) != "winger":
            continue
        side = _wide_side(slot.slot)
        if side is None:
            continue
        stats = player_stats[slot.player]
        fit = player_slot_fit(stats, attack_team.formation, slot.slot)
        side_threats[side] = max(side_threats[side], _winger_threat_score(stats, fit))

    threat = max(side_threats.values())
    if threat < 0.42 or defend_transition_risk < 0.22:
        return {
            "multiplier": 1.0,
            "boost": 0.0,
            "winger_threat": round(threat, 3),
            "transition_risk": round(defend_transition_risk, 3),
            "active": False,
        }

    boost = min(0.045, (threat - 0.40) * 0.12 * (defend_transition_risk / 0.48))

    # Wing-back-dependency amplifier: does the flank actually carrying the
    # peak threat face a stretched lone wide body rather than a real
    # fullback? Threshold (0.35) chosen against _LONE_WIDE_MID_DEFENCE_WEIGHT
    # (0.42) -- a lone wide mid with a below-average defence contribution
    # crosses it; a genuinely strong two-way one does not.
    threat_side = max(side_threats, key=side_threats.get)
    coverage = _side_wide_coverage(defend_team, player_stats, threat_side)
    wide_dependency = coverage is not None and coverage < 0.35
    if wide_dependency:
        boost = min(0.07, boost * 1.35)

    return {
        "multiplier": round(1.0 + boost, 4),
        "boost": round(boost, 4),
        "winger_threat": round(threat, 3),
        "transition_risk": round(defend_transition_risk, 3),
        "active": boost > 0.005,
        "wide_dependency_side": threat_side if wide_dependency else None,
    }


