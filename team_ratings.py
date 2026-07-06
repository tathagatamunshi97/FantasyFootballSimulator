"""Build attack / midfield / defence / GK unit ratings from blended player stats."""

from __future__ import annotations



from dataclasses import dataclass



from formation_fit import player_slot_fit

from models import FantasyTeam, PlayerStats

from sample_confidence import (

    MIN_TRUSTED_MINUTES,

    is_backup_goalkeeper,

    reliability_multiplier,

    shrink_gk_stats,

)

from slot_roles import FULLBACK_SLOTS, WINGER_SLOTS, slot_role, slot_unit_weights





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





def _player_attack_contrib(stats: PlayerStats, fit: float) -> float:

    """Finishing / shooting threat."""

    finisher = (

        _scale(stats.npxg90 or stats.xg90, 0.85) * 0.35

        + _scale(stats.xg90, 0.85) * 0.15

        + _scale(stats.shots90, 4.0) * 0.12

        + _scale(stats.shots_on_target90, 2.5) * 0.08

        + _scale(stats.big_chances_created90, 1.2) * 0.08

        + _scale(max(0.0, stats.big_chances_created90 - stats.big_chances_missed90), 1.0) * 0.05

    )

    carry = _scale(stats.dribbles90, 3.0) * 0.10 * _scale(stats.dribble_pct, 100.0)

    return (finisher + carry) * (0.55 + 0.45 * fit)





def _player_chance_creation_contrib(stats: PlayerStats, fit: float) -> float:

    """Chance creation: crosses, key passes, pre-assist buildup."""

    raw = (

        _scale(stats.xa90, 0.55) * 0.28

        + _scale(stats.assists90, 0.45) * 0.08

        + _scale(stats.key_passes90, 2.5) * 0.22

        + _scale(stats.understat_key_passes90, 2.5) * 0.10

        + _scale(stats.big_chances_created90, 1.2) * 0.20

        + _scale(stats.xg_buildup90, 0.55) * 0.07

        + _scale(stats.xg_chain90, 0.9) * 0.05

    )

    return raw * (0.55 + 0.45 * fit)





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

    )

    return raw * (0.6 + 0.4 * fit)





def _player_defence_contrib(stats: PlayerStats, fit: float) -> float:

    raw = (

        _scale(stats.tackles90, 3.5) * 0.28

        + _scale(stats.interceptions90, 2.5) * 0.30

        + _scale(stats.clearances90, 6.0) * 0.22

        + _scale(stats.xg_buildup90, 0.4) * 0.05

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



    gp_weight = 0.28 if stats.minutes >= MIN_TRUSTED_MINUTES else 0.10

    rating_norm = _clamp((shrunk["rating"] - 6.2) / 1.0)

    conceded_norm = _clamp((1.25 - shrunk["goals_conceded90"]) / 1.25)

    gp_norm = _scale(shrunk["goals_prevented90"], 0.12)



    raw = (

        gp_norm * gp_weight

        + rating_norm * 0.38

        + conceded_norm * 0.27

        + _scale(shrunk["pass_pct"], 100.0) * 0.07

    )

    raw *= 0.6 + 0.4 * fit



    league_avg = 0.40

    regressed = conf * raw + (1.0 - conf) * league_avg

    regressed *= reliability_multiplier(stats.minutes)



    if backup:

        regressed = min(regressed, league_avg + 0.05 * conf)

        regressed *= 0.90



    return regressed, conf, backup





def _compute_transition_risk(

    team: FantasyTeam,

    player_stats: dict[str, PlayerStats],

) -> float:

    """

    Attacking fullbacks increase transition exposure when midfield cannot cover.

    High creation fullbacks (e.g. Dumfries) push forward; DMs/CMs must shield the space.

    """

    fb_exposure: list[float] = []
    dm_cover: list[float] = []
    cm_cover: list[float] = []

    for slot in team.lineup:
        stats = player_stats[slot.player]
        fit = player_slot_fit(stats, team.formation, slot.slot)
        role = slot_role(slot.slot)

        if slot.slot.upper() in FULLBACK_SLOTS or role == "fullback":
            fb_exposure.append(_fullback_attack_exposure(stats, fit))
        if role == "dm":
            w = slot_unit_weights(slot.slot, stats.fpl_position)
            dm_cover.append(_player_midfield_defence_contrib(stats, fit) * w.midfield_defence)
        if role == "cm":
            w = slot_unit_weights(slot.slot, stats.fpl_position)
            cm_cover.append(_player_midfield_defence_contrib(stats, fit) * w.midfield_defence)

    if not fb_exposure:
        return 0.0

    # The most aggressive fullback drives transition exposure (not the pair average).
    exposure = max(fb_exposure)
    dm = _avg(dm_cover, 0.38)
    cm = _avg(cm_cover, 0.38)
    cover = 0.68 * dm + 0.32 * cm
    uncovered = max(0.08, 1.0 - cover * 0.95)
    return _clamp(exposure * uncovered * 1.35, 0.0, 0.48)





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

        fit = player_slot_fit(stats, team.formation, slot.slot)

        weights = slot_unit_weights(slot.slot, stats.fpl_position)



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

    finishing = _clamp(sum(finishing_top) / 2.0 if finishing_top else 0.0)

    chance_creation = _clamp(sum(creation_top) / 1.75 if creation_top else 0.0)

    attack = _clamp(0.56 * finishing + 0.44 * chance_creation)



    midfield = _avg(midfield_scores)

    defence = _avg(defence_scores)

    midfield_defence = _avg(midfield_defence_scores)

    goalkeeper = _avg(gk_scores, default=0.5)

    transition_risk = _compute_transition_risk(team, player_stats)



    overall = (

        0.28 * attack

        + 0.24 * midfield

        + 0.20 * defence

        + 0.14 * goalkeeper

        + 0.10 * midfield_defence

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





def midfield_battle_multiplier(home_mid: float, away_mid: float) -> tuple[float, float]:

    """Return chance multipliers from midfield dominance (-8% to +8% approx)."""

    delta = home_mid - away_mid

    home_mult = 1.0 + 0.10 * max(-0.8, min(0.8, delta))

    away_mult = 1.0 - 0.10 * max(-0.8, min(0.8, delta))

    return home_mult, away_mult





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

        0.50 * defence_rating

        + 0.26 * midfield_defence_rating

        + 0.24 * goalkeeper_rating

    )

    combined *= max(0.68, 1.0 - transition_risk * 0.32)

    return 1.0 / (1.0 + combined * 0.95)





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


