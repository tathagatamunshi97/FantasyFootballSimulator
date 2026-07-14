# Match Replay Trace — Design Notes (Parked)

**Status:** Parked for later. Not started. This document captures the scoping
discussion so we can pick it back up without re-deriving context.

## The problem

Today, "replay" of a completed match does **not** show what actually
happened. `tactic_board.js` builds a fresh goal schedule purely from the
final score:

```js
const scheduled = replayScore ? scheduleGoals(homeGoalsTarget, awayGoalsTarget, rng) : [];
```

`scheduleGoals()` distributes N goals across 90 minutes using a fresh
`rng()` seed unrelated to the original live match. Replay is a *different*,
freshly-improvised match that happens to finish with the same scoreline —
different scorers, different minutes, different everything, purely by
coincidence if it ever lines up.

The ask: let a team review how they *actually* played (goals, patterns,
outcomes) after a live-hosted tournament match, not a re-roll.

## What already exists (the good news)

Live-hosted matches already log a genuinely rich, timestamped,
player-attributed event trace via `matchLog` in `tactic_board.js`:

- Every goal: minute, scorer, assister
- Every shot / big chance, with estimated xG
- Every save, every blocked shot (new as of this session)
- Every dribble won/lost, every turnover, every offside

This gets persisted server-side already, via `complete_from_board()` in
`web/tournament.py`, into the tournament document (`board_events`/
`match_log`). So "what actually happened, event-wise" is not missing data —
it's captured and stored today. Replay mode just doesn't read it.

## Two tiers of fidelity — pick one to build

### Tier 1: Event-accurate replay (moderate effort)

Feed `scheduleGoals()`'s replacement the *real* stored goals (real minute +
scorer + assist) instead of generating a fresh schedule. The engine already
has the mechanism to force a goal at a scheduled minute
(`nextScheduledGoal`); it would just consume real data instead of invented
data.

**Result:** same goals, same scorers, same minutes. Buildup play *around*
each goal is still regenerated/plausible, not literally reproduced.

**Effort:** small-to-moderate. Mostly wiring — reuse existing scheduling
mechanism, change the data source.

### Tier 2: Full position-trace replay (large effort)

Record player/ball pitch positions during the live match at a sparse
sampling rate, then play back by interpolating between recorded keyframes
instead of running any decision logic.

This is the tier discussed in depth. Breakdown:

#### 1. Recording (moderate)
- Rendering runs on `requestAnimationFrame` (~60fps) — too fine-grained to
  record at that rate.
- Sample sparser: every 200–300ms (3–5 samples/sec). The *existing* easing
  code (`applyPinMotion`'s `stepTowardClamped`) already smooths between
  targets during live play — the same interpolation can smooth between
  recorded keyframes during playback, so recording doesn't need to be
  dense.
- Hook into the existing tick loop; buffer in memory; flush alongside the
  existing `matchLog` payload at full-time.

#### 2. Playback (moderate, but simpler than the live engine)
- A trace-playback mode needs **none** of the decision engine —
  no `decideAction`, no attack patterns, no `organicWillScore`. Just "read
  the next keyframe, interpolate, render."
- Structurally simpler than live mode. Can reuse most of the existing
  rendering/DOM-update code (`pinEls`, ball rendering) — only the "what
  decides where things go" layer changes.

#### 3. Storage (the real cost — needs care)
- Rough data volume: ~1,900 samples for an 8-minute watch (at the current
  0.5x/240s default) × 46 numbers (22 players + ball, x/y each) ≈
  **400–500KB per match** with compact encoding.
- **Do not embed this in the tournament document.** `load_tournament()`
  deserializes the whole document on every read — tournament pages,
  admin actions, fixture lists all pay that cost. Bloating every
  tournament load for a feature only used when someone opens replay for
  one specific match would be a real regression.
- **Correct pattern:** store each match's trace as its own R2 object,
  e.g. `tournaments/{tournament_id}/traces/{match_id}.json`, mirroring
  the existing pattern already used for match analysis
  (`r2_storage.save_match_analysis` / `load_match_analysis`). Fetch it
  only when replay is actually opened for that match.

#### 4. Fallback handling
- Only live-hosted matches would ever have a trace. Instant "Run match"
  Monte Carlo simulations, and any match completed before this feature
  ships, would have none.
- Replay needs to fall back cleanly to Tier 1 (or today's improvised
  behavior) when no trace exists — never break for older results.

## Recommendation when we pick this back up

Start with **Tier 1** regardless of whether Tier 2 ever gets built — it's
a small fraction of the effort, immediately makes replay meaningfully
truthful (real scorers/minutes), and isn't wasted work if Tier 2 comes
later (Tier 2 is additive on top, not a replacement).

Only go to **Tier 2** if "real goals, plausible buildup" genuinely isn't
enough for how the team wants to review matches — e.g. if they specifically
need to see the actual passing sequence or defensive shape that led to a
goal, not just that it happened.

## Open questions to resolve before starting

- Sampling rate for Tier 2 (200ms? 300ms? — tradeoff between file size and
  playback smoothness).
- Do we want scrub/pause/seek controls on replay, or just a straight
  watch-through?
- Does Tier 2 need to cover every match going forward, or only ones a team
  explicitly flags for review (to bound storage growth)?
- Retention: do old traces ever get pruned, or kept indefinitely in R2?

## Non-goals (explicitly out of scope for this plan)

- Reconstructing traces for matches played before this feature exists —
  not possible, no data was recorded.
- Recording anything beyond the existing engine's own decisions — this is
  about replaying what the engine already did, not adding new gameplay
  logic (see the gameplay fixes done separately this session: blocked
  shots, goalkeeper quality in saves, CM/AM one-two, recycle-bias tuning,
  marking reaction, wide-final-third gating).
