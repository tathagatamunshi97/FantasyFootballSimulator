# How This App Simulates a Football Match

This describes the current state of the simulation logic, for anyone (including
another AI) trying to help make the gameplay feel more like real football.
There are **two completely separate engines** that do fundamentally different
things — a common source of confusion, so this is split accordingly.

---

## Engine 1: Python statistical model (`match_engine.py` + `team_ratings.py`)

**What it's for:** instant "Run match" simulations, pre-match win/draw/loss
odds, squad-strength reports, tournament fixture predictions.

**What it is NOT:** there is no pitch, no player positions, no passing, no
movement of any kind. It is a pure statistical model — think "advanced Poisson
model," not "simulation."

### Step 1 — Player stats → unit ratings

Every player has per-90 stats (goals, xG, xA, key passes, tackles,
interceptions, aerials, dribbles, etc., blended from Sofascore/FBref/Understat
data). Each player produces several **contribution scores** via hand-tuned
weighted sums of their stats, each scaled 0–1 (e.g. `_player_attack_contrib`,
`_player_chance_creation_contrib`, `_player_midfield_contrib`,
`_player_defence_contrib`, `_player_gk_contrib`). Example (finishing):

```python
finisher = (
    scale(npxg90, 0.72) * 0.36
    + scale(xg90, 0.72) * 0.16
    + scale(shots90, 3.6) * 0.13
    + scale(shots_on_target90, 2.2) * 0.09
    + scale(big_chances_created90, 1.2) * 0.07
    + scale(big_chances_created90 - big_chances_missed90, 1.0) * 0.04
)
```

Each contribution is multiplied by how well the player **fits their assigned
formation slot** (`formation_fit.player_slot_fit` — blends natural position
match with a stat-profile match for the slot, e.g. a striker slot expects
high `xg90`/`shots90`), and by a **slot-role weight** (`slot_roles.py`) — a
striker's defensive contribution barely counts; a centre-back's attacking
contribution barely counts.

### Step 2 — Team unit ratings

Per-player contributions aggregate into team-level ratings
(`team_ratings.compute_unit_ratings`): `attack, finishing, chance_creation,
midfield, defence, midfield_defence, transition_risk, goalkeeper, overall`.

- Finishing/chance-creation use the **top-3 players' average**, not a full-XI
  average — rewards having a few genuine stars over spreading quality thin.
- `transition_risk` models counter-attack exposure: how aggressively a team's
  fullback pushes forward (`_fullback_attack_exposure`, from xA/key
  passes/dribbles/big chances), discounted by midfield defensive cover.
- A **fullback-winger combination bonus** was recently added: a fullback's
  forward-join stats previously only ever hurt the team (transition risk) and
  never helped it. Now a bounded bonus rewards genuine overlap/underlap
  combination play with the winger ahead of them on the same flank.
- `overall = 0.30·attack + 0.24·midfield + 0.22·defence + 0.10·GK + 0.12·midfield_defence + 0.04·(1−transition_risk)`

### Step 3 — Expected goals

```python
base = attack_to_xg(finishing) + creation_to_xg(chance_creation)
suppression = defence_suppression(opp.defence, opp.goalkeeper, opp.midfield_defence, opp.transition_risk)
fit_boost = 0.90 + 0.10 * formation_fit
xg = max(0.25, base * suppression * mid_battle_multiplier * fit_boost * wide_modifier * press_modifier * (1 + home_adv))
```

- `defence_suppression`: `combined = 0.54·defence + 0.32·midfield_defence + 0.14·compressed_GK`, suppressed further if the attacker's transition risk is high; final multiplier `1/(1+combined*0.95)`.
- `mid_battle_multiplier`: ±8% swing from the midfield rating gap between the two teams.
- `wide_modifier`: small bonus (capped ~4.5%) when a team's best winger threat is high *and* the opponent's transition risk is high.
- `press_modifier`: small suppression (capped ~12%) when a team's pressing intensity exceeds the opponent's press resistance.

### Step 4 — Goals and attribution

- Goals drawn from a custom Poisson sampler per team, from the xG above.
- Each goal's **scorer** and **assister** are picked via a weighted random draw
  over the team's players, using stat-blend "shares" (npxG, xG-buildup, key
  passes, etc.), each scaled by a slot-role weight (striker scorer weight
  1.0, fullback assist weight 1.18 — fullbacks are weighted as strong assist
  sources despite low scoring threat). ~74% of goals get an assist. Goal
  minute is drawn from a Beta(2.2, 2.0) distribution (slightly second-half
  skewed).
- This whole match is simulated **thousands of times** (Monte Carlo) to
  produce win/draw/loss %, goal distributions, BTTS%, over/under 2.5%, and
  common scorelines.

**Bottom line for engine 1:** it's a well-calibrated statistical model of
*who should win and by roughly how much*, built from real per-90 stats. It
has no concept of "how" a goal happens beyond picking a plausible scorer.

---

## Engine 2: Live tactical board (`web/static/tactic_board.js`, ~7,300 lines)

**What it's for:** live-hosted "Matchday" tournament broadcasts — this is
what people actually *watch*. Runs entirely client-side in the browser.

**What it is:** a genuine positional/rule-based simulation. Every player has
real pitch coordinates (`left`/`top` as % of pitch), a role (GK/CB/FB/DM/CM/AM/W/ST),
and the engine ticks forward via `requestAnimationFrame`, deciding actions
based on real per-90 stats plus team-level composite ratings passed in from
the Python side (`unitHome`/`unitAway`: attack, defence, pressing_intensity,
press_resistance, goalkeeper, etc.).

### Possession structure

A "spell" = one continuous phase of possession by one side, moving through
stages: `BUILD_UP → PROGRESSING → FINAL_THIRD → BOX_OCCUPATION →
CHANCE_CREATION → FINISH`. Within a spell, an **attack pattern** gets picked
via weighted random choice and periodically re-picked as it goes stale
(`patternConfidence` decays per action):

- `central` — central progression, through-ball attempts, dribbles.
- `wide_switch` — switch play to the far flank.
- `wing_carry` — winger/fullback carries down the line; this is where the
  fullback-winger **overlap / underlap / decoy run / one-two** logic lives
  (`decideFbWingLink`), weighted by real stats (`dribbles90`, `pass_pct`, a
  `fbAttackThreat()` score).
- `cut_inside` — winger/AM cuts inside and drives at the box
  (`driveIntoBox`), or does a decoy dribble, or slips a through ball.
- `recycle` — safe backward/sideways pass to reset.

**Progression urgency** (`progressionUrgency`) climbs the longer a spell
continues (starts near 0, climbs toward ~1.2+ after several sustained
actions), and gates most of the incisive options (through balls, one-twos,
box drives) behind minimum thresholds — modeling "early in a move, be
patient; once it's been building a while, take more risk."

### Combination play

Four explicit chains exist, all via the same `spell.combo` start/complete
machinery (cue a "start" pass, then complete it if the ball returns to the
right player before anything interrupts):
1. CM/AM → ST layoff → CM/AM third-man return
2. Winger → ST layoff → Winger return
3. Fullback → Winger (overlap run cued) → ball back to Fullback
4. CM/AM → nearby CM/AM give-and-go one-two (added most recently, to give a
   pressed central midfielder an option besides "recycle or hope for a lane")

### Defensive shape

Off-ball defenders pick a `defMode` per tick: `hold / press / track / cover /
mark`, based on distance to ball, team press rating, and whether a specific
attacker is making a run. The number of players allowed into active "press"
mode at once is capped (1–4, scaled by team pressing rating) — most of the
back line holds/covers rather than pressing as a unit.

**Known gap:** attacking off-ball movement (AM/winger/striker positioning
when not on the ball) is mostly *scripted sine-wave oscillation* between
preset pocket positions by role and possession stage — there is no
reactive "my marker just got tight, I need to check away / spin off" logic,
only a small generic personal-space collision-avoidance nudge (recently
widened slightly for tightly-marked off-ball attackers specifically, but
still not a real marking-evasion system).

### Shooting

`doShot` → `organicWillScore(carrier)` decides if a shot *wants* to score,
using the carrier's own `xg90`, `shots90`, `goals90` (credits players who
outperform their own xG — "clinical finishing"), and a `finisherQuality`
composite that raises both the base probability *and* the ceiling for
genuine finishers. A second-stage `saveP` check (using the *opponent's*
defence rating **and**, as of a recent fix, the individual **goalkeeper's**
own rating specifically) can still deny it. If the shot doesn't score, it
resolves to one of three distinct outcomes — **blocked** (by an outfield
defender), **saved** (reaches keeper), or **wide** — each with its own
animation and event log entry (this three-way split, and the goalkeeper
term, were both recent fixes; previously every non-scoring shot was
mislabeled "saved" regardless of whether a defender or the keeper actually
stopped it, and individual GK quality had zero effect on saves).

### Turnovers

`pressTurnoverChance` — a smooth background probability from team
press/resist ratings and proximity — flips possession with **no discrete
tackle event and no fouls**. Every turnover reads as a clean interception,
even ones that in reality would often be a foul.

### What does NOT exist at all (verified absent from the code)

- Fouls, cards, free kicks
- Corners, throw-ins
- Substitutions
- Fatigue/stamina over the 90 minutes (there's a goal-count-based "fatigue"
  dampener, unrelated to elapsed time or player conditioning)
- Mid-match tactical adjustment (team pressing/tempo/shape inputs are fixed
  for the whole 90 minutes regardless of scoreline)
- True frame-by-frame match replay (a "replay" of a completed match
  currently re-improvises a fresh match from just the final score, not the
  actual events — scoped separately, see `MATCH_REPLAY_TRACE_PLAN.md`)

---

## Recent tuning history this session (context for what's already been tried)

1. Gave fullback overlap play a genuine *attacking* credit (previously only
   ever penalized as transition-risk exposure) — Python engine.
2. Found and fixed two gating bugs that were silently preventing
   `cut_inside`/`wing_carry` patterns (box drives, fullback-winger
   combination) from ever executing — JS engine.
3. **That fix over-corrected**: removing the gate entirely flipped those
   patterns from "almost never fires" to "almost always fires," since their
   selection *weights* were tuned assuming the old gate would keep blocking
   them. Produced blowout matches (two real matches with >7 total xG,
   confirmed via production data). Redialed to a bounded 40%-of-attempts
   exemption instead of a full one.
4. Reduced structural bias toward "recycle" over progressing, by (a)
   strengthening how much rising urgency suppresses the recycle option, and
   (b) fixing an inconsistency where recycling reset the possession-stage
   machinery further back than every other reset path in the file did.
5. Stopped wingers near the final third from backpassing all the way to
   their own centre-back when a nearer/more sensible out-ball exists.
6. Added the CM/AM give-and-go one-two (item 3 above).
7. Fixed a client-side polling race where viewers (not the admin, who hosts
   their own view directly) could see a live score/board state briefly
   flicker backward, from overlapping unguarded poll requests.

## Open, not-yet-tackled gameplay gaps (from earlier discussion)

Roughly in priority order previously discussed: fatigue/stamina modeling,
substitutions, wider combination-play repertoire (only 4 fixed chains exist),
cue-based/coordinated pressing (currently continuous distance-based
probability, not discrete triggers), foul/tackle discreteness, mid-match
tactical adaptation to scoreline. Corners/throw-ins/set-pieces were
explicitly deferred as "bring in later, not gameplay-core."
