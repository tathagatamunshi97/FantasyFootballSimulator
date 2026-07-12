"""Build attack / midfield / defence / GK unit ratings from blended player stats.

Calibration (v2.3):
- Progressive pool (xA, xG-buildup, xG-chain, key passes) split: 38% attack, 58% creation
  (96% total — avoids full double-count while crediting all positions).
- GK suppression: back line 54%, mid shield 32%, GK 14% (was 24%); GK rating compressed
  toward league avg 0.40 with 55% deviation retention.
- Overall rating GK weight 10% (was 14%).
"""

from __future__ import annotations



from dataclasses import dataclass



from formation_fit import get_slot_definition, normalize_formation, player_slot_fit

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





def _avg(values: list[float], default: float = 0.5) -> float:

    return sum(values) / len(values) if values else default





def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:

    return max(lo, min(hi, x))





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
    # Caps slightly below elite season rates so dampened Kane/Díaz/Yamal still
    # saturate finishing (0.70–0.75 xG90 / ~3.6 shots) rather than looking mid-table.
    xg = stats.npxg90 or stats.xg90
    finisher = (
        _scale(xg, 0.72) * 0.36
        + _scale(stats.xg90, 0.72) * 0.16
        + _scale(stats.shots90, 3.6) * 0.13
        + _scale(stats.shots_on_target90, 2.2) * 0.09
        + _scale(stats.big_chances_created90, 1.2) * 0.07
        + _scale(max(0.0, stats.big_chances_created90 - stats.big_chances_missed90), 1.0) * 0.04
    )
    # Missing dribble% used to zero the carry term for sparse primes.
    drib_pct = stats.dribble_pct if stats.dribble_pct > 0 else 50.0
    carry = _scale(stats.dribbles90, 3.0) * 0.10 * _scale(drib_pct, 100.0)
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





def _duel_def_term(stats: PlayerStats) -> float:
    """FotMob duel win rate — skip GKs / missing data (no penalty)."""
    if stats.fpl_position == "GK" or stats.duels_won_pct <= 0:
        return 0.0
    return _scale(stats.duels_won_pct, 100.0) * DUEL_DEF_WEIGHT


def _aerial_def_term(stats: PlayerStats) -> float:
    """Modest aerial signal for CB/LB/RB from FotMob."""
    pos = (stats.primary_position or "").upper()
    roles = {p.upper() for p in (stats.positions or [])}
    if pos not in _BACKLINE_POSITIONS and not roles & _BACKLINE_POSITIONS:
        return 0.0
    if stats.aerials_won90 <= 0 and stats.aerials_won_pct <= 0:
        return 0.0
    win_rate = _scale(stats.aerials_won_pct, 100.0) if stats.aerials_won_pct > 0 else 0.55
    volume = _scale(stats.aerials_won90, 2.5)
    return (volume * 0.58 + win_rate * 0.42) * AERIAL_DEF_WEIGHT


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

    raw = (

        _scale(stats.tackles90, 3.5) * 0.28

        + _scale(stats.interceptions90, 2.5) * 0.30

        + _scale(stats.clearances90, 6.0) * 0.22

        + _scale(stats.xg_buildup90, 0.4) * 0.05

        + _duel_def_term(stats)

        + _aerial_def_term(stats)

        + _press_resist_contrib(stats, fit, for_defence=True)

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
    {"3-4-1-2 (flat)", "3-4-1-2 (normal)", "3-5-2", "3-4-3(1)", "3-4-3(2)"}
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

    if formation == "4-3-3 attacking":
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



    for slot in team.lineup:

        stats = player_stats[slot.player]

        fit = _slot_fit(stats, team, slot)

        weights = slot_unit_weights(_eff_slot(slot), stats.fpl_position)



        if stats.fpl_position == "GK":

            score, conf, backup = _player_gk_contrib(stats, fit)

            gk_scores.append(score)

            gk_conf = conf

            gk_backup = backup

            continue



        finishing_scores.append(_player_attack_contrib(stats, fit) * weights.attack)

        creation_scores.append(_player_chance_creation_contrib(stats, fit) * weights.creation)

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

    for slot in team.lineup:
        stats = player_stats[slot.player]
        fit = _slot_fit(stats, team, slot)
        role = slot_role(_eff_slot(slot))

        if stats.fpl_position == "GK" or role == "gk":
            score, conf, backup = _player_gk_contrib(stats, fit)
            gk_scores.append(score)
            gk_conf = conf
            gk_backup = backup
            continue

        if role in _FINISHING_ROLES:
            finishing_scores.append(_player_attack_contrib(stats, fit))
        if role in _CREATION_ROLES:
            creation_scores.append(_player_chance_creation_contrib(stats, fit))
        if role in _ATTACK_ROLES:
            attack_scores.append(
                0.56 * _player_attack_contrib(stats, fit)
                + 0.44 * _player_chance_creation_contrib(stats, fit)
            )
        if role in _MIDFIELD_ROLES:
            midfield_scores.append(_player_midfield_contrib(stats, fit))
        if role in _DEFENCE_ROLES:
            defence_scores.append(_player_defence_contrib(stats, fit))
        if role in _MIDDEF_ROLES:
            w = 1.0 if role == "dm" else 0.72
            midfield_defence_scores.append(_player_midfield_defence_contrib(stats, fit) * w)

    # Top-3 mean (divisor=3): keeps elite above mid-table without everyone at 1.00.
    finishing = _top_n_avg(finishing_scores, 3, divisor=3.0)
    chance_creation = _top_n_avg(creation_scores, 3, divisor=3.0)
    attack = _clamp(_avg(attack_scores) if attack_scores else 0.56 * finishing + 0.44 * chance_creation)
    midfield = _avg(midfield_scores, default=0.28)
    defence = _avg(defence_scores, default=0.18)
    midfield_defence = _avg(midfield_defence_scores, default=0.12)
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
    for slot in team.lineup:
        st = player_stats[slot.player]
        if st.fpl_position in ("DEF", "MID"):
            fit = player_slot_fit(st, team.formation, slot.slot)
            press_resist_scores.append(_player_press_resistance(st, fit))
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





def compute_wide_matchup_modifier(

    attack_team: FantasyTeam,

    defend_team: FantasyTeam,

    player_stats: dict[str, PlayerStats],

    defend_transition_risk: float,

) -> dict[str, float | bool]:

    """

    Modest xG boost when elite opposition wingers face a high transition-risk back line.

    Capped so wide overloads do not dominate the simulation.

    """

    threats: list[float] = []

    for slot in attack_team.lineup:

        if slot.slot.upper() not in WINGER_SLOTS and slot_role(slot.slot) != "winger":

            continue

        stats = player_stats[slot.player]

        fit = player_slot_fit(stats, attack_team.formation, slot.slot)

        threats.append(_winger_threat_score(stats, fit))

    threat = max(threats) if threats else 0.0

    if threat < 0.42 or defend_transition_risk < 0.22:

        return {

            "multiplier": 1.0,

            "boost": 0.0,

            "winger_threat": round(threat, 3),

            "transition_risk": round(defend_transition_risk, 3),

            "active": False,

        }

    boost = min(0.045, (threat - 0.40) * 0.12 * (defend_transition_risk / 0.48))

    return {

        "multiplier": round(1.0 + boost, 4),

        "boost": round(boost, 4),

        "winger_threat": round(threat, 3),

        "transition_risk": round(defend_transition_risk, 3),

        "active": boost > 0.005,

    }


