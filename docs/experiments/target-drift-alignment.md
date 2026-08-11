# Target-drift layer alignment

Follow-on to [target-drift-decomposition.md](target-drift-decomposition.md),
which measured each perturbation layer's *magnitude* but not its
*direction* relative to the underlying tactical intent — leaving open
whether the 1.47× gross/net churn ratio came from layers reinforcing the
base signal, deliberately opposing it, or just adding uncorrelated noise.

## Question

For each perturbation layer, does its displacement vector tend to point
the same way as the base tactical signal's own current direction of
travel (reinforcing), the opposite way (opposing), or is it uncorrelated
(noise)?

## Method

Extended the (diagnostic-only, removed after archiving) instrumentation in
`updateTeamShape`'s finalization loop to snapshot each pin's full
pitch-% position at every stage (not just magnitudes this time), plus the
previous call's base position. Analysis (in-browser, not shipped):
"base tactical vector" = this call's pre-perturbation position minus the
previous call's; each layer's vector = its stage delta. Cosine similarity
computed per evaluation where both vectors exceed a 0.15 pitch-% noise
floor (comparisons below that are dropped as directionless). Collected
9,733 evaluations from a live match (~24 simulated minutes).

## Results

| layer | comparable samples | mean cosine | reinforcing | opposing | orthogonal |
|---|---:|---:|---:|---:|---:|
| Arc wobble | 2,466 | **0.041** | 38.4% | 32.9% | 28.7% |
| Width elasticity | 1,809 | **0.013** | 40.2% | 37.6% | 22.2% |
| Box-threat jitter | 784 | **-0.005** | 38.8% | 39.8% | 21.4% |
| Near-opponent check-away | 622 | 0.200 | 44.7% | 23.3% | 32.0% |
| Counter anticipation | 461 | **-0.543** | 16.7% | 75.9% | 7.4% |

(Sample sizes shrink layer to layer because each layer is only "comparable"
on evaluations where both it and the base vector clear the noise floor —
jitter and anticipation are gated to begin with, per the earlier
decomposition experiment.)

**Arc wobble, width elasticity, and box-threat jitter are all
statistically indistinguishable from random noise relative to tactical
direction** (mean cosine ≈ 0, roughly even 3-way split between reinforcing/
opposing/orthogonal for all three). These are exactly the three layers
that dominated gross churn (85.4% combined) in the prior experiment. That
combination — dominant magnitude, zero directional correlation with intent
— is precisely what produces a high gross/net ratio: they add a lot of
movement that doesn't reliably point anywhere in particular, so a good
chunk of it gets undone by the next tick's opposite-signed contribution
(jitter is literally `rng()-0.5`, so zero correlation is expected and
correctly measured; wobble's near-zero result is more notable, since it
was added specifically for perceived liveliness, not as noise, yet
measures indistinguishable from it; elasticity's near-zero result is less
damning by itself — its job is width compression/expansion based on team
phase, not "point toward wherever the target is currently heading," so a
low alignment score doesn't necessarily mean it's badly designed, just
that this particular metric isn't the right lens for judging it).

**Counter anticipation is the one clear outlier — strongly *opposing* the
base vector (75.9% of the time), not random.** This is plausibly by
design, not waste: it only fires for STs/Ws on the defending side when
`counterReadiness` is high, deliberately nudging them forward in depth to
preserve an outlet — likely fighting against a base shape that's
otherwise retreating during that same phase. Anti-correlation here reads
as intentional tension between "the team is dropping off" and "keep a
counter option alive," not accidental churn, though the small sample
(461, since it's gated to 14.5% activation) means this should be treated
as a lead, not a settled conclusion.

**Near-opponent check-away is mildly reinforcing** (mean cosine 0.20,
44.7% reinforcing vs. 23.3% opposing) — a collision-avoidance nudge that
happens to correlate somewhat with where the base signal is already
pushing, plausibly because both respond to the same local opponent
geometry.

## Conclusion

The three layers responsible for 85% of gross target churn (wobble,
elasticity, jitter) are also the three with no measurable directional
relationship to tactical intent — they're not correcting the base signal,
not reinforcing it, just adding uncorrelated motion on top of it. Arc
wobble is the cleanest case: it has no tactical justification for its
direction (its phase is `sin(shapePulse*0.55 + iHash(pin.id)*5.1)`,
completely decoupled from the ball or team state), was added purely for
perceived liveliness, and now measures as statistically pure noise
relative to what the team is actually trying to do. Counter anticipation
is the one layer that clearly isn't noise — it's structured, sizeable, and
directionally consistent (just usually opposing rather than reinforcing),
consistent with intentional design rather than decoration.

## Decisions

- No behavior changes made — pure measurement, as scoped.
- Diagnostic instrumentation removed from `tactic_board.js` after
  archiving.
- Confirms arc wobble as the strongest candidate for the next
  intervention (amplitude reduction, isolated from every other layer) —
  not yet started, no scope agreed. Elasticity and jitter are also
  measured as uncorrelated noise but weren't the top-priority pick;
  anticipation should be left alone given the evidence it's doing
  deliberate, structured work rather than adding churn.
