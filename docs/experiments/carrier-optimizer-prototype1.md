# Prototype 1 — continuous local optimization, ball carrier only

Archived findings from the carrier-optimizer experiment (2026-07-27). The
diagnostic instrumentation this data came from (`window.__diagOptimizer` in
`optimizeCarrierPosition`, `web/static/tactic_board.js`) has been removed from
the codebase — this file is the durable record.

## What was tested

Replaced "steer toward a periodically-assigned target" (`pin.tx/ty`, updated
every `DECISION_INTERVAL_MIN/MAX` 0.22–0.48 match-minutes) with "every frame,
re-evaluate a 12-point ring + stay-put, score each via `scoreOpenSpace` +
progress + momentum, drift toward the best" — for the ball carrier only, for
exactly one frame at a time, using only existing utility functions. No new
tactical heuristics were added.

## Method

Instrumented `optimizeCarrierPosition` to record every candidate's score,
the chosen point, velocity, and the pre-existing target (`tx/ty`) per frame,
gated behind `window.__diagOptimizer` (no effect on normal play). Watched a
full live match. Frames were grouped into "carry episodes" by detecting
position jumps larger than the engine's own per-frame movement cap
(`cruiseSpeed * 1.6 * dt`, dt ≤ 0.05s, empirically < ~2 pitch-%) — this
segmentation is done at capture time, not reconstructed after the fact from a
time-gap heuristic, which an earlier pass showed produces false merges (two
separate touches by the same player counted as one continuous carry).

## Results (108 qualifying carries ≥ 8 frames, from 115 total episodes / 2855 frames)

- **Reversals: 0/108.** (A single reversal seen in an earlier, contaminated
  69-carry sample turned out to be exactly this segmentation artifact — a
  reception discontinuity merged into a carry, not real oscillation.)
- **Mean path efficiency 1.014, median 1.001** — carries are close to
  straight lines; only 2/108 (1.9%) exceeded 1.15.
- **Heading divergence vs. the pre-existing target (`tx/ty`)**: 93.6% of
  frames differ by more than 20°. This is *not* evidence of instability —
  `tx/ty` is the team-shape "return to your slot" anchor computed by
  `updateTeamShape`, not a carrying-direction system. The two are naturally
  near-orthogonal while a player sprints forward with the ball; they operate
  on different timescales ("eventually return here" vs. "given I have the
  ball, what's my next 1–2 metres").

## Conclusion

The carrier optimizer is stable — smooth, non-jittery, low-reversal, close
to straight-line efficient. It behaves like a constrained steering
controller, not a hill-climbing search. This **falsified the original
hypothesis** that continuous optimization would make the carrier visibly
more exploratory/FM-like on its own.

**Implication:** continuous local optimization for the carrier alone is not
sufficient to close the gap with FM's visual realism. The remaining gap most
likely lives in the off-ball interaction layer — how much nearby non-carrier
players (nearest defender, support runners, the eventual receiver) adjust in
response to the carrier, and whether those adjustments are continuous or
only tick-driven — not in refining the carrier's own movement further.

## Decisions

- Keep `optimizeCarrierPosition` and its wiring in `applyPinMotion` as-is —
  it works, don't touch it.
- Do **not** add a velocity-biased sampling cone or a switching-cost penalty
  — nothing in the measurements motivates them.
- Diagnostic instrumentation (`window.__diagOptimizer`, episode
  segmentation, `tx/ty` capture) removed from `tactic_board.js` now that
  this data is archived.
- Next experiment (not yet started): instrument off-ball motion during a
  carry — how many nearby players' desired positions change by more than a
  threshold, how large the changes are, and whether they're caused by a
  specific trigger (defender steps → winger widens → mid rotates) or just
  the periodic decision tick firing for everyone at once.
