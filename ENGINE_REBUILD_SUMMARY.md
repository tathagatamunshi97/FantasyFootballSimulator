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
**Status: Partial.** Only centre-back-pair coordination was built: each CB
previously computed its own `x` position independently by chasing the ball,
with zero awareness of where the other CB stood. Now, when defending, the CB
further from the ball-side danger holds back toward central cover instead of
mirroring the near CB's shift. The full chain from the critique's example
("LCB shifts, DM slides over, LB tucks inside, RW tracks back") is **not**
built — only the CB↔CB piece.

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
**Status: Partial.** `assignSupportRoles` (tagging teammates as
safe_outlet/progressive/third_man/switch/depth_runner based on real lane and
marking checks) already existed before this rebuild and was left as-is. What
changed: wingers now get genuine space-evaluated movement (see Problem 6).
AM/ST/CM support movement is still the older, formula/stage-driven
positioning — not rebuilt.

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
**Status: Not done.** A pre-existing heuristic, `receiverFacingPasser`,
checks the receiver's relative position/orientation to the passer for
pass-target scoring — but no defender ever moves *before* a pass is thrown
based on reading the carrier's body shape. Interceptions are still decided at
the moment `doPass` executes, as a probability roll.

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
**Status: Only the one specific bug from Problem 1 was fixed.** No general
"windup begins before the decision completes, defenders never freeze"
architecture was built.

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
**Status: Not done**, beyond the narrow touchline-vs-half-space choice for
wingers (Problem 6) and the reception/turnover reaction bursts (Problem 8).
The richer menu of off-ball actions the critique described doesn't exist.

---

## Status against the "if I were rebuilding" priority list

| # | Priority | Status |
|---|---|---|
| 1 | Continuous 1v1/2v1 duels replacing random turnover | Done for dribble/carry/pass; not for aerial duels (separate, untouched formula) |
| 2 | Dynamic off-ball movement engine | Wingers only; AM/ST/CM/FB untouched |
| 3 | Coordinated defensive shape | CB pair only; midfield/fullback/winger coordination not built |
| 4 | Spatial evaluation replacing fixed attack patterns | Only the re-pick *trigger* got real spatial awareness; `pickAttackPattern` itself is still the same weighted-random choice among 5 named patterns |
| 5 | Objectives vs. execution methods | One pattern (`wing_carry`) only, and only the *order* methods are tried in, not a true per-method scoring system; the other 4 patterns are untouched |

---

## What this rebuild deliberately did NOT attempt

- A full continuous multi-agent simulation replacing the decide→animate
  loop. The engine is still fundamentally "ball carrier decides, then
  animates," with the reaction-burst functions (Problem 8) as a bounded
  patch on top, not a replacement.
- Anticipation/pre-pass defender movement (Problem 7).
- Animation/physics synchronization as a general principle (Problem 9).
- Aerial duel modeling with the pressure field (still its own separate,
  older formula).
- Rebuilding `pickAttackPattern`'s pattern *selection* itself, or any
  pattern besides `wing_carry`'s method ordering.
- Player orientation/facing/first-touch direction (Problem 11) — this would
  require adding a new property to the player data model, not just a new
  formula.

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
```

Each commit message contains the specific before/after reasoning and the
verification steps taken for that piece.
