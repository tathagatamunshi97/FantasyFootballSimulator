# Target-drift source decomposition

Follow-on to [offball-interaction-layer.md](offball-interaction-layer.md).
Prototype 2 (conditional target commits, restricting *who* is allowed to
commit a new target during the action-timer refresh) was implemented and
tested, then **abandoned** — see below — in favor of this measurement.

## Why Prototype 2 was abandoned

Implemented: `updateTeamShape(fullCommit)` — the decision-timer call stays
unchanged (full team refresh, safety net); the action-timer call only
commits `tx`/`ty` for a functional core (carrier, nearest 2 teammates +
nearest 2 opponents to the carrier, anyone `_pressing`/`_running`, or an
"emergency" escape hatch reusing the existing `jump > maxJump` check).

Result over 215 action-timer firings: **mean 20.96 of 21.13 evaluated
players still committed** (mean suppressed: 0.17/firing). The policy was
almost a complete no-op. Root cause: the "emergency" escape hatch fired for
nearly everyone nearly every time, because computed targets are *already*
routinely moving further than one tick's `maxJump` allowance — not a rare
special case, but close to the normal state. Reusing `jump > maxJump` as an
"emergency" signal doesn't actually discriminate anything under the
current tuning. Rather than pick an arbitrary new threshold to hide that
fact, the change was fully reverted (`updateTeamShape` back to its
original single-branch, always-commit form) and the investigation moved
one layer upstream: **why is the desired target itself moving so much
between refreshes?**

## Question

Decompose the shape target's movement into its contributing sources.
Which layers actually drive target drift: the base tactical signal
(formation + ball position + role + phase), or the "alive"/organic
perturbation layers added over the course of this project (width
elasticity, arc wobble, box-threat jitter, counter-anticipation, near-
opponent check-away)?

## Method

Diagnostic-only instrumentation inside `updateTeamShape`'s per-pin
finalization loop (`web/static/tactic_board.js`, removed after archiving):
snapshotted the pin's pitch-% position at each of 6 sequential stages
(pre-perturbation base, after width elasticity, after box-threat jitter,
after counter-anticipation, after arc wobble, after near-opponent
check-away = final), and recorded each stage's incremental pitch-%
displacement. Also recorded each pin's base-signal call-to-call drift
(comparing this call's pre-perturbation position to the previous call's).
No behavior change — pure snapshotting of values already being computed.
Collected 8,381 evaluations from a live match (~32 simulated minutes).

The base tactical signal (formation/ball/role/phase, computed in the ~150
lines above the finalization loop) could not be decomposed further without
a much larger, riskier restructure, so it's reported as one combined
figure (mean call-to-call drift) rather than split into formation vs.
ball vs. role sub-components.

## Results

[Visualized here](https://claude.ai/code/artifact/05fdfa28-8c96-4096-8d1c-9671479cc85a).

| layer | active on | mean magnitude when active | % of gross churn |
|---|---:|---:|---:|
| Arc wobble | 99.7% of calls | 1.45 pitch-% | 32.1% |
| Width elasticity | 82.7% | 1.64 pitch-% | 30.3% |
| Box-threat jitter | 26.2% (gated, defence under real pressure) | 3.94 pitch-% | 23.0% |
| Counter anticipation | 14.5% | 2.69 pitch-% | 8.7% |
| Near-opponent check-away | 26.1% | 1.03 pitch-% | 6.0% |
| **Base signal (formation+ball+role+phase)** | every call | **1.74 pitch-%** (call-to-call) | *not a churn component — reference only* |

- **Decorative layers (wobble + elasticity + jitter) = 85.4% of all gross
  target-movement churn.** Reactive layers (anticipation + check-away, the
  two most plausibly "tactical" in the traditional sense) = 14.7%.
- Arc wobble — a continuous `sin()` applied on every single recompute,
  originally added this session for player liveliness/curved locomotion —
  is active on 99.7% of calls and is the single largest churn contributor.
- Gross churn (sum of all layer magnitudes) is **1.47×** the net final
  displacement — meaning a substantial share of these perturbations are
  pulling in different directions and partly cancelling each other out
  rather than compounding into purposeful movement.
- The base tactical signal's own call-to-call drift (1.74 pitch-%) is
  *smaller* than elasticity's or wobble's typical individual contribution,
  and less than half of jitter's.

## Conclusion

**Scenario B, not Scenario A.** The target isn't drifting primarily because
the ball or tactical picture is genuinely changing that fast — the
"alive"/organic perturbation layers, especially arc wobble (always on) and
width elasticity (almost always on), are the dominant source of target
churn, well ahead of the base tactical signal itself. This explains why
Prototype 2 was a no-op: restricting *who* commits doesn't help when the
*target itself* is being pushed around by layers that fire on nearly every
pin, nearly every call, regardless of tactical relevance. It also explains
why conditional target commits looked promising on paper — the interaction
bubble is real and tactically meaningful — but couldn't produce a visible
effect while the shape-space target underneath it is this restless.

## Decisions

- Prototype 2 (conditional commits) fully reverted — not shipped.
- Diagnostic instrumentation removed from `tactic_board.js` now that this
  data is archived.
- No behavior changes made in this experiment — pure measurement, as
  scoped.
- Next step (not yet started, not yet scoped): whether/how to dampen the
  decorative layers — particularly arc wobble and width elasticity, the
  two biggest and most persistent contributors — without losing the
  liveliness they were built for. This is a genuinely different
  intervention point than either Prototype 1 (carrier) or the abandoned
  Prototype 2 (commit policy): it targets the *magnitude of the target
  signal itself*, not who gets to follow it or how.
