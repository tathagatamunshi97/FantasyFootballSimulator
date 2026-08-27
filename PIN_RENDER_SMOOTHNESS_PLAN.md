# Pin Render Smoothness — Design Notes (Implemented)

**Status:** Primary fix implemented (transform-based positioning). Verified
programmatically in this environment (proportional position correctness,
per-frame movement via a patched raf loop, a full 90-minute match completing
cleanly with zero console errors) — a live devtools Performance-panel
frame-timing comparison and a real phone/live-match eyeball check are still
outstanding, per the Verification gap note below (this environment still
cannot composite/screenshot the board, same limitation noted at diagnosis
time). The secondary `visibilitychange` fallback was evaluated and skipped —
`dt` is already unconditionally clamped to 0.05 in `_tickBody` regardless of
how stale `lastTs` gets, so there was no actual bug for it to fix.

## The ask

User shared a WhatsApp video and asked why pin movement in it looked
smoother than "what we have here." Diagnosis below.

## What the video actually is

Frame-extraction (ffmpeg via `imageio-ffmpeg`, no video tool was already
available in this repo/env) confirmed the clip is **Football Manager 26
Mobile** (Chelsea vs Liverpool, FA Cup 5th round) — FM's own Match Settings
panel, Substitutions screen, Team Talk screen, and an Android status bar
all appear in sampled frames. So the real question is "why isn't our
web-rendered pin animation as smooth as a native compiled game's," not a
bug relative to some other part of our own app.

Checked the pins specifically (20 consecutive frames, 30fps, ~0.67s
window): FM's dots move in small, steady per-frame increments — no
teleporting, no held frames. That's the expected baseline for a native,
GPU-composited render loop with nothing else competing for the frame
budget.

## Where our engine actually stands (not the naive-math problem it might look like)

`applyPinMotion()` in [tactic_board.js](web/static/tactic_board.js) (around
line 9437) is already a fairly sophisticated continuous-motion system:

- Real velocity (`pin.vx`/`vy`) that turns gradually toward a desired
  heading (steering, not instant re-aim) — curved paths, slight
  overshoot/correction.
- Deceleration radius so pins slow down approaching a target instead of
  cruising at full speed and snapping to a stop.
- Bezier-curved scripted paths (`_pathCtrl`) for special moves (e.g. a
  shot's plant-foot bulge).
- A *second* smoothing pass: rendered position (`pin.rx`/`ry`) trails the
  logical position (`pin.left`/`top`) rather than the DOM chasing the
  target directly.

This is not the "the interpolation model is naive" case one might expect —
the motion math is good. The smoothness gap is in the rendering substrate
underneath it.

## Root cause

1. **Layout-triggering CSS properties, every frame, on every pin.**
   [tactic_board.js:9605-9606](web/static/tactic_board.js:9605) (and the
   ball equivalents, and debug-dot equivalents — 21 occurrences total in
   the file) write `el.style.left` / `el.style.top` as percentages, once
   per `requestAnimationFrame` tick, for up to 22 pins + the ball (+ debug
   dots if enabled). `left`/`top` are layout-triggering CSS properties —
   the browser recomputes layout and repaints each of those elements every
   single frame. That work happens on the *same* JS main thread that's
   also running the full tactical decision engine (the multi-thousand-line
   lerp/steering logic in this same file) every frame. FM Mobile has no
   such contention — native, GPU-composited, nothing else sharing the
   frame budget.

2. **An existing but ineffective attempted fix.**
   [styles.css:1412](web/static/styles.css:1412) already has
   `will-change: left, top;` on `.tactic-pin` — a fossil suggesting someone
   previously suspected this exact cost and tried to hint the browser
   about it. It doesn't help: `will-change` only meaningfully offloads
   *compositor-only* properties (`transform`, `opacity`) to the GPU;
   `left`/`top` force layout regardless of the hint. Confirm-and-replace,
   not "already handled."

3. **`requestAnimationFrame` fully stops when the page isn't visible/composited.**
   Confirmed directly (not assumed): with the render surface not actively
   displayed, `document.hidden` was `true` and polling pin `style.left` /
   the match clock showed both completely frozen — no throttling, full
   stop. This is standard browser behavior for hidden documents. On a
   phone, screen-lock / app-switch / a notification banner will stall the
   *entire* board (positions and match clock alike) the same way, since
   `tick()`'s only driver is `raf = requestAnimationFrame(tick)` — no
   fallback timer. A native app's render loop doesn't share this failure
   mode. Likely a secondary, intermittent contributor to "choppy," not
   the main one — but real, and previously undocumented.

## The fix (not yet implemented)

**Primary:** switch pin/ball positioning from `style.left`/`style.top`
percentage strings to a `transform: translate(...)` (composed with the
existing `translate(-50%, -50%)` centering transform already on
`.tactic-pin`). Compositor-only property, no layout/paint per frame — the
standard, well-established fix for this exact class of DOM-animation jank.
Touches:

- `applyPinMotion()` render step — [tactic_board.js:9602-9606](web/static/tactic_board.js:9602)
  and its snap-pose sibling around [tactic_board.js:9639-9640](web/static/tactic_board.js:9639).
- Ball render — [tactic_board.js:2214-2215](web/static/tactic_board.js:2214),
  [tactic_board.js:2231-2232](web/static/tactic_board.js:2231),
  [tactic_board.js:9661-9662](web/static/tactic_board.js:9661).
- Debug dots — same pattern, lower priority (debug-only overlay).
- `styles.css:1402-1413` (`.tactic-pin` base rule) — drop the now-inert
  `will-change: left, top` in favor of `will-change: transform`, keep
  `position: absolute` (needed for the container-relative percentage
  layout position) but stop writing `left`/`top` per frame — set them once
  at pin creation and drive all subsequent movement through `transform`.
- `toRenderXY()` and any other helper that currently returns
  percentage-for-`style.left/top` — needs a variant (or the same return
  shape reused) that feeds a transform string instead.

**Secondary (smaller, optional):** give `tick()` a fallback so a stall
doesn't sit frozen indefinitely once the tab regains visibility — e.g.
also resync on the `visibilitychange` event so a long hidden period
doesn't leave `lastTs` stale in a way that causes a single oversized
`dt` on return (currently clamped to 0.05 in `_tickBody`, so this is a
minor correctness/UX detail, not a live-blocking one).

## Effort / risk

- **Moderate effort, contained.** The transform swap is mechanical
  (same computed x/y values, different CSS property to write), but
  `tactic_board.js` is a large, heavily-tuned file with a lot of
  historically fragile animation code (see git log — multiple past
  "engine fix" comments inline around this exact function). Needs the
  same care as other engine-behavior changes in this codebase: implement,
  smoke-test with the Team Lab random-match flow, and treat as unverified
  until reviewed live on an actual phone (this diagnosis was done via
  static code reading + a FM reference video; no live before/after FPS
  comparison was possible in this session — see below).
- **Do this on a clean base.** `tactic_board.js` already had uncommitted
  changes at diagnosis time (unrelated to this). Land or stash those
  first so the transform change is its own reviewable diff.
- **Verification gap:** this session could not get a live rendered
  comparison of our own board (the browser preview pane wasn't
  compositing frames in this environment, so `requestAnimationFrame`
  never ran — which is itself what surfaced finding #3 above). Whoever
  picks this up should verify the transform swap with actual devtools
  frame timing (Performance panel, look for reduced "Layout"/"Recalculate
  Style" time per frame) plus a real phone/live-match eyeball check, not
  just code review.
