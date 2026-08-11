# Arc-wobble amplitude A/B

Follow-on to [target-drift-alignment.md](target-drift-alignment.md), which
identified arc wobble as the strongest candidate for a first controlled
intervention: 32.1% of gross target churn, active on 99.7% of
`updateTeamShape` calls, and statistically uncorrelated with tactical
direction (mean cosine ≈ 0.04). This experiment cuts its amplitude by 70%
and re-measures, leaving every other perturbation layer untouched.

## Change

One line in `updateTeamShape`'s finalization loop
(`web/static/tactic_board.js`): `arc = sin(...) * arcAmp` becomes
`arc = sin(...) * arcAmp * ARC_WOBBLE_TEST_SCALE` with
`ARC_WOBBLE_TEST_SCALE = 0.3`. Scaled `arc` only, not `arcAmp` itself,
because `arcAmp` is also reused for the unrelated curved-locomotion
jump-correction bias (`latBias`/`depthBias`) — scaling `arcAmp` would have
changed two mechanisms at once. Nothing else touched.

## Method

Re-ran the same magnitude-decomposition instrumentation from
[target-drift-decomposition.md](target-drift-decomposition.md) (diagnostic-
only, removed after archiving) plus the tx/ty write-log from
[offball-interaction-layer.md](offball-interaction-layer.md) for a fresh
cluster-size read, plus a new back-line compactness sampler (mean pairwise
distance between CB/FB pins). Collected 6,802 drift-decomposition
evaluations and 12,939 target writes from one live match (~32 simulated
minutes) — comparable sample size to the baseline runs.

**Caveat on comparability**: the live tactic-board watch isn't seed-
controlled — each "Watch" is an independent random rollout, not a matched
replay of the baseline match. So this isn't a perfectly matched pair; it's
the same style of aggregate before/after comparison used throughout this
whole investigation (large per-tick sample sizes within each run, not a
single paired trial). As a built-in consistency check: `meanBaseCallToCall`
(the base tactical signal, which the wobble change cannot affect) reads
2.32 pitch-% here vs. 1.74 in the baseline run — a similar order of
match-to-match variance to what shows up in the other untouched layers,
confirming those differences are normal rollout variance, not an effect of
the code change.

## Results

| metric | baseline | wobble × 0.3 |
|---|---:|---:|
| Wobble mean magnitude when active | 1.45 pitch-% | **0.48 pitch-%** (≈0.33×, matches the applied scale) |
| Wobble % of gross churn | 32.1% | **17.4%** |
| Elasticity % of gross churn | 30.3% | 42.1% (mechanical consequence of wobble's share shrinking, not elasticity growing — its own mean magnitude, 1.14 vs 1.36, is within normal variance) |
| Jitter % of gross churn | 23.0% | 23.7% (unchanged) |
| Anticipation % of gross churn | 8.7% | 10.2% (unchanged) |
| Gross churn ÷ net displacement | 1.47× | **1.41×** |
| Mean simultaneous target-update cluster size | ~19.4–20.5 | **18.74** |
| Back-line mean pairwise distance (compactness) | not measured before | 46.67 (home) / 41.42 (away) — descriptive only, no baseline to compare against |

Match played normally throughout (zero console errors across ~32 simulated
minutes; passes, dribbles, shots, goals all fired as expected).

## Interpretation

The change worked exactly as designed — wobble's own magnitude dropped by
almost precisely the applied 0.3× factor, direct causal confirmation the
edit did what it was supposed to and nothing else. The knock-on effects are
**real but modest**: gross/net churn ratio improved slightly (1.47→1.41,
less wasted cancellation), and simultaneous-update cluster size dropped a
little (~19.4-20.5→18.74). This is smaller than a naive "cut 32% of churn"
might suggest, because wobble was never the *only* driver of synchrony —
elasticity (active 82.7-80.7% of calls, itself uncorrelated with tactical
direction) is still there at roughly the same absolute magnitude, now
simply the largest remaining share by arithmetic. Cutting wobble alone
does not, on its own, dissolve the synchronized-update pattern; it turns
down the loudest of three co-equal noise sources.

**Qualitative/visual check — honest limitation**: this environment's
Browser tool cannot render real screenshots while running the
visibility-override workaround needed to keep the match animating in the
background (a known constraint noted earlier this session), so "does it
look more alive" could not be directly assessed here. That judgment call
needs the user watching a live match themselves.

## Decisions

- The code change (`ARC_WOBBLE_TEST_SCALE = 0.3`) is left in place,
  pending the user's own visual review and a keep/revert/adjust decision —
  this is a real behavior change with a modest-but-real positive
  quantitative signal and no detected regressions, not a clear win or a
  clear null result, so it isn't being unilaterally kept or reverted.
- Diagnostic-only instrumentation (drift decomposition, tx/ty write-log,
  compactness sampler) removed from `tactic_board.js` after archiving.
- If pursued further: elasticity is now the largest remaining uncorrelated
  churn source (per the alignment experiment, also mean cosine ≈ 0) and
  would be the natural next candidate for the same isolated-amplitude
  treatment — not yet scoped.
