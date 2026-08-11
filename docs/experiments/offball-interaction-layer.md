# Off-ball interaction-layer experiment

Follow-on to [carrier-optimizer-prototype1.md](carrier-optimizer-prototype1.md).
That experiment showed the ball carrier's own movement is already stable and
smooth; the open question was whether the remaining gap with FM-style
realism lives in how nearby off-ball players respond during a carry.

## Question

During a live carry, what proportion of nearby off-ball movement comes from
continuous/staggered tactical evolution versus discrete, synchronized
periodic updates?

## Method

Diagnostic-only instrumentation in `web/static/tactic_board.js` (removed
after this data was archived), gated behind `window.__diagOffBall`:

- Converted every pin's `tx`/`ty` properties to accessor properties that log
  every write — `{t, pinId, dim, from, to, reason}` — with `reason`
  resolved automatically from the JS call stack (the name of whichever
  function actually performed the assignment), rather than hand-tagging the
  ~25 call sites that write `tx`/`ty` across the file. This is more
  accurate than a manually-maintained enum and can't drift out of sync with
  the code.
- Each tick, while a player is carrying, snapshotted the carrier's nearest 5
  teammates + nearest 2 opponents (by distance, tagged with role/side) as
  the "interaction bubble" for that instant.
- Watched one full live match, collecting 32,563 target writes and 7,092
  carry-bubble frames.

## Results

### Trigger-frequency calibration (whole match, ~81 simulated minutes)

| reason | calls | avg players/call | total writes |
|---|---:|---:|---:|
| `shape_update:decision_timer` | 443 | 19.4 | 17,192 |
| `shape_update:action_timer` | 376 | 20.5 | 15,414 |
| `triggerDefensiveBreachReactions` | 56 | 3.64 | 410 |
| `triggerReceptionReactions` | 34 | 1.32 | 90 |
| `triggerCarrierRotationReaction` | 95 | 1.0 | 184 |
| `triggerTurnoverReactions` | 5 | 1.0 | 10 |
| everything else (doPass/doDribble/doCarry/doShot/box runs/etc.) | ~76 | ~1.1 | ~150 |

The two `shape_update` paths alone account for ~32,600 of the ~32,860 total
writes (>99%) and fire ~819 times over the match — roughly every 6 real
seconds of match-clock time, each time touching ~20 of the 22 players at
once. Every individual event-reaction trigger combined (breach, reception,
turnover, carrier rotation, plus every actual pass/dribble/carry/shot
follow-through) accounts for well under 1% of write volume, and each of
those affects on average ~1 player, occasionally 2-4 for the coordinated
ones (breach reactions move the beaten defender + cover + screen + far
fullback together).

### Per-carry analysis (165 carries ≥ 8 frames)

- Mean interaction-bubble size: 7.64 nearby players tracked per carry.
- Mean players who actually got a target adjustment during the carry: 6.43
  (84% of the bubble) — **0/165 carries had zero off-ball adjustment**, so
  off-ball players are always moving during a carry, just not necessarily
  continuously or independently.
- **Synchrony Index** (largest simultaneous update cluster ÷ total updates
  in the carry): mean 0.547, median 0.5. On a typical carry, half of all
  off-ball target updates in the bubble land in the single largest
  synchronized wave.
- Per-pin event reasons during carries are overwhelmingly
  `shape_update:decision_timer` / `shape_update:action_timer`, with only
  occasional single interjections from an event-specific reaction.

### Shape of target evolution (1,061 pin-traces across all carries)

- 23% single-event (one jump only, no further adjustment during that carry).
- 59% monotonic ("staircase" — a sequence of same-direction steps).
- 10% oscillating (direction flips repeatedly).
- 8% mixed.
- Median gap between consecutive updates for the same pin: ~0.09
  match-minutes (~5.5 match-seconds).
- Median step magnitude: 2.58 pitch-%, p90: 2.70 pitch-% — a consistent,
  moderate-size discrete jump, not continuous drift and not huge
  discontinuous teleports either.

One representative carry (home-ST, 0.40 match-minutes,
[visualized here](https://claude.ai/code/artifact/9281b0ee-da9d-45c3-8687-60953da7562b))
shows the pattern directly: 9 nearby players update in near-perfect unison
at t=0, 0.146, 0.313, and 0.402 (all `shape_update` waves), with exactly one
solo event (`triggerCarrierRotationReaction`, home-AM, t=0.015) in between.

## Conclusion

The architectural question is answered clearly: **off-ball movement during
a carry is overwhelmingly driven by the periodic bulk shape-refresh system
(`updateTeamShape`, invoked from both the coarse decision timer and the
more frequent action timer), not by staggered, individually-triggered
reactions.** Event-driven reactions (breach cover, reception support runs,
turnover reactions, carrier rotation) exist, fire regularly, and are
individually well-targeted — but they are a small minority of total
off-ball movement volume, even restricted to the tight bubble immediately
around the ball. The step pattern (median ~2.6 pitch-% every ~5.5
match-seconds, 59% monotonic) is best described as a "staircase" — coarse,
regular, purposeful steps toward a periodically-recomputed target — rather
than continuous drift (like the carrier optimizer) or pure noise.

This is the likely source of whatever "FM feel" gap remains after the
carrier work: FM's off-ball players read as continuously alive because many
individual, causally-linked adjustments (a CB stepping causes a winger to
widen causes a mid to rotate) happen in a staggered cascade; here, ~20
players' positions get recomputed together on a shared clock roughly every
6 seconds, which is legible as "the team shape refreshing" rather than
"players individually reading the game."

## Follow-up measurement: are the synchronized writes substantive or cosmetic?

The initial result (>99% of writes from `shape_update`) only measured that a
write happened, not whether it represented a meaningful position change —
20 simultaneous writes could equally mean 20 real repositionings or 20
near-identical no-ops. Re-instrumented (same diagnostic pattern, tx/ty
write log only, no bubble tracking needed this time) and collected a fresh
~31-minute sample: 329 `shape_update` firings, 6,730 individual per-player
distance-moved observations, each pairing that firing's tx+ty delta into
one 2D magnitude.

| threshold | % of writes exceeding it | avg players/firing exceeding it (of ~20) |
|---|---:|---:|
| > 0.5 pitch-% | 91.5% | 18.72 |
| > 1 pitch-% | 81.5% | 16.66 |
| > 2 pitch-% | 52.5% | 10.73 |
| > 3 pitch-% | 0% | 0 |

Median distance moved per write: 2.17 pitch-%. Mean: 1.83 pitch-%. Only
8.5% of writes are ≤0.5 pitch-% (genuinely cosmetic). The 0% above 3
pitch-% lines up exactly with `updateTeamShape`'s own `maxJump` cap (2.6 for
a normal off-ball player, 3.8-4.2 only while pressing/running) — so writes
aren't hitting an arbitrary ceiling, they're hitting the engine's own
per-recompute jump limit almost every time.

Example single firing (`t=0.625`, 21 players, sorted by distance moved):
top 5 players moved 2.2-2.7 pitch-%, the next 12 moved 1.0-1.2 pitch-%, and
only the two goalkeepers + one uninvolved fullback moved under 0.75.

**Conclusion: the synchronized refreshes are substantive, not cosmetic.**
This rules out the alternative explanation (many near-identical low-impact
writes inflating the apparent synchrony) and reinforces the original
finding rather than undermining it — on a typical `updateTeamShape` firing,
roughly 17-19 of ~20 players receive a real, non-trivial target change at
the same instant. The "who updates" question (evaluate everyone but only
commit targets above a materiality threshold, or only for a small
functionally-relevant set) is therefore a live, well-motivated next
experiment rather than one likely to dissolve the finding.

## Decisions

- Diagnostic instrumentation removed from `tactic_board.js` now that this
  data is archived (same pattern as the carrier-optimizer experiment).
- No code changes made to `updateTeamShape`, the reaction triggers, or
  anything else — this was pure measurement, per the agreed scope.
- Next step is a design/architecture decision, not another measurement:
  whether and how to convert more of the shape-refresh cadence into
  staggered, causally-triggered reactions (extending the existing
  `triggerXReactions` pattern) without touching the (already-verified
  stable) carrier optimizer — not yet started, no scope agreed.
