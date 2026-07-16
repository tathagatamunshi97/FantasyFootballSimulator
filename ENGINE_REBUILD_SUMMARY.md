# Engine Rebuild Summary — for ChatGPT validation

**Purpose of this document:** a critique of this match engine (pasted into this
project by the user, originally from a ChatGPT conversation) argued the engine
was "a decision tree simulation, not a continuous spatial one," listed 12
specific problems, and proposed a rebuild priority order. This document
summarizes exactly what was changed in response, organized against that same
critique so it can be checked point-by-point against the original list. Where
something was **not** addressed, that's stated plainly rather than implied.

All changes are in a single file: `web/static/tactic_board.js` (the
client-side, real-time tactic-board engine — see `GAMEPLAY_ENGINE_OVERVIEW.md`
for how this differs from the separate Python statistical model used for
instant match odds).

**Ground rule the whole rebuild followed:** every change was scoped as one
small, reviewable, testable piece — patched onto the live engine, not a
rewrite — and verified three ways before being committed: (1) a brace/paren/
bracket balance check on the edited file, (2) hand or Python-replica reasoning
about the new formula's shape (e.g. confirming a 2-vs-1 situation scores
higher than 1-vs-1), and (3) actually running a live match locally in a
browser and watching it play for 10-25 simulated minutes with the browser
console open, checking for runtime errors and confirming the new behavior
visibly fires in the match commentary (not just "the code looks right").

---

## The core diagnosis (recap)

The critique's central claim: `pressHome`/`pressAway`/`resistHome`/
`resistAway` — the team-wide "pressure" and "press-resistance" numbers used in
almost every attacking/defending formula — were **static scalars, computed
once at kickoff from squad unit ratings, and never touched actual player
positions.** A dribble past a defender was a dice roll against a team-wide
constant, not a contest between two nearby bodies. This was confirmed by
reading the code before any fix was written, and it's the literal mechanism
behind several of the 12 problems below (a covering defender two steps away
contributed nothing to any formula at all).

---

## Status against the 12 problems

### Problem 1 — Ball carrier waits too long before shooting
**Status: Fixed** (same session, just before the rebuild proper started).
`driveIntoBox()`'s post-run-in wait (`lockUntil`/`pendingShot` timing) was
~0.5 match-minutes longer than the run animation itself, producing a visible
freeze before every box shot. Trimmed to a brief take-a-touch beat.

### Problem 2 — Nobody closes down dribblers (no engagement radius)
**Status: Mostly done.**
- Added `pressureAt(x, y, side)` — sums real defensive heat from every
  opponent within a 10-unit radius of a pitch position, weighted by
  proximity², whether the defender is already engaged (pressing/running),
  and their own tackling/interception stats. Summing over *every* nearby
  opponent (not just the closest) is what gives genuine 2-v-1 coverage — a
  second covering defender who isn't the single nearest one now measurably
  raises the pressure.
- Wired into `doDribble` and `doCarry` (the two ball-progression duels),
  replacing the static press/resist scalar terms.
- `doCarry` (pure ball-progression with no dribble attempt) was previously
  **unconditionally safe** even with a defender standing right next to the
  carrier — a separate, real bug found and fixed the same night: added a
  genuine dispossession chance gated on real proximity/pressure.
- Not a literal tiered 6m/2m/1m/0.5m zone system as the critique sketched —
  it's one continuous formula, not discrete zones.

### Problem 3 — One player beats five defenders (no collective shape)
**Status: Partial, extended in Round 3.** Started as CB-pair-only
coordination: each CB previously computed its own `x` position independently
by chasing the ball, with zero awareness of where the other CB stood. Round 1
fixed that — the CB further from the ball-side danger holds back toward
central cover instead of mirroring the near CB's shift. Round 3 extended it
outward: once the near-side CB has actually committed to `defMode "press"`,
the DM slides across to screen the vacated space, and the far-side FB tucks
infield to cover in behind. Closer to the critique's full chain ("LCB shifts,
DM slides over, LB tucks inside, RW tracks back") but still not complete —
the winger-tracks-back piece isn't built.

### Problem 4 — Repetitive passing (no pass memory)
**Status: Done.** `spell.lastReceivers` existed as a field in the spell object
before this rebuild but was **dead code** — declared, never read or written
anywhere else in the file. Now it's actually populated (capped to the last 4
receivers) every time a pass completes, and `scorePassingOption` (the central
function used to rank every pass target) penalizes passing straight back to
someone who touched the ball recently, decaying with how long ago (heaviest
penalty if they had it last, down to zero after ~4 touches). This discourages
sustained CM↔RB ping-pong without permanently blacklisting anyone once a
couple of other players have touched the ball.

### Problem 5 — Support movement (every player needs an objective)
**Status: Done, after a second round.** `assignSupportRoles` (tagging
teammates as safe_outlet/progressive/third_man/switch/depth_runner based on
real lane and marking checks) already existed before this rebuild and was
left as-is. What's new: a **persistent player intent** system (`ensureIntent`)
gives W/FB/AM/ST/CM/DM a held behavioral goal — drawn from a small per-role
menu, weighted by real context, and kept for ~1.0-2.2 match-minutes rather
than recomputed every tick — wired into every FINAL_THIRD and
BOX_OCCUPATION/CHANCE_CREATION/FINISH positioning branch for those six roles.
This was a direct response to a second round of ChatGPT feedback on the
first rebuild pass, which argued the engine now had "enough tactical
richness" and what it actually lacked was persistent intent, not more space
evaluation. See the "Round 2" section below for detail.

### Problem 6 — No space model (sine-wave positioning)
**Status: Done for wingers specifically.** Found the critique's exact
example, verbatim: winger `x` position oscillating as a pure function of
elapsed time (`x = lerp(touch, half, (sin(time)+1)/2)`), with a comment
literally reading "oscillate touchline ↔ half-space." Worse: a **second,
independent** sine-wave block existed further down, applying on top of the
first and blending 65% of the winger's position back toward its own
time-driven value — silently undoing any fix made only to the first block.
Added `scoreOpenSpace(pin, x, depth)`, which scores a candidate position on
real openness (`pressureAt`), passing-lane clarity from the current ball
position (`laneScore`, a pre-existing function), and teammate crowding. Both
sine-wave blocks now pick between touchline/half-space using this real
scoring, sharing one hysteresis flag so the choice doesn't flicker every
recompute or flip at a stage boundary.
AM still has three of its own sine oscillations, left untouched (different
role, out of scope for this slice). ST/CM/FB positioning is untouched.

### Problem 7 — No anticipation (defenders react after the pass, not before)
**Status: Done across every defensive mode with a meaningful target.** A
pre-existing heuristic, `receiverFacingPasser`, checks the receiver's relative
position/orientation to the passer for pass-target scoring — untouched, and
distinct from this. What's new across Rounds 3-4:
- **mark** and **track** (both target a specific attacker) read that
  attacker's held intent and anticipate a small shift in the direction it's
  actually taking them (`stretch`/`overlap` → drifting wider;
  `underlap`/`attack_gap`/`tuck_support` → cutting inside) instead of only
  reacting to their current position — a direct product of the intent system
  existing.
- **cover** and **press** (zonal/ball-oriented, no single marked attacker)
  instead read the carrier's `_supportRole` tagging (`assignSupportRoles`,
  computed every tick) to identify the `progressive`/`third_man` teammate —
  the carrier's actual most dangerous option — and shade toward screening
  that specific option: cover shades its zonal position toward them; press
  angles its approach to the ball to also block that lane ("pressing with
  cover shadow"), instead of pure ball-position pursuit.
- Closed the loop between anticipated positioning and actual outcomes in
  `doPass`: a defender already in mark or cover mode gets a genuine
  interception-odds bonus when the pass actually goes to the player they'd
  been anticipating — not just cosmetic positioning with no payoff.
- `hold` (the passive default) has nothing specific to anticipate against
  and was left alone.
- **mark** also now reads the *carrier's own* held intent, not just the
  marked attacker's — the closest this engine gets to the critique's literal
  "carrier body angle → likely pass": a carrier whose own intent is
  forward-oriented (`progressive_run`/`attack_gap`/`underlap`/`back_post`)
  signals they're looking to release forward, so the marker tightens up
  harder on the mark instead of tracking at a fixed rate regardless of what
  the passer themselves is telegraphing.
- The interception-odds payoff was extended to press's own duel outcome too
  — a presser in active "press" mode (already anticipating with cover
  shadow) gets a bonus in the "steal" (winning it in the tackle before the
  pass gets away) odds, not just `doPass`'s "intercept" outcome.

This closes every anticipation gap identified after Round 4. Genuinely open
boundary: no literal player-orientation/facing property exists on the data
model (Problem 11) — everything here reads *held intent* and *tagged support
roles* as the proxy for "what is this player about to do," not a modeled
body angle.

### Problem 8 — Everything happens sequentially, not parallel
**Status: Partial, with an important framing caveat.** The engine is
single-threaded JavaScript, so literal concurrency isn't possible — the fix
targets the real behavioral gap instead: off-ball reactions previously only
emerged gradually as the continuous shape recompute (already running every
tick for all 22 players) happened to catch up to a new ball position, tick
by tick. Nothing reacted *in the same instant* something significant
happened. Added two trigger functions, both firing sub-second reaction
bundles across multiple players in one synchronous call:
- `triggerReceptionReactions(receiver)` — fires the moment a pass is
  received in a genuinely advanced position: one nearby attacker not already
  running bursts forward, and one nearby fullback not already overlapping
  steps up, simultaneously.
- `triggerTurnoverReactions(winner)` — fires the moment the ball is won back
  (interception, press steal, or a dribble dispossession): up to two
  attack-eligible teammates immediately push forward for the counter, and the
  nearest opponent to the new carrier is flagged pressing right away.
Confirmed live: `Grimaldo intercepts` was followed, in the very next lines of
commentary, by `Chance brewing — Messi` / `Messi into the box` — the
immediate-counter effect visibly firing, not just present in the code.
This is still two specific trigger points reacting with two specific roles
each, not a general "every player reacts to everything" architecture.

### Problem 9 — Animations don't match physics (freeze before/during actions)
**Status: Partial, extended in Round 3.** The Problem 1 shot-freeze bug was
already fixed. New: a shot previously had zero wind-up at all — the ball
started flying the instant the decision was made, no plant-foot/backswing
motion on the shooter. Added a brief, bounded plant bulge on the shooter's
own sprite right at the shot's start (same `_pathCtrl` bezier mechanism as
`doDribble`/`doCarry`), purely cosmetic — doesn't delay the scoring decision,
xG, or ball flight timing. Confirmed via code reading (not just assumption)
that "never freeze everyone" was already true architecturally before this:
`updateTeamShape`/`applyPinMotion` run for all 22 players every tick
regardless of `ballFlight` state. No goalkeeper save-reaction pose or general
"animation begins before decision completes" system beyond this one instance.

### Problem 10 — No pressure field
**Status: Done, and adopted broadly — this ended up being the rebuild's
spine.** `pressureAt` (see Problem 2) is now read by:
- `doDribble`, `doCarry` (dribble/carry contests — Phase 1)
- `refreshSpellPattern` (pattern re-picks now trigger on a real pressure
  spike at the carrier, not just a fixed ~6-7-action timer — Phase 4)
- `doPass`'s interception and press-steal odds (previously the last major
  duel-type formula still reading the static scalar pair)
- `doShot`'s block probability (found this had **zero** positional signal at
  all — a shot could be "blocked" with the nearest defender 40+ units away;
  now gated/scaled on real pressure at the shooter)
- `doShot`'s save probability (a rushed/pressured strike is now modestly
  easier to save)
`sideAttack`/`sideDefend` (aggregate squad quality) were deliberately left
alone — a different, legitimate concept from moment-to-moment ball pressure,
not something `pressureAt` should replace.

### Problem 11 — Passing lanes (width, interception risk, body angle, first touch)
**Status: Partial.** `laneScore`/`defendersInLane` (lane-width/interception-risk
checks) already existed before this rebuild and are reused in
`scoreOpenSpace`. Receiver body angle and first-touch direction are **not
modeled at all** — no orientation/facing property exists anywhere on a
player pin.

### Problem 12 — Off-ball intelligence (drag defender, check short, spin behind, occupy weak-side CB, create overload)
**Status: Partial, after Round 2.** The persistent intent system (Problem 5)
gives six roles a genuine held goal (e.g. ST `pin_last_line`/`drop_short`/
`far_post`, W `stretch`/`attack_gap`/`underlap`) which covers some of this —
"drop_short" is a check-to-feet, "underlap" is a version of spinning
inside/beyond a marker, "pin_last_line" is occupying the shoulder of the
last defender. Not covered: explicitly *dragging* a specific named defender
out of position, occupying the *weak-side* CB specifically (intent doesn't
reason about which opposing defender it's manipulating), or blind-side runs.

---

## Status against the "if I were rebuilding" priority list

| # | Priority | Status |
|---|---|---|
| 1 | Continuous 1v1/2v1 duels replacing random turnover | Done for dribble/carry/pass; not for aerial duels (separate, untouched formula) |
| 2 | Dynamic off-ball movement engine | Wingers got space evaluation (Round 1); all six outfield attacking roles now also have persistent intent (Round 2). CB/DM/GK untouched (not off-ball-attacking roles in the same sense) |
| 3 | Coordinated defensive shape | CB pair only; midfield/fullback/winger coordination not built |
| 4 | Spatial evaluation replacing fixed attack patterns | Only the re-pick *trigger* got real spatial awareness; `pickAttackPattern` itself is still the same weighted-random choice among 5 named patterns |
| 5 | Objectives vs. execution methods | One pattern (`wing_carry`) only, and only the *order* methods are tried in, not a true per-method scoring system; the other 4 patterns are untouched. (Note: this is pattern-level objectives/methods, distinct from the new player-level intent system, which addresses a related but different critique — see Round 2.) |

---

## Round 2 — persistent player intent (in response to a second ChatGPT review)

After Round 1 (Phases 1-5 plus the standalone pressure-field/pass-memory/
reaction-trigger fixes above), ChatGPT reviewed this same document and
concluded the engine now had "enough tactical richness" — the bigger gap
wasn't another tactical system, it was that off-ball movement had no
**persistent intent**: `_supportRole` and the winger touchline/half-space
choice were both recomputed fresh every tick, which can flicker between
near-tied options ("an indecisive player"). The proposed fix: give each
player a held goal (stretch, receive, attack a gap, drag a marker, support,
etc.) that lasts a few seconds, with space evaluation serving *how* to
achieve the intent rather than deciding *whether* to have one.

Built as `ensureIntent(pin, relBall)` — draws from a small, context-weighted
per-role menu and holds the result for ~1.0-2.2 match-minutes:

| Role | Menu |
|---|---|
| W | `stretch`, `attack_gap`, `underlap` |
| FB | `overlap`, `hold_width`, `tuck_support` |
| AM | `attack_gap`, `support`, `back_post` |
| ST | `pin_last_line`, `drop_short`, `far_post` |
| CM | `support`, `progressive_run`, `hold_width` |
| DM | `screen`, `support` |

Wired into every FINAL_THIRD and BOX_OCCUPATION/CHANCE_CREATION/FINISH
positioning branch for all six roles — intent selects the target zone,
existing space-aware math (`scoreOpenSpace`, the near/far-post oscillation,
`fbAttackThreat`) still decides how to get there or how far to commit. The
FB overlap branch's real-time opportunity check (ball central + CM on it +
same flank) is preserved as a gate on top of intent, not replaced by it.
The standalone winger `_wPrefHalf` hysteresis (a narrower, role-specific
version of the same idea, added in Round 1) was removed and replaced by this
general mechanism, so there's one persistent-decision layer, not two.

Verified the same way as Round 1: brace/paren/bracket balance after each of
three edit passes (infrastructure, FINAL_THIRD, BOX_OCCUPATION), and a live
local match watched via the Browser tool (~11,000 ticks/22 simulated
minutes) with no console errors.

**Honest limits:** the menus are hand-picked and reasonably small (2-3 per
role), not the full 8-item off-ball menu from the original critique (check
short/spin behind/drag CB/occupy weak-side CB/blind-side run/late arrival
are only partially represented). Intent doesn't reason about *which specific
opposing player* it affects (e.g. no explicit "drag *that* CB out"). CB/DM/GK
don't have attacking intent (arguably correct — those aren't off-ball
attacking-movement roles in the same sense — but it means Problem 12 is
still only partially closed.

---

## Round 3 — defensive intent, extended shape, anticipation, physics

Four pieces, each verified separately with a live local match:

1. **Defensive intent hold.** `defMode` (hold/press/track/cover/mark) was
   recomputed from scratch every tick — the same flicker risk the winger
   hysteresis and `_supportRole` had before Phase 6. Two defenders near-tied
   on `pressRank` (nearest-to-ball) could flip which one presses and which
   covers on every recompute. The full priority-chain logic is untouched
   (renamed to `naturalMode`); added a hold wrapper so a mode persists
   ~0.35-0.6 match-minutes once assigned, except `track` (a breaking runner),
   which always overrides immediately.
2. **Extended defensive shape** (Problem 3, see above).
3. **Anticipation** (Problem 7, see above).
4. **Physics realism / shot wind-up** (Problem 9, see above).

## What this rebuild deliberately did NOT attempt

- A full continuous multi-agent simulation replacing the decide→animate
  loop. The engine is still fundamentally "ball carrier decides, then
  animates," with the reaction-burst functions (Problem 8) and the intent
  system (Problem 5/12) as bounded patches on top, not a replacement.
- Full anticipation — only the "mark" mode reads intent; interceptions are
  still a probability roll decided at pass time, not a lane closed off
  before the ball is released.
- A general "animation begins before decision completes" architecture
  (Problem 9) — only the shooter's own plant motion was added; no goalkeeper
  save-reaction pose or equivalent for other actions.
- Aerial duel modeling with the pressure field (still its own separate,
  older formula).
- Rebuilding `pickAttackPattern`'s pattern *selection* itself, or any
  pattern besides `wing_carry`'s method ordering.
- Player orientation/facing/first-touch direction (Problem 11) — this would
  require adding a new property to the player data model, not just a new
  formula.
- Explicit "drag a named defender" / weak-side-CB-targeting logic within
  intent — intent selects a zone/behavior, not a specific opposing player
  to manipulate.
- The winger-tracks-back piece of the Problem 3 defensive chain.

---

## Commits (chronological, oldest first)

```
dff810e Engine rebuild Phase 1: continuous pressure field replaces static press/resist in duels
95ff156 Engine rebuild Phase 2: real off-ball space evaluation replaces winger sine-wave oscillation
93c1f6a Engine rebuild Phase 3: coordinated CB lateral cover instead of independent ball-chasing
2fa90a3 Engine rebuild Phase 4: pattern re-picks react to real spatial pressure, not just a timer
6d3e5fd Engine rebuild Phase 5: objective stays fixed, method order adapts to real pressure
4bbcd72 Engine rebuild: pass memory to stop repetitive CM<->RB ping-pong
131c50f Engine rebuild: extend pressure field to pass interception/steal odds
4d37326 Engine rebuild: gate shot-block chance on real pressure at the shooter
d1e7186 Engine rebuild: factor real shot pressure into save probability
4d87699 Engine rebuild: simultaneous off-ball reactions on advanced pass reception
cfb9ff5 Engine rebuild: simultaneous reactions when the ball is won back (turnover)
1e0c60f Document the engine rebuild against the original critique, for ChatGPT review
5c7d099 Engine rebuild Phase 6: persistent player intent, full build and integration
17078f2 Update rebuild summary with the persistent-intent round (Round 2)
a5ea6f7 Engine rebuild: defensive intent hold, mirroring the attacking-intent fix
62da411 Engine rebuild: extend defensive shape outward + real anticipation
844b467 Engine rebuild: physics realism - shot wind-up instead of instant ball departure
71add83 Document Round 3: defensive intent, extended shape, anticipation, physics
b4e1472 Engine rebuild: full anticipation - track mode reads intent, interceptions pay off
4d6d249 Document Round 4: full anticipation (track mode + interception payoff)
5a4e0fc Engine rebuild: extend anticipation to cover mode via progressive/third-man tags
cc8ee76 Engine rebuild: extend anticipation to press mode (press with cover shadow)
f85215d Document full anticipation completion across mark/track/cover/press modes
c281b17 Engine rebuild: read the carrier's own intent, and give press its duel payoff
```

Each commit message contains the specific before/after reasoning and the
verification steps taken for that piece.
