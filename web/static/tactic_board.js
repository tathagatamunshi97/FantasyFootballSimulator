/**
 * Tactic-board pitch — FM / Top Eleven style 2D pin match.
 *
 * SPACE-DRIVEN + PASSING-NETWORK football (decide → animate → decide):
 *   Every decision tick hierarchy:
 *     1. Team possession STATE
 *     2. Shape — updateTeamShape() for BOTH teams (all 22 targets) BEFORE ball choice
 *        Support roles + lane-clearing movement so the carrier keeps 3–5 options
 *     3. Individual movement / flank links / decoys
 *     4. Space / passing-lane evaluation (not rating-first receiver picks)
 *     5. Ball decision (pass / dribble / recycle / shoot / through)
 *     6. Animation only visualizes pre-decided targets + ball flight
 *
 *   Intelligent risk (not max possession safety):
 *     Progression urgency rises with spell.actions — force vertical play, not endless recycle.
 *     Shallow attack-sequence look-ahead (pass + next 1–2) beats isolated lane-maxing.
 *     Justified switches only; triangles / third-man combos / through balls create chances.
 *     Team matchups (attack–defend, press–resist, flank, aerial) reshape urgency, patterns & marking.
 *     Possession→chance/xG: lower ball-control soft-scales shot volume (floored so a solid attack
 *     unit cannot be starved to ~half the opponent's xG without an extreme mismatch); maestros
 *     partially offset; high-poss sides muted vs much stronger opp creation + defence/mid-def shield.
 *
 *   Possession states (depth + box occupation, not timers alone):
 *     BUILD_UP → PROGRESSING → FINAL_THIRD → BOX_OCCUPATION → CHANCE_CREATION → FINISH
 *     Recycle drops state back. Defending side gets defensive shape targets.
 *
 *   Pattern confidence starts at 100 (−15 / ball action); at 0 re-pick.
 *   High confidence biases channels slightly; blocked lanes still win.
 *
 *   Animation: left/top = logical (decisions/offside); rx/ry = rendered sprite.
 *   Targets (tx/ty) may jump; logical/render move via speed-clamped ease only
 *   (except kickoff / goal / HT / reset snaps). Renderer never leads the engine.
 *
 * Never decide outcomes mid-tween; never hop pins.
 * Official tournament score comes from goals scored here (engine: tactic_board).
 */
(function (global) {
  "use strict";

  /** Team-relative layouts: [x 0–1 left→right, depth 0–1 own goal→attack]. Resting shape; live play uses block lines. */
  const FORMATION_LAYOUTS = {
    "4-4-2": {
      GK: [0.5, 0.05],
      RB: [0.86, 0.2],
      CB1: [0.62, 0.18],
      CB2: [0.38, 0.18],
      LB: [0.14, 0.2],
      RM: [0.86, 0.4],
      CM: [0.58, 0.4],
      DM: [0.42, 0.34],
      LM: [0.14, 0.4],
      ST1: [0.62, 0.56],
      ST2: [0.38, 0.56],
    },
    "4-3-3 flat": {
      GK: [0.5, 0.05],
      RB: [0.86, 0.2],
      CB1: [0.62, 0.18],
      CB2: [0.38, 0.18],
      LB: [0.14, 0.2],
      DM: [0.5, 0.32],
      CM1: [0.68, 0.4],
      CM2: [0.32, 0.4],
      RW: [0.86, 0.56],
      ST: [0.5, 0.62],
      LW: [0.14, 0.56],
    },
    "4-3-3 attacking": {
      // DM/CM/AM used to all sit at x=0.5 — a dead vertical stack rather than
      // a midfield sharing the width. DM anchors central; CM and AM take
      // opposite half-spaces at their own depths, like a real 3-man midfield.
      // Kept inside the |x-0.5| < 0.08 band (flankOfPin's "C" range) so they
      // stay classified as central rather than being read as flank players.
      GK: [0.5, 0.05],
      RB: [0.86, 0.2],
      CB1: [0.62, 0.18],
      CB2: [0.38, 0.18],
      LB: [0.14, 0.2],
      DM: [0.5, 0.3],
      CM: [0.44, 0.4],
      AM: [0.56, 0.5],
      RW: [0.86, 0.58],
      ST: [0.5, 0.64],
      LW: [0.14, 0.58],
    },
    "4-3-1-2 diamond": {
      GK: [0.5, 0.05],
      RB: [0.86, 0.2],
      CB1: [0.62, 0.18],
      CB2: [0.38, 0.18],
      LB: [0.14, 0.2],
      DM: [0.5, 0.3],
      CM1: [0.7, 0.4],
      CM2: [0.3, 0.4],
      AM: [0.5, 0.5],
      CF1: [0.62, 0.62],
      CF2: [0.38, 0.62],
    },
    "4-3-2-1": {
      GK: [0.5, 0.05],
      RB: [0.86, 0.2],
      CB1: [0.62, 0.18],
      CB2: [0.38, 0.18],
      LB: [0.14, 0.2],
      DM: [0.5, 0.3],
      CM1: [0.7, 0.4],
      CM2: [0.3, 0.4],
      AM1: [0.62, 0.52],
      AM2: [0.38, 0.52],
      ST: [0.5, 0.64],
    },
    "3-4-1-2 (flat)": {
      GK: [0.5, 0.05],
      CB1: [0.72, 0.18],
      CB2: [0.5, 0.16],
      CB3: [0.28, 0.18],
      LM: [0.12, 0.4],
      DM1: [0.62, 0.34],
      DM2: [0.38, 0.34],
      RM: [0.88, 0.4],
      AM: [0.5, 0.5],
      CF1: [0.62, 0.62],
      CF2: [0.38, 0.62],
    },
    "3-4-1-2 (normal)": {
      GK: [0.5, 0.05],
      CB1: [0.72, 0.18],
      CB2: [0.5, 0.16],
      CB3: [0.28, 0.18],
      LM: [0.12, 0.4],
      DM: [0.42, 0.32],
      CM: [0.58, 0.38],
      RM: [0.88, 0.4],
      AM: [0.5, 0.5],
      CF1: [0.62, 0.62],
      CF2: [0.38, 0.62],
    },
    "3-4-2-1": {
      GK: [0.5, 0.05],
      CB1: [0.72, 0.18],
      CB2: [0.5, 0.16],
      CB3: [0.28, 0.18],
      LM: [0.12, 0.4],
      DM1: [0.62, 0.34],
      DM2: [0.38, 0.34],
      RM: [0.88, 0.4],
      AM1: [0.62, 0.5],
      AM2: [0.38, 0.5],
      ST: [0.5, 0.64],
    },
    "4-2-2-2": {
      GK: [0.5, 0.05],
      RB: [0.86, 0.2],
      CB1: [0.62, 0.18],
      CB2: [0.38, 0.18],
      LB: [0.14, 0.2],
      DM1: [0.62, 0.34],
      DM2: [0.38, 0.34],
      AM1: [0.62, 0.52],
      AM2: [0.38, 0.52],
      ST1: [0.62, 0.64],
      ST2: [0.38, 0.64],
    },
    "3-5-2": {
      GK: [0.5, 0.05],
      CB1: [0.72, 0.18],
      CB2: [0.5, 0.16],
      CB3: [0.28, 0.18],
      RWB: [0.9, 0.4],
      CM1: [0.68, 0.38],
      DM: [0.5, 0.32],
      CM2: [0.32, 0.38],
      LWB: [0.1, 0.4],
      ST1: [0.62, 0.6],
      ST2: [0.38, 0.6],
    },
    "4-2-3-1": {
      GK: [0.5, 0.05],
      RB: [0.86, 0.2],
      CB1: [0.62, 0.18],
      CB2: [0.38, 0.18],
      LB: [0.14, 0.2],
      DM1: [0.62, 0.34],
      DM2: [0.38, 0.34],
      RW: [0.86, 0.52],
      AM: [0.5, 0.52],
      LW: [0.14, 0.52],
      ST: [0.5, 0.64],
    },
    "3-4-3(1)": {
      GK: [0.5, 0.05],
      CB1: [0.72, 0.18],
      CB2: [0.5, 0.16],
      CB3: [0.28, 0.18],
      RWB: [0.9, 0.4],
      DM: [0.42, 0.32],
      CM: [0.58, 0.38],
      LWB: [0.1, 0.4],
      RW: [0.78, 0.58],
      ST: [0.5, 0.64],
      LW: [0.22, 0.58],
    },
    "3-4-3(2)": {
      GK: [0.5, 0.05],
      CB1: [0.72, 0.18],
      CB2: [0.5, 0.16],
      CB3: [0.28, 0.18],
      RM: [0.88, 0.42],
      DM: [0.42, 0.32],
      CM: [0.58, 0.38],
      LM: [0.12, 0.42],
      RW: [0.78, 0.58],
      ST: [0.5, 0.64],
      LW: [0.22, 0.58],
    },
  };

  const DEFAULT_LAYOUT = FORMATION_LAYOUTS["4-3-3 flat"];
  /**
   * Sim-seconds for a full 90' at 1× speed.
   * Default board speed is 0.5× → wall-clock ≈ 2 × MATCH_WATCH_SECONDS ≈ 6 minutes
   * (two 3-minute halves).
   */
  const MATCH_WATCH_SECONDS = 180;

  /** Role stagger within a team block (offsets from defence / mid / attack line depths). */
  const LINE_ROLE = {
    GK: "gk",
    CB: "def",
    FB: "def",
    DM: "mid",
    CM: "mid",
    AM: "atk",
    W: "atk",
    ST: "atk",
  };

  /** Small role bias on top of the shared line (individuality, not abandonment). */
  const ROLE_LINE_BIAS = {
    GK: 0,
    CB: 0,
    FB: 0.07,
    DM: -0.035,
    CM: 0.01,
    AM: 0.02,
    W: 0.02,
    ST: 0.055,
  };

  /** Lateral ball-attraction while attacking — CMs offer the primary progressive angles. */
  const ATTACK_BALL_X = { GK: 0.08, CB: 0.04, FB: 0.12, DM: 0.12, CM: 0.28, AM: 0.2, W: 0.16, ST: 0.1 };

  /** Follow-rate multipliers — lower = smoother, less twitchy pins. */
  const MOTION_EASE = { GK: 0.42, CB: 0.48, FB: 0.55, DM: 0.5, CM: 0.58, AM: 0.58, W: 0.6, ST: 0.58 };
  /**
   * Max pitch-% travel per sim-second (dt already includes playback speed).
   * Targets (tx/ty) may jump on state changes; left/top and rx/ry never may
   * (except kickoff / goal / HT / reset snaps).
   */
  const RUN_SPEED_PCT = { GK: 16, CB: 26, FB: 34, DM: 28, CM: 32, AM: 34, W: 38, ST: 36 };
  /**
   * Render↔logic desync debug (red logical dots).
   * Off by default; force on with ?debugPos=1 in the page URL.
   */
  const DEBUG_POS_SYNC = false;
  /**
   * Live Presentation Director threat-score debug overlay. Off by default;
   * force on with ?debugThreat=1 in the page URL. Phase 1 (see
   * computeLiveThreat below): parallel/experimental, FM Mobile broadcast
   * mode only, purely observational -- does not drive any real
   * presentation decision yet.
   */
  const DEBUG_THREAT = false;
  /**
   * Decision layer cadence (wall-seconds at 1×). Shape targets refresh here —
   * animation never invents new targets mid-frame.
   */
  const DECISION_INTERVAL_MIN = 0.22;
  const DECISION_INTERVAL_MAX = 0.48;
  /** Small home-side push in knockout fixtures only (chance creation,
   * finishing, defending, shot quality) — see isKnockout in createBoard.
   * Mirrors the Monte-Carlo engine's own (1 + home_adv) multiplicative
   * pattern; that engine's home_advantage stays at 0 by design, this is
   * live-engine-only. */
  const KNOCKOUT_HOME_PUSH = 0.025;
  /** @deprecated alias — shape retargets with the decision tick */
  const SHAPE_RETARGET_EVERY = 0.28;

  const ROLE_GENERIC = {
    GK: { dribbles90: 0.1, dribble_pct: 40, key_passes90: 0.2, xa90: 0.02, xg90: 0.01, shots90: 0.05, tackles90: 0.2, interceptions90: 0.3, pass_pct: 70 },
    CB: { dribbles90: 0.3, dribble_pct: 55, key_passes90: 0.3, xa90: 0.03, xg90: 0.04, shots90: 0.4, tackles90: 1.8, interceptions90: 1.6, pass_pct: 84 },
    FB: { dribbles90: 1.0, dribble_pct: 58, key_passes90: 0.9, xa90: 0.12, xg90: 0.05, shots90: 0.5, tackles90: 1.6, interceptions90: 1.2, pass_pct: 80 },
    DM: { dribbles90: 0.6, dribble_pct: 60, key_passes90: 0.8, xa90: 0.08, xg90: 0.06, shots90: 0.7, tackles90: 2.2, interceptions90: 1.8, pass_pct: 86 },
    CM: { dribbles90: 0.9, dribble_pct: 62, key_passes90: 1.4, xa90: 0.14, xg90: 0.1, shots90: 1.2, tackles90: 1.5, interceptions90: 1.1, pass_pct: 85 },
    AM: { dribbles90: 1.5, dribble_pct: 58, key_passes90: 2.0, xa90: 0.25, xg90: 0.22, shots90: 2.2, tackles90: 0.9, interceptions90: 0.5, pass_pct: 82 },
    W: { dribbles90: 2.2, dribble_pct: 52, key_passes90: 1.6, xa90: 0.22, xg90: 0.25, shots90: 2.4, tackles90: 0.8, interceptions90: 0.4, pass_pct: 78 },
    ST: { dribbles90: 1.1, dribble_pct: 48, key_passes90: 0.9, xa90: 0.12, xg90: 0.45, shots90: 3.2, tackles90: 0.5, interceptions90: 0.2, pass_pct: 74 },
  };

  function initials(name) {
    const parts = String(name || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    if (!parts.length) return "?";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  function shortName(name) {
    const parts = String(name || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    if (!parts.length) return "Player";
    return parts[parts.length - 1];
  }

  function mulberry32(seed) {
    let t = seed >>> 0;
    return function () {
      t += 0x6d2b79f5;
      let r = Math.imul(t ^ (t >>> 15), 1 | t);
      r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
      return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
    };
  }

  function hashSeed(str) {
    let h = 2166136261;
    const s = String(str || "");
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }

  function layoutFor(formation) {
    const base = FORMATION_LAYOUTS[formation] || DEFAULT_LAYOUT;
    const out = {};
    for (const [slot, coord] of Object.entries(base)) {
      const x = Number(coord[0]);
      const d = Number(coord[1]);
      // Spread laterally so pins use more of the pitch width (less cramped).
      const sx = 0.5 + (x - 0.5) * 1.22;
      out[slot] = [clamp(sx, 0.06, 0.94), d];
    }
    return out;
  }

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  function lerp(a, b, u) {
    return a + (b - a) * u;
  }

  function easeOutCubic(t) {
    const u = clamp(t, 0, 1);
    return 1 - Math.pow(1 - u, 3);
  }

  function smoothDamp(current, target, rate) {
    return lerp(current, target, easeOutCubic(clamp(rate, 0, 1)));
  }

  /** Ease toward target but never travel more than maxStep in one frame. */
  function stepTowardClamped(curL, curT, wantL, wantT, rate, maxStep) {
    let nextL = smoothDamp(curL, wantL, rate);
    let nextT = smoothDamp(curT, wantT, rate);
    const dx = nextL - curL;
    const dy = nextT - curT;
    const step = Math.hypot(dx, dy);
    if (step > maxStep && step > 1e-9) {
      const s = maxStep / step;
      nextL = curL + dx * s;
      nextT = curT + dy * s;
    }
    return { left: nextL, top: nextT };
  }

  function pinRunSpeedPct(pin) {
    const base = RUN_SPEED_PCT[pin.role] ?? 30;
    if (pin._running) return base * 1.22;
    if (pin._pressing) return base * 1.1;
    return base * 0.72;
  }

  function easeInOut(u) {
    return u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;
  }

  function dist(a, b) {
    const dx = (a.left ?? a.x) - (b.left ?? b.x);
    const dy = (a.top ?? a.y) - (b.top ?? b.y);
    return Math.hypot(dx, dy);
  }

  function roleOf(slot) {
    const s = String(slot || "").toUpperCase();
    if (s === "GK") return "GK";
    if (/^CB/.test(s)) return "CB";
    if (/^(RB|LB|RWB|LWB)$/.test(s)) return "FB";
    if (/^DM/.test(s)) return "DM";
    if (/^(AM|CAM)/.test(s)) return "AM";
    if (/^(RW|LW|RM|LM)$/.test(s)) return "W";
    if (/^(ST|CF|FW)/.test(s)) return "ST";
    if (/^CM/.test(s) || s === "CM") return "CM";
    return "CM";
  }

  function isThreeBackFormation(formation) {
    return /^3[- ]/.test(String(formation || "").trim());
  }

  /** Formations whose midfield must screen centrally when defending (not chase flanks). */
  function wantsCentralDefMidCover(formation) {
    const f = String(formation || "").trim();
    return (
      /^3-4-3/.test(f) ||
      /^3-4-2-1/.test(f) ||
      f === "4-2-3-1" ||
      f === "4-3-2-1" ||
      f === "4-2-2-2" ||
      /^3-4-1-2/.test(f) ||
      /^4-3-3/.test(f) ||
      /^4-3-1-2/.test(f)
    );
  }

  /**
   * Full-pitch mapping: depth 0 = own goal line, depth 1 = opposition goal.
   * Home attacks up (decreasing top%); away attacks down.
   */
  /** Push lateral coords outward so XIs use more pitch width (less cramped). */
  function stretchLaneX(x) {
    return clamp(0.5 + (x - 0.5) * 1.18, 0.05, 0.95);
  }

  function toPitchPct(side, x, depth) {
    const xx = clamp(stretchLaneX(x), 0.04, 0.96);
    const dd = clamp(depth, 0.02, 0.98);
    if (side === "home") {
      return { left: xx * 100, top: 100 - (4 + dd * 92) };
    }
    return { left: (1 - xx) * 100, top: 4 + dd * 92 };
  }

  function fromPitchPct(side, left, top) {
    if (side === "home") {
      return { x: left / 100, depth: (100 - top - 4) / 92 };
    }
    return { x: 1 - left / 100, depth: (top - 4) / 92 };
  }

  /**
   * Pure render-space transpose: every gameplay coordinate (pin.left/top,
   * pin.rx/ry, ball.left/top) stays in the original vertical-pitch logical
   * space untouched — toPitchPct/fromPitchPct, offside lines, box geometry,
   * everything upstream is unaffected. Only DOM writes/reads go through
   * this, so the pitch renders landscape (home defends/attacks left→right,
   * away right→left) without touching any engine math.
   */
  function toRenderXY(left, top) {
    return { left: 100 - top, top: left };
  }
  function fromRenderXY(renderLeft, renderTop) {
    return { left: renderTop, top: 100 - renderLeft };
  }

  function num(v, fallback) {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }

  /** Like num, but treat literal 0 as missing (sparse FBref primes ship 0 for %). */
  function numPos(v, fallback) {
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? n : fallback;
  }

  function mergeStats(slot, raw) {
    const role = roleOf(slot);
    const g = ROLE_GENERIC[role] || ROLE_GENERIC.CM;
    const s = raw || {};
    const shots =
      numPos(s.shots90, 0) ||
      numPos(s.understat_shots90, 0) ||
      (numPos(s.shots_on_target90, 0) ? numPos(s.shots_on_target90, 0) / 0.42 : 0) ||
      g.shots90;
    // Fix (set-piece Phase 3 follow-up) -- true only when the RAW input
    // actually carried a real shot-volume signal, before any
    // ROLE_GENERIC/ratio fallback was applied. fkTechniqueProxy uses this
    // to keep missing data from reading as elite shooting accuracy: the
    // shots_on_target90 fallback below (Math.max(0.4, shots*0.4)) always
    // produces a ratio near 1.0 against a small fallback shots90, which is
    // a data-availability artifact, not a real signal, if nothing else in
    // this function consulted it for that purpose.
    const hasShotData = Boolean(numPos(s.shots90, 0) || numPos(s.understat_shots90, 0) || numPos(s.shots_on_target90, 0));
    return {
      hasShotData,
      dribbles90: num(s.dribbles90, g.dribbles90),
      // 0% completion is never real match data — fall back to role norms
      dribble_pct: numPos(s.dribble_pct, g.dribble_pct),
      key_passes90: num(s.key_passes90, g.key_passes90),
      xa90: num(s.xa90, g.xa90),
      xg90: numPos(s.xg90 ?? s.npxg90, g.xg90),
      // Distinct from xg90 above (which folds npxg90 in only as a missing-
      // data fallback) -- kept separate so open-play decisions can use a
      // penalty-free threat number. See openPlayXg().
      npxg90: numPos(s.npxg90 ?? s.xg90, g.xg90),
      shots90: shots,
      shots_on_target90: num(s.shots_on_target90, Math.max(0.4, shots * 0.4)),
      goals90: num(s.goals90, 0),
      aerials_won90: num(s.aerials_won90, 0),
      aerials_won_pct: numPos(s.aerials_won_pct, role === "ST" ? 48 : 45),
      tackles90: num(s.tackles90, g.tackles90),
      interceptions90: num(s.interceptions90, g.interceptions90),
      pass_pct: numPos(s.pass_pct, g.pass_pct),
      // Wired in from the previously-unused stat fields (see memory: the
      // wire-in-22-stats project). Flat, role-agnostic fallbacks — these are
      // secondary/nudge signals in every mechanic that reads them, not
      // primary drivers, so unlike the 13 fields above they don't warrant
      // per-role tuning in ROLE_GENERIC.
      assists90: num(s.assists90, 0),
      clearances90: num(s.clearances90, 0),
      blocks90: num(s.blocks90, 0),
      ball_recoveries90: num(s.ball_recoveries90, 0),
      duels_won_pct: numPos(s.duels_won_pct, 50),
      long_balls90: num(s.long_balls90, 0),
      long_ball_pct: numPos(s.long_ball_pct, 55),
      big_chances_created90: num(s.big_chances_created90, 0),
      big_chances_missed90: num(s.big_chances_missed90, 0),
      possession_lost90: num(s.possession_lost90, 7),
      penalty_goals90: num(s.penalty_goals90, 0),
      xg_chain90: num(s.xg_chain90, 0),
      xg_buildup90: num(s.xg_buildup90, 0),
      saves90: num(s.saves90, role === "GK" ? 2.5 : 0),
      goals_prevented90: num(s.goals_prevented90, 0),
      goals_conceded90: num(s.goals_conceded90, 0),
      clean_sheet_pct: numPos(s.clean_sheet_pct, role === "GK" ? 30 : 0),
      yellow_cards90: num(s.yellow_cards90, 0),
      red_cards90: num(s.red_cards90, 0),
      // 0 deliberately means "no rating data" (see isMaestroPin-adjacent
      // Batch F usage) -- excluded from averages downstream, not treated as
      // a real bottom-of-the-scale rating.
      rating: num(s.rating, 0),
      // Percentiles are computed server-side (web/tournament.py) against the
      // full match player pool -- 0 is a legitimate rank (the single worst
      // player), so num() not numPos() here; 0.5 fallback = "no signal,
      // treat as average" when the server couldn't rank this player.
      rating_percentile: num(s.rating_percentile, 0.5),
      goals_conceded_percentile: num(s.goals_conceded_percentile, 0.5),
      goals90_percentile: num(s.goals90_percentile, 0.5),
    };
  }

  function buildPins(team, side) {
    const layout = layoutFor(team.formation);
    let lineup = (team.lineup || []).slice();
    if (!lineup.length) {
      lineup = Object.keys(layout).map((slot) => ({ slot, player: slot }));
    } else if (lineup.length < 11) {
      const used = new Set(lineup.map((p) => p.slot));
      const extras = Object.keys(layout)
        .filter((slot) => !used.has(slot))
        .slice(0, 11 - lineup.length)
        .map((slot) => ({ slot, player: slot }));
      lineup = lineup.concat(extras);
    }
    return lineup.map((p, i) => {
      const slot = p.slot || `P${i}`;
      const roleKey = (p.role_filter || "").trim() || slot;
      const coord = layout[slot] || [0.5, 0.15 + (i % 10) * 0.08];
      const pct = toPitchPct(side, coord[0], coord[1]);
      const stats = mergeStats(roleKey, p.stats || p);
      const role = roleOf(roleKey);
      return {
        id: `${side}-${slot}`,
        side,
        slot,
        roleFilter: (p.role_filter || "").trim().toUpperCase() || "",
        role,
        player: p.player || slot,
        short: shortName(p.player || slot),
        label: initials(p.player || slot),
        baseX: coord[0],
        baseDepth: coord[1],
        x: coord[0],
        depth: coord[1],
        left: pct.left,
        top: pct.top,
        /** Engine targets — may jump on shape/state changes. */
        tx: pct.left,
        ty: pct.top,
        /** Rendered sprite — trails logical; never leads toward tx/ty. */
        rx: pct.left,
        ry: pct.top,
        stats,
        hasBall: false,
        lockUntil: 0,
        favorUntil: 0,
        _running: false,
        _pressing: false,
        _pathCtrl: null,
        _runPhase: 0,
      };
    });
  }

  function scheduleGoals(homeGoals, awayGoals, rng) {
    const events = [];
    for (let i = 0; i < homeGoals; i++) events.push({ side: "home", minute: 0 });
    for (let i = 0; i < awayGoals; i++) events.push({ side: "away", minute: 0 });
    if (!events.length) return events;

    const slots = [];
    const n = events.length;
    for (let i = 0; i < n; i++) {
      const band = 8 + (80 / Math.max(1, n)) * (i + 0.35 + rng() * 0.5);
      slots.push(clamp(Math.round(band + (rng() - 0.5) * 6), 8, 88));
    }
    slots.sort((a, b) => a - b);
    for (let i = 1; i < slots.length; i++) {
      if (slots[i] - slots[i - 1] < 5) slots[i] = Math.min(88, slots[i - 1] + 5 + Math.floor(rng() * 3));
    }
    for (let i = events.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      const tmp = events[i];
      events[i] = events[j];
      events[j] = tmp;
    }
    return events.map((e, i) => ({ side: e.side, minute: slots[i], scored: false }));
  }

  function teamAttackPower(pins) {
    const attackers = pins.filter((p) => p.role === "ST" || p.role === "W" || p.role === "AM" || p.role === "CM");
    if (!attackers.length) return 0.45;
    const avg =
      attackers.reduce(
        (s, p) =>
          s +
          p.stats.xg90 * 1.35 +
          p.stats.xa90 * 1.1 +
          p.stats.key_passes90 * 0.18 +
          p.stats.dribbles90 * 0.1 +
          p.stats.shots90 * 0.04,
        0
      ) / attackers.length;
    return clamp(avg / 2.0, 0.15, 0.98);
  }

  function teamDefendPower(pins) {
    const defs = pins.filter((p) => p.role === "CB" || p.role === "DM" || p.role === "FB" || p.role === "GK");
    if (!defs.length) return 0.45;
    const avg =
      defs.reduce((s, p) => s + p.stats.tackles90 * 0.4 + p.stats.interceptions90 * 0.35 + (p.role === "GK" ? 0.8 : 0), 0) /
      defs.length;
    return clamp(avg / 2.1, 0.15, 0.98);
  }

  /** Midfield control / pass quality — how long a team can keep a spell. */
  function teamPossessionQuality(pins) {
    const pool = pins.filter((p) => p.role === "DM" || p.role === "CM" || p.role === "AM" || p.role === "CB" || p.role === "FB");
    if (!pool.length) return 0.5;
    const avg =
      pool.reduce((s, p) => s + p.stats.pass_pct * 0.009 + p.stats.key_passes90 * 0.06 + p.stats.dribble_pct * 0.002, 0) /
      pool.length;
    return clamp(avg / 1.15, 0.22, 0.92);
  }

  /** Chance creation — key passes / xA driven. Floor keeps underdogs creating. */
  function teamCreationPower(pins) {
    const creators = pins.filter((p) => p.role === "AM" || p.role === "CM" || p.role === "W" || p.role === "ST" || p.role === "FB");
    if (!creators.length) return 0.52;
    const avg =
      creators.reduce((s, p) => s + p.stats.key_passes90 * 0.28 + p.stats.xa90 * 2.2 + p.stats.xg90 * 0.15, 0) / creators.length;
    return clamp(avg / 1.5, 0.38, 0.95);
  }

  /** Pull unit ratings toward the mean so underdogs stay competitive. */
  function softRating(v, toward = 0.5, amount = 0.42) {
    return lerp(v, toward, amount);
  }

  /**
   * Map raw team composites onto comparable 0–1 bands.
   * pressing_intensity typically ~0.35–0.58; press_resistance ~0.07–0.22 —
   * treating them as the same 0–1 scale made press always dominate.
   */
  function rescaleBand(v, lo, hi) {
    return clamp((v - lo) / Math.max(1e-6, hi - lo), 0, 1);
  }
  function normPressIntensity(raw) {
    return softRating(rescaleBand(raw, 0.34, 0.58), 0.5, 0.2);
  }
  function normPressResistance(raw) {
    return softRating(rescaleBand(raw, 0.05, 0.24), 0.5, 0.2);
  }

  /** Quadratic bezier — start a, control ctrl, end b (curved runs, not straight lerps). */
  function bezier2(a, ctrl, b, u) {
    const t = clamp(u, 0, 1);
    const omt = 1 - t;
    return omt * omt * a + 2 * omt * t * ctrl + t * t * b;
  }

  function createBoard(container, opts) {
    const homeTeam = opts.home || { name: "Home", formation: "4-3-3 flat", lineup: [] };
    const awayTeam = opts.away || { name: "Away", formation: "4-3-3 flat", lineup: [] };
    const homePins = buildPins(homeTeam, "home");
    const awayPins = buildPins(awayTeam, "away");
    const allPins = [...homePins, ...awayPins];
    const pinById = new Map(allPins.map((p) => [p.id, p]));
    // Mid-match substitutions pull from here — mutated in place by
    // substitutePlayer (outgoing player goes back on, incoming comes off).
    const benchBySide = {
      home: (homeTeam.bench || []).map((b) => ({ player: b.player, stats: b.stats || {} })),
      away: (awayTeam.bench || []).map((b) => ({ player: b.player, stats: b.stats || {} })),
    };

    const live = Boolean(opts.live ?? opts.organicGoals ?? opts.mode === "live");
    const viewerMode = Boolean(opts.viewerMode);
    const hostMode = Boolean(opts.hostMode) && !viewerMode;
    const hideControls = Boolean(opts.hideControls) || viewerMode;
    // A participating team's own browser is still just a passive viewer
    // (frames only, never runs the sim) — but unlike a spectator, it gets
    // the subs/formation panel for its OWN side, submitting requests via
    // onAction instead of mutating pins directly (see substitutePlayer/
    // changeFormation call sites below).
    const participantSide =
      !hostMode && (opts.participantSide === "home" || opts.participantSide === "away")
        ? opts.participantSide
        : null;
    const requestAction = typeof opts.onAction === "function" ? opts.onAction : null;
    /** Knockout ties: level after 90 → ET (2×15) → pens if still level. Group matches ignore this. */
    const isKnockout = Boolean(opts.isKnockout || opts.knockout) && live && !viewerMode;
    // Final: still a knockout tie (ET/pens rules apply the same), but
    // conventionally a neutral-venue match — excluded from KNOCKOUT_HOME_PUSH
    // specifically (see the four isKnockout && !isFinalRound sites below).
    const isFinalRound = Boolean(opts.isFinal);
    // Two-legged tie context (leg 2 only — see prepare_board_match in
    // tournament.py): { leg, twoLegged, enteringAggHome, enteringAggAway }.
    // Leg 1 of a two-legged tie gets { leg: 1, twoLegged: true } with no
    // entering-aggregate fields (it never resolves/requires a winner off
    // its own scoreline). A single-legged tie (the Final, or a legacy
    // single_elim tournament) gets no aggContext at all — today's exact
    // plain FT/AET/pens behavior, unchanged.
    const aggContext = isKnockout && opts.aggContext ? opts.aggContext : null;
    const isTwoLegLeg1 = Boolean(aggContext && aggContext.twoLegged && aggContext.leg === 1);
    const isTwoLegLeg2 = Boolean(aggContext && aggContext.twoLegged && aggContext.leg === 2);
    const onBroadcast = typeof opts.onBroadcast === "function" ? opts.onBroadcast : null;
    const broadcastEvery = Math.max(80, Number(opts.broadcastIntervalMs) || 220);
    let lastBroadcastAt = 0;
    const replayScore =
      !live &&
      (opts.homeGoals != null || opts.awayGoals != null) &&
      (Number(opts.homeGoals) > 0 || Number(opts.awayGoals) > 0 || opts.forceReplayScore);
    const homeGoalsTarget = Math.max(0, Math.round(Number(opts.homeGoals) || 0));
    const awayGoalsTarget = Math.max(0, Math.round(Number(opts.awayGoals) || 0));
    const seed =
      opts.seed ||
      hashSeed(`${homeTeam.name}-${awayTeam.name}-${live ? "live" : `${homeGoalsTarget}-${awayGoalsTarget}`}`);
    const rng = mulberry32(seed);

    const unitHome = opts.unitHome || {};
    const unitAway = opts.unitAway || {};
    function unit01(v, fallback = 0.55) {
      const n = Number(v);
      if (!Number.isFinite(n)) return fallback;
      // Accept 0–1 composites or legacy 0–100 UI scores
      return n > 1.5 ? clamp(n / 100, 0, 1) : clamp(n, 0, 1);
    }
    const pressHome = normPressIntensity(unit01(unitHome.pressing_intensity, 0.48));
    const pressAway = normPressIntensity(unit01(unitAway.pressing_intensity, 0.48));
    const resistHome = normPressResistance(unit01(unitHome.press_resistance, 0.14));
    const resistAway = normPressResistance(unit01(unitAway.press_resistance, 0.14));
    const unitAtkHome = softRating(
      unit01(unitHome.attacking_effectiveness ?? unitHome.finishing_threat ?? unitHome.attack, teamAttackPower(homePins))
    );
    const unitAtkAway = softRating(
      unit01(unitAway.attacking_effectiveness ?? unitAway.finishing_threat ?? unitAway.attack, teamAttackPower(awayPins))
    );
    const unitDefHome = softRating(
      unit01(unitHome.defensive_unit ?? unitHome.xga_suppression ?? unitHome.defence ?? unitHome.defense, teamDefendPower(homePins))
    );
    const unitDefAway = softRating(
      unit01(unitAway.defensive_unit ?? unitAway.xga_suppression ?? unitAway.defence ?? unitAway.defense, teamDefendPower(awayPins))
    );
    const unitCreateHome = softRating(
      unit01(unitHome.chance_creation ?? unitHome.creation ?? unitHome.attacking_effectiveness, teamCreationPower(homePins)),
      0.5,
      0.52
    );
    const unitCreateAway = softRating(
      unit01(unitAway.chance_creation ?? unitAway.creation ?? unitAway.attacking_effectiveness, teamCreationPower(awayPins)),
      0.5,
      0.52
    );

    const unitPossHome = softRating(
      unit01(unitHome.possession_control, teamPossessionQuality(homePins))
    );
    const unitPossAway = softRating(
      unit01(unitAway.possession_control, teamPossessionQuality(awayPins))
    );
    const midDefHome = softRating(
      unit01(
        unitHome.midfield_defence ??
          (unitHome.units && unitHome.units.midfield_defence) ??
          unitHome.midfield,
        0.45
      ),
      0.5,
      0.4
    );
    const midDefAway = softRating(
      unit01(
        unitAway.midfield_defence ??
          (unitAway.units && unitAway.units.midfield_defence) ??
          unitAway.midfield,
        0.45
      ),
      0.5,
      0.4
    );

    // Softer blends — player + unit, compressed so favorites win more often but don't steamroll
    const attackHome = clamp(teamAttackPower(homePins) * 0.55 + unitAtkHome * 0.45, 0.25, 0.82);
    const attackAway = clamp(teamAttackPower(awayPins) * 0.55 + unitAtkAway * 0.45, 0.25, 0.82);
    // +6% flat buff — attacking was overpowering defence across the board
    // (chance creation, dribbles/carries, shot conversion all read off this),
    // so raise the one number that feeds every defensive term at once.
    const defendHome = clamp((teamDefendPower(homePins) * 0.55 + unitDefHome * 0.4 + pressHome * 0.08) * 1.06, 0.25, 0.87);
    const defendAway = clamp((teamDefendPower(awayPins) * 0.55 + unitDefAway * 0.4 + pressAway * 0.08) * 1.06, 0.25, 0.87);
    // Create floor: weak sides still manufacture chances vs strong defences
    const createHome = clamp(teamCreationPower(homePins) * 0.55 + unitCreateHome * 0.45, 0.42, 0.9);
    const createAway = clamp(teamCreationPower(awayPins) * 0.55 + unitCreateAway * 0.45, 0.42, 0.9);
    // Possession control: pin pass quality + press resist + team possession_control composite
    const possHome = clamp(
      teamPossessionQuality(homePins) * 0.4 + resistHome * 0.25 + unitPossHome * 0.35,
      0.25,
      0.85
    );
    const possAway = clamp(
      teamPossessionQuality(awayPins) * 0.4 + resistAway * 0.25 + unitPossAway * 0.35,
      0.25,
      0.85
    );
    const aerialHome = softRating(unit01(unitHome.aerial_defence, 0.45), 0.45, 0.5);
    const aerialAway = softRating(unit01(unitAway.aerial_defence, 0.45), 0.45, 0.5);
    // Raw finishing unit (0–1); drives day-form mixture, not soft-compressed attack
    const unitFinHome = unit01(unitHome.finishing ?? unitHome.finishing_threat, 0.55);
    const unitFinAway = unit01(unitAway.finishing ?? unitAway.finishing_threat, 0.55);
    // Individual goalkeeper quality (backend's confidence-weighted per-keeper rating).
    // Fallback 0.4 matches team_ratings.py's LEAGUE_GK_RATING baseline.
    const gkHome = unit01(unitHome.goalkeeper, 0.4);
    const gkAway = unit01(unitAway.goalkeeper, 0.4);

    // Engine fix — expected-xG target per side, used by xgPaceMul (near
    // spellChanceP) to anchor total chance volume against what squad quality
    // actually predicts for a full 90 minutes. opts.xgHome/xgAway usually
    // aren't set (every match is played live on the board, not predicted),
    // so this falls back to approximating the same figure from unit ratings
    // that are present on every live match regardless of flow — mirrors
    // team_ratings.py's combined_attack_xg / defence_suppression /
    // midfield_battle_multiplier (the dominant terms in the real formula)
    // closely enough to serve as a pacing anchor; deliberately skips the
    // smaller terms (press_xg_suppression, trophy/silverware multiplier)
    // since this only needs to be a reasonable target, not a bit-for-bit
    // replica of the separate Python engine.
    const unitMidHome = unit01(unitHome.midfield, 0.5);
    const unitMidAway = unit01(unitAway.midfield, 0.5);
    const transitionRiskHome = unit01(unitHome.transition_risk, 0.3);
    const transitionRiskAway = unit01(unitAway.transition_risk, 0.3);
    function approxXgTarget(finishing, chanceCreation, oppDefence, oppMidDef, oppGk, oppTransRisk, ownMid, oppMid) {
      const atkXg = Math.max(0.35, 2.05 * (0.42 + 0.88 * finishing));
      const createXg = Math.max(0, 2.05 * 0.36 * chanceCreation * 0.5);
      const effGk = 0.4 + 0.55 * (oppGk - 0.4);
      let combined = 0.54 * oppDefence + 0.32 * oppMidDef + 0.14 * effGk;
      combined *= Math.max(0.68, 1 - oppTransRisk * 0.32);
      const suppression = 1 / (1 + combined * 0.95);
      const midDelta = clamp(ownMid - oppMid, -0.8, 0.8);
      return (atkXg + createXg) * suppression * (1 + 0.1 * midDelta);
    }
    const rawXgHome = Number(opts.xgHome);
    const rawXgAway = Number(opts.xgAway);
    const targetXgHome =
      Number.isFinite(rawXgHome) && rawXgHome > 0.05
        ? rawXgHome
        : approxXgTarget(unitFinHome, unitCreateHome, defendAway, midDefAway, gkAway, transitionRiskAway, unitMidHome, unitMidAway);
    const targetXgAway =
      Number.isFinite(rawXgAway) && rawXgAway > 0.05
        ? rawXgAway
        : approxXgTarget(unitFinAway, unitCreateAway, defendHome, midDefHome, gkHome, transitionRiskHome, unitMidAway, unitMidHome);

    function sideAttack(side) {
      return side === "home" ? attackHome : attackAway;
    }
    function sideDefend(side) {
      return side === "home" ? defendHome : defendAway;
    }
    function sideGoalkeeper(side) {
      return side === "home" ? gkHome : gkAway;
    }
    function sidePress(side) {
      return side === "home" ? pressHome : pressAway;
    }
    function sideResist(side) {
      return side === "home" ? resistHome : resistAway;
    }
    function sideCreate(side) {
      return side === "home" ? createHome : createAway;
    }
    function sidePoss(side) {
      return side === "home" ? possHome : possAway;
    }
    function sideMidDef(side) {
      return side === "home" ? midDefHome : midDefAway;
    }
    function sideAerial(side) {
      return side === "home" ? aerialHome : aerialAway;
    }
    function sideFinishing(side) {
      return side === "home" ? unitFinHome : unitFinAway;
    }

    const scheduled = replayScore ? scheduleGoals(homeGoalsTarget, awayGoalsTarget, rng) : [];
    const onComplete = typeof opts.onComplete === "function" ? opts.onComplete : null;
    const onScore = typeof opts.onScore === "function" ? opts.onScore : null;

    const mobileBroadcast = Boolean(opts.mobileBroadcast);
    container.innerHTML = `
      <div class="tactic-board${mobileBroadcast ? " tactic-board--mobile" : ""}" data-tactic-board>
        <div class="tactic-topbar">
          <span class="tactic-clock" data-tb-clock>0'</span>
          <div class="tactic-score-block">
            <span class="team-name home">${escHtml(homeTeam.name)}</span>
            <span class="tactic-score" data-tb-score>0 – 0</span>
            <span class="team-name away">${escHtml(awayTeam.name)}</span>
          </div>
          <div class="tactic-topbar-controls" ${hideControls ? "hidden" : ""}>
            <button type="button" class="btn-primary btn-sm" data-tb-play>Play</button>
            <button type="button" class="btn-ghost btn-sm" data-tb-pause>Pause</button>
          </div>
        </div>
        <div class="tactic-hud" data-tb-hud>
          <div class="tactic-hud-cell" title="Possession">
            <span class="tactic-hud-label">Possession</span>
            <span class="tactic-hud-value"><span data-tb-poss-h>50</span>% – <span data-tb-poss-a>50</span>%</span>
          </div>
          <div class="tactic-hud-cell" title="Expected goals">
            <span class="tactic-hud-label">xG</span>
            <span class="tactic-hud-value"><span data-tb-xg-h>0.00</span> – <span data-tb-xg-a>0.00</span></span>
          </div>
        </div>
        <div class="tactic-mobile-info" data-tb-mobile-info hidden>
          <div class="tactic-mobile-scorers" data-tb-mobile-scorers>
            <div class="ms-col home" data-tb-scorers-home></div>
            <div class="ms-col away" data-tb-scorers-away></div>
          </div>
          <div class="tactic-mobile-stats" data-tb-mobile-stats>
            <div class="mobile-stat-row"><span class="ms-val home" data-ms="poss-home">50%</span><span class="ms-label">Possession</span><span class="ms-val away" data-ms="poss-away">50%</span></div>
            <div class="mobile-stat-row"><span class="ms-val home" data-ms="bigchances-home">0</span><span class="ms-label">Clear-cut chances</span><span class="ms-val away" data-ms="bigchances-away">0</span></div>
            <div class="mobile-stat-row"><span class="ms-val home" data-ms="xg-home">0.00</span><span class="ms-label">xG</span><span class="ms-val away" data-ms="xg-away">0.00</span></div>
            <div class="mobile-stat-row"><span class="ms-val home" data-ms="shots-home">0</span><span class="ms-label">Shots</span><span class="ms-val away" data-ms="shots-away">0</span></div>
            <div class="mobile-stat-row"><span class="ms-val home" data-ms="sot-home">0</span><span class="ms-label">Shots on target</span><span class="ms-val away" data-ms="sot-away">0</span></div>
            <div class="mobile-stat-row"><span class="ms-val home" data-ms="fouls-home">0</span><span class="ms-label">Fouls</span><span class="ms-val away" data-ms="fouls-away">0</span></div>
            <div class="mobile-stat-row"><span class="ms-val home" data-ms="corners-home">0</span><span class="ms-label">Corners</span><span class="ms-val away" data-ms="corners-away">0</span></div>
          </div>
          <div class="tactic-mobile-zone" data-tb-mobile-zone>
            <div class="mz-track"><span class="mz-marker" data-mz-marker></span></div>
            <div class="mz-labels">
              <span class="mz-label-home">${escHtml(homeTeam.name)}</span>
              <span>Midfield</span>
              <span class="mz-label-away">${escHtml(awayTeam.name)}</span>
            </div>
          </div>
        </div>
        <div class="tactic-pitch-wrap" data-tb-pitch-wrap>
          <div class="tactic-pitch" data-tb-pitch>
            <div class="pitch-lines" aria-hidden="true">
              <div class="pitch-halfway"></div>
              <div class="pitch-circle"></div>
              <div class="pitch-box top"></div>
              <div class="pitch-box bottom"></div>
              <div class="pitch-goal top"></div>
              <div class="pitch-goal bottom"></div>
              <div class="pitch-spot center"></div>
            </div>
            <div class="tactic-ball" data-tb-ball></div>
            <div class="tactic-flash" data-tb-flash hidden></div>
            <div class="tactic-goalcard" data-tb-goalcard hidden>
              <span class="goalcard-badge" data-tb-goalcard-badge></span>
              <div class="goalcard-text">
                <span class="goalcard-name" data-tb-goalcard-name></span>
                <span class="goalcard-sub" data-tb-goalcard-sub></span>
              </div>
            </div>
          </div>
        </div>
        <div class="tactic-bottombar" data-tb-bottombar>
          <span class="tactic-ticker" data-tb-phase>Kick-off</span>
        </div>
        <aside class="tactic-commentary" aria-label="Match commentary">
          <div class="tactic-commentary-head">Commentary</div>
          <div class="tactic-commentary-list" data-tb-feed></div>
        </aside>
        <div class="tactic-overlay" data-tb-ht hidden>
          <div class="tactic-overlay-card" style="text-align:center;max-width:22rem">
            <h3 data-tb-ht-title>Half time</h3>
            <p class="tactic-ht-score" data-tb-ht-score style="font-size:1.8rem;font-weight:800;margin:0.35rem 0">0 – 0</p>
            <div class="ht-stats" data-tb-ht-stats-grid>
              <div><div class="ht-val" data-tb-ht-poss>—</div><div class="ht-lab">Possession</div></div>
              <div><div class="ht-val" data-tb-ht-xg>—</div><div class="ht-lab">xG</div></div>
              <div><div class="ht-val" data-tb-ht-score-lab>—</div><div class="ht-lab">Score</div></div>
            </div>
            <p class="muted" data-tb-ht-stats hidden></p>
            <p class="muted" data-tb-break-note hidden style="margin:0.35rem 0 0.75rem;font-size:0.85rem"></p>
            <ul class="tactic-pens-list" data-tb-pens-list hidden></ul>
            <button type="button" class="btn-primary" data-tb-ht-resume>Resume 2nd half</button>
          </div>
        </div>
        <div class="tactic-overlay" data-tb-prematch hidden>
          <div class="tactic-overlay-card" data-tb-prematch-body></div>
        </div>
        <div class="tactic-controls" ${hideControls ? "hidden" : ""}>
          <button type="button" class="btn-ghost btn-sm" data-tb-replay>Replay</button>
        </div>
        <div class="tactic-instructions" data-tb-instructions ${hideControls ? "hidden" : ""}>
          <span class="muted" style="font-size:0.78rem">Instructions</span>
          <button type="button" class="btn-ghost btn-sm" data-tb-push="home">Home push</button>
          <button type="button" class="btn-ghost btn-sm" data-tb-sit="home">Home sit</button>
          <button type="button" class="btn-ghost btn-sm" data-tb-push="away">Away push</button>
          <button type="button" class="btn-ghost btn-sm" data-tb-sit="away">Away sit</button>
        </div>
        <div class="tactic-subs" data-tb-subs ${hostMode || participantSide ? "" : "hidden"}></div>
        <p class="muted tactic-note" data-tb-note>
          ${
            viewerMode
              ? "Live Matchday broadcast — shared pin board from the admin host. Hard-refresh if the board looks stale."
              : live
                ? "Decide → animate loop (FM-style). Goals here are official. Click a pin to favor; push/sit for shape. Hard-refresh (Ctrl+F5) after updates."
                : replayScore
                  ? "Replay of the saved pin-board scoreline. Hard-refresh if pins look stale."
                  : "Pin match — score emerges from possession spells. Click a pin to favor; push/sit biases shape."
          }
        </p>
      </div>`;

    const pitch = container.querySelector("[data-tb-pitch]");
    const ballEl = container.querySelector("[data-tb-ball]");
    const scoreEl = container.querySelector("[data-tb-score]");
    const clockEl = container.querySelector("[data-tb-clock]");
    const phaseEl = container.querySelector("[data-tb-phase]");
    const flashEl = container.querySelector("[data-tb-flash]");
    const goalCardEl = container.querySelector("[data-tb-goalcard]");
    const goalCardBadgeEl = container.querySelector("[data-tb-goalcard-badge]");
    const goalCardNameEl = container.querySelector("[data-tb-goalcard-name]");
    const goalCardSubEl = container.querySelector("[data-tb-goalcard-sub]");
    const feedEl = container.querySelector("[data-tb-feed]");
    const pitchWrapEl = container.querySelector("[data-tb-pitch-wrap]");
    const mobileInfoEl = container.querySelector("[data-tb-mobile-info]");
    const mobileStatsEl = container.querySelector("[data-tb-mobile-stats]");
    const mobileZoneEl = container.querySelector("[data-tb-mobile-zone]");
    const mobileZoneMarkerEl = container.querySelector("[data-mz-marker]");
    const mobileScorersEl = container.querySelector("[data-tb-mobile-scorers]");
    const bottombarEl = container.querySelector("[data-tb-bottombar]");
    const mobileScorersHomeEl = container.querySelector("[data-tb-scorers-home]");
    const mobileScorersAwayEl = container.querySelector("[data-tb-scorers-away]");
    if (mobileBroadcast) {
      if (mobileInfoEl) mobileInfoEl.hidden = false;
    }
    const possHEl = container.querySelector("[data-tb-poss-h]");
    const possAEl = container.querySelector("[data-tb-poss-a]");
    const xgHEl = container.querySelector("[data-tb-xg-h]");
    const xgAEl = container.querySelector("[data-tb-xg-a]");
    const htOverlay = container.querySelector("[data-tb-ht]");
    const htScoreEl = container.querySelector("[data-tb-ht-score]");
    const htStatsEl = container.querySelector("[data-tb-ht-stats]");
    const htPossEl = container.querySelector("[data-tb-ht-poss]");
    const htXgEl = container.querySelector("[data-tb-ht-xg]");
    const htScoreLabEl = container.querySelector("[data-tb-ht-score-lab]");
    const htResumeBtn = container.querySelector("[data-tb-ht-resume]");
    const htTitleEl = container.querySelector("[data-tb-ht-title]");
    const breakNoteEl = container.querySelector("[data-tb-break-note]");
    const pensListEl = container.querySelector("[data-tb-pens-list]");
    const htStatsGrid = container.querySelector("[data-tb-ht-stats-grid]");
    const prematchOverlay = container.querySelector("[data-tb-prematch]");
    const prematchBody = container.querySelector("[data-tb-prematch-body]");
    const showPrematch = Boolean(opts.showPrematch) && Boolean(live);

    const pinEls = new Map();
    const debugDotEls = new Map();
    const showPosSyncDebug =
      DEBUG_POS_SYNC ||
      (typeof global.location !== "undefined" &&
        /(?:\?|&)debugPos=1(?:&|$)/.test(String(global.location.search || "")));
    allPins.forEach((pin) => {
      if (pin.rx == null) pin.rx = pin.left;
      if (pin.ry == null) pin.ry = pin.top;
      const el = document.createElement("div");
      el.className = `tactic-pin ${pin.side} role-${pin.role}`;
      el.dataset.pinId = pin.id;
      el.title = `${pin.player} (${pin.slot}) — click to favor`;
      el.innerHTML = `<span class="pin-dot">${escHtml(pin.label)}</span>`;
      const rPos0 = toRenderXY(pin.rx, pin.ry);
      el.style.left = `${rPos0.left}%`;
      el.style.top = `${rPos0.top}%`;
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        if (viewerMode) return;
        favorPin(pin);
      });
      pitch.appendChild(el);
      pinEls.set(pin.id, el);
      if (showPosSyncDebug) {
        const dot = document.createElement("div");
        dot.className = "tactic-debug-logical";
        dot.title = `logical ${pin.short}`;
        dot.style.cssText =
          "position:absolute;width:7px;height:7px;border-radius:50%;background:#e53935;border:1px solid rgba(255,255,255,0.85);" +
          "transform:translate(-50%,-50%);z-index:6;pointer-events:none;box-shadow:0 0 0 1px rgba(0,0,0,0.35)";
        const rDbg0 = toRenderXY(pin.left, pin.top);
        dot.style.left = `${rDbg0.left}%`;
        dot.style.top = `${rDbg0.top}%`;
        pitch.appendChild(dot);
        debugDotEls.set(pin.id, dot);
      }
    });

    // Live Presentation Director debug overlay -- Phase 1, FM Mobile
    // broadcast mode only. A single breakdown panel (not per-pin dots),
    // meant as a real tuning tool the user watches during live matches,
    // not throwaway instrumentation to strip before commit.
    const showThreatDebug =
      mobileBroadcast &&
      (DEBUG_THREAT ||
        (typeof global.location !== "undefined" &&
          /(?:\?|&)debugThreat=1(?:&|$)/.test(String(global.location.search || ""))));
    if (showThreatDebug) {
      threatDebugEl = document.createElement("div");
      threatDebugEl.className = "tactic-debug-threat";
      threatDebugEl.style.cssText =
        "position:absolute;top:6px;left:6px;z-index:7;pointer-events:none;" +
        "background:rgba(10,12,16,0.82);color:#e8eaed;border:1px solid rgba(255,255,255,0.25);" +
        "border-radius:6px;padding:6px 8px;font:11px/1.4 ui-monospace,monospace;white-space:pre;min-width:150px";
      pitch.appendChild(threatDebugEl);
    }

    pitch.addEventListener("click", (ev) => {
      if (viewerMode || finished || !playing) return;
      const rect = pitch.getBoundingClientRect();
      const renderLeft = ((ev.clientX - rect.left) / rect.width) * 100;
      const renderTop = ((ev.clientY - rect.top) / rect.height) * 100;
      const logical = fromRenderXY(renderLeft, renderTop);
      triggerZoneSwitch(logical.left, logical.top);
    });

    let playing = false;
    // FM Mobile broadcast mode -- routine play/commentary flows fast by
    // default (viewer isn't watching player movement, just reading
    // commentary + the zone strip), dropping to MOBILE_EVENT_SPEED only
    // for the handful of key events that actually get the full pitch
    // shown. Standard (non-mobile) boards keep the existing 0.5 default.
    let speed = mobileBroadcast ? 2.5 : 0.5;
    const MOBILE_NORMAL_SPEED = 2.5;
    const MOBILE_EVENT_SPEED = 0.3;
    // How long (real ms) the full pitch stays up after a key event. This is
    // the dominant lever on live-view share -- calibrated so live/highlight
    // time lands around 20-25% of total watch time (user's explicit target),
    // measured across several seeds: 4200ms held live ~35-58%, too much;
    // 1200ms holds ~17-29%, averaging ~22%.
    const MOBILE_EVENT_MS = 1200;
    // Bug fix -- how close to a spell's estimated resolution (spell.end)
    // before the buildup view kicks in. Keeps the "show buildup before
    // the shot" behavior bounded to roughly the 2-3 match-minutes it was
    // meant to be, instead of the entire (up to 15-minute) spell.
    const MOBILE_BUILDUP_WINDOW = 3;
    let mobileEventUntilTs = 0;
    // FM Mobile broadcast mode -- true while the current spell is flagged
    // to attempt a chance (spell.willAttemptChance), so the slow full-pitch
    // view is already showing before any shot/goal fires, not just for the
    // MOBILE_EVENT_MS hold after. Cleared in archiveSpell (reverting to
    // fast mode if the spell never actually produced a key event) and on
    // reset.
    let mobileBuildupActive = false;
    let matchMinute = 0;
    let lastTs = 0;
    let raf = 0;
    let homeScore = 0;
    let awayScore = 0;
    let possession = "home";
    let phase = "BUILD_UP";
    let carrierId = null;
    let actionTimer = 0;
    let commentaryHold = 0;
    let finished = false;
    let kickoffDone = false;
    let completeFired = false;
    let lastGoalMinute = -20;
    let favoredId = null;
    let halfTimeShown = false;
    let halfTimePaused = false;
    /** Period break between FT→ET1, ET1→ET2, or pens intro (reuses HT overlay). */
    let breakPaused = false;
    /** "ht" | "et_intro" | "et_half" | "pens" */
    let breakKind = null;
    /** Regulation ends at 90; ET1 at 105; ET2 at 120. */
    let clockCap = 90;
    let ft90Home = null;
    let ft90Away = null;
    let decidedBy = "ft";
    let pensActive = false;
    let penScore = { home: 0, away: 0 };
    let penLog = [];
    let pensTimer = 0;
    let possSeconds = { home: 0, away: 0 };
    let liveXg = { home: 0, away: 0 };
    // Engine fix — how long (in match-minutes) a side stays "scrambling" after
    // triggerDefensiveBreachReactions fires against it. The reaction sets a
    // movement target (tx/ty) for the covering players, but their actual
    // on-pitch position (pin.left/top — what pressureAt/nearestOpponent
    // read) only catches up over several rendered frames. If the very next
    // action (often driveIntoBox, in the same match-minute) checks for a
    // nearby defender before that catch-up happens, it correctly finds
    // nobody close — the recovery never had time to matter. This window
    // lets the contest checks themselves acknowledge the defence is
    // actively scrambling even before its sprites have visually arrived.
    let breachRecoveryUntil = { home: 0, away: 0 };
    // Engine fix — a side that just scored had no reaction to it at all:
    // same attacking urgency and pattern mix the very next spell as if
    // nothing happened. Real teams manage the game for a few minutes after
    // taking a lead — consolidate possession, don't immediately commit
    // numbers forward again — instead of pushing straight back onto the
    // front foot. Set in markGoal; read by pickAttackPattern (favours
    // recycle) and spellChanceP (fewer forced chance attempts) for the
    // scoring side only.
    let leadProtectUntil = { home: 0, away: 0 };
    // Phase 3: Track defensive shape exposure when defenders step out of position
    // central: 0-1 scale of how exposed the central midfield zone is (DM/CM beaten)
    // wide: 0-1 scale of how exposed the wing zones are (FB beaten)
    // Decays over time as defenders reset shape
    let defensiveShapeExposure = { home: { central: 0, wide: 0 }, away: { central: 0, wide: 0 } };
    /**
     * Live Presentation Director (experimental, Phase 1) -- a parallel
     * threat-score system alongside willAttemptChance/isMobileKeyEvent, per
     * the user's own staged spec: build it observationally first (compute +
     * debug-display only, drive nothing real) before ever considering it as
     * a replacement for the existing highlight trigger. See
     * computeLiveThreat() near tickRender. Answers "how interesting is the
     * current situation becoming", not "how likely is a shot" -- shot
     * quality (shotAngleQuality) is only the single biggest of six inputs.
     */
    let threatScoreSmoothed = 0;
    let threatPrevDepth = 0.5;
    let threatMode = "TICKER"; // "TICKER" | "HIGHLIGHT" -- observational only, nothing reads this yet
    let lastThreatHighlightTs = 0; // performance.now() of the last TICKER->HIGHLIGHT flip
    let lastThreatResult = null; // { score, breakdown, mode } -- latest computeLiveThreat() output
    let threatDebugEl = null;
    /**
     * Per-team finishing form for this match (drawn once at reset/kickoff).
     * Multiplies shot conversion; does not invent goals without shots.
     * Mixture biased by unit finishing (avg ≈ cold 8% / hot 12% / normal 80%).
     */
    let finishingForm = { home: 1, away: 1 };
    // Engine fix — anti-drought for big chances specifically. organicWillScore's
    // conversion ceiling was purely a function of the shooter's own finishing
    // quality/form, with zero sensitivity to how many similar chances the same
    // side had just missed — a genuinely clinical finisher and a genuinely
    // clinical forward line could both go cold for several consecutive big
    // chances at the same fixed odds every time, which reads as unbelievable
    // ("nothing dropped for anyone all night") rather than one bad shot.
    // Tracks consecutive missed *big_chance* shots per player (reset when that
    // player scores) and per side (reset when that side scores); read by
    // organicWillScore to raise the odds on the next big chance, not to
    // guarantee one — see isClinicalFinisher/sideForwardLineClinical below.
    let sideBigMissStreak = { home: 0, away: 0 };
    let commentaryLines = [];

    let instrHome = 0;
    let instrAway = 0;
    let instrHomeUntil = 0;
    let instrAwayUntil = 0;

    let ball = { left: 50, top: 50 };
    let ballFrom = { left: 50, top: 50 };
    let ballTo = { left: 50, top: 50 };
    let ballCtrl = null;
    let ballTween = 1;
    let ballTweenDur = 0.45;
    let ballAttached = true;

    let flashTimer = 0;
    let goalCardTimer = 0;
    let shapePulse = 0;
    /** Smoothed 0–1 defensive box/chance pressure per side (gradual drop-back). */
    const defPressureSmooth = { home: 0, away: 0 };
    // Engine fix — Milestone 2: team elasticity. Smoothed per-side width
    // multiplier (around 1.0) applied to every pin's lateral distance from
    // the pitch centreline, and the attacking-stage/possession key it was
    // last computed against — see teamBlockLines.
    const teamWidthSmooth = { home: 1, away: 1 };
    const lastElasticityStage = { home: null, away: null };
    // Engine fix — Milestone 3: continuous per-side "sense of an incoming
    // counter" — EMA-smoothed, always updating, read by the ST/W depth bias
    // in updateTeamShape's pending-pin finalization (not a discrete trigger).
    const counterReadiness = { home: 0, away: 0 };
    /** Decision-layer cadence (sim-seconds). Shape retargets only here. */
    let decisionAcc = DECISION_INTERVAL_MAX;
    let nextDecisionIn = DECISION_INTERVAL_MIN + rng() * (DECISION_INTERVAL_MAX - DECISION_INTERVAL_MIN);
    /** Off-ball support runs: pinId → { x, depth, until } */
    let supportRuns = new Map();
    let supportRunRefresh = 0;

    /**
     * Pre-decided ball flight — outcomes locked before animation starts.
     * Resolved only when ballTween reaches 1 (never mid-tween).
     */
    let ballFlight = null;
    let pendingRestart = null;
    let pendingClear = null;
    let pendingKickoffCarrier = null;
    let pendingShot = null;
    /**
     * Set-piece Phase 0 — generic out-of-bounds state. { type: "throw_in"
     * | "corner" | "goal_kick", side, left, top, at }, drained by
     * flushDeferredRestarts exactly like pendingRestart/pendingClear/
     * pendingKickoffCarrier above. decideAction stands down entirely while
     * this is set (see its early-return guard) so normal action/pass/
     * dribble logic can't keep mutating ball/possession/player targets
     * underneath an in-progress restart -- there is exactly one owner of
     * that state at a time.
     */
    let pendingSetPiece = null;
    /** Side that last touched the ball — feeds corner-vs-goal-kick attribution. */
    let lastTouchSide = null;
    /** Set-piece Phase 0/1 instrumentation — see evaluateOutOfBounds/dispatchBallTarget. */
    let oobStats = {
      outOfBoundsEvents: 0,
      touchlineExits: 0,
      bylineExits: 0,
      cornersGenerated: 0,
      goalKicksGenerated: 0,
      throwInsGenerated: 0,
      falsePositiveOob: 0,
    };
    let freeKickUntil = 0; // Block dribbling during free kick situations
    /**
     * Set-piece Phase 3 — marks an in-flight cross as corner-originated so
     * the shared doPass flight-resolution code (used by every cross in the
     * match, not just corners) can run the second-ball contest ONLY for
     * this one flight, then discard it. Never read outside that gate, so
     * regular open-play crosses are completely unaffected.
     */
    let pendingCornerContext = null;
    /** Set-piece Phase 3 — corner instrumentation (see resolveCorner/resolveCornerSecondBall). */
    let cornerStats = {
      cornersWon: 0,
      delivery: { near: 0, far: 0, central: 0, edge: 0, short: 0 },
      firstContactsAttack: 0,
      firstContactsDefense: 0,
      clearances: 0,
      secondBalls: 0,
      cornerShots: 0,
    };
    /** Set-piece Phase 2 — free-kick instrumentation (see classifyFreeKickZone/resolve*FreeKick). */
    let fkStats = {
      directShots: 0,
      directCrosses: 0,
      wideCrosses: 0,
      midfieldRestarts: 0,
      indirectRestarts: 0,
    };
    /**
     * Diagnostic-only (Phase 3 follow-up) — short-corner gate visibility,
     * requested after the 20-match batch showed 0/63 short corners: total
     * corners -> had a receiver nearby -> weak taker / aerial disadvantage
     * present -> gate actually opened -> short corner actually selected.
     * `samples` keeps a rolling window of the raw per-corner numbers so the
     * gate thresholds (0.35 taker quality, -0.28 aerial edge) can be
     * evaluated against real distributions before anything is tuned.
     */
    let shortCornerDiag = {
      totalCorners: 0,
      hadCandidate: 0,
      hadReceiver: 0,
      receiverMarked: 0,
      weakTaker: 0,
      aerialDisadvantage: 0,
      gateOpen: 0,
      selected: 0,
      samples: [],
    };
    /**
     * Diagnostic-only, opt-in (opts.decisionDiagRoles: ["CM"] etc.) —
     * "instrument before you tune" for the CM-vs-AM/W creative-output
     * question. Logs every possession-decision entry for a tracked role:
     * where the carrier was, what forward/through/wide/box options
     * existed, the single best-scoring option by scorePassingOption (the
     * same yardstick the engine's own generic passing logic uses — not a
     * new scoring system), what was actually chosen, and the pass
     * outcome (completed/intercepted/steal/offside) where applicable.
     * Zero overhead when no role is being tracked (the common case —
     * gated at the top of decideAction, never runs during normal play or
     * FM Mobile broadcasts).
     */
    const decisionDiagRoles = new Set(Array.isArray(opts.decisionDiagRoles) ? opts.decisionDiagRoles : []);
    const decisionDiagAll = Boolean(opts.decisionDiagAll);
    let decisionDiag = { samples: [] };
    let pendingDecisionSnapshot = null;
    /**
     * Diagnostic-only, opt-in — raw possession count per pin (every time
     * giveBall() hands a player the ball, regardless of what they do with
     * it or whether decideAction resolves into one of the four hooked
     * actions below). This is deliberately a SEPARATE counter from
     * decisionDiag's sample count: decisionDiag only captures possessions
     * that terminate in pass/carry/dribble/shot, so comparing the two
     * numbers per player answers "how many touches were there at all" vs
     * "how many of those touches did we actually classify" — the exact
     * gap the CM/AM touch-rate question needed and didn't have.
     */
    let possessionCounts = {};
    /** Last successful passer before shot/goal — used for assist attribution. */
    let lastPasser = null;

    /** Possession spell: BUILD_UP → … → FINISH (depth + box occupation). */
    let spell = null;

    /** Event log for post-match analysis (goals, offsides, broken passes, etc.). */
    let matchLog = emptyMatchLog();

    function emptyMatchLog() {
      const blank = () => ({
        goals: 0,
        assists: 0,
        shots: 0,
        big_chances: 0,
        offsides: 0,
        passes_broken: 0,
        dribbles_won: 0,
        dribbles_lost: 0,
        saves: 0,
        blocked_shots: 0,
        possessions: 0,
        turnovers: 0,
        chances_created: 0,
        xg: 0,
      });
      return {
        goals: [],
        assists: [],
        events: [],
        counts: { home: blank(), away: blank() },
        spells: [],
        unit_edges: {
          home: { ...unitHome },
          away: { ...unitAway },
        },
      };
    }

    function clearLastPasser() {
      lastPasser = null;
    }

    function bumpCount(side, key, n = 1) {
      const bucket = matchLog.counts[side];
      if (!bucket || !(key in bucket)) return;
      bucket[key] += n;
    }

    function pushMatchEvent(type, side, extra = {}) {
      const entry = {
        type,
        side,
        minute: Math.max(0, Math.floor(matchMinute)),
        player: extra.player || null,
        player_short: extra.player_short || null,
        detail: extra.detail || null,
      };
      if (extra.by) entry.by = extra.by;
      if (extra.against) entry.against = extra.against;
      if (extra.xg != null && Number.isFinite(Number(extra.xg))) entry.xg = Number(extra.xg);
      if (extra.assist) entry.assist = extra.assist;
      if (extra.assist_short) entry.assist_short = extra.assist_short;
      if (extra.distance != null && Number.isFinite(Number(extra.distance))) entry.distance = Number(extra.distance);
      if (extra.big_chance != null) entry.big_chance = Boolean(extra.big_chance);
      if (extra.in_box != null) entry.in_box = Boolean(extra.in_box);
      matchLog.events.push(entry);
      if (mobileBroadcast && isMobileKeyEvent(type, entry.detail)) triggerMobileHighlight();
      if (type === "goal") {
        bumpCount(side, "goals");
        const goalRow = {
          side,
          minute: entry.minute,
          player: entry.player,
          player_short: entry.player_short,
        };
        if (entry.assist) {
          goalRow.assist = entry.assist;
          goalRow.assist_short = entry.assist_short || null;
          bumpCount(side, "assists");
          matchLog.assists.push({
            side,
            minute: entry.minute,
            player: entry.assist,
            player_short: entry.assist_short || null,
            for_player: entry.player,
          });
        }
        matchLog.goals.push(goalRow);
      } else if (type === "shot" || type === "big_chance") {
        bumpCount(side, "shots");
        if (type === "big_chance") bumpCount(side, "big_chances");
        bumpCount(side, "chances_created");
      } else if (type === "offside") bumpCount(side, "offsides");
      else if (type === "pass_broken") bumpCount(side, "passes_broken");
      else if (type === "dribble_won") bumpCount(side, "dribbles_won");
      else if (type === "dribble_lost") bumpCount(side, "dribbles_lost");
      else if (type === "save") bumpCount(side, "saves");
      else if (type === "blocked_shot") bumpCount(side, "blocked_shots");
      else if (type === "possession") bumpCount(side, "possessions");
      else if (type === "turnover") bumpCount(side, "turnovers");
    }

    function possessionPct() {
      const total = possSeconds.home + possSeconds.away;
      if (total < 0.01) return { home: 50, away: 50 };
      const h = Math.round((possSeconds.home / total) * 100);
      return { home: h, away: 100 - h };
    }

    function updateHud() {
      const poss = possessionPct();
      if (possHEl) possHEl.textContent = String(poss.home);
      if (possAEl) possAEl.textContent = String(poss.away);
      if (xgHEl) xgHEl.textContent = liveXg.home.toFixed(2);
      if (xgAEl) xgAEl.textContent = liveXg.away.toFixed(2);
      if (mobileBroadcast) {
        updateMobileStats(poss);
        updateMobileScorers();
      }
    }

    /**
     * FM Mobile broadcast mode — the 7 stats shown per side, picked to
     * mirror the real FM Mobile match-stats screen the user referenced
     * (possession / clear-cut chances / shots / shots on target / fouls
     * & corners as one combined row) with xG substituted for "team
     * rating," which nothing here computes live. All derived from
     * data already tracked (matchLog.counts, matchLog.events, liveXg) —
     * no new counters. shots-on-target isn't a stored counter, so it's
     * derived: every goal is on target by definition, and every "save"
     * event already records which side was shooting via its `against`
     * field.
     */
    const mobileStatEls = {};
    if (mobileStatsEl) {
      mobileStatsEl.querySelectorAll("[data-ms]").forEach((el) => {
        mobileStatEls[el.dataset.ms] = el;
      });
    }
    function mobileTeamStats(side) {
      const counts = matchLog.counts[side];
      const events = matchLog.events;
      const shotsOnTarget =
        events.filter((e) => e.type === "goal" && e.side === side).length +
        events.filter((e) => e.type === "save" && e.against === side).length;
      const corners = events.filter((e) => e.type === "corner" && e.side === side).length;
      const fouls = events.filter((e) => e.type === "foul" && e.side === side).length;
      return { shots: counts.shots, shotsOnTarget, bigChances: counts.big_chances, corners, fouls };
    }
    function updateMobileStats(poss) {
      if (!mobileStatsEl) return;
      const p = poss || possessionPct();
      const h = mobileTeamStats("home");
      const a = mobileTeamStats("away");
      const set = (key, val) => {
        if (mobileStatEls[key]) mobileStatEls[key].textContent = val;
      };
      set("poss-home", `${p.home}%`);
      set("poss-away", `${p.away}%`);
      set("bigchances-home", h.bigChances);
      set("bigchances-away", a.bigChances);
      set("xg-home", liveXg.home.toFixed(2));
      set("xg-away", liveXg.away.toFixed(2));
      set("shots-home", h.shots);
      set("shots-away", a.shots);
      set("sot-home", h.shotsOnTarget);
      set("sot-away", a.shotsOnTarget);
      set("fouls-home", h.fouls);
      set("fouls-away", a.fouls);
      set("corners-home", h.corners);
      set("corners-away", a.corners);
    }

    /** FM Mobile broadcast mode — goal/card strip beneath the score, like the reference screenshot. */
    function updateMobileScorers() {
      if (!mobileScorersHomeEl || !mobileScorersAwayEl) return;
      const cards = matchLog.events.filter((e) => e.type === "yellow_card");
      const rowsFor = (side) => {
        const goalRows = matchLog.goals
          .filter((g) => g.side === side)
          .map((g) => `<div class="ms-scorer">⚽ ${escHtml(g.player_short || g.player)} ${g.minute}'</div>`);
        const cardRows = cards
          .filter((e) => e.side === side)
          .map((e) => `<div class="ms-scorer ms-card">\u{1F7E8} ${escHtml(e.player_short || e.player)} ${e.minute}'</div>`);
        return goalRows.concat(cardRows).join("");
      };
      mobileScorersHomeEl.innerHTML = rowsFor("home");
      mobileScorersAwayEl.innerHTML = rowsFor("away");
    }

    /** FM Mobile broadcast mode — zone strip marker from live ball position, per-frame (cheap: one style write). */
    function updateMobileZone() {
      if (!mobileZoneMarkerEl) return;
      // home attacks toward decreasing top (top~0 = away's own goal); the
      // "home" label sits on the LEFT of the strip, so a ball near home's
      // OWN goal (top~100) should read as the LEFT end: 100 - top.
      const pos = clamp(100 - ball.top, 0, 100);
      mobileZoneMarkerEl.style.left = `${pos}%`;
      mobileZoneMarkerEl.classList.toggle("mz-marker--home", possession === "home");
      mobileZoneMarkerEl.classList.toggle("mz-marker--away", possession === "away");
      if (bottombarEl) {
        bottombarEl.classList.toggle("poss-home", possession === "home");
        bottombarEl.classList.toggle("poss-away", possession === "away");
      }
    }

    /**
     * FM Mobile broadcast mode — the pitch and the scorers/stats/zone panel
     * occupy the same slot, not stacked (stacking forced a scroll to reach
     * the pitch). Exactly one is visible at a time: the pitch while a key
     * event is live/building, the info panel otherwise.
     */
    function setMobileLive(isLive) {
      if (pitchWrapEl) pitchWrapEl.classList.toggle("tactic-pitch-wrap--live", isLive);
      if (mobileInfoEl) mobileInfoEl.hidden = isLive;
    }

    /**
     * FM Mobile broadcast mode — only corners, direct free kicks, shots,
     * goals, and yellow cards get the full pitch shown, and only for a
     * bounded REAL-time window (not sim-time — the whole point is to
     * slow the clock down so the viewer has time to actually watch it).
     * Everything else stays on the fast commentary+zone-strip view.
     */
    function triggerMobileHighlight() {
      if (!mobileBroadcast) return;
      if (mobileEventUntilTs <= 0) {
        speed = MOBILE_EVENT_SPEED;
        setMobileLive(true);
      }
      mobileEventUntilTs = performance.now() + MOBILE_EVENT_MS;
    }
    function isMobileKeyEvent(type, detail) {
      if (type === "shot" || type === "goal" || type === "corner" || type === "yellow_card") return true;
      if (type === "free_kick" && detail === "direct free kick") return true;
      return false;
    }

    /**
     * Team-context adjustment from goals_conceded90 (via the server-computed
     * goals_conceded_percentile, ranked against the full match player pool
     * -- see web/tournament.py's _percentile_ranks). Per the user's own
     * framing: a player who posted good individual numbers for a leaky-
     * defense team is quietly better than their raw stats suggest, since
     * their team gave them a worse platform. Bounded to a modest nudge
     * (0.92-1.10), not a dominant factor. Scoped to openPlayXg (below) --
     * the single, already-reused "how threatening is this attacker really"
     * signal from Batch B -- rather than sprinkled across every formula.
     */
    function sideContextMul(side) {
      const pins = pinsOf(side).filter((p) => p.role !== "GK");
      if (!pins.length) return 1;
      const avg = pins.reduce((s, p) => s + (p.stats.goals_conceded_percentile ?? 0.5), 0) / pins.length;
      return clamp(0.92 + avg * 0.18, 0.92, 1.1);
    }

    /**
     * xg90 includes penalty history, which has nothing to do with a specific
     * open-play look. npxg90 (now its own field on .stats, see mergeStats)
     * is the right signal for open-play decisions; penalty-specific
     * functions (penConvertChance, pickPenaltyOrder) keep reading raw xg90
     * on purpose, since penalty conversion is exactly what that captures.
     */
    function openPlayXg(pin) {
      if (!pin || !pin.stats) return 0;
      const raw = pin.stats.npxg90 || pin.stats.xg90 || 0;
      return raw * sideContextMul(pin.side);
    }

    function estimateChanceXg(carrier, chanceType) {
      const d = possessionDepth(carrier);
      const create = sideCreate(carrier.side);
      const boxed = inPenaltyBox(carrier);
      const near = nearPenaltyBox(carrier);
      const ready = boxOccupationReady(carrier.side);
      const carrierXg = openPlayXg(carrier);
      let kind = chanceType;
      if (kind === "big_chance" && (!boxed || !ready)) kind = "shot";
      let base;
      let floor;
      let ceil;
      if (boxed && ready && kind === "big_chance") {
        base = 0.28 + carrierXg * 0.2 + create * 0.07;
        floor = 0.16 + create * 0.05;
        ceil = 0.68;
      } else if (boxed && ready) {
        base = 0.15 + carrierXg * 0.14 + create * 0.05;
        floor = 0.1 + create * 0.03;
        ceil = 0.42;
      } else if (boxed && !ready) {
        base = 0.1 + carrierXg * 0.06;
        floor = 0.07;
        ceil = 0.18;
      } else if (near) {
        base = 0.07 + carrierXg * 0.05 + create * 0.02;
        floor = 0.04;
        ceil = 0.14;
      } else {
        base = 0.035 + carrierXg * 0.03;
        floor = 0.025;
        ceil = 0.11;
      }
      const depthBoost = boxed && ready ? (d > 0.88 ? 0.08 : 0.04) : 0;
      let xg = clamp(Math.max(floor, base + depthBoost + (rng() - 0.5) * 0.02), floor, ceil);
      if (xg > 0.2 && !ready) xg = Math.min(xg, 0.15);
      if (!boxed) xg = Math.min(xg, 0.14);
      // Soft possession→xG: low-control sides get slightly worse looks; sterile high-poss muted
      const volMul = possChanceVolumeMul(carrier.side);
      const suppMul = possessionSuppressionMul(carrier.side);
      xg *= lerp(1, volMul, 0.32) * suppMul;
      // Engine fix — same pace anchor as spellChanceP (xgPaceMul), blended at
      // partial weight here. Frequency (spellChanceP) is still the primary
      // lever; this just means a side already running well above its own
      // expected pace doesn't get full-quality looks on top of also getting
      // more of them, instead of frequency alone carrying the entire
      // correction.
      xg *= lerp(1, xgPaceMul(carrier.side), 0.45);
      if (isMaestroPin(carrier) && volMul < 0.98) {
        xg *= clamp(1.06 + (1 - volMul) * 0.14, 1, 1.2);
      }
      // Elite ST/W/AM big looks: nudge chance xG toward their season shot quality
      if (isAttackFinisher(carrier) && boxed && ready) {
        const fq = finisherQuality(carrier);
        xg *= clamp(1 + (fq - 0.5) * 0.12, 0.94, 1.14);
        ceil = Math.min(0.75, ceil + (fq >= 0.7 ? 0.04 : 0));
      }
      // Knockout-only home push (shot quality) — see KNOCKOUT_HOME_PUSH.
      if (isKnockout && !isFinalRound && carrier.side === "home") xg *= 1 + KNOCKOUT_HOME_PUSH;
      return clamp(xg, Math.min(floor, 0.02), ceil);
    }

    function getMatchLogPayload() {
      const poss = possessionPct();
      matchLog.counts.home.xg = Math.round(liveXg.home * 1000) / 1000;
      matchLog.counts.away.xg = Math.round(liveXg.away * 1000) / 1000;
      const payload = {
        goals: matchLog.goals.slice(),
        assists: matchLog.assists.slice(),
        events: matchLog.events.slice(),
        counts: {
          home: { ...matchLog.counts.home },
          away: { ...matchLog.counts.away },
        },
        spells: matchLog.spells.slice(),
        unit_edges: matchLog.unit_edges,
        possession: { home: poss.home, away: poss.away },
        possession_pct: { home: poss.home, away: poss.away },
        xg: {
          home: Math.round(liveXg.home * 1000) / 1000,
          away: Math.round(liveXg.away * 1000) / 1000,
        },
        live_xg: {
          home: Math.round(liveXg.home * 1000) / 1000,
          away: Math.round(liveXg.away * 1000) / 1000,
        },
        home_goals: homeScore,
        away_goals: awayScore,
      };
      if (ft90Home != null) {
        payload.ft_home_goals = ft90Home;
        payload.ft_away_goals = ft90Away;
      }
      if (decidedBy === "pens" || penLog.length) {
        payload.penalties = {
          home: penScore.home,
          away: penScore.away,
          kicks: penLog.slice(),
        };
      }
      if (decidedBy && decidedBy !== "ft") payload.decided_by = decidedBy;
      return payload;
    }

    function say(text, hold = 1.6) {
      phaseEl.textContent = text;
      commentaryHold = hold;
      const min = Math.max(0, Math.floor(matchMinute));
      commentaryLines.push({ minute: min, text: String(text || "") });
      if (commentaryLines.length > 12) commentaryLines.shift();
      if (feedEl) {
        const item = document.createElement("div");
        item.className = "tactic-commentary-item";
        item.innerHTML = `<span class="cm-min">${min}'</span>${escHtml(text)}`;
        feedEl.appendChild(item);
        while (feedEl.children.length > 40) feedEl.removeChild(feedEl.firstChild);
        feedEl.scrollTop = feedEl.scrollHeight;
      }
    }

    /** Hide OFFSIDE! overlay (display:grid otherwise beats [hidden]). */
    function clearFlash() {
      flashTimer = 0;
      if (flashEl) {
        flashEl.hidden = true;
        flashEl.textContent = "";
      }
    }

    /** Slide-in goal-scorer card — badge + name + minute/assist/scoreline. */
    function showGoalCard(side, scorerName, badgeText, subText) {
      if (!goalCardEl) return;
      goalCardTimer = 2.4;
      goalCardEl.hidden = false;
      goalCardEl.className = `tactic-goalcard ${side}`;
      if (goalCardBadgeEl) {
        goalCardBadgeEl.textContent = badgeText || "";
        goalCardBadgeEl.style.background = side === "home" ? "var(--home)" : "var(--away)";
      }
      if (goalCardNameEl) goalCardNameEl.textContent = scorerName || "Goal!";
      if (goalCardSubEl) goalCardSubEl.textContent = subText || "";
      // Force reflow so the slide-in transition replays on back-to-back goals.
      void goalCardEl.offsetWidth;
      goalCardEl.classList.add("show");
    }

    function clearGoalCard() {
      goalCardTimer = 0;
      if (goalCardEl) {
        goalCardEl.classList.remove("show");
        goalCardEl.hidden = true;
      }
    }

    function setBallTarget(left, top, dur, attach, ctrl) {
      ballFrom = { left: ball.left, top: ball.top };
      // Allow ~1–99 so finishes can land inside the goal mouth (CSS ~0–2.5% / 97.5–100%)
      ballTo = { left: clamp(left, 1, 99), top: clamp(top, 0.85, 99.15) };
      if (ctrl && Number.isFinite(ctrl.left) && Number.isFinite(ctrl.top)) {
        ballCtrl = { left: clamp(ctrl.left, 1, 99), top: clamp(ctrl.top, 1, 99) };
      } else {
        ballCtrl = null;
      }
      ballTween = 0;
      ballTweenDur = Math.max(0.22, dur || 0.45);
      if (attach !== undefined) ballAttached = attach;
    }

    /**
     * Set-piece Phase 0 — generic out-of-bounds detection. Evaluated on the
     * RAW, unclamped intended ball destination — callers MUST pass this
     * before any local safety clamp of their own, otherwise an intended
     * (103, 50) silently becomes "stayed in play" once clamped to 99 and
     * the whole point is lost. setBallTarget's own clamp above is
     * untouched and stays the final safety net for genuinely in-play
     * destinations — this function only decides whether a destination
     * even reaches it.
     *
     * Geometry (absolute pitch %, both axes 0-100): touchlines at
     * left=0/100, bylines at top=0/100. The goal mouth mirrors
     * attackGoalLeft()'s own 46.5-53.5 window; a byline-crossing
     * destination inside that window is a genuine shot — its actual
     * goal/save/wide outcome is already pre-decided by ballFlight before
     * this destination was ever picked (see doShot) — and is explicitly
     * left alone here, never classified as a restart.
     */
    const OOB_GOAL_MOUTH_MIN = 45;
    const OOB_GOAL_MOUTH_MAX = 55;
    function evaluateOutOfBounds(rawLeft, rawTop, touchSide) {
      const sidelineOut = rawLeft < 0 || rawLeft > 100;
      const bylineOut = rawTop < 0 || rawTop > 100;
      if (!sidelineOut && !bylineOut) return null;

      if (bylineOut) {
        const inGoalMouth = rawLeft >= OOB_GOAL_MOUTH_MIN && rawLeft <= OOB_GOAL_MOUTH_MAX;
        if (inGoalMouth) return null;
        // home attacks toward decreasing top (top≈0 = away's goal); away
        // attacks toward increasing top (top≈100 = home's goal) — see
        // toPitchPct's own doc comment.
        const bylineIsHomeGoal = rawTop > 100;
        const goalOwnerSide = bylineIsHomeGoal ? "home" : "away";
        const attackingSide = oppOf(goalOwnerSide);
        const clampedLeft = clamp(rawLeft, 3, 97);
        const clampedTop = bylineIsHomeGoal ? 98 : 2;
        if (touchSide === attackingSide) {
          return { type: "goal_kick", side: goalOwnerSide, left: clampedLeft, top: clampedTop };
        }
        return { type: "corner", side: attackingSide, left: clampedLeft, top: clampedTop };
      }

      // Sideline: thrown to whichever side did NOT put it out.
      const side = oppOf(touchSide);
      const clampedTop = clamp(rawTop, 3, 97);
      const clampedLeft = rawLeft < 0 ? 1 : 99;
      return { type: "throw_in", side, left: clampedLeft, top: clampedTop };
    }

    /**
     * Wraps setBallTarget with the out-of-bounds check above WITHOUT
     * changing setBallTarget's own semantics/signature at all — it stays a
     * pure safety clamp for genuinely in-play destinations. Callers whose
     * destination is a real, could-legitimately-miss decision (a
     * dribble/carry touch, an open pass) should call this instead of
     * setBallTarget directly. Scripted/always-in-bounds placements
     * (kickoff centering, HT reset, corner-flag spots, penalty spot,
     * shot-outcome destinations already pre-decided by ballFlight) should
     * keep calling setBallTarget directly — a generic geometry check has
     * nothing useful to add there, and touching every call site
     * indiscriminately is exactly the invasive change we're avoiding.
     */
    function dispatchBallTarget(left, top, dur, attach, ctrl, touchSide) {
      const oob = evaluateOutOfBounds(left, top, touchSide);
      if (oob) {
        oobStats.outOfBoundsEvents++;
        if (oob.type === "throw_in") oobStats.touchlineExits++;
        else oobStats.bylineExits++;
        lastTouchSide = touchSide;
        pendingSetPiece = { ...oob, at: matchMinute + 0.35 };
        ballAttached = false;
        setBallTarget(oob.left, oob.top, Math.min(0.35, dur || 0.3), false, null);
        return true;
      }
      setBallTarget(left, top, dur, attach, ctrl);
      return false;
    }

    /** Published ball path for host→viewer sync (fixed travel; no mid-tween redecide). */
    function getBallPathState() {
      if (ballTween >= 1) {
        return {
          left: Math.round(ball.left * 100) / 100,
          top: Math.round(ball.top * 100) / 100,
          attached: Boolean(ballAttached),
          tween: 1,
        };
      }
      return {
        left: Math.round(ball.left * 100) / 100,
        top: Math.round(ball.top * 100) / 100,
        from: {
          left: Math.round(ballFrom.left * 100) / 100,
          top: Math.round(ballFrom.top * 100) / 100,
        },
        to: {
          left: Math.round(ballTo.left * 100) / 100,
          top: Math.round(ballTo.top * 100) / 100,
        },
        ctrl: ballCtrl
          ? {
              left: Math.round(ballCtrl.left * 100) / 100,
              top: Math.round(ballCtrl.top * 100) / 100,
            }
          : null,
        tween: Math.round(ballTween * 1000) / 1000,
        tweenDur: Math.round(ballTweenDur * 1000) / 1000,
        attached: Boolean(ballAttached),
      };
    }

    /** Curved pass control point + duration from distance (visible arc, no teleport). */
    function passArcFor(fromL, fromT, toL, toT, kind) {
      const dx = toL - fromL;
      const dy = toT - fromT;
      const d = Math.hypot(dx, dy) + 1e-6;
      const midL = (fromL + toL) * 0.5;
      const midT = (fromT + toT) * 0.5;
      const nx = -dy / d;
      const ny = dx / d;
      // Crosses loft higher and hang longer so contested headers read clearly
      let loft;
      let base;
      let durMin = 0.3;
      let durMax = 0.62;
      if (kind === "cross") {
        loft = 12 + d * 0.22;
        base = 0.58 + d * 0.01;
        durMin = 0.52;
        durMax = 0.95;
      } else if (kind === "switch" || kind === "long") {
        loft = 7 + d * 0.12;
        base = 0.42 + d * 0.0065;
      } else if (kind === "through") {
        loft = 4.5 + d * 0.08;
        base = 0.36 + d * 0.0055;
      } else if (kind === "cutback") {
        loft = 2.4 + d * 0.04;
        base = 0.28 + d * 0.0045;
        durMin = 0.26;
        durMax = 0.48;
      } else {
        loft = 3.2 + d * 0.06;
        base = 0.3 + d * 0.005;
      }
      const side = (midL < 50 ? 1 : -1) * (rng() < 0.5 ? 1 : 0.65);
      const loftY = kind === "cross" ? 0.85 : 0.55;
      const ctrl = {
        left: clamp(midL + nx * loft * side, 4, 96),
        top: clamp(midT + ny * loft * side * loftY - Math.abs(dy) * (kind === "cross" ? 0.08 : 0.04), 3, 97),
      };
      return { ctrl, dur: clamp(base, durMin, durMax) };
    }

    function stepBallTween(dt) {
      if (ballTween >= 1) return false;
      ballTween = Math.min(1, ballTween + dt / Math.max(0.18, ballTweenDur));
      const u = easeInOut(ballTween);
      if (ballCtrl) {
        ball.left = bezier2(ballFrom.left, ballCtrl.left, ballTo.left, u);
        ball.top = bezier2(ballFrom.top, ballCtrl.top, ballTo.top, u);
      } else {
        ball.left = lerp(ballFrom.left, ballTo.left, u);
        ball.top = lerp(ballFrom.top, ballTo.top, u);
      }
      const rTween = toRenderXY(ball.left, ball.top);
      ballEl.style.left = `${rTween.left}%`;
      ballEl.style.top = `${rTween.top}%`;
      if (ballTween >= 1) {
        ballCtrl = null;
        return false;
      }
      return true;
    }

    /** Apply a locked-in ballFlight once the tween finishes. */
    function resolveBallFlight() {
      const flight = ballFlight;
      if (!flight) return;
      ballFlight = null;
      ball.left = ballTo.left;
      ball.top = ballTo.top;
      const rResolve = toRenderXY(ball.left, ball.top);
      ballEl.style.left = `${rResolve.left}%`;
      ballEl.style.top = `${rResolve.top}%`;
      ballTween = 1;
      ballCtrl = null;

      if (flight.outcome === "intercept" || flight.outcome === "steal") {
        const def = flight.interceptor;
        clearLastPasser();
        if (def) {
          // Set-piece Phase 3 — corner second balls. A cleared corner
          // previously always handed the clearing defender 100% clean
          // possession, no matter how crowded the box was. Scoped tightly
          // to corner-originated crosses only (pendingCornerContext, set
          // right before resolveCornerDelivery's doPass call and consumed
          // exactly once here) — every other intercept/steal in the match,
          // including every regular open-play cross, is untouched.
          if (
            flight.outcome === "intercept" &&
            pendingCornerContext &&
            matchMinute < pendingCornerContext.until &&
            def.side === pendingCornerContext.defSide
          ) {
            const ctx = pendingCornerContext;
            pendingCornerContext = null;
            cornerStats.clearances++;
            if (rng() < 0.32) {
              cornerStats.secondBalls++;
              const contest = resolveCornerSecondBall(ctx.attackingSide, ctx.defSide, def);
              if (contest.winnerSide === ctx.attackingSide) {
                cornerStats.firstContactsAttack++;
                archiveSpell("corner_second_ball");
                spell = null;
                giveBall(contest.pin, `${contest.pin.short} pounces on the loose ball!`);
                if (inPenaltyBox(contest.pin) || nearPenaltyBox(contest.pin)) {
                  cornerStats.cornerShots++;
                  doShot(contest.pin, false);
                }
                actionTimer = 0.5;
                return;
              }
              cornerStats.firstContactsDefense++;
              archiveSpell("intercept");
              spell = null;
              giveBall(contest.pin, `${contest.pin.short} clears the second ball`);
              triggerTurnoverReactions(contest.pin);
              actionTimer = 0.4 + spellIdlePause() * 0.45;
              return;
            }
            cornerStats.firstContactsDefense++;
          }
          pendingCornerContext = null;
          archiveSpell(flight.outcome === "steal" ? "press" : "intercept");
          spell = null;
          giveBall(def, flight.comment || `${def.short} intercepts`);
          triggerTurnoverReactions(def);
          actionTimer = 0.4 + spellIdlePause() * 0.45;
        }
        return;
      }

      if (flight.outcome === "offside") {
        clearLastPasser();
        whistleOffside(flight.pin);
        return;
      }

      if (flight.outcome === "pass") {
        const to = flight.pin;
        const from = flight.from;
        if (!to) return;
        if (
          pendingCornerContext &&
          matchMinute < pendingCornerContext.until &&
          to.side === pendingCornerContext.attackingSide
        ) {
          cornerStats.firstContactsAttack++;
          pendingCornerContext = null;
        }
        carrierId = to.id;
        possession = to.side;
        ballAttached = true;
        to._dribbleStreak = 0;
        to._lastDribbleOpp = null;
        // Engine fix — every deliberate action in this file (doDribble,
        // doCarry, doShot's plant, driveIntoBox...) sets _pathCtrl, tx/ty,
        // and lockUntil together as one unit; reception set none of them.
        // A receiver still mid-run carries whatever _pathCtrl bulge was
        // active from their PREVIOUS action, and with no lockUntil,
        // updateTeamShape is free to overwrite their tx/ty with a fresh
        // generic shape target on the very next tick, before decideAction
        // gets a chance to issue a real next move. The bezier curve then
        // has to bend from the current position, through a now-stale
        // control point, to a target that just changed out from under it —
        // reads as an unmotivated plant-and-pull-back right after the ball
        // arrives (the "fake shot" look). Clear the stale curve and hold
        // position briefly so the receiver's own next decision — not shape
        // — is what moves them.
        to._pathCtrl = null;
        to.lockUntil = Math.max(to.lockUntil || 0, matchMinute + 0.15);
        // Bug fix — the organic arrival-based decision (evaluateArrivals/
        // scoreDynamicReceiver) had no memory of who just passed to this
        // player, so a receiver with residual high arrival momentum could
        // immediately look like the best target back to their own passer,
        // producing an unbounded through-ball ping-pong (two players
        // trading "slips it through" every tick, never shooting, since
        // evaluateArrivals is checked before any shot logic runs).
        to._lastPasserFrom = from ? from.id : null;
        // Engine fix — player orientation (Problem 11), first concrete
        // consumer. A receiver's real facing direction (tracked in
        // applyPinMotion from actual movement, not a proxy) tells us
        // whether they took the ball on the half-turn or with their back to
        // goal. The latter needs a genuine extra touch before they can turn
        // and drive — read as a brief penalty by doDribble/doCarry/
        // driveIntoBox rather than treating every reception as equally
        // ready to go immediately.
        {
          const attackSign = to.side === "home" ? -1 : 1;
          const facingForward = (to.facingY ?? 0) * attackSign > 0.15;
          if (!facingForward) to._backToGoalUntil = matchMinute + 0.22;
        }
        // Engine rebuild — pass memory. Record who's received the ball
        // recently in this spell so scorePassingOption can penalize giving
        // it straight back, instead of the same CM<->RB exchange scoring as
        // the "best" option forever regardless of context.
        if (spell && spell.side === to.side) {
          spell.lastReceivers = spell.lastReceivers || [];
          spell.lastReceivers.push(to.id);
          if (spell.lastReceivers.length > 4) spell.lastReceivers.shift();
        }
        // Engine rebuild — parallel/simultaneous reactions (Problem 8).
        triggerReceptionReactions(to);
        // Engine fix — the recovery reaction that fires when a duel is
        // physically lost (doDribble/doCarry/driveIntoBox) also needs to
        // fire here: a dangerous pass into an advanced position beats the
        // defence positionally even when no dribble ever happened — the
        // exact gap behind "slips it through -> unmarked run -> goal" with
        // zero defensive reaction anywhere in the sequence. Treat the
        // defender nearest the new advanced receiver as the one who needed
        // to close the passing lane and didn't, and fire the same recovery
        // burst (chase back, covering CB/FB shifts across, DM/CM drops in).
        if (possessionDepth(to) >= 0.55) {
          const nearestDef = nearestOpponent(to, 16);
          if (nearestDef) triggerDefensiveBreachReactions(nearestDef.pin);
        }
        if (from && from.side === to.side && from.player) {
          lastPasser = {
            player: from.player,
            player_short: from.short || shortName(from.player),
            side: from.side,
            toId: to.id,
          };
        }
        if (flight.lockRun) {
          to.tx = flight.lockTx ?? to.tx;
          to.ty = flight.lockTy ?? to.ty;
          to.lockUntil = matchMinute + 0.8;
        }
        updatePhaseFromBall();
        actionTimer = Math.max(actionTimer, spellIdlePause() * 0.65);
        if (flight.thenShot) {
          if (spell) spell.awaitingShot = false;
          pendingShot = { side: to.side, at: matchMinute + 0.12 };
        }
        return;
      }

      if (flight.outcome === "dribble_won") {
        ballAttached = true;
        actionTimer = Math.max(actionTimer, spellIdlePause() * 0.5);
        return;
      }

      if (flight.outcome === "dribble_lost") {
        const opp = flight.interceptor;
        clearLastPasser();
        archiveSpell("dribble_lost");
        spell = null;
        if (opp) {
          giveBall(opp, flight.comment || `${opp.short} wins it`);
          triggerTurnoverReactions(opp);
        }
        actionTimer = 0.4;
        return;
      }

      if (flight.outcome === "goal") {
        markGoal(flight.side);
        actionTimer = 1.5;
        pendingRestart = { side: oppOf(flight.side), at: matchMinute + 1.05 };
        return;
      }

      if (flight.outcome === "save") {
        const keeper = flight.interceptor;
        clearLastPasser();
        pushMatchEvent("save", keeper.side, {
          player: keeper.player,
          player_short: keeper.short,
          against: flight.against,
          detail: `denied ${flight.shooterShort || "the shot"}`,
        });
        // Engine addition — corners. A save isn't always a clean catch;
        // sometimes the keeper can only push it behind. Not every save, or
        // this becomes a corner-fest, but a real fraction.
        if (rng() < 0.3) {
          say(`${keeper.short} can only palm it behind!`, 1.3);
          spell = null;
          resolveCorner(flight.against);
          return;
        }
        say(`${keeper.short} saves`, 1.3);
        spell = null;
        giveBall(keeper, `${keeper.short} clears`);
        const outlet = pinsOf(keeper.side).find((p) => p.role === "CB" || p.role === "DM" || p.role === "FB");
        if (outlet) {
          pendingClear = { fromId: keeper.id, toId: outlet.id, at: matchMinute + 0.35 };
        }
        actionTimer = 0.7;
        return;
      }

      if (flight.outcome === "blocked") {
        const blocker = flight.interceptor;
        clearLastPasser();
        if (blocker) {
          pushMatchEvent("blocked_shot", blocker.side, {
            player: blocker.player,
            player_short: blocker.short,
            against: flight.against,
            detail: `blocked ${flight.shooterShort || "the shot"}`,
          });
        }
        // Engine addition — corners. A last-ditch block is hard to control
        // the direction of; often it goes behind rather than staying in play.
        if (blocker && rng() < 0.42) {
          say(`Blocked behind! ${blocker.short} turns it behind for a corner`, 1.3);
          spell = null;
          resolveCorner(flight.against);
          return;
        }
        say(`Blocked! ${blocker?.short || "defender"} gets across`, 1.3);
        spell = null;
        if (blocker) giveBall(blocker, `${blocker.short} clears the danger`);
        actionTimer = 0.65;
        return;
      }

      if (flight.outcome === "wide") {
        const defPin = flight.interceptor;
        clearLastPasser();
        // Engine addition — corners. Most wide shots just go out for a
        // goal kick, but a shot close enough to curl just past the post
        // (rather than sail well wide) can take a deflection behind too.
        if (rng() < 0.18) {
          say(`${flight.shooterShort || "Shot"} goes wide — off the post and behind`, 1.2);
          spell = null;
          resolveCorner(flight.against);
          return;
        }
        say(`${flight.shooterShort || "Shot"} goes wide`, 1.2);
        spell = null;
        if (defPin) giveBall(defPin, `${defPin.short} starts again`);
        actionTimer = 0.7;
        return;
      }
    }

    function flushDeferredRestarts() {
      if (pendingShot && matchMinute >= pendingShot.at && ballTween >= 1 && !ballFlight) {
        const side = pendingShot.side;
        pendingShot = null;
        if (spell) spell.awaitingShot = false;
        const c = findCarrier();
        if (c && c.side === side && !finished) {
          if (
            !inPenaltyBox(c) &&
            !c._boxDriveDone &&
            // Engine addition — goal-scoring midfielder archetype (a
            // Lampard/Gerrard arriving late to shoot). CM/DM eligibility is
            // self-correcting: their own xg90 still drives the roll below,
            // so a real passer (low xg90) rarely triggers this regardless.
            (c.role === "ST" || c.role === "AM" || c.role === "CM" || c.role === "DM") &&
            rng() < 0.7 + c.stats.xg90 * 0.2
          ) {
            c._boxDriveDone = true;
            if (spell) {
              spell.awaitingBoxShot = true;
              spell.chanceDone = false;
            }
            if (driveIntoBox(c)) return;
          }
          c._boxDriveDone = false;
          // Bug fix — same class as the shoot-decision fixes elsewhere: the
          // drive-in attempt above only fires for ST/AM/CM/DM on a
          // probability roll, so a W/FB pendingShot carrier (or a failed
          // roll/drive-in) fell straight through to a naked shot with no
          // box-proximity check at all. Gate on the carrier's own position.
          if (!inPenaltyBox(c) && !nearPenaltyBox(c)) {
            if (forwardInFinalThird(c)) {
              forwardFinalThirdAction(c);
              return;
            }
            doPass(c, backPassTarget(c), "pass");
            dropPossessionState(1);
            return;
          }
          doShot(c, false);
        }
        return;
      }
      if (pendingRestart && matchMinute >= pendingRestart.at && ballTween >= 1 && !ballFlight) {
        const side = pendingRestart.side;
        pendingRestart = null;
        clearFlash();
      clearGoalCard();
        const c = pickKickoffCarrier(side);
        spell = null;
        possession = side;
        phase = "BUILD_UP";
        setBallTarget(50, 50, 0.38, false);
        // Send every outfield player back toward their own formation shape —
        // previously only the ball recentred, so the restart resumed with
        // whoever was still upfield/out wide from the previous attack still
        // there. Give them a sprint boost and enough real time to get home
        // before kickoff, instead of the old near-instant handoff.
        // Engine fix — kickoff law (both teams stay in their own half until
        // the ball is in play): this sent everyone straight to their raw
        // formation baseDepth, which for advanced roles (ST/W/AM, often
        // 0.56-0.64) is already past the halfway line into the opponent's
        // half. Clamp everyone to their own half for the restart itself.
        // lockUntil must survive past the kickoff (matchMinute + 1.3, when
        // pendingKickoffCarrier actually puts the ball live) — updateTeamShape
        // skips any pin with lockUntil > matchMinute (line ~4728), so leaving
        // this at 0 let the very next decision tick immediately recompute
        // each pin's normal (unclamped) formation depth and overwrite the
        // clamp before the restart ever happened.
        for (const pin of allPins) {
          const kickoffDepth = Math.min(pin.baseDepth, 0.46);
          const pct = toPitchPct(pin.side, pin.baseX, kickoffDepth);
          pin.tx = pct.left;
          pin.ty = pct.top;
          pin._pathCtrl = null;
          pin.lockUntil = matchMinute + 1.3;
          pin._running = true;
          pin._pressing = false;
        }
        pendingKickoffCarrier = { pin: c, at: matchMinute + 1.3 };
        actionTimer = 1.35;
        return;
      }
      if (pendingKickoffCarrier && matchMinute >= pendingKickoffCarrier.at && ballTween >= 1 && !ballFlight) {
        const c = pendingKickoffCarrier.pin;
        pendingKickoffCarrier = null;
        giveBall(c, `${c.short} restarts`);
        actionTimer = 0.85;
      }
      if (pendingClear && matchMinute >= pendingClear.at && ballTween >= 1 && !ballFlight) {
        const from = pinById.get(pendingClear.fromId);
        const to = pinById.get(pendingClear.toId);
        pendingClear = null;
        if (from && to && carrierId === from.id) doPass(from, to, "clear");
      }
      // Set-piece Phase 0/1 — drain exactly like the three restart flags
      // above: wait for the short "ball freezes at the exit point" tween
      // dispatchBallTarget already kicked off to finish, then hand off to
      // the matching resolver. Corners/goal kicks reuse the EXISTING
      // resolveCorner (unmodified) — this only gives it a new caller for
      // open-play exits, not a reimplementation — plus a minimal new
      // resolveGoalKick (its necessary counterpart; not a named phase in
      // the spec, kept deliberately as simple as throw-ins).
      if (pendingSetPiece && matchMinute >= pendingSetPiece.at && ballTween >= 1 && !ballFlight) {
        const sp = pendingSetPiece;
        pendingSetPiece = null;
        if (sp.type === "throw_in") {
          resolveThrowIn(sp.side, sp.left, sp.top);
        } else if (sp.type === "corner") {
          oobStats.cornersGenerated++;
          resolveCorner(sp.side);
        } else if (sp.type === "goal_kick") {
          oobStats.goalKicksGenerated++;
          resolveGoalKick(sp.side);
        }
        return;
      }
    }

    function pinsOf(side) {
      return side === "home" ? homePins : awayPins;
    }

    function oppOf(side) {
      return side === "home" ? "away" : "home";
    }

    function findCarrier() {
      return pinById.get(carrierId) || null;
    }

    function instrBias(side) {
      const until = side === "home" ? instrHomeUntil : instrAwayUntil;
      if (matchMinute > until) return 0;
      return side === "home" ? instrHome : instrAway;
    }

    function favorPin(pin) {
      favoredId = pin.id;
      pin.favorUntil = matchMinute + 8;
      allPins.forEach((p) => {
        const el = pinEls.get(p.id);
        if (el) el.classList.toggle("favored", p.id === pin.id);
      });
      say(`Favoring ${pin.short}`, 1.2);
      if (possession === pin.side && findCarrier() && findCarrier().id !== pin.id && rng() < 0.55) {
        doPass(findCarrier(), pin, "pass");
      }
    }

    function setInstruction(side, mode) {
      const bias = mode === "push" ? 1 : -1;
      if (side === "home") {
        instrHome = bias;
        instrHomeUntil = matchMinute + 12;
      } else {
        instrAway = bias;
        instrAwayUntil = matchMinute + 12;
      }
      say(`${side === "home" ? homeTeam.name : awayTeam.name} ${mode === "push" ? "push forward" : "sit deep"}`, 1.5);
    }

    function triggerZoneSwitch(left, top) {
      const carrier = findCarrier();
      if (!carrier || actionTimer > 0.15) return;
      const mates = teammates(carrier);
      if (!mates.length) return;
      let best = mates[0];
      let bestD = Infinity;
      for (const m of mates) {
        const d = Math.hypot(m.left - left, m.top - top);
        if (d < bestD) {
          bestD = d;
          best = m;
        }
      }
      doPass(carrier, best, Math.abs(best.left - carrier.left) > 28 ? "switch" : "pass");
    }

    function pickKickoffCarrier(side) {
      const pins = pinsOf(side);
      return (
        pins.find((p) => p.role === "ST") ||
        pins.find((p) => p.role === "AM" || p.role === "CM") ||
        pins[Math.floor(pins.length / 2)]
      );
    }

    function nearestOpponent(pin, maxDist) {
      const opp = pinsOf(oppOf(pin.side));
      let best = null;
      let bestD = Infinity;
      for (const o of opp) {
        if (o.role === "GK") continue;
        const d = dist(pin, o);
        if (d < bestD) {
          bestD = d;
          best = o;
        }
      }
      if (best && bestD <= (maxDist ?? 14)) return { pin: best, d: bestD };
      return null;
    }

    function nearestOpponents(pin, maxDist, n) {
      const opp = pinsOf(oppOf(pin.side))
        .filter((o) => o.role !== "GK")
        .map((o) => ({ pin: o, d: dist(pin, o) }))
        .filter((o) => o.d <= (maxDist ?? 16))
        .sort((a, b) => a.d - b.d);
      return opp.slice(0, n ?? 2);
    }

    /**
     * Engine rebuild Phase 1 — continuous pressure field. Real defensive heat
     * at a pitch position, summed from every nearby opponent's actual
     * position (not a per-team constant), so a covering second defender who
     * isn't the single nearest one still counts. This is what a genuine
     * 1v1/2v1 duel should be contested against instead of a static
     * team-wide press/resist scalar computed once at kickoff.
     */
    const PRESSURE_RADIUS = 10;
    function pressureAt(x, y, side) {
      const opponents = pinsOf(oppOf(side));
      let total = 0;
      for (const opp of opponents) {
        if (opp.role === "GK") continue;
        const d = dist({ left: x, top: y }, opp);
        if (d >= PRESSURE_RADIUS) continue;
        const proximity = 1 - d / PRESSURE_RADIUS;
        const closing = opp._pressing || opp._running ? 1.2 : 1;

        // Role-based pressure multiplier: DM/CM apply different defensive weight
        const defMod = defensiveArchetypeModifiers(opp);
        const rolePressureMultiplier =
          opp.role === "DM" ? 1.3 :
          opp.role === "CM" ? 1.1 :
          opp.role === "CB" ? 1.2 :
          opp.role === "FB" ? 1.0 :
          0.75; // W, AM, ST

        // Defensive quality: tackles + interceptions, scaled by archetype
        const defArchetype = computeDefensiveArchetype(opp);
        const quality =
          0.4 +
          (opp.stats.tackles90 || 0) * 0.08 * defMod.pressureMultiplier +
          (opp.stats.interceptions90 || 0) * 0.04 * defMod.laneControlStrength +
          (opp.stats.ball_recoveries90 || 0) * 0.02;

        // Clearance bonus for defensive line
        const clearanceBonus =
          opp.role === "CB" || opp.role === "FB" ? (opp.stats.clearances90 || 0) * 0.02 : 0;

        // Centrality bonus: DM/CM exert more pressure centrally (x: 40-60)
        const centralityDistance = Math.abs(opp.left - 50);
        const centralityBonus =
          (opp.role === "DM" || opp.role === "CM") ?
            Math.max(0, 1 - centralityDistance / 20) * 0.08 : 0;

        total +=
          proximity * proximity *
          closing *
          (quality + clearanceBonus + centralityBonus) *
          rolePressureMultiplier;
      }
      // Phase 3: Defensive shape exposure reduces pressure in exposed zones
      // When defenders have stepped out and lost duels, the zones they exposed have less pressure
      if (defensiveShapeExposure && defensiveShapeExposure[oppOf(side)]) {
        const exposure = defensiveShapeExposure[oppOf(side)];
        const isCentral = x >= 40 && x <= 60;
        const isWide = x < 40 || x > 60;
        if (isCentral && exposure.central > 0) {
          total *= (1 - exposure.central * 0.4); // Up to 40% reduction in central zone
        } else if (isWide && exposure.wide > 0) {
          total *= (1 - exposure.wide * 0.4); // Up to 40% reduction in wide zones
        }
      }
      return total;
    }

    /**
     * Per-action scoring project, Phase B — promoted out of pickAttackPattern
     * (it lived there as a private closure over `carrier`, unusable
     * elsewhere). Openness (0-1-ish, `1/(1+pressureAt)`) of a side-relative
     * target zone (zx/zd in 0-1 attacking-direction space, same convention
     * as fromPitchPct/toPitchPct) for the given side — "how open is this
     * specific patch of pitch right now," independent of who's currently on
     * the ball. Reused by scoreCarry/scoreSwitch below and still by
     * pickAttackPattern itself (now passing `carrier.side` explicitly
     * instead of closing over `carrier`).
     */
    function zoneOpenness(side, zx, zd) {
      const pct = toPitchPct(side, clamp(zx, 0.04, 0.96), clamp(zd, 0.04, 0.96));
      return 1 / (1 + pressureAt(pct.left, pct.top, side));
    }

    /** Shared by executeAttackPattern's pressure-adaptive method ordering
     * (wide_switch/wing_carry/cut_inside/central each pick between two
     * hand-written try-order arrays off this same threshold). */
    function isUnderPressure(carrier) {
      return pressureAt(carrier.left, carrier.top, carrier.side) > 0.5;
    }

    /** Try each method in order until one reports success. */
    function tryInOrder(methods) {
      for (const attempt of methods) {
        if (attempt()) return true;
      }
      return false;
    }

    /**
     * Engine rebuild — real aerial-duel presence, replacing the static
     * sideAerial/strikerAerialThreat squad-wide scalars in the cross/header
     * contest. Same shape as pressureAt (proximity²-weighted sum over every
     * nearby player, not just the single nearest one), but weighted by
     * aerial ability instead of tackling — a header contest is decided by
     * who's actually in the box jumping, not by a team-wide averaged rating
     * with no positional signal at all.
     */
    const AERIAL_RADIUS = 12;
    function boxAerialPresence(x, y, side, excludeId) {
      let total = 0;
      for (const p of pinsOf(side)) {
        if (p.role === "GK" || p.id === excludeId) continue;
        const d = dist({ left: x, top: y }, p);
        if (d >= AERIAL_RADIUS) continue;
        const proximity = 1 - d / AERIAL_RADIUS;
        const ability = 0.35 + (p.stats.aerials_won90 || 0) * 0.09 * Math.max(0.4, (p.stats.aerials_won_pct || 50) / 100);
        total += proximity * proximity * ability;
      }
      return total;
    }

    function teammates(pin) {
      return pinsOf(pin.side).filter((p) => p.id !== pin.id && p.role !== "GK");
    }

    /**
     * Engine rebuild — persistent player intent. ChatGPT's follow-up
     * critique on the earlier rebuild: recomputing a role's behavioral goal
     * every single tick (as the old winger touchline/half-space hysteresis
     * and _supportRole both did) lets it flicker between options that are
     * only marginally different in score — an indecisive player. Intent is
     * drawn from a small per-role menu and *held* for a few sim-seconds,
     * re-drawn only once it expires. Space evaluation (scoreOpenSpace,
     * pressureAt) still decides HOW to serve the intent within each role's
     * positioning branch — it no longer decides WHETHER to have one.
     */
    const INTENT_MENUS = {
      W: ["stretch", "attack_gap", "underlap"],
      FB: ["overlap", "hold_width", "tuck_support"],
      AM: ["attack_gap", "support", "back_post", "box_crash"],
      ST: ["pin_last_line", "drop_short", "far_post"],
      // Engine fix — CM previously had no box_crash option at all, and every
      // other CM intent is depth-capped below the inPenaltyBox() threshold
      // (0.86) by construction (see BOX_OCCUPATION branch below). A real CM
      // does sometimes break forward into the box on a sustained attack, not
      // only the rare stat-defined "box_crashing_midfielder" archetype.
      CM: ["support", "progressive_run", "hold_width", "box_crash"],
      DM: ["screen", "support"],
    };
    const INTENT_WEIGHTS = {
      W: { central: [0.3, 0.45, 0.25], wide: [0.55, 0.3, 0.15] },
      FB: { central: [0.35, 0.35, 0.3], wide: [0.5, 0.3, 0.2] },
      // Engine fix — AM's 4th slot (box_crash) used to be 0 by default, i.e.
      // literally impossible to draw unless clinicalBoxThreat (an elite-
      // scorer-only signal) was already > 0 -- a normal playmaking AM could
      // never make a genuine box run regardless of match state. Given a
      // modest non-zero floor here instead; clinicalBoxThreat still boosts
      // it further on top of this floor for real finisher-type AMs.
      AM: { central: [0.36, 0.32, 0.2, 0.12], wide: [0.36, 0.32, 0.2, 0.12] },
      ST: { central: [0.5, 0.3, 0.2], wide: [0.5, 0.3, 0.2] },
      // Engine fix — same floor added for CM's new box_crash slot (see
      // INTENT_MENUS.CM above). Kept modest since this should still be the
      // exception, not the norm, for a CM's positioning.
      CM: { central: [0.35, 0.28, 0.22, 0.15], wide: [0.35, 0.28, 0.22, 0.15] },
      DM: { central: [0.55, 0.45], wide: [0.55, 0.45] },
    };

    /** Shared by ensureIntent's stat-driven weight boosts: steal `boost` worth
     * of probability mass for slot `idx`, shrinking every other slot
     * proportionally so the weights still sum the same. */
    function boostIntentSlot(weights, idx, boost) {
      if (idx < 0 || !(boost > 0)) return weights;
      const othersSum = weights.reduce((s, w, i) => (i === idx ? s : s + w), 0);
      const shrink = othersSum > 0 ? boost / othersSum : 0;
      return weights.map((w, i) => (i === idx ? w + boost : w * (1 - shrink)));
    }

    /**
     * Per-role map of {progress, score} intent-menu slot indices used by the
     * run-intelligence boost below — which intent represents "get on the
     * ball / make something happen" (progress) vs. "make the run that
     * actually arrives to score" (score) for that role.
     */
    const RUN_INTENT_SLOTS = {
      CM: { progress: 1, score: 3 }, // progressive_run, box_crash
      AM: { progress: 0, score: 3 }, // attack_gap, box_crash
      W: { progress: 1, score: 2 }, // attack_gap, underlap
      ST: { progress: 1, score: 2 }, // drop_short, far_post
    };

    function ensureIntent(pin, relBall, atkStage) {
      const menu = INTENT_MENUS[pin.role];
      if (!menu) return null;
      if (pin._intent && pin._intentUntil > matchMinute) {
        // Engine fix — faster intent cancellation. A held intent used to run
        // its full 1.0-2.2 minute window no matter what changed around it —
        // real players abandon an overlap/underlap the moment the picture
        // that justified it (a CB stepping out, pressure spiking or
        // collapsing at this exact spot) has genuinely shifted, not on a
        // fixed clock. Compares current pressureAt this pin's position
        // against what it was when the intent was set; a swing bigger than
        // one defender's worth of heat forces an early re-roll instead of
        // finishing a now-stale decision.
        const currentPressure = pressureAt(pin.left, pin.top, pin.side);
        const baseline = pin._intentSetPressure ?? currentPressure;
        if (Math.abs(currentPressure - baseline) <= 0.55) return pin._intent;
        pin._intent = null;
      }
      const central = Math.abs(relBall.x - 0.5) < 0.22;
      let weights = INTENT_WEIGHTS[pin.role][central ? "central" : "wide"];
      // Engine addition — clinical W/AM box entry. A wide player or AM whose
      // own finishing output earns a real clinicalBoxThreat steals
      // probability mass from their other intents toward the one that
      // actually targets the box zone ("underlap" for W, "box_crash" for
      // AM). 0 for a genuine creator, so this only ever redistributes away
      // from the default shape for players whose own stats justify it.
      const boxThreat = clinicalBoxThreat(pin);
      if (boxThreat > 0) {
        const boxIdx = pin.role === "W" ? 2 : pin.role === "AM" ? 3 : -1;
        weights = boostIntentSlot(weights, boxIdx, boxThreat * (pin.role === "W" ? 0.35 : 0.45));
      }
      // Engine addition — run-intelligence driven by real chain involvement,
      // per spec: xg_buildup90 makes a player more likely to make an
      // intelligent forward run during build-up/progression; xg_chain90
      // does the same in the final third / around the box; xg90 (actual
      // scoring output) specifically boosts the run that arrives to score,
      // not just the general "get on the ball" one. A player with none of
      // that involvement keeps today's plain role-based weights.
      const runSlots = RUN_INTENT_SLOTS[pin.role];
      if (runSlots) {
        const st = pin.stats || {};
        if (atkStage === "BUILD_UP" || atkStage === "PROGRESSING") {
          weights = boostIntentSlot(weights, runSlots.progress, clamp((st.xg_buildup90 || 0) * 0.5, 0, 0.45));
        } else if (atkStage === "FINAL_THIRD" || atkStage === "BOX_OCCUPATION" || atkStage === "CHANCE_CREATION") {
          weights = boostIntentSlot(weights, runSlots.progress, clamp((st.xg_chain90 || 0) * 0.4, 0, 0.4));
          weights = boostIntentSlot(weights, runSlots.score, clamp((st.xg90 || 0) * 0.55, 0, 0.45));
        }
      }
      const roll = rng();
      let acc = 0;
      let chosen = menu[menu.length - 1];
      for (let i = 0; i < menu.length; i++) {
        acc += weights[i];
        if (roll < acc) {
          chosen = menu[i];
          break;
        }
      }
      pin._intent = chosen;
      pin._intentSetPressure = pressureAt(pin.left, pin.top, pin.side);
      // Held for ~1.0-2.2 match-minutes (roughly 2-4.5 real seconds at the
      // default board speed) — long enough to read as a decision, not a
      // twitch, short enough to keep responding to how the game develops.
      // Can still be cancelled early above if the picture shifts hard.
      pin._intentUntil = matchMinute + 1.0 + rng() * 1.2;
      return chosen;
    }

    /**
     * Engine rebuild Phase 2 — off-ball space evaluation. Score a candidate
     * (x, depth) position for `pin` on how genuinely open it is right now:
     * real defensive pressure there (pressureAt, Phase 1), how clear the
     * passing lane from the current ball position would be (laneScore), and
     * whether a teammate is already crowding it. This is what should decide
     * between two off-ball spots instead of a sine wave of elapsed time.
     */
    function scoreOpenSpace(pin, x, depth) {
      const pct = toPitchPct(pin.side, x, depth);
      const pressure = pressureAt(pct.left, pct.top, pin.side);
      const openness = 1 / (1 + pressure);
      const lane = laneScore({ left: ball.left, top: ball.top, side: pin.side }, pct) / 3.6;
      let nearestMate = Infinity;
      for (const m of teammates(pin)) {
        const d = dist(pct, m);
        if (d < nearestMate) nearestMate = d;
      }
      const crowding = nearestMate < 6 ? -0.4 : nearestMate < 10 ? -0.15 : 0;
      return openness * 1.3 + lane + crowding;
    }

    /**
     * Experiment — continuous local optimization, ball carrier only. Not a
     * refactor: the target-based system (updateTeamShape's tx/ty, on the
     * DECISION_INTERVAL_MIN/MAX 0.22-0.48 match-minute cadence) is completely
     * untouched for all 21 other players and for this player the instant
     * they stop carrying. This answers one diagnostic question — does
     * replacing "steer toward a periodically-assigned target" with "every
     * frame, re-evaluate a small local neighborhood and drift toward
     * whichever nearby spot currently scores best" produce more lifelike
     * movement — using ONLY existing utility signals (scoreOpenSpace, which
     * already blends pressureAt/laneScore/teammate-crowding), plus a
     * progress term (REL depth is already 0=own goal/1=opponent's goal, so
     * candidateDepth - currentDepth IS "progress" with no extra heuristic)
     * and a momentum term (prefer candidates roughly in line with current
     * velocity, so the optimum doesn't zig-zag frame to frame). No new
     * tactical rules — same inputs already used everywhere else in the file.
     * Samples 12 points on a ring at ~2 pitch-% radius (a "couple of metres"
     * proxy) plus "stay exactly here", scores each, returns the best.
     *
     * Measured stable via a full-match instrumented run (108 carries):
     * 0 reversals, mean path efficiency 1.014 — see
     * docs/experiments/carrier-optimizer-prototype1.md. Leave as-is.
     */
    function optimizeCarrierPosition(pin) {
      const baseRel = fromPitchPct(pin.side, pin.left, pin.top);
      const radius = 2.2;
      const N = 12;
      const velMag = Math.hypot(pin.vx || 0, pin.vy || 0);
      const stayScore = scoreOpenSpace(pin, baseRel.x, baseRel.depth);
      let bestScore = stayScore;
      let bestLeft = pin.left;
      let bestTop = pin.top;
      for (let i = 0; i < N; i++) {
        const angle = (i / N) * Math.PI * 2;
        const candLeft = clamp(pin.left + Math.cos(angle) * radius, 2, 98);
        const candTop = clamp(pin.top + Math.sin(angle) * radius, 2, 98);
        const candRel = fromPitchPct(pin.side, candLeft, candTop);
        const space = scoreOpenSpace(pin, candRel.x, candRel.depth);
        const progress = (candRel.depth - baseRel.depth) * 1.4;
        const dx = candLeft - pin.left;
        const dy = candTop - pin.top;
        const moveMag = Math.hypot(dx, dy) || 1e-6;
        const momentum =
          velMag > 0.5 ? ((dx * pin.vx + dy * pin.vy) / (moveMag * velMag)) * 0.5 : 0;
        const score = space + progress + momentum;
        if (score > bestScore) {
          bestScore = score;
          bestLeft = candLeft;
          bestTop = candTop;
        }
      }
      return { left: bestLeft, top: bestTop };
    }

    function isMidRole(role) {
      return role === "DM" || role === "CM" || role === "AM";
    }

    function isDefRole(role) {
      return role === "CB" || role === "FB";
    }

    function isFwdRole(role) {
      return role === "ST" || role === "W";
    }

    /**
     * Elite attacker / creator score (Messi–Neymar calibre).
     * Uses board player signals: xG, xA, key passes, dribbles, shots.
     */
    function maestroScore(pin) {
      if (!pin || !pin.stats) return 0;
      const st = pin.stats;
      return (
        st.xg90 * 1.15 +
        st.xa90 * 1.4 +
        st.key_passes90 * 0.24 +
        st.dribbles90 * 0.2 +
        st.shots90 * 0.05
      );
    }

    /** True game-changer threshold — partial chance-volume exception on low-poss sides. */
    function isMaestroPin(pin) {
      if (!pin) return false;
      if (!(isFwdRole(pin.role) || pin.role === "AM" || pin.role === "CM")) return false;
      const st = pin.stats;
      const score = maestroScore(pin);
      return (
        score >= 1.05 ||
        st.xg90 >= 0.52 ||
        st.xa90 >= 0.38 ||
        (st.xg90 >= 0.38 && st.xa90 >= 0.22) ||
        (st.key_passes90 >= 2.4 && st.xa90 >= 0.28) ||
        (st.dribbles90 >= 3.2 && (st.xg90 >= 0.28 || st.xa90 >= 0.22))
      );
    }

    /** Top 1–2 maestros on a side; returns 0–0.28 partial offset (not full cancel). */
    function sideMaestroBoost(side) {
      const pool = pinsOf(side).filter(
        (p) => isFwdRole(p.role) || p.role === "AM" || p.role === "CM"
      );
      const maestros = pool
        .filter(isMaestroPin)
        .sort((a, b) => maestroScore(b) - maestroScore(a))
        .slice(0, 2);
      if (!maestros.length) return 0;
      let boost = 0;
      for (const p of maestros) {
        boost += clamp(0.1 + (maestroScore(p) - 1.0) * 0.12, 0.08, 0.18);
      }
      return clamp(boost, 0, 0.28);
    }

    /**
     * Norm: lower possession-control → fewer chance/shot attempts (soft, not absolute).
     * Floor stays high enough that a solid attack (~0.55+) still manufactures volume;
     * extreme possession mismatches no longer half-starve xG on their own.
     * Exception: 1–2 maestros partially offset the volume penalty.
     */
    function possChanceVolumeMul(side) {
      const delta = sidePoss(side) - sidePoss(oppOf(side));
      // Milder slope + higher floor (was 0.55× / 0.68) — avoid 2× xG gaps from poss alone.
      let mul = clamp(1 + delta * 0.38, 0.82, 1.12);
      if (delta < -0.04) {
        mul = clamp(mul + sideMaestroBoost(side) * 0.85, 0.82, 1.12);
      }
      // Solid attack / creation soft-lifts a low-poss side (not a maestro-only escape hatch).
      if (delta < -0.03) {
        const atkLift = clamp((sideAttack(side) - 0.48) * 0.22, 0, 0.08);
        const createLift = clamp((sideCreate(side) - 0.48) * 0.16, 0, 0.05);
        mul = clamp(mul + atkLift + createLift, 0.82, 1.12);
      }
      return mul;
    }

    /**
     * High possession ≠ always more xG: mute box conversion when opponent has
     * much stronger chance creation AND a strong defence / midfield shield.
     */
    function possessionSuppressionMul(side) {
      const possEdge = sidePoss(side) - sidePoss(oppOf(side));
      const createGap = sideCreate(oppOf(side)) - sideCreate(side);
      const oppShield = sideDefend(oppOf(side)) * 0.55 + sideMidDef(oppOf(side)) * 0.45;
      if (possEdge > 0.06 && createGap > 0.08 && oppShield > 0.52) {
        const strength = clamp(
          (possEdge - 0.06) * 1.15 + (createGap - 0.08) * 1.75 + (oppShield - 0.52) * 1.35,
          0,
          1
        );
        return clamp(1 - strength * 0.34, 0.66, 1);
      }
      return 1;
    }

    /** ST/W in the final third should progress, dribble, or shoot — not recycle back. */
    function forwardInFinalThird(carrier) {
      return Boolean(carrier && isFwdRole(carrier.role) && possessionDepth(carrier) >= 0.66);
    }

    // Engine fix — an overlapping FB who actually reaches the box/edge-of-box
    // had no equivalent of the above: decideWideFinalThird only zeroed its
    // recycle weight (and only routed to a forced shot/dribble/progress
    // action) for ST/W. An FB in that same genuinely dangerous position kept
    // a live, unconditional chance of picking "recycle" and then always
    // executed a sterile backPassTarget() pass — the exact "looks free on
    // goal, then suddenly back-passes" bug. FB isn't given forwardFinalThirdAction's
    // shot bias (unrealistic for a fullback); it should still fall through
    // to the existing cross/cutback choice instead of recycling.
    function fbDeepInBox(carrier) {
      return Boolean(carrier && carrier.role === "FB" && (inPenaltyBox(carrier) || nearPenaltyBox(carrier)));
    }

    function forwardFinalThirdAction(carrier) {
      if (!carrier) return false;
      const maestro = isMaestroPin(carrier);
      const shotFloor = maestro ? 0.12 : 0.18;
      if (
        inPenaltyBox(carrier) ||
        (nearPenaltyBox(carrier) && (carrier.stats.xg90 > shotFloor || rng() < (maestro ? 0.62 : 0.45)))
      ) {
        doShot(carrier, false);
        return true;
      }
      if (rng() < 0.42 + carrier.stats.dribbles90 * 0.1 + (maestro ? 0.12 : 0)) {
        doDribble(carrier);
        return true;
      }
      const prog = progressiveTarget(carrier);
      if (prog && prog.id !== carrier.id) {
        const creatorMod = creatorBehaviorModifiers(carrier);
        const passType = throughBallLegal(carrier, prog) && rng() < creatorMod.throughBallMultiplier ? "through" : "pass";
        doPass(carrier, prog, passType);
        return true;
      }
      doDribble(carrier);
      return true;
    }

    const POSS_ORDER = [
      "BUILD_UP",
      "PROGRESSING",
      "FINAL_THIRD",
      "BOX_OCCUPATION",
      "CHANCE_CREATION",
      "FINISH",
    ];

    function possIndex(stage) {
      const i = POSS_ORDER.indexOf(stage);
      return i >= 0 ? i : 0;
    }

    function dropPossessionState(steps) {
      if (!spell) return;
      const next = Math.max(0, possIndex(spell.stage) - Math.max(1, steps || 1));
      spell.stage = POSS_ORDER[next];
      phase = spell.stage;
      updatePhaseFromBall();
    }

    function flankOfPin(pin) {
      if (!pin) return "C";
      if (pin.baseX >= 0.58) return "R";
      if (pin.baseX <= 0.42) return "L";
      return "C";
    }

    function slotFlank(slot) {
      const s = String(slot || "").toUpperCase();
      if (/^(LB|LWB|LW|LM)/.test(s)) return "L";
      if (/^(RB|RWB|RW|RM)/.test(s)) return "R";
      if (/^CM3$/.test(s)) return "L";
      if (/^CM1$/.test(s)) return "R";
      return "C";
    }

    function pinFlank(pin) {
      const sf = slotFlank(pin.slot);
      if (sf !== "C") return sf;
      return flankOfPin(pin);
    }

    /** Flank link chain: W ↔ FB ↔ ST ↔ nearest CM (Priority 5). */
    function flankLinks(side, flank) {
      const pins = pinsOf(side);
      const preferX = flank === "R" ? 0.86 : flank === "L" ? 0.14 : 0.5;
      const onFlank = (p) => {
        const f = pinFlank(p);
        if (f === flank) return true;
        return flank !== "C" && Math.abs(p.baseX - preferX) < 0.32;
      };
      const pick = (role, prefer) => {
        const list = pins.filter((p) => p.role === role && onFlank(p));
        if (!list.length) {
          return (
            pins
              .filter((p) => p.role === role)
              .sort((a, b) => Math.abs(a.baseX - prefer) - Math.abs(b.baseX - prefer))[0] || null
          );
        }
        return list.sort((a, b) => Math.abs(a.baseX - prefer) - Math.abs(b.baseX - prefer))[0] || null;
      };
      const stPrefer = flank === "R" ? 0.62 : flank === "L" ? 0.38 : 0.5;
      const w = pick("W", preferX);
      const fb = pick("FB", preferX);
      const st =
        pins.filter((p) => p.role === "ST").sort((a, b) => Math.abs(a.baseX - stPrefer) - Math.abs(b.baseX - stPrefer))[0] ||
        null;
      const cms = pins.filter((p) => p.role === "CM" || p.role === "AM" || p.role === "DM");
      const anchorX = w?.baseX ?? fb?.baseX ?? preferX;
      const cm =
        cms.sort(
          (a, b) =>
            Math.abs(a.baseX - anchorX) -
            Math.abs(b.baseX - anchorX) +
            (a.role === "CM" ? -0.08 : a.role === "AM" ? -0.02 : 0.05)
        )[0] || null;
      return { w, fb, st, cm, flank };
    }

    function linkedOptions(carrier) {
      const flank = pinFlank(carrier);
      if (flank === "C") {
        const L = flankLinks(carrier.side, "L");
        const R = flankLinks(carrier.side, "R");
        return [L.w, R.w, L.fb, R.fb, L.cm, R.cm, L.st, R.st].filter((p) => p && p.id !== carrier.id);
      }
      const link = flankLinks(carrier.side, flank);
      const ordered = [];
      if (carrier.role === "W") {
        if (link.fb) ordered.push(link.fb);
        if (link.st) ordered.push(link.st);
        if (link.cm) ordered.push(link.cm);
      } else if (carrier.role === "FB") {
        if (link.w) ordered.push(link.w);
        if (link.cm) ordered.push(link.cm);
        if (link.st) ordered.push(link.st);
      } else if (carrier.role === "ST") {
        if (link.w) ordered.push(link.w);
        if (link.cm) ordered.push(link.cm);
        if (link.fb) ordered.push(link.fb);
      } else {
        if (link.w) ordered.push(link.w);
        if (link.fb) ordered.push(link.fb);
        if (link.st) ordered.push(link.st);
        if (link.cm && link.cm.id !== carrier.id) ordered.push(link.cm);
      }
      return ordered.filter(Boolean);
    }

    function countBoxAttackers(side) {
      return pinsOf(side).filter((p) => p.role !== "GK" && inPenaltyBox(p)).length;
    }

    function countArrivingRunners(side) {
      return pinsOf(side).filter((p) => {
        if (p.role === "GK" || inPenaltyBox(p)) return false;
        const running = p._running || p.lockUntil > matchMinute;
        if (!running) return false;
        const d = fromPitchPct(p.side, p.left, p.top).depth;
        if (d > 0.78) return true;
        // Bug fix — sequencing gap behind the box-arrival investigation:
        // this only ever credited a runner AFTER their own depth had
        // already crossed 0.78, but boxOccupationReady (the main consumer)
        // gets checked as part of the shoot/cross decision itself, not
        // after the fact — a runner genuinely underway and close to
        // arriving read as invisible right when it mattered. Look-ahead:
        // credit a runner heading toward a real box-depth target (their
        // own tx/ty, not current position) who is close enough to
        // genuinely get there soon — capped at ~0.4 match-minutes (0.8
        // sim-seconds) at their own top running speed (RUN_SPEED_PCT), not
        // an arbitrary distance. A runner just setting off from miles away
        // still correctly doesn't count.
        const targetDepth = fromPitchPct(p.side, p.tx, p.ty).depth;
        if (targetDepth <= 0.78) return false;
        const remaining = Math.hypot(p.tx - p.left, p.ty - p.top);
        const speed = RUN_SPEED_PCT[p.role] || 28;
        return remaining <= speed * 0.8;
      }).length;
    }

    /** 0–1.35 finishing threat from board signals (xg / shots / SOT / goals). */
    function finisherQuality(pin) {
      if (!pin || !pin.stats) return 0;
      const st = pin.stats;
      const sot = st.shots_on_target90 || st.shots90 * 0.4;
      const goals = st.goals90 || 0;
      return clamp(st.xg90 * 0.82 + st.shots90 * 0.055 + sot * 0.07 + goals * 0.12, 0, 1.35);
    }

    /**
     * 0-1 gate: how much a W/AM's own finishing output (finisherQuality,
     * goals90_percentile against this match's full player pool) earns them
     * extra box-entry tendency, on top of their default wide/pocket shape.
     * 0 for a genuine creator (Fàbregas/Xavi-tier, average-or-below scoring
     * rate) even if they're a good passer -- this only reacts to their own
     * finishing signal, same self-correcting design as isAttackFinisher.
     */
    function clinicalBoxThreat(pin) {
      if (!pin || (pin.role !== "W" && pin.role !== "AM")) return 0;
      const fq = finisherQuality(pin);
      const gPct = pin.stats.goals90_percentile ?? 0.5;
      return clamp((fq - 0.35) * 0.9 + (gPct - 0.55) * 1.1, 0, 1);
    }

    /**
     * Phase 1: Arrival detection. Track depth velocity (momentum toward goal)
     * and combine with intent flags to compute _arrivalStrength (0-1, how much
     * is this player actively moving into a scoring position right now).
     * Updated each tick during position calculations.
     */
    /**
     * Per-action scoring project — shared "how creative/good a passer is
     * this carrier" read, 0-0.4 (xa90/key_passes90/pass_pct). Used to weight
     * pass options UP (scoreDynamicReceiver) and carry/dribble options DOWN
     * (scoreCarry/scoreDribble) in progression/build-up specifically, per
     * user feedback: a genuinely creative player's best contribution there
     * is picking a pass, not running the ball himself. One shared read so
     * the three consumers can't drift apart the way scoreShot's predecessors
     * did (see scoreShot's own docstring).
     */
    function carrierCreativity(carrier) {
      return clamp(
        (carrier.stats.xa90 || 0) * 0.14 +
          (carrier.stats.key_passes90 || 0) * 0.05 +
          Math.max(0, (carrier.stats.pass_pct || 70) - 70) * 0.006,
        0,
        0.4
      );
    }

    /**
     * Phase 2: Open-space reader. Score each potential receiver on how good
     * a target they are RIGHT NOW: combines arrival momentum + real pressure
     * + finishing threat + distance + angle. Returns 0-1 value; highest score
     * in the pool is the best receiving option at this moment.
     */
    function scoreDynamicReceiver(carrier, candidate, stage, relBall) {
      if (!carrier || !candidate || candidate.id === carrier.id) return 0;
      if (candidate.role === "GK") return 0; // GK never receives

      // Base score from arrival momentum: a player genuinely moving into space is more valuable
      const arrivalScore = candidate._arrivalStrength ?? 0;

      // Pressure at candidate's current position: lower pressure = better target
      const pressure = pressureAt(candidate.left, candidate.top, candidate.side);
      const openness = 1 / (1 + pressure); // 0-1, higher = more open

      // Finishing threat: can this player actually do something with the ball?
      // For attackers (ST/W/AM), use finisher quality. For midfielders, use creative output.
      let finishingThreat = 0;
      if (candidate.role === "ST" || candidate.role === "W" || candidate.role === "AM") {
        finishingThreat = finisherQuality(candidate) * 1.2; // ST/W/AM finishing is primary threat
      } else if (candidate.role === "CM" || candidate.role === "DM") {
        // Midfielders: value their creative output + finishing upside (after archetype fix, CM/DM can finish)
        const creative = (candidate.stats.xa90 || 0) * 0.4;
        const cmFinish = finisherQuality(candidate) * 0.3; // secondary threat
        finishingThreat = creative + cmFinish;
      } else if (candidate.role === "FB") {
        // Fullbacks: overlapping + creating is the threat
        finishingThreat = fbAttackThreat(candidate) * 0.8;
      }
      finishingThreat = clamp(finishingThreat, 0, 1);

      // Distance penalty: closer targets are easier to pass to. Engine fix
      // — the previous version capped at 0.85 by dist=22 and was only
      // weighted ×0.1 in the final score below, so the maximum possible
      // penalty for ANY distance beyond 22 units — 30 away or 90 away,
      // identical — was ~0.085, negligible against finishingThreat/
      // arrivalScore/progression. That's the actual mechanism behind
      // unrealistic full-pitch passes (an RB finding the LW cross-field):
      // this function runs first in decideAction, ahead of the older
      // pattern-based passing code that already penalizes distance
      // properly, so a wide-open, well-statted candidate 80 units away
      // lost almost nothing for being that far. Uncapped past a realistic
      // range now. Also added below: a separate, role-agnostic lateral
      // term (the actual "difficulty of pass" this was missing) — a
      // straight forward ball and a full-width diagonal of the same raw
      // distance are very different passes in real football, and nothing
      // here distinguished them.
      const dist_to_candidate = dist(carrier, candidate);
      const lateral_to_candidate = Math.abs(carrier.left - candidate.left);
      const distPenalty =
        dist_to_candidate <= 22 ? clamp((dist_to_candidate - 5) / 20, 0, 0.85) : 0.85 + (dist_to_candidate - 22) * 0.045;
      const lateralPenalty = lateral_to_candidate > 24 ? (lateral_to_candidate - 24) * 0.035 : 0;

      // Passing lane: can we actually reach this player without interception?
      // (simplified: use laneScore from ball to candidate's position)
      const candidatePct = toPitchPct(candidate.side, candidate.left, candidate.top);
      const laneQuality = laneScore({ left: ball.left, top: ball.top, side: candidate.side }, candidatePct) / 3.6;

      // Bug fix — the objective of an attack is to threaten the opponent's
      // goal against real resistance; nothing here previously measured
      // whether a candidate is actually MORE ADVANCED than the carrier.
      // Flanks are structurally less congested than the centre/box (fewer
      // defenders per unit area out there), so a stationary wide option's
      // openness alone could consistently outscore a genuinely progressive
      // central option -- the direct cause of possession recycling along
      // the touchline (RW<->LW<->both wing-backs) instead of players
      // working the ball toward an actual attempt on goal. Reward real
      // advancement, penalize sideways/backward options unless they
      // clearly earn it on other axes.
      //
      // Engine fix — a backward pass used to be capped at the same -0.3
      // penalty regardless of context, so a striker at the box edge and a
      // CB near his own goal were treated identically for giving the ball
      // away backward. Giving up a genuinely dangerous position is far
      // worse than recycling from a harmless one; scale the penalty by how
      // advanced the carrier already is instead of a flat cap (this is
      // what let an unpressured deep fullback outscore a shot/forward
      // option when the carrier was already at the box edge).
      const depthDelta = possessionDepth(candidate) - possessionDepth(carrier);
      const progression =
        depthDelta >= 0
          ? clamp(depthDelta * 2.2, 0, 0.5)
          : clamp(depthDelta * (1.6 + possessionDepth(carrier) * 2.4), -1.1, 0);

      // Stage weighting: in box-occupation, finishing threat matters more. In build-up, arrival matters more.
      let stageWeight = 1.0;
      if (stage === "BOX_OCCUPATION" || stage === "FINISH") {
        stageWeight = 1.3; // finishing matters most
        finishingThreat *= 1.2;
      } else if (stage === "FINAL_THIRD") {
        stageWeight = 1.15;
      }

      // User feedback — in progression/build-up specifically, the CARRIER's
      // own passing/creativity should factor into how good a pass this is,
      // not just the receiver's threat profile above. A world-class
      // creative passer (high xa90/key_passes90/pass_pct) and a poor one
      // scored an identical pass to an identical receiver identically --
      // wrong, since the same forward ball is more likely to actually be
      // picked out by a genuinely creative player. Weighted heavily here
      // (a deep playmaker's distribution is what matters most during
      // progression/build-up), lighter in other stages where finishing
      // threat/arrival already dominate. See carrierCreativity's own
      // docstring above.
      const creativityWeight = stage === "PROGRESSING" || stage === "BUILD_UP" ? 0.3 : 0.12;

      // Combine all factors. distPenalty/lateralPenalty weighted high
      // enough that an extreme option (either axis) reliably outweighs the
      // ~1.05 max positive score, instead of the old ×0.1 that let it be
      // ignored entirely -- see the notes above.
      const score =
        arrivalScore * 0.28 +
        openness * 0.18 +
        finishingThreat * 0.22 +
        laneQuality * 0.12 +
        progression * 0.25 +
        carrierCreativity(carrier) * creativityWeight -
        distPenalty * 0.32 -
        lateralPenalty * 0.32;

      return clamp(score * stageWeight, 0, 1);
    }

    function findBestArrivingReceiver(carrier, stage, depth, minScore) {
      // Of all teammates, find the one with highest scoreDynamicReceiver()
      // Returns the candidate pin or null if no one scores above threshold.
      // minScore lets a caller demand a stronger option than the default
      // "worth considering at all" bar — see the Priority 1.45 pass-first
      // check above, which needs a genuinely good progressive option, not
      // just any technically-open teammate, before preferring it over a
      // deep player's own carry.
      if (!carrier || !stage) return null;

      const mates = teammates(carrier);
      if (!mates.length) return null;

      let best = null;
      let bestScore = minScore ?? 0.15; // threshold: must score above this to be considered a real option

      for (const m of mates) {
        // Never immediately return the ball to whoever just passed it to us --
        // the direct cause of the Yamal<->Diomande-style infinite through-ball
        // loop (see _lastPasserFrom note in resolveBallFlight).
        if (carrier._lastPasserFrom != null && m.id === carrier._lastPasserFrom) continue;
        let score = scoreDynamicReceiver(carrier, m, stage, { x: 0.5, depth }); // rough relBall
        // Bug fix — the single-passer exclusion above only breaks a 2-player
        // ping-pong; a small group (e.g. RW/LW/both full-backs) can still
        // carousel possession among themselves indefinitely since each
        // individual pass has a different immediate source. Reuse the same
        // lastReceivers memory scorePassingOption already relies on
        // elsewhere, damping (not banning -- legitimate recycling still
        // happens in real football) anyone who's touched the ball recently
        // in this spell.
        if (spell && spell.side === carrier.side && spell.lastReceivers && spell.lastReceivers.includes(m.id)) {
          score *= 0.55;
        }
        if (score > bestScore) {
          bestScore = score;
          best = m;
        }
      }

      return best;
    }

    /**
     * Per-action scoring project, Phase A — unified shot-quality score.
     * Real geometric angle (shotAngleQuality) gates the score
     * multiplicatively — a bad angle stays bad regardless of finishing
     * quality — scaled by the carrier's own finishing signal and reduced by
     * how tightly marked he is, plus a small bonus for general room at the
     * carrier's own position. Consolidates two formulas for the same real
     * question ("how good a shot is this, right now") that had drifted
     * apart with slightly different coefficients: evaluateArrivals's
     * wide-shooting-zone check and decideWideFinalThird's shootW. Returns
     * 0-0.75, usable directly as an rng() probability (evaluateArrivals) or
     * as a relative weight against cross/cutback/recycle (decideWideFinalThird).
     *
     * Deliberately NOT wired into evaluateArrivals's separate boxed/near-box
     * flat-probability shot check (canShoot/shootP) or cut_inside's
     * tryShootSeq — the former is a flat 0.82/0.62 roll with no angle
     * sensitivity at all (a real gap, but touching a high-frequency branch
     * is its own change, not a duplicate-formula cleanup); the latter is a
     * different kind of gate entirely (xg90/attackDefendDelta/urgency
     * driven, bundling a through-pass/progressive-pass/drive-into-box/shot
     * sequence, not a pure shot-quality check) — forcing this formula into
     * it wouldn't be de-duplication, it'd be a behavior change. Both are
     * left for the later phases of the unified-scoring project once the
     * whole action list is being compared on equal footing anyway.
     */
    function scoreShot(carrier) {
      const angleQ = shotAngleQuality(carrier);
      const fq = finisherQuality(carrier);
      const marker = nearestOpponent(carrier, 6);
      const contest = marker ? clamp(1 - marker.d / 6, 0, 1) : 0;
      const openness = 1 / (1 + pressureAt(carrier.left, carrier.top, carrier.side));
      return clamp((angleQ - 0.1) * 1.8 * (0.45 + fq * 0.9) + openness * 0.06 - contest * 0.32, 0, 0.75);
    }

    /**
     * Per-action scoring project, Phase B — "how good is it to just advance
     * the ball myself into open space right now," 0-0.6. Reuses the exact
     * openness/isolation read evaluateArrivals's `trulyIsolated` branch
     * already used (no real threat within 10, real room at the carrier's
     * own position), as a continuous score instead of a gated all-or-
     * nothing check.
     *
     * Bug fix (found in Phase C's first real test, not Phase B's own
     * unit-style checks — flagging the gap) — first cut of this scaled
     * openness alone up to a 0.92 ceiling. Measured head-to-head against
     * scoreDynamicReceiver/scoreShot in a real match: openness runs
     * systematically high across most of the pitch (defenders are sparse
     * away from the ball), so this carried roughly DOUBLE pass/shoot's
     * typical realistic score (median 0.65 vs. 0.36/0.26) — dribble/carry
     * won almost every comparison by scale, not genuine situational
     * superiority (shot count collapsed 6-12 -> ~2/match in testing).
     * Rescaled down and folded in a real depth/value term — advancing the
     * ball yourself is worth more from a genuinely dangerous position than
     * from inside your own half, the same kind of progression-value signal
     * scoreDynamicReceiver already has and this didn't.
     *
     * User feedback — a genuinely creative carrier (high carrierCreativity)
     * should be relatively less inclined to just run it himself during
     * progression/build-up, where his passing is the more valuable
     * contribution; discounted, not zeroed, so a truly open runway still
     * wins for anyone. `stage` is optional — omitted, this behaves exactly
     * as the plain openness/depth score (e.g. for a caller outside the
     * progression/build-up context that doesn't track stage).
     */
    function scoreCarry(carrier, stage) {
      const threat = nearestOpponent(carrier, 10);
      const openness = 1 / (1 + pressureAt(carrier.left, carrier.top, carrier.side));
      const depth = possessionDepth(carrier);
      if (depth < 0.1 || (threat && threat.d < 7 && openness <= 0.55)) return 0;
      const score = clamp(openness * 0.4 * (0.55 + depth * 0.6), 0, 0.48);
      const discountWeight = stage === "PROGRESSING" || stage === "BUILD_UP" ? 0.6 : 0.2;
      return clamp(score * (1 - carrierCreativity(carrier) * discountWeight), 0, 0.48);
    }

    /**
     * Per-action scoring project, Phase B — "how good a take-on is this,
     * right now," 0-0.55. Originally reused the exact attacker-vs-marker
     * duel math evaluateArrivals's Priority 1.6 take-on check used
     * (dribbles90/dribble_pct vs. the marker's tackles90/duels_won_pct),
     * as a continuous score.
     *
     * Bug fix (found via the 100-match real-squad player study, not the
     * earlier generic-squad Phase B/C testing — flagging the gap) — the
     * original 0.14 dribbles90 coefficient and 0.68 ceiling were carried
     * over unchanged from the old system, where this score was only ever
     * used as `rng() < takeOnP` (a per-attempt probability, fine for a
     * genuine specialist to hit 68% often). Once compared directly against
     * pass/shoot/carry in Phase C's real argmax, that ceiling turned out to
     * be a near-constant for any real elite dribbler: Doku/Hazard/Diomandé
     * (dribbles90 5.3/3.0/4.0) all hit 0.68 against a COMPLETELY AVERAGE
     * marker, regardless of actual matchup quality — measured directly:
     * 100-match sample had these three resolving 83-86% of every touch as
     * a dribble, far beyond any other position (CBs 12-17%). Generic
     * ROLE_GENERIC squads never surfaced this because nothing in that pool
     * has anywhere near a real specialist's dribbles90. Rescaled down and
     * softened the dribbles90 sensitivity so an elite dribbler still gets a
     * real, meaningful edge against a weak marker (~0.47 vs a decent pass's
     * ~0.3) without systematically dominating against an average one
     * (~0.4) or a tough one (~0.15-0.21, where passing should clearly win).
     * Distinct from scoreCarry above: this is for a genuine 1v1/1v2 with a
     * marker close enough to actually challenge, not open space with
     * nobody around.
     *
     * Same carrierCreativity discount as scoreCarry, same reasoning
     * (per user feedback) — a creative playmaker should generally look to
     * release the ball rather than dribble through traffic during
     * progression/build-up.
     */
    function scoreDribble(carrier, stage) {
      const markers = nearestOpponents(carrier, 8, 2);
      const marker = markers[0];
      if (!marker || marker.d < 1.4) return 0;
      let attackerEdge =
        (carrier.stats.dribbles90 || 0) * 0.05 +
        Math.max(0, (carrier.stats.dribble_pct || 50) - 50) * 0.006 -
        (marker.pin.stats.tackles90 || 0) * 0.09 -
        Math.max(0, (marker.pin.stats.duels_won_pct || 50) - 50) * 0.006;
      const second = markers[1];
      if (second) {
        attackerEdge -= (second.pin.stats.tackles90 || 0) * 0.05 + 0.04;
      }
      const score = clamp(0.2 + attackerEdge, 0.05, 0.55);
      const discountWeight = stage === "PROGRESSING" || stage === "BUILD_UP" ? 0.6 : 0.2;
      return clamp(score * (1 - carrierCreativity(carrier) * discountWeight), 0.03, 0.55);
    }

    /**
     * Per-action scoring project, Phase B — "how good is switching play to
     * this specific teammate right now," 0-0.95. Generalizes the boolean
     * isJustifiedSwitch + longBallDifficulty ceiling (currently only used
     * inside wide_switch's tryFarSwitch) into a continuous score: not a
     * genuine cross-field situation, or beyond the same 2.3 difficulty
     * ceiling longBallTarget/tryFarSwitch already use, scores 0; an
     * unjustified-but-plausible switch is heavily discounted rather than
     * hard-zeroed, so a real scored comparison downstream isn't just
     * re-implementing another boolean gate. Additive only this phase.
     */
    function scoreSwitch(carrier, target) {
      if (!target || !isCrossFieldSwitch(carrier, target)) return 0;
      const difficulty = longBallDifficulty(carrier, target);
      if (difficulty > 2.3) return 0;
      const justified = isJustifiedSwitch(carrier, target);
      const farEdge = flankMatchupEdge(carrier.side, pinFlank(target));
      const threatValue = (target.stats.xg90 || 0) * 0.5 + (target.stats.xa90 || 0) * 0.6;
      const base = clamp(
        0.35 + Math.max(0, farEdge) * 0.6 + threatValue * 0.4 - (difficulty - 1) * 0.22,
        0,
        0.95
      );
      return justified ? base : base * 0.25;
    }

    /**
     * Per-action scoring project, Phase C — true unified argmax, replacing
     * the priority-ordered early-return ladder this function used to be
     * (shoot checked and returned before pass was even scored, so a great
     * pass could never beat a mediocre shot; a beaten winger's dribble
     * option was buried behind several earlier gates). Build every real
     * candidate action (shoot/pass/dribble-or-carry), score them on a
     * comparable 0-1ish scale via the shared scorers (scoreShot, Phase A;
     * scoreDynamicReceiver via findBestArrivingReceiver; scoreCarry/
     * scoreDribble, Phase B), and pick via nearOptimalPick — the same
     * "weighted draw among near-tied top scorers" primitive
     * decideWideFinalThird/decideFbWingLink already use correctly, so a
     * genuinely much better option always wins but near-ties still get
     * realistic variety.
     *
     * Continuity (not flip-flopping cross/dribble every tick) is now an
     * ADDITIVE nudge on spell.lastActionType/actionContinuityConfidence
     * (see beginSpell) instead of a hard-locked category — same decay
     * numbers refreshSpellPattern already uses for spell.pattern (-15/
     * action, invalidated by a real pressure spike since the action was
     * picked), just applied as a score term so continuity can never block a
     * genuinely better option, only tip a close call.
     *
     * Returns: { type: 'pass', target } | { type: 'dribble' } | { type: 'shoot' } | { type: 'recycle' }
     */
    function evaluateArrivals(carrier, stage, depth) {
      if (!carrier || !stage) return { type: "recycle" };

      const boxed = inPenaltyBox(carrier);
      const nearBox = !boxed && nearPenaltyBox(carrier);
      const dribblePressure = pressureAt(carrier.left, carrier.top, carrier.side);
      const dribbleOpenness = 1 / (1 + dribblePressure);

      // Bug fix (found via the winger-dribble recalibration follow-up) —
      // 0.08 was meant as a gentle "don't flip-flop" nudge, but measured
      // directly against real score gaps: a wide fullback's carry and pass
      // scores often land within ~0.005-0.03 of each other (e.g. Dimarco:
      // avg scoreCarry 0.247 vs. avg pass score 0.242, nearly a coin flip),
      // so an 0.08 bonus is 3-15x the actual gap it's supposed to be a
      // nudge on top of — whichever option wins the FIRST touch of a spell
      // (a near-tie, decided by nearOptimalPick's small random draw) then
      // self-reinforces almost every subsequent touch until confidence
      // decays out, turning a genuine coin flip into 177/180 (98%) one way
      // for an entire match sample. Cut to a size that can still break a
      // literal tie but can't single-handedly override a real difference
      // between two otherwise-comparable options.
      let continuityBonus = 0;
      if (spell && spell.lastActionType) {
        const spiked =
          spell.actionContinuityBaselinePressure != null &&
          dribblePressure > spell.actionContinuityBaselinePressure + 0.6;
        if (!spiked) {
          continuityBonus = 0.025 * ((spell.actionContinuityConfidence ?? 100) / 100);
        }
      }

      const candidates = [];

      // Shoot — eligible when genuinely boxed/near-box (isWideShootingZone
      // deliberately excludes those, see its own docstring) or a real wide-
      // angle attempt. Bug fix (folded in here) — the boxed case used to be
      // a flat 0.82/0.62 roll with ZERO angle sensitivity, unlike the
      // wide-zone case; a bad-angle box shot got the same odds as a clean
      // one. One shared score now for both.
      if ((boxed || nearBox || isWideShootingZone(carrier)) && isAttackFinisher(carrier)) {
        let score = scoreShot(carrier);
        if (spell?.lastActionType === "shoot") score += continuityBonus;
        candidates.push({ type: "shoot", score, target: null });
      }

      // Pass — best real receiver right now. The old CB/FB/DM-specific
      // pass-first pre-empt (a workaround for the priority-order bug: those
      // roles' own carry/dribble checks used to fire before the receiver
      // search ever ran) isn't needed anymore — real scoring below already
      // has a creative deep player's carry/dribble score discounted
      // (carrierCreativity) and a flatter role-level distribution
      // preference (distributorRole below) for a less creative one, so a
      // genuinely good pass wins on its own merits instead of by pre-empt.
      const bestReceiver = findBestArrivingReceiver(carrier, stage, depth, 0.05);
      if (bestReceiver) {
        let score = scoreDynamicReceiver(carrier, bestReceiver, stage, { x: 0.5, depth });
        if (spell?.lastActionType === "pass" && spell.lastActionTargetId === bestReceiver.id) {
          score += continuityBonus;
        }
        candidates.push({ type: "pass", score, target: bestReceiver });
      }

      // Dribble/carry — one candidate covering both real situations
      // (open-space advance vs. a genuine take-on against a close marker):
      // doDribble already resolves which one actually happens internally
      // via its own threat check, so evaluateArrivals only ever needed one
      // "dribble" return type either way. Takes whichever framing scores
      // better right now. Bug fix (folded in here) — the old code gated
      // the take-on check to specific stages/roles (FINAL_THIRD/
      // BOX_OCCUPATION/near-box/advanced-attacking-role); scoreDribble's
      // own marker-proximity requirement is a real enough gate on its own,
      // so a genuine 1v1 anywhere on the pitch can now compete honestly
      // instead of being architecturally unavailable outside those states.
      const distributorRole = carrier.role === "CB" || carrier.role === "FB" || carrier.role === "DM";
      const carryMult = distributorRole ? 0.72 : 1;
      const dribbleScore = Math.max(scoreCarry(carrier, stage), scoreDribble(carrier, stage)) * carryMult;
      if (dribbleScore > 0) {
        let score = dribbleScore;
        if (spell?.lastActionType === "dribble") score += continuityBonus;
        candidates.push({ type: "dribble", score, target: null });
      }

      if (candidates.length) {
        candidates.sort((a, b) => b.score - a.score);
        const winner = nearOptimalPick(candidates, confidenceMargin(carrier, 0.1));
        if (spell) {
          const sameAsLast =
            spell.lastActionType === winner.type &&
            (winner.type !== "pass" || spell.lastActionTargetId === winner.target?.id);
          if (sameAsLast) {
            spell.actionContinuityConfidence = Math.max(0, (spell.actionContinuityConfidence ?? 100) - 15);
          } else {
            spell.actionContinuityConfidence = 100;
            spell.actionContinuityBaselinePressure = dribblePressure;
          }
          spell.lastActionType = winner.type;
          spell.lastActionTargetId = winner.type === "pass" ? winner.target.id : null;
        }
        // Below this bar the "winning" candidate still isn't really worth
        // doing (e.g. the only entry was a barely-above-zero pass) —
        // fall through to hold-up play / recycle instead of forcing it.
        if (winner.score > 0.08) {
          if (winner.type === "shoot") return { type: "shoot" };
          if (winner.type === "pass") return { type: "pass", target: winner.target };
          return { type: "dribble" };
        }
      }

      // Hold-up play. Nothing scored meaningfully above: no shot, no
      // decent receiver, no real dribble/carry opportunity. Real football's
      // answer here isn't always "recycle backward" — a composed carrier
      // reads that a teammate COULD be dangerous a beat from now and holds
      // the ball to let that develop, instead of only ever reacting to a
      // run that's already happening. throughBallLegal (used by
      // throughRunner elsewhere) requires the runner to already be
      // _running — nothing in the engine ever started that run on the
      // carrier's behalf. This cues it: pick a genuine runner, send them,
      // and have the carrier shield the ball for this tick so the next
      // decision (a beat later) can find them legally through. Chance of
      // even recognizing the moment scales with the carrier's own vision
      // (xa90/key_passes90), same signal confidenceMargin uses.
      if (depth >= 0.4 && dribbleOpenness > 0.32) {
        const vision = clamp((carrier.stats.xa90 || 0) * 0.6 + (carrier.stats.key_passes90 || 0) * 0.15, 0, 1);
        if (rng() < clamp(0.22 + vision * 0.45, 0.15, 0.62)) {
          const cued = cueThroughRun(carrier, stage, depth);
          if (cued) {
            return { type: "dribble" };
          }
        }
      }

      return { type: "recycle" };
    }

    /**
     * Sends the best-positioned forward on a run in behind, for a carrier
     * who's holding the ball up rather than releasing immediately (see
     * Priority 3.5 above). This is what makes hold-up play actually work:
     * throughBallLegal only ever recognized a run already in progress,
     * nothing initiated one. Targets the space just onside of the real
     * offside line, in the runner's current channel, so the very next
     * throughRunner check (a tick later) finds a legal, live option.
     */
    function cueThroughRun(carrier, stage, depth) {
      const candidates = teammates(carrier)
        .filter((m) => (m.role === "ST" || m.role === "AM" || m.role === "W") && m.id !== carrier.id)
        .filter((m) => !m._running && !(m.lockUntil > matchMinute))
        .filter((m) => canPlayForward(carrier, m, stage, depth));
      if (!candidates.length) return null;

      let best = null;
      let bestScore = -Infinity;
      for (const m of candidates) {
        const mRel = fromPitchPct(m.side, m.left, m.top);
        const score =
          (m.stats.xg90 || 0) * 1.3 + (m.stats.xa90 || 0) * 0.4 - Math.abs(mRel.x - 0.5) * 0.2 + rng() * 0.3;
        if (score > bestScore) {
          bestScore = score;
          best = m;
        }
      }
      if (!best) return null;

      const bestRel = fromPitchPct(best.side, best.left, best.top);
      const line = defendingOffsideLine(best.side);
      const runDepth = clamp(line - 0.03, bestRel.depth + 0.06, 0.9);
      const runX = clamp(bestRel.x, 0.15, 0.85);
      const pct = toPitchPct(best.side, runX, runDepth);
      best.tx = pct.left;
      best.ty = pct.top;
      best.lockUntil = matchMinute + 0.9;
      best._running = true;
      return best;
    }

    function updateArrivalStrength(pin, newDepth, stage, side) {
      if (!pin || !stage) return;
      // Initialize depth history on first call
      if (!pin._depthHistory) {
        pin._depthHistory = [newDepth, newDepth, newDepth];
        pin._prevDepth = newDepth;
      }
      // Shift history and add new depth
      pin._depthHistory[0] = pin._depthHistory[1];
      pin._depthHistory[1] = pin._depthHistory[2];
      pin._depthHistory[2] = newDepth;

      const prev2 = pin._depthHistory[0];
      const prev1 = pin._depthHistory[1];
      const curr = pin._depthHistory[2];

      // Depth velocity: trend over last 2 ticks (moving toward goal = positive)
      const vel1 = curr - prev1; // most recent tick
      const vel2 = prev1 - prev2; // previous tick
      const depthVelocity = (vel1 + vel2) * 0.5; // average

      // Base arrival strength from depth velocity
      // Moving forward (toward goal/box) = high; static or retreating = low
      let arrivalStrength = clamp(depthVelocity * 8, 0, 1); // scaled so 0.125 depth/tick = 1.0

      // Boost if player has _running flag (intent-driven forward movement)
      if (pin._running) {
        arrivalStrength = Math.max(arrivalStrength, 0.6);
      }

      // Boost if FB overlapping (explicit arrival signal)
      if (pin.role === "FB" && pin._overlapRun) {
        arrivalStrength = Math.max(arrivalStrength, 0.7);
      }

      // In attacking final third/box occupation stages, arrival is more relevant
      if (stage === "FINAL_THIRD" || stage === "BOX_OCCUPATION") {
        arrivalStrength *= 1.15;
      }

      pin._arrivalStrength = clamp(arrivalStrength, 0, 1);
    }

    function isAttackFinisher(pin) {
      // Engine addition — goal-scoring midfielder archetype. Widened from
      // ST/W/AM to also include CM/DM so a real box-to-box scoring
      // midfielder (Lampard/Gerrard) gets the same finisher-tier
      // conversion math (organicWillScore's xgW/shW/goalsW/clinical/
      // eliteBoost terms) their own real xg90/shots90/goals90 earn --
      // previously those stats were structurally inert for any CM/DM no
      // matter how elevated. A genuine passer (Xavi/Iniesta-tier, low
      // xg90) still converts poorly regardless, since the formula stays
      // multiplicative on their own stats -- this only unlocks the
      // *quality* of treatment, not a free boost.
      return Boolean(
        pin && (pin.role === "ST" || pin.role === "W" || pin.role === "AM" || pin.role === "CM" || pin.role === "DM")
      );
    }

    /** A real-world clinical finisher: historically outscores their own xG. */
    function isClinicalFinisher(pin) {
      return Boolean(pin && pin.stats && pin.stats.goals90 > pin.stats.xg90);
    }

    /** Mirrors isClinicalFinisher for creators: historically outscores their own xA. */
    function isClinicalCreator(pin) {
      return Boolean(pin && pin.stats && pin.stats.assists90 > pin.stats.xa90);
    }

    /**
     * Finisher archetype profiling: decompose finishing pattern into big-chance
     * vs half-chance efficiency. A player with high big_chances_missed but high
     * goals90 is a "half-chance scorer"; one with low misses and high goals is
     * "clinical on big chances"; wasteful finishers have high misses + low goals.
     */
    function computeFinisherArchetype(pin) {
      if (!pin || !pin.stats) return { archetype: "unknown", bigChanceEff: 0, halfChanceEff: 0, wasteRate: 0 };

      const npxg = pin.stats.xg90 || 0;
      const goals = pin.stats.goals90 || 0;
      const shots = pin.stats.shots90 || 0;
      const bigChancesMissed = pin.stats.big_chances_missed90 || 0;

      // Expected big chances ≈ npxg / 0.60 (standard big-chance xG value)
      const expectedBigChances = npxg > 0 ? npxg / 0.60 : 0;

      // Implied big chances scored (npxg - value lost to misses)
      // Assume each miss costs ~0.60 xG on average
      const impliedBigChancesScored = Math.max(0, npxg - bigChancesMissed * 0.60);

      // Big-chance efficiency: goals from 0.6+ xG opportunities
      const bigChanceEff = expectedBigChances > 0 ? impliedBigChancesScored / expectedBigChances : 0;

      // Half-chance efficiency: goals from <0.6 xG opportunities
      // Inferred as: total goals - big-chance goals; half-chances ≈ shots - big-chances
      const estimatedBigChanceShots = expectedBigChances * 0.8; // rough correlation
      const estimatedHalfChanceShots = Math.max(0, shots - estimatedBigChanceShots);
      const impliedHalfChanceGoals = Math.max(0, goals - impliedBigChancesScored);
      const halfChanceEff = estimatedHalfChanceShots > 0 ? impliedHalfChanceGoals / estimatedHalfChanceShots : 0;

      // Waste rate: missed big chances vs expected
      const wasteRate = expectedBigChances > 0 ? bigChancesMissed / expectedBigChances : 0;

      // Archetype classification: primarily based on big-chance miss rate + overall finishing
      let archetype = "balanced";

      // Direct big-chance miss rate signal (per 90 basis)
      // Clinical finishers: low misses (< 0.25/90), good conversion on what they do attempt
      // Half-chance scorers: higher misses (0.3+/90) but compensate with overall goals
      // Wasteful: high misses AND low goals (underperforms xG)

      if (bigChancesMissed < 0.25 && goals >= npxg * 0.95) {
        archetype = "clinical_big_chance"; // Few big-chance misses, converts well overall
      } else if (bigChancesMissed >= 0.32 && goals >= npxg * 0.90) {
        archetype = "half_chance_scorer"; // Higher big-chance miss rate but scores overall
      } else if (bigChancesMissed >= 0.40 && goals < npxg * 0.85) {
        archetype = "wasteful"; // Many misses AND underperforms xG
      } else if (goals > npxg * 1.20) {
        archetype = "over_performer"; // Significantly outscores xG (>20%)
      }

      return {
        archetype,
        bigChanceEff: clamp(bigChanceEff, 0, 1),
        halfChanceEff: clamp(halfChanceEff, 0, 1),
        wasteRate: clamp(wasteRate, 0, 1),
        expectedBigChances
      };
    }

    /** Dynamic profligacy based on finisher archetype and chance type. */
    function profligacyByArchetype(pin, chanceType) {
      if (!pin || !pin.stats) return 0;

      const archetype = computeFinisherArchetype(pin);
      const bigChancesMissed = (pin.stats.big_chances_missed90 || 0) * 0.015;

      // Base profligacy (same as before)
      let profligacy = chanceType === "big_chance" ? clamp(bigChancesMissed, 0, 0.1) : 0;

      // Archetype-specific adjustments
      if (chanceType === "big_chance") {
        if (archetype.archetype === "clinical_big_chance") {
          // Reduce penalty: they're actually good at big chances
          profligacy *= 0.5;
        } else if (archetype.archetype === "half_chance_scorer") {
          // Increase penalty: they struggle with big chances specifically
          profligacy *= 1.3;
        } else if (archetype.archetype === "wasteful") {
          // Heavy penalty: consistently miss big chances
          profligacy *= 1.5;
        }
      } else if (chanceType === "half_chance" || chanceType === undefined) {
        // Boost half-chance scorers on lower-xG opportunities
        if (archetype.archetype === "half_chance_scorer") {
          profligacy -= clamp(archetype.halfChanceEff * 0.08, 0, 0.12);
        } else if (archetype.archetype === "clinical_big_chance") {
          // Slight penalty on half-chances if they're pure big-chance specialists
          profligacy += clamp((0.6 - archetype.halfChanceEff) * 0.03, 0, 0.06);
        }
      }

      return clamp(profligacy, -0.15, 0.2);
    }

    /**
     * Creator archetype profiling: decompose creation into big-chance quality,
     * volume, and conversion efficiency. Classifies into archetypes (elite_chance_creator,
     * volume_creator, selective_elite_creator, progressive_creator, etc.) that drive
     * behavioral decisions during chance-creation phases.
     */
    function computeCreatorArchetype(pin) {
      if (!pin || !pin.stats) return { archetype: "unknown", bigChanceCreationPower: 0, volumeIndex: 0, progressionIndex: 0 };

      const xa90 = pin.stats.xa90 || 0;
      const keyPasses90 = pin.stats.key_passes90 || 0;
      const assists90 = pin.stats.assists90 || 0;
      const dribbles90 = pin.stats.dribbles90 || 0;
      const passAccuracy = pin.stats.pass_pct || 75;

      // Big-chance creation power: xa90 is primary; scale up if high key_passes (volume) and high accuracy
      const bigChanceCreationPower = clamp(xa90 + keyPasses90 * 0.08, 0, 1.5);

      // Volume index: key_passes90 + through_balls, adjusted for pass accuracy
      const volumeIndex = clamp((keyPasses90 + (pin.stats.through_balls90 || 0)) * ((passAccuracy - 75) * 0.005 + 1), 0, 5);

      // Quality per pass: xa90 / key_passes90; high quality means selective elite
      const xaPerKeyPass = keyPasses90 > 0 ? xa90 / keyPasses90 : 0;

      // Progression index: dribbles90 + progressive intent
      const progressionIndex = clamp(dribbles90 + (pin.stats.long_balls90 || 0) * 0.15, 0, 3);

      // Assist conversion: do assists match xA expectation?
      const assistConversion = xa90 > 0 ? assists90 / xa90 : 0;

      // Archetype classification
      let archetype = "balanced";

      if (xa90 > 0.28 && keyPasses90 > 1.8) {
        archetype = "elite_chance_creator"; // High xA + high volume = elite
      } else if (keyPasses90 > 2.2 && xa90 > 0.15) {
        archetype = "volume_creator"; // Very high key_passes, moderate xA
      } else if (xaPerKeyPass > 0.22 && keyPasses90 < 1.8 && xa90 > 0.15) {
        archetype = "selective_elite_creator"; // High quality per pass, selective volume
      } else if (progressionIndex > 1.2 && xa90 > 0.12) {
        archetype = "progressive_creator"; // Ball carrier, progressive threat
      } else if (xa90 > 0.22 && assistConversion < 0.7) {
        archetype = "under_converting_creator"; // Creates but teammates don't finish
      }

      return {
        archetype,
        bigChanceCreationPower: clamp(bigChanceCreationPower, 0, 1.5),
        volumeIndex: clamp(volumeIndex, 0, 5),
        xaPerKeyPass: clamp(xaPerKeyPass, 0, 0.5),
        progressionIndex: clamp(progressionIndex, 0, 3),
        assistConversion: clamp(assistConversion, 0, 2)
      };
    }

    /**
     * Archetype-driven behavior modifiers for creator decision-making.
     * Returns multipliers for the five key decision points.
     */
    function creatorBehaviorModifiers(pin) {
      if (!pin || !pin.stats) {
        return {
          spellProbeBoost: 0,
          throughBallMultiplier: 1.0,
          amGateBoost: 0,
          progressiveBoost: 0,
          dmFunnelAdjust: 0
        };
      }

      const archetype = computeCreatorArchetype(pin);
      const arch = archetype.archetype;

      // Base modifiers
      let spellProbeBoost = 0;
      let throughBallMultiplier = 1.0;
      let amGateBoost = 0;
      let progressiveBoost = 0;
      let dmFunnelAdjust = 0;

      if (arch === "elite_chance_creator") {
        // Aggressive creator: frequent attempts, through-ball focus, high gate boost
        spellProbeBoost = 0.03; // +3% spell probe chance
        throughBallMultiplier = 1.4; // 40% higher through-ball tendency
        amGateBoost = 0.08; // Higher creative edge gate
        progressiveBoost = 0.04; // Forward-focused
        dmFunnelAdjust = 0.08; // More willing to funnel forward (higher cmFunnelP)
      } else if (arch === "volume_creator") {
        // Frequent passer: high volume, safe pass preference, quick tempo
        spellProbeBoost = 0.025; // +2.5% spell probe
        throughBallMultiplier = 0.85; // Slightly favor safe pass over through
        amGateBoost = 0.04; // Moderate gate boost
        progressiveBoost = 0; // Balanced
        dmFunnelAdjust = -0.12; // Lower cmFunnelP, more willing to recycle
      } else if (arch === "selective_elite_creator") {
        // Patient elite: wait for perfect moment, high-quality through balls
        spellProbeBoost = 0.01; // Minimal probe boost, waits for openings
        throughBallMultiplier = 1.35; // Very high through-ball tendency when committed
        amGateBoost = 0.12; // High gate, but only when creativeEdge truly high
        progressiveBoost = 0.02; // Selective progressive
        dmFunnelAdjust = 0.05; // Slightly forward-focused
      } else if (arch === "progressive_creator") {
        // Ball carrier: dribble-first, progressive passes, forward momentum
        spellProbeBoost = 0.015; // Moderate probe
        throughBallMultiplier = 1.2; // Forward through-balls
        amGateBoost = 0.06; // Balanced
        progressiveBoost = 0.06; // Strong progressive preference
        dmFunnelAdjust = 0.06; // Forward-minded
      } else if (arch === "under_converting_creator") {
        // Maintains high xA despite assist output; not penalized
        spellProbeBoost = 0.02; // Normal probe (doesn't get discouraged)
        throughBallMultiplier = 1.0; // Balanced
        amGateBoost = 0.05; // Normal
        progressiveBoost = 0; // Balanced
        dmFunnelAdjust = 0; // Normal
      }

      return {
        spellProbeBoost,
        throughBallMultiplier,
        amGateBoost,
        progressiveBoost,
        dmFunnelAdjust
      };
    }

    /**
     * Defensive archetype profiling: classify DMs and CMs into defensive archetypes
     * that drive positioning, lane control, and commitment behavior.
     *
     * DM archetypes:
     * - anchor: high interceptions/positioning, low aggression → screening specialist
     * - ball_winner: high tackles/duels, high aggression → proactive ball recovery
     *
     * CM archetypes:
     * - box_to_box: high tackles/duels/stamina → mobile coverage specialist
     * - playmaker: high passing/xa90, lower defensive stats → creative focus
     */
    function computeDefensiveArchetype(pin) {
      if (!pin || !pin.stats || !pin.role) {
        return { archetype: "unknown", defensiveIndex: 0, mobilityIndex: 0, aggressionIndex: 0 };
      }

      const role = pin.role;
      const tackles90 = pin.stats.tackles90 || 0;
      const interceptions90 = pin.stats.interceptions90 || 0;
      const recoveries90 = pin.stats.ball_recoveries90 || 0;
      const duelsWonPct = pin.stats.duels_won_pct || 50;
      const dribbles90 = pin.stats.dribbles90 || 0;
      const xa90 = pin.stats.xa90 || 0;
      const passAccuracy = pin.stats.pass_pct || 75;
      const yellowCards90 = pin.stats.yellow_cards90 || 0;

      // Defensive positioning index: reading the game (interceptions + recoveries)
      const defensiveIndex = clamp((interceptions90 + recoveries90 * 0.5) * 0.4, 0, 2);

      // Mobility index: ability to cover ground (dribbles + pass accuracy + work rate proxy)
      const mobilityIndex = clamp(dribbles90 * 0.3 + ((passAccuracy - 75) * 0.02), 0, 2);

      // Aggression index: physical engagement (tackles + duels + cards)
      const aggressionIndex = clamp(
        tackles90 * 0.15 + (duelsWonPct - 50) * 0.02 + yellowCards90 * 0.3,
        0,
        2.5
      );

      // Archetype classification
      let archetype = "balanced";

      if (role === "DM") {
        // DM: classify as anchor vs ball-winner
        if (interceptions90 > 1.5 && aggressionIndex < 0.8) {
          archetype = "anchor"; // High positioning, low aggression → screening
        } else if (tackles90 > 2.2 && aggressionIndex > 1.0) {
          archetype = "ball_winner"; // High tackles/aggression → proactive
        }
      } else if (role === "CM") {
        // CM: classify as box-to-box vs playmaker
        if (mobilityIndex > 0.8 && tackles90 > 1.5) {
          archetype = "box_to_box"; // Mobile, defensive → coverage
        } else if (xa90 > 0.22 && passAccuracy > 80) {
          archetype = "playmaker"; // Creative focus
        }
      }

      return {
        archetype,
        defensiveIndex: clamp(defensiveIndex, 0, 2),
        mobilityIndex: clamp(mobilityIndex, 0, 2),
        aggressionIndex: clamp(aggressionIndex, 0, 2.5),
        positioningStrength: interceptions90 / (tackles90 + 0.1) // High = reads game well
      };
    }

    /**
     * Defensive archetype behavioral modifiers for role-specific actions.
     */
    function defensiveArchetypeModifiers(pin) {
      if (!pin || !pin.stats) {
        return {
          pressureMultiplier: 1.0,
          laneControlStrength: 0.5,
          commitmentThreshold: 0.5,
          coverageRadius: 8,
          aggressionBias: 0
        };
      }

      const archetype = computeDefensiveArchetype(pin);
      const arch = archetype.archetype;

      let pressureMultiplier = 1.0;
      let laneControlStrength = 0.5;
      let commitmentThreshold = 0.5;
      let coverageRadius = 8;
      let aggressionBias = 0;

      if (arch === "anchor") {
        // Anchor DM: high pressure, strong lane control, patient (high commitment threshold)
        pressureMultiplier = 1.4; // Very strong pressure in own zone
        laneControlStrength = 1.3; // Excellent at controlling passing lanes
        commitmentThreshold = 0.7; // Waits for clear threat before engaging
        coverageRadius = 10; // Covers large central zone
        aggressionBias = -0.2; // Prefers positioning over tackling
      } else if (arch === "ball_winner") {
        // Ball-winning DM: aggressive, good lane control, low commitment threshold
        pressureMultiplier = 1.25;
        laneControlStrength = 1.1;
        commitmentThreshold = 0.3; // Engages aggressively, early
        coverageRadius = 9;
        aggressionBias = 0.3; // Actively attacks the ball
      } else if (arch === "box_to_box") {
        // Box-to-box CM: mobile, good coverage, balanced commitment
        pressureMultiplier = 1.15;
        laneControlStrength = 0.9;
        commitmentThreshold = 0.45;
        coverageRadius = 11; // Can cover more ground due to mobility
        aggressionBias = 0.1;
      } else if (arch === "playmaker") {
        // Playmaking CM: lower pressure, minimal lane control, patient
        pressureMultiplier = 0.95;
        laneControlStrength = 0.6;
        commitmentThreshold = 0.6;
        coverageRadius = 7; // Tighter positioning
        aggressionBias = -0.15; // Prefers structure over pressing
      }

      return {
        pressureMultiplier,
        laneControlStrength,
        commitmentThreshold,
        coverageRadius,
        aggressionBias
      };
    }

    /**
     * Fullback archetype profiling: classify left/right backs into attacking vs defensive variants
     * based on their stats. Driving decision for off-ball positioning and wide play participation.
     *
     * Attacking Fullback: high pace + high tackles90 + crossing ability → aggressive overlap/underlay
     * Defensive Fullback: high interceptions90 + high blocks90 + lower pace → protective, deep positioning
     */
    function computeFullbackArchetype(pin) {
      if (!pin || !pin.stats || (pin.role !== "FB")) {
        return { archetype: "unknown", attackingIndex: 0, defensiveIndex: 0 };
      }

      const pace = pin.stats.pace || 75;
      const tackles90 = pin.stats.tackles90 || 0;
      const interceptions90 = pin.stats.interceptions90 || 0;
      const blocks90 = pin.stats.blocks90 || 0;
      const crossing = pin.stats.crossing || 60;
      const dribbles90 = pin.stats.dribbles90 || 0;
      const duelsWonPct = pin.stats.duels_won_pct || 50;

      // Attacking index: pace + dribbling + crossing ability
      const attackingIndex = clamp((pace - 70) * 0.02 + dribbles90 * 0.2 + (crossing - 60) * 0.01, 0, 2);

      // Defensive index: tackling + interceptions + blocks
      const defensiveIndex = clamp((tackles90 + interceptions90) * 0.3 + (blocks90 * 0.2), 0, 2);

      // Classification
      let archetype = "balanced";
      if (attackingIndex > defensiveIndex + 0.3 && pace > 78) {
        archetype = "attacking"; // Pace + dribbling + crossing > defensive duties
      } else if (defensiveIndex > attackingIndex + 0.3 && tackles90 > 1.8) {
        archetype = "defensive"; // Defensive solidity > attacking contribution
      }

      return {
        archetype,
        attackingIndex: clamp(attackingIndex, 0, 2),
        defensiveIndex: clamp(defensiveIndex, 0, 2),
        recoveryPace: pace // How quickly can recover if caught out
      };
    }

    /**
     * Fullback behavioral modifiers based on archetype.
     * Controls positioning depth, overlap tendency, defensive commitment.
     */
    function fullbackArchetypeModifiers(pin) {
      if (!pin || !pin.stats) {
        return {
          attackingTendency: 0.5,
          offensiveDepth: 60, // How far forward they push (y coordinate)
          defensiveDepth: 20, // How far back they sit (y coordinate)
          overlapFrequency: 0.5,
          underlapFrequency: 0.3,
          widthCoverage: 8
        };
      }

      const archetype = computeFullbackArchetype(pin);
      const arch = archetype.archetype;

      let attackingTendency = 0.5;
      let offensiveDepth = 60;
      let defensiveDepth = 20;
      let overlapFrequency = 0.5;
      let underlapFrequency = 0.3;
      let widthCoverage = 8;

      if (arch === "attacking") {
        // Attacking fullback: push high, overlap often, less concern for defensive depth
        attackingTendency = 0.85; // Very likely to join attack
        offensiveDepth = 70; // Push very high when attacking
        defensiveDepth = 25; // Still protect goal, but less conservative
        overlapFrequency = 0.8; // Frequent overlaps with winger
        underlapFrequency = 0.5; // Also cuts inside sometimes
        widthCoverage = 9; // Wider area of control due to positioning
      } else if (arch === "defensive") {
        // Defensive fullback: stay deep, cover center backs, less attacking
        attackingTendency = 0.3; // Rarely join attack
        offensiveDepth = 45; // Stay in middle when team attacks
        defensiveDepth = 15; // Sit very deep for protection
        overlapFrequency = 0.2; // Rare overlaps
        underlapFrequency = 0.1; // Almost never underlap
        widthCoverage = 10; // Wider defensive area to compensate for lack of width in attack
      }

      return {
        attackingTendency,
        offensiveDepth,
        defensiveDepth,
        overlapFrequency,
        underlapFrequency,
        widthCoverage
      };
    }

    /**
     * Center back archetype profiling: classify CBs into defensive variants
     * Dominant: physical, aggressive tackler
     * Positioning: reader of game, cuts out passes
     */
    function computeCBArchetype(pin) {
      if (!pin || !pin.stats || pin.role !== "CB") {
        return { archetype: "unknown", dominanceIndex: 0, positioningIndex: 0 };
      }

      const tackles90 = pin.stats.tackles90 || 0;
      const interceptions90 = pin.stats.interceptions90 || 0;
      const blocks90 = pin.stats.blocks90 || 0;
      const duelsWonPct = pin.stats.duels_won_pct || 50;
      const clearances90 = pin.stats.clearances90 || 0;

      const dominanceIndex = clamp((tackles90 * 0.2 + (duelsWonPct - 50) * 0.015 + blocks90 * 0.15), 0, 2);
      const positioningIndex = clamp((interceptions90 * 0.3 + clearances90 * 0.1), 0, 2);

      let archetype = "balanced";
      if (dominanceIndex > positioningIndex + 0.3 && tackles90 > 1.8) {
        archetype = "dominant"; // Physical, aggressive
      } else if (positioningIndex > dominanceIndex + 0.3 && interceptions90 > 1.2) {
        archetype = "positioning"; // Reader of game, cuts out passes
      }

      return {
        archetype,
        dominanceIndex: clamp(dominanceIndex, 0, 2),
        positioningIndex: clamp(positioningIndex, 0, 2)
      };
    }

    /**
     * Hybrid player archetypes: players who excel in unconventional combinations
     * Goal-Scoring Attacker: W/AM with high goals90 + high xa90 (shoots more)
     * Box-Crashing Midfielder: CM with high xg90 + high goals90 + high shots90 (attacking threat)
     */
    function computeHybridArchetype(pin) {
      if (!pin || !pin.stats) {
        return { archetype: "standard" };
      }

      const role = pin.role;
      const goals90 = pin.stats.goals90 || 0;
      const xa90 = pin.stats.xa90 || 0;
      const xg90 = pin.stats.xg90 || 0;
      const shots90 = pin.stats.shots90 || 0;

      // Goal-scoring winger/AM: scores like a striker but creates like a midfielder
      if ((role === "W" || role === "AM") && goals90 > 0.25 && xa90 > 0.18) {
        return { archetype: "goal_scoring_attacker" };
      }

      // Box-crashing midfielder: high scoring threat (xg90 + goals90 + shot volume)
      if (role === "CM" && xg90 > 0.23 && goals90 > 0.2 && shots90 > 1.8) {
        return { archetype: "box_crashing_midfielder" };
      }

      return { archetype: "standard" };
    }

    /**
     * Lane control: how much does a defender control the passing lane to a receiver?
     * Used in pass interception calculations.
     */
    function computeLaneControl(defender, passer, receiver) {
      if (!defender || !passer || !receiver) return 0;

      const defMod = defensiveArchetypeModifiers(defender);
      const dToLane = dist(defender, { left: (passer.left + receiver.left) / 2, top: (passer.top + receiver.top) / 2 });
      const laneLength = dist(passer, receiver);

      // How "in the lane" is the defender? (0 = far from lane, 1 = perfectly positioned)
      const lanePenetration = clamp(1 - dToLane / laneLength * 1.5, 0, 1);

      // Defender's positioning ability
      const positioningQuality = computeDefensiveArchetype(defender).positioningStrength;

      // Final lane control: proximity × positioning × role modifier
      return lanePenetration * positioningQuality * defMod.laneControlStrength * 0.15;
    }

    /**
     * Defensive coverage: how much area is this defender realistically covering?
     * Used for transition and press resistance calculations.
     */
    function defensiveCoverage(pin, ballX, ballY) {
      if (!pin || !pin.stats) return 0;

      const defMod = defensiveArchetypeModifiers(pin);
      const dToBall = dist(pin, { left: ballX, top: ballY });

      // Base coverage decreases with distance (exponential falloff)
      const baseCoverage = Math.max(0, 1 - dToBall / defMod.coverageRadius);

      // Mobility bonus: faster players cover more ground
      const mobilityBonus = pin.stats.dribbles90 * 0.08;

      return clamp(baseCoverage * (1 + mobilityBonus), 0, 1);
    }

    /**
     * Defensive commitment: should this defender step out aggressively?
     * Returns 0-1: how committed the defender is to engaging the ball carrier.
     */
    function defensiveCommitment(pin, ballX, ballY, threat) {
      if (!pin || !threat) return 0;

      const defMod = defensiveArchetypeModifiers(pin);
      const dToBall = dist(pin, { left: ballX, top: ballY });
      const threatPower = threat.pin.stats.dribbles90 * 0.15 + (threat.pin.stats.duels_won_pct - 50) * 0.008;

      // Base commitment: closer = more committed
      const proximityCommitment = clamp(1 - dToBall / defMod.coverageRadius, 0, 1);

      // Threat commitment: bigger threat = more commitment needed
      const threatCommitment = clamp(threatPower * 0.8, 0, 1);

      // Final commitment, accounting for archetype aggression
      return clamp(
        (proximityCommitment * 0.6 + threatCommitment * 0.4) +
          defMod.aggressionBias -
          defMod.commitmentThreshold * 0.2,
        0,
        1
      );
    }

    /**
     * Defensive shape state: track which zones are currently exposed.
     * This creates the "consequences" when defenders step out.
     */
    function computeDefensiveShape(side) {
      const defenders = pinsOf(side).filter((p) => p.role === "DM" || p.role === "CM" || p.role === "CB");
      if (!defenders.length) return { centralExposure: 0, wideExposure: 0 };

      let centralCoverage = 0;
      let wideCoverage = 0;

      for (const def of defenders) {
        if (def.role === "DM" || def.role === "CM") {
          // Midfielders cover central zone (x: 40-60)
          const centralDist = Math.abs(def.left - 50);
          centralCoverage += Math.max(0, 1 - centralDist / 15);

          // And contribute to wide coverage
          wideCoverage += defensiveCoverage(def, def.left, def.top) * 0.3;
        }
        if (def.role === "CB" || def.role === "DM") {
          // CBs + DM cover central
          const centralDist = Math.abs(def.left - 50);
          centralCoverage += Math.max(0, 1 - centralDist / 20) * 0.6;
        }
      }

      return {
        centralExposure: clamp(1 - centralCoverage / Math.max(1, defenders.length * 0.7), 0, 1),
        wideExposure: clamp(1 - wideCoverage / Math.max(1, defenders.length * 0.3), 0, 1)
      };
    }

    /** Forward line (ST/W/AM) collectively within 5% of its combined xG, or ahead of it. */
    function sideForwardLineClinical(side) {
      const fwd = pinsOf(side).filter(
        (p) => p.role === "ST" || p.role === "W" || p.role === "AM" || p.role === "CM" || p.role === "DM"
      );
      if (!fwd.length) return false;
      let goals = 0;
      let xg = 0;
      for (const p of fwd) {
        goals += p.stats.goals90 || 0;
        xg += p.stats.xg90 || 0;
      }
      return xg > 0 && goals >= xg * 0.95;
    }

    /** Quality chance gate: ≥2 in box OR 1 in box + arriving runner; urgency/matchup can soften. */
    function boxOccupationReady(side) {
      const boxed = countBoxAttackers(side);
      const arriving = countArrivingRunners(side);
      if (boxed >= 2 || (boxed >= 1 && arriving >= 1)) return true;
      // Bug fix — closes the remaining sequencing gap countArrivingRunners'
      // own look-ahead (see its comment) doesn't fully solve: boxed only
      // ever reflects who is LITERALLY standing in the box at the exact
      // instant this gets checked, but this check itself fires as part of
      // the shoot/cross decision, often a beat before the carrier (or a
      // teammate) actually steps in. Two genuinely inbound, about-to-arrive
      // runners (both already past countArrivingRunners' own look-ahead
      // bar) is real box occupation forming, not a coin flip on timing —
      // matches "at least two runners join the box" without requiring one
      // to have already crossed the geometric line by pure luck of when
      // this happened to be polled.
      if (arriving >= 2) return true;
      const urg = spell && spell.side === side ? progressionUrgency(spell) : 0;
      const ad = attackDefendDelta(side);
      if (urg >= 1.05 && boxed >= 1) return true;
      if (urg >= 1.2 && arriving >= 1 && ad > 0.08) return true;
      if (ad > 0.18 && boxed >= 1) return true;
      // Focal #9 / elite finisher alone in the box — but only when genuinely
      // unmarked. This was firing for any elite forward merely standing in
      // the box at modest urgency regardless of whether a defender was right
      // there marking him, so defensive coverage got no credit at all.
      // Tightened thresholds and require the nearest defender not be tight.
      if (boxed >= 1) {
        const finishers = pinsOf(side).filter(
          (p) =>
            isAttackFinisher(p) &&
            inPenaltyBox(p) &&
            finisherQuality(p) >= 0.55 &&
            (nearestOpponent(p, 6)?.d ?? 99) >= 4.5
        );
        if (finishers.length) {
          const elite = finishers.some((p) => finisherQuality(p) >= 0.72 || p.role === "ST");
          if (
            elite &&
            (urg >= 0.75 || ad > 0.1 || (arriving >= 1 && ad > 0.02) || finishers.some((p) => p.role === "ST" && finisherQuality(p) >= 0.72))
          ) {
            return true;
          }
          if (finishers.some((p) => p.role === "ST" && finisherQuality(p) >= 0.84)) return true;
        }
      }
      return false;
    }

    function allowDeepRun(side) {
      const st = spell && spell.side === side ? spell.stage : null;
      return (
        st === "BOX_OCCUPATION" ||
        st === "CHANCE_CREATION" ||
        st === "FINISH" ||
        st === "FINAL_THIRD"
      );
    }

    function patternChannelsPrefer(pattern, mate, carrier) {
      if (!pattern || !mate) return 0;
      const flank = pinFlank(carrier);
      const mFlank = pinFlank(mate);
      if (pattern === "central") {
        if (mate.role === "CM" || mate.role === "AM" || mate.role === "ST") return 2.4;
        if (mate.role === "DM") return 0.6;
        return -0.8;
      }
      if (pattern === "wide_switch") {
        if ((mate.role === "W" || mate.role === "FB") && mFlank !== flank && mFlank !== "C") return 3.2;
        if (mate.role === "CM") return 0.35;
        return -0.4;
      }
      if (pattern === "wing_carry") {
        if ((mate.role === "W" || mate.role === "FB") && (mFlank === flank || flank === "C")) return 3.0;
        if (mate.role === "ST" && mFlank === flank) return 1.6;
        if (mate.role === "CM" && mFlank === flank) return 1.2;
        if (mate.role === "CM") return -1.6;
        return -0.6;
      }
      if (pattern === "cut_inside") {
        if (mate.role === "ST" || mate.role === "AM") return 2.6;
        if (mate.role === "W") return 1.4;
        if (mate.role === "CM") return 0.45;
        return -0.3;
      }
      if (pattern === "recycle") {
        if (mate.role === "DM" || mate.role === "CB" || mate.role === "CM") return 2.8;
        return -1.2;
      }
      return 0;
    }

    function bumpPatternOnAction() {
      if (!spell) return;
      spell.patternConfidence = Math.max(0, (spell.patternConfidence ?? 100) - 15);
      spell.patternActions = (spell.patternActions || 0) + 1;
      if (spell.patternConfidence <= 0) {
        spell.lastPattern = spell.pattern;
        spell.pattern = null;
        spell.patternConfidence = 100;
        spell.patternAnnounced = false;
      }
    }


    /** True for CB/FB → ST/W skips that jump the midfield. */
    function isLongSkip(from, to) {
      if (!from || !to) return false;
      return isDefRole(from.role) && isFwdRole(to.role);
    }

    /** Build-up / progress: keep it among defence + midfield until advanced; then wide outlets. */
    function canPlayForward(carrier, target, stage, depth) {
      if (!target) return false;
      if (isMidRole(target.role) || isDefRole(target.role)) return true;
      if (isLongSkip(carrier, target)) return false;
      const late =
        stage === "FINAL_THIRD" ||
        stage === "BOX_OCCUPATION" ||
        stage === "CHANCE_CREATION" ||
        stage === "FINISH";
      if (target.role === "ST") {
        if (stage === "BUILD_UP") return false;
        if (stage === "PROGRESSING") {
          return depth >= 0.55 && (isMidRole(carrier.role) || carrier.role === "W" || carrier.role === "AM");
        }
        return depth >= 0.5 && (isMidRole(carrier.role) || carrier.role === "W" || carrier.role === "AM" || carrier.role === "FB");
      }
      if (target.role === "W") {
        if (stage === "BUILD_UP") return isMidRole(carrier.role) && depth >= 0.38;
        if (stage === "PROGRESSING") {
          return isMidRole(carrier.role) || carrier.role === "W" || carrier.role === "FB" || carrier.role === "AM";
        }
        return depth >= 0.42 || isMidRole(carrier.role) || carrier.role === "FB" || carrier.role === "AM";
      }
      if (late) return depth >= 0.48 || isMidRole(carrier.role) || carrier.role === "W";
      return depth >= 0.52 && (isMidRole(carrier.role) || carrier.role === "W" || carrier.role === "AM");
    }

    function pointToSegmentDist(px, py, ax, ay, bx, by) {
      const abx = bx - ax;
      const aby = by - ay;
      const apx = px - ax;
      const apy = py - ay;
      const ab2 = abx * abx + aby * aby || 1e-6;
      const t = clamp((apx * abx + apy * aby) / ab2, 0, 1);
      return Math.hypot(px - (ax + t * abx), py - (ay + t * aby));
    }

    /** Opponents near the pass segment (excluding those marking the endpoints). */
    function defendersInLane(from, to, maxDist = 4.5) {
      if (!from || !to) return 0;
      const ops = pinsOf(oppOf(from.side));
      let n = 0;
      for (const d of ops) {
        if (d.role === "GK") continue;
        if (dist(d, from) < 3.5 || dist(d, to) < 3.5) continue;
        if (pointToSegmentDist(d.left, d.top, from.left, from.top, to.left, to.top) < maxDist) n++;
      }
      return n;
    }

    function laneBlocked(from, to) {
      return defendersInLane(from, to) >= 1;
    }

    /** Higher = clearer passing lane. */
    function laneScore(from, to) {
      const n = defendersInLane(from, to);
      if (n >= 2) return -3.6;
      if (n === 1) return -1.9;
      const lateral = Math.abs(to.left - from.left);
      return 1.45 + (lateral > 8 && lateral < 28 ? 0.35 : 0);
    }

    /** Heuristic: prefer receivers open to the passer / half-turned toward goal. */
    function receiverFacingPasser(from, to) {
      const attackSign = to.side === "home" ? -1 : 1;
      const ahead = attackSign * (to.top - from.top);
      const toPasserL = from.left - to.left;
      const d = dist(from, to);
      const facingBall = Math.abs(toPasserL) > 2 || d < 18;
      const openBody = ahead > -2 && ahead < 18;
      return (openBody ? 0.55 : 0) + (facingBall ? 0.45 : 0);
    }

    /** 0–1+: rises with completed ball actions; matchups accelerate or delay vertical pressure. */
    function attackDefendDelta(atkSide) {
      return (
        sideAttack(atkSide) -
        sideDefend(oppOf(atkSide)) +
        sideCreate(atkSide) * 0.15 +
        instrBias(atkSide) * 0.045 -
        instrBias(oppOf(atkSide)) * 0.03
      );
    }

    function pressOnBallDelta(atkSide) {
      return sidePress(oppOf(atkSide)) - sideResist(atkSide);
    }

    function possessionHoldDelta(atkSide) {
      return sidePoss(atkSide) - sidePress(oppOf(atkSide));
    }

    function flankUnitPower(side, flank, mode) {
      const preferX = flank === "R" ? 0.86 : flank === "L" ? 0.14 : 0.5;
      const pins = pinsOf(side).filter((p) => {
        if (mode === "atk") return p.role === "W" || p.role === "FB";
        return p.role === "FB" || p.role === "CB" || (p.role === "W" && sidePress(side) > 0.45);
      });
      const onFlank = pins.filter((p) => {
        const f = pinFlank(p);
        return f === flank || (flank !== "C" && Math.abs(p.baseX - preferX) < 0.34);
      });
      const list = onFlank.length ? onFlank : pins;
      if (!list.length) return 0.4;
      let sum = 0;
      for (const p of list) {
        if (mode === "atk") {
          sum +=
            p.stats.xa90 * 1.35 +
            p.stats.dribbles90 * 0.32 +
            p.stats.key_passes90 * 0.12 +
            (p.role === "FB" ? fbAttackThreat(p) * 0.8 : 0.15);
        } else {
          sum +=
            p.stats.tackles90 * 0.28 +
            p.stats.interceptions90 * 0.32 +
            sideDefend(side) * 0.35 +
            (p.role === "FB" ? 0.25 : 0.15);
        }
      }
      return clamp(sum / list.length, 0.15, 1.25);
    }

    function flankMatchupEdge(atkSide, flank) {
      if (flank === "C") return 0;
      return flankUnitPower(atkSide, flank, "atk") - flankUnitPower(oppOf(atkSide), flank, "def");
    }

    function strikerAerialThreat(side) {
      const sts = pinsOf(side).filter((p) => p.role === "ST" || p.role === "AM");
      if (!sts.length) return 0.35;
      return clamp(
        sts.reduce((s, p) => {
          const aw = p.stats.aerials_won90 || 0;
          const ap = (p.stats.aerials_won_pct || 0) / 100;
          const aerial = aw > 0 ? aw * 0.22 * Math.max(0.45, ap || 0.5) : 0;
          return s + p.stats.xg90 * 0.95 + p.stats.shots90 * 0.05 + aerial;
        }, 0) / sts.length,
        0.2,
        1.15
      );
    }

    function progressionUrgency(sp = spell) {
      const n = (sp && (sp.patience ?? sp.actions)) || 0;
      const side = (sp && sp.side) || possession;
      const ad = attackDefendDelta(side);
      const pressD = pressOnBallDelta(side);
      const hold = possessionHoldDelta(side);
      // Actions pile up far faster than a spell's own nominal duration (roughly
      // one action every ~0.175 match-minutes), so urgency was saturating
      // within the first ~1.5 minutes of an 8-9 minute spell and sitting
      // pinned at max for the rest of it — a rushed sprint to a shot instead
      // of a patient buildup. Slow just the action-count component; the
      // tactical signals below (strong attack vs weak defence, heavy press)
      // still apply at full strength since those are genuine hurry-up cues.
      const nSlow = n * 0.35;
      let effective = nSlow;
      // Strong attack vs weak defence → urgency earlier
      if (ad > 0.1) effective += 1.15 + ad * 2.8;
      else if (ad < -0.08) {
        // Weak attack vs strong defence → patient through actions 1–4, then catch up
        if (nSlow <= 4) effective = nSlow * (0.45 + Math.max(0, 0.12 + ad));
        else effective = 2.0 + (nSlow - 4) * (1.05 + Math.min(0.25, -ad * 0.4));
      }
      // High press vs weak resist → hurry decisions
      if (pressD > 0.08) effective += pressD * 3.1;
      // Possession side vs low press → hold patience longer
      if (hold > 0.1 && pressD < 0.06) effective -= Math.min(2.4, hold * 2.6);
      // Sterile high-poss vs elite create+shield → less forced progression into the box
      const supp = possessionSuppressionMul(side);
      if (supp < 0.95) effective -= (1 - supp) * 1.8;
      effective = Math.max(0, effective);
      if (effective <= 3) return 0.1 + effective * 0.06;
      if (effective <= 6) return 0.42 + (effective - 3) * 0.14;
      if (effective <= 9) return 0.92 + (effective - 6) * 0.1;
      return 1.25 + Math.min(0.55, (effective - 9) * 0.1);
    }

    function isFinalThirdStage(stage) {
      return (
        stage === "FINAL_THIRD" ||
        stage === "BOX_OCCUPATION" ||
        stage === "CHANCE_CREATION" ||
        stage === "FINISH"
      );
    }

    function progressiveLanesBlocked(carrier) {
      if (!carrier) return true;
      const attackSign = carrier.side === "home" ? -1 : 1;
      const opts = teammates(carrier).filter((m) => {
        const ahead = attackSign * (m.top - carrier.top);
        return ahead > 2 && dist(carrier, m) < 26 && !wouldPassBeOffside(carrier, m);
      });
      if (!opts.length) return true;
      return opts.every((m) => defendersInLane(carrier, m) >= 1);
    }

    function isCrossFieldSwitch(carrier, mate) {
      if (!carrier || !mate) return false;
      const lateral = Math.abs(mate.left - carrier.left);
      if (lateral < 28) return false;
      const cFlank = pinFlank(carrier);
      const mFlank = pinFlank(mate);
      const wingPair =
        (carrier.role === "W" || carrier.role === "FB") && (mate.role === "W" || mate.role === "FB");
      const opposite =
        (cFlank === "L" && mFlank === "R") ||
        (cFlank === "R" && mFlank === "L") ||
        lateral > 36;
      return wingPair && opposite;
    }

    function flankOverloadedOrBlocked(carrier) {
      const flank = pinFlank(carrier);
      const ops = pinsOf(oppOf(carrier.side));
      let crowd = 0;
      for (const d of ops) {
        if (d.role === "GK") continue;
        if (dist(d, carrier) > 12) continue;
        const sameSide =
          flank === "C" ||
          (flank === "L" && d.left < 48) ||
          (flank === "R" && d.left > 52) ||
          dist(d, carrier) < 7.5;
        if (sameSide) crowd++;
      }
      return crowd >= 2 || progressiveLanesBlocked(carrier);
    }

    /** Long LW↔RW / far-flank switches only when tactically justified. */
    function isJustifiedSwitch(carrier, mate) {
      if (!isCrossFieldSwitch(carrier, mate)) return true;
      if (defendersInLane(carrier, mate) >= 1) return false;
      const nearMark = nearestOpponent(carrier, 10);
      const farMark = nearestOpponent(mate, 10);
      const nearSpace = nearMark ? nearMark.d : 14;
      const farSpace = farMark ? farMark.d : 14;
      const farFlank = pinFlank(mate);
      const nearFlank = pinFlank(carrier);
      const farEdge = flankMatchupEdge(carrier.side, farFlank);
      const nearEdge = flankMatchupEdge(carrier.side, nearFlank);
      const overloaded = flankOverloadedOrBlocked(carrier);
      // Overloaded weak flank → switch to strong far side (open lane required above)
      if (overloaded && farEdge > 0.1 && farSpace >= nearSpace + 1.4) return true;
      if (nearEdge < -0.05 && farEdge > 0.18 && farSpace > nearSpace + 1.2) return true;
      if (!overloaded) return false;
      if (farSpace < nearSpace + 2.8 && farEdge < 0.12) return false;
      const attackSign = carrier.side === "home" ? -1 : 1;
      const ahead = attackSign * (mate.top - carrier.top);
      const mateDepth = fromPitchPct(mate.side, mate.left, mate.top).depth;
      const carDepth = possessionDepth(carrier);
      if (ahead < -5 && farSpace < nearSpace + 5) return false;
      if (mateDepth + 0.04 < carDepth && farSpace < nearSpace + 4.5 && farEdge < 0.2) return false;
      return true;
    }

    function isLocalTriangleOption(carrier, mate) {
      if (!carrier || !mate) return false;
      const d = dist(carrier, mate);
      if (d < 5 || d > 20) return false;
      if (Math.abs(mate.left - carrier.left) > 22) return false;
      if (isCrossFieldSwitch(carrier, mate)) return false;
      const roles = `${carrier.role}-${mate.role}`;
      const pairOk =
        /CM|AM|DM|FB|W|ST/.test(carrier.role) &&
        /CM|AM|DM|FB|W|ST/.test(mate.role) &&
        !(isDefRole(carrier.role) && isDefRole(mate.role));
      if (!pairOk) return false;
      const third = teammates(carrier).some((t) => {
        if (t.id === mate.id || t.role === "GK") return false;
        return dist(t, carrier) < 18 && dist(t, mate) < 18 && Math.abs(t.left - carrier.left) < 26;
      });
      return (
        third ||
        mate._supportRole === "third_man" ||
        mate._supportRole === "progressive" ||
        /FB-W|W-FB|CM-ST|ST-CM|AM-ST|ST-AM|W-ST|ST-W|CM-FB|FB-CM|CM-W|W-CM/.test(roles)
      );
    }

    /** Light follow-up score from a hypothetical receiver (no recursion into sequences). */
    function scoreFollowUpOption(from, to) {
      if (!from || !to || wouldPassBeOffside(from, to)) return -6;
      const attackSign = from.side === "home" ? -1 : 1;
      const ahead = attackSign * (to.top - from.top);
      const d = dist(from, to);
      if (d > 32) return -3.5;
      const nLane = defendersInLane(from, to);
      const stage = spell?.stage || "PROGRESSING";
      const late = isFinalThirdStage(stage);
      const urg = progressionUrgency(spell);
      const ad = attackDefendDelta(from.side);
      const pressD = pressOnBallDelta(from.side);
      let s = laneScore(from, to) * 0.6;
      s += clamp(ahead, -5, 14) * (0.1 + urg * 0.05 + Math.max(0, ad) * 0.06);
      if (nLane >= 2) s -= 2.8 + Math.max(0, -ad) * 0.9;
      else if (nLane === 1) s -= 1.1 + Math.max(0, -ad) * 0.45;
      if (d >= 8 && d <= 20) s += 0.85 + Math.max(0, possessionHoldDelta(from.side)) * 0.35;
      if (throughBallLegal(from, to)) {
        s += 2.35 + (late ? 1.15 : 0.25) + ad * 1.4;
        if (ad < -0.1) s -= 1.1;
      }
      if (to._supportRole === "third_man" || to._supportRole === "depth_runner") s += 0.95;
      if (to._supportRole === "progressive") s += 0.7 + Math.max(0, ad) * 0.35;
      if (isCrossFieldSwitch(from, to) && !isJustifiedSwitch(from, to)) s -= 4.2;
      else if (isLocalTriangleOption(from, to)) s += 1.05 + Math.max(0, possessionHoldDelta(from.side)) * 0.5;
      if (late && ahead > 2 && nLane < 2) s += 1.15 + Math.max(0, ad) * 0.7;
      if (late && ahead < -2) s -= 1.45 * (0.55 + urg * 0.35);
      if (late && from.role === "W" && (to.role === "ST" || to.role === "AM") && d < 18) s += 1.15;
      if (from.role === "ST" && (to.role === "CM" || to.role === "AM" || to.role === "W") && ahead > -3) s += 0.95;
      if ((from.role === "FB" || from.role === "W") && to.role === "FB" && to._overlapRun) s += 1.25;
      const mFlank = pinFlank(to);
      if ((to.role === "W" || to.role === "FB") && mFlank !== "C") {
        s += flankMatchupEdge(from.side, mFlank) * 0.85;
      }
      if (to._running && nLane === 0) s += 0.55 + Math.max(0, ad) * 0.3;
      if (pressD > 0.12 && ahead < 1) s -= 0.45;
      return s;
    }

    function bestFollowUpFrom(receiver) {
      if (!receiver) return { score: -2, mate: null };
      let best = -3.5;
      let bestMate = null;
      for (const m of teammates(receiver)) {
        if (m.role === "GK") continue;
        const s = scoreFollowUpOption(receiver, m);
        if (s > best) {
          best = s;
          bestMate = m;
        }
      }
      return { score: best, mate: bestMate };
    }

    /**
     * Shallow attack-sequence score: immediate pass + likely next 1–2 touches.
     * Scales with attack–defend / press–resist so good teams break blocks differently.
     */
    function scoreAttackSequence(carrier, mate, depthPly = 2) {
      const immediate = scorePassingOption(carrier, mate);
      if (depthPly < 1) return immediate;
      const ad = attackDefendDelta(carrier.side);
      const pressD = pressOnBallDelta(carrier.side);
      const followW = 0.55 + clamp(ad * 0.12 - Math.max(0, pressD) * 0.05, -0.12, 0.18);
      const secondW = 0.25 + clamp(ad * 0.06, -0.06, 0.1);
      const follow = bestFollowUpFrom(mate);
      let second = 0;
      if (depthPly >= 2 && follow.mate) {
        second = bestFollowUpFrom(follow.mate).score;
      }
      return immediate + followW * follow.score + secondW * second;
    }

    function scorePassingOption(carrier, mate, opts = {}) {
      const stage = spell?.stage || "PROGRESSING";
      const depth = possessionDepth(carrier);
      const pattern = spell?.pattern;
      const conf = spell?.patternConfidence ?? 0;
      const urg = progressionUrgency(spell);
      const late = isFinalThirdStage(stage);
      const ad = attackDefendDelta(carrier.side);
      const hold = possessionHoldDelta(carrier.side);
      const pressD = pressOnBallDelta(carrier.side);
      const attackSign = carrier.side === "home" ? -1 : 1;
      const ahead = attackSign * (mate.top - carrier.top);
      const d = dist(carrier, mate);
      const lateral = Math.abs(mate.left - carrier.left);
      const nLane = defendersInLane(carrier, mate);
      const lane = laneScore(carrier, mate);
      const marked = nearestOpponent(mate, 7);
      const pressOnPasser = nearestOpponent(carrier, 8);
      const sideways = Math.abs(ahead) < 2.8 && lateral > 10;
      const recycleBack = ahead < -1.2;

      let score = lane;
      if (nLane >= 2) score -= 4.2 + Math.max(0, -ad) * 0.85;
      else if (nLane === 1) score -= Math.max(0, -ad) * 0.4;

      if (marked) score -= clamp(2.1 - marked.d / 4, 0.25, 2.1);
      else score += 0.75;
      if (pressOnPasser && pressOnPasser.d < 6) score -= 0.4 + Math.max(0, pressD) * 0.35;

      if (d < 6) score -= 0.85;
      else if (d >= 8 && d <= 20) score += 1.65 + Math.max(0, hold) * 0.4;
      else if (d <= 22) score += 0.95;
      else if (d <= 32) score -= 0.45 + (d - 22) * 0.08;
      else score -= 1.9 + (d - 32) * 0.055;

      if (d > 28 && lateral > 24 && nLane >= 1) score -= 5.2;
      if (d > 30 && lateral > 28) score -= 2.8;

      score += receiverFacingPasser(carrier, mate);
      if (!marked && ahead > 1 && ahead < 14) score += 0.55;
      score -= d * 0.025;

      const progress = clamp(ahead, -6, 16);
      const progressMul = (nLane === 0 ? 0.12 : 0.04) + urg * 0.06 + Math.max(0, ad) * 0.05;
      score += progress * progressMul;

      if (wouldPassBeOffside(carrier, mate)) score -= 8.5;

      if ((mate.role === "ST" || mate.role === "W") && !canPlayForward(carrier, mate, stage, depth)) {
        score -= 10;
      } else if (isMidRole(mate.role)) {
        score += mate.role === "CM" ? 0.55 : mate.role === "AM" ? 0.7 : 0.35;
        if (stage === "BUILD_UP" && mate.role === "CM") score += 0.45;
        if (hold > 0.1) score += 0.35;
      } else if (mate.role === "FB") {
        score += 0.4;
      } else if (mate.role === "CB") {
        score += stage === "BUILD_UP" || stage === "PROGRESSING" ? 0.35 : -0.55 - urg * 0.35;
      }

      const role = mate._supportRole;
      if (role === "progressive") score += 1.15 + urg * 0.35 + Math.max(0, ad) * 0.4;
      else if (role === "safe_outlet") score += urg < 0.45 ? 0.55 : 0.1 - urg * 0.2;
      else if (role === "third_man") score += 0.95 + urg * 0.25;
      else if (role === "depth_runner") score += 0.55 + (late ? 0.85 : 0.15) + Math.max(0, ad) * 0.5;
      else if (role === "switch") score += nLane === 0 && d < 36 && isJustifiedSwitch(carrier, mate) ? 0.45 : -2.4;

      if (isCrossFieldSwitch(carrier, mate)) {
        score += isJustifiedSwitch(carrier, mate) ? 0.35 + Math.max(0, flankMatchupEdge(carrier.side, pinFlank(mate))) * 0.7 : -6.8;
      } else if (isLocalTriangleOption(carrier, mate)) {
        score += 1.35 + (urg < 0.7 ? 0.45 : 0.2) + Math.max(0, hold) * 0.55;
      }

      const mFlank = pinFlank(mate);
      if ((mate.role === "W" || mate.role === "FB") && mFlank !== "C") {
        score += flankMatchupEdge(carrier.side, mFlank) * 1.05;
      }

      // Possession patience: early circulate; late force progression
      if (urg <= 0.35) {
        if (recycleBack || sideways) score += 0.35 + Math.max(0, hold) * 0.25;
        if (ahead > 8 && nLane >= 1) score -= 0.9 + Math.max(0, -ad) * 0.5;
      } else if (urg >= 0.85) {
        const trapped =
          progressiveLanesBlocked(carrier) && pressOnPasser && pressOnPasser.d < 6.2;
        if ((recycleBack || sideways) && !trapped) score -= 2.4 * Math.min(urg, 1.5);
        if (ahead > 3 && nLane < 2) score += 1.55 * Math.min(urg, 1.4) + Math.max(0, ad) * 0.6;
      }
      if (urg >= 1.2 && ahead > 2 && nLane <= 1) score += 1.25 + Math.max(0, ad) * 0.45;

      // Final third: through balls, layoffs, cutbacks — not sterile recycle
      if (late) {
        if (throughBallLegal(carrier, mate)) {
          score += 2.4 + ad * 1.5;
          if (ad < -0.1) score -= 1.2;
        }
        if (ahead > 2 && nLane < 2) score += 1.4 + Math.max(0, ad) * 0.55;
        if (mate.role === "ST" && ahead > -1 && nLane < 2) score += 1.05;
        if ((carrier.role === "ST" || mate.role === "ST") && isLocalTriangleOption(carrier, mate)) score += 0.75;
        if (recycleBack && !(progressiveLanesBlocked(carrier) && pressOnPasser && pressOnPasser.d < 5.5)) {
          score -= 2.1 * (0.7 + urg * 0.35);
        }
        if (isFwdRole(carrier.role) && depth >= 0.66) {
          if (recycleBack) score -= 6.5;
          if (ahead > 0 && nLane < 2) score += 2.2;
          if (mate.role === "ST" || mate.role === "W" || mate.role === "AM") score += 1.1;
        }
      }

      const channelBias = patternChannelsPrefer(pattern, mate, carrier) * (conf > 40 ? 0.4 : 0.18);
      score += nLane === 0 ? channelBias : channelBias * 0.12;
      if (pattern === "wide_switch" && isCrossFieldSwitch(carrier, mate) && !isJustifiedSwitch(carrier, mate)) {
        score -= 4.5;
      }

      const linkSet = opts.linkSet;
      if (linkSet && linkSet.has(mate.id) && nLane === 0) {
        score += carrier.role === "W" || carrier.role === "FB" ? 0.95 : 0.45;
      }
      if (mate.id === favoredId && mate.favorUntil > matchMinute && nLane < 2) score += 0.7;

      if (mate._running && nLane === 0) score += 0.35 + (late ? 0.55 : 0);

      // Engine rebuild — pass memory (Problem 4: repetitive passing). A
      // decision with no memory of who just had the ball scores the same
      // CM<->RB exchange as "best" forever. Penalize passing straight back
      // to someone who's touched it recently in this spell, decaying with
      // how long ago — discourages instant ping-pong without permanently
      // blacklisting anyone once a couple of other players have touched it.
      if (spell?.lastReceivers?.length) {
        const idx = spell.lastReceivers.lastIndexOf(mate.id);
        if (idx >= 0) {
          const recency = spell.lastReceivers.length - idx; // 1 = had it last
          score -= Math.max(0, 2.4 - (recency - 1) * 0.9);
        }
      }

      score += rng() * 0.28;
      return score;
    }

    function progressiveTarget(carrier) {
      const mates = teammates(carrier);
      const stage = spell?.stage || "PROGRESSING";
      const depth = possessionDepth(carrier);
      const urg = progressionUrgency(spell);
      const attackSign = carrier.side === "home" ? -1 : 1;
      const links = linkedOptions(carrier);
      const linkSet = new Set(links.map((p) => p.id));
      const scored = mates.map((m) => ({
        m,
        score: scoreAttackSequence(carrier, m, 2),
        d: dist(carrier, m),
        nLane: defendersInLane(carrier, m),
        ahead: attackSign * (m.top - carrier.top),
      }));

      // Under urgency, prefer progressive options unless truly trapped
      const trapped = progressiveLanesBlocked(carrier) && nearestOpponent(carrier, 6)?.d < 6;
      const shortClear = scored.filter(
        (s) =>
          s.d < 22 &&
          s.nLane < 2 &&
          s.score > -3.2 &&
          !wouldPassBeOffside(carrier, s.m) &&
          (s.ahead > -3 || isMidRole(s.m.role) || isDefRole(s.m.role)) &&
          !(isCrossFieldSwitch(carrier, s.m) && !isJustifiedSwitch(carrier, s.m))
      );
      shortClear.sort((a, b) => b.score - a.score);
      if (urg >= 0.85 && !trapped) {
        const progressive = shortClear.filter((s) => s.ahead > 1.5);
        const eligible = progressive.filter(
          (s) => canPlayForward(carrier, s.m, stage, depth) || isMidRole(s.m.role) || s.m.role === "FB"
        );
        const pick = nearOptimalPick(eligible, confidenceMargin(carrier, 0.6));
        if (pick) return pick.m;
      }
      {
        const eligible = shortClear.filter(
          (s) => canPlayForward(carrier, s.m, stage, depth) || isMidRole(s.m.role) || isDefRole(s.m.role)
        );
        const pick = nearOptimalPick(eligible, confidenceMargin(carrier, 0.6));
        if (pick) return pick.m;
      }
      if (shortClear.length) return shortClear[0].m;

      scored.sort((a, b) => b.score - a.score);
      {
        const eligible = scored.filter((s) => {
          if (wouldPassBeOffside(carrier, s.m)) return false;
          if (s.d > 28 && s.nLane >= 1) return false;
          if (isCrossFieldSwitch(carrier, s.m) && !isJustifiedSwitch(carrier, s.m)) return false;
          if (s.d > 32 && Math.abs(s.m.left - carrier.left) > 28) return false;
          return canPlayForward(carrier, s.m, stage, depth) || isMidRole(s.m.role) || isDefRole(s.m.role);
        });
        const pick = nearOptimalPick(eligible, confidenceMargin(carrier, 0.6));
        if (pick) return pick.m;
      }
      return scored[0]?.m || mates[0];
    }

    /**
     * Engine fix — how hard a long ball actually is to pull off, purely as
     * a function of distance and lateral width. longBallTarget used to pick
     * the best-statted forward with no regard for how far/wide the ball had
     * to travel to reach them, so a fullback would ping a full-width
     * diagonal to the opposite winger as readily as a short ball to a
     * nearby runner whenever that winger had the best xG/xA on the team.
     * Divides the target's attacking-stat score, so a harder pass needs a
     * proportionally better payoff to still win out — same spirit as the
     * distance ladder scorePassingOption already applies to every other
     * pass, just scoped to this one selection.
     */
    function longBallDifficulty(carrier, mate) {
      const d = dist(carrier, mate);
      const lateral = Math.abs(mate.left - carrier.left);
      let difficulty = 1;
      if (d > 22) difficulty += (d - 22) * 0.045;
      if (lateral > 24) difficulty += (lateral - 24) * 0.05;
      return difficulty;
    }

    function longBallTarget(carrier) {
      const runners = teammates(carrier)
        .filter((m) => isFwdRole(m.role) || m.role === "AM")
        .filter((m) => !wouldPassBeOffside(carrier, m))
        // Bug fix — this used to hand back the best-statted forward
        // regardless of whether there was any real opportunity to hit them,
        // so a long ball fired just because an attacker existed somewhere
        // upfield. Require an actual read of space: the runner is actively
        // making the move, or the lane to find them is genuinely clear.
        .filter((m) => m._running || defendersInLane(carrier, m) === 0)
        // Engine fix — an unjustified full-width switch (e.g. an RB pinging
        // the ball cross-field straight to the LW) is a genuinely
        // low-probability pass in real football; hold it to the same bar
        // isJustifiedSwitch already applies to every other pass (open lane
        // + a real space/matchup edge on the far side) rather than letting
        // it compete on raw attacking stats alone. Passes through untouched
        // for any target that isn't a cross-field switch in the first
        // place.
        .filter((m) => isJustifiedSwitch(carrier, m));
      if (!runners.length) return null;
      runners.sort((a, b) => {
        const scoreA = (a.stats.xg90 * 1.4 + a.stats.xa90 * 1.15) / longBallDifficulty(carrier, a);
        const scoreB = (b.stats.xg90 * 1.4 + b.stats.xa90 * 1.15) / longBallDifficulty(carrier, b);
        return scoreB - scoreA + rng() * 0.2;
      });
      const best = runners[0];
      // Engine fix — isJustifiedSwitch's wingPair check only classifies a
      // W/FB carrier as capable of a "switch" at all, so a CB launching the
      // identical full-width diagonal to the opposite winger was never
      // caught by the filter above, and the soft difficulty divisor alone
      // can't stop it when this happens to be the only live runner in the
      // pool (sorting one candidate never discounts it out of contention).
      // Hard cap regardless of carrier role: past this difficulty the pass
      // just doesn't get attempted this tick.
      if (longBallDifficulty(carrier, best) > 2.1) return null;
      return best;
    }

    function backPassTarget(carrier) {
      let mates = teammates(carrier);
      // A winger close to/in the final third shouldn't recycle all the way back
      // to a CB — the "behind" scoring below naturally favours whoever is
      // deepest, which is almost always the centre-back. Exclude CB from the
      // pool here (FB/CM/DM remain, so a nearby out-ball is still available)
      // unless that leaves no options at all.
      if (carrier.role === "W" && possessionDepth(carrier) >= 0.58) {
        const noCB = mates.filter((m) => m.role !== "CB");
        if (noCB.length) mates = noCB;
      }
      // Engine fix — a real back pass is a short, safe out-ball, not a
      // cross-field diagonal. The old -0.03/unit distance term was too
      // weak to stop a distant, high-stat teammate (e.g. a winger on the
      // far flank) from outscoring a genuinely nearby option purely on
      // being open and well-statted -- that's what "huge diagonal passes
      // happen too often" actually traces to. Restrict the pool to a
      // realistic passing radius first; only fall back to the full pool if
      // that leaves nobody at all.
      const nearby = mates.filter((m) => dist(carrier, m) <= 32);
      if (nearby.length) mates = nearby;
      const attackSign = carrier.side === "home" ? -1 : 1;
      const scored = mates.map((m) => {
        const behind = -attackSign * (m.top - carrier.top);
        let roleBias = isMidRole(m.role) ? 1.8 : isDefRole(m.role) ? 1.2 : -1.5;
        if (m.role === "DM") roleBias += 0.8;
        return {
          m,
          score:
            behind * 0.1 +
            m.stats.pass_pct * 0.016 +
            m.stats.key_passes90 * 0.08 +
            (m.stats.xg_buildup90 || 0) * 0.2 +
            (m.stats.xg_chain90 || 0) * 0.1 +
            roleBias -
            dist(carrier, m) * 0.09 +
            rng() * 0.3,
        };
      });
      scored.sort((a, b) => b.score - a.score);
      return scored[0]?.m || mates[0];
    }

    function shooterTarget(carrier) {
      // Engine addition — goal-scoring midfielder archetype. CM/DM added
      // so a real box-to-box scoring midfielder can be picked to receive
      // the ball for a shot; the sort below is already stat-weighted
      // (openPlayXg/shots90/finisherQuality), so a genuine passer with low
      // shooting stats still rarely wins this over a real forward.
      const mates = teammates(carrier).filter(
        (m) => m.role === "ST" || m.role === "AM" || m.role === "W" || m.role === "CM" || m.role === "DM"
      );
      if (!mates.length) return carrier;
      mates.sort((a, b) => {
        const fa = a.id === favoredId ? 0.35 : 0;
        const fb = b.id === favoredId ? 0.35 : 0;
        const boxA = inPenaltyBox(a) ? 1.4 : nearPenaltyBox(a) ? 0.45 : 0;
        const boxB = inPenaltyBox(b) ? 1.4 : nearPenaltyBox(b) ? 0.45 : 0;
        const roleA = a.role === "ST" ? 0.55 : a.role === "AM" ? 0.18 : 0.05;
        const roleB = b.role === "ST" ? 0.55 : b.role === "AM" ? 0.18 : 0.05;
        const fqA = finisherQuality(a) * 0.55;
        const fqB = finisherQuality(b) * 0.55;
        return (
          openPlayXg(b) * 1.55 +
          b.stats.shots90 * 0.16 +
          boxB +
          fb +
          roleB +
          fqB -
          (openPlayXg(a) * 1.55 + a.stats.shots90 * 0.16 + boxA + fa + roleA + fqA)
        );
      });
      const best = mates[0];
      if (inPenaltyBox(carrier) && openPlayXg(carrier) >= openPlayXg(best) * 0.7) return carrier;
      // Focal #9 with real shot volume should receive the ball more often
      const feedP =
        best.role === "ST" && finisherQuality(best) >= 0.55
          ? 0.72
          : best.role === "ST" || finisherQuality(best) >= 0.7
            ? 0.64
            : 0.55;
      return rng() < feedP ? best : carrier;
    }

    function weightedPick(entries) {
      let total = 0;
      for (const e of entries) total += Math.max(0, e.w);
      if (total <= 0) return entries[0]?.id ?? null;
      let r = rng() * total;
      for (const e of entries) {
        r -= Math.max(0, e.w);
        if (r <= 0) return e.id;
      }
      return entries[entries.length - 1].id;
    }

    /**
     * Engine fix — near-optimal decision tolerance. pickAttackPattern and
     * decideWideFinalThird's cross/cutback/recycle choice already use real
     * weighted-random selection via weightedPick above, so two near-tied
     * options there already get picked close to evenly over time. Pass-target
     * selection (progressiveTarget, centralProgressTarget) didn't: it was a
     * flat sort-then-take-top, so the single highest-scored option always
     * won even when a second option scored almost identically — a real
     * player sometimes takes the slightly-worse-scored pass on purpose
     * (disguise, trust, anticipated pressure). `list` must already be sorted
     * descending by .score; picks a weighted draw among every entry within
     * `margin` of the top score instead of always the literal best.
     */
    function nearOptimalPick(list, margin) {
      if (!list.length) return null;
      const top = list[0].score;
      const contenders = [];
      for (const s of list) {
        if (top - s.score <= margin) contenders.push(s);
        else break;
      }
      if (contenders.length <= 1) return list[0];
      const minS = contenders[contenders.length - 1].score;
      const idx = weightedPick(contenders.map((c, i) => ({ id: i, w: c.score - minS + 0.4 })));
      return contenders[idx];
    }

    /**
     * Engine fix — Milestone 3: confidence model. A flat near-optimal margin
     * treated every passer identically, but the real premise (disguise,
     * trust, reading pressure a beat ahead) is a skill some players have
     * more of than others. Widens the margin passed to nearOptimalPick for
     * a carrier with real vision/creativity (xa90, key_passes90) — a high-
     * composure playmaker is more willing to deliberately take the
     * second-best option; an average passer stays closer to strict argmax.
     */
    function confidenceMargin(carrier, base) {
      if (!carrier || !carrier.stats) return base;
      const creativity = clamp((carrier.stats.xa90 || 0) * 0.55 + (carrier.stats.key_passes90 || 0) * 0.14, 0, 1.1);
      return base * (1 + creativity * 0.4);
    }

    function isWideChannel(pin) {
      return pin.left < 24 || pin.left > 76;
    }

    function inPenaltyBox(pin) {
      if (!pin) return false;
      const rel = fromPitchPct(pin.side, pin.left, pin.top);
      return rel.depth >= 0.86 && rel.x >= 0.3 && rel.x <= 0.7;
    }

    function nearPenaltyBox(pin) {
      if (!pin) return false;
      const rel = fromPitchPct(pin.side, pin.left, pin.top);
      return !inPenaltyBox(pin) && rel.depth >= 0.7 && rel.x >= 0.22 && rel.x <= 0.78;
    }

    /**
     * Real geometric shot angle (approx pitch meters, 105x68m goal-to-goal),
     * used for the wide-carrier shoot-vs-cross-vs-cutback decision in
     * decideWideFinalThird -- NOT wired into estimateChanceXg's own shot-
     * quality calc, which stays untouched (out of scope for this change).
     * 0deg = no goal visible at all (level with or past the goal line, wide
     * of the post); ~37deg = a central penalty-spot look; grows further as
     * the carrier gets close and central (six-yard box). This is what makes
     * a winger glued to the touchline at the byline correctly read as a
     * near-zero angle (a real "why would he shoot from there" position)
     * while a winger who's cut to the corner of the box gets a real, if
     * modest, angle -- the "rises approaching the box, falls again right at
     * the byline" shape falls straight out of the geometry, no separate
     * hand-tuned byline penalty needed.
     */
    const PITCH_LENGTH_M = 105;
    const PITCH_WIDTH_M = 68;
    const GOAL_HALF_WIDTH_M = 3.66;
    /**
     * Real-world metres between two pin positions. dist() treats left/top
     * as equal-scale percentage points, which is wrong for anything that
     * needs an actual distance -- the left (width) axis spans 68m and the
     * top (length) axis spans 105m, so a raw Euclidean diff in 0-100 space
     * mixes two different real-world scales. Used for carry-distance
     * tracking, where the number is shown to users and needs to mean
     * something.
     */
    function pitchDistM(a, b) {
      const dx = ((a.left - b.left) / 100) * PITCH_WIDTH_M;
      const dy = ((a.top - b.top) / 100) * PITCH_LENGTH_M;
      return Math.hypot(dx, dy);
    }
    function shotAngleDeg(carrier) {
      const rel = fromPitchPct(carrier.side, carrier.left, carrier.top);
      const dx = (rel.x - 0.5) * PITCH_WIDTH_M;
      const dy = Math.max(0.5, (1 - rel.depth) * PITCH_LENGTH_M);
      const aL = Math.atan2(-GOAL_HALF_WIDTH_M - dx, dy);
      const aR = Math.atan2(GOAL_HALF_WIDTH_M - dx, dy);
      return Math.abs(aR - aL) * (180 / Math.PI);
    }
    /** 0-~1.3 normalized version of shotAngleDeg: ~1.0 at a central
     * penalty-spot look, higher for tap-in range, near-0 once the angle
     * closes up (wide of the post / level with the goal line). */
    function shotAngleQuality(carrier) {
      return clamp(shotAngleDeg(carrier) / 37, 0, 1.3);
    }

    /**
     * A wide carrier's box helpers (inPenaltyBox/nearPenaltyBox) are
     * correct, real-geometry checks — x~0.24-0.76 genuinely is the penalty
     * area, and a winger out at x=0.85-0.95 genuinely isn't in it. That was
     * never the bug. The bug: evaluateArrivals (the dominant decision path
     * — checked first, every tick, before any pattern-based fallback) had
     * NO shooting concept at all for the genuinely-wide-but-plausibly-
     * shootable stretch just past the box's edge — isWideChannel's own
     * boundary (x<0.24 or x>0.76) sits almost exactly where
     * nearPenaltyBox's stops, so a carrier out there fell through every
     * priority in evaluateArrivals into an endless dribble/pass loop,
     * never a shot (confirmed via instrumentation: decideWideFinalThird,
     * the older pattern-fallback shoot fix, was never even reached across
     * three full synthetic matches — evaluateArrivals was resolving
     * everything first).
     * Deliberately separate from and narrower than the box helpers — does
     * NOT touch inPenaltyBox/nearPenaltyBox themselves (doShot,
     * countBoxAttackers, boxOccupationReady, attemptSpellChance and others
     * all depend on those staying real-geometry-accurate; widening them
     * globally would ripple into all of those for no reason). Gated on: a
     * real, non-trivial angle (shotAngleQuality — falls to ~0 right at the
     * touchline or the byline, see its own comment), final-third-or-deeper
     * depth, and not already covered by the box helpers above (avoids
     * double-counting evaluateArrivals's own Priority 1).
     */
    function isWideShootingZone(carrier) {
      if (!carrier || !isAttackFinisher(carrier)) return false;
      if (inPenaltyBox(carrier) || nearPenaltyBox(carrier)) return false;
      if (!isWideChannel(carrier)) return false;
      if (possessionDepth(carrier) < 0.68) return false;
      return shotAngleQuality(carrier) > 0.12;
    }

    function fbAttackThreat(pin) {
      if (!pin || pin.role !== "FB") return 0;
      const s = pin.stats;
      return clamp(
        (s.xa90 * 2.4 + s.key_passes90 * 0.38 + s.dribbles90 * 0.32 + s.xg90 * 0.9 + s.shots90 * 0.05) / 2.6,
        0,
        1
      );
    }

    function isWideFinalThird(carrier) {
      if (!carrier) return false;
      const depth = possessionDepth(carrier);
      const wideRole = carrier.role === "W" || carrier.role === "FB";
      return wideRole && isWideChannel(carrier) && depth >= 0.62;
    }

    function sameFlankPartners(carrier, role) {
      return teammates(carrier)
        .filter((m) => m.role === role && Math.abs(m.left - carrier.left) < 30)
        .sort((a, b) => dist(carrier, a) - dist(carrier, b) + (rng() - 0.5) * 2);
    }

    /**
     * Through ball ONLY if runner is moving behind the line + lane exists.
     * Prefer when defender is square and receiver is goalside of the press.
     */
    function throughBallLegal(carrier, runner) {
      if (!carrier || !runner) return false;
      if (!runner._running && !(runner.lockUntil > matchMinute)) return false;
      const rDepth = fromPitchPct(runner.side, runner.left, runner.top).depth;
      const cDepth = possessionDepth(carrier);
      if (rDepth <= cDepth + 0.02) return false;
      const line = defendingOffsideLine(runner.side);
      // Runner must be attacking the space behind / toward the line
      if (rDepth < line - 0.08 && !allowDeepRun(runner.side)) return false;
      // Lane: no opponent tightly between
      const midL = (carrier.left + runner.left) * 0.5;
      const midT = (carrier.top + runner.top) * 0.5;
      const blocker = nearestOpponents(carrier, 16, 3).find((o) => {
        const d = Math.hypot(o.pin.left - midL, o.pin.top - midT);
        return d < 5.5;
      });
      if (blocker) return false;
      // Soft goalside check: runner at least as advanced as nearby marker
      const marker = nearestOpponent(runner, 9);
      if (marker) {
        const mDepth = fromPitchPct(runner.side, marker.pin.left, marker.pin.top).depth;
        if (rDepth + 0.01 < mDepth && rDepth < line - 0.04) return false;
      }
      return true;
    }

    function throughBallAttractive(carrier, runner) {
      if (!throughBallLegal(carrier, runner)) return false;
      const marker = nearestOpponent(runner, 10);
      const square =
        !marker ||
        Math.abs(marker.pin.left - runner.left) < 9 ||
        fromPitchPct(runner.side, marker.pin.left, marker.pin.top).depth <=
          fromPitchPct(runner.side, runner.left, runner.top).depth + 0.02;
      const laneOpen = defendersInLane(carrier, runner) === 0;
      return square && laneOpen && !wouldPassBeOffside(carrier, runner);
    }

    function decideFbWingLink(carrier, stage, depth) {
      const isFB = carrier.role === "FB";
      const isW = carrier.role === "W";
      if (!isFB && !isW) return false;
      const partners = sameFlankPartners(carrier, isFB ? "W" : "FB");
      if (!partners.length) return false;
      const partner = partners[0];
      const threat = fbAttackThreat(isFB ? carrier : partner) + (isW ? carrier.stats.dribbles90 * 0.12 : 0);
      const pick = weightedPick([
        { id: "overlap", w: 1.15 + (isFB ? 0.55 : 0.35) + threat * 0.55 },
        { id: "underlap", w: 0.75 + (isW ? 0.4 : 0.2) + threat * 0.25 },
        { id: "onetwo", w: 0.9 + carrier.stats.pass_pct * 0.006 + partner.stats.pass_pct * 0.004 },
        { id: "to_fb_then_w", w: isW ? 0.2 : 0.7 + threat * 0.35 },
        { id: "decoy", w: isW ? 0.85 + threat * 0.2 : 0.25 },
      ]);

      const sideSign = carrier.baseX >= 0.5 ? 1 : -1;
      const wideX = carrier.baseX >= 0.5 ? 0.93 : 0.07;
      const halfX = clamp(0.5 + sideSign * 0.22, 0.18, 0.82);

      if (pick === "decoy" && isW) {
        // Decoy: W runs inside → CB follows → FB receives in space
        const wantD = clamp(0.7 + rng() * 0.06, 0.64, 0.82);
        const insideX = clamp(0.5 + sideSign * 0.18, 0.22, 0.78);
        const pct = toPitchPct(carrier.side, insideX, wantD);
        carrier.tx = pct.left;
        carrier.ty = pct.top;
        carrier.lockUntil = matchMinute + 0.95;
        carrier._running = true;
        carrier._decoyInside = true;
        const fb = partner.role === "FB" ? partner : sameFlankPartners(carrier, "FB")[0];
        if (fb) {
          const fbPct = toPitchPct(fb.side, wideX, clamp(depth + 0.04, 0.62, 0.88));
          fb.tx = fbPct.left;
          fb.ty = fbPct.top;
          fb.lockUntil = matchMinute + 1.05;
          fb._running = true;
          fb._overlapRun = true;
          say(`Decoy run — ${carrier.short}; ${fb.short} free`, 1.3);
          doPass(carrier, fb, "pass");
          return true;
        }
      }

      if (pick === "overlap") {
        const runner = isFB ? carrier : partner;
        // Overlaps already running when pass arrives — cue run first
        const wantD = clamp(0.78 + threat * 0.12, 0.7, 0.92);
        const pct = toPitchPct(runner.side, wideX, wantD);
        const mid = toPitchPct(runner.side, lerp(runner.baseX, wideX, 0.55), lerp(possessionDepth(runner), wantD, 0.45));
        runner._pathCtrl = { left: mid.left, top: mid.top, from: matchMinute, until: matchMinute + 0.55 };
        runner.tx = pct.left;
        runner.ty = pct.top;
        runner.lockUntil = matchMinute + 1.2;
        runner._running = true;
        runner._overlapRun = true;
        if (carrier.id === runner.id) {
          ballAttached = true;
          setBallTarget(pct.left, pct.top, 0.78, true);
          actionTimer = 0.85 + spellIdlePause() * 0.3;
          say(`Overlap — ${carrier.short}`, 1.25);
          ballFlight = { outcome: "dribble_won" };
          return true;
        }
        say(`Overlap — ${runner.short}`, 1.2);
        doPass(carrier, runner, "pass");
        return true;
      }

      if (pick === "underlap") {
        const runner = isW ? partner : carrier;
        const wantD = clamp(0.72 + threat * 0.1, 0.64, 0.88);
        const pct = toPitchPct(runner.side, halfX, wantD);
        runner.tx = pct.left;
        runner.ty = pct.top;
        runner.lockUntil = matchMinute + 1.05;
        runner._running = true;
        if (carrier.id === runner.id) {
          ballAttached = true;
          setBallTarget(pct.left, pct.top, 0.72, true);
          actionTimer = 0.8 + spellIdlePause() * 0.25;
          say(`Underlap — ${carrier.short}`, 1.2);
          ballFlight = { outcome: "dribble_won" };
          return true;
        }
        say(`Underlap — ${runner.short}`, 1.15);
        doPass(carrier, runner, "pass");
        return true;
      }

      if (pick === "onetwo") {
        const aheadD = clamp(possessionDepth(partner) + 0.06, depth + 0.02, 0.9);
        const partnerRel = fromPitchPct(partner.side, partner.left, partner.top);
        const pct = toPitchPct(partner.side, clamp(partnerRel.x + sideSign * 0.04, 0.08, 0.92), aheadD);
        partner.tx = pct.left;
        partner.ty = pct.top;
        partner.lockUntil = matchMinute + 0.95;
        partner._running = true;
        say(`One-two — ${carrier.short} & ${partner.short}`, 1.25);
        doPass(carrier, partner, "pass");
        return true;
      }

      if (isW) {
        say(`Into the fullback — ${partner.short}`, 1.1);
        doPass(carrier, partner, "pass");
        if (spell) spell.patternHint = "fb_to_w";
        return true;
      }
      const wing = sameFlankPartners(carrier, "W")[0];
      if (wing) {
        say(`Fullback to winger — ${wing.short}`, 1.2);
        doPass(carrier, wing, throughBallLegal(carrier, wing) ? "through" : "pass");
        return true;
      }
      return false;
    }

    function driveIntoBox(carrier) {
      if (!carrier || inPenaltyBox(carrier)) return false;
      // Engine fix — real defensive contest during the drive. This was a
      // fully uncontested cinematic dash: the carrier warped straight to a
      // shooting position with zero chance of being closed down along the
      // way, no matter how many defenders were actually nearby.
      // doDribble/doCarry/doPass all already have a genuine pressure-based
      // contest (this session's earlier work); this function — called from
      // 7 different attacking decision points — was the one place a carrier
      // could always walk into the box unopposed, which is very likely the
      // literal mechanism behind "attacker moves in, defence reacts after,
      // lots of clean 1v1 looks." Mirrors doCarry's dispossession check.
      // Engine fix — a defender mid-recovery (triggerDefensiveBreachReactions
      // fired against this carrier's side within the last ~0.35 match-
      // minutes) is actively scrambling across even though their on-pitch
      // position hasn't caught up to that yet — pressureAt/nearestOpponent
      // only see where they physically are right now, so a fast follow-up
      // action in the same minute as the breach would otherwise find nobody
      // engaged at all. Widen the engagement gate during that window so the
      // covering run actually has a chance to matter instead of always
      // arriving one tick too late to affect anything.
      const scrambling = (breachRecoveryUntil[oppOf(carrier.side)] || 0) > matchMinute;
      // Engine fix — player orientation: a carrier still turning from a
      // back-to-goal reception (resolveBallFlight's pass outcome) is a
      // genuine opening for the defence, same spirit as the scrambling
      // window above.
      const backToGoal = (carrier._backToGoalUntil || 0) > matchMinute;
      const engageRadius = scrambling || backToGoal ? 13 : 9;
      const threat = nearestOpponent(carrier, engageRadius);
      const fieldPressure = pressureAt(carrier.left, carrier.top, carrier.side);
      const engageGate = scrambling || backToGoal ? 12.5 : 8.5;
      const pressureGate = scrambling || backToGoal ? 0.15 : 0.35;
      if ((threat && threat.d < engageGate) || fieldPressure > pressureGate || scrambling || backToGoal) {
        const resist = sideResist(carrier.side);
        const def = sideDefend(oppOf(carrier.side));
        const closeMul = threat ? clamp(1.2 - threat.d / engageRadius, 0.55, 1.2) : 0.7;
        const stopP =
          (0.06 +
            def * 0.11 +
            (threat ? threat.pin.stats.tackles90 * 0.055 : 0) +
            (threat ? threat.pin.stats.interceptions90 * 0.02 : 0) -
            resist * 0.07 -
            carrier.stats.dribbles90 * 0.032 +
            fieldPressure * 0.1 +
            (scrambling ? 0.08 : 0) +
            (backToGoal ? 0.07 : 0) +
            (rng() - 0.5) * 0.04) *
          closeMul;
        if (rng() < clamp(stopP, 0.04, 0.28)) {
          // Bug fix — "attacker is far from the defender but commentary says
          // stopped": the blind 14-unit fallback let a defender who was
          // genuinely nowhere near the actual challenge (threat null, i.e.
          // nobody was within the real engageRadius above) still get named
          // as the one who "stopped" the carrier, with the ball warping
          // straight to wherever that defender happened to be standing and
          // that pin never moving an inch — from the viewer's side,
          // indistinguishable from the attacker just passing it backward.
          // Only credit a real, close-enough-to-plausibly-make-the-
          // challenge defender; if nobody is that close, there's no stop
          // this tick (falls through to the normal advance below).
          const opp = threat?.pin;
          if (opp) {
            pushMatchEvent("dribble_lost", carrier.side, {
              player: carrier.player,
              player_short: carrier.short,
              by: opp.player,
              detail: `stopped by ${opp.short}`,
            });
            say(`${opp.short} stops ${carrier.short}`, 1.35);
            ballAttached = false;
            // Land the ball at the point of the challenge, near the carrier
            // — not warped across to wherever opp was standing — and give
            // opp a real corrective close-down so the pin actually arrives
            // there instead of the ball just floating to a stationary
            // defender.
            const stopAngle = Math.atan2(opp.top - carrier.top, opp.left - carrier.left);
            const closeDist = clamp(dist(carrier, opp) * 0.3, 1, 3.5);
            const landLeft = clamp(carrier.left + Math.cos(stopAngle) * closeDist, 2, 98);
            const landTop = clamp(carrier.top + Math.sin(stopAngle) * closeDist, 2, 98);
            const arc = passArcFor(carrier.left, carrier.top, landLeft, landTop, "pass");
            const dur = clamp(arc.dur, 0.2, 0.4);
            setBallTarget(landLeft, landTop, dur, false, arc.ctrl);
            opp.tx = landLeft;
            opp.ty = landTop;
            opp._running = true;
            opp.lockUntil = matchMinute + dur + 0.3;
            actionTimer = dur + 0.2;
            ballFlight = { outcome: "dribble_lost", interceptor: opp, comment: `${opp.short} closes it down` };
            return false;
          }
        }
        if (threat) triggerDefensiveBreachReactions(threat.pin);
      }
      const rel = fromPitchPct(carrier.side, carrier.left, carrier.top);
      const sideSign = rel.x >= 0.5 ? -1 : 1;
      const wantX = clamp(0.5 + (rel.x - 0.5) * 0.45 + sideSign * 0.02 + (rng() - 0.5) * 0.04, 0.34, 0.66);
      const wantD = clamp(0.88 + rng() * 0.04, 0.87, 0.94);
      const pct = toPitchPct(carrier.side, wantX, wantD);
      const mid = toPitchPct(carrier.side, lerp(rel.x, wantX, 0.4) + sideSign * 0.06, lerp(rel.depth, wantD, 0.45));
      carrier._pathCtrl = { left: mid.left, top: mid.top, from: matchMinute, until: matchMinute + 0.55 };
      carrier.tx = pct.left;
      carrier.ty = pct.top;
      // Was locked/held to +1.05/+0.95 — well past when the run-in (until +0.55)
      // actually finishes, so the striker stood dead still for a stretch waiting
      // for the clock before shooting. Trimmed to a brief take-a-touch beat.
      carrier.lockUntil = matchMinute + 0.75;
      carrier._running = true;
      ballAttached = true;
      setBallTarget(pct.left, pct.top, 0.88, true);
      actionTimer = 0.95 + spellIdlePause() * 0.25;
      say(`${carrier.short} into the box`, 1.25);
      ballFlight = { outcome: "dribble_won" };
      carrier._boxDriveDone = true;
      if (spell) {
        spell.awaitingBoxShot = true;
        spell.chanceDone = true;
        spell.stage = "CHANCE_CREATION";
        spell.awaitingShot = false;
      }
      pendingShot = { side: carrier.side, at: matchMinute + 0.7 };
      return true;
    }

    function oppositeFlankWinger(carrier) {
      const mates = teammates(carrier).filter((m) => m.role === "W" || m.role === "FB");
      if (!mates.length) return null;
      mates.sort((a, b) => Math.abs(b.left - carrier.left) - Math.abs(a.left - carrier.left));
      return Math.abs(mates[0].left - carrier.left) > 14 ? mates[0] : null;
    }

    function crossBoxTarget(carrier, mode) {
      // Engine addition — goal-scoring midfielder archetype (a CM/DM
      // arriving late to meet a cross/cutback, e.g. Gerrard/Lampard).
      const mates = teammates(carrier).filter(
        (m) =>
          m.role === "ST" ||
          m.role === "AM" ||
          m.role === "CM" ||
          m.role === "DM" ||
          (m.role === "W" && Math.abs(m.left - carrier.left) > 18)
      );
      if (!mates.length) return progressiveTarget(carrier);
      const fromLeft = carrier.left < 50;
      // Set-piece Phase 3 — corner delivery modes beyond near/far.
      // "central"/"edge" ignore the near/far post lane entirely (the ball
      // isn't going to either post); "edge" additionally biases toward a
      // CM/AM loitering at the edge of the box for a first-time look
      // rather than the ST/W crowd already inside it.
      const ignoreLane = mode === "central" || mode === "edge";
      mates.sort((a, b) => {
        const aNear = fromLeft ? a.left <= 52 : a.left >= 48;
        const bNear = fromLeft ? b.left <= 52 : b.left >= 48;
        const preferNear = mode === "near" || mode === "cutback";
        const lane = ignoreLane ? 0 : preferNear ? (bNear ? 1 : 0) - (aNear ? 1 : 0) : (aNear ? 1 : 0) - (bNear ? 1 : 0);
        const edgeBias =
          mode === "edge"
            ? (b.role === "CM" || b.role === "AM" ? 1 : 0) - (a.role === "CM" || a.role === "AM" ? 1 : 0)
            : 0;
        return lane * 2 + edgeBias * 1.5 + (b.stats.xg90 - a.stats.xg90) * 1.55 + (rng() - 0.5) * 0.2;
      });
      return mates[0];
    }

    function centralProgressTarget(carrier, stage, depth) {
      const mates = teammates(carrier)
        .filter((m) => m.role === "CM" || m.role === "AM" || m.role === "ST" || m.role === "DM")
        .filter((m) => canPlayForward(carrier, m, stage, depth) || isMidRole(m.role));
      if (!mates.length) return progressiveTarget(carrier);
      const scored = mates.map((m) => {
        const lateral = Math.abs(m.left - 50);
        const hub = m.role === "CM" ? 3.2 : m.role === "AM" ? 2.4 : m.role === "ST" ? 1.2 : 0.6;
        const centralBias = 2.2 - lateral * 0.04;
        const create =
          m.stats.key_passes90 * 0.38 +
          m.stats.xa90 * 1.55 +
          m.stats.pass_pct * 0.005 +
          // How central this player really is to buildup that ends in a
          // shot -- a more direct signal than key_passes90/pass_pct alone.
          (m.stats.xg_buildup90 || 0) * 0.6 +
          (m.stats.xg_chain90 || 0) * 0.3 +
          // A teammate who reliably sets up a genuine big chance next is a
          // better progression target than raw creativity stats capture.
          (m.stats.big_chances_created90 || 0) * 0.5 +
          // Engine addition — a CM/DM's own goal threat now counts toward
          // how attractive they are as a progression target too, not just
          // ST/AM. Smaller coefficient than ST/AM's since arriving late to
          // shoot is a secondary, not primary, job for these roles.
          (m.role === "ST" || m.role === "AM" ? m.stats.xg90 * 0.55 : (m.role === "CM" || m.role === "DM") ? m.stats.xg90 * 0.3 : 0);
        const space = m._running ? 0.9 : 0;
        return { m, score: hub + centralBias + create + space - dist(carrier, m) * 0.02 + rng() * 0.4 };
      });
      scored.sort((a, b) => b.score - a.score);
      return nearOptimalPick(scored, confidenceMargin(carrier, 0.5)).m;
    }

    function throughRunner(carrier, stage, depth) {
      // Engine addition — goal-scoring midfielder archetype (a late CM/DM
      // run through the middle, e.g. Gerrard/Lampard bursting past the
      // last line).
      const runners = teammates(carrier)
        .filter((m) => m.role === "ST" || m.role === "AM" || m.role === "W" || m.role === "CM" || m.role === "DM")
        .filter((m) => canPlayForward(carrier, m, stage, depth))
        .filter((m) => throughBallLegal(carrier, m));
      if (!runners.length) return null;
      const scored = runners.map((m) => {
        const attr = throughBallAttractive(carrier, m) ? 2.4 : 0;
        return { m, score: attr + m.stats.xg90 * 1.45 + m.stats.xa90 * 0.75 - Math.abs(m.left - 50) * 0.01 + rng() * 0.25 };
      });
      scored.sort((a, b) => b.score - a.score);
      return nearOptimalPick(scored, confidenceMargin(carrier, 0.5)).m;
    }

    /**
     * Sticky third-man patterns: CM→ST→CM, FB→W→FB overlap, W→ST→W return.
     */
    function tryThirdManCombo(carrier) {
      if (!spell || !carrier) return false;
      const urg = progressionUrgency(spell);
      const stage = spell.stage || "PROGRESSING";
      const depth = possessionDepth(carrier);
      const last = spell.combo;

      const cueRun = (pin, wideX, wantD, until = 1.1) => {
        if (!pin) return;
        const pct = toPitchPct(pin.side, wideX, wantD);
        pin.tx = pct.left;
        pin.ty = pct.top;
        pin.lockUntil = matchMinute + until;
        pin._running = true;
      };

      // Complete: ST layoff to CM runner
      if (last && last.kind === "cm_st_feet" && carrier.role === "ST") {
        const cm =
          pinById.get(last.fromId) ||
          teammates(carrier)
            .filter((m) => m.role === "CM" || m.role === "AM")
            .sort((a, b) => dist(carrier, a) - dist(carrier, b))[0];
        if (cm && dist(carrier, cm) < 24 && !wouldPassBeOffside(carrier, cm)) {
          if (!cm._running) {
            const wantD = clamp(possessionDepth(cm) + 0.08, 0.55, 0.88);
            cueRun(cm, clamp(cm.baseX, 0.28, 0.72), wantD, 1.05);
            cm._supportRole = cm._supportRole || "third_man";
          }
          spell.combo = { kind: "st_cm_return", fromId: carrier.id, toId: cm.id };
          doPass(carrier, cm, throughBallLegal(carrier, cm) ? "through" : "pass");
          return true;
        }
      }

      // Complete: W return after ST feet
      if (last && last.kind === "w_st_feet" && carrier.role === "ST") {
        const w = pinById.get(last.fromId);
        if (w && dist(carrier, w) < 22 && !wouldPassBeOffside(carrier, w)) {
          spell.combo = { kind: "st_w_return", fromId: carrier.id, toId: w.id };
          doPass(carrier, w, throughBallLegal(carrier, w) ? "through" : "pass");
          return true;
        }
      }

      // Complete: FB overlap after FB→W
      if (last && last.kind === "fb_w_overlap" && carrier.role === "W") {
        const fb = pinById.get(last.fromId);
        if (fb && dist(carrier, fb) < 26 && (fb._overlapRun || fb._running || urg >= 0.5)) {
          spell.combo = { kind: "w_fb_overlap", fromId: carrier.id, toId: fb.id };
          doPass(carrier, fb, throughBallLegal(carrier, fb) ? "through" : "pass");
          return true;
        }
      }

      // Complete: CM/AM give-and-go return after cm_cm_layoff
      if (last && last.kind === "cm_cm_layoff" && (carrier.role === "CM" || carrier.role === "AM")) {
        const passer = pinById.get(last.fromId);
        if (passer && dist(carrier, passer) < 20 && (passer._running || passer.lockUntil > matchMinute || urg >= 0.35)) {
          spell.combo = { kind: "cm_cm_return", fromId: carrier.id, toId: passer.id };
          doPass(carrier, passer, throughBallLegal(carrier, passer) ? "through" : "pass");
          return true;
        }
      }

      // Start: CM → ST feet (set up third-man return)
      if (
        (carrier.role === "CM" || carrier.role === "AM") &&
        urg >= 0.28 &&
        depth >= 0.42 &&
        rng() < 0.26 + urg * 0.16 + (isFinalThirdStage(stage) ? 0.12 : 0)
      ) {
        const sts = teammates(carrier)
          .filter((m) => m.role === "ST" && canPlayForward(carrier, m, stage, depth))
          .filter((m) => defendersInLane(carrier, m) < 2 && !wouldPassBeOffside(carrier, m))
          .sort((a, b) => scoreAttackSequence(carrier, b) - scoreAttackSequence(carrier, a));
        if (sts[0]) {
          const st = sts[0];
          spell.combo = { kind: "cm_st_feet", fromId: carrier.id, toId: st.id };
          // Cue passer or partner CM as third-man runner
          const partner = teammates(carrier).find(
            (m) => (m.role === "CM" || m.role === "AM") && m.id !== carrier.id && dist(m, st) < 28
          );
          const runner = partner || carrier;
          if (runner.id !== carrier.id) {
            cueRun(runner, clamp(lerp(runner.baseX, st.baseX, 0.35), 0.28, 0.72), clamp(depth + 0.1, 0.55, 0.9));
            runner._supportRole = "third_man";
          }
          doPass(carrier, st, "pass");
          return true;
        }
      }

      // Start: FB → W (overlap follows)
      if (carrier.role === "FB" && urg >= 0.25 && rng() < 0.32 + urg * 0.14) {
        const w = sameFlankPartners(carrier, "W")[0];
        if (w && defendersInLane(carrier, w) < 2 && !wouldPassBeOffside(carrier, w)) {
          const wideX = carrier.baseX >= 0.5 ? 0.92 : 0.08;
          cueRun(carrier, wideX, clamp(depth + 0.1, 0.62, 0.9), 1.2);
          carrier._overlapRun = true;
          spell.combo = { kind: "fb_w_overlap", fromId: carrier.id, toId: w.id };
          doPass(carrier, w, "pass");
          return true;
        }
      }

      // Start: W → ST feet
      if (carrier.role === "W" && urg >= 0.3 && depth >= 0.48 && rng() < 0.24 + urg * 0.14) {
        const sts = teammates(carrier)
          .filter((m) => m.role === "ST" && canPlayForward(carrier, m, stage, depth))
          .filter((m) => dist(carrier, m) < 24 && defendersInLane(carrier, m) < 2)
          .sort((a, b) => dist(carrier, a) - dist(carrier, b));
        if (sts[0]) {
          spell.combo = { kind: "w_st_feet", fromId: carrier.id, toId: sts[0].id };
          doPass(carrier, sts[0], "pass");
          return true;
        }
      }

      // Start: CM/AM give-and-go — a quick one-two with a nearby central partner to
      // beat a presser, rather than only ever recycling backward under pressure.
      if (
        (carrier.role === "CM" || carrier.role === "AM") &&
        urg >= 0.22 &&
        depth >= 0.3 &&
        rng() < 0.22 + urg * 0.14
      ) {
        const partner = teammates(carrier)
          .filter((m) => (m.role === "CM" || m.role === "AM") && m.id !== carrier.id)
          .filter((m) => dist(carrier, m) < 18 && defendersInLane(carrier, m) < 2)
          .sort((a, b) => dist(carrier, a) - dist(carrier, b))[0];
        if (partner && !wouldPassBeOffside(carrier, partner)) {
          spell.combo = { kind: "cm_cm_layoff", fromId: carrier.id, toId: partner.id };
          // Cue the passer to run into space for the return ball (the give-and-go).
          cueRun(carrier, clamp(carrier.baseX, 0.22, 0.78), clamp(depth + 0.08, 0.3, 0.85), 1.0);
          carrier._supportRole = "third_man";
          doPass(carrier, partner, "pass");
          return true;
        }
      }

      return false;
    }

    function pickAttackPattern(carrier, stage, depth) {
      const create = sideCreate(carrier.side);
      const atk = sideAttack(carrier.side);
      const possQ = sidePoss(carrier.side);
      const urg = progressionUrgency(spell);
      const ad = attackDefendDelta(carrier.side);
      const hold = possessionHoldDelta(carrier.side);
      const pressD = pressOnBallDelta(carrier.side);
      const edgeL = flankMatchupEdge(carrier.side, "L");
      const edgeR = flankMatchupEdge(carrier.side, "R");
      const bestFlankEdge = Math.max(edgeL, edgeR);
      const st = carrier.stats;
      const mates = teammates(carrier);
      const hasW = mates.some((m) => m.role === "W" || m.role === "FB");
      const hasCM = mates.some((m) => m.role === "CM");
      const threat = nearestOpponent(carrier, 10);
      const last = spell?.lastPattern || spell?.pattern;
      const centralBall = Math.abs(carrier.left - 50) < 20;

      // Engine rebuild — central-carry nerf. wCentral used to pick up the
      // SAME team-quality/passing terms (create/atk/key_passes90/pass_pct)
      // no matter who had the ball or where — a CB or DM with decent passing
      // stats got pulled toward "central" almost as strongly as an actual
      // playmaker, while wWing/wCut only reached comparable magnitude when
      // the carrier was genuinely a W/FB. That role-agnostic inflation was
      // the real source of "central carry is extremely overpowered, wing
      // carry almost never happens" from a full tournament of real play —
      // not a doDribble/doCarry success-rate bias (verified neither
      // function has one). Trimmed the role-agnostic terms here and in
      // wWing/wCut/wSwitch's own bases below; left the genuinely
      // situational signals (CM/AM role bonus, hasCM, centralBall, ad,
      // depth/stage/urgency) untouched.
      // Bug fix — the central-carry nerf (see comment above) overcorrected:
      // a CB/FB/W/ST carrier -- which is most of the match, since
      // defenders start every buildup and wingers/strikers receive the
      // final ball -- had central play crushed by role/position penalties
      // regardless of whether a real midfield outlet actually existed.
      // That's the direct cause of "midfielders almost never involved,
      // it's all CB/FB/W/ST" -- a self-reinforcing loop where the wide
      // carrier's own low wCentral kept choosing wide patterns again.
      // Softened (not reverted) the three worst offenders: the CM/AM role
      // gap, and the two flat penalties for not already being a
      // midfielder/central. Real buildup finds a central outlet from a
      // CB/FB reasonably often; it shouldn't be structurally avoided.
      let wCentral =
        0.85 +
        create * 0.55 +
        atk * 0.15 +
        st.key_passes90 * 0.16 +
        st.pass_pct * 0.003 +
        (carrier.role === "CM" || carrier.role === "AM" ? 0.75 : 0.28) +
        (hasCM ? 0.4 : -0.12) +
        (centralBall ? 0.3 : -0.05) +
        Math.max(0, ad) * 0.55;
      if (depth < 0.5) wCentral += 0.25;
      if (stage === "PROGRESSING") wCentral += 0.2;
      if (urg >= 0.85) wCentral += 0.45 + Math.max(0, ad) * 0.35;

      let wSwitch = hasW
        ? 0.45 + create * 0.4 + st.xa90 * 0.6 + (centralBall ? 0.5 : 0.1) + (carrier.role === "CM" ? 0.25 : 0)
        : 0.04;
      if (bestFlankEdge > 0.15 && (edgeL < -0.05 || edgeR < -0.05)) wSwitch += 0.55 + bestFlankEdge * 0.6;
      if (depth >= 0.35 && depth < 0.72) wSwitch += 0.12;

      let wWing =
        carrier.role === "W" || carrier.role === "FB"
          ? 1.2 + st.dribbles90 * 0.45 + st.xa90 * 1.25 + (isWideChannel(carrier) ? 0.7 : 0.15)
          : hasW
            ? 0.5 + create * 0.4 + (depth > 0.42 ? 0.35 : 0)
            : 0.08;
      if (isWideChannel(carrier) && depth >= 0.55) wWing += 0.65;
      wWing += bestFlankEdge * 0.75;
      if (carrier.role === "W" || carrier.role === "FB") {
        wWing += flankMatchupEdge(carrier.side, pinFlank(carrier)) * 0.9;
      }
      // Bug fix — wWing only ever read season-average matchup/xa stats, no
      // live signal for "my marker is actually beaten right now." Real
      // space beyond the fullback (no opponent within genuine challenge
      // range) should itself pull a winger toward attacking the space, not
      // just his career dribbling average.
      if ((carrier.role === "W" || carrier.role === "FB") && (!threat || threat.d > 10)) {
        wWing += 0.6;
      }

      let wCut =
        carrier.role === "W"
          ? 0.9 + st.dribbles90 * 0.35 + openPlayXg(carrier) * 0.8 + (isWideChannel(carrier) ? 0.5 : 0)
          : carrier.role === "AM"
            ? 0.4 + st.dribbles90 * 0.16 + openPlayXg(carrier) * 0.2
            : 0.12;
      if (depth >= 0.5) wCut += 0.2;
      if (ad > 0.1 && isFinalThirdStage(stage)) wCut += 0.35;
      // A clinical W/AM (own finishing quality + goals90 percentile) drives
      // toward goal themselves more readily than a creator-profile teammate
      // with otherwise similar dribble/xG inputs would.
      wCut += clinicalBoxThreat(carrier) * 0.5;

      let wRecycle =
        0.32 +
        possQ * 0.45 +
        (stage === "BUILD_UP" ? 0.15 : 0.08) +
        (carrier.role === "DM" || carrier.role === "CB" ? 0.45 : 0) +
        (threat && threat.d < 7 ? 0.4 : 0) +
        Math.max(0, hold) * 0.35 +
        Math.max(0, -ad) * 0.45;
      if ((spell?.patternActions || 0) >= 5) wRecycle += 0.25;
      if (spell?.willAttemptChance && (stage === "CHANCE_CREATION" || stage === "BOX_OCCUPATION")) wRecycle *= 0.35;
      // Urgency coefficient: original 0.55, nudged to 0.65 earlier this session,
      // pulled back partway to 0.60 — 0.65 was contributing to runaway one-sided
      // matches on unvalidated production data going into a hard deadline.
      wRecycle *= clamp(1.15 - urg * 0.6 - Math.max(0, ad) * 0.35 + Math.max(0, -pressD) * 0.1, 0.2, 1.15);
      if (hold > 0.12 && urg < 0.55) wRecycle *= 1.15;
      if (isFwdRole(carrier.role) && depth >= 0.66) wRecycle = 0;

      // Possession-control delta: low-poss sides recycle more / progress less unless a maestro has the ball.
      // Starve is capped gently — solid attack units still progress (was min(0.48, ×1.25)).
      const possDelta = sidePoss(carrier.side) - sidePoss(oppOf(carrier.side));
      const maestroOnBall = isMaestroPin(carrier);
      if (possDelta < -0.05) {
        if (maestroOnBall) {
          wCut += 0.38;
          wCentral += 0.22;
          wWing += 0.12;
          wRecycle *= 0.62;
        } else {
          const atk = sideAttack(carrier.side);
          const starveCap = atk >= 0.55 ? 0.22 : atk >= 0.48 ? 0.3 : 0.38;
          const starve = Math.min(starveCap, -possDelta * 0.85);
          wRecycle += starve;
          wCentral *= 0.94;
          wCut *= 0.92;
          wWing *= 0.95;
        }
      }
      // Compact elite defending suppresses progressive entries for sterile high-poss sides
      const supp = possessionSuppressionMul(carrier.side);
      if (supp < 0.96) {
        wCut *= supp;
        wWing *= lerp(1, supp, 0.55);
        wCentral *= lerp(1, supp, 0.4);
        wRecycle += (1 - supp) * 0.6;
      }

      // Engine rebuild — spatial evaluation for pattern selection (Priority 4).
      // Every weight above is squad-quality/urgency/carrier-stat driven; none
      // of them ask whether the specific space each pattern actually needs is
      // open right now — the exact "fixed pattern menu with no space model"
      // gap. Score each pattern's real target zone with the same pressureAt
      // field used everywhere else in the rebuild, and fold that into the
      // existing weights rather than replacing them (pickAttackPattern's
      // squad/urgency signals stay the primary driver; this is a real-time
      // correction on top).
      const relC = fromPitchPct(carrier.side, carrier.left, carrier.top);
      const ownFlank = pinFlank(carrier);
      const farFlank = ownFlank === "L" ? "R" : ownFlank === "R" ? "L" : relC.x > 0.5 ? "L" : "R";
      const farFlankX = farFlank === "L" ? 0.12 : 0.88;
      // Per-action scoring project, Phase B — zoneOpenness promoted to a
      // shared top-level helper (now takes `side` explicitly instead of
      // closing over `carrier`); see its own docstring near pressureAt.
      const centralOpen = zoneOpenness(carrier.side, 0.5, Math.min(0.94, relC.depth + 0.12));
      const farFlankOpen = zoneOpenness(carrier.side, farFlankX, Math.min(0.94, relC.depth + 0.08));
      const ownFlankOpen = zoneOpenness(carrier.side, relC.x, Math.min(0.94, relC.depth + 0.14));
      const halfSpaceX = clamp(relC.x + (relC.x > 0.5 ? -0.18 : 0.18), 0.05, 0.95);
      const halfSpaceOpen = zoneOpenness(carrier.side, halfSpaceX, Math.min(0.94, relC.depth + 0.1));
      wCentral += (centralOpen - 0.5) * 1.1;
      wSwitch += (farFlankOpen - 0.5) * 1.3;
      wWing += (ownFlankOpen - 0.5) * 1.1;
      wCut += (halfSpaceOpen - 0.5) * 1.1;
      wRecycle += (0.5 - Math.max(centralOpen, farFlankOpen, ownFlankOpen, halfSpaceOpen)) * 0.5;

      // Engine fix — protect-the-lead mentality. A side that just scored
      // manages the game for a few minutes: favour holding the ball over
      // immediately committing back forward.
      if ((leadProtectUntil[carrier.side] || 0) > matchMinute) {
        wRecycle *= 1.7;
        wCentral *= 0.7;
        wCut *= 0.6;
        wWing *= 0.75;
        wSwitch *= 0.8;
      }

      const entries = [
        { id: "central", w: wCentral },
        { id: "wide_switch", w: wSwitch },
        { id: "wing_carry", w: wWing },
        { id: "cut_inside", w: wCut },
        { id: "recycle", w: wRecycle },
      ];
      for (const e of entries) {
        if (e.id === last) e.w *= 0.55;
      }
      return weightedPick(entries) || "central";
    }

    function refreshSpellPattern(carrier) {
      if (!spell || spell.side !== possession) return null;
      const stage = spell.stage || "PROGRESSING";
      const depth = possessionDepth(carrier);
      // Confidence-driven re-pick (Priority 4): starts 100, −15/action, re-pick at 0
      // Engine rebuild Phase 4 — spatial evaluation: a pattern is a bet that a
      // certain space stays open. Also force an immediate re-pick if real
      // defensive pressure at the carrier has spiked well past what it was
      // when this pattern was chosen, instead of blindly running the fixed
      // action-count timer while the defence has already closed it down.
      const currentPressure = pressureAt(carrier.left, carrier.top, carrier.side);
      const pressureSpiked =
        spell.pattern &&
        spell.patternBaselinePressure != null &&
        currentPressure > spell.patternBaselinePressure + 0.6;
      const stale = !spell.pattern || (spell.patternConfidence ?? 100) <= 0 || pressureSpiked;
      if (stale) {
        const next = pickAttackPattern(carrier, stage, depth);
        if (spell.pattern && next !== spell.pattern) spell.lastPattern = spell.pattern;
        const changed = next !== spell.pattern;
        spell.pattern = next;
        spell.patternConfidence = 100;
        spell.patternActions = 0;
        spell.patternBaselinePressure = currentPressure;
        if (changed || !spell.patternAnnounced) {
          const labels = {
            central: "Central",
            wide_switch: "Switch",
            wing_carry: "Wing carry",
            cut_inside: "Cut inside",
            recycle: "Recycle",
          };
          say(labels[next] || "Build", 1.3);
          spell.patternAnnounced = true;
        }
      }
      return spell.pattern;
    }

    function executeAttackPattern(carrier, stage) {
      const pattern = refreshSpellPattern(carrier);
      bumpPatternOnAction();
      const depth = possessionDepth(carrier);
      const st = carrier.stats;
      const threat = nearestOpponent(carrier, 11);
      const urg = progressionUrgency(spell);
      const ad = attackDefendDelta(carrier.side);
      const late = isFinalThirdStage(stage);

      if (tryThirdManCombo(carrier)) return true;

      // Through ball as primary chance creator when conditions met
      {
        const runner = depth >= 0.48 || urg >= 0.7 ? throughRunner(carrier, stage, depth) : null;
        if (
          runner &&
          throughBallAttractive(carrier, runner) &&
          (carrier.role === "CM" || carrier.role === "AM" || carrier.role === "W" || carrier.role === "FB") &&
          rng() <
            clamp(
              0.28 +
                st.key_passes90 * 0.12 +
                st.xa90 * 0.22 +
                urg * 0.18 +
                (late ? 0.2 : 0) +
                ad * 0.45 +
                (carrier.role === "CM" || carrier.role === "AM" ? 0.1 : 0),
              0.12,
              0.82
            )
        ) {
          doPass(carrier, runner, "through");
          return true;
        }
      }

      // NOTE: this used to fire unconditionally whenever a winger/FB was simply out
      // wide and deep — pre-empting "cut_inside"/"wing_carry" almost every time.
      // A full exemption (tried earlier this session) over-corrected badly: those
      // patterns carry a high base pattern-selection weight for wingers already,
      // tuned assuming this gate would keep blocking them — removing the gate
      // entirely flipped them from ~never executing to ~always executing,
      // producing runaway one-sided matches (confirmed: blowout scores, >7 xG
      // games, rapid repeat goals). First correction (40%) still ran on
      // unvalidated production data going into a hard deadline — cut further
      // to 20% for more safety margin. Still nonzero (the original bug was
      // "never", not "should always"), just conservative until this can
      // actually be watched play out.
      const allowPatternBreakthrough =
        (pattern === "cut_inside" || pattern === "wing_carry") && rng() < 0.2;
      if (isWideFinalThird(carrier) && stage !== "BUILD_UP" && !allowPatternBreakthrough) {
        return decideWideFinalThird(carrier);
      }

      // High urgency: refuse sterile recycle unless trapped
      if (pattern === "recycle" && urg >= 0.85) {
        const trapped = progressiveLanesBlocked(carrier) && threat && threat.d < 6.2;
        if (!trapped) {
          const prog = progressiveTarget(carrier);
          doPass(carrier, prog, throughBallLegal(carrier, prog) ? "through" : "pass");
          return true;
        }
      }

      if (pattern === "recycle") {
        if (forwardInFinalThird(carrier)) {
          return forwardFinalThirdAction(carrier);
        }
        if (urg < 0.5 && holdTrianglePrefer(carrier)) {
          const tri = teammates(carrier)
            .filter((m) => isLocalTriangleOption(carrier, m))
            .sort((a, b) => scoreAttackSequence(carrier, b) - scoreAttackSequence(carrier, a));
          if (tri[0]) {
            doPass(carrier, tri[0], "pass");
            return true;
          }
        }
        const back = backPassTarget(carrier);
        const dm = teammates(carrier).find((m) => m.role === "DM");
        const cb = teammates(carrier).find((m) => m.role === "CB");
        // Winger close to/in the final third: don't force the explicit CB fallback
        // below — backPassTarget already steered `back` away from CB for this case,
        // so just use it (FB/CM/DM) rather than overriding back to cb anyway.
        const avoidCB = carrier.role === "W" && possessionDepth(carrier) >= 0.58;
        const target = dm || (isDefRole(back?.role) || avoidCB ? back : cb) || back;
        doPass(carrier, target, "pass");
        if (spell) {
          spell.lastPattern = "recycle";
          spell.pattern = null;
          spell.patternConfidence = 100;
          spell.patternActions = 0;
          // Was dropPossessionState(2) — every other recycle/reset call site in this
          // file uses 1 step. Regressing 2 stages (e.g. BOX_OCCUPATION -> PROGRESSING)
          // re-blocked several stage-gated aggressive checks (isFinalThirdStage, the
          // wide-final-third gate, etc.) for longer than a single sideways pass should.
          dropPossessionState(1);
        }
        return true;
      }

      if (pattern === "wide_switch") {
        // Engine rebuild — objectives vs methods (Phase 5), extended past
        // wing_carry. The objective ("switch the point of attack") stays
        // fixed; only the order these methods are tried in now adapts to
        // real pressure — under a swarm, the cross-field switch is the
        // riskiest, slowest-to-execute option, so reach for the available
        // local pass first instead of still looking for the long switch.
        const far = oppositeFlankWinger(carrier);
        const tryFarSwitch = () => {
          // Engine fix — isJustifiedSwitch's own gate (isCrossFieldSwitch's
          // wingPair check) only restricts a W/FB carrier, so a CB reaching
          // this pattern (a live possibility -- wide_switch is a team-level
          // pattern choice, not gated by who's currently on the ball) got
          // isJustifiedSwitch === true unconditionally regardless of
          // distance. oppositeFlankWinger also deliberately picks the MOST
          // extreme lateral option by design, so "justified" alone doesn't
          // bound how far/wide it can be -- add the same absolute realism
          // ceiling longBallTarget holds every long pass to, regardless of
          // carrier role or how the lane/space checks came out.
          if (far && isJustifiedSwitch(carrier, far) && longBallDifficulty(carrier, far) <= 2.3) {
            say(`Switch — ${far.short}`, 1.2);
            doPass(carrier, far, "switch");
            return true;
          }
          return false;
        };
        const tryLocalPass = () => {
          // Unjustified: prefer local FB/CM/supporting winger
          const local = teammates(carrier)
            .filter((m) => !isCrossFieldSwitch(carrier, m) && (m.role === "CM" || m.role === "FB" || m.role === "W" || m.role === "ST"))
            .filter((m) => isLocalTriangleOption(carrier, m) || dist(carrier, m) < 20)
            .sort((a, b) => scoreAttackSequence(carrier, b) - scoreAttackSequence(carrier, a));
          if (local[0]) {
            doPass(carrier, local[0], "pass");
            return true;
          }
          return false;
        };
        const tryCmFallback = () => {
          const cm = teammates(carrier).find((m) => m.role === "CM");
          if (cm) {
            doPass(carrier, cm, "pass");
            return true;
          }
          return false;
        };
        const orderWS = isUnderPressure(carrier)
          ? [tryLocalPass, tryFarSwitch, tryCmFallback]
          : [tryFarSwitch, tryLocalPass, tryCmFallback];
        if (tryInOrder(orderWS)) return true;
      }

      if (pattern === "wing_carry") {
        if (carrier.role === "W" || carrier.role === "FB") {
          // Used to reroute straight back to decideWideFinalThird (cross/cutback/
          // recycle only) once deep+wide — exactly the situation this pattern
          // exists for, so it silently killed fullback/winger combination play
          // (decideFbWingLink below) whenever it would have mattered most.
          const flankEdge = flankMatchupEdge(carrier.side, pinFlank(carrier));
          // Engine rebuild Phase 5 — objectives vs methods. The objective
          // here ("progress down this flank") stays fixed, but the method
          // was always attempted in the same fixed order (link, then pass,
          // then dribble, then carry) regardless of what the defence is
          // doing right now. Every individual method's own odds are
          // untouched below; only the ORDER they're tried in adapts to real
          // pressure — under a swarm, reach for the quick simple release
          // first instead of still looking for the fancy combination.
          const tryLink = () => {
            if (
              (sameFlankPartners(carrier, carrier.role === "FB" ? "W" : "FB").length || spell?.patternHint === "fb_to_w") &&
              rng() <
                0.68 +
                  (carrier.role === "FB" ? fbAttackThreat(carrier) * 0.25 : carrier.stats.dribbles90 * 0.06) +
                  Math.max(0, flankEdge) * 0.25
            ) {
              if (spell?.patternHint === "fb_to_w") spell.patternHint = null;
              if (decideFbWingLink(carrier, stage, depth)) return true;
            }
            return false;
          };
          const tryPass = () => {
            if (carrier.role !== "W") return false;
            const links = linkedOptions(carrier).filter((m) => canPlayForward(carrier, m, stage, depth) || isMidRole(m.role) || m.role === "FB");
            if (links.length && rng() < 0.72) {
              doPass(carrier, links[0], throughBallLegal(carrier, links[0]) ? "through" : "pass");
              return true;
            }
            return false;
          };
          const tryDribble = () => {
            if (rng() < 0.32 + st.dribbles90 * 0.14 + (threat && threat.d < 9 ? 0.12 : 0.05)) {
              doDribble(carrier);
              return true;
            }
            return false;
          };
          const tryCarry = () => {
            if (rng() < 0.4 + st.dribbles90 * 0.04) {
              doCarry(carrier);
              return true;
            }
            return false;
          };
          // Bug fix — real user report: "when wingers get space beyond the
          // fullback, he is just passing backwards. not dribbling past
          // them." The non-pressure branch below used to try tryLink/tryPass
          // FIRST and only fall back to dribble/carry last — but a winger
          // who's genuinely beaten his man is, by definition, not "under
          // pressure" (isUnderPressure reads local pressureAt, which is low
          // exactly when no defender is close), so this was the ordering
          // used in precisely the situation it got wrong: real space ahead
          // led to a reflexive pass, never an attempt to attack the space.
          // Read the same beaten-marker signal directly — no opponent
          // within real challenge range — and go at goal first when it's
          // true, matching what an actual winger does with a run in behind.
          const isolated = !threat || threat.d > 10;
          const order = isUnderPressure(carrier)
            ? [tryCarry, tryDribble, tryPass, tryLink]
            : isolated
              ? [tryDribble, tryCarry, tryPass, tryLink]
              : [tryLink, tryPass, tryDribble, tryCarry];
          if (tryInOrder(order)) return true;
          if (decideFbWingLink(carrier, stage, depth)) return true;
          const flank = teammates(carrier)
            .filter((m) => (m.role === "W" || m.role === "FB") && Math.abs(m.left - carrier.left) < 22)
            .filter((m) => canPlayForward(carrier, m, stage, depth));
          if (flank.length) {
            doPass(carrier, flank[0], "pass");
            return true;
          }
        } else {
          const wing = teammates(carrier)
            .filter((m) => m.role === "W" || m.role === "FB")
            .sort(
              (a, b) =>
                flankMatchupEdge(carrier.side, pinFlank(b)) * 1.2 +
                possessionDepth(b) -
                possessionDepth(a) +
                (b.stats.dribbles90 - a.stats.dribbles90) * 0.22 +
                (b.stats.xa90 - a.stats.xa90) * 0.8 +
                (b.role === "FB" ? fbAttackThreat(b) : 0) * 0.55 -
                (a.role === "FB" ? fbAttackThreat(a) : 0) * 0.55 -
                flankMatchupEdge(carrier.side, pinFlank(a)) * 1.2
            );
          if (wing.length) {
            const pick = wing[0];
            if (pick.role === "FB" && spell) spell.patternHint = "fb_to_w";
            if (pick.role === "W" && Math.abs(carrier.left - 50) < 22) {
              const fb = sameFlankPartners(pick, "FB")[0];
              if (fb) {
                const wideX = fb.baseX >= 0.5 ? 0.92 : 0.08;
                const pct = toPitchPct(fb.side, wideX, clamp(0.74, 0.66, 0.88));
                fb.tx = pct.left;
                fb.ty = pct.top;
                fb.lockUntil = matchMinute + 1.15;
                fb._running = true;
                fb._overlapRun = true;
              }
            }
            let kind = Math.abs(pick.left - carrier.left) > 26 ? "switch" : "pass";
            if (kind === "switch" && !isJustifiedSwitch(carrier, pick)) kind = "pass";
            if (kind === "switch") say(`Switch — ${pick.short}`, 1.15);
            doPass(carrier, pick, kind);
            return true;
          }
        }
      }

      if (pattern === "cut_inside") {
        if (carrier.role === "W" || (carrier.role === "AM" && isWideChannel(carrier))) {
          // Engine rebuild — objectives vs methods (Phase 5), extended past
          // wing_carry. The objective ("cut inside and create") stays fixed;
          // only the order these three methods are tried in now adapts to
          // real pressure — under a swarm, the ambitious drive/shoot sequence
          // is the riskiest option, so release the ball to whoever's already
          // in a good spot first instead of still trying to carry through
          // traffic.
          const tryShootSeq = () => {
            if (
              depth >= 0.72 &&
              Math.abs(carrier.left - 50) < 28 &&
              rng() < 0.4 + st.xg90 * 0.45 + Math.max(0, ad) * 0.35 + urg * 0.08
            ) {
              // Bug fix — same class as the attemptSpellChance/decideAction
              // fixes: gate the shot on the carrier's own box proximity, not
              // team box-readiness. The outer depth/left check above is a
              // loose "final third, central-ish" gate, not a real box-
              // proximity check, so without this a CM/DM with modest attacking
              // stats could shoot from genuine range once teammates were
              // already positioned inside the box.
              if (!inPenaltyBox(carrier) && !nearPenaltyBox(carrier)) {
                const slip = throughRunner(carrier, stage, depth);
                if (slip && urg >= 0.7) {
                  doPass(carrier, slip, "through");
                  return true;
                }
                doPass(carrier, progressiveTarget(carrier), "pass");
                return true;
              }
              if (!inPenaltyBox(carrier) && (carrier.role === "AM" || st.xg90 > 0.28 || ad > 0.12)) {
                return Boolean(driveIntoBox(carrier));
              }
              doShot(carrier, false);
              return true;
            }
            return false;
          };
          const tryCutDribble = () => {
            if (rng() < 0.5 + st.dribbles90 * 0.12) {
              const attackSign = carrier.side === "home" ? -1 : 1;
              const sideSign = carrier.left < 50 ? 1 : -1;
              // Engine fix — this used one fixed geometric template every
              // time (shift sideways a bit, curve back toward centre),
              // regardless of where the actual space or the marker was, so
              // every cut inside looked identical. Sample a few real
              // candidate directions (sharp diagonal, shallow horizontal
              // drift, diagonal-forward) using the same pressureAt field
              // everything else in the file already uses for "how open is
              // this spot", biased away from the nearest marker, and pick
              // whichever direction is actually free -- the objective is
              // finding space, not walking one scripted shape.
              const marker = nearestOpponent(carrier, 10);
              const reach = 9 + rng() * 5;
              const candidates = [
                { ax: 0.85, ay: 0.25 }, // sharp diagonal cut toward centre
                { ax: 1.0, ay: 0.05 }, // shallow horizontal drift for space
                { ax: 0.55, ay: 0.65 }, // diagonal while still driving forward
              ];
              let best = null;
              let bestOpenness = -Infinity;
              for (const c of candidates) {
                const px = clamp(carrier.left + sideSign * c.ax * reach, 12, 88);
                const py = clamp(carrier.top + attackSign * c.ay * reach, 5, 95);
                const markerPull =
                  marker && marker.d < 8 ? clamp(1 - dist({ left: px, top: py }, marker.pin) / 12, 0, 1) : 0;
                const openness = 1 / (1 + pressureAt(px, py, carrier.side)) - markerPull * 0.5;
                if (openness > bestOpenness) {
                  bestOpenness = openness;
                  best = { px, py };
                }
              }
              const midX = clamp(lerp(carrier.left, best.px, 0.5 + (rng() - 0.5) * 0.2), 15, 85);
              const midY = clamp(lerp(carrier.top, best.py, 0.45 + (rng() - 0.5) * 0.2), 5, 95);
              const nx = clamp(best.px + (rng() - 0.5) * 3, 15, 85);
              const ny = clamp(best.py + (rng() - 0.5) * 3, 5, 95);
              carrier._pathCtrl = { left: midX, top: midY, from: matchMinute, until: matchMinute + 0.5 };
              carrier.tx = nx;
              carrier.ty = ny;
              carrier.lockUntil = matchMinute + 0.95;
              carrier._decoyInside = true;
              ballAttached = true;
              setBallTarget(nx, ny + attackSign * -0.4, 0.7, true);
              actionTimer = 0.82 + spellIdlePause() * 0.3;
              say(`${carrier.short} cuts inside`, 1.25);
              ballFlight = { outcome: "dribble_won" };
              return true;
            }
            return false;
          };
          const tryPassToShooter = () => {
            const slip = throughRunner(carrier, stage, depth) || shooterTarget(carrier);
            if (slip.id !== carrier.id && rng() < 0.55 + urg * 0.12 + Math.max(0, ad) * 0.2) {
              doPass(carrier, slip, throughBallLegal(carrier, slip) ? "through" : "pass");
              return true;
            }
            return false;
          };
          const orderCI = isUnderPressure(carrier)
            ? [tryPassToShooter, tryCutDribble, tryShootSeq]
            : [tryShootSeq, tryCutDribble, tryPassToShooter];
          if (tryInOrder(orderCI)) return true;
        } else {
          const winger = teammates(carrier)
            .filter((m) => m.role === "W")
            .sort(
              (a, b) =>
                flankMatchupEdge(carrier.side, pinFlank(b)) +
                b.stats.dribbles90 * 1.15 +
                b.stats.xa90 * 0.9 -
                (flankMatchupEdge(carrier.side, pinFlank(a)) + a.stats.dribbles90 * 1.15 + a.stats.xa90 * 0.9)
            );
          if (winger.length) {
            doPass(carrier, winger[0], "pass");
            return true;
          }
        }
      }

      // central
      // Engine rebuild — objectives vs methods (Phase 5), extended past
      // wing_carry. The objective ("progress centrally") stays fixed; only
      // the order these methods are tried in now adapts to real pressure —
      // under a swarm, reach for the quick release (dribble away or a safe
      // carry) before still looking for the elaborate through-ball. The
      // unconditional doCarry at the very end is unchanged from before this
      // patch — every path through this block must still always resolve to
      // some action, so it stays as the guaranteed last resort regardless of
      // how the earlier methods get reordered.
      {
        const tryDribbleClose = () => {
          if (threat && threat.d < 9 && rng() < 0.32 + st.dribbles90 * 0.09) {
            doDribble(carrier);
            return true;
          }
          return false;
        };
        const tryThrough = () => {
          const runner = depth >= 0.5 || urg >= 0.65 ? throughRunner(carrier, stage, depth) : null;
          if (
            runner &&
            (carrier.role === "CM" || carrier.role === "AM" || carrier.role === "W") &&
            rng() <
              clamp(
                0.32 +
                  st.key_passes90 * 0.12 +
                  st.xa90 * 0.25 +
                  (carrier.role === "CM" ? 0.14 : 0) +
                  urg * 0.16 +
                  (late ? 0.18 : 0) +
                  ad * 0.4,
                0.15,
                0.85
              )
          ) {
            doPass(carrier, runner, "through");
            return true;
          }
          return false;
        };
        const tryPass = () => {
          if (rng() < (carrier.role === "CM" ? 0.78 : 0.62)) {
            doPass(carrier, centralProgressTarget(carrier, stage, depth), "pass");
            return true;
          }
          return false;
        };
        const tryCarryGated = () => {
          if (rng() < 0.4 + st.dribbles90 * 0.04) {
            doCarry(carrier);
            return true;
          }
          return false;
        };
        const orderC = isUnderPressure(carrier)
          ? [tryDribbleClose, tryCarryGated, tryThrough, tryPass]
          : [tryDribbleClose, tryThrough, tryPass, tryCarryGated];
        if (tryInOrder(orderC)) return true;
        doCarry(carrier);
        return true;
      }
    }

    function holdTrianglePrefer(carrier) {
      return possessionHoldDelta(carrier.side) > 0.08 || attackDefendDelta(carrier.side) < -0.05;
    }

    function decideWideFinalThird(carrier) {
      const create = sideCreate(carrier.side);
      const aerialDef = sideAerial(oppOf(carrier.side));
      const aerialAtk = strikerAerialThreat(carrier.side);
      const threat = nearestOpponent(carrier, 9);
      const ready = boxOccupationReady(carrier.side);
      const urg = progressionUrgency(spell);
      const ad = attackDefendDelta(carrier.side);
      const flankEdge = flankMatchupEdge(carrier.side, pinFlank(carrier));
      const aerialEdge = aerialAtk - aerialDef;

      // Structural fix — this function used to be cross/cutback/recycle
      // ONLY, with no shooting branch at all, no matter how deep the
      // carrier got. A winger glued to the touchline (isWideChannel) who
      // beat his man and reached the byline unmarked still could only
      // deliver or recycle -- the shot was architecturally unavailable,
      // not just low-probability. Recognize a genuine wide-box shooting
      // opportunity first: real geometric angle (shotAngleQuality, falls
      // toward 0 both far from goal AND right on the byline wide of the
      // post) combined with the carrier's own finishing signal
      // (finisherQuality) and how tightly marked he is. Only even offered
      // when boxed or near-box -- outside the box this stays cross/
      // cutback/recycle exactly as before.
      const boxed = inPenaltyBox(carrier);
      const nearBox = !boxed && nearPenaltyBox(carrier);
      const angleQ = shotAngleQuality(carrier);
      let shootW = 0;
      if ((boxed || nearBox) && angleQ > 0.12 && isAttackFinisher(carrier)) {
        // Per-action scoring project, Phase A — shared with evaluateArrivals's
        // wide-shooting-zone check via scoreShot(carrier). Scaled ~1.1x to
        // preserve this function's pre-existing weight scale relative to
        // crossW/cutbackW/recycleW below — this is a relative weightedPick
        // weight, not a raw probability, so scoreShot's 0-0.75 clamp alone
        // would understate it here.
        shootW = scoreShot(carrier) * 1.1;
      }

      const crossW =
        0.9 +
        carrier.stats.xa90 * 1.85 +
        carrier.stats.key_passes90 * 0.1 +
        create * 0.45 -
        aerialDef * 0.75 +
        aerialAtk * 0.55 +
        aerialEdge * 0.65 +
        (carrier.role === "W" ? 0.2 : 0.05) +
        (ready ? 0.35 : -0.25) +
        Math.max(0, flankEdge) * 0.35;
      const cutbackW =
        0.55 +
        carrier.stats.key_passes90 * 0.28 +
        carrier.stats.xa90 * 0.55 +
        create * 0.35 +
        (threat && threat.d < 6 ? 0.25 : 0) +
        (ready ? 0.4 : -0.15) +
        Math.max(0, flankEdge) * 0.55 +
        Math.max(0, ad) * 0.25 +
        urg * 0.12;
      let recycleW =
        0.38 + sidePoss(carrier.side) * 0.4 + (threat && threat.d < 5.5 ? 0.35 : 0) + (ready ? 0 : 0.55);
      // Original 0.5, nudged to 0.58 earlier this session, pulled back partway
      // to 0.54 alongside pickAttackPattern's wRecycle for the same reason.
      recycleW *= clamp(1.1 - urg * 0.54 - Math.max(0, ad) * 0.3, 0.2, 1.1);
      if (forwardInFinalThird(carrier) || fbDeepInBox(carrier)) recycleW = 0;
      const options = [
        { id: "cross", w: Math.max(0.05, crossW) },
        { id: "cutback", w: cutbackW },
        { id: "recycle", w: recycleW },
      ];
      if (shootW > 0) options.push({ id: "shoot", w: shootW });
      const pick = weightedPick(options);

      if (pick === "shoot") {
        say(`${carrier.short} goes himself — shoots!`, 1.35);
        doShot(carrier, false);
        return true;
      }

      if ((pick === "recycle" || (!ready && rng() < 0.55 - urg * 0.2)) && urg < 1.05 && !fbDeepInBox(carrier)) {
        if (forwardInFinalThird(carrier)) {
          return forwardFinalThirdAction(carrier);
        }
        doPass(carrier, backPassTarget(carrier), "pass");
        if (spell) {
          spell.lastPattern = spell.pattern || "wing_carry";
          spell.pattern = null;
          spell.patternConfidence = 100;
          spell.patternActions = 0;
          dropPossessionState(1);
        }
        return true;
      }

      // Prefer cutback when aerial defence dominates; cross when ST aerial matchup favours attack
      let modePick = pick;
      if (pick === "cross" && aerialEdge < -0.12 && cutbackW > crossW * 0.75) modePick = "cutback";
      if (pick === "recycle" && urg >= 1.05) modePick = aerialEdge > 0 ? "cross" : "cutback";

      const postMode = modePick === "cutback" ? "cutback" : rng() < 0.55 ? "near" : "far";
      const target = crossBoxTarget(carrier, postMode);
      cueBoxRuns(carrier, postMode);
      cueDefensiveBoxCover(oppOf(carrier.side));
      if (spell) {
        spell.awaitingShot = true;
        if (spell.stage === "FINAL_THIRD" || spell.stage === "BOX_OCCUPATION") {
          spell.stage = "CHANCE_CREATION";
        }
      }
      say(modePick === "cross" ? `Cross incoming — ${target.short}` : `Cutback — ${target.short}`, 1.35);
      doPass(carrier, target, modePick === "cross" ? "cross" : "cutback");
      return true;
    }

    function cueBoxRuns(carrier, mode) {
      // Set-piece Phase 3 — a short corner isn't being crossed in yet, so
      // don't cue box runs prematurely; whatever happens after the short
      // pass goes through the normal engine decision loop instead.
      if (mode === "short") return;
      const fromLeft = carrier.left < 50;
      const nearX = fromLeft ? 0.38 : 0.62;
      const farX = fromLeft ? 0.64 : 0.36;
      const cutX = fromLeft ? 0.44 : 0.56;
      const centralX = 0.5;
      for (const pin of teammates(carrier)) {
        // Engine fix — only ST/AM used to get sent into the box for a cross;
        // the OTHER winger (not the one delivering it) stayed put at the
        // edge instead of making a far-post run, so "everyone standing at
        // the edge" included a player who should clearly be arriving too.
        if (pin.role !== "ST" && pin.role !== "AM" && pin.role !== "W") continue;
        const useNear =
          mode === "near" || mode === "cutback" ? pin.baseX < 0.5 === fromLeft : pin.baseX < 0.5 !== fromLeft;
        const tx =
          mode === "cutback"
            ? cutX
            : mode === "central" || mode === "edge"
              ? centralX + (pin.baseX < 0.5 ? -0.06 : 0.06)
              : useNear
                ? nearX
                : farX;
        const depthWant = clamp(0.88 + (pin.role === "ST" ? 0.04 : 0.01), 0.85, 0.94);
        // Allow intentional box runs to 0.90+ when occupation state demands
        const safePct = toPitchPct(pin.side, tx, depthWant);
        pin.tx = safePct.left;
        pin.ty = safePct.top;
        pin.lockUntil = matchMinute + 1.15;
        pin._running = true;
      }
    }

    // Engine fix — nothing on the defending side reacted at all when a
    // cross was cued; only the attacking box runs (cueBoxRuns above) were
    // wired up, so defenders just stood at the edge of the box instead of
    // tracking back to actually mark the incoming runners. Pulls CB/FB/DM
    // toward their own goal (not the whole side -- own attackers shouldn't
    // retreat for a regular open-play cross the way retreatDefensiveShape
    // pulls everyone back for a penalty/dangerous free kick).
    function cueDefensiveBoxCover(defSide) {
      for (const pin of pinsOf(defSide)) {
        if (pin.role !== "CB" && pin.role !== "FB" && pin.role !== "DM") continue;
        const depthWant = Math.min(pin.baseDepth, 0.12);
        const pct = toPitchPct(pin.side, pin.baseX, depthWant);
        pin.tx = pct.left;
        pin.ty = pct.top;
        pin.lockUntil = matchMinute + 1.15;
        pin._running = true;
      }
    }

    function gkOf(side) {
      return pinsOf(side).find((p) => p.role === "GK") || pinsOf(side)[0];
    }

    /** Pitch % into the attacking goal mouth (between posts, in the net — not the D). */
    function attackGoalTop(side) {
      return side === "home" ? 1.35 : 98.65;
    }

    /** Horizontal aim inside the goal mouth (~14% wide, centered). */
    function attackGoalLeft() {
      return clamp(50 + (rng() - 0.5) * 7.5, 46.5, 53.5);
    }

    function possessionDepth(carrier) {
      if (!carrier) return 0.4;
      const rel = fromPitchPct(carrier.side, carrier.left, carrier.top);
      return clamp(rel.depth, 0, 1);
    }

    function updatePhaseFromBall() {
      if (spell && spell.side === possession) {
        phase = spell.stage || "BUILD_UP";
        return;
      }
      const c = findCarrier();
      const d = possessionDepth(c);
      const boxed = c ? countBoxAttackers(c.side) : 0;
      if (d < 0.35) phase = "BUILD_UP";
      else if (d < 0.52) phase = "PROGRESSING";
      else if (d < 0.68 && boxed < 1) phase = "FINAL_THIRD";
      else if (boxed >= 1 || d >= 0.72) phase = "BOX_OCCUPATION";
      else phase = "FINAL_THIRD";
    }

    /** Second-last defender depth in the attacking team's coordinate system (FIFA offside line). */
    function defendingOffsideLine(attackingSide) {
      const defs = pinsOf(oppOf(attackingSide));
      const depths = defs
        .map((d) => fromPitchPct(attackingSide, d.left, d.top).depth)
        .sort((a, b) => b - a);
      if (!depths.length) return 0.55;
      if (depths.length === 1) return depths[0];
      return depths[1];
    }

    /**
     * Offside if receiver is beyond both the ball and the second-last defender
     * (and roughly in the opponents' half). Positions are pitch %; ball = pass origin.
     */
    function isOffsidePosition(side, left, top, ballLeft, ballTop) {
      const prog = fromPitchPct(side, left, top).depth;
      const ballProg = fromPitchPct(side, ballLeft, ballTop).depth;
      if (prog <= 0.5) return false;
      const line = defendingOffsideLine(side);
      return prog > line + 0.01 && prog > ballProg + 0.01;
    }

    function wouldPassBeOffside(passer, receiver, recvLeft, recvTop) {
      if (!passer || !receiver || receiver.role === "GK") return false;
      return isOffsidePosition(
        receiver.side,
        recvLeft ?? receiver.left,
        recvTop ?? receiver.top,
        passer.left,
        passer.top
      );
    }

    function whistleOffside(attacker) {
      pushMatchEvent("offside", attacker.side, {
        player: attacker.player,
        player_short: attacker.short,
        detail: "flagged offside",
      });
      say(`Offside! ${attacker.short}`, 1.9);
      flashEl.hidden = false;
      flashEl.className = "tactic-flash offside";
      flashEl.textContent = "OFFSIDE!";
      flashTimer = 1.15;
      ballAttached = false;
      const defSide = oppOf(attacker.side);
      const taker =
        pinsOf(defSide).find((p) => p.role === "CB") ||
        pinsOf(defSide).find((p) => p.role === "DM" || p.role === "FB") ||
        gkOf(defSide);
      const fk = toPitchPct(defSide, taker.baseX, Math.min(0.35, fromPitchPct(defSide, taker.left, taker.top).depth + 0.05));
      setBallTarget(fk.left, fk.top, 0.35, false);
      actionTimer = 1.15;
      spell = null;
      ballFlight = {
        outcome: "pass",
        pin: taker,
        lockRun: false,
        thenShot: false,
      };
    }

    /**
     * Engine addition — line-breaking run threat. Real defences don't only
     * drop because the ball itself is deep; a winger/fullback/striker
     * making a genuine run toward or past the CURRENT offside line forces
     * the block deeper regardless of where the ball or its carrier
     * currently sit — otherwise that runner is played through, or (per
     * the user's own framing) pins the striker level with the last
     * defender so a cutback/cross opens the defence up. countArrivingRunners
     * only ever credits a runner AFTER they're already near the box; this
     * is the proactive version, keyed off the actual offside line rather
     * than a fixed depth threshold, and off where the runner is HEADING
     * (tx/ty) rather than where they already are.
     */
    function lineBreakingRunThreat(side) {
      const atkSide = oppOf(side);
      if (possession !== atkSide) return 0;
      const offLine = defendingOffsideLine(atkSide);
      let maxThreat = 0;
      for (const p of pinsOf(atkSide)) {
        if (p.role !== "W" && p.role !== "FB" && p.role !== "ST") continue;
        if (!(p._running || p.lockUntil > matchMinute)) continue;
        const headingTo = fromPitchPct(atkSide, p.tx ?? p.left, p.ty ?? p.top).depth;
        const threat = clamp((headingTo - (offLine - 0.15)) / 0.15, 0, 1);
        if (threat > maxThreat) maxThreat = threat;
      }
      return maxThreat;
    }

    /**
     * Continuous 0–1 defensive pressure (box / chance). Not binary — blends ball depth,
     * near/in-box presence, attackers in box, and attacking spell stage.
     */
    function defensivePressureThreat(side) {
      const atkSide = oppOf(side);
      const relBall = fromPitchPct(side, ball.left, ball.top);
      const ballD = clamp(relBall.depth, 0, 1);
      // Own-goal is depth 0: pressure rises as the ball advances into our half / box
      const depthThreat = clamp((0.52 - ballD) / 0.42, 0, 1);

      const carrier = findCarrier();
      let boxThreat = 0;
      if (carrier && carrier.side === atkSide) {
        if (inPenaltyBox(carrier)) boxThreat = 1;
        else if (nearPenaltyBox(carrier)) boxThreat = 0.58;
        else {
          const ad = fromPitchPct(atkSide, carrier.left, carrier.top).depth;
          boxThreat = clamp((ad - 0.6) / 0.3, 0, 0.48);
        }
      } else {
        const atkBall = fromPitchPct(atkSide, ball.left, ball.top);
        boxThreat = clamp((atkBall.depth - 0.62) / 0.32, 0, 0.72);
      }

      const boxed = countBoxAttackers(atkSide);
      const arriving = countArrivingRunners(atkSide);
      const boxCountThreat = clamp(boxed / 2.4 + arriving * 0.12, 0, 1);

      const stage =
        spell && spell.side === atkSide
          ? spell.stage
          : possession === atkSide
            ? phase
            : null;
      const stageThreat =
        stage === "FINISH"
          ? 1
          : stage === "CHANCE_CREATION"
            ? 0.88
            : stage === "BOX_OCCUPATION"
              ? 0.72
              : stage === "FINAL_THIRD" || stage === "final" || stage === "chance"
                ? 0.4
                : stage === "PROGRESSING" || stage === "progress"
                  ? 0.12
                  : 0;

      return clamp(depthThreat * 0.36 + boxThreat * 0.26 + boxCountThreat * 0.16 + stageThreat * 0.3, 0, 1);
    }

    function teamBlockLines(side, attacking) {
      const relBall = fromPitchPct(side, ball.left, ball.top);
      const pushSit = instrBias(side);
      const threeBack = isThreeBackFormation(side === "home" ? homeTeam.formation : awayTeam.formation);
      // Engine addition — the baseline line height itself used to be
      // identical for every team, only ever moving in reaction to ball
      // position/threat. Real teams don't: a side with genuinely strong,
      // positionally disciplined defenders and effective pressing holds a
      // higher resting line; a side without that quality sits deeper by
      // default, not just when directly under the ball. Reuses the same
      // composite defensive/pressing scores (sideDefend/sidePress) already
      // driving individual duels elsewhere, so a team's line height and
      // its actual defending ability stay consistent with each other.
      const lineQuality = clamp((sideDefend(side) - 0.56) * 0.5 + (sidePress(side) - 0.48) * 0.35, -0.09, 0.09);
      let defLine;
      let midLine;
      let atkLine;
      let boxThreat = 0;
      if (attacking) {
        defPressureSmooth[side] = lerp(defPressureSmooth[side], 0, 0.1);
        const shift =
          phase === "BUILD_UP" || phase === "build"
            ? 0.06
            : phase === "PROGRESSING" || phase === "progress"
              ? 0.16
              : phase === "FINAL_THIRD" || phase === "final"
                ? 0.26
                : phase === "BOX_OCCUPATION" || phase === "CHANCE_CREATION" || phase === "FINISH" || phase === "chance"
                  ? 0.3
                  : 0.22;
        defLine = clamp(0.2 + shift + pushSit * 0.035 + lineQuality, 0.14, 0.4);
        midLine = clamp(0.38 + shift + pushSit * 0.045, 0.3, 0.6);
        atkLine = clamp(0.54 + shift + pushSit * 0.055, 0.46, 0.86);
        // Keep block compact: attack line not wildly ahead of defence
        atkLine = Math.min(atkLine, defLine + 0.48);
        midLine = clamp(midLine, defLine + 0.12, atkLine - 0.08);
        if (threeBack) {
          // Keep midfield connected to the back three while attacking
          midLine = clamp(midLine - 0.03, defLine + 0.1, atkLine - 0.08);
        }
      } else {
        const ballD = clamp(relBall.depth, 0, 1);
        const rawThreat = defensivePressureThreat(side);
        // Gradual: EMA so lines ease deeper as pressure builds (no snap)
        defPressureSmooth[side] = lerp(defPressureSmooth[side], rawThreat, 0.13);
        boxThreat = defPressureSmooth[side];

        defLine = clamp(0.14 + ballD * 0.2 - pushSit * 0.04 + lineQuality, 0.1, 0.36);
        midLine = clamp(defLine + 0.15, 0.22, 0.52);
        atkLine = clamp(defLine + 0.28, 0.34, 0.64);
        if (threeBack) {
          // Deeper resting midfield — protect the back three, less push
          midLine = clamp(defLine + 0.1, 0.18, 0.44);
          atkLine = clamp(defLine + 0.22, 0.28, 0.56);
        }
        // Progressive drop-back: compress toward own goal / protect ball→goal corridor
        if (boxThreat > 0.02) {
          const coverDepth = clamp(Math.min(relBall.depth - 0.02, 0.14), 0.055, 0.2);
          defLine = lerp(defLine, coverDepth, boxThreat * 0.9);
          midLine = lerp(midLine, clamp(defLine + (threeBack ? 0.08 : 0.11), 0.12, 0.38), boxThreat * 0.78);
          atkLine = lerp(atkLine, clamp(defLine + (threeBack ? 0.18 : 0.22), 0.2, 0.5), boxThreat * 0.55);
        }
        // Engine addition — a winger/fullback/striker actually running
        // toward or past the offside line pulls the block deeper on its
        // own, separate from (and on top of) the diffuse ball-depth/box-
        // count/stage blend above. This is the direct feedback loop real
        // defences run: drop now, or that runner (or the striker sitting
        // on the shoulder) is in behind.
        const runThreat = lineBreakingRunThreat(side);
        if (runThreat > 0.05) {
          const runCoverDepth = clamp(defLine - 0.1, 0.06, defLine);
          defLine = lerp(defLine, runCoverDepth, runThreat * 0.7);
          midLine = lerp(midLine, clamp(defLine + (threeBack ? 0.08 : 0.11), 0.12, 0.38), runThreat * 0.55);
        }
      }

      // Engine fix — Milestone 2: team elasticity, width dimension. Depth/
      // line compactness above already breathes with pressure and attacking
      // stage; width never did — every pin computed its own lateral (x)
      // position more or less independently, so the team never visibly
      // stretched for a switch or squeezed as a whole unit under real
      // central danger. One shared, per-side width multiplier (applied to
      // every pin's distance from the pitch centreline in updateTeamShape),
      // plus an explicit Zone 14 (the dangerous central channel just
      // outside the box) compression trigger on top of the general
      // pressure-driven target.
      const inZone14 = relBall.depth > 0.72 && relBall.depth < 0.9 && Math.abs(relBall.x - 0.5) < 0.24;
      let widthTarget = attacking
        ? phase === "BUILD_UP" || phase === "PROGRESSING"
          ? 1.12
          : phase === "FINAL_THIRD"
            ? 1.04
            : 0.9 // BOX_OCCUPATION/CHANCE_CREATION/FINISH — funnel narrow toward goal
        : 1.0 - boxThreat * 0.22;
      if (inZone14) widthTarget -= attacking ? 0.02 : 0.1;
      widthTarget = clamp(widthTarget, 0.82, 1.16);

      // Anticipate a genuine tactical shift (attacking stage / possession
      // just changed) quickly; otherwise ease slowly so width doesn't chase
      // every small ball wobble — "line delays, line recovers" rather than
      // width following the ball 1:1 every tick.
      const stageKey = attacking ? phase : "defending";
      const stageChanged = lastElasticityStage[side] !== stageKey;
      teamWidthSmooth[side] = lerp(teamWidthSmooth[side] ?? 1, widthTarget, stageChanged ? 0.45 : 0.1);
      lastElasticityStage[side] = stageKey;

      return { defLine, midLine, atkLine, relBall, threeBack, boxThreat, teamWidth: teamWidthSmooth[side] };
    }

    /**
     * Engine rebuild — parallel/simultaneous reactions (Problem 8: "everything
     * happens sequentially"). JS is single-threaded, so this can't be literal
     * concurrency, but the spirit of the fix is real: when the ball arrives
     * somewhere dangerous, multiple teammates should react in that same
     * instant, not each independently notice the opportunity a tick or two
     * later once the continuous shape recompute happens to catch up. Fires
     * a small synchronous burst of immediate off-ball reactions right when a
     * pass is received in a genuinely advanced position — one attacking
     * teammate bursts into a run, one nearby fullback overlaps — using the
     * same _pathCtrl/tx/ty/lockUntil mechanism doDribble/doCarry/driveIntoBox
     * already use for a run that survives the next shape tick.
     */
    function triggerReceptionReactions(receiver) {
      if (!receiver || receiver.role === "GK") return;
      if (possessionDepth(receiver) < 0.55) return;
      const attackSign = receiver.side === "home" ? -1 : 1;
      const mates = teammates(receiver).filter((m) => m.role !== "GK");

      // One advanced attacker not already making a run bursts forward now,
      // instead of waiting for the next shape tick to notice the opening.
      const runner = mates
        .filter(
          (m) =>
            (m.role === "ST" || m.role === "W" || m.role === "AM" || m.role === "CM" || m.role === "DM") &&
            !m._running &&
            (m.lockUntil || 0) <= matchMinute
        )
        .sort((a, b) => dist(receiver, a) - dist(receiver, b))[0];
      if (runner) {
        const nx = clamp(runner.left + (rng() - 0.5) * 8, 6, 94);
        const ny = clamp(runner.top + attackSign * (5 + rng() * 3), 5, 95);
        const midX = clamp((runner.left + nx) / 2, 6, 94);
        const midY = clamp(runner.top + attackSign * 2.5, 5, 95);
        runner._pathCtrl = { left: midX, top: midY, from: matchMinute, until: matchMinute + 0.6 };
        runner.tx = nx;
        runner.ty = ny;
        runner._running = true;
        runner.lockUntil = matchMinute + 0.55;
      }

      // One nearby fullback not already overlapping steps forward at the
      // same time, rather than as a separate, later decision.
      const fb = mates
        .filter((m) => m.role === "FB" && !m._overlapRun && Math.abs(m.left - receiver.left) < 30)
        .sort((a, b) => dist(receiver, a) - dist(receiver, b))[0];
      if (fb) {
        const nx = fb.left > 50 ? 90 : 10;
        const ny = clamp(fb.top + attackSign * 5, 5, 95);
        const midX = clamp((fb.left + nx) / 2, 6, 94);
        const midY = clamp(fb.top + attackSign * 2, 5, 95);
        fb._pathCtrl = { left: midX, top: midY, from: matchMinute, until: matchMinute + 0.6 };
        fb.tx = nx;
        fb.ty = ny;
        fb._running = true;
        fb._overlapRun = true;
        fb.lockUntil = matchMinute + 0.55;
      }
    }

    /**
     * Engine fix — defensive breach recovery. Until now, a defender who lost
     * a 1v1 (doDribble, doCarry, driveIntoBox) just returned to the normal
     * shape cycle like nothing happened: no recovery sprint, no covering
     * teammate shifting across, no holding midfielder dropping to protect
     * the space in front of goal. Real defending is a team reaction the
     * instant a player is beaten, not just that one player's problem. Fires
     * synchronously at the moment the duel is lost, mirroring
     * triggerTurnoverReactions/triggerReceptionReactions — the conceding
     * side's version of the same "react in this exact instant, don't wait
     * for the next shape tick" idea.
     */
    function triggerDefensiveBreachReactions(beaten) {
      if (!beaten || beaten.role === "GK") return;
      const attackSign = beaten.side === "home" ? -1 : 1;
      const mates = teammates(beaten).filter((m) => m.role !== "GK");
      // Mark this side as actively scrambling for a short window — read by
      // driveIntoBox/doCarry so an immediate follow-up action doesn't check
      // for a nearby defender before the recovery sprint above has had any
      // chance to actually close the distance.
      breachRecoveryUntil[beaten.side] = matchMinute + 0.35;

      // The beaten defender chases back goal-side instead of drifting back
      // at normal shape speed.
      const recoverY = clamp(beaten.top - attackSign * 6, 3, 97);
      const midY = clamp(beaten.top - attackSign * 2.5, 3, 97);
      beaten._pathCtrl = { left: beaten.left, top: midY, from: matchMinute, until: matchMinute + 0.5 };
      beaten.tx = beaten.left;
      beaten.ty = recoverY;
      beaten._running = true;
      beaten.lockUntil = matchMinute + 0.5;

      // Covering CB/FB shifts across and drops immediately, instead of only
      // shading over on the next shape recompute.
      if (beaten.role === "CB" || beaten.role === "FB") {
        const cover = mates
          .filter((m) => (m.role === "CB" || m.role === "FB") && m.id !== beaten.id)
          .sort((a, b) => dist(beaten, a) - dist(beaten, b))[0];
        if (cover) {
          cover.tx = clamp(lerp(cover.left, beaten.left, 0.3), 6, 94);
          cover.ty = clamp(cover.top - attackSign * 2.5, 3, 97);
          cover._running = true;
          cover.lockUntil = matchMinute + 0.45;
        }
      }

      // Nearest DM/CM drops back to screen the space in front of goal.
      const screen = mates
        .filter((m) => m.role === "DM" || m.role === "CM")
        .sort((a, b) => dist(beaten, a) - dist(beaten, b))[0];
      if (screen) {
        screen.tx = clamp(lerp(screen.left, beaten.left, 0.3), 10, 90);
        screen.ty = clamp(screen.top - attackSign * 3, 3, 97);
        screen._running = true;
        screen.lockUntil = matchMinute + 0.45;
      }

      // Far-side FB tucks infield to help cover centrally.
      const farFB = mates.find(
        (m) => m.role === "FB" && m.id !== beaten.id && (m.left > 50) !== (beaten.left > 50)
      );
      if (farFB) {
        farFB.tx = clamp(lerp(farFB.left, 50, 0.35), 15, 85);
        farFB.ty = farFB.top;
        farFB._tuckIn = true;
        farFB.lockUntil = matchMinute + 0.4;
      }
    }

    /**
     * Engine rebuild — parallel/simultaneous reactions, turnover edition.
     * The moment the ball is won back (interception/steal/dribble lost),
     * both sides should react in that same instant: the side that just won
     * it gets an immediate counter-attacking push, and the nearest opponent
     * to the new carrier reacts by pressing right away, rather than each
     * only converging gradually over the following shape ticks.
     */
    function triggerTurnoverReactions(winner) {
      if (!winner || winner.role === "GK") return;
      const attackSign = winner.side === "home" ? -1 : 1;
      const mates = teammates(winner).filter((m) => m.role !== "GK");

      const runners = mates
        .filter(
          (m) =>
            (m.role === "ST" || m.role === "W" || m.role === "AM" || m.role === "CM") &&
            !m._running &&
            (m.lockUntil || 0) <= matchMinute
        )
        .sort((a, b) => dist(winner, a) - dist(winner, b))
        .slice(0, 2);
      for (const runner of runners) {
        const nx = clamp(runner.left + (rng() - 0.5) * 10, 6, 94);
        const ny = clamp(runner.top + attackSign * (6 + rng() * 4), 5, 95);
        const midX = clamp((runner.left + nx) / 2, 6, 94);
        const midY = clamp(runner.top + attackSign * 3, 5, 95);
        runner._pathCtrl = { left: midX, top: midY, from: matchMinute, until: matchMinute + 0.6 };
        runner.tx = nx;
        runner.ty = ny;
        runner._running = true;
        runner.lockUntil = matchMinute + 0.55;
      }

      // The side that just lost it reacts immediately too - the nearest
      // opponent to the new carrier presses right away instead of only
      // converging over the following ticks.
      const opp = nearestOpponent(winner, 14);
      if (opp && opp.pin.role !== "GK") {
        opp.pin._pressing = true;
        opp.pin.lockUntil = Math.max(opp.pin.lockUntil || 0, matchMinute + 0.35);
      }
    }

    /**
     * Engine fix — event-triggered micro-update, CB edition. A CB stepping
     * out to press was only ever visible to the rest of the sim on the next
     * shape recompute: the space it vacates behind/inside it sits there
     * unattacked for a tick even though a real opposing forward would sense
     * the gap and move into it the instant the CB commits. Mirrors the same
     * "react in this exact instant" idea as the other trigger* functions,
     * fired the moment updateTeamShape's per-pin defensive-mode hysteresis
     * actually transitions a CB into "press" (not every tick it stays there).
     */
    function triggerCBStepOutReaction(pressingCB) {
      if (!pressingCB) return;
      const oppSide = oppOf(pressingCB.side);
      const attackSign = oppSide === "home" ? -1 : 1;
      const target = pinsOf(oppSide)
        .filter(
          (m) =>
            (m.role === "W" || m.role === "AM" || m.role === "ST") &&
            !m._running &&
            (m.lockUntil || 0) <= matchMinute
        )
        .sort((a, b) => dist(pressingCB, a) - dist(pressingCB, b))[0];
      if (!target) return;
      const nx = clamp(pressingCB.left + (rng() - 0.5) * 6, 6, 94);
      const ny = clamp(pressingCB.top + attackSign * 6, 5, 95);
      const midX = clamp((target.left + nx) / 2, 6, 94);
      const midY = clamp(target.top + attackSign * 2.5, 5, 95);
      target._pathCtrl = { left: midX, top: midY, from: matchMinute, until: matchMinute + 0.6 };
      target.tx = nx;
      target.ty = ny;
      target._running = true;
      target.lockUntil = matchMinute + 0.55;
    }

    /**
     * Engine fix — event-triggered micro-update, carrier rotation edition.
     * A carrier who suddenly reorients (turning infield, spinning away from
     * press) previously left every teammate's run pointed at where the ball
     * USED to be headed until the next shape tick caught up. Bends the
     * nearest teammate who's already mid-run toward the carrier's new
     * facing direction right away — doesn't start a fresh run, just
     * redirects one already in progress, matching the real "nobody waits"
     * feel. Called from applyPinMotion only for the current ball carrier,
     * gated by a short cooldown so one sustained turn doesn't refire every
     * frame.
     */
    function triggerCarrierRotationReaction(carrier) {
      if (!carrier || carrier.role === "GK") return;
      const mates = teammates(carrier).filter((m) => m.role !== "GK");
      const runner = mates
        .filter(
          (m) =>
            (m.role === "ST" || m.role === "W" || m.role === "AM") &&
            (m._running || (m.lockUntil || 0) > matchMinute)
        )
        .sort((a, b) => dist(carrier, a) - dist(carrier, b))[0];
      if (!runner) return;
      const bendX = clamp(runner.tx + carrier.facingX * 6, 6, 94);
      const bendY = clamp(runner.ty + carrier.facingY * 4, 5, 95);
      runner._pathCtrl = {
        left: lerp(runner.left, bendX, 0.5),
        top: lerp(runner.top, bendY, 0.5),
        from: matchMinute,
        until: matchMinute + 0.45,
      };
      runner.tx = bendX;
      runner.ty = bendY;
      runner.lockUntil = Math.max(runner.lockUntil || 0, matchMinute + 0.4);
    }

    /**
     * Emergent support roles around the ball (carrier / outlet / progressive / third-man / switch / depth).
     */
    function assignSupportRoles(side, carrier, pins) {
      for (const p of pins) {
        p._supportRole = carrier && p.id === carrier.id ? "carrier" : null;
      }
      if (!carrier || carrier.side !== side) return;
      const attackSign = side === "home" ? -1 : 1;
      const scored = pins
        .filter((p) => p.id !== carrier.id && p.role !== "GK")
        .map((m) => {
          const ahead = attackSign * (m.top - carrier.top);
          const d = dist(carrier, m);
          const nLane = defendersInLane(carrier, m);
          const marked = nearestOpponent(m, 7);
          return { m, ahead, d, nLane, marked, lateral: Math.abs(m.left - carrier.left) };
        });

      const outlets = scored
        .filter((s) => s.ahead < 4 && s.nLane === 0 && (!s.marked || s.marked.d > 5) && s.d < 22)
        .sort((a, b) => a.d - b.d);
      if (outlets[0]) outlets[0].m._supportRole = "safe_outlet";

      const prog = scored
        .filter((s) => !s.m._supportRole && s.ahead > 2 && s.nLane < 2 && s.d < 26)
        .sort((a, b) => b.ahead / (1 + b.nLane) - a.ahead / (1 + a.nLane));
      if (prog[0]) prog[0].m._supportRole = "progressive";

      const progPin = prog[0]?.m;
      if (progPin) {
        const third = scored
          .filter(
            (s) =>
              !s.m._supportRole &&
              attackSign * (s.m.top - progPin.top) > 1 &&
              s.nLane < 2 &&
              Math.abs(s.m.left - progPin.left) > 4
          )
          .sort((a, b) => b.ahead - a.ahead);
        if (third[0]) third[0].m._supportRole = "third_man";
      }

      const switches = scored
        .filter(
          (s) =>
            !s.m._supportRole &&
            s.lateral > 28 &&
            s.nLane === 0 &&
            (s.m.role === "W" || s.m.role === "FB")
        )
        .sort((a, b) => b.lateral - a.lateral);
      if (switches[0]) switches[0].m._supportRole = "switch";

      for (const s of scored) {
        if (s.m.role === "ST" && s.m._running && !s.m._supportRole) s.m._supportRole = "depth_runner";
      }
    }

    /**
     * Teammates continually open lanes / leave cover shadows / keep useful distances.
     * Mutates pending {pin,x,depth} targets for the attacking side.
     */
    function ensurePassingNetwork(side, carrier, pending) {
      if (!carrier || carrier.side !== side) return;
      const ballPos = { left: ball.left, top: ball.top };
      const cRel = fromPitchPct(side, carrier.left, carrier.top);
      const mates = pending.filter(
        (e) =>
          e.pin.id !== carrier.id &&
          e.pin.role !== "GK" &&
          e.pin.role !== "CB" &&
          (e.pin.role === "ST" ||
            e.pin.role === "W" ||
            e.pin.role === "AM" ||
            e.pin.role === "CM" ||
            e.pin.role === "FB" ||
            e.pin.role === "DM")
      );

      for (const entry of mates) {
        const pin = entry.pin;
        const h = iHash(pin.id);
        const probePct = toPitchPct(side, entry.x, entry.depth);
        const probe = { left: probePct.left, top: probePct.top, side, role: pin.role };
        const dBall = dist(probe, ballPos);

        if (dBall < 7) {
          const away = Math.sign(entry.x - cRel.x) || (pin.baseX >= 0.5 ? 1 : -1);
          entry.x = clamp(entry.x + away * 0.045, 0.08, 0.92);
        } else if (dBall > 26 && pin._supportRole !== "switch" && pin.role !== "ST") {
          entry.x = lerp(entry.x, cRel.x, 0.16);
          entry.depth = lerp(entry.depth, clamp(cRel.depth + 0.02, 0.18, 0.88), 0.14);
        } else if (dBall > 8 && dBall < 20) {
          // sweet spot — light hold
        } else if (dBall >= 20 && dBall <= 26 && pin._supportRole !== "switch") {
          entry.depth = lerp(entry.depth, clamp(cRel.depth + (pin._supportRole === "progressive" ? 0.05 : 0.01), 0.2, 0.9), 0.1);
        }

        const marker = nearestOpponent(probe, 10);
        if (marker) {
          const ax = ball.left;
          const ay = ball.top;
          const bx = marker.pin.left;
          const by = marker.pin.top;
          if (pointToSegmentDist(probe.left, probe.top, ax, ay, bx, by) < 5.2) {
            const sideNudge = probe.left >= (ax + bx) * 0.5 ? 1 : -1;
            entry.x = clamp(entry.x + sideNudge * (0.028 + h * 0.01), 0.06, 0.94);
          }
        }

        const refreshed = toPitchPct(side, entry.x, entry.depth);
        const probe2 = { left: refreshed.left, top: refreshed.top, side, role: pin.role };
        if (defendersInLane(carrier, probe2) >= 1) {
          const nudge = entry.x >= cRel.x ? 0.032 : -0.032;
          entry.x = clamp(entry.x + nudge, 0.06, 0.94);
          entry.depth = lerp(entry.depth, cRel.depth + 0.015, 0.08);
        }

        // Avoid standing directly behind an opponent relative to the ball
        for (const opp of pinsOf(oppOf(side))) {
          if (opp.role === "GK") continue;
          if (dist(probe2, opp) > 9) continue;
          const t = pointToSegmentDist(opp.left, opp.top, ball.left, ball.top, probe2.left, probe2.top);
          if (t < 3.2 && dist(opp, ballPos) < dist(probe2, ballPos)) {
            entry.x = clamp(entry.x + (entry.x >= 0.5 ? 0.03 : -0.03), 0.06, 0.94);
            break;
          }
        }
      }

      // Break collinear triangles: ball + two mates
      for (let i = 0; i < mates.length; i++) {
        for (let j = i + 1; j < mates.length; j++) {
          const a = mates[i];
          const b = mates[j];
          const ap = toPitchPct(side, a.x, a.depth);
          const bp = toPitchPct(side, b.x, b.depth);
          const col =
            pointToSegmentDist(ap.left, ap.top, ball.left, ball.top, bp.left, bp.top) < 3.5 ||
            pointToSegmentDist(bp.left, bp.top, ball.left, ball.top, ap.left, ap.top) < 3.5;
          if (!col) continue;
          const nudge = (a.x - b.x) || (a.pin.baseX - b.pin.baseX) || 0.04;
          a.x = clamp(a.x + Math.sign(nudge) * 0.025, 0.08, 0.92);
          b.x = clamp(b.x - Math.sign(nudge) * 0.025, 0.08, 0.92);
        }
      }

      // Role depth bias + ST onside clamp after network nudges
      for (const entry of pending) {
        const pin = entry.pin;
        if (pin.id === carrier.id) continue;
        const role = pin._supportRole;
        if (role === "safe_outlet") {
          entry.depth = Math.min(entry.depth, cRel.depth + 0.01);
        } else if (role === "progressive") {
          entry.depth = Math.max(entry.depth, cRel.depth + 0.03);
        } else if (role === "third_man") {
          entry.depth = Math.max(entry.depth, cRel.depth + 0.055);
        } else if (role === "switch") {
          entry.x = lerp(entry.x, pin.baseX >= 0.5 ? 0.9 : 0.1, 0.35);
        }
        if (pin.role === "ST") {
          const offLine = defendingOffsideLine(side);
          const onsideDepth = offLine - (0.008 + iHash(pin.id) * 0.012);
          if (!(pin._running && pin._supportRole === "depth_runner")) {
            entry.depth = Math.min(entry.depth, onsideDepth);
          } else {
            entry.depth = Math.min(entry.depth, offLine + 0.02);
          }
        }
      }
    }

    /** Wide CBs of a back three (CB1 / CB3), not the central CB2. */
    function isWideCentreBack(pin) {
      if (!pin || pin.role !== "CB") return false;
      const slot = String(pin.slot || "").toUpperCase();
      if (/^CB2$/.test(slot)) return false;
      if (/^CB[13]$/.test(slot)) return true;
      return Math.abs(pin.baseX - 0.5) >= 0.14;
    }

    /** Full-backs / wing-backs / wide midfielders that can invert in possession. */
    function isInvertWideSlot(pin) {
      if (!pin) return false;
      const slot = String(pin.slot || "").toUpperCase();
      return /^(LB|RB|LWB|RWB|LM|RM)$/.test(slot) || pin.role === "FB";
    }

    /**
     * Occasional inverted tuck: help build-up / possession centrally.
     * 4-back FBs = rare pulse; 3-back wide CBs or LWB/RWB/LM/RM = more frequent.
     */
    function wantPossessionTuckIn(pin, threeBack, atkStage, relBall, conf, flank) {
      if (!pin || pin._overlapRun || flank === "C") return false;
      const stageOk =
        atkStage === "BUILD_UP" ||
        atkStage === "PROGRESSING" ||
        (threeBack &&
          (atkStage === "FINAL_THIRD" ||
            atkStage === "CHANCE_CREATION" ||
            atkStage === "BOX_OCCUPATION"));
      if (!stageOk) return false;

      const eligible4 = !threeBack && pin.role === "FB";
      const eligible3 =
        threeBack && (isWideCentreBack(pin) || isInvertWideSlot(pin));
      if (!eligible4 && !eligible3) return false;

      // Prefer when ball is central or on the opposite flank (their side holds width)
      const ballCentral = Math.abs(relBall.x - 0.5) < 0.22;
      const ballOpp =
        (flank === "R" && relBall.x < 0.46) || (flank === "L" && relBall.x > 0.54);
      if (!ballCentral && !ballOpp) return false;

      const h = iHash(pin.id);
      const pulse = (Math.sin(shapePulse * (threeBack ? 0.58 : 0.36) + h * 2.85) + 1) * 0.5;
      const stageBoost =
        atkStage === "BUILD_UP" ? 0.14 : atkStage === "PROGRESSING" ? 0.09 : 0.05;
      const confBoost = conf > 45 ? 0.07 : conf > 25 ? 0.03 : 0;
      // Lower threshold = more frequent. 3-back tucks much more often than 4-back FBs.
      const thresh = clamp((threeBack ? 0.34 : 0.58) - stageBoost - confBoost + h * 0.03, 0.18, 0.72);
      return pulse > thresh;
    }

    /**
     * SPACE-DRIVEN shape (Priority 1–2, 6–8) + passing-network support.
     * Assigns ideal positions for all 22 players by possession state + pattern + role
     * BEFORE any ball decision. Animation only follows these targets.
     */
    function updateTeamShape() {
      const ballLeft = ball.left;
      const ballTop = ball.top;
      shapePulse += 0.011;
      const atkStage = spell && spell.side === possession ? spell.stage : phase;
      const atkPattern = spell && spell.side === possession ? spell.pattern : null;
      const conf = spell && spell.side === possession ? spell.patternConfidence ?? 100 : 0;

      for (const side of ["home", "away"]) {
        const attacking = side === possession;
        const formation = side === "home" ? homeTeam.formation : awayTeam.formation;
        const centralMidCover = wantsCentralDefMidCover(formation);
        const { defLine, midLine, atkLine, relBall, threeBack, boxThreat, teamWidth } = teamBlockLines(side, attacking);
        const pins = pinsOf(side);
        const pending = [];
        const boxedN = attacking ? countBoxAttackers(side) : 0;
        const deepOk = attacking && allowDeepRun(side);

        // Engine fix — Milestone 3: anticipation ("likely counter"),
        // continuous edition. The first version was a rare coin-flip (6%
        // per tick) that fired a one-off dash — mostly nothing happened,
        // and when it did it read as a random twitch rather than a sensed,
        // building threat. Real anticipation is continuous: a smoothed
        // per-side "counter readiness" value that's always being updated
        // from the live pressure-on-ball/opponent-commitment signal (an EMA
        // like teamWidthSmooth/defPressureSmooth, not a gated trigger), and
        // continuously nudges the outlet forward's resting depth every tick
        // — see the counterReadiness use at the xx/dd finalization below.
        // triggerTurnoverReactions still covers the reactive burst once the
        // ball is actually won; this is the ongoing sense of it building.
        {
          const ballCarrier = findCarrier();
          let readinessTarget = 0;
          if (!attacking && ballCarrier && ballCarrier.side !== side) {
            const pressureOnBall = pressureAt(ballCarrier.left, ballCarrier.top, ballCarrier.side);
            const oppCommitment = attackDefendDelta(ballCarrier.side);
            readinessTarget = clamp(pressureOnBall * 0.55 + Math.max(0, oppCommitment) * 2.2, 0, 1);
          }
          counterReadiness[side] = lerp(counterReadiness[side] ?? 0, readinessTarget, 0.1);
        }

        // ST cycle phase shared across strikers (Priority 7)
        const stCycleNames = ["drop", "pin", "drift", "near", "far"];
        const stCycleIdx = Math.floor((shapePulse * 0.18 + (side === "home" ? 0 : 2.1)) % 5);
        const stCycle = stCycleNames[stCycleIdx];
        // AM/CAM pocket cycles — distinct from ST near/far post (except 4-3-3 attacking)
        const amCamStack = /4-3-3\s*attacking/i.test(formation || "");
        const amCycleNames = ["halfL", "pocket", "drop", "halfR", "late", "support"];
        const amCycleIdx = Math.floor((shapePulse * 0.22 + (side === "home" ? 1.3 : 3.4)) % 6);
        const amCycle = amCycleNames[amCycleIdx];

        for (const pin of pins) {
          pin._pressing = false;
          if (!attacking) pin._tuckIn = false;
          if (pin.lockUntil > matchMinute) continue;
          const h = iHash(pin.id);
          let x = pin.baseX;
          let depth;
          const bias = ROLE_LINE_BIAS[pin.role] ?? 0.02;
          const lineKind = LINE_ROLE[pin.role] || "mid";
          const flank = pinFlank(pin);
          const sideSign = flank === "R" ? 1 : flank === "L" ? -1 : pin.baseX >= 0.5 ? 1 : -1;

          if (pin.role === "GK") {
            depth =
              attacking && (atkStage === "FINAL_THIRD" || atkStage === "BOX_OCCUPATION" || atkStage === "CHANCE_CREATION")
                ? 0.07
                : attacking
                  ? 0.055
                  : 0.05;
            // Engine fix — this was a flat 8% blend toward the ball's
            // lateral position regardless of distance, so the keeper shaded
            // exactly as far for a ball on the halfway line as for one on
            // the six-yard box, and stayed square/uncommitted right when a
            // shot from close range needed real angle coverage. Scale the
            // blend by proximity to this side's own goal (relBall.depth
            // near 0 = ball right on top of it) so shading ramps up sharply
            // only once the ball is genuinely dangerous.
            //
            // Bug fix — "danger" here was purely a function of ball depth,
            // with no regard for who actually has the ball. A team calmly
            // building out from the back has the ball deep in its OWN
            // third by definition, which this read as maximum danger
            // exactly like an actual opposition attack -- so the keeper
            // shaded hard toward wherever his own centre-back happened to
            // be holding the ball during routine build-up, real match
            // report: left=32-35 (should be ~50) during BUILD_UP, own
            // possession, no threat at all. Only the DEFENDING case (the
            // opponent has/is threatening with the ball) should drive this
            // shading; the attacking case gets a small flat blend so the
            // keeper still looks alive as an outlet without swinging off
            // his line for his own side's possession.
            const gkDanger = attacking ? 0 : clamp(1 - relBall.depth, 0, 1);
            x = lerp(pin.baseX, relBall.x, attacking ? 0.05 : 0.06 + gkDanger * gkDanger * 0.34);
          } else {
            if (lineKind === "def") depth = defLine + bias;
            else if (lineKind === "mid") depth = midLine + bias;
            else depth = atkLine + bias;
            x = pin.baseX + (pin.baseX - 0.5) * 0.02;

            if (attacking) {
              // --- Ideal positions by possession STATE (before ball attraction) ---
              if (atkStage === "BUILD_UP") {
                if (pin.role === "CB") depth = clamp(0.18 + bias, 0.14, 0.28);
                if (pin.role === "FB") {
                  // Phase 5: Fullback archetype-based positioning
                  const fbMod = fullbackArchetypeModifiers(pin);
                  const defensiveDepth = fbMod.defensiveDepth / 100; // Convert to 0-1
                  depth = clamp(0.22 + bias, 0.16, 0.34);
                  // Defensive FB sits deeper, attacking FB slightly higher even in build-up
                  if (pin._fbArchetype === "defensive") {
                    depth = clamp(defensiveDepth + bias, 0.14, 0.28);
                  }
                }
                if (pin.role === "DM") depth = clamp(0.3 + bias, 0.24, 0.4);
                if (pin.role === "CM") depth = clamp(0.36 + bias, 0.3, 0.46);
                if (pin.role === "AM") {
                  depth = amCamStack
                    ? clamp(0.48 + bias, 0.42, 0.56)
                    : clamp(0.42 + bias, 0.36, 0.5);
                }
                if (pin.role === "W") {
                  x = flank === "R" ? 0.88 : flank === "L" ? 0.12 : pin.baseX;
                  depth = clamp(0.48 + bias, 0.42, 0.56);
                }
                if (pin.role === "ST") depth = clamp(0.52 + bias, 0.46, 0.6);
              } else if (atkStage === "PROGRESSING") {
                if (pin.role === "FB") {
                  // Phase 5: Attacking FB pushes higher, defensive FB stays back
                  const fbMod = fullbackArchetypeModifiers(pin);
                  const targetDepth = fbMod.archetype === "attacking"
                    ? lerp(depth, midLine + 0.08, 0.55)
                    : lerp(depth, midLine + 0.01, 0.35);
                  depth = targetDepth;
                }
                // Engine rebuild — build-up used to be a flat lerp-to-formation-
                // line for every role with zero variety, while FINAL_THIRD (just
                // above) already had real intent-driven movement. Most of a
                // possession's actual duration is spent here, so an off-ball
                // creator/attacker had nothing dynamic to do until the ball was
                // already deep — no checking runs, no bursts into the gap, no
                // reason for a marker to ever lose track of them. Reuse the same
                // ensureIntent machinery FINAL_THIRD already proves out, with
                // build-up-scaled geometry; run-frequency itself is driven by
                // each player's own xg_buildup90 (see ensureIntent).
                if (pin.role === "CM") {
                  const intent = ensureIntent(pin, relBall, atkStage);
                  if (intent === "progressive_run") {
                    x = lerp(x, clamp(relBall.x + (relBall.x > 0.5 ? 0.12 : -0.12), 0.28, 0.72), 0.4);
                    depth = clamp(lerp(depth, midLine + 0.14 + bias, 0.45), midLine + 0.06, atkLine - 0.02);
                    pin._running = true;
                  } else if (intent === "hold_width") {
                    x = lerp(pin.baseX, 0.5, 0.25);
                    depth = lerp(depth, midLine + 0.04, 0.4);
                  } else {
                    depth = lerp(depth, midLine + 0.06, 0.5);
                  }
                }
                if (pin.role === "AM") {
                  const intent = ensureIntent(pin, relBall, atkStage);
                  // Pocket ahead of CMs, behind ST — not on the striker line.
                  const pocketD = midLine + 0.1;
                  if (intent === "attack_gap") {
                    x = lerp(x, clamp(relBall.x + (relBall.x > 0.5 ? -0.14 : 0.14), 0.26, 0.74), 0.45);
                    depth = clamp(lerp(depth, pocketD + 0.1 + bias, 0.45), midLine + 0.1, atkLine - 0.02);
                    pin._running = true;
                  } else {
                    depth = lerp(depth, clamp(pocketD + bias, midLine + 0.04, atkLine - 0.04), 0.45);
                    const halfOsc = Math.sin(shapePulse * 0.65 + h * 2.8);
                    x = lerp(x, clamp(0.5 + halfOsc * 0.14, 0.32, 0.68), 0.35);
                  }
                }
                if (pin.role === "W") {
                  const intent = ensureIntent(pin, relBall, atkStage);
                  if (intent === "attack_gap" || intent === "underlap") {
                    const halfX = flank === "R" ? 0.7 : flank === "L" ? 0.3 : 0.5;
                    x = lerp(x, halfX, 0.4);
                    depth = lerp(depth, atkLine + 0.02, 0.42);
                    pin._running = true;
                  } else {
                    depth = lerp(depth, atkLine - 0.02, 0.4);
                  }
                }
                if (pin.role === "ST") {
                  const intent = ensureIntent(pin, relBall, atkStage);
                  const offLine = defendingOffsideLine(pin.side);
                  const onsideDepth = offLine - (0.008 + h * 0.012);
                  if (intent === "drop_short") {
                    x = lerp(x, clamp(relBall.x, 0.34, 0.66), 0.35);
                    depth = clamp(lerp(depth, relBall.depth - 0.04, 0.4), midLine + 0.08, atkLine - 0.02);
                    pin._running = true;
                  } else {
                    depth = lerp(depth, Math.min(atkLine, onsideDepth), 0.4);
                  }
                }
              } else if (atkStage === "FINAL_THIRD") {
                // ST near/far post onside of last defender; LW half-space; RW far post/wide;
                // CM edge of box; AM pocket / half-spaces (deeper than ST unless 4-3-3 attacking);
                // FB hold width OR overlap (start when ball still central with CM)
                // Engine rebuild — every branch below now reads a held pin._intent
                // (ensureIntent) instead of recomputing a fresh choice every tick.
                // Existing space-aware math (scoreOpenSpace, the near/far-post
                // oscillation, etc.) still decides HOW to execute the intent; it
                // no longer decides WHETHER to have one.
                if (pin.role === "ST") {
                  const intent = ensureIntent(pin, relBall, atkStage);
                  const offLine = defendingOffsideLine(pin.side);
                  const onsideDepth = offLine - (0.008 + h * 0.012);
                  const ballWide = relBall.x < 0.32 || relBall.x > 0.68;
                  const nearPost = relBall.x < 0.5 ? 0.38 : 0.62;
                  const farPost = relBall.x < 0.5 ? 0.64 : 0.36;
                  if (intent === "drop_short") {
                    x = lerp(x, clamp(relBall.x, 0.32, 0.68), 0.4);
                    depth = clamp(relBall.depth - 0.08, midLine + 0.04, 0.7);
                  } else if (intent === "far_post") {
                    x = lerp(x, farPost, 0.4);
                    depth = clamp(onsideDepth, midLine + 0.1, 0.9);
                  } else {
                    // pin_last_line (default) — hold the shoulder of the last
                    // defender; still drifts near/far post but less freely
                    // than a pure oscillation since the intent is to stay
                    // pinned onside rather than wander.
                    const osc = (Math.sin(shapePulse * 0.9 + h * 3.5) + 1) * 0.5;
                    x = lerp(nearPost, farPost, osc * 0.35 + 0.32);
                    depth = clamp(onsideDepth, midLine + 0.1, 0.9);
                    if (ballWide) x = lerp(x, relBall.x, 0.12);
                  }
                } else if (pin.role === "FB") {
                  // Phase 5: Fullback overlap/underlay in attacking moves
                  const fbMod = fullbackArchetypeModifiers(pin);
                  if (fbMod.archetype === "attacking" && rng() < fbMod.overlapFrequency) {
                    // Attacking fullback makes an overlap run with nearby winger
                    const offlineDepth = fbMod.offensiveDepth / 100;
                    depth = clamp(offlineDepth, 0.65, 0.85);
                    // Move into wider attacking position
                    x = lerp(x, pin.baseX, 0.4);
                    pin._overlapRun = true;
                  } else if (fbMod.archetype === "defensive") {
                    // Defensive fullback holds width but stays back
                    const defDepth = fbMod.defensiveDepth / 100;
                    depth = clamp(defDepth, 0.18, 0.35);
                  }
                } else if (pin.role === "W") {
                  // Engine rebuild Phase 2 — was a pure sine wave of elapsed
                  // time picking touchline vs half-space regardless of
                  // pressure, lane, or teammate crowding. Now the intent
                  // (stretch / attack_gap / underlap) decides the target
                  // zone, held for a few seconds; scoreOpenSpace still fine-
                  // tunes how far to commit to it based on real pressure.
                  const intent = ensureIntent(pin, relBall, atkStage);
                  const touch = flank === "R" ? 0.93 : flank === "L" ? 0.07 : pin.baseX;
                  const half = flank === "R" ? 0.72 : flank === "L" ? 0.28 : 0.5;
                  const underlapX = clamp(0.5 + (pin.baseX - 0.5) * 0.3, 0.38, 0.62);
                  let targetX = touch;
                  let targetD = 0.72;
                  if (intent === "attack_gap") {
                    targetX = half;
                    targetD = 0.78;
                  } else if (intent === "underlap") {
                    targetX = underlapX;
                    targetD = 0.82;
                  }
                  const openHere = scoreOpenSpace(pin, targetX, targetD);
                  const openTouch = scoreOpenSpace(pin, touch, 0.72);
                  const settle = clamp(0.5 + (openHere - openTouch) * 0.05, 0.35, 0.62);
                  x = lerp(x, targetX, settle);
                  depth = clamp(lerp(depth, targetD, settle), 0.66, 0.84);
                  pin._running = true;
                } else if (pin.role === "AM") {
                  const intent = ensureIntent(pin, relBall, atkStage);
                  const halfL = 0.36;
                  const halfR = 0.64;
                  const ballSideHalf = relBall.x < 0.5 ? halfL : halfR;
                  const oppHalf = relBall.x < 0.5 ? halfR : halfL;
                  if (intent === "support") {
                    x = lerp(x, clamp(relBall.x, 0.32, 0.68), 0.4);
                    depth = clamp(relBall.depth - 0.06, midLine + 0.04, 0.7);
                  } else if (intent === "back_post") {
                    const farX = relBall.x < 0.5 ? 0.7 : 0.3;
                    x = lerp(x, farX, 0.4);
                    depth = clamp(0.72 + bias, 0.66, 0.8);
                  } else if (intent === "box_crash") {
                    // Engine addition — clinical AM box entry. Only drawn by
                    // a genuine finisher (clinicalBoxThreat); a pure
                    // playmaker AM never reaches this depth by default.
                    x = clamp(0.5 + (pin.baseX - 0.5) * 0.3, 0.36, 0.64);
                    depth = clamp(0.82 + h * 0.05, 0.78, 0.88);
                  } else {
                    // attack_gap (default) — existing half-space pocket behaviour
                    const osc = (Math.sin(shapePulse * 0.85 + h * 3.1) + 1) * 0.5;
                    // Was two branches — amCamStack (4-3-3 attacking) deliberately stacked
                    // the AM at 0.68-0.84 depth, nearly the same line as ST (which sits
                    // ~0.8-0.9 here). Use the properly-separated pocket depth for every
                    // formation instead of just the non-stacked one.
                    x = lerp(ballSideHalf, oppHalf, osc * 0.55);
                    x = lerp(x, clamp(relBall.x + (relBall.x > 0.5 ? -0.08 : 0.08), 0.3, 0.7), 0.25);
                    // Edge of box / pocket — clearly deeper than ST near/far posts
                    depth = clamp(0.66 + bias + osc * 0.04, 0.58, 0.74);
                  }
                  pin._running = true;
                } else if (pin.role === "CM") {
                  const intent = ensureIntent(pin, relBall, atkStage);
                  if (intent === "progressive_run") {
                    x = lerp(x, clamp(relBall.x + (relBall.x > 0.5 ? 0.1 : -0.1), 0.26, 0.74), 0.4);
                    depth = clamp(0.74 + bias, 0.68, 0.82);
                  } else if (intent === "hold_width") {
                    x = lerp(pin.baseX, 0.5, 0.3);
                    depth = clamp(0.62 + bias, 0.55, 0.7);
                  } else {
                    // support (default) — existing edge-of-box behaviour
                    x = lerp(pin.baseX, clamp(0.5 + (pin.baseX - 0.5) * 0.7, 0.28, 0.72), 0.4);
                    depth = clamp(0.7 + bias, 0.64, 0.78); // edge of box
                  }
                  pin._running = true;
                } else if (pin.role === "FB") {
                  const intent = ensureIntent(pin, relBall, atkStage);
                  const ballCentral = Math.abs(relBall.x - 0.5) < 0.22;
                  const cmHasBall =
                    carrierId &&
                    (() => {
                      const c = pinById.get(carrierId);
                      return c && c.side === side && (c.role === "CM" || c.role === "AM" || c.role === "DM");
                    })();
                  const sameFlankAsBall =
                    (flank === "R" && relBall.x >= 0.5) || (flank === "L" && relBall.x < 0.5);
                  const oppFlank =
                    (flank === "R" && relBall.x < 0.42) || (flank === "L" && relBall.x > 0.58);
                  // Overlap starts when ball still central with CM — BEFORE winger
                  // receives - but only when the FB's held intent is actually to
                  // overlap; the opportunity existing isn't enough on its own.
                  if (
                    ((ballCentral && cmHasBall && sameFlankAsBall) || (atkPattern === "wing_carry" && sameFlankAsBall)) &&
                    intent === "overlap"
                  ) {
                    x = flank === "R" ? 0.92 : 0.08;
                    depth = clamp(0.76 + fbAttackThreat(pin) * 0.1, 0.68, 0.9);
                    pin._running = true;
                    pin._overlapRun = true;
                  } else if (oppFlank || intent === "tuck_support") {
                    // Opposite FB tucks (or held intent is to tuck and support)
                    x = lerp(pin.baseX, 0.5 + sideSign * 0.18, 0.55);
                    depth = clamp(midLine + 0.02, defLine + 0.06, midLine + 0.1);
                    pin._overlapRun = false;
                  } else {
                    x = flank === "R" ? 0.88 : 0.12;
                    depth = clamp(midLine + 0.08 + fbAttackThreat(pin) * 0.08, midLine, 0.72);
                    pin._overlapRun = false;
                  }
                }
              } else if (atkStage === "BOX_OCCUPATION" || atkStage === "CHANCE_CREATION" || atkStage === "FINISH") {
                // ≥2 attackers crash box OR 1 + arriving runner; CM edge; W cutback lane
                // AM stays in pocket / arrives late — not same near/far posts as ST (except 4-3-3 attacking)
                // Engine rebuild — same held pin._intent as FINAL_THIRD (usually
                // still active on entering this stage; ensureIntent redraws only
                // if it's actually expired).
                if (pin.role === "ST") {
                  const intent = ensureIntent(pin, relBall, atkStage);
                  const offLine = defendingOffsideLine(pin.side);
                  const onsideDepth = offLine - (0.008 + h * 0.012);
                  const crashers = pins.filter((p) => p.role === "ST" || p.role === "W");
                  const idx = crashers.findIndex((p) => p.id === pin.id);
                  const nearPost = relBall.x < 0.5 ? 0.4 : 0.6;
                  const farPost = relBall.x < 0.5 ? 0.62 : 0.38;
                  if (intent === "drop_short") {
                    x = lerp(x, clamp(relBall.x, 0.32, 0.68), 0.4);
                    depth = clamp(relBall.depth - 0.06, midLine + 0.1, 0.8);
                  } else if (intent === "far_post") {
                    x = farPost;
                    depth = clamp(onsideDepth, midLine + 0.12, 0.92);
                  } else {
                    x = idx % 2 === 0 ? nearPost : farPost;
                    depth = clamp(onsideDepth, midLine + 0.12, 0.92);
                  }
                } else if (pin.role === "AM") {
                  const intent = ensureIntent(pin, relBall, atkStage);
                  const halfL = 0.34;
                  const halfR = 0.66;
                  const ballSideHalf = relBall.x < 0.5 ? halfL : halfR;
                  const oppHalf = relBall.x < 0.5 ? halfR : halfL;
                  if (intent === "support") {
                    x = lerp(x, clamp(relBall.x, 0.3, 0.7), 0.4);
                    depth = clamp(relBall.depth - 0.08, midLine + 0.06, 0.72);
                  } else if (intent === "back_post") {
                    x = relBall.x < 0.5 ? 0.72 : 0.28;
                    depth = clamp(0.7 + bias, 0.62, 0.78);
                  } else if (intent === "box_crash") {
                    // Engine addition — clinical AM box entry. Reaches genuine
                    // inPenaltyBox depth (>=0.86) and central x, unlike every
                    // other AM intent here -- gated behind clinicalBoxThreat
                    // so only a real finisher-type AM draws it.
                    x = clamp(0.5 + (pin.baseX - 0.5) * 0.3, 0.36, 0.64);
                    depth = clamp(0.86 + h * 0.04, 0.84, 0.92);
                  } else {
                    const osc = (Math.sin(shapePulse * 0.95 + h * 2.6) + 1) * 0.5;
                    // Was two branches — amCamStack (4-3-3 attacking) deliberately stacked
                    // the AM at 0.72-0.88 depth, nearly the same as ST's box-occupation
                    // depth (~midLine+0.12 to 0.92, often 0.8+). Use the properly-separated
                    // pocket depth for every formation instead of just the non-stacked one.
                    x = lerp(ballSideHalf, oppHalf, osc * 0.5);
                    x = lerp(x, clamp(relBall.x + (relBall.x > 0.5 ? -0.1 : 0.1), 0.28, 0.72), 0.3);
                    // Pocket / edge of box — under ST, not crashing same posts
                    depth = clamp(0.68 + bias + osc * 0.05, 0.6, 0.78);
                  }
                  pin._running = true;
                } else if (pin.role === "W") {
                  const intent = ensureIntent(pin, relBall, atkStage);
                  if (intent === "underlap") {
                    // Cut inside to attack the near-post/six-yard channel instead
                    // of holding the touchline cutback lane.
                    x = clamp(0.5 + (pin.baseX - 0.5) * 0.35, 0.36, 0.64);
                    depth = clamp(0.8 + h * 0.04, 0.76, 0.88);
                  } else {
                    // Cutback lane — wide and slightly deeper than the six-yard
                    x = flank === "R" ? 0.9 : flank === "L" ? 0.1 : lerp(pin.baseX, relBall.x, 0.2);
                    depth = clamp(0.78 + h * 0.04, 0.74, 0.86);
                  }
                  pin._running = true;
                } else if (pin.role === "CM") {
                  const intent = ensureIntent(pin, relBall, atkStage);
                  if (intent === "box_crash") {
                    // Engine fix — CM's only genuine path to inPenaltyBox()
                    // depth (>=0.86); every other CM branch here is capped
                    // at 0.84, below the box threshold, by construction.
                    // Mirrors AM's box_crash target math for consistency.
                    x = clamp(0.5 + (pin.baseX - 0.5) * 0.3, 0.36, 0.64);
                    depth = clamp(0.86 + h * 0.04, 0.84, 0.9);
                  } else if (intent === "progressive_run") {
                    x = clamp(relBall.x + (relBall.x > 0.5 ? 0.12 : -0.12), 0.26, 0.74);
                    depth = clamp(0.76 + bias, 0.7, 0.84);
                  } else if (intent === "hold_width") {
                    x = lerp(pin.baseX, 0.5, 0.2);
                    depth = clamp(0.6 + bias, 0.52, 0.68);
                  } else {
                    x = clamp(0.5 + (pin.baseX - 0.5) * 0.55 + (h - 0.5) * 0.04, 0.3, 0.7);
                    depth = clamp(0.72 + bias, 0.68, 0.8);
                  }
                  pin._running = true;
                } else if (pin.role === "FB") {
                  const intent = ensureIntent(pin, relBall, atkStage);
                  if (
                    (pin._overlapRun || atkPattern === "wing_carry" || Math.abs(relBall.x - pin.baseX) < 0.35) &&
                    intent !== "hold_width"
                  ) {
                    x = flank === "R" ? 0.91 : 0.09;
                    depth = clamp(0.8 + fbAttackThreat(pin) * 0.08, 0.72, 0.9);
                    pin._running = true;
                  } else {
                    x = lerp(pin.baseX, 0.5 + sideSign * 0.2, 0.4);
                    depth = clamp(midLine + 0.06, defLine + 0.08, 0.7);
                  }
                } else if (pin.role === "DM") {
                  const intent = ensureIntent(pin, relBall, atkStage);
                  if (intent === "screen") {
                    depth = clamp(0.54 + bias, 0.46, 0.62);
                    x = lerp(pin.baseX, 0.5, 0.3);
                  } else {
                    depth = clamp(0.58 + bias, 0.5, 0.66);
                    x = lerp(pin.baseX, relBall.x, 0.25);
                  }
                }
                // Ensure enough crashers when occupation thin. Engine fix —
                // this used to only push depth to 0.8, still short of
                // inPenaltyBox()'s 0.86 threshold, so it could never actually
                // produce a real box occupant no matter how thin things got.
                // Also extended to AM, which the original check skipped.
                if (boxedN < 2 && (pin.role === "W" || pin.role === "CM" || pin.role === "AM") && h > 0.45) {
                  depth = Math.max(depth, 0.87);
                  pin._running = true;
                }
              }

              // Inverted / tuck-in wide defenders while in possession (pulse; 3-back more often)
              pin._tuckIn = false;
              if (
                !pin._overlapRun &&
                wantPossessionTuckIn(pin, threeBack, atkStage, relBall, conf, flank)
              ) {
                pin._tuckIn = true;
                const halfSpace = clamp(0.5 + sideSign * (threeBack ? 0.11 : 0.15), 0.34, 0.66);
                const tuckX = isWideCentreBack(pin)
                  ? lerp(pin.baseX, 0.5, threeBack ? 0.58 : 0.4)
                  : halfSpace;
                x = lerp(x, tuckX, threeBack ? 0.68 : 0.52);
                if (atkStage === "BUILD_UP" || atkStage === "PROGRESSING") {
                  const helpD = clamp(
                    midLine + (pin.role === "CB" ? -0.02 : 0.02) + bias * 0.5,
                    defLine + 0.05,
                    midLine + 0.14
                  );
                  depth = lerp(depth, helpD, threeBack ? 0.45 : 0.35);
                } else if (threeBack && (pin.role === "FB" || isInvertWideSlot(pin))) {
                  // Chance creation: step inside as an extra central option
                  depth = lerp(depth, clamp(midLine + 0.1, midLine, atkLine - 0.04), 0.32);
                  x = lerp(x, clamp(0.5 + sideSign * 0.14, 0.36, 0.64), 0.4);
                }
              }

              // Pattern sticky shape while confidence high
              if (atkPattern && conf > 40) {
                if (atkPattern === "wide_switch" || atkPattern === "wing_carry") {
                  if ((pin.role === "W" || pin.role === "FB") && !pin._tuckIn) {
                    x = lerp(x, flank === "R" ? 0.92 : flank === "L" ? 0.08 : x, 0.55);
                  }
                } else if (atkPattern === "central") {
                  if (pin.role === "CM" || pin.role === "AM" || pin.role === "ST") {
                    x = lerp(x, 0.5 + (pin.baseX - 0.5) * 0.35, 0.4);
                  }
                } else if (atkPattern === "cut_inside" && pin.role === "W") {
                  x = lerp(x, 0.5 + sideSign * 0.2, 0.55);
                } else if (atkPattern === "recycle") {
                  if (pin.role === "W" || pin.role === "ST") depth = lerp(depth, midLine + 0.08, 0.35);
                }
              }

              // Priority 7: ST cycles — always driven by defensive line (onside default)
              if (pin.role === "ST" && atkStage !== "BUILD_UP") {
                const offLine = defendingOffsideLine(pin.side);
                const onsideDepth = offLine - (0.008 + h * 0.012);
                const carrierPin = carrierId ? pinById.get(carrierId) : null;
                const passImminent =
                  deepOk &&
                  carrierPin &&
                  carrierPin.side === side &&
                  carrierPin.id !== pin.id &&
                  (carrierPin.role === "CM" ||
                    carrierPin.role === "AM" ||
                    carrierPin.role === "W" ||
                    carrierPin.role === "FB") &&
                  dist(carrierPin, pin) < 28;
                const pressOnCarrier = carrierPin ? nearestOpponent(carrierPin, 6) : null;
                const canRelease = passImminent && !(pressOnCarrier && pressOnCarrier.d < 4.2);

                // stCycle is a time-driven roll, independent of the striker's
                // held intent (ensureIntent) computed earlier this tick — so
                // a "drop" roll used to override a held "pin_last_line"/
                // "far_post" intent regardless of whether the situation
                // actually called for it. Treat "drop" as "pin" whenever the
                // held intent says to hold the line, so the two systems
                // don't fight each other.
                const holdIntent = pin._intent === "pin_last_line" || pin._intent === "far_post";
                if (stCycle === "drop" && !holdIntent) {
                  depth = lerp(depth, clamp(relBall.depth - 0.02, midLine, onsideDepth), 0.45);
                  x = lerp(x, relBall.x, 0.25);
                  pin._running = false;
                } else if (stCycle === "pin" || (stCycle === "drop" && holdIntent)) {
                  depth = lerp(depth, onsideDepth, 0.55);
                  x = lerp(x, 0.5 + (pin.baseX - 0.5) * 0.4, 0.35);
                } else if (stCycle === "drift") {
                  x = lerp(x, clamp(pin.baseX + sideSign * 0.12, 0.2, 0.8), 0.5);
                  depth = Math.min(depth, onsideDepth);
                } else if (stCycle === "near") {
                  x = lerp(x, relBall.x < 0.5 ? 0.38 : 0.62, 0.55);
                  depth = lerp(depth, onsideDepth, 0.5);
                } else if (stCycle === "far") {
                  x = lerp(x, relBall.x < 0.5 ? 0.64 : 0.36, 0.55);
                  depth = lerp(depth, onsideDepth, 0.5);
                }

                // Brief timed run beyond the line only when release is imminent
                if (
                  canRelease &&
                  (atkStage === "CHANCE_CREATION" ||
                    atkStage === "BOX_OCCUPATION" ||
                    atkStage === "FINISH" ||
                    (atkStage === "FINAL_THIRD" && passImminent))
                ) {
                  depth = Math.min(offLine + 0.018, 0.92);
                  pin._running = true;
                } else {
                  if (pin._running && !canRelease) pin._running = false;
                  depth = Math.min(depth, onsideDepth);
                }
              }

              // AM/CAM cycles — pocket / half-spaces / late arrive; not ST near/far clones.
              // Used to skip this whole block for amCamStack (4-3-3 attacking), leaving
              // that formation's AM without any pocket-cycling behaviour at all — give
              // every formation the same richer AM movement.
              if (pin.role === "AM" && atkStage !== "BUILD_UP") {
                const offLine = defendingOffsideLine(pin.side);
                const pocketCap = Math.min(offLine - 0.04, 0.78);
                const halfL = 0.34;
                const halfR = 0.66;
                const stMate = pins.find((p) => p.role === "ST");
                const underStX = stMate ? clamp(stMate.baseX + (stMate.baseX - 0.5) * -0.15, 0.32, 0.68) : 0.5;
                if (amCycle === "halfL") {
                  x = lerp(x, halfL, 0.5);
                  depth = lerp(depth, clamp(midLine + 0.12, midLine, pocketCap), 0.4);
                } else if (amCycle === "halfR") {
                  x = lerp(x, halfR, 0.5);
                  depth = lerp(depth, clamp(midLine + 0.12, midLine, pocketCap), 0.4);
                } else if (amCycle === "pocket") {
                  x = lerp(x, clamp(0.5 + (pin.baseX - 0.5) * 0.3, 0.36, 0.64), 0.45);
                  depth = lerp(depth, clamp(0.66 + bias, midLine + 0.08, pocketCap), 0.5);
                } else if (amCycle === "drop") {
                  // Drop to feet — show for the ball
                  depth = lerp(depth, clamp(relBall.depth - 0.04, midLine, pocketCap - 0.04), 0.5);
                  x = lerp(x, relBall.x, 0.35);
                  pin._running = false;
                } else if (amCycle === "late") {
                  // Arrive late into the box (still below ST post depth)
                  x = lerp(x, clamp(relBall.x + (relBall.x > 0.5 ? -0.08 : 0.08), 0.3, 0.7), 0.4);
                  depth = lerp(depth, clamp(pocketCap - 0.02, 0.64, 0.8), 0.55);
                  pin._running = true;
                } else if (amCycle === "support") {
                  // Under the striker
                  x = lerp(x, underStX, 0.45);
                  depth = lerp(depth, clamp(0.62 + bias, midLine + 0.06, pocketCap - 0.06), 0.45);
                }
                depth = Math.min(depth, pocketCap);
              }

              // Engine rebuild Phase 2 — was a second, independent sine wave
              // applied on top of the FINAL_THIRD scoring above (diluting
              // it 65% back toward a time-driven blend) and the only signal
              // at all for PROGRESSING. FINAL_THIRD is already handled by
              // real space-scoring above; drive PROGRESSING the same way,
              // reading the same held pin._intent (engine rebuild — persistent
              // intent) so a winger doesn't flip preference right at the
              // PROGRESSING/FINAL_THIRD stage boundary.
              if (pin.role === "W" && atkStage === "PROGRESSING") {
                const intent = ensureIntent(pin, relBall, atkStage);
                const touch = flank === "R" ? 0.92 : flank === "L" ? 0.08 : pin.baseX;
                const half = flank === "R" ? 0.7 : flank === "L" ? 0.3 : 0.5;
                const targetX = intent === "attack_gap" || intent === "underlap" ? half : touch;
                x = lerp(x, targetX, 0.5);
              }

              // Ball-carrier network offsets (W / CM / FB): shape already offers options when ball arrives
              if (
                carrierId &&
                pin.id !== carrierId &&
                (atkStage === "PROGRESSING" ||
                  atkStage === "FINAL_THIRD" ||
                  atkStage === "BOX_OCCUPATION" ||
                  atkStage === "CHANCE_CREATION")
              ) {
                const carrierPin = pinById.get(carrierId);
                if (carrierPin && carrierPin.side === side) {
                  const cFlank = pinFlank(carrierPin);
                  const sameFlank =
                    (flank === cFlank && flank !== "C") ||
                    (cFlank === "C" && Math.abs(pin.baseX - carrierPin.baseX) < 0.22);
                  const oppFlank =
                    (flank === "R" && cFlank === "L") ||
                    (flank === "L" && cFlank === "R") ||
                    (cFlank !== "C" && flank !== "C" && flank !== cFlank);

                  if (carrierPin.role === "W") {
                    if (pin.role === "FB" && sameFlank) {
                      x = flank === "R" ? 0.91 : 0.09;
                      depth = lerp(depth, clamp(relBall.depth + 0.06, midLine, 0.86), 0.45);
                      pin._running = true;
                      pin._overlapRun = true;
                    } else if (pin.role === "CM" || pin.role === "AM") {
                      x = lerp(x, clamp(relBall.x + (relBall.x > 0.5 ? -0.12 : 0.12), 0.28, 0.72), 0.4);
                      // Was atkLine (i.e. no cap at all, same as ST's own line) for
                      // amCamStack — always keep a real gap behind the striker.
                      const amCap = pin.role === "AM" ? atkLine - 0.08 : atkLine;
                      depth = lerp(depth, clamp(relBall.depth - 0.02, midLine, amCap), 0.35);
                    } else if (pin.role === "ST") {
                      const offLine = defendingOffsideLine(pin.side);
                      const onsideDepth = offLine - (0.008 + h * 0.012);
                      depth = lerp(depth, clamp(relBall.depth + 0.01, midLine, onsideDepth), 0.4);
                      x = lerp(x, relBall.x, 0.2);
                    } else if ((pin.role === "W" || pin.role === "FB") && oppFlank) {
                      x = lerp(x, flank === "R" ? 0.88 : 0.12, 0.4);
                      depth = lerp(depth, clamp(relBall.depth - 0.04, midLine, atkLine), 0.25);
                    }
                  } else if (carrierPin.role === "CM" || carrierPin.role === "AM") {
                    // Vertical triangle + recycle triangle
                    if (pin.role === "ST") {
                      const offLine = defendingOffsideLine(pin.side);
                      const onsideDepth = offLine - (0.008 + h * 0.012);
                      depth = lerp(depth, Math.min(onsideDepth, relBall.depth + 0.08), 0.35);
                      x = lerp(x, clamp(relBall.x + (pin.baseX - 0.5) * 0.25, 0.28, 0.72), 0.3);
                    } else if (pin.role === "AM" && pin.id !== carrierPin.id) {
                      // Second AM / support: pocket under ball, not ST crash depth.
                      // Was a much shallower gap (0.01 vs 0.06) up to atkLine itself
                      // for amCamStack — keep the same real separation everywhere.
                      x = lerp(x, clamp(relBall.x + (pin.baseX - 0.5) * 0.2, 0.3, 0.7), 0.35);
                      depth = lerp(depth, clamp(relBall.depth - 0.06, midLine, atkLine - 0.06), 0.35);
                    } else if (pin.role === "DM" || (pin.role === "CM" && pin.id !== carrierPin.id)) {
                      depth = lerp(depth, clamp(relBall.depth - 0.08, defLine + 0.06, midLine + 0.06), 0.4);
                      x = lerp(x, relBall.x + (pin.baseX - relBall.x) * 0.5, 0.3);
                    } else if (pin.role === "W" || pin.role === "FB") {
                      x = lerp(x, flank === "R" ? 0.86 : flank === "L" ? 0.14 : x, 0.35);
                      depth = lerp(depth, clamp(relBall.depth + 0.02, midLine, atkLine), 0.3);
                    }
                  } else if (carrierPin.role === "FB") {
                    if (pin.role === "W" && sameFlank) {
                      x = lerp(x, flank === "R" ? 0.82 : 0.18, 0.4);
                      depth = lerp(depth, clamp(relBall.depth + 0.05, midLine, 0.86), 0.4);
                      pin._running = true;
                    } else if (pin.role === "CM" || pin.role === "AM") {
                      x = lerp(x, clamp(relBall.x + (relBall.x > 0.5 ? -0.1 : 0.1), 0.3, 0.7), 0.38);
                      const amCap = pin.role === "AM" ? atkLine - 0.08 : atkLine;
                      depth = lerp(depth, clamp(relBall.depth - 0.01, midLine, amCap), 0.32);
                    } else if (pin.role === "ST") {
                      const offLine = defendingOffsideLine(pin.side);
                      const onsideDepth = offLine - (0.008 + h * 0.012);
                      depth = lerp(depth, onsideDepth, 0.35);
                      x = lerp(x, clamp(relBall.x * 0.4 + 0.3, 0.32, 0.68), 0.25);
                    } else if ((pin.role === "W" || pin.role === "FB") && oppFlank) {
                      x = lerp(x, flank === "R" ? 0.88 : 0.12, 0.35);
                    }
                  }
                }
              }

              // Ball attraction + support (after ideal state slots)
              if (carrierId && pin.id !== carrierId) {
                const attract = ATTACK_BALL_X[pin.role] ?? 0.1;
                x = lerp(x, lerp(pin.baseX, relBall.x, attract), 0.28);
                const dToBall = dist({ left: pin.left, top: pin.top }, { left: ballLeft, top: ballTop });
                const nearSupport = dToBall < 22;
                if (nearSupport && (pin.role === "CM" || pin.role === "AM" || pin.role === "W" || pin.role === "FB")) {
                  pin._running = true;
                }
                // Decoy: W runs inside → CB follows tendency (def shape); FB receives in space
                if (pin.role === "W" && atkPattern === "cut_inside") {
                  x = lerp(x, 0.5 + sideSign * 0.16, 0.5);
                  pin._decoyInside = true;
                }
              }

              if (pin.id === carrierId) {
                depth = lerp(depth, Math.max(depth, Math.min(relBall.depth + 0.02, atkLine + 0.08)), 0.4);
              }
              if (pin.id === favoredId && pin.favorUntil > matchMinute) {
                depth = Math.min(depth + 0.02, atkLine + 0.1);
                x = lerp(x, relBall.x, 0.1);
              }

              // Continuous offside reaction: ST onside by default; W/AM/overlap softer
              if (pin.role === "ST") {
                const offLine = defendingOffsideLine(pin.side);
                const onsideDepth = offLine - (0.008 + h * 0.012);
                const carrierPin = carrierId ? pinById.get(carrierId) : null;
                const passImminent =
                  deepOk &&
                  carrierPin &&
                  carrierPin.side === side &&
                  (carrierPin.role === "CM" ||
                    carrierPin.role === "AM" ||
                    carrierPin.role === "W" ||
                    carrierPin.role === "FB") &&
                  dist(carrierPin, pin) < 28;
                const pressOnCarrier = carrierPin ? nearestOpponent(carrierPin, 6) : null;
                const canRelease = passImminent && !(pressOnCarrier && pressOnCarrier.d < 4.2);
                if (pin._running && canRelease && deepOk) {
                  depth = Math.min(depth, offLine + 0.02);
                } else {
                  if (pin._running && !canRelease) pin._running = false;
                  depth = Math.min(depth, onsideDepth);
                }
              } else if (pin.role === "W" || pin.role === "AM" || (pin.role === "FB" && pin._overlapRun)) {
                const offLine = defendingOffsideLine(pin.side);
                // This is a final clamp applied after every per-stage depth calc above —
                // for amCamStack (4-3-3 attacking) it used to fall through to the same
                // near-offside-line cap as an overlapping FB/winger, silently undoing
                // the pocket separation those stages had just set. Apply the pocket-side
                // cap to every formation's AM, not just non-stacked ones.
                if (pin.role === "AM") {
                  // CAM stays pocket-side of the last line — don't share ST crash depth
                  depth = Math.min(depth, Math.min(0.78, offLine - 0.035));
                } else if (deepOk || pin._overlapRun) {
                  depth = Math.min(depth, Math.min(0.94, offLine + 0.04));
                } else {
                  depth = Math.min(depth, offLine - 0.008);
                }
              }
            } else {
              // --- Defending: dynamic mark — hold / press / track runner / cover lane ---
              const press = sidePress(pin.side);
              const defQ = sideDefend(pin.side);
              const atkQ = sideAttack(oppOf(pin.side));
              const pressEdge = press - sideResist(oppOf(pin.side));
              const trackBoost = clamp(0.55 + defQ * 0.7 - atkQ * 0.25 + pressEdge * 0.35, 0.35, 1.35);
              const threat = boxThreat || 0;
              // Under box/chance pressure, shrink aggressive press radius so the block drops rather than holds high
              const pressRadius = (11 + press * 9 + Math.max(0, pressEdge) * 4) * (1 - threat * 0.42);
              const dBall = dist({ left: pin.left, top: pin.top }, { left: ballLeft, top: ballTop });
              const isScreenMid =
                pin.role === "DM" || pin.role === "CM" || pin.role === "AM";
              // Central-cover shapes: midfield screens the middle — don't drift wide with the ball
              if (centralMidCover && isScreenMid) {
                const channel =
                  pin.role === "DM" ? 0.2 : pin.role === "CM" ? 0.24 : 0.26;
                const followX = clamp(relBall.x, 0.5 - channel, 0.5 + channel);
                const midCompress =
                  pin.role === "DM" ? 0.14 : pin.role === "CM" ? 0.12 : 0.1;
                x = lerp(lerp(pin.baseX, 0.5, 0.42), followX, midCompress + threat * 0.06);
              } else {
                // Bug fix — W used to fall through to the unlabeled 0.12
                // default here, the weakest ball-tracking of any outfield
                // role, real user report: wingers stay pinned wide/high and
                // barely react when defending. A tracking winger should
                // compress toward the ball at least as readily as a CM.
                const compress =
                  pin.role === "CB" ? 0.18 : pin.role === "DM" ? 0.28 : pin.role === "FB" ? 0.2 : pin.role === "CM" ? 0.24 : pin.role === "W" ? 0.26 : 0.12;
                x = lerp(pin.baseX, relBall.x, compress + threat * (pin.role === "CB" || pin.role === "DM" ? 0.1 : pin.role === "W" ? 0.08 : 0.05));
              }
              if (pin.role === "W") {
                // Real full-pitch defensive shape: the ball-FAR winger tucks
                // into the half-space/central channel to thicken the block
                // rather than stretching to their own touchline for no
                // reason -- "venture into central areas" per the user's
                // report. The ball-near winger already tracks the ball via
                // compress above, so only override when the ball is clearly
                // on the opposite flank.
                const ballOnFarSide =
                  (flank === "R" && relBall.x < 0.42) || (flank === "L" && relBall.x > 0.58);
                if (ballOnFarSide) {
                  const tuckX = 0.5 + (flank === "R" ? 0.12 : -0.12);
                  x = lerp(x, tuckX, 0.4 + threat * 0.15);
                }
              }
              if (pin.role === "CB") {
                x = lerp(pin.baseX, 0.5 + (pin.baseX - 0.5) * 0.85, 0.5);
                x = lerp(x, relBall.x, 0.18 + threat * 0.12);
                const decoy = pinsOf(oppOf(pin.side)).find((a) => a.role === "W" && a._decoyInside && Math.abs(a.left - pin.left) < 22);
                if (decoy) {
                  const dRel = fromPitchPct(pin.side, decoy.left, decoy.top);
                  x = lerp(x, dRel.x, 0.42 * (1 - threat * 0.35));
                }
              }

              // 3-back: midfield stays deeper / connected to CBs
              if (threeBack && (pin.role === "DM" || pin.role === "CM" || pin.role === "AM")) {
                const tether = pin.role === "DM" ? 0.05 : pin.role === "CM" ? 0.08 : 0.11;
                depth = lerp(depth, clamp(defLine + tether, defLine + 0.03, midLine + 0.02), 0.42);
                depth = Math.min(depth, midLine + (pin.role === "AM" ? 0.04 : 0.02));
              }

              // Bug fix — LINE_ROLE pins W to "atk" (the team's most advanced
              // line) unconditionally, so the base depth computed above the
              // attacking/defending split left wingers parked on the
              // attacking line even while the team defends. Real user
              // report: "wingers come down while defending, venture into
              // central areas" — they don't in this engine at all right
              // now. Drop the winger back toward the midfield line, deeper
              // still as the danger rises (own box under threat), same
              // shape as every other outfield role already gets.
              if (pin.role === "W") {
                const wDefDepth = lerp(midLine + bias, defLine + 0.14 + bias, clamp(threat * 1.5, 0, 1));
                depth = Math.min(depth, wDefDepth);
              }

              const carrier = findCarrier();
              // Engine fix — an overlapping opposition FB was invisible to this
              // list entirely (role filter only covered ST/W/AM/CM), so no CB/FB
              // ever tracked or marked one: they could run the full length of the
              // flank and arrive in the box completely unaccounted for. Only
              // count a FB once they're actually making a forward run, so a
              // normally-positioned FB still doesn't spuriously draw coverage.
              const threats = pinsOf(oppOf(pin.side)).filter(
                (a) =>
                  (a.role === "ST" ||
                    a.role === "W" ||
                    a.role === "AM" ||
                    a.role === "CM" ||
                    (a.role === "FB" && (a._overlapRun || a._running))) &&
                  Math.abs(a.left - pin.left) < (pin.role === "FB" ? 22 : 17) &&
                  dist(pin, a) < 20
              );
              threats.sort((a, b) => {
                const runA = a._running || a.lockUntil > matchMinute ? -4 : 0;
                const runB = b._running || b.lockUntil > matchMinute ? -4 : 0;
                return runA + dist(pin, a) - (runB + dist(pin, b));
              });
              const runner = threats.find((a) => a._running || a.lockUntil > matchMinute || a._overlapRun);
              const mark = threats[0] || null;

              let naturalMode = "hold";
              // Bug fix — W was excluded from every defensive mode below
              // (press/track/mark all role-gated without it), so naturalMode
              // stayed "hold" for a winger 100% of the time on defence — no
              // pressing, no tracking a runner, no marking anyone, ever.
              // Give them the same eligibility as a FB: they're the ones
              // actually positioned out on the flank to close down the ball.
              const pressEligible =
                pin.role === "DM" ||
                pin.role === "CM" ||
                pin.role === "FB" ||
                pin.role === "CB" ||
                pin.role === "W" ||
                (!threeBack && pin.role === "AM");
              const ranked = pins
                .filter(
                  (p) =>
                    p.role === "DM" ||
                    p.role === "CM" ||
                    p.role === "FB" ||
                    p.role === "CB" ||
                    p.role === "W" ||
                    (!threeBack && p.role === "AM")
                )
                .map((p) => ({
                  id: p.id,
                  d: dist({ left: p.left, top: p.top }, { left: ballLeft, top: ballTop }),
                  mid: p.role === "DM" || p.role === "CM" ? 0 : p.role === "FB" || p.role === "AM" || p.role === "W" ? 1 : 2,
                }))
                .sort((a, b) => a.mid - b.mid || a.d - b.d);
              const nPressBase = pressEdge > 0.15 ? (press > 0.55 ? 4 : 3) : press > 0.7 ? 3 : press > 0.42 ? 2 : 1;
              // Chance/box pressure: fewer push up; favour cover/retreat
              const nPressScaled = Math.max(1, Math.round(nPressBase * (1 - threat * 0.55)));
              const nPress = threeBack ? Math.min(nPressScaled, 2) : nPressScaled;
              const pressRank = ranked.findIndex((r) => r.id === pin.id);

              // Engine fix — pressRadius/nPress both shrink specifically as
              // boxThreat rises (see just above), which is exactly when a
              // second attacker has pulled up outside the box on a viable
              // shooting angle while the block drops to cover the goal
              // line -- the whole team can be legitimately "correctly"
              // retreating and still leave that shooter completely
              // unaccounted for, since nothing here ever checked "is this
              // specific opponent about to shoot" as its own press trigger.
              // Hard override: the single nearest defender always closes
              // down a genuine outside-the-box shooting threat, regardless
              // of pressRank/nPress/pressRadius or the CB-barring clause
              // just below -- a real back line always sends someone at
              // that ball.
              const shootThreat =
                carrier &&
                carrier.side !== pin.side &&
                !inPenaltyBox(carrier) &&
                isAttackFinisher(carrier) &&
                possessionDepth(carrier) > 0.62 &&
                shotAngleQuality(carrier) > 0.1;
              const isNearestToShooter =
                shootThreat &&
                pinsOf(pin.side)
                  .filter((p) => p.role !== "GK")
                  .every((p) => p.id === pin.id || dist(p, carrier) >= dist(pin, carrier));

              if (
                runner &&
                (pin.role === "CB" || pin.role === "FB" || pin.role === "W" || (pin.role === "DM" && defQ > 0.5)) &&
                dist(pin, runner) < 16 + trackBoost * 3
              ) {
                naturalMode = "track";
              } else if (shootThreat && isNearestToShooter && dist(pin, carrier) < 14) {
                naturalMode = "press";
              } else if (
                pressEligible &&
                pressRank >= 0 &&
                pressRank < nPress &&
                dBall < pressRadius &&
                !(threat > 0.55 && pin.role === "CB" && pressRank > 0)
              ) {
                naturalMode = "press";
              } else if (
                (pin.role === "CM" || pin.role === "DM" || (threeBack && pin.role === "AM")) &&
                carrier &&
                (threats.some((t) => t._supportRole === "progressive" || t._supportRole === "third_man") ||
                  defQ > 0.48 ||
                  threat > 0.35)
              ) {
                naturalMode = "cover";
              } else if (mark && (pin.role === "CB" || pin.role === "FB" || pin.role === "DM" || pin.role === "CM" || pin.role === "W")) {
                naturalMode = "mark";
              }

              // Engine rebuild — defensive intent hold. naturalMode above was
              // recomputed from scratch every tick, same as the pre-rebuild
              // winger hysteresis and _supportRole: two defenders near-tied on
              // pressRank (nearest to the ball) could flip which one presses
              // and which holds/covers every single recompute. "track" (a
              // breaking runner) always overrides immediately since missing a
              // run is too costly to hold a stale assignment through; every
              // other mode is held for a short window once assigned.
              const defHoldActive = (pin._defModeUntil || 0) > matchMinute;
              if (naturalMode === "track" || !defHoldActive || pin._defMode == null) {
                if (pin._defMode !== naturalMode) {
                  if (pin.role === "CB" && naturalMode === "press") {
                    triggerCBStepOutReaction(pin);
                  }
                  pin._defMode = naturalMode;
                  pin._defModeUntil = matchMinute + 0.35 + rng() * 0.25;
                }
              }
              const defMode = pin._defMode || naturalMode;

              // Goalside cover depth: between ball and own goal (depth ≤ ball)
              const goalside = clamp(Math.min(relBall.depth - 0.02, defLine + 0.02), 0.05, midLine + 0.04);

              if (defMode === "track" && runner) {
                const markRel = fromPitchPct(pin.side, runner.left, runner.top);
                // Engine rebuild — full anticipation: same held-intent read as
                // the "mark" branch below, applied to tracking a breaking
                // runner too. A runner's intent tells you where the run is
                // actually going, not just where they are right now.
                let trackAnticipatedX = markRel.x;
                if (runner._intent === "stretch" || runner._intent === "overlap") {
                  trackAnticipatedX = clamp(markRel.x + (markRel.x > 0.5 ? 0.05 : -0.05), 0.05, 0.95);
                } else if (
                  runner._intent === "underlap" ||
                  runner._intent === "attack_gap" ||
                  runner._intent === "tuck_support"
                ) {
                  trackAnticipatedX = clamp(markRel.x + (markRel.x > 0.5 ? -0.05 : 0.05), 0.05, 0.95);
                }
                const t = clamp(0.38 + trackBoost * 0.22, 0.32, 0.72);
                const trackX =
                  centralMidCover && isScreenMid
                    ? clamp(trackAnticipatedX, 0.28, 0.72)
                    : trackAnticipatedX;
                x = lerp(x, trackX, t * (centralMidCover && isScreenMid ? 0.72 : 1));
                const trackDepth = clamp(markRel.depth - 0.005, defLine - 0.04, midLine + 0.1);
                depth = lerp(depth, threat > 0.4 ? Math.min(trackDepth, goalside + 0.04) : trackDepth, t * 0.9);
                pin._pressing = dist(pin, runner) < 8;
              } else if (defMode === "press") {
                pin._pressing = true;
                const nearBoost = dBall < 5 ? 1.4 : dBall < 8 ? 1.1 : 0.7;
                const t = (0.22 + press * 0.32 + pin.stats.tackles90 * 0.04 + Math.max(0, pressEdge) * 0.12) * nearBoost;
                const step = clamp(t * (1 - threat * 0.28), 0.14, 0.62);
                // Engine rebuild — full anticipation, press mode ("press with
                // cover shadow"): a real presser angles their run to also
                // screen the easiest out-ball while closing the carrier down,
                // rather than beelining straight at the ball. Bias the
                // approach slightly toward the carrier's tagged danger option
                // (assignSupportRoles) when one exists.
                let pressTargetX = relBall.x;
                if (carrier && carrier.side !== pin.side) {
                  const dangerMate = teammates(carrier).find(
                    (m) => m._supportRole === "progressive" || m._supportRole === "third_man"
                  );
                  if (dangerMate) {
                    const dangerRel = fromPitchPct(pin.side, dangerMate.left, dangerMate.top);
                    pressTargetX = lerp(relBall.x, dangerRel.x, 0.2);
                  }
                }
                if (centralMidCover && isScreenMid) {
                  const pressX = clamp(pressTargetX, 0.3, 0.7);
                  x = lerp(x, pressX, step * 0.55);
                } else {
                  x = lerp(x, pressTargetX, step);
                }
                if (threeBack && (pin.role === "CM" || pin.role === "DM" || pin.role === "AM")) {
                  depth = lerp(depth, clamp(relBall.depth - 0.02, defLine, midLine + 0.04), step * 0.5);
                } else {
                  const pressDepth = clamp(relBall.depth - 0.005, defLine - 0.06, midLine + 0.14);
                  depth = lerp(depth, threat > 0.35 ? Math.min(pressDepth, goalside + 0.06) : pressDepth, step * 0.85);
                }
              } else if (defMode === "cover") {
                const laneX = centralMidCover && isScreenMid
                  ? lerp(relBall.x, 0.5, 0.62)
                  : lerp(relBall.x, 0.5, 0.4);
                x = lerp(x, laneX, 0.32 + defQ * 0.12 + threat * 0.1);
                // Engine rebuild — full anticipation, cover mode. Cover's
                // whole job is screening the next dangerous option, so read
                // it directly instead of only reacting to ball position: if
                // the carrier already has a teammate tagged as the
                // progressive/third-man option (assignSupportRoles, computed
                // every tick), shade toward them specifically ahead of the
                // pass, not just generic ball-side space.
                if (carrier && carrier.side !== pin.side) {
                  const dangerMate = teammates(carrier).find(
                    (m) => m._supportRole === "progressive" || m._supportRole === "third_man"
                  );
                  if (dangerMate) {
                    const dangerRel = fromPitchPct(pin.side, dangerMate.left, dangerMate.top);
                    x = lerp(x, clamp(dangerRel.x, 0.28, 0.72), 0.18);
                  }
                }
                if (mark && !(centralMidCover && isScreenMid)) x = lerp(x, clamp(mark.left, 18, 82), 0.18);
                else if (mark && centralMidCover && isScreenMid) {
                  const markRel = fromPitchPct(pin.side, mark.left, mark.top);
                  x = lerp(x, clamp(markRel.x, 0.32, 0.68), 0.12);
                }
                depth = lerp(
                  depth,
                  clamp(
                    threat > 0.25 ? Math.min(relBall.depth - 0.04, goalside + 0.05) : relBall.depth - 0.04,
                    defLine,
                    midLine + (threeBack ? 0.02 : 0.06)
                  ),
                  threeBack ? 0.38 : 0.28 + threat * 0.12
                );
              } else if (defMode === "mark" && mark) {
                const markRel = fromPitchPct(pin.side, mark.left, mark.top);
                // Engine rebuild — anticipation (Problem 7). Was purely
                // reactive: always tracked the marked attacker's exact
                // current spot. Now that intent persists (Phase 6) it's a
                // real, readable signal — anticipate a small shift in the
                // direction that intent is actually taking them (stretch/
                // overlap keep drifting wider; underlap/attack_gap/
                // tuck_support cut inside) instead of only marking where
                // they already are.
                let anticipatedX = markRel.x;
                if (mark._intent === "stretch" || mark._intent === "overlap") {
                  anticipatedX = clamp(markRel.x + (markRel.x > 0.5 ? 0.05 : -0.05), 0.05, 0.95);
                } else if (
                  mark._intent === "underlap" ||
                  mark._intent === "attack_gap" ||
                  mark._intent === "tuck_support"
                ) {
                  anticipatedX = clamp(markRel.x + (markRel.x > 0.5 ? -0.05 : 0.05), 0.05, 0.95);
                }
                // Engine rebuild — full anticipation: also read the
                // carrier's OWN held intent, not just the marked attacker's
                // - the closest this engine gets to "carrier body angle ->
                // likely pass" from the critique. A carrier whose own intent
                // is forward-oriented is signalling they're looking to
                // release forward, so tighten up on the mark a bit harder
                // instead of tracking at the same fixed rate regardless of
                // what the passer themselves is telegraphing.
                const carrierForward =
                  carrier &&
                  carrier.side !== pin.side &&
                  (carrier._intent === "progressive_run" ||
                    carrier._intent === "attack_gap" ||
                    carrier._intent === "underlap" ||
                    carrier._intent === "back_post");
                const markT = (pin.role === "FB" || pin.role === "CM" ? 0.4 : 0.32) * trackBoost * (carrierForward ? 1.15 : 1);
                const markX =
                  centralMidCover && isScreenMid
                    ? clamp(anticipatedX, 0.3, 0.7)
                    : anticipatedX;
                x = lerp(x, markX, clamp(markT * (centralMidCover && isScreenMid ? 0.7 : 1), 0.28, 0.55));
                const markDepth = clamp(markRel.depth - 0.01, defLine - 0.03, midLine + 0.08);
                depth = lerp(depth, threat > 0.4 ? Math.min(markDepth, goalside + 0.05) : markDepth, 0.34 * trackBoost);
              } else if ((pin.role === "CB" || pin.role === "FB") && dBall < 9 + press * 4) {
                pin._pressing = dBall < 7 && threat < 0.65;
                x = lerp(x, relBall.x, 0.18 + press * 0.12);
                depth = lerp(depth, clamp(Math.min(relBall.depth - 0.015, goalside + 0.03), defLine - 0.03, midLine + 0.04), 0.2 + threat * 0.15);
              } else if (pin.role === "CM" || pin.role === "DM" || (threeBack && pin.role === "AM")) {
                const laneX = lerp(relBall.x, 0.5, centralMidCover ? 0.55 : 0.35);
                x = lerp(x, laneX, centralMidCover ? 0.38 : 0.28);
                if (threeBack) {
                  depth = lerp(depth, clamp(defLine + (pin.role === "DM" ? 0.06 : 0.09), defLine, midLine), 0.22);
                }
              }

              // Progressive retreat overlay: CB/FB/DM (+ cover CM) drop deeper with threat
              if (
                threat > 0.06 &&
                (pin.role === "CB" ||
                  pin.role === "FB" ||
                  pin.role === "DM" ||
                  (pin.role === "CM" && (defMode === "cover" || defMode === "hold")))
              ) {
                const retreatT = 0.22 + threat * 0.48;
                depth = lerp(depth, Math.min(depth, goalside), retreatT);
                if (threat > 0.35) {
                  const retreatX = centralMidCover && isScreenMid
                    ? lerp(relBall.x, 0.5, 0.58)
                    : lerp(relBall.x, 0.5, 0.4);
                  x = lerp(x, retreatX, threat * 0.2);
                }
              }

              // CAM sat out of any defensive duty entirely — fine to not
              // track back into their own box, but shouldn't stay pinned
              // upfield either while the side defends. Nudge back toward at
              // least the halfway line under real pressure, well short of
              // the CB/FB/DM low-block retreat above. (W's own retreat is
              // handled earlier, right after the threeBack tether — this
              // guard used to also cover W but the condition was inverted:
              // `depth < wingRetreatCap` only fires when already deep, i.e.
              // never for a winger actually pinned forward.)
              if (threat > 0.12 && pin.role === "AM") {
                const wingRetreatCap = midLine + 0.05;
                if (depth < wingRetreatCap) {
                  depth = lerp(depth, wingRetreatCap, 0.14 + threat * 0.2);
                }
              }

              // Final central channel clamp for designated cover shapes
              if (centralMidCover && isScreenMid) {
                const hard =
                  pin.role === "DM" ? 0.22 : pin.role === "CM" ? 0.26 : 0.28;
                x = clamp(x, 0.5 - hard, 0.5 + hard);
                x = lerp(x, 0.5, 0.1 + threat * 0.08);
              }

              pin._decoyInside = false;
              pin._overlapRun = false;
              pin._tuckIn = false;
            }

            x += Math.sin(shapePulse * (0.55 + h * 0.12) + h * 3.1) * (0.0012 + h * 0.0006);
            depth += Math.cos(shapePulse * (0.45 + h * 0.1) + h * 2.4) * (0.0009 + h * 0.00045);
          }

          pending.push({ pin, x, depth });
        }

        if (attacking) {
          const carrier = findCarrier();
          if (carrier && carrier.side === side) {
            assignSupportRoles(side, carrier, pins);
            ensurePassingNetwork(side, carrier, pending);

            // Engine addition — front-three relational movement. With a
            // CM/AM on the ball, the striker and both wingers previously
            // computed position independently (stCycle/amCycle/pattern
            // selection are all self-contained, per the off-ball audit) —
            // no awareness of what the OTHER front players are doing right
            // now. Read live position (not an internal cycle flag) so this
            // reacts to the striker/winger actually being short, whatever
            // caused it, same "read the real situation" approach as the
            // winger-tracks-back chain above.
            if (carrier.role === "CM" || carrier.role === "AM") {
              const offLine = defendingOffsideLine(side);
              const stEntry = pending.find((p) => p.pin.role === "ST");
              const wEntries = pending.filter((p) => p.pin.role === "W");
              const stRel = stEntry ? fromPitchPct(side, stEntry.pin.left, stEntry.pin.top) : null;
              const stShort = Boolean(stRel && stRel.depth < offLine - 0.14);

              if (stShort && wEntries.length) {
                // Striker's dropped short — each winger exploits the space
                // he vacated: run beyond if there's room, or hold the
                // touchline to isolate their marker 1v1 if tightly held.
                // The wingers' push target is capped at the striker's own
                // effective ceiling (offLine, not offLine+0.02) and the
                // striker himself is nudged back up in the same pass — the
                // earlier version only ever advanced the wingers, so a
                // short striker had nothing pulling him level again and
                // could end up reading as the deepest of the front three.
                for (const wEntry of wEntries) {
                  const nearOpp = nearestOpponent(wEntry.pin, 9);
                  if (nearOpp && nearOpp.d < 5) {
                    wEntry.x = lerp(wEntry.x, wEntry.pin.baseX, 0.35);
                  } else {
                    wEntry.depth = Math.max(wEntry.depth, lerp(wEntry.depth, offLine, 0.4));
                  }
                }
                if (stEntry) {
                  stEntry.depth = Math.max(stEntry.depth, lerp(stEntry.depth, offLine - 0.05, 0.35));
                }
              } else if (wEntries.length) {
                const shortW = wEntries.find((w) => {
                  const wRel = fromPitchPct(side, w.pin.left, w.pin.top);
                  return wRel.depth < offLine - 0.16;
                });
                if (shortW) {
                  // A winger's dropped short — the striker and the OTHER
                  // winger peel off the resulting central crowding to
                  // stretch the defense, rather than also drifting inward.
                  const otherW = wEntries.find((w) => w.pin.id !== shortW.pin.id);
                  if (otherW) {
                    otherW.x = lerp(otherW.x, otherW.pin.baseX, 0.3);
                    otherW.depth = Math.max(otherW.depth, lerp(otherW.depth, offLine, 0.3));
                  }
                  if (stEntry) {
                    stEntry.x = lerp(stEntry.x, 0.5 + (stEntry.pin.baseX - 0.5) * 0.6, 0.3);
                    stEntry.depth = Math.max(stEntry.depth, lerp(stEntry.depth, offLine, 0.3));
                  }
                }
              }
            }

            // Engine fix — winger + fullback wide-position collision. Each
            // role's default wide x-target is computed completely
            // independently (FINAL_THIRD/BOX_OCCUPATION branches above),
            // and the only place they're ever made aware of each other is
            // the ball-carrier network-offset block later in this function,
            // which is inert unless one of them is literally the ball
            // carrier right now. For the rest of a possession they land on
            // near-identical touchline x -- the "wingers and fullbacks
            // occupying the same position outwide" symptom. When a same-
            // flank W/FB pair has converged and neither currently has the
            // ball, tuck the W into the half-space (its own underlap
            // target) so the flank offers two distinct options again.
            const flankSides = [0, 1];
            for (const flankIsRight of flankSides) {
              const wEntry = pending.find(
                (p) => p.pin.role === "W" && (p.pin.baseX >= 0.5) === Boolean(flankIsRight)
              );
              const fbEntry = pending.find(
                (p) => p.pin.role === "FB" && (p.pin.baseX >= 0.5) === Boolean(flankIsRight)
              );
              if (!wEntry || !fbEntry) continue;
              if (wEntry.pin.id === carrier.id || fbEntry.pin.id === carrier.id) continue;
              if (Math.abs(wEntry.x - fbEntry.x) < 0.08) {
                wEntry.x = clamp(0.5 + (wEntry.pin.baseX - 0.5) * 0.35, 0.36, 0.64);
              }
            }

            // Engine fix — off-ball teammates converging on the ball
            // carrier's own spot instead of making a separate run. Several
            // "support" branches above deliberately lerp a W/AM's target
            // toward the carrier's live position (relBall.x/relBall.depth)
            // -- correct for build-up, where staying close offers a short
            // out-ball, wrong once the carrier is genuinely advanced: real
            // teammates spread into different attacking options (a run in
            // behind, near/far post) rather than stand beside the man on
            // the ball. When a W/AM's computed target has converged within
            // a tight radius of the advanced carrier, push it sideways and
            // forward (toward/beyond the carrier's depth, capped at the
            // offside line) instead of leaving it stacked on the same spot.
            if (possessionDepth(carrier) >= 0.62) {
              const carrierRel = fromPitchPct(side, carrier.left, carrier.top);
              const offLine3 = defendingOffsideLine(side);
              for (const entry of pending) {
                if (entry.pin.id === carrier.id) continue;
                if (entry.pin.role !== "W" && entry.pin.role !== "AM") continue;
                const dx = entry.x - carrierRel.x;
                const dd = entry.depth - carrierRel.depth;
                if (Math.hypot(dx, dd) >= 0.1) continue;
                const pushSign = dx !== 0 ? Math.sign(dx) : entry.pin.baseX >= 0.5 ? 1 : -1;
                entry.x = clamp(carrierRel.x + pushSign * 0.16, 0.12, 0.88);
                entry.depth = Math.max(entry.depth, Math.min(offLine3, carrierRel.depth + 0.08));
                entry.pin._running = true;
              }
            }
          }
        }

        const cbPend = pending.filter((p) => p.pin.role === "CB");
        if (cbPend.length >= 2) {
          const avgD = cbPend.reduce((s, p) => s + p.depth, 0) / cbPend.length;
          for (const p of cbPend) {
            if (p.pin._pressing) p.depth = clamp(p.depth, avgD - 0.05, avgD + 0.08);
            else {
              p.depth = clamp(p.depth, avgD - 0.028, avgD + 0.028);
              p.depth = lerp(p.depth, avgD, 0.55);
            }
          }
          // Engine rebuild Phase 3 — coordinated lateral cover, not just depth.
          // Each CB independently chases the ball's x-position (set above),
          // which can leave both drifting the same way and the far side
          // uncovered — the exact "defenders act independently" gap from the
          // critique. The CB further from the ball-side danger holds back
          // toward central cover instead of also mirroring the near CB's
          // shift, so beating one defender doesn't leave both exposed.
          if (!attacking) {
            const byDanger = [...cbPend].sort(
              (a, b) => Math.abs(a.pin.left - ballLeft) - Math.abs(b.pin.left - ballLeft)
            );
            const nearCB = byDanger[0];
            const farCB = byDanger[byDanger.length - 1];
            if (farCB) {
              const coverX = 0.5 + (farCB.pin.baseX - 0.5) * 0.5;
              farCB.x = lerp(farCB.x, coverX, 0.3);
            }
            // Engine rebuild — extend the coordinated reshape outward, closer
            // to the critique's full chain ("LCB shifts, DM slides over, LB
            // tucks inside"): once the near-side CB has actually committed to
            // pressing, the DM slides across to screen the space just
            // vacated, and the far-side FB tucks infield to cover in behind,
            // instead of each independently computing a position with no
            // awareness that a teammate has just stepped out.
            if (nearCB && nearCB.pin._defMode === "press") {
              const dmEntry = pending.find((p) => p.pin.role === "DM");
              if (dmEntry) {
                dmEntry.x = clamp(lerp(dmEntry.x, nearCB.x, 0.3), 0.3, 0.7);
              }
              for (const p of pending) {
                if (p.pin.role !== "FB") continue;
                const isFarSideFB = (p.pin.left > 50) !== (nearCB.pin.left > 50);
                if (isFarSideFB) {
                  p.x = lerp(p.x, 0.5 + (p.pin.baseX - 0.5) * 0.6, 0.25);
                }
              }
            }
          }
        }
        if (cbPend.length) {
          const cbAvg = cbPend.reduce((s, p) => s + p.depth, 0) / cbPend.length;
          for (const p of pending) {
            if (p.pin.role === "FB" && !p.pin._pressing && !p.pin._overlapRun) {
              const maxAhead = attacking ? (p.pin._tuckIn ? 0.16 : 0.22) : 0.085;
              p.depth = clamp(p.depth, cbAvg - 0.02, cbAvg + maxAhead);
            }
          }
        }

        // Engine rebuild — coordinated CM/DM cover, mirroring Phase 3's
        // CB-pair fix onto the central midfield group. Each CM/DM
        // independently chased the ball's x-position with zero awareness of
        // where its midfield partner stood — the same "defenders act
        // independently" gap the CB fix closed, just one line further
        // forward. Generalized over however many CM+DM pins the formation
        // actually fields (2-3 across the supported formations — some are a
        // DM+DM double pivot with no CM at all, e.g. 4-2-3-1; others a
        // DM+CM1+CM2 trio, e.g. 4-3-3 flat), rather than assuming an exact
        // pair. Lateral cover only, deliberately no depth-leveling like the
        // CB pair gets — a DM is supposed to sit behind the CM(s), so
        // flattening that natural depth gap the way the CB pair's shared
        // line does would be wrong here.
        if (!attacking) {
          const cmdmPend = pending.filter((p) => p.pin.role === "CM" || p.pin.role === "DM");
          if (cmdmPend.length >= 2) {
            const byDangerMD = [...cmdmPend].sort(
              (a, b) => Math.abs(a.pin.left - ballLeft) - Math.abs(b.pin.left - ballLeft)
            );
            const farMD = byDangerMD[byDangerMD.length - 1];
            if (farMD) {
              const coverX = 0.5 + (farMD.pin.baseX - 0.5) * 0.5;
              farMD.x = lerp(farMD.x, coverX, 0.3);
            }
            // A three-pin midfield's middle player shades toward central
            // cover too, instead of also independently chasing the ball.
            for (const p of byDangerMD.slice(1, -1)) {
              p.x = lerp(p.x, 0.5 + (p.pin.baseX - 0.5) * 0.7, 0.18);
            }
          }
        }

        // Engine rebuild — winger tracks back, the last link in the Problem 3
        // defensive chain ("LCB shifts, DM slides over, LB tucks inside, RW
        // tracks back"). W is never defMode-eligible (always "hold" while
        // defending) and previously only had a generic depth-only retreat
        // nudge (below), with zero awareness of whether its own FB had
        // actually recovered. The FB's *target* depth gets hard-clamped back
        // near the CB line every tick just above, but its real on-pitch
        // position (pin.left/top) lags that target while still jogging back
        // from an advanced run — that lag is the genuine open flank. Read the
        // FB's actual position, not the clamped target, to detect it.
        if (!attacking) {
          for (const fbEntry of pending) {
            if (fbEntry.pin.role !== "FB" || fbEntry.pin._pressing) continue;
            const fbRel = fromPitchPct(fbEntry.pin.side, fbEntry.pin.left, fbEntry.pin.top);
            const exposure = fbRel.depth - (defLine + 0.16);
            if (exposure <= 0) continue;
            const wEntry = pending.find(
              (p) => p.pin.role === "W" && !p.pin._pressing && (p.pin.left > 50) === (fbEntry.pin.left > 50)
            );
            if (wEntry) {
              const coverT = clamp(exposure * 1.8, 0.15, 0.55);
              wEntry.x = lerp(wEntry.x, fbEntry.pin.baseX, coverT);
              wEntry.depth = Math.min(wEntry.depth, lerp(wEntry.depth, defLine + 0.1, coverT));
            }
          }
        }

        // Engine addition — front-line press trigger. Strikers were never
        // part of the defensive _defMode hysteresis (pressEligible above
        // excludes ST/W), so a striker genuinely closing the ball down deep
        // in the opponent's third had zero effect on the winger next to
        // them — the same "wingers sat out of any defensive duty" gap as
        // the tracks-back fix above, just for pressing rather than
        // recovery. When our own striker is closing the ball down high up
        // the pitch, the near-side winger reacts by shading into the
        // passing lane to the opposing ball-side fullback, instead of
        // independently computing a generic position with no awareness a
        // teammate has just committed to the press. 0.72 depth reuses the
        // existing Zone 14 threshold (dangerous attacking third).
        if (!attacking) {
          const stPend = pending.find((p) => p.pin.role === "ST");
          if (stPend && relBall.depth > 0.72 && dist(stPend.pin, { left: ballLeft, top: ballTop }) < 10) {
            const wEntry = pending.find(
              (p) => p.pin.role === "W" && (p.pin.left > 50) === (ballLeft > 50)
            );
            const oppFB = pinsOf(oppOf(side)).find(
              (o) => o.role === "FB" && (o.left > 50) === (ballLeft > 50)
            );
            if (wEntry && oppFB) {
              const oppFBRel = fromPitchPct(side, oppFB.left, oppFB.top);
              wEntry.x = lerp(wEntry.x, (wEntry.x + oppFBRel.x) / 2, 0.3);
            }
          }
        }

        for (const { pin, x, depth } of pending) {
          let dd = clamp(depth, 0.03, 0.96);
          let xx = clamp(x, 0.04, 0.96);
          // Engine fix — Milestone 2: apply the side's breathing width
          // multiplier here, scaling every outfield pin's distance from the
          // pitch centreline as one coherent unit (GK excluded — keepers
          // don't stretch/compress with team shape).
          // Experiment — width-elasticity amplitude A/B (follow-on to the
          // arc-wobble test). Measured (see
          // docs/experiments/target-drift-decomposition.md): this per-pin
          // width multiplier is 30.3% of gross off-ball target churn (active
          // on 82.7% of calls) and, like wobble, its direction is
          // statistically uncorrelated with tactical intent (mean cosine
          // ~0.013). Damping only the multiplier's DEVIATION from 1 (not
          // `teamWidthSmooth`/`widthTarget` themselves, which stay fully
          // tactical/stage-aware) keeps this a single-variable change.
          const ELASTICITY_TEST_SCALE = 0.3;
          const dampedTeamWidth = 1 + (teamWidth - 1) * ELASTICITY_TEST_SCALE;
          if (pin.role !== "GK") xx = clamp(0.5 + (xx - 0.5) * dampedTeamWidth, 0.03, 0.97);
          // Engine fix — Milestone 4: defensive panic, continuous edition.
          // A coin-flip gate (rng() < boxThreat*0.35) meant most ticks
          // nothing happened even under real overload — a real back line
          // under pressure is CONSTANTLY a little scrambled, continuously,
          // not occasionally. Jitter magnitude now scales directly with
          // boxThreat instead of being gated on whether it fires at all;
          // boxThreat is already 0 for the attacking side (only computed in
          // teamBlockLines' defending branch), so this still only ever
          // shows up for a genuinely threatened defence.
          if (pin.role !== "GK" && boxThreat > 0.15) {
            xx = clamp(xx + (rng() - 0.5) * boxThreat * 0.14, 0.03, 0.97);
            dd = clamp(dd + (rng() - 0.5) * boxThreat * 0.09, 0.03, 0.96);
          }
          // Engine fix — Milestone 3: continuous counter anticipation. See
          // counterReadiness declaration/update above — this is the actual
          // effect: the outlet forward's resting depth nudges forward every
          // tick, smoothly tracking how live the counter threat currently
          // is, instead of a rare discrete dash.
          if ((pin.role === "ST" || pin.role === "W") && !attacking && counterReadiness[side] > 0.02) {
            dd = clamp(dd + counterReadiness[side] * 0.07, 0.03, 0.96);
          }
          const h = iHash(pin.id);
          const dx = xx - (pin.x ?? pin.baseX);
          const dd0 = dd - (pin.depth ?? pin.baseDepth);
          const pathLen = Math.hypot(dx, dd0) + 1e-6;
          const perpX = -dd0 / pathLen;
          const perpD = dx / pathLen;
          const arcAmp = (pin._running ? 0.022 : pin._pressing ? 0.012 : 0.008) * (0.75 + h * 0.35);
          // Experiment — arc-wobble amplitude A/B. Measured (see
          // docs/experiments/target-drift-alignment.md): this continuous
          // sin() nudge is 32.1% of gross off-ball target churn and its
          // direction is statistically uncorrelated with tactical intent
          // (mean cosine ~0.04 vs the base tactical vector) — i.e. it reads
          // as background motion, not football. Scaling ONLY `arc` (not
          // `arcAmp`, which is also reused below for the unrelated
          // curved-locomotion jump-correction bias) keeps this a
          // single-variable change — everything else in this function is
          // untouched.
          const ARC_WOBBLE_TEST_SCALE = 0.3;
          const arc = Math.sin(shapePulse * 0.55 + h * 5.1) * arcAmp * ARC_WOBBLE_TEST_SCALE;
          // Engine fix — this background wobble is deliberately tactically
          // meaningless (see above); applying it to the keeper undermines
          // the angle-based shading just added above him specifically, so
          // he's exempted the same way he already is from teamWidth/
          // boxThreat jitter and the personal-space bump nearby.
          if (pin.role !== "GK") {
            xx = clamp(xx + perpX * arc, 0.04, 0.96);
            dd = clamp(dd + perpD * arc * 0.45, 0.03, 0.96);
          }
          if (pin.role !== "GK" && !pin._pressing) {
            const nearOpp = nearestOpponent(pin, 7.5);
            if (nearOpp && nearOpp.d < 7) {
              const oRel = fromPitchPct(pin.side, nearOpp.pin.left, nearOpp.pin.top);
              const away = Math.sign(xx - oRel.x) || (pin.baseX >= 0.5 ? 1 : -1);
              // An off-ball attacker genuinely tight-marked (<4, vs the general 7
              // personal-space band) gets a slightly bigger check-away than pure
              // collision avoidance — a small, bounded reaction to close marking,
              // not a new movement system.
              const tightMark = attacking && pin.id !== carrierId && nearOpp.d < 4;
              const bump = (1 - nearOpp.d / 7) * (tightMark ? 0.038 : 0.022);
              xx = clamp(xx + away * bump, 0.04, 0.96);
              dd = clamp(dd + (dd >= oRel.depth ? 0.008 : -0.006) * bump * 8, 0.03, 0.96);
            }
          }
          const pct = toPitchPct(pin.side, xx, dd);
          const maxJump = pin.role === "GK" ? 1.6 : pin._pressing ? 3.8 : pin._running ? 4.2 : 2.6;
          const jdx = pct.left - pin.tx;
          const jdy = pct.top - pin.ty;
          const jump = Math.hypot(jdx, jdy);
          // Engine fix — this perpendicular "curve the run" bias is scaled
          // for an outfield player's much larger movement range (a winger
          // covering 20+ units), so the same arcAmp*18/12 magnitude applied
          // to a keeper's tiny, frequent adjustments (retargeting toward
          // wherever the ball currently is) could swerve his target 10-16
          // points off a direct line -- a real match showed the away GK
          // pulled out to left=65+ chasing a target that was actually
          // sitting near 45-49. A keeper corrects in a straight line, not
          // a curved run.
          const latBias = pin.role !== "GK" && jump > 0.35 ? (-jdy / (jump + 1e-6)) * arcAmp * 18 : 0;
          const depthBias = pin.role !== "GK" && jump > 0.35 ? (jdx / (jump + 1e-6)) * arcAmp * 12 : 0;
          const dampRate = pin._running || pin._pressing ? 0.28 : 0.18;
          if (jump > maxJump) {
            const s = maxJump / jump;
            pin.tx = smoothDamp(pin.tx, pin.tx + jdx * s + latBias, dampRate);
            pin.ty = smoothDamp(pin.ty, pin.ty + jdy * s + depthBias, dampRate);
          } else {
            pin.tx = smoothDamp(pin.tx, pct.left + latBias * 0.35, dampRate);
            pin.ty = smoothDamp(pin.ty, pct.top + depthBias * 0.35, dampRate);
          }
          // Phase 1 arrival detection: update _arrivalStrength based on depth momentum
          const atkStageForArrival = attacking ? phase : "defending";
          updateArrivalStrength(pin, dd, atkStageForArrival, pin.side);
          pin.x = xx;
          pin.depth = dd;
        }
      }
    }

    /** @deprecated alias — shape is space-driven via updateTeamShape */
    function computeShapeTargets() {
      updateTeamShape();
    }

    function iHash(s) {
      let h = 0;
      for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
      return (h % 1000) / 100;
    }

    function applyPinMotion(dt) {
      // left/top = logical (engine). rx/ry = rendered sprite. Both clamp toward
      // targets; rendered only follows logical so it never leads the engine.
      const baseFollow = clamp(1 - Math.pow(0.035, dt), 0.02, 0.11);
      for (const pin of allPins) {
        const h = iHash(pin.id);
        const roleEase = MOTION_EASE[pin.role] ?? 0.7;
        let rate = baseFollow * roleEase * (0.94 + h * 0.02);
        if (pin.id === carrierId && !ballAttached) rate *= 0.45;
        // Engine fix — Milestone 4: match rhythm, continuous edition. The
        // first version only touched the ball carrier and only changed
        // anything behind a coin-flip check refreshed every 0.1-0.4 match-
        // minutes — in practice that meant one dot out of 22 occasionally
        // twitching, invisible against the whole pitch. Real rhythm is
        // constant and applies to everyone: every outfield pin continuously
        // breathes between a context target (patient build-up slows the
        // whole side down, a counter speeds everyone up, box occupation
        // widens the swing into genuine chaos) and a per-pin sine wobble
        // (phase-offset per pin via iHash so 22 players don't move in
        // lockstep) riding on top of it — always on, every frame, no gate.
        if (pin.role !== "GK") {
          const rhythmStage = spell && spell.side === pin.side ? spell.stage : phase;
          const rhythmUrg = progressionUrgency(spell);
          let tempoTarget = 1.0;
          let tempoAmp = 0.12;
          let tempoFreq = 1.1;
          if (rhythmUrg >= 1.1 && (rhythmStage === "PROGRESSING" || rhythmStage === "FINAL_THIRD")) {
            tempoTarget = 1.28;
            tempoAmp = 0.16;
            tempoFreq = 1.6;
          } else if (rhythmStage === "BOX_OCCUPATION" || rhythmStage === "CHANCE_CREATION" || rhythmStage === "FINISH") {
            tempoTarget = 1.0;
            tempoAmp = 0.34;
            tempoFreq = 2.6;
          } else if ((rhythmStage === "BUILD_UP" || rhythmStage === "PROGRESSING") && rhythmUrg < 0.5) {
            tempoTarget = 0.78;
            tempoAmp = 0.14;
            tempoFreq = 0.85;
          }
          if (pin._tempoTargetSmooth == null) pin._tempoTargetSmooth = 1;
          pin._tempoTargetSmooth = lerp(pin._tempoTargetSmooth, tempoTarget, 0.05);
          const wobble = Math.sin(matchMinute * tempoFreq + iHash(pin.id) * 6.28) * tempoAmp;
          const localPressure = pressureAt(pin.left, pin.top, pin.side);
          const pressureBias = (localPressure - 0.4) * 0.12;
          rate *= clamp(pin._tempoTargetSmooth + wobble + pressureBias, 0.35, 1.8);
        }
        if (pin._pressing) rate *= 1.35;
        else if (pin._running) rate *= 1.28;
        else if (pin.side !== possession && dist(pin, ball) < 12) rate *= 1.08;
        let wantL = pin.tx;
        let wantT = pin.ty;
        if (pin._pathCtrl && pin._pathCtrl.until > matchMinute) {
          const span = Math.max(0.12, pin._pathCtrl.until - (pin._pathCtrl.from ?? matchMinute - 0.35));
          const u = clamp((matchMinute - (pin._pathCtrl.from ?? matchMinute - span)) / span, 0, 1);
          wantL = bezier2(pin.left, pin._pathCtrl.left, pin.tx, easeInOut(u));
          wantT = bezier2(pin.top, pin._pathCtrl.top, pin.ty, easeInOut(u));
          rate = Math.max(rate, 0.08);
        } else if (pin._pathCtrl) {
          pin._pathCtrl = null;
        }
        // Experiment — continuous local optimization, ball carrier only (see
        // optimizeCarrierPosition). Overrides wantL/wantT for THIS FRAME
        // only, for THIS pin only, while they're actually carrying and no
        // scripted pathCtrl (e.g. a shot's plant-foot bulge) is running —
        // pin.tx/pin.ty themselves are never touched, so the instant this
        // player stops carrying (or a pathCtrl takes over) they fall
        // straight back to the untouched target-based system below, same as
        // every other player, every other frame.
        if (pin.id === carrierId && ballAttached && !pin._pathCtrl) {
          const opt = optimizeCarrierPosition(pin);
          wantL = opt.left;
          wantT = opt.top;
        }
        const prevLeft = pin.left;
        const prevTop = pin.top;
        // Engine fix — curved steering (Milestone 1: locomotion). The old
        // model had no velocity at all: every frame it re-lerped position
        // directly toward the target, so heading snapped to point exactly at
        // wherever tx/ty currently was — the "gliding to a fixed target" feel.
        // Now each pin carries a real velocity (pin.vx/vy) that only turns
        // gradually toward the desired direction (steerRate below, reusing
        // the same role/context-aware `rate` this file already computes for
        // every modifier above — pressing, running, tempo, pathCtrl — so all
        // of that tuning carries over instead of being redone), which is what
        // actually produces curved paths and slight overshoot/correction
        // instead of an instant turn. Speed itself also ramps down near the
        // target (decelRadius) rather than cruising at full speed until it
        // suddenly arrives.
        const cruiseSpeed = pinRunSpeedPct(pin);
        const toL = wantL - pin.left;
        const toT = wantT - pin.top;
        const distToTarget = Math.hypot(toL, toT);
        const decelRadius = 4;
        const speedScale = distToTarget > 1e-6 ? clamp(distToTarget / decelRadius, 0.12, 1) : 0;
        const dirL = distToTarget > 1e-6 ? toL / distToTarget : 0;
        const dirT = distToTarget > 1e-6 ? toT / distToTarget : 0;
        const desiredVx = dirL * cruiseSpeed * speedScale;
        const desiredVy = dirT * cruiseSpeed * speedScale;
        if (pin.vx == null) {
          pin.vx = 0;
          pin.vy = 0;
        }
        const steerRate = clamp(rate * 2.4, 0.06, 0.95);
        pin.vx = lerp(pin.vx, desiredVx, steerRate);
        pin.vy = lerp(pin.vy, desiredVy, steerRate);
        let nextLeft = pin.left + pin.vx * dt;
        let nextTop = pin.top + pin.vy * dt;
        // Safety cap: bound how far one frame can move regardless of any
        // velocity overshoot, same spirit as the old maxStep clamp.
        const maxStepThisFrame = Math.max(0.05, cruiseSpeed * 1.6 * dt);
        const stepDx = nextLeft - pin.left;
        const stepDy = nextTop - pin.top;
        const stepMag = Math.hypot(stepDx, stepDy);
        if (stepMag > maxStepThisFrame && stepMag > 1e-9) {
          const s = maxStepThisFrame / stepMag;
          nextLeft = pin.left + stepDx * s;
          nextTop = pin.top + stepDy * s;
        }
        pin.left = clamp(nextLeft, 1, 99);
        pin.top = clamp(nextTop, 1, 99);
        // Engine fix — player orientation (Problem 11). Every other engine
        // piece (intent, support roles, anticipation) has been a proxy for
        // "what is this player about to do" because there was never an
        // actual orientation property on a pin. Derive a real facing
        // direction from actual movement this frame; when barely moving
        // (marking, holding shape), default to facing the ball, which is
        // what a stationary player is actually looking at.
        const moveDx = pin.left - prevLeft;
        const moveDy = pin.top - prevTop;
        const moveMag = Math.hypot(moveDx, moveDy);
        if (moveMag > 0.015) {
          const newFacingX = moveDx / moveMag;
          const newFacingY = moveDy / moveMag;
          // Engine fix — event-triggered micro-update, rotation edition (carrier
          // only — checking every pin every render frame would be wasted work
          // for the one reaction that actually matters). A sharp turn (>45°,
          // dot product of old vs new facing below ~0.7) redirects the nearest
          // teammate's in-progress run immediately; cooldown stops one sustained
          // spin from refiring every frame.
          if (
            pin.id === carrierId &&
            pin.facingX != null &&
            matchMinute >= (pin._rotationReactCooldown || 0) &&
            pin.facingX * newFacingX + pin.facingY * newFacingY < 0.7
          ) {
            triggerCarrierRotationReaction(pin);
            pin._rotationReactCooldown = matchMinute + 0.4;
          }
          pin.facingX = newFacingX;
          pin.facingY = newFacingY;
        } else if (pin.facingX == null) {
          const bx = ball.left - pin.left;
          const by = ball.top - pin.top;
          const bm = Math.hypot(bx, by) || 1;
          pin.facingX = bx / bm;
          pin.facingY = by / bm;
        }
        // Render trails logical (slightly softer / slower) — never chases tx directly
        if (pin.rx == null) pin.rx = pin.left;
        if (pin.ry == null) pin.ry = pin.top;
        const maxLogical = Math.max(0.04, cruiseSpeed * dt);
        const maxRender = maxLogical * 0.92;
        const rendered = stepTowardClamped(pin.rx, pin.ry, pin.left, pin.top, rate * 0.88, maxRender);
        pin.rx = rendered.left;
        pin.ry = rendered.top;
        const el = pinEls.get(pin.id);
        if (el) {
          const rPos = toRenderXY(pin.rx, pin.ry);
          el.style.left = `${rPos.left}%`;
          el.style.top = `${rPos.top}%`;
          el.classList.toggle("has-ball", pin.id === carrierId);
          el.classList.toggle(
            "pressing",
            pin.side !== possession && (pin._pressing || dist(pin, ball) < 8 + sidePress(pin.side) * 5)
          );
          el.classList.toggle("running", Boolean(pin._running) && pin.id !== carrierId);
        }
        const dbg = debugDotEls.get(pin.id);
        if (dbg) {
          const rDbg = toRenderXY(pin.left, pin.top);
          dbg.style.left = `${rDbg.left}%`;
          dbg.style.top = `${rDbg.top}%`;
        }
      }
    }

    /** Hard-sync logical = rendered = target (kickoff / reset / set-piece only). */
    function snapPinPose(pin, left, top) {
      const L = clamp(left, 2, 98);
      const T = clamp(top, 2, 98);
      pin.left = L;
      pin.top = T;
      pin.tx = L;
      pin.ty = T;
      pin.rx = L;
      pin.ry = T;
      pin.vx = 0;
      pin.vy = 0;
      pin._pathCtrl = null;
      const el = pinEls.get(pin.id);
      if (el) {
        const rSnap = toRenderXY(L, T);
        el.style.left = `${rSnap.left}%`;
        el.style.top = `${rSnap.top}%`;
      }
      const dbg = debugDotEls.get(pin.id);
      if (dbg) {
        const rDbgSnap = toRenderXY(L, T);
        dbg.style.left = `${rDbgSnap.left}%`;
        dbg.style.top = `${rDbgSnap.top}%`;
      }
    }

    function attachBallToCarrier() {
      const c = findCarrier();
      if (!c || !ballAttached) return;
      const offsetY = c.side === "home" ? -1.2 : 1.2;
      // Stick ball to rendered feet so it doesn't float ahead of the sprite
      const wantL = c.rx ?? c.left;
      const wantT = (c.ry ?? c.top) + offsetY;
      // Ease onto feet — never hard-snap when possession transfers
      ball.left = smoothDamp(ball.left, wantL, 0.38);
      ball.top = smoothDamp(ball.top, wantT, 0.38);
      const rBall = toRenderXY(ball.left, ball.top);
      ballEl.style.left = `${rBall.left}%`;
      ballEl.style.top = `${rBall.top}%`;
    }

    function giveBall(pin, comment) {
      if (decisionDiagAll || decisionDiagRoles.size) {
        possessionCounts[pin.id] = (possessionCounts[pin.id] || 0) + 1;
      }
      const prevSide = possession;
      const sideChanged = !spell || pin.side !== prevSide;
      carrierId = pin.id;
      possession = pin.side;
      ballAttached = true;
      ballCtrl = null;
      pin._boxDriveDone = false;
      pin._dribbleStreak = 0;
      pin._lastDribbleOpp = null;
      if (sideChanged) clearLastPasser();
      setBallTarget(pin.left, pin.top + (pin.side === "home" ? -1.2 : 1.2), 0.32, true);
      if (comment) say(comment);
      if (sideChanged) beginSpell(pin.side, comment || "possession");
      else updatePhaseFromBall();
    }

    /** Draw how long (match minutes) this side keeps the ball before spell resolves. */
    function drawSpellDuration(side) {
      const possQ = sidePoss(side);
      const resist = sideResist(side);
      const press = sidePress(oppOf(side));
      const edge = press - resist;
      // Baseline hold + differential press (not absolute intensity)
      const hold = 0.58 + possQ * 0.3 + resist * 0.26 - Math.max(-0.12, edge) * 0.16 + (rng() - 0.5) * 0.3;
      return clamp(4.4 + hold * 8.2 + rng() * 3.0, 3.6, 15);
    }

    /**
     * Engine fix — anchor total chance volume to the pre-match quality-implied
     * xG target (targetXgHome/targetXgAway, read from opts.xgHome/xgAway —
     * the same number the Monte Carlo engine already computes and displays
     * pre-match, but that the live spell pipeline never once compared itself
     * against). Root cause found by instrumenting two live matches of the
     * identical fixture: total match xG swung from 0.53 to 4.73 for the same
     * side, traced to shot COUNT (not per-shot xG) — 11 shots in one run, 1
     * in the other — because nothing in the spell pipeline ever checks a
     * side's actual accumulated xG so far against what its own quality
     * predicts for a full 90 minutes. This is a bounded mean-reversion on
     * spellChanceP (whether a spell escalates into a shot at all): a side
     * running well above its own expected pace gets throttled toward fewer
     * further chances; a side running well below gets a lift. Deliberately
     * not touching per-shot xG (estimateChanceXg) or conversion
     * (organicWillScore/finishingForm) — those were checked and are fine in
     * isolation; this only tempers how often a spell is allowed to become a
     * shot in the first place. "Slight variance" is still expected — this
     * dampens runaway swings, it doesn't erase them.
     *
     * Strengthened after a real production match still finished 3.6 vs 1.8
     * xG against a 2.24-2.19 target (Team B kept scoring steadily at 53',
     * 74', 86' — well after they were already running hot, exactly when the
     * original 0.55-slope/0.55-floor version should have been braking hardest
     * but wasn't: at that magnitude of overshoot it only cut spellChanceP to
     * ~0.67x, nowhere near enough against ~10-15 total spells). Slope
     * doubled, floor/ceiling widened. Also now blended into estimateChanceXg
     * (partial weight, not full — frequency was already the primary lever
     * and shouldn't be fully duplicated) so a side running hot gets both
     * fewer additional chances AND slightly tougher ones once it does get
     * one, instead of frequency alone trying to carry the whole correction.
     */
    function xgPaceMul(side) {
      const target = side === "home" ? targetXgHome : targetXgAway;
      if (!Number.isFinite(target) || target <= 0.05) return 1;
      const progress = clamp(matchMinute / 90, 0.12, 1);
      const expectedSoFar = target * progress;
      const relGap = (liveXg[side] - expectedSoFar) / Math.max(target, 0.6);
      return clamp(1 - relGap * 1.1, 0.3, 1.7);
    }

    /** Probability this spell produces a shot attempt (~most spells; target ~10–14 shots / match). */
    function spellChanceP(side) {
      const create = sideCreate(side);
      const atk = sideAttack(side);
      const def = sideDefend(oppOf(side));
      const vol = possChanceVolumeMul(side);
      const supp = possessionSuppressionMul(side);
      // Floor/base pulled down — every possession firing a shot attempt 52-92%
      // of the time meant defence never got credit for just containing a spell
      // without it escalating into a chance. Underdogs still fire reasonably
      // often; possession control soft-scales volume; attack weight kept
      // relative to creation so a strong attack isn't ignored either.
      // Engine fix — protect-the-lead mentality: fewer forced chance
      // attempts for a few minutes right after scoring, same spirit as the
      // pattern-weight shift in pickAttackPattern.
      const leadProtectMul = (leadProtectUntil[side] || 0) > matchMinute ? 0.72 : 1;
      // Knockout-only home push (chance creation) — see KNOCKOUT_HOME_PUSH.
      const homePushMul = isKnockout && !isFinalRound && side === "home" ? 1 + KNOCKOUT_HOME_PUSH : 1;
      return clamp(
        (0.42 + create * 0.24 + atk * 0.18 - def * 0.03 + (rng() - 0.5) * 0.05) *
          vol *
          lerp(1, supp, 0.45) *
          xgPaceMul(side) *
          leadProtectMul *
          homePushMul,
        0.32,
        0.72
      );
    }

    function beginSpell(side, reason) {
      const dur = drawSpellDuration(side);
      const willChance = rng() < spellChanceP(side);
      spell = {
        side,
        stage: "BUILD_UP",
        start: matchMinute,
        end: matchMinute + dur,
        willAttemptChance: willChance,
        chanceDone: false,
        actions: 0,
        patience: 0,
        combo: null,
        lastReceivers: [],
        reason: reason || "builds",
        pattern: null,
        lastPattern: null,
        patternConfidence: 100,
        patternActions: 0,
        patternAnnounced: false,
        patternBaselinePressure: null,
        patternHint: null,
        awaitingBoxShot: false,
        // Per-action scoring project, Phase C — continuity for the unified
        // evaluateArrivals argmax. Same shape as pattern/patternConfidence
        // above (start 100, decay -15/action, invalidated on a pressure
        // spike) but tracks a concrete last-picked action type instead of
        // an abstract category, so scoring doesn't flip-flop tick to tick
        // while still letting a genuinely much better option win instantly
        // (it's an additive nudge, not a gate).
        lastActionType: null,
        lastActionTargetId: null,
        actionContinuityConfidence: 100,
        actionContinuityBaselinePressure: null,
      };
      phase = "BUILD_UP";
      pushMatchEvent("possession", side, { detail: reason || "builds" });
      if (commentaryHold <= 0.4) {
        const name = side === "home" ? homeTeam.name : awayTeam.name;
        say(`${name} in possession`, 1.4);
      }
      // FM Mobile broadcast mode -- a spell that's going to attempt a
      // chance gets the slow full-pitch view once it's actually
      // APPROACHING that chance (see MOBILE_BUILDUP_WINDOW below), not
      // from the moment the possession starts. Bug fix -- this used to
      // fire unconditionally on willChance alone, and spells can run
      // 3.6-15 match-minutes (drawSpellDuration), so a long spell put the
      // full pitch up for its ENTIRE duration: measured live, 90.7% of a
      // full match ended up in "live" mode, inverting the whole point of
      // the commentary-first design. Only a spell already short enough to
      // BE within the buildup window at kickoff triggers here; everything
      // else is caught by the tick-loop poll once it's actually close.
      if (mobileBroadcast && willChance && dur <= MOBILE_BUILDUP_WINDOW) {
        mobileBuildupActive = true;
        if (mobileEventUntilTs <= 0) {
          speed = MOBILE_EVENT_SPEED;
          setMobileLive(true);
        }
      }
    }

    function archiveSpell(outcome) {
      if (!spell) return;
      matchLog.spells.push({
        side: spell.side,
        start: Math.floor(spell.start),
        end: Math.floor(matchMinute),
        duration: Math.round((matchMinute - spell.start) * 10) / 10,
        will_chance: Boolean(spell.willAttemptChance),
        chance_done: Boolean(spell.chanceDone),
        pattern: spell.pattern || spell.lastPattern || null,
        stage: spell.stage || null,
        outcome: outcome || "ended",
        actions: spell.actions || 0,
      });
      // If this spell was flagged for the buildup view but never actually
      // produced a key event (triggerMobileHighlight never fired during
      // it), drop back to fast mode instead of leaving the viewer stuck on
      // a slow view of a spell that fizzled into a turnover.
      if (mobileBroadcast && mobileBuildupActive && mobileEventUntilTs <= 0) {
        speed = MOBILE_NORMAL_SPEED;
        setMobileLive(false);
      }
      mobileBuildupActive = false;
    }

    /**
     * Advance possession state by ball depth + box occupation (not timers alone).
     * Recycle drops via dropPossessionState().
     */
    function syncPossessionState() {
      if (!spell || spell.side !== possession) return;
      const carrier = findCarrier();
      const depth = possessionDepth(carrier);
      const boxed = countBoxAttackers(spell.side);
      const arriving = countArrivingRunners(spell.side);
      let next = spell.stage;

      // Soft timer nudge only — never sole driver
      const span = Math.max(0.5, spell.end - spell.start);
      const frac = clamp((matchMinute - spell.start) / span, 0, 1.2);

      if (spell.stage === "FINISH") {
        next = "FINISH";
      } else if (spell.awaitingShot || spell.awaitingBoxShot) {
        next = "CHANCE_CREATION";
      } else if (boxed >= 2 || (boxed >= 1 && arriving >= 1)) {
        const vol = possChanceVolumeMul(spell.side);
        const supp = possessionSuppressionMul(spell.side);
        // Low-poss / suppressed sides need more commitment before CHANCE_CREATION
        const chanceReady =
          spell.willAttemptChance ||
          (depth >= 0.75 && vol * supp > 0.78) ||
          (depth >= 0.82 && isMaestroPin(carrier));
        next = chanceReady ? "CHANCE_CREATION" : "BOX_OCCUPATION";
      } else if (boxed >= 1 || depth >= 0.72) {
        next = "BOX_OCCUPATION";
      } else if (depth >= 0.58 || frac > 0.5) {
        next = "FINAL_THIRD";
      } else if (depth >= 0.38 || frac > 0.22) {
        next = "PROGRESSING";
      } else {
        next = "BUILD_UP";
      }

      // Never jump backward via sync (only recycle drops)
      if (possIndex(next) < possIndex(spell.stage)) next = spell.stage;
      // Cap advance to one step per sync unless box/chance demands
      if (possIndex(next) > possIndex(spell.stage) + 1) {
        if (next === "CHANCE_CREATION" || next === "BOX_OCCUPATION") {
          /* allow jump into box/chance */
        } else {
          next = POSS_ORDER[Math.min(possIndex(spell.stage) + 1, POSS_ORDER.length - 1)];
        }
      }

      if (next !== spell.stage) {
        spell.stage = next;
        updatePhaseFromBall();
      }
    }

    /** @deprecated alias */
    function syncSpellStage() {
      syncPossessionState();
    }

    function pressTurnoverChance(carrier) {
      const press = sidePress(oppOf(carrier.side));
      const resist = sideResist(carrier.side);
      const possQ = sidePoss(carrier.side);
      const edge = press - resist;
      const stageMul = {
        BUILD_UP: 0.55,
        PROGRESSING: 0.72,
        FINAL_THIRD: 0.85,
        BOX_OCCUPATION: 0.92,
        CHANCE_CREATION: 1.02,
        FINISH: 1.05,
      }[spell?.stage || "PROGRESSING"] || 0.8;
      const near = nearestOpponents(carrier, 11, 2);
      const closest = near[0];
      const nearMul = closest
        ? clamp(1.2 - closest.d / 13, 0.32, 1.22) * (near.length > 1 && near[1].d < 9 ? 1.1 : 1)
        : 0.26;
      const presserBonus = closest && (closest.pin.role === "DM" || closest.pin.role === "CM") ? 1.06 : 1;
      // Cap press-edge contribution so rock-bottom resist (~0.08) isn't double-punished
      // into constant turnovers before the final third.
      const edgeTerm = Math.min(0.11, Math.max(0, edge) * 0.12);
      const pressWin = Math.max(0, 0.028 + edgeTerm - possQ * 0.045 - resist * 0.035);
      return clamp((0.018 + pressWin * stageMul * nearMul * presserBonus + (rng() - 0.5) * 0.022), 0.012, 0.16);
    }

    function doTurnover(carrier, detail) {
      const opp = nearestOpponent(carrier, 28)?.pin || pinsOf(oppOf(carrier.side)).find((p) => p.role !== "GK");
      if (!opp) return;
      pushMatchEvent("turnover", carrier.side, {
        player: carrier.player,
        player_short: carrier.short,
        by: opp.player,
        against: opp.side,
        detail: detail || "loses possession",
      });
      archiveSpell("turnover");
      say(`${opp.short} wins it — ${detail || "turnover"}`, 1.5);
      spell = null;
      giveBall(opp, `${opp.short} on the break`);
      actionTimer = 0.55 + rng() * 0.35;
      // Engine fix — this was the one turnover pathway with zero reaction of
      // any kind: resolveBallFlight's intercept/steal outcome already fires
      // triggerTurnoverReactions for the side that just won it, but a press-
      // forced mistake (decideAction's "pressed into a mistake" branch,
      // which calls doTurnover directly) skipped both that AND the
      // conceding side's defensive recovery — a fast break could go straight
      // from turnover to goal with nobody on the losing side reacting at
      // all. carrier is the one who just lost it; treat them as the trigger
      // point the same way a beaten defender would be (chase back, nearest
      // covering teammates react) since the whole side now needs to
      // organize immediately, not just whoever misplaced the ball.
      triggerTurnoverReactions(opp);
      triggerDefensiveBreachReactions(carrier);
    }

    function spellIdlePause() {
      const stage = spell?.stage || "PROGRESSING";
      if (stage === "BUILD_UP") return 0.28 + rng() * 0.35;
      if (stage === "PROGRESSING") return 0.22 + rng() * 0.28;
      if (stage === "FINAL_THIRD") return 0.2 + rng() * 0.24;
      return 0.18 + rng() * 0.22;
    }

    function attemptSpellChance(carrier) {
      if (!spell) return;
      spell.stage = "CHANCE_CREATION";
      phase = "CHANCE_CREATION";
      say(`Chance brewing — ${carrier.short}`, 1.25);
      const pattern = refreshSpellPattern(carrier) || spell.pattern;
      const create = sideCreate(carrier.side);
      const ready = boxOccupationReady(carrier.side);
      const maestro = isMaestroPin(carrier);
      const lowPoss = sidePoss(carrier.side) < sidePoss(oppOf(carrier.side)) - 0.04;
      // Maestro on low-poss side: still force dangerous actions out of nothing
      const maestroShine = maestro && lowPoss;

      // Engine rebuild — separate AM/ST intelligence. Every branch below this
      // point that follows was written as "(carrier.role === 'ST' ||
      // carrier.role === 'AM')" — an AM on the ball made the exact same
      // drive/shoot choices as a ST with the same stats, differing only in
      // shooterTarget's role bias for who *else* gets picked, never in what
      // the AM itself does with the ball. A CAM's real job is chance
      // creation first, shooting second; give that its own gate ahead of
      // everything else, scaled by the AM's own creative-vs-finishing
      // profile so a genuinely goal-hungry AM (high xg90 relative to xa90)
      // still plays like a shooting threat instead of being forced to pass.
      if (carrier.role === "AM" && !inPenaltyBox(carrier) && !maestroShine) {
        const amStats = carrier.stats;
        const creatorMod = creatorBehaviorModifiers(carrier);
        const creativeEdge = amStats.xa90 * 1.3 + amStats.key_passes90 * 0.35 - amStats.xg90 * 0.9 + creatorMod.amGateBoost;
        if (creativeEdge > 0.05) {
          const shooter = shooterTarget(carrier);
          if (shooter.id !== carrier.id && rng() < 0.5 + amStats.xa90 * 0.5 + amStats.key_passes90 * 0.1) {
            const kind =
              throughBallLegal(carrier, shooter) && rng() < (0.5 + amStats.key_passes90 * 0.14 + amStats.xa90 * 0.25) * creatorMod.throughBallMultiplier
                ? "through"
                : "pass";
            spell.awaitingShot = true;
            doPass(carrier, shooter, kind);
            return;
          }
        }
      }

      // Without box occupation, refuse high-xG path — recycle instead
      if (!ready && !inPenaltyBox(carrier)) {
        if (
          (carrier.role === "ST" || carrier.role === "AM" || carrier.role === "CM" || carrier.role === "DM" || maestroShine) &&
          rng() < 0.55 + carrier.stats.xg90 * 0.2 + (maestroShine ? 0.22 : 0)
        ) {
          spell.awaitingBoxShot = true;
          if (driveIntoBox(carrier)) return;
        }
        if (isWideFinalThird(carrier)) {
          decideWideFinalThird(carrier);
          return;
        }
        // Probe toward box / recycle
        const creatorMod = creatorBehaviorModifiers(carrier);
        if (rng() < 0.45 + (maestroShine ? 0.2 : 0) + creatorMod.progressiveBoost || forwardInFinalThird(carrier) || maestroShine) {
          if (forwardInFinalThird(carrier) || maestroShine) {
            forwardFinalThirdAction(carrier);
            return;
          }
          doPass(carrier, progressiveTarget(carrier), "pass");
          return;
        }
        doPass(carrier, backPassTarget(carrier), "pass");
        dropPossessionState(1);
        return;
      }

      if (
        spell.awaitingBoxShot ||
        ((carrier.role === "ST" ||
          carrier.role === "AM" ||
          carrier.role === "CM" ||
          carrier.role === "DM" ||
          maestroShine) &&
          !inPenaltyBox(carrier) &&
          rng() < 0.72 + carrier.stats.xg90 * 0.25 + (maestroShine ? 0.12 : 0))
      ) {
        spell.awaitingBoxShot = true;
        if (driveIntoBox(carrier)) return;
      }

      spell.chanceDone = true;

      if (isWideFinalThird(carrier) || pattern === "wing_carry") {
        if (isWideChannel(carrier) && (carrier.role === "W" || carrier.role === "FB")) {
          decideWideFinalThird(carrier);
          return;
        }
      }
      if (pattern === "cut_inside" && (carrier.role === "W" || carrier.role === "AM")) {
        if (!inPenaltyBox(carrier) && rng() < 0.65) {
          spell.awaitingBoxShot = true;
          spell.chanceDone = false;
          if (driveIntoBox(carrier)) return;
          spell.chanceDone = true;
        }
        // Bug fix — same class as the attemptSpellChance final-fallback fix:
        // gate on the carrier's own proximity, not team box-readiness, so a
        // failed/skipped drive-in doesn't fall through to a naked long shot.
        if (!inPenaltyBox(carrier) && !nearPenaltyBox(carrier)) {
          if (forwardInFinalThird(carrier)) {
            forwardFinalThirdAction(carrier);
            return;
          }
          doPass(carrier, backPassTarget(carrier), "pass");
          dropPossessionState(1);
          return;
        }
        if (rng() < 0.55 + carrier.stats.xg90 * 0.4) {
          spell.awaitingShot = false;
          spell.stage = "FINISH";
          doShot(carrier, false);
          return;
        }
      }
      if (pattern === "central" || pattern === "wide_switch") {
        const shooter = shooterTarget(carrier);
        if (shooter.id !== carrier.id && rng() < 0.6 + create * 0.25) {
          const kind =
            pattern === "central" &&
            throughBallLegal(carrier, shooter) &&
            rng() < 0.55 + carrier.stats.key_passes90 * 0.12 + carrier.stats.xa90 * 0.2
              ? "through"
              : "pass";
          spell.awaitingShot = true;
          doPass(carrier, shooter, kind);
          return;
        }
      }

      const shooter = shooterTarget(carrier);
      if (shooter.id !== carrier.id && rng() < 0.55 + create * 0.25) {
        const kind =
          throughBallLegal(carrier, shooter) && rng() < 0.45 + carrier.stats.key_passes90 * 0.12 + carrier.stats.xa90 * 0.2
            ? "through"
            : "pass";
        spell.awaitingShot = true;
        doPass(carrier, shooter, kind);
        return;
      }
      if (
        (carrier.role === "W" || carrier.role === "FB") &&
        (carrier.left < 24 || carrier.left > 76) &&
        rng() < 0.45 + carrier.stats.xa90 * 1.15
      ) {
        decideWideFinalThird(carrier);
        return;
      }
      if (
        !inPenaltyBox(carrier) &&
        (carrier.role === "ST" || carrier.role === "AM" || carrier.role === "CM" || carrier.role === "DM") &&
        rng() < 0.55
      ) {
        spell.awaitingBoxShot = true;
        spell.chanceDone = false;
        if (driveIntoBox(carrier)) return;
        spell.chanceDone = true;
      }
      // Bug fix — this used to gate the naked doShot below on team box
      // occupation only (!boxOccupationReady), not the carrier's own
      // position. That let a carrier who was himself still outside the box
      // (and not even near it) take a genuine long-range shot whenever
      // teammates happened to already be positioned inside — the source of
      // low-xG (~0.11) long shots with "nobody getting chances in the box."
      // Gate on the carrier's own proximity instead: only let the naked
      // shot through when he's boxed or near-box; otherwise keep driving in
      // or recycle possession.
      if (!inPenaltyBox(carrier) && !nearPenaltyBox(carrier)) {
        if (forwardInFinalThird(carrier)) {
          forwardFinalThirdAction(carrier);
          return;
        }
        doPass(carrier, backPassTarget(carrier), "pass");
        dropPossessionState(1);
        return;
      }
      spell.awaitingShot = false;
      spell.stage = "FINISH";
      doShot(carrier, false);
    }

    function nextScheduledGoal(side, minute) {
      return scheduled.find((g) => !g.scored && g.side === side && g.minute <= minute + 1.5);
    }

    function remainingGoals(side) {
      return scheduled.filter((g) => !g.scored && g.side === side).length;
    }

    function forceLateGoals(minute) {
      if (!replayScore || minute < 78) return null;
      const pending = scheduled.filter((g) => !g.scored);
      if (!pending.length) return null;
      return pending.find((g) => g.minute <= minute + 2) || (minute >= 86 ? pending[0] : null);
    }

    function markGoal(side) {
      const g = scheduled.find((x) => !x.scored && x.side === side);
      if (g) g.scored = true;
      if (side === "home") homeScore += 1;
      else awayScore += 1;
      lastGoalMinute = matchMinute;
      // Engine fix — protect-the-lead mentality. See declaration.
      leadProtectUntil[side] = matchMinute + 3;
      scoreEl.textContent = `${homeScore} – ${awayScore}`;
      const scorer = findCarrier();
      const scorerName = shortName(scorer?.player || "");
      const assistEligible =
        lastPasser &&
        lastPasser.side === side &&
        lastPasser.player &&
        lastPasser.player !== (scorer?.player || null);
      const assistExtra = assistEligible
        ? { assist: lastPasser.player, assist_short: lastPasser.player_short || shortName(lastPasser.player) }
        : {};
      const goalMinuteLabel = `${Math.max(0, Math.floor(matchMinute))}'`;
      const goalSubParts = [goalMinuteLabel];
      if (assistExtra.assist_short) goalSubParts.push(`Assist: ${assistExtra.assist_short}`);
      goalSubParts.push(`${homeScore}–${awayScore}`);
      showGoalCard(side, scorerName || "Goal!", initials(scorer?.player || scorerName || ""), goalSubParts.join(" · "));
      pushMatchEvent("goal", side, {
        player: scorer?.player || null,
        player_short: scorer?.short || scorerName || null,
        detail: `${homeScore}–${awayScore}`,
        ...assistExtra,
      });
      clearLastPasser();
      archiveSpell("goal");
      const assistNote = assistExtra.assist_short ? ` (assist ${assistExtra.assist_short})` : "";
      say(`GOAL! ${scorerName}${assistNote} — ${homeScore}–${awayScore}`, 2.2);
      if (onScore) onScore({ homeGoals: homeScore, awayGoals: awayScore, side, minute: matchMinute });
    }

    function doPass(from, to, kind) {
      if (!to || ballFlight) return;
      ballAttached = false;
      let passKind = kind;
      const isLong = passKind === "long" || (passKind !== "clear" && isLongSkip(from, to) && dist(from, to) > 18);
      if (isLong && passKind !== "long") passKind = "long";

      // Decide intercept / steal / offside BEFORE any animation
      const passWasOffside = passKind !== "clear" && wouldPassBeOffside(from, to, to.left, to.top);
      const threat = nearestOpponent(to, 12);
      const pressers = nearestOpponents(from, 10, 2);
      const resist = sideResist(from.side);
      const atkU = sideAttack(from.side);
      const defU = sideDefend(oppOf(from.side));
      const possQ = sidePoss(from.side);
      // Engine rebuild — real pressure on the passer instead of the static
      // team press/resist scalar pair, consistent with Phase 1 (doDribble/
      // doCarry) and Phase 4 (pattern re-picks). A passer genuinely swarmed
      // by nearby opponents should be more likely to lose it regardless of
      // the team's overall pressing rating.
      const fieldPressure = pressureAt(from.left, from.top, from.side);

      let outcome = "pass";
      let interceptor = null;
      let comment = null;

      if (threat && !(replayScore && nextScheduledGoal(possession, matchMinute))) {
        const def = threat.pin;
        // A real long-ball specialist (volume + accuracy) is genuinely
        // better at hitting this pass than the flat penalty assumed.
        const longSpecialist = passKind === "long" || isLongSkip(from, to);
        const longPen = longSpecialist
          ? clamp(0.2 - (from.stats.long_balls90 || 0) * 0.006 - ((from.stats.long_ball_pct || 55) - 55) * 0.002, 0.06, 0.22)
          : 0;
        // Engine fix — through balls had no risk premium of their own at
        // all: the interception cap and formula treated "slips it through"
        // identically to a routine short pass (capped at the same 0.3, no
        // extra penalty term the way long balls get longPen), when threading
        // a ball through a set defensive line is one of the hardest passes
        // to complete cleanly in real football — it's precisely what a
        // well-organized back line (and the offside trap) exists to punish.
        const throughPen = passKind === "through" ? 0.16 : 0;
        const laneN = defendersInLane(from, to);
        const lanePen = laneN * 0.055;
        // Engine rebuild — full anticipation. A defender already in "mark"
        // mode on the receiver has been anticipating their held intent
        // (Problem 7) every tick before this pass was even thrown - they
        // aren't starting cold. Same for "cover": its whole job is screening
        // the carrier's progressive/third-man option, so if the actual pass
        // goes to exactly that tagged teammate, the cover defender read it
        // correctly. Give both a genuine payoff in the actual interception
        // odds, not just in where the defender's sprite stands.
        const markAnticipating = def._defMode === "mark" && Boolean(to._intent);
        const coverAnticipating =
          def._defMode === "cover" && (to._supportRole === "progressive" || to._supportRole === "third_man");
        const anticipationBonus = markAnticipating ? 0.05 : coverAnticipating ? 0.04 : 0;
        // Lane control bonus: DMs screening the passing lane significantly increase interception probability
        const laneControl = computeLaneControl(def, from, to);

        const pIntercept =
          0.035 +
          def.stats.interceptions90 * 0.05 +
          def.stats.tackles90 * 0.03 +
          Math.min(0.1, Math.max(0, fieldPressure - resist * 1.4) * 0.09) +
          defU * 0.07 -
          resist * 0.05 -
          possQ * 0.055 -
          atkU * 0.04 -
          from.stats.pass_pct * 0.0015 -
          from.stats.key_passes90 * 0.008 -
          // A creator who genuinely outscores their own xA in assists
          // threads passes better than pass_pct/key_passes90 alone predict.
          (isClinicalCreator(from) ? 0.015 : 0) +
          // Generic ball-security signal — a passer who loses possession a
          // lot in real matches is a bit sloppier even before live pressure.
          (from.stats.possession_lost90 || 0) * 0.0015 +
          longPen +
          throughPen +
          lanePen +
          laneControl +
          anticipationBonus;
        const cap = passKind === "long" ? 0.48 : passKind === "through" ? 0.4 : 0.3;
        if (rng() < clamp(pIntercept, 0.025, cap)) {
          outcome = "intercept";
          interceptor = def;
          comment = `${def.short} intercepts`;
          pushMatchEvent("pass_broken", def.side, {
            player: def.player,
            player_short: def.short,
            against: from.side,
            by: def.player,
            detail: passKind === "long" ? `cuts out the long ball` : `broke ${from.short}'s pass`,
          });
        }
      }
      if (outcome === "pass" && pressers[0] && fieldPressure > 0.3 && passKind !== "clear") {
        const p = pressers[0].pin;
        // Engine rebuild — full anticipation, press's own duel payoff. A
        // presser in active "press" mode has been angling their run with
        // cover shadow, reading the danger option, not just reacting cold
        // when they happen to get close. Give that anticipation a bonus in
        // the actual steal-in-the-tackle odds too, not just interception.
        const pressAnticipating = p._defMode === "press";
        const stealP =
          0.028 +
          Math.max(0, fieldPressure - resist * 1.2) * 0.11 +
          p.stats.tackles90 * 0.035 -
          from.stats.dribble_pct * 0.0012 +
          (pressAnticipating ? 0.03 : 0);
        if (rng() < clamp(stealP, 0.015, 0.22)) {
          outcome = "steal";
          interceptor = p;
          comment = `${p.short} wins it in the press`;
          pushMatchEvent("pass_broken", p.side, {
            player: p.player,
            player_short: p.short,
            against: from.side,
            by: p.player,
            detail: `presses ${from.short}`,
          });
        }
      }
      if (outcome === "pass" && passWasOffside) {
        outcome = "offside";
      }

      // Destination locked to the decided outcome — ball never retargets mid-flight
      let tx = to.left;
      let ty = to.top;
      let crossPost = null;
      if (outcome === "intercept" || outcome === "steal") {
        // Bug fix — same class as the driveIntoBox/doDribble teleport fix:
        // the ball used to snap straight to wherever the interceptor
        // happened to be standing, which can be well off the actual pass
        // line (a presser near the passer, or a marker off to the side of
        // the receiver), with that defender's own pin never moving to meet
        // it — reads as the attacker just passing it straight to the
        // "wrong" player. Land it at the closest point ON THE PASS'S OWN
        // FLIGHT LINE to the interceptor (where the interception
        // realistically happens), and give the interceptor a short
        // corrective close-down to that same point so the pins actually
        // converge on screen.
        const abx = to.left - from.left;
        const aby = to.top - from.top;
        const lenSq = abx * abx + aby * aby || 1;
        let t = ((interceptor.left - from.left) * abx + (interceptor.top - from.top) * aby) / lenSq;
        t = clamp(t, 0.15, 0.95);
        tx = from.left + abx * t;
        ty = from.top + aby * t;
        interceptor.tx = tx;
        interceptor.ty = ty;
        interceptor._running = true;
        interceptor.lockUntil = matchMinute + 0.5;
      } else if (passKind === "through") {
        const attackSign = from.side === "home" ? -1 : 1;
        ty = clamp(to.top + attackSign * 4, 4, 96);
      } else if (passKind === "cross") {
        const fromLeft = from.left < 50;
        crossPost = rng() < 0.55 ? "near" : "far";
        if (crossPost === "near") {
          tx = fromLeft ? clamp(36 + rng() * 10, 28, 48) : clamp(52 + rng() * 10, 52, 72);
        } else {
          tx = fromLeft ? clamp(54 + rng() * 14, 50, 74) : clamp(26 + rng() * 14, 26, 50);
        }
        ty = from.side === "home" ? clamp(8 + rng() * 12, 5, 26) : clamp(92 - rng() * 12, 74, 95);
        // Contested header vs aerial defence / CB positioning — decided before flight.
        // Engine rebuild — migrated off the static sideAerial/strikerAerialThreat
        // squad-wide scalars (never touched actual positions) onto boxAerialPresence,
        // the same proximity²-weighted real-position field pressureAt uses elsewhere:
        // how many bodies are genuinely in the box around the landing spot, not a
        // team-average rating applied regardless of who actually made the run.
        if (outcome === "pass") {
          const cbs = pinsOf(oppOf(from.side)).filter((p) => p.role === "CB");
          let bestCb = null;
          let bestD = Infinity;
          for (const cb of cbs) {
            const d = Math.hypot(cb.left - tx, cb.top - ty);
            if (d < bestD) {
              bestD = d;
              bestCb = cb;
            }
          }
          const toAerial =
            (to.stats.aerials_won90 || 0) > 0
              ? (to.stats.aerials_won90 || 0) * 0.08 *
                Math.max(0.45, (to.stats.aerials_won_pct || 50) / 100)
              : 0;
          const atkBoxPresence = boxAerialPresence(tx, ty, from.side, to.id);
          const defBoxPresence = boxAerialPresence(tx, ty, oppOf(from.side));
          const attAerial =
            0.32 +
            to.stats.xg90 * 0.36 +
            toAerial +
            (to.role === "ST" ? 0.14 : 0.05) +
            from.stats.xa90 * 0.3 +
            atkU * 0.08 +
            atkBoxPresence * 0.18;
          const defAerial =
            defBoxPresence * 0.5 +
            (bestCb ? 0.18 + bestCb.stats.interceptions90 * 0.045 + bestCb.stats.tackles90 * 0.02 : 0.12) +
            (bestD < 11 ? 0.14 : bestD < 16 ? 0.06 : 0) +
            defU * 0.08;
          const winP = clamp(0.4 + attAerial - defAerial + (rng() - 0.5) * 0.1, 0.16, 0.8);
          if (rng() > winP && bestCb) {
            outcome = "intercept";
            interceptor = bestCb;
            comment = `${bestCb.short} wins the aerial`;
            // Bug fix — same teleport class as the open-play intercept
            // fix, though milder here since bestCb was already chosen for
            // being nearest the cross's own landing spot. Keep the ball at
            // that real landing spot (tx/ty already set above) instead of
            // snapping to bestCb's exact standing position, and give him a
            // short corrective close-down so the pin actually meets it.
            bestCb.tx = tx;
            bestCb.ty = ty;
            bestCb._running = true;
            bestCb.lockUntil = matchMinute + 0.5;
            pushMatchEvent("pass_broken", bestCb.side, {
              player: bestCb.player,
              player_short: bestCb.short,
              against: from.side,
              by: bestCb.player,
              detail: `clears ${from.short}'s cross`,
            });
          }
        }
      } else if (passKind === "cutback") {
        const fromLeft = from.left < 50;
        tx = fromLeft ? clamp(42 + rng() * 8, 36, 55) : clamp(45 + rng() * 8, 45, 64);
        ty = from.side === "home" ? clamp(to.top + 1, 14, 30) : clamp(to.top - 1, 70, 86);
      } else if (passKind === "long") {
        const attackSign = from.side === "home" ? -1 : 1;
        ty = clamp(to.top + attackSign * 2.5, 4, 96);
      }

      const arc = passArcFor(ball.left, ball.top, tx, ty, passKind);
      const dur = arc.dur;
      setBallTarget(tx, ty, dur, false, arc.ctrl);
      actionTimer = dur + 0.12 + spellIdlePause() * 0.25;

      // Receiver runs onto the landing spot during flight (logical left clamps;
      // never snap left/rx to tx). Through/cross/long/cutback lock the target now.
      if (
        outcome === "pass" &&
        (passKind === "through" || passKind === "cross" || passKind === "long" || passKind === "cutback")
      ) {
        to.tx = tx;
        to.ty = ty;
        to._running = true;
        to.lockUntil = matchMinute + dur + 0.55;
      }

      const label =
        passKind === "through"
          ? `${from.short} slips it through`
          : passKind === "switch"
            ? `Switch — ${from.short} to ${to.short}`
            : passKind === "cross"
              ? `Cross incoming — ${from.short}${crossPost ? ` (${crossPost} post)` : ""}`
              : passKind === "cutback"
                ? `${from.short} cuts it back`
                : passKind === "long"
                  ? `${from.short} goes long toward ${to.short}`
                  : `${from.short} finds ${to.short}`;
      // Wide-final already announced Cross/Cutback — don't double-speak
      if ((passKind === "cross" || passKind === "cutback") && commentaryHold > 0.8) {
        /* keep prior "Cross incoming" line */
      } else if (outcome === "pass" || outcome === "offside") say(label, 1.3);
      else if (commentaryHold <= 0.5) say(label, 1.0);

      if (pendingDecisionSnapshot && pendingDecisionSnapshot.carrierId === from.id) {
        let cls;
        if (passKind === "through") cls = "through_ball";
        else if (passKind === "cross" || passKind === "cutback") cls = "cross";
        else {
          const depthDelta = possessionDepth(to) - possessionDepth(from);
          cls = depthDelta > 0.08 ? "progressive_pass" : depthDelta < -0.05 ? "recycle" : "normal_pass";
        }
        const chosenScore = passKind !== "clear" ? scorePassingOption(from, to) : null;
        logDecisionOutcome(cls, {
          targetRole: to.role,
          targetId: to.id,
          chosenScore: Number.isFinite(chosenScore) ? Math.round(chosenScore * 100) / 100 : null,
          passKind,
          outcome,
        });
      }

      ballFlight = {
        outcome,
        pin: to,
        from,
        interceptor,
        comment,
        lockRun: passKind === "through" || passKind === "cross" || passKind === "long" || passKind === "cutback",
        lockTx: tx,
        lockTy: ty,
        thenShot: Boolean(spell?.awaitingShot) && (passKind === "cross" ? outcome === "pass" : true),
      };
      if (outcome !== "pass") clearLastPasser();
      if (spell?.awaitingShot && outcome !== "pass") {
        spell.awaitingShot = false;
      }
    }

    function doDribble(carrier) {
      if (ballFlight) return;
      if (pendingDecisionSnapshot && pendingDecisionSnapshot.carrierId === carrier.id) {
        logDecisionOutcome("dribble", {});
      }
      if (matchMinute < freeKickUntil) return; // Block dribbling during free kick
      // Engine fix — this contest never got the scrambling-window treatment
      // doCarry/driveIntoBox already have. A covering defender mid-recovery
      // (triggerDefensiveBreachReactions just fired against this side) is
      // actively closing in even though their on-pitch position hasn't
      // caught up yet — without this, doDribble's fixed 12-unit search and
      // unmodified odds meant the SECOND defender in a breakaway (e.g. the
      // far CB covering after the near CB was already beaten) got a
      // completely normal-difficulty duel, or worse, no threat at all if
      // they hadn't visually arrived — exactly backwards from a defence
      // that's actively scrambling to cover a breach.
      const scrambling = (breachRecoveryUntil[oppOf(carrier.side)] || 0) > matchMinute;
      const threat = nearestOpponent(carrier, scrambling ? 16 : 12);
      // Engine fix — this used to run the full contested-duel roll (and,
      // on success, count toward the dribbles_won stat with "dribbles
      // past X" commentary) even when nearestOpponent found nobody in
      // range at all — so an uncontested forward touch got styled and
      // counted identically to a genuine take-on ("49 dribbles" in the
      // match report with no visible take-on among them), and a rare miss
      // could only blame whichever random distant defender the fallback
      // chain landed on. No real opponent to beat is just a carry: always
      // advances the ball, doesn't touch the dribble stat, and says so
      // honestly instead of claiming to have gone past someone who isn't
      // there.
      if (!threat) {
        const attackSign = carrier.side === "home" ? -1 : 1;
        const ahead = 2.4 + carrier.stats.dribbles90 * 0.4 + rng() * 1.3;
        const jink = (rng() < 0.5 ? 1 : -1) * (1.2 + rng() * 1.8);
        const midX = clamp(carrier.left + jink, 6, 94);
        const midY = clamp(carrier.top + attackSign * ahead * 0.4, 5, 95);
        const nx = clamp(carrier.left + jink * 0.65 + (rng() - 0.5) * 1.2, 1, 99);
        const ny = clamp(carrier.top + attackSign * ahead, 2, 98);
        carrier._pathCtrl = { left: midX, top: midY, from: matchMinute, until: matchMinute + 0.4 };
        carrier.tx = nx;
        carrier.ty = ny;
        carrier.lockUntil = matchMinute + 0.7;
        ballAttached = true;
        const dur = 0.55;
        dispatchBallTarget(nx, ny + attackSign * -0.5, dur, true, null, carrier.side);
        actionTimer = dur + 0.12 + spellIdlePause() * 0.3;
        carrier._dribbleStreak = 0;
        say(`${carrier.short} carries it forward`, 1.2);
        // Engine addition — distance carried. Doesn't touch dribbles_won
        // (this is deliberately NOT a take-on stat, see above), but a
        // "most distance carried" leaderboard wants every carrying touch,
        // contested or not, same as real carry-distance analytics track it
        // separately from 1v1 take-on success.
        pushMatchEvent("carry", carrier.side, {
          player: carrier.player,
          player_short: carrier.short,
          distance: Math.round(pitchDistM({ left: carrier.left, top: carrier.top }, { left: nx, top: ny }) * 10) / 10,
        });
        ballFlight = { outcome: "dribble_won" };
        return;
      }
      const resist = sideResist(carrier.side);
      const atkU = sideAttack(carrier.side);
      const defU = sideDefend(oppOf(carrier.side));
      // Engine rebuild Phase 1 — real positional pressure instead of the
      // static team press/resist scalar. A covering second defender who
      // isn't the single nearest one now measurably raises the difficulty
      // (genuine 2v1), and a press-resistant team blunts local heat rather
      // than team-wide press that has nothing to do with this exact duel.
      const fieldPressure = pressureAt(carrier.left, carrier.top, carrier.side);
      // Each consecutive dribble against a fresh defender (without releasing the
      // ball via a pass) gets harder — covering defenders regroup/gang up, so a
      // run of 3-4 beaten defenders in one carry is rare rather than routine.
      const streak = carrier._dribbleStreak || 0;
      // Engine fix — beating a second, genuinely DIFFERENT defender in the
      // same unbroken run (e.g. a striker who's already beaten one CB now
      // facing the covering CB) needs to be meaningfully rarer than shimmying
      // past the same marker twice — real football sees a striker beat one
      // defender far more often than an entire back line in one run. The
      // existing streak penalty scales with *how many* wins in a row, but
      // didn't care whether it was the same or a new opponent each time.
      const lastBeaten = carrier._lastDribbleOpp;
      const freshDefender = threat && lastBeaten && threat.pin.id !== lastBeaten;
      // Engine fix — player orientation: a carrier still mid-turn from
      // receiving with their back to goal (see resolveBallFlight's pass
      // outcome) hasn't had a real touch to get the ball under control
      // facing forward yet.
      const backToGoal = (carrier._backToGoalUntil || 0) > matchMinute;
      // Phase 2 integration: defensive commitment modifies tackle/interception effectiveness
      // A defender who isn't willing/able to engage (low commitment) has reduced duel effectiveness
      const defCommitment = threat ? defensiveCommitment(threat.pin, carrier.left, carrier.top, threat) : 1;
      const defCommitmentMult = clamp(0.5 + defCommitment * 0.5, 0.5, 1.0); // Range 0.5-1.0 based on commitment
      // DM/CM archetype-aware blend: aggressionBias shifts a defender's stopping
      // power between tackling and reading the game instead of a flat, role-blind
      // split. aggressionBias is 0 for CB/FB (computeDefensiveArchetype only
      // classifies DM/CM), so this is a no-op there -- tackleWeight/interceptWeight
      // reduce to exactly the original 0.07/0.02 constants for every other role.
      const threatMod = threat ? defensiveArchetypeModifiers(threat.pin) : null;
      const tackleWeight = 0.07 * (1 + (threatMod ? threatMod.aggressionBias : 0));
      const interceptWeight = 0.02 * (1 + (threatMod ? -threatMod.aggressionBias * 0.6 : 0));
      // Engine addition — buff dribbling for attackers/creative players.
      // dribbles90/dribble_pct's own coefficients used to apply flat
      // across every role, so a winger's or AM's actual dribbling ability
      // translated into exactly the same practical edge as a CB's
      // incidental dribble stat. Real attacking/creative players should get
      // more out of the same underlying numbers — this only scales their
      // OWN stats up, it doesn't touch the defender's side of the contest
      // or any non-attacking role's baseline.
      const dribbleRoleMult = { ST: 1.3, W: 1.35, AM: 1.25, CM: 1.15 }[carrier.role] || 1.0;
      const successP =
        0.28 +
        carrier.stats.dribbles90 * 0.07 * dribbleRoleMult +
        carrier.stats.dribble_pct * 0.0035 * dribbleRoleMult +
        resist * 0.16 +
        atkU * 0.06 -
        Math.max(0, fieldPressure - resist * 1.6) * 0.16 -
        defU * 0.08 -
        (threat ? threat.pin.stats.tackles90 * 0.07 * defCommitmentMult : 0) -
        (threat ? threat.pin.stats.interceptions90 * 0.02 * defCommitmentMult : 0) +
        // General physical-duel modifier, centered on the 50 neutral
        // fallback -- additive to dribble_pct (attack-specific) and
        // tackles90 (defence-specific) above, not a replacement for either.
        (carrier.stats.duels_won_pct - 50) * 0.003 -
        // Engine addition — the defender's OWN duel-winning ability is what
        // actually stops a dribbler (a physical, in-the-moment contest),
        // distinct from interceptions90 above (reading/cutting a pass,
        // already correctly the dominant defensive lever in doPass instead).
        // 0.0041 solved so the pool's best pure tackler (duels_won_pct)
        // vs its most complete dribbler lands at a genuine 50/50, not
        // lopsided toward the attacker the way the shared 0.003 left it.
        (threat ? (threat.pin.stats.duels_won_pct - 50) * 0.0041 : 0) -
        Math.min(streak, 4) * 0.11 -
        (freshDefender ? 0.16 : 0) -
        (backToGoal ? 0.12 : 0) -
        (scrambling ? 0.07 : 0) +
        (rng() - 0.5) * 0.08;
      // Knockout-only home push (defending) — the home side is tougher to
      // dribble past. See KNOCKOUT_HOME_PUSH.
      const defenderIsHome = oppOf(carrier.side) === "home";
      const pushedSuccessP = isKnockout && !isFinalRound && defenderIsHome ? successP * (1 - KNOCKOUT_HOME_PUSH) : successP;

      const won = rng() < clamp(pushedSuccessP, 0.1, 0.72);
      if (threat) carrier._lastDribbleOpp = threat.pin.id;
      const attackSign = carrier.side === "home" ? -1 : 1;
      // Engine fix — a genuine contested take-on (real defender in range)
      // needs to actually read as beating someone, not blend into routine
      // shape drift. Bumped from the old 2.2-6/±2.2-5 range so the burst
      // past the defender is visually legible.
      const ahead = 2.8 + carrier.stats.dribbles90 * 0.65 + rng() * 1.8;
      const jink = (rng() < 0.5 ? 1 : -1) * (2.8 + rng() * 3.2);
      const midX = clamp(carrier.left + jink, 6, 94);
      const midY = clamp(carrier.top + attackSign * ahead * 0.4, 5, 95);
      // Set-piece Phase 0 — the ball's own target no longer gets a private
      // 6-94/5-95 safety clamp here; dispatchBallTarget's out-of-bounds
      // detector owns that boundary now, so a heavy touch near the line
      // while jinking away from a defender can genuinely put it out
      // instead of always being silently rescued back onto the pitch.
      // Bug fix — first cut of this widened only the BALL's clamp and left
      // the carrier's own tx/ty at 6-94/5-95; empirically that alone still
      // produced zero touchline exits across a full half in testing,
      // because midX is itself derived from carrier.left, and every pin's
      // shape-driven position is already bounded to roughly 4-96 upstream
      // (stretchLaneX) — a jink of a few units off an already-safe center
      // essentially never reaches the true edge. During an active dribble
      // specifically (a deliberate, contested forward touch, not routine
      // off-ball shape) the carrier's own target may now approach the real
      // touchline much more closely — a winger already out wide taking a
      // heavy touch under pressure can genuinely run/put it out. Derived
      // straight from carrier.left, NOT from midX above (which is itself
      // still clamped to 6-94 for the visual path-bulge control point) —
      // routing it through that clamped value was the reason the first cut
      // still produced zero exits.
      const rawNx = carrier.left + jink * 0.65 + (rng() - 0.5) * 1.4;
      const rawNy = carrier.top + attackSign * ahead;
      const nx = clamp(rawNx, 1, 99);
      const ny = clamp(rawNy, 2, 98);

      carrier._pathCtrl = { left: midX, top: midY, from: matchMinute, until: matchMinute + 0.45 };
      carrier.tx = nx;
      carrier.ty = ny;
      carrier.lockUntil = matchMinute + 0.9;
      ballAttached = true;
      const dur = 0.65;
      dispatchBallTarget(rawNx, rawNy + attackSign * -0.5, dur, true, null, carrier.side);
      actionTimer = dur + 0.12 + spellIdlePause() * 0.35;

      if (won) {
        carrier._dribbleStreak = streak + 1;
        // Engine fix — get the faster maxJump/easing treatment applyPinMotion
        // already gives running pins, so beating a marked defender resolves
        // as a visible burst rather than the same drift-speed everything
        // else moves at.
        carrier._running = true;
        pushMatchEvent("dribble_won", carrier.side, {
          player: carrier.player,
          player_short: carrier.short,
          detail: threat ? `past ${threat.pin.short}` : "past the press",
          distance: Math.round(pitchDistM({ left: carrier.left, top: carrier.top }, { left: nx, top: ny }) * 10) / 10,
        });
        say(`${carrier.short} dribbles past ${threat?.pin.short || "the press"}`, 1.4);
        ballFlight = { outcome: "dribble_won" };
        if (threat) {
          triggerDefensiveBreachReactions(threat.pin);
          // Phase 3 consequence: defender stepped out and got beaten, exposing their zone
          // Track which defensive archetype lost the duel to inform shape updates
          const threatArchetype = computeDefensiveArchetype(threat.pin);
          if (defCommitment > 0.5) {
            // High commitment defender was beaten — they stepped out
            if (threat.pin.role === "DM" || threat.pin.role === "CM") {
              // Central midfield zone now exposed
              if (!defensiveShapeExposure) defensiveShapeExposure = {};
              if (!defensiveShapeExposure[oppOf(carrier.side)]) defensiveShapeExposure[oppOf(carrier.side)] = { central: 0, wide: 0 };
              defensiveShapeExposure[oppOf(carrier.side)].central = Math.min(1.0, defensiveShapeExposure[oppOf(carrier.side)].central + 0.3);
            } else if (threat.pin.role === "FB") {
              // Wide zone now exposed
              if (!defensiveShapeExposure) defensiveShapeExposure = {};
              if (!defensiveShapeExposure[oppOf(carrier.side)]) defensiveShapeExposure[oppOf(carrier.side)] = { central: 0, wide: 0 };
              defensiveShapeExposure[oppOf(carrier.side)].wide = Math.min(1.0, defensiveShapeExposure[oppOf(carrier.side)].wide + 0.3);
            }
          }
        }
      } else {
        // Bug fix — "attacker is far from the defender but commentary says
        // stopped": a 30-unit blind fallback (almost a third of the pitch)
        // let a defender who was nowhere near the real challenge get named
        // as the one who "stopped" the carrier, with the ball warping to
        // wherever they happened to be standing. Shrunk to a distance a
        // defender could plausibly have actually closed down in real time.
        // The pinsOf(...)[3] fallback stays purely as a non-null safety net
        // for the foul-quality math just below (opp.stats.* is dereferenced
        // unconditionally) — in normal play a defender within 10 units
        // almost always exists, so it essentially never fires.
        const opp = threat?.pin || nearestOpponent(carrier, 10)?.pin || pinsOf(oppOf(carrier.side))[3];
        // Engine addition — fouls. A defender "winning" this duel wasn't
        // necessarily a clean tackle; some fraction is a foul instead, more
        // likely in a dangerous last-man situation (attacker already in the
        // box). No per-player discipline data exists in the current stat
        // set (dribbles90/tackles90/etc. have nothing foul-related directly),
        // so foul-proneness is derived from the defender's own tackle/
        // interception quality instead: a defender who doesn't win duels
        // cleanly resorts to fouling more often. Normalized against a
        // realistic elite ceiling (no true percentile-vs-full-player-pool
        // lookup exists client-side — this approximates one). Even an
        // elite defender still fouls sometimes, just at a floor rate, not
        // zero. Simplified restart: the fouled player takes it themselves
        // at their own spot (reusing giveBall, same as every other
        // turnover-style restart in this file) rather than a full dead-ball
        // set-piece sequence.
        const duelQuality = clamp(
          (opp.stats.tackles90 / 3.5) * 0.7 + (opp.stats.interceptions90 / 2.5) * 0.3,
          0,
          1
        );
        // Secondary signal from real card history -- duelQuality (tackles90/
        // interceptions90-derived) stays the primary driver per the original
        // design; this only sharpens it for a defender whose actual
        // disciplinary record runs worse than their tackling numbers alone
        // would predict. Bounded well below duelQuality's own swing.
        const cardNudge = clamp((opp.stats.yellow_cards90 || 0) * 0.06 + (opp.stats.red_cards90 || 0) * 0.1, 0, 0.04);

        // Tactical foul consideration: increase foul probability based on danger level
        // Never commit tactical fouls in penalty box — penalty risk too high
        const inBox = inPenaltyBox(carrier);

        // Clear run (isolation): count how many other defenders are nearby
        const nearDefenders = pinsOf(oppOf(carrier.side)).filter(
          d => d.role !== "GK" && dist(d, carrier) < 14
        ).length;
        const isClear = nearDefenders <= 1; // Isolated or 1-on-1

        // Proximity to goal: closer to goal = more dangerous
        const oppGoalTop = attackGoalTop(carrier.side);
        const distToGoal = Math.abs(carrier.top - oppGoalTop);
        const dangerProximity = clamp(1 - distToGoal / 25, 0, 1); // Max danger within 25 units of goal

        // Tactical motivation: trailing team more willing to foul
        const scoreOf = (s) => (s === "home" ? homeScore : awayScore);
        const scoreDiff = scoreOf(oppOf(opp.side)) - scoreOf(opp.side); // Positive = defending team trailing
        const isTrailing = scoreDiff > 0;

        // Bug fix — real user report: fouls/cards/free kicks read as
        // extremely rare across a full match, "teams are not fighting for
        // the ball and fighting for winning." This is the ONLY foul source
        // in the whole engine (there's no separate foul chance on a tackle
        // outside a dribble duel), so it was carrying way less weight than
        // real football's actual foul rate demands. Raised both the base
        // rate and the tactical/cynical-foul bonus — a team fighting to
        // stay in the game should be noticeably more willing to give away a
        // cheap free kick to stop a dangerous break, not just occasionally.
        const tacticalFoulBoost = !inBox && ((isClear && dangerProximity > 0.3 && isTrailing) ? 0.16 :
                                             (isClear && dangerProximity > 0.5) ? 0.1 : 0);

        const foulP = (0.32 - duelQuality * 0.16) + (inPenaltyBox(carrier) ? 0.12 : 0) + cardNudge + tacticalFoulBoost;
        if (opp && rng() < foulP) {
          pushMatchEvent("foul", opp.side, {
            player: opp.player,
            player_short: opp.short,
            against: carrier.player,
            detail: `on ${carrier.short}`,
          });
          say(`Foul! ${opp.short} on ${carrier.short}`, 1.3);
          // Bad-foul (yellow card) tier — IFAB Law 12's careless/reckless/
          // excessive-force split: most fouls are merely careless (free
          // kick only, no card); a reckless one earns a caution; excessive
          // force (send-off) is explicitly out of scope for now. Reuses
          // duelQuality — a poorer defender's fouls skew more reckless, not
          // just more frequent. Gate: no second yellow yet (send-off/
          // 10-v-11 isn't built) — a player already on a caution this match
          // just can't pick up another one for the moment.
          const recklessCardNudge = clamp(
            (opp.stats.yellow_cards90 || 0) * 0.1 + (opp.stats.red_cards90 || 0) * 0.2,
            0,
            0.05
          );
          const recklessP = 0.35 - duelQuality * 0.25 + recklessCardNudge;
          if ((opp._yellowCards || 0) < 1 && rng() < recklessP) {
            opp._yellowCards = (opp._yellowCards || 0) + 1;
            pushMatchEvent("yellow_card", opp.side, {
              player: opp.player,
              player_short: opp.short,
              against: carrier.player,
              detail: `caution on ${carrier.short}`,
            });
            say(`Yellow card — ${opp.short}`, 1.4);
          }
          // Engine addition — dangerous-restart branching. A foul inside the
          // box is a penalty. Everywhere else, Set-piece Phase 2 splits the
          // restart into the four zones from the spec (direct-shooting-
          // range / wide-attacking / deep-midfield / indirect), each with
          // its own allowed actions instead of the old binary "near box or
          // nothing" split.
          if (inPenaltyBox(carrier)) {
            resolveInPlayPenalty(carrier.side);
            return;
          }
          const fkZone = classifyFreeKickZone(carrier);
          if (fkZone === "direct") {
            resolveDangerousFreeKick(carrier.side, carrier);
            return;
          }
          if (fkZone === "wide") {
            resolveWideFreeKick(carrier.side, carrier);
            return;
          }
          if (fkZone === "deep") {
            resolveMidfieldFreeKick(carrier.side, carrier);
            return;
          }
          fkStats.indirectRestarts++;
          pushMatchEvent("free_kick", carrier.side, {
            player: carrier.player,
            player_short: carrier.short,
            detail: "indirect free kick",
          });
          clearLastPasser();
          spell = null;
          giveBall(carrier, `${carrier.short} takes the free kick`);
          actionTimer = 0.6 + spellIdlePause() * 0.3;
          return;
        }
        pushMatchEvent("dribble_lost", carrier.side, {
          player: carrier.player,
          player_short: carrier.short,
          by: opp?.player,
          detail: opp ? `stopped by ${opp.short}` : "loses possession",
          distance: Math.round(pitchDistM({ left: carrier.left, top: carrier.top }, { left: nx, top: ny }) * 10) / 10,
        });
        say(opp ? `${opp.short} stops ${carrier.short}` : `${carrier.short} loses it`, 1.4);
        // Ball ends at the point of the challenge — path decided now.
        // Bug fix — same class as driveIntoBox: land near the carrier
        // (where the tackle actually happens), not warped across to
        // wherever opp was standing, and give opp a real corrective
        // close-down so the pin actually arrives there.
        if (opp) {
          ballAttached = false;
          const stopAngle = Math.atan2(opp.top - carrier.top, opp.left - carrier.left);
          const closeDist = clamp(dist(carrier, opp) * 0.3, 1, 3.5);
          const landLeft = clamp(carrier.left + Math.cos(stopAngle) * closeDist, 2, 98);
          const landTop = clamp(carrier.top + Math.sin(stopAngle) * closeDist, 2, 98);
          const arc = passArcFor(ball.left, ball.top, landLeft, landTop, "pass");
          setBallTarget(landLeft, landTop, Math.min(dur, arc.dur), false, arc.ctrl);
          opp.tx = landLeft;
          opp.ty = landTop;
          opp._running = true;
          opp.lockUntil = matchMinute + arc.dur + 0.3;
          actionTimer = arc.dur + 0.15;
        }
        ballFlight = {
          outcome: "dribble_lost",
          interceptor: opp,
          comment: opp ? `${opp.short} collects` : null,
        };
      }
    }

    function doCarry(carrier) {
      if (pendingDecisionSnapshot && pendingDecisionSnapshot.carrierId === carrier.id) {
        logDecisionOutcome("carry", {});
      }
      // Was unconditionally safe even with a defender right next to the
      // carrier — a free, guaranteed advance regardless of pressure, while
      // doDribble (the only contestable forward action) only fires on a
      // separate dice roll. Give a nearby defender a real, if modest, chance
      // to close a carry down instead of always standing there doing nothing.
      // Engine fix — same scrambling window as driveIntoBox: a defender
      // triggerDefensiveBreachReactions just sent recovering hasn't
      // physically arrived yet, so widen the engagement gate briefly rather
      // than let the recovery run always be one tick too late to count.
      const scrambling = (breachRecoveryUntil[oppOf(carrier.side)] || 0) > matchMinute;
      // Engine fix — player orientation: a carrier still turning from a
      // back-to-goal reception is a genuine opening for the defence, same
      // spirit as the scrambling window above.
      const backToGoal = (carrier._backToGoalUntil || 0) > matchMinute;
      const engageRadius = scrambling || backToGoal ? 13 : 9;
      const threat = nearestOpponent(carrier, engageRadius);
      // Engine rebuild Phase 1 — also gate on the real pressure field, not
      // just the single nearest defender, so a converging 2v1 (neither
      // defender alone inside the old 8.5-unit cutoff) still counts as real
      // pressure instead of being invisible to this check.
      const fieldPressure = pressureAt(carrier.left, carrier.top, carrier.side);
      const engageGate = scrambling || backToGoal ? 12.5 : 8.5;
      const pressureGate = scrambling || backToGoal ? 0.15 : 0.35;
      if ((threat && threat.d < engageGate) || fieldPressure > pressureGate || scrambling || backToGoal) {
        const resist = sideResist(carrier.side);
        const def = sideDefend(oppOf(carrier.side));
        const closeMul = threat ? clamp(1.2 - threat.d / engageRadius, 0.55, 1.2) : 0.7;
        const dispossessP =
          (0.05 +
            def * 0.1 +
            (threat ? threat.pin.stats.tackles90 * 0.05 : 0) -
            resist * 0.08 -
            carrier.stats.dribbles90 * 0.03 +
            fieldPressure * 0.09 +
            // Generic ball-security baseline (see doPass's pIntercept for
            // the passer-side equivalent) -- sloppier real-match carriers
            // lose the ball more even before live pressure is applied.
            (carrier.stats.possession_lost90 || 0) * 0.0015 +
            (scrambling ? 0.07 : 0) +
            (backToGoal ? 0.06 : 0) +
            (rng() - 0.5) * 0.04) *
          closeMul;
        if (rng() < clamp(dispossessP, 0.03, 0.26)) {
          // threat, or (when fieldPressure alone triggered the gate) the
          // nearest opponent within the pressure radius — always non-null.
          const opp = threat?.pin || nearestOpponent(carrier, 14)?.pin;
          pushMatchEvent("dribble_lost", carrier.side, {
            player: carrier.player,
            player_short: carrier.short,
            by: opp.player,
            detail: `dispossessed by ${opp.short}`,
          });
          say(`${opp.short} dispossesses ${carrier.short}`, 1.3);
          ballAttached = false;
          const arc = passArcFor(carrier.left, carrier.top, opp.left, opp.top, "pass");
          const dur = clamp(arc.dur, 0.2, 0.4);
          setBallTarget(opp.left, opp.top, dur, false, arc.ctrl);
          actionTimer = dur + 0.2;
          ballFlight = { outcome: "dribble_lost", interceptor: opp, comment: `${opp.short} closes it down` };
          return;
        }
        if (threat && threat.d < 8.5) triggerDefensiveBreachReactions(threat.pin);
      }
      const attackSign = carrier.side === "home" ? -1 : 1;
      const push = 2.2 + rng() * 2.4 + carrier.stats.dribbles90 * 0.35;
      const jink = (rng() < 0.55 ? 1 : -1) * (1.6 + rng() * 2.6);
      const midX = clamp(carrier.left + jink, 8, 92);
      const midY = clamp(carrier.top + attackSign * push * 0.38, 5, 95);
      // Set-piece Phase 0 — same fix as doDribble: derive the ball's own
      // target straight from carrier.left (NOT the pre-clamped midX above,
      // still used only for the visual path-bulge control point), and
      // clamp it wide (1-99/2-98) instead of the old 8-92/5-95 — routing
      // through the clamped value was empirically why the first cut
      // produced zero real exits across a full half of testing.
      const rawNx = carrier.left + jink * 0.72 + (rng() - 0.5) * 1.2;
      const rawNy = carrier.top + attackSign * push;
      const nx = clamp(rawNx, 1, 99);
      const ny = clamp(rawNy, 2, 98);
      carrier._pathCtrl = { left: midX, top: midY, from: matchMinute, until: matchMinute + 0.4 };
      carrier.tx = nx;
      carrier.ty = ny;
      carrier.lockUntil = matchMinute + 0.75;
      ballAttached = true;
      dispatchBallTarget(rawNx, rawNy + attackSign * -0.8, 0.7, true, null, carrier.side);
      actionTimer = 0.55 + rng() * 0.25 + spellIdlePause() * 0.5;
      if (commentaryHold <= 0) say(`${carrier.short} drives forward`, 1.0);
    }

    /**
     * Average rating_percentile (server-computed, see web/tournament.py)
     * across a side's finishing-relevant pins (ST/AM/W -- the roles this
     * feeds into via drawFinishingForm/organicWillScore). 0.5 is the
     * neutral "no signal" value the server already falls back to for a
     * player it couldn't rank, so a side with no real rating data anywhere
     * averages out to exactly 0.5 here too -- no special-casing needed for
     * "if absent, behave as before".
     */
    function sideFormReliability(side) {
      const pins = pinsOf(side).filter((p) => p.role === "ST" || p.role === "AM" || p.role === "W");
      if (!pins.length) return 0.5;
      return pins.reduce((s, p) => s + (p.stats.rating_percentile ?? 0.5), 0) / pins.length;
    }

    /**
     * Skewed day-form draw for one side, biased by that side's finishing unit.
     * Baseline (fin≈0.55): P(cold)≈0.08, P(hot)≈0.12, P(normal)≈0.80.
     * High finishing → more hot / fewer cold (+ slight normal mean lift);
     * low finishing → more cold / fewer hot. Elite still mostly normal days.
     */
    function drawFinishingForm(side) {
      const fin = sideFinishing(side);
      // bias ∈ [-0.45, 0.45]: fin 0→−0.45, 0.55→0, 1→+0.45
      const bias = clamp((fin - 0.55) * 1.0, -0.45, 0.45);
      let pCold = clamp(0.08 - bias * 0.12, 0.02, 0.18);
      let pHot = clamp(0.12 + bias * 0.16, 0.04, 0.28);
      // rating -- a genuinely reliable finishing line (high real rating
      // percentile) plays more consistently: narrows the hot/cold draw
      // toward "normal" rather than shifting the mean. A below-average or
      // unranked (0.5 neutral) line leaves the spread exactly as before --
      // per the user's own framing, this only ever narrows, never widens.
      const varianceMul = clamp(1 - Math.max(0, sideFormReliability(side) - 0.5) * 0.6, 0.7, 1);
      pCold *= varianceMul;
      pHot *= varianceMul;
      const u = rng();
      if (u < pCold) {
        // Cold day — was 0.32-0.72 (drawn once, held for the whole match).
        // Real production data: a team creating 2+ xG and scoring 0 while
        // the opponent overperforms wildly, in a single 90-minute lock-in
        // with no chance to turn it around, feels like a coin flip rather
        // than controlled variance. Narrowed the swing.
        return clamp(0.55 + rng() * 0.25, 0.52, 0.8);
      }
      if (u < pCold + pHot) {
        // Hot day — was 1.3-1.95. Narrowed to match.
        return clamp(1.2 + rng() * 0.35, 1.18, 1.55);
      }
      // Normal — triangular-ish around 1.0 (+ mild finishing mean shift)
      const noise = (rng() + rng() + rng() - 1.5) * 0.2;
      const meanShift = bias * 0.06;
      return clamp(1.0 + meanShift + noise, 0.82, 1.18);
    }

    function redrawFinishingForm() {
      finishingForm = { home: drawFinishingForm("home"), away: drawFinishingForm("away") };
    }

    function organicWillScore(carrier, chanceType) {
      const atk = sideAttack(carrier.side);
      const def = sideDefend(oppOf(carrier.side));
      const drought = matchMinute - lastGoalMinute;
      const droughtBoost = drought > 28 ? 0.05 : drought > 18 ? 0.025 : 0;
      const totalGoals = homeScore + awayScore;
      // Reverted the harsher blowout rubber-band from earlier — dampening
      // conversion by total goals scored punishes a genuinely elite finisher
      // for their team's *other* goals, regardless of their own numbers. The
      // right lever against blowouts is upstream (fewer/harder big chances
      // via spellChanceP/boxOccupationReady/progressionUrgency), not this.
      const fatigue = totalGoals >= 5 ? 0.55 : totalGoals >= 4 ? 0.7 : 1;
      const boxed = inPenaltyBox(carrier);
      const box = boxed ? 0.1 : nearPenaltyBox(carrier) ? 0.03 : -0.04;
      const skillGap = atk - def;
      const urg = progressionUrgency(spell);
      const ad = attackDefendDelta(carrier.side);
      const form = clamp(finishingForm[carrier.side] ?? 1, 0.2, 1.95);
      const roleFin = isAttackFinisher(carrier);
      const fq = finisherQuality(carrier);
      const goals = carrier.stats.goals90 || 0;
      // Elite ST/W/AM (high xG/shots) convert much harder; old 0.3×xg + hi=0.40
      // compressed Kane (~0.89 xG) down to average-ST conversion.
      // Fox-in-box overperformers (goals90 >> xg90, e.g. Higuaín 1.1 vs 0.75)
      // were still converted at their xG floor — credit clinical finishing directly.
      const xgW = boxed ? (roleFin ? 0.42 : 0.3) : roleFin ? 0.18 : 0.12;
      const shW = roleFin ? 0.035 : 0.02;
      const goalsW = roleFin ? (boxed ? 0.09 : 0.04) : 0;
      const clinical = roleFin
        ? clamp((goals - carrier.stats.xg90) * (boxed ? 0.28 : 0.12), 0, boxed ? 0.14 : 0.06)
        : 0;
      const eliteBoost = roleFin ? clamp((fq - 0.42) * 0.24, 0, 0.2) : 0;
      const roleBox = roleFin && boxed ? 0.045 : 0;
      // Real profligacy rate on big chances specifically -- independent of
      // the live anti-drought missBoost below (which only reacts to THIS
      // match's own streak), a real wasteful-in-front-of-goal history nudges
      // the baseline down a little. Archetype-aware: half-chance scorers get
      // boosted on non-big-chances, clinical finishers penalized less on big chances.
      const profligacy = roleFin ? profligacyByArchetype(carrier, chanceType) : 0;
      const p =
        (0.05 +
          carrier.stats.xg90 * xgW +
          carrier.stats.shots90 * shW +
          goals * goalsW +
          clinical -
          profligacy +
          atk * 0.16 -
          def * 0.14 +
          skillGap * 0.14 +
          box +
          roleBox +
          eliteBoost +
          droughtBoost +
          Math.max(0, ad) * 0.06 +
          (boxed ? urg * 0.025 : 0) +
          (rng() - 0.5) * 0.1) *
        fatigue *
        form;
      // Floors drop on cold days; ceilings rise with finisher quality for ST/W/AM.
      // Reverted the ceiling cut from earlier — capping how well elite
      // finishers convert is the wrong lever (it suppresses a genuinely good
      // Neymar/Messi-calibre finisher's numbers directly). The fix belongs
      // upstream, in how rarely a big/quality chance gets created at all.
      const lo = boxed ? (form < 0.7 ? 0.012 : 0.04) : form < 0.7 ? 0.006 : 0.015;
      const hiElite = roleFin ? clamp((fq - 0.38) * 0.42, 0, 0.24) : 0;
      const hi = boxed
        ? clamp((0.4 + hiElite) * Math.min(form, 1.55), 0.32, roleFin ? 0.72 : 0.58)
        : clamp((0.15 + hiElite * 0.4) * Math.min(form, 1.55), 0.11, roleFin ? 0.34 : 0.26);
      // Engine fix — anti-drought (big chances only, see sideBigMissStreak
      // declaration). Raises odds on the NEXT big chance after a miss; never
      // guarantees one (missBoost and the final probability are both capped),
      // so a genuinely bad night is still possible, just rarer than a flat
      // i.i.d. coin flip would produce for a proven clinical finisher/attack.
      let missBoost = 0;
      if (chanceType === "big_chance") {
        if (isClinicalFinisher(carrier)) {
          missBoost += clamp((carrier._bigMissStreak || 0) * 0.22, 0, 0.35);
        }
        if (sideForwardLineClinical(carrier.side)) {
          missBoost += clamp(Math.max(0, (sideBigMissStreak[carrier.side] || 0) - 1) * 0.14, 0, 0.24);
        }
        missBoost = clamp(missBoost, 0, 0.4);
      }
      const boostedHi = clamp(hi + missBoost, hi, 0.85);
      // Knockout-only home push (finishing) — see KNOCKOUT_HOME_PUSH.
      const homePush = isKnockout && !isFinalRound && carrier.side === "home" ? 1 + KNOCKOUT_HOME_PUSH : 1;
      return rng() < clamp((p + missBoost) * homePush, lo, boostedHi);
    }

    /**
     * Dangerous-restart defensive shape. The defending side regroups deep
     * toward their own goal for a penalty or a near-box direct free kick,
     * instead of holding normal formation shape — same tx/ty+lockUntil
     * repositioning pattern flushDeferredRestarts already uses for kickoffs,
     * just applied to one side only and pulled much deeper (own defensive
     * third rather than own half).
     */
    function retreatDefensiveShape(defSide, excludeIds) {
      const exclude = excludeIds || new Set();
      for (const pin of pinsOf(defSide)) {
        if (pin.role === "GK" || exclude.has(pin.id)) continue;
        const depthWant = Math.min(pin.baseDepth, 0.2);
        const pct = toPitchPct(pin.side, pin.baseX, depthWant);
        pin.tx = pct.left;
        pin.ty = pct.top;
        pin.lockUntil = matchMinute + 1.4;
        pin._running = true;
      }
    }

    /**
     * Lines up the nearest defenders between the ball and goal for a direct
     * free kick — no prior "wall" concept existed in the engine. Returns the
     * set of pin ids placed in the wall so retreatDefensiveShape can leave
     * them where they stand instead of also pulling them back deep.
     */
    function formDefensiveWall(defSide, ballLeft, ballTop, goalLeft, goalTop, count) {
      const dx = goalLeft - ballLeft;
      const dy = goalTop - ballTop;
      const lineDist = Math.hypot(dx, dy) || 1;
      const frac = clamp(9 / lineDist, 0.12, 0.4);
      const wx = ballLeft + dx * frac;
      const wy = ballTop + dy * frac;
      const px = -dy / lineDist;
      const py = dx / lineDist;
      const spacing = 2.6;
      const ballPoint = { left: ballLeft, top: ballTop };
      const wallPins = pinsOf(defSide)
        .filter((p) => p.role !== "GK")
        .sort((a, b) => dist(a, ballPoint) - dist(b, ballPoint))
        .slice(0, count);
      const start = -(wallPins.length - 1) / 2;
      wallPins.forEach((pin, i) => {
        const off = (start + i) * spacing;
        pin.tx = clamp(wx + px * off, 2, 98);
        pin.ty = clamp(wy + py * off, 2, 98);
        pin.lockUntil = matchMinute + 1.6;
        pin._running = true;
      });
      return new Set(wallPins.map((p) => p.id));
    }

    /**
     * A foul inside the box is a penalty. Reuses the shootout's own
     * pickPenaltyOrder/penConvertChance (pure functions of the taker) rather
     * than the shootout's sudden-death sequencing machinery, which doesn't
     * apply to a single in-play kick. Binary scored/saved outcome, matching
     * how shootout penalties already work — no extra save/wide nuance added.
     */
    function resolveInPlayPenalty(fouledSide) {
      const defSide = oppOf(fouledSide);
      const taker = pickPenaltyOrder(fouledSide)[0];
      if (!taker) return;
      const spot = toPitchPct(fouledSide, 0.5, 0.895);
      snapPinPose(taker, spot.left, spot.top);
      taker.lockUntil = matchMinute + 1.6;
      retreatDefensiveShape(defSide, new Set());
      const keeper = gkOf(defSide);
      const keeperSpot = toPitchPct(defSide, 0.5, 0.02);
      keeper.tx = keeperSpot.left;
      keeper.ty = keeperSpot.top;
      keeper.lockUntil = matchMinute + 1.6;

      clearLastPasser();
      spell = null;
      pushMatchEvent("penalty", fouledSide, {
        player: taker.player,
        player_short: taker.short,
        detail: "penalty awarded",
        xg: 0.76,
      });
      say(`Penalty! ${taker.short} steps up`, 1.5);
      updateHud();
      maybeBroadcast(true);
      giveBall(taker, null);
      ballAttached = false;
      phase = "FINISH";
      if (spell) {
        spell.chanceDone = true;
        spell.stage = "FINISH";
      }
      liveXg[fouledSide] += 0.76;
      matchLog.counts[fouledSide].xg = Math.round(liveXg[fouledSide] * 1000) / 1000;

      const scored = rng() < penConvertChance(taker, keeper);
      if (scored) {
        const netLeft = attackGoalLeft();
        const netTop = attackGoalTop(fouledSide);
        const arc = passArcFor(spot.left, spot.top, netLeft, netTop, "through");
        const dur = clamp(arc.dur * 0.85, 0.3, 0.5);
        setBallTarget(netLeft, netTop, dur, false, arc.ctrl);
        actionTimer = dur + 0.4;
        ballFlight = { outcome: "goal", side: fouledSide };
      } else {
        const arc = passArcFor(spot.left, spot.top, keeper.left, keeper.top, "through");
        const dur = clamp(arc.dur * 0.85, 0.3, 0.5);
        setBallTarget(keeper.left, keeper.top, dur, false, arc.ctrl);
        actionTimer = dur + 0.4;
        ballFlight = { outcome: "save", interceptor: keeper, against: fouledSide, shooterShort: taker.short };
      }
    }

    /**
     * A foul just outside the box is a direct free kick in a genuinely
     * dangerous position — the taker either shoots direct (gated by a wall,
     * via doShot's wallBoost) or floats it into the box (reusing
     * crossBoxTarget/cueBoxRuns, the same delivery mechanic wide open play
     * already uses). How central the spot is drives the shoot-vs-cross
     * split: central and close reads much more like "have a direct pop at
     * goal," wide reads much more like "put it in the mixer."
     */
    /**
     * Set-piece Phase 2 — no dedicated free-kick stat exists anywhere in
     * the data, so this is a documented proxy rather than an invented
     * rating: shot placement (shots_on_target90/shots90 — a real accuracy
     * signal, distinct from shot VOLUME or xg90's shot-selection/movement
     * signal), blended with the same delivery-technique terms
     * cornerTakerRank already uses (long_ball_pct, xa90). This is
     * deliberately NOT dominated by xg90 — a pure poacher with great
     * finishing but no dead-ball technique shouldn't automatically inherit
     * free-kick duties (pickPenaltyOrder, which IS xg90-driven, stays the
     * penalty taker order — a different skill, finishing under pressure
     * from a fixed spot rather than technique from a static ball at range).
     *
     * Fix (real-player validation, set-piece Phase 3 follow-up) — the
     * accuracy term used to gate on `shots90 > 0.3`, which every default/
     * statless player also clears via mergeStats' ROLE_GENERIC fallback,
     * so it never actually detected real data. Combined with
     * shots_on_target90's own fallback (Math.max(0.4, shots90*0.4)), a
     * player with NO real shooting data at all landed a ~1.0 accuracy
     * ratio — higher than real Kimmich (0.33) or Hazard (0.57) ever
     * scored with genuine numbers, so a default CB kept out-ranking both
     * for free-kick duty. Missing data must read as neutral (0.5), never
     * as elite ability — gate on hasShotData (set in mergeStats from the
     * RAW input, before any fallback), not on the post-fallback value.
     */
    function fkTechniqueProxy(p) {
      if (!p || !p.stats) return 0;
      const st = p.stats;
      const accuracy = st.hasShotData ? clamp((st.shots_on_target90 || 0) / Math.max(st.shots90, 0.3), 0, 1) : 0.5;
      const delivery = clamp((st.long_ball_pct || 0) / 100, 0, 1);
      const vision = clamp((st.xa90 || 0) / 0.6, 0, 1);
      return accuracy * 0.4 + delivery * 0.35 + vision * 0.25;
    }

    /**
     * Set-piece Phase 2 — zone classifier driving the four free-kick
     * categories from the spec. Reuses the SAME fromPitchPct/inPenaltyBox/
     * nearPenaltyBox geometry the penalty/dangerous-FK split already used,
     * just extended with two more bands instead of a hardcoded
     * `if x > N` check.
     */
    function classifyFreeKickZone(carrier) {
      if (nearPenaltyBox(carrier)) return "direct";
      const rel = fromPitchPct(carrier.side, carrier.left, carrier.top);
      if (rel.depth >= 0.62 && (rel.x < 0.22 || rel.x > 0.78)) return "wide";
      if (rel.depth >= 0.42) return "deep";
      return "indirect";
    }

    /**
     * Set-piece Phase 2 — taker selection per zone. Direct/wide need real
     * dead-ball technique (fkTechniqueProxy); deep/indirect are just a
     * restart, so the best available passer takes it rather than a
     * "specialist" moment nobody in real football treats as one.
     */
    function pickFreeKickTaker(side, zone) {
      const pins = pinsOf(side).filter((p) => p.role !== "GK");
      if (!pins.length) return null;
      if (zone === "deep" || zone === "indirect") {
        return [...pins].sort((a, b) => (b.stats.pass_pct || 0) - (a.stats.pass_pct || 0))[0];
      }
      const rank = (p) => fkTechniqueProxy(p) + (p.role === "AM" ? 0.05 : p.role === "W" ? 0.03 : 0);
      return [...pins].sort((a, b) => rank(b) - rank(a))[0];
    }

    function resolveDangerousFreeKick(fouledSide, carrier) {
      const defSide = oppOf(fouledSide);
      const spotLeft = carrier.left;
      const spotTop = carrier.top;
      const rel = fromPitchPct(fouledSide, spotLeft, spotTop);
      const centrality = 1 - clamp(Math.abs(rel.x - 0.5) * 2.4, 0, 1);
      const taker = pickFreeKickTaker(fouledSide, "direct");
      if (!taker) return;
      snapPinPose(taker, spotLeft, spotTop);
      taker.lockUntil = matchMinute + 1.5;

      const goalTop = attackGoalTop(fouledSide);
      const wallCount = clamp(Math.round(2 + centrality * 2), 2, 4);
      const wallIds = formDefensiveWall(defSide, spotLeft, spotTop, 50, goalTop, wallCount);
      retreatDefensiveShape(defSide, wallIds);

      clearLastPasser();
      spell = null;
      pushMatchEvent("free_kick", fouledSide, {
        player: taker.player,
        player_short: taker.short,
        detail: "direct free kick",
      });
      giveBall(taker, `Free kick — ${taker.short} stands over it`);
      freeKickUntil = matchMinute + 2; // Block dribbling until free kick is taken

      const shootP = clamp(0.12 + centrality * 0.55 + fkTechniqueProxy(taker) * 0.35, 0.08, 0.78);
      if (rng() < shootP) {
        fkStats.directShots++;
        doShot(taker, false, { wallBoost: 0.14 + centrality * 0.08 });
      } else {
        fkStats.directCrosses++;
        const mode = rng() < 0.5 ? "near" : "far";
        cueBoxRuns(taker, mode);
        const target = crossBoxTarget(taker, mode);
        say(`${taker.short} whips one into the box`, 1.35);
        doPass(taker, target, "cross");
      }
      freeKickUntil = 0; // Clear free kick flag after kick is taken
    }

    /**
     * Set-piece Phase 2 — wide-attacking free kicks. No genuine shooting
     * angle exists out near the touchline, so this only delivers a cross —
     * reusing the SAME cueBoxRuns/cueDefensiveBoxCover/crossBoxTarget/
     * doPass machinery resolveCorner uses, not a new delivery system.
     */
    function resolveWideFreeKick(fouledSide, carrier) {
      const defSide = oppOf(fouledSide);
      const taker = pickFreeKickTaker(fouledSide, "wide");
      if (!taker) return;
      snapPinPose(taker, carrier.left, carrier.top);
      taker.lockUntil = matchMinute + 1.4;

      cueDefensiveBoxCover(defSide);
      const keeper = gkOf(defSide);
      if (keeper) {
        const keeperSpot = toPitchPct(defSide, 0.5, 0.02);
        keeper.tx = keeperSpot.left;
        keeper.ty = keeperSpot.top;
        keeper.lockUntil = matchMinute + 1.4;
      }

      const boxMode = rng() < 0.5 ? "near" : "far";
      cueBoxRuns(taker, boxMode);

      clearLastPasser();
      spell = null;
      pushMatchEvent("free_kick", fouledSide, {
        player: taker.player,
        player_short: taker.short,
        detail: "wide free kick",
      });
      say(`Free kick — ${taker.short} to deliver`, 1.3);
      giveBall(taker, null);
      freeKickUntil = matchMinute + 2;

      const target = crossBoxTarget(taker, boxMode);
      say(`${taker.short} whips it in`, 1.35);
      doPass(taker, target, "cross");
      freeKickUntil = 0;
      fkStats.wideCrosses++;
    }

    /**
     * Set-piece Phase 2 — deep-midfield free kicks. Real football: a foul
     * in the middle third almost never gets a "delivery" — it's a quick
     * restart so the team can rebuild the attack through the normal engine
     * loop. No wall, no box runs, no cross — deliberately the simplest of
     * the four categories, matching the spec's "different allowed
     * actions" per zone. The fouled player retakes it themselves (the real
     * default), just now logged and instrumented instead of being an
     * invisible fallback.
     */
    function resolveMidfieldFreeKick(fouledSide, carrier) {
      clearLastPasser();
      spell = null;
      pushMatchEvent("free_kick", fouledSide, {
        player: carrier.player,
        player_short: carrier.short,
        detail: "midfield free kick",
      });
      say(`Free kick — ${carrier.short}`, 1.2);
      giveBall(carrier, null);
      actionTimer = 0.6 + spellIdlePause() * 0.3;
      fkStats.midfieldRestarts++;
    }

    /**
     * Set-piece Phase 1 — throw-ins. Deliberately simple per spec: nearest
     * eligible outfield player to the exit point (excludes GK; "nearest
     * sensible teammate," not literally nearest-any-player).
     */
    function pickThrowInTaker(side, left, top) {
      const spot = { left, top };
      const pins = pinsOf(side).filter((p) => p.role !== "GK");
      let best = null;
      let bestD = Infinity;
      for (const p of pins) {
        const d = dist(p, spot);
        if (d < bestD) {
          bestD = d;
          best = p;
        }
      }
      return best;
    }

    /**
     * Set-piece Phase 1 — throw-ins. Kept deliberately simple: position the
     * taker at the exit point, pick a receiver by reusing the SAME
     * scoreDynamicReceiver/findBestArrivingReceiver machinery evaluateArrivals
     * already relies on elsewhere (no third receiver-scoring system), then
     * hand off to the normal doPass pipeline for the actual reception — a
     * real, non-guaranteed contest via the exact same interception
     * mechanics every other pass already uses, not an invented probability
     * layer bolted on beside it.
     */
    function resolveThrowIn(side, left, top) {
      const taker = pickThrowInTaker(side, left, top);
      if (!taker) return;
      const pct = { left: clamp(left, 1, 99), top: clamp(top, 2, 98) };
      snapPinPose(taker, pct.left, pct.top);
      taker.lockUntil = matchMinute + 1.0;

      clearLastPasser();
      spell = null;
      pushMatchEvent("throw_in", side, {
        player: taker.player,
        player_short: taker.short,
        detail: "throw-in",
      });
      oobStats.throwInsGenerated++;

      const depth = possessionDepth(taker);
      const stage = depth < 0.35 ? "BUILD_UP" : depth < 0.68 ? "PROGRESSING" : "FINAL_THIRD";
      const receiver = findBestArrivingReceiver(taker, stage, depth, 0.12);
      if (!receiver) {
        say(`${taker.short} takes the throw`, 1.2);
        giveBall(taker, null);
        return;
      }
      say(`${taker.short} throws to ${receiver.short}`, 1.2);
      doPass(taker, receiver, "pass");
    }

    /**
     * Minimal goal kick — not a named phase in the spec, but the necessary
     * counterpart to a corner: the SAME byline-exit-outside-goal-mouth
     * detection needs a resolution either way depending on who touched it
     * last. Kept as simple as throw-ins on purpose — keeper collects and
     * restarts; the real reception contest happens through the normal
     * pass pipeline once play resumes, not invented here.
     */
    function resolveGoalKick(side) {
      const keeper = gkOf(side);
      if (!keeper) return;
      const spot = toPitchPct(side, 0.5, 0.06);
      snapPinPose(keeper, spot.left, spot.top);
      keeper.lockUntil = matchMinute + 1.0;
      clearLastPasser();
      spell = null;
      pushMatchEvent("goal_kick", side, {
        player: keeper.player,
        player_short: keeper.short,
        detail: "goal kick",
      });
      say(`Goal kick — ${keeper.short}`, 1.2);
      giveBall(keeper, null);
    }

    /**
     * Engine addition — corners. Best crosser on the side, not the
     * penalty-taking order (a different skill: dead-ball delivery from
     * width, not finishing under pressure from the spot). Weighted toward
     * W/FB, who are the real-football default corner takers, but any
     * outfield player with genuine delivery numbers can win it.
     */
    function cornerTakerRank(p) {
      return (
        (p.stats.long_ball_pct || 0) * 0.02 +
        (p.stats.key_passes90 || 0) * 0.45 +
        (p.stats.xa90 || 0) * 1.4 +
        (p.stats.long_balls90 || 0) * 0.12 +
        (p.role === "W" ? 0.4 : p.role === "FB" ? 0.32 : p.role === "AM" ? 0.15 : p.role === "CM" ? 0.08 : 0)
      );
    }

    function pickCornerTaker(side) {
      const pins = pinsOf(side).filter((p) => p.role !== "GK");
      return [...pins].sort((a, b) => cornerTakerRank(b) - cornerTakerRank(a))[0] || null;
    }

    /**
     * Set-piece Phase 3 fix — short-corner receiver. The original check
     * (`dist(p, taker) < 14` evaluated AFTER taker.left/top was already
     * snapped to the corner-flag spot) was really asking "is a teammate
     * already standing at the corner flag right now?" — which is
     * essentially never true in normal open play, an area nobody idles
     * in. That produced 0/10 `hadReceiver` in the diagnostic sample
     * regardless of taker quality or aerial matchup.
     *
     * Real corners always have a plausible short option: the near-side
     * FB/W (or a supporting CM) shuffles across as the corner is being
     * organized, specifically BECAUSE a short corner is a live option —
     * not because they happened to already be loitering by the flag.
     * Model that intended routine explicitly: pick the nearest ELIGIBLE
     * attacking outfield player by ROLE (same flank preferred), not by
     * literal pre-kick position. Distance still matters — a CM stranded
     * on the opposite touchline isn't a real short-corner option — but
     * the cutoff (45, roughly half the pitch) exists only to rule out
     * genuinely pathological cases, not to gate the common case the way
     * the old 14-unit "already there" check did.
     */
    function pickShortCornerReceiver(taker, attackingSide, flagSpot) {
      const eligible = pinsOf(attackingSide).filter(
        (p) => p.id !== taker.id && (p.role === "FB" || p.role === "W" || p.role === "CM")
      );
      if (!eligible.length) return null;
      const fromLeft = flagSpot.left < 50;
      eligible.sort((a, b) => {
        const aSameFlank = a.left < 50 === fromLeft ? 0 : 1;
        const bSameFlank = b.left < 50 === fromLeft ? 0 : 1;
        if (aSameFlank !== bSameFlank) return aSameFlank - bSameFlank;
        return dist(a, flagSpot) - dist(b, flagSpot);
      });
      const best = eligible[0];
      return dist(best, flagSpot) < 45 ? best : null;
    }

    /**
     * Set-piece Phase 3 — corner delivery selection. Previously a flat
     * rng() < 0.55 near/far coin flip with no signal behind it. Real
     * signals only: aerialEdge (the SAME sideAerial/strikerAerialThreat
     * attack-vs-defence matchup term decideWideFinalThird already uses to
     * pick cross vs cutback for regular open-play crosses), the taker's
     * own delivery quality (cornerTakerRank), and match state (chasing a
     * goal nudges toward more direct/central delivery). Short corners are
     * only weighted in when genuinely justified — a weak taker AND a
     * defence that heavily wins the aerial matchup — not a fixed rate.
     */
    function pickCornerDeliveryMode(taker, attackingSide, defSide) {
      const aerialAtk = strikerAerialThreat(attackingSide);
      const aerialDef = sideAerial(defSide);
      const aerialEdge = aerialAtk - aerialDef;
      const takerQuality = clamp(cornerTakerRank(taker) / 2.2, 0, 1);
      const scoreOf = (s) => (s === "home" ? homeScore : awayScore);
      const chasing =
        scoreOf(defSide) > scoreOf(attackingSide) ? clamp((scoreOf(defSide) - scoreOf(attackingSide)) * 0.15, 0, 0.3) : 0;
      // shortCornerCandidate stage: does the team even HAVE a role-eligible
      // outfield player besides the taker? (near-universal yes)
      const hadCandidate = pinsOf(attackingSide).some(
        (p) => p.id !== taker.id && (p.role === "FB" || p.role === "W" || p.role === "CM")
      );
      // nearby receiver exists stage: of that candidate pool, is the
      // nearest one within a realistic short-corner passing distance?
      const shortMate = pickShortCornerReceiver(taker, attackingSide, taker);
      // Diagnostic only (no gate here uses this yet) -- is the nearest
      // short option actually available, or would they be closed down
      // immediately? Answers "no_space" separately from "no_receiver".
      const shortMateMarked = shortMate ? Boolean(nearestOpponent(shortMate, 5)) : false;

      const options = [
        { id: "near", w: Math.max(0.05, 0.85 + Math.max(0, -aerialEdge) * 0.4 + takerQuality * 0.3) },
        { id: "far", w: Math.max(0.05, 0.7 + Math.max(0, aerialEdge) * 0.55 + takerQuality * 0.25) },
        { id: "central", w: Math.max(0.05, 0.35 + aerialAtk * 0.9 + chasing) },
        { id: "edge", w: Math.max(0.05, 0.25 + takerQuality * 0.4) },
      ];
      // taker quality stage
      const weakTaker = takerQuality < 0.35;
      // aerial matchup stage
      const aerialDisadvantage = aerialEdge < -0.28;
      const gateOpen = Boolean(shortMate) && (weakTaker || aerialDisadvantage);
      if (gateOpen) {
        options.push({
          id: "short",
          w: 0.3 + (0.35 - Math.min(0.35, takerQuality)) * 0.8 + Math.max(0, -aerialEdge) * 0.5,
        });
      }
      const picked = weightedPick(options);

      // Diagnostic instrumentation (Phase 3 follow-up) -- records the
      // short-corner gate's underlying candidate count and rejection
      // reasons BEFORE any tuning, per the explicit "instrument before
      // you tune" request. Five sequential stages: shortCornerCandidate
      // -> nearby receiver exists -> taker quality -> aerial matchup ->
      // short corner selected, kept distinct so the diagnostic stays
      // meaningful (not collapsed into one pass/fail count).
      shortCornerDiag.totalCorners++;
      if (hadCandidate) shortCornerDiag.hadCandidate++;
      if (shortMate) shortCornerDiag.hadReceiver++;
      if (shortMateMarked) shortCornerDiag.receiverMarked++;
      if (weakTaker) shortCornerDiag.weakTaker++;
      if (aerialDisadvantage) shortCornerDiag.aerialDisadvantage++;
      if (gateOpen) shortCornerDiag.gateOpen++;
      if (picked === "short") shortCornerDiag.selected++;
      if (shortCornerDiag.samples.length >= 200) shortCornerDiag.samples.shift();
      shortCornerDiag.samples.push({
        takerQuality: Math.round(takerQuality * 1000) / 1000,
        aerialEdge: Math.round(aerialEdge * 1000) / 1000,
        hadCandidate,
        hadReceiver: Boolean(shortMate),
        receiverMarked: shortMateMarked,
        gateOpen,
        picked,
      });

      return picked;
    }

    /**
     * Set-piece Phase 3 — who wins the loose ball after a corner clearance
     * isn't clean. Stat-driven contest (duels_won_pct + tackles90 for the
     * defending side, duels_won_pct + xg90 as a predatory-instinct proxy
     * for the attacking side — same family of signals doDribble/doShot
     * already use for physical duels), not a fixed 50/50. Defence keeps a
     * realistic edge (more bodies back, facing the ball) rather than an
     * even contest.
     */
    function resolveCornerSecondBall(attackingSide, defSide, clearer) {
      const spot = { left: clearer.left, top: clearer.top };
      const attackers = pinsOf(attackingSide).filter((p) => p.role !== "GK" && dist(p, spot) < 20);
      const defenders = pinsOf(defSide).filter((p) => p.role !== "GK" && dist(p, spot) < 20);
      const atkScore = (p) => (p.stats.duels_won_pct || 50) * 0.01 + (p.stats.xg90 || 0) * 0.4 - dist(p, spot) * 0.05;
      const defScore = (p) =>
        (p.stats.duels_won_pct || 50) * 0.01 + (p.stats.tackles90 || 0) * 0.05 - dist(p, spot) * 0.05;
      const bestAtk = [...attackers].sort((a, b) => atkScore(b) - atkScore(a))[0];
      const bestDef = [...defenders].sort((a, b) => defScore(b) - defScore(a))[0];
      const atkPower = bestAtk ? 0.4 + (bestAtk.stats.duels_won_pct || 50) * 0.006 : 0.25;
      const defPower = bestDef
        ? 0.55 + (bestDef.stats.tackles90 || 0) * 0.05 + (bestDef.stats.duels_won_pct || 50) * 0.006
        : 0.4;
      const winP = clamp(atkPower / (atkPower + defPower), 0.15, 0.62);
      if (bestAtk && rng() < winP) return { winnerSide: attackingSide, pin: bestAtk };
      return { winnerSide: defSide, pin: bestDef || clearer };
    }

    /**
     * Engine addition — corners. The ball going behind the byline off a
     * defender previously always just handed possession back cleanly (see
     * the save/blocked/wide outcome handlers) -- no corner ever existed in
     * the engine. Mirrors resolveDangerousFreeKick's structure: position
     * the taker, set up both boxes, deliver a cross.
     */
    function resolveCorner(attackingSide) {
      if (!attackingSide) return;
      const defSide = oppOf(attackingSide);
      const taker = pickCornerTaker(attackingSide);
      if (!taker) return;

      // Which flag: whichever side of goal the ball actually went out on,
      // read in the attacking side's own frame (x<0.5 = left flag).
      const ballRel = fromPitchPct(attackingSide, ball.left, ball.top);
      const cornerX = ballRel.x < 0.5 ? 0 : 1;
      const flagSpot = toPitchPct(attackingSide, cornerX, 0.99);
      snapPinPose(taker, flagSpot.left, flagSpot.top);
      taker.lockUntil = matchMinute + 1.6;

      cueDefensiveBoxCover(defSide);
      const keeper = gkOf(defSide);
      if (keeper) {
        const keeperSpot = toPitchPct(defSide, 0.5, 0.02);
        keeper.tx = keeperSpot.left;
        keeper.ty = keeperSpot.top;
        keeper.lockUntil = matchMinute + 1.6;
      }

      cornerStats.cornersWon++;
      const boxMode = pickCornerDeliveryMode(taker, attackingSide, defSide);
      cornerStats.delivery[boxMode] = (cornerStats.delivery[boxMode] || 0) + 1;

      clearLastPasser();
      spell = null;
      pushMatchEvent("corner", attackingSide, {
        player: taker.player,
        player_short: taker.short,
        detail: `corner awarded (${boxMode})`,
      });

      if (boxMode === "short") {
        const shortMate = pickShortCornerReceiver(taker, attackingSide, taker);
        if (!shortMate) {
          // No genuine short option nearby -- fall back to a standard
          // delivery instead of forcing a short corner with nobody there.
          resolveCornerDelivery(taker, attackingSide, defSide, "near");
          return;
        }
        say(`Short corner — ${taker.short} to ${shortMate.short}`, 1.3);
        giveBall(taker, null);
        freeKickUntil = matchMinute + 1.5;
        doPass(taker, shortMate, "pass");
        freeKickUntil = 0;
        return;
      }

      resolveCornerDelivery(taker, attackingSide, defSide, boxMode);
    }

    /**
     * Set-piece Phase 3 — the actual delivery once a non-short mode is
     * picked. Split out of resolveCorner so the short-corner branch can
     * bail into a standard delivery without duplicating the CB-join/cross
     * logic. Tags the flight via pendingCornerContext so the shared
     * doPass flight-resolution code can run the second-ball contest.
     */
    function resolveCornerDelivery(taker, attackingSide, defSide, boxMode) {
      cueBoxRuns(taker, boxMode);
      // A real detail: a CB joins the attack for a corner, unlike any
      // other cross -- cueBoxRuns deliberately doesn't include CB since
      // that would be wrong for open-play crosses. Only one, not both:
      // real teams still keep a spare man back for the counter.
      const joiningCb = pinsOf(attackingSide)
        .filter((p) => p.role === "CB")
        .sort(() => rng() - 0.5)[0];
      if (joiningCb) {
        const cbTarget = toPitchPct(attackingSide, 0.5 + (rng() - 0.5) * 0.22, 0.87);
        joiningCb.tx = cbTarget.left;
        joiningCb.ty = cbTarget.top;
        joiningCb.lockUntil = matchMinute + 1.3;
        joiningCb._running = true;
      }

      say(`Corner! ${taker.short} to the flag`, 1.3);
      giveBall(taker, null);
      freeKickUntil = matchMinute + 2;

      const target = crossBoxTarget(taker, boxMode);
      say(`${taker.short} swings it in`, 1.35);
      pendingCornerContext = { attackingSide, defSide, until: matchMinute + 2.5 };
      doPass(taker, target, "cross");
      freeKickUntil = 0;
    }

    /**
     * Real per-keeper quality, replacing the team-level sideGoalkeeper()
     * composite for save probability specifically (that composite is still
     * used everywhere else it was, e.g. approxXgTarget's pacing anchor --
     * this is scoped to the actual save mechanic only). Blends shot-stopping
     * volume (saves90), the standard post-shot-xG-minus-goals-conceded skill
     * signal (goals_prevented90, can be negative for an underperforming
     * keeper), and game-level reliability (clean_sheet_pct). Normalized
     * against the same reference ceilings formation_fit.py's STAT_CAPS
     * already uses for these exact fields (saves90: 4.5, goals_prevented90:
     * 0.8), for consistency even though that's a separate Python file.
     */
    function gkPinQuality(keeper) {
      if (!keeper || !keeper.stats) return 0.5;
      const st = keeper.stats;
      const savesTerm = clamp((st.saves90 || 0) / 4.5, 0, 1);
      const gpTerm = clamp(((st.goals_prevented90 || 0) + 0.4) / 1.2, 0, 1);
      const csTerm = clamp((st.clean_sheet_pct || 0) / 100, 0, 1);
      return clamp(savesTerm * 0.35 + gpTerm * 0.45 + csTerm * 0.2, 0.15, 0.95);
    }

    function doShot(carrier, mustScore, opts) {
      if (ballFlight) return;
      if (pendingDecisionSnapshot && pendingDecisionSnapshot.carrierId === carrier.id) {
        logDecisionOutcome("shot", {});
      }
      const wallBoost = (opts && opts.wallBoost) || 0;
      // Engine rebuild — physics realism (Problem 9). A shot previously had
      // zero wind-up: the ball started flying the instant the decision was
      // made, no plant-foot/backswing motion at all. Give the shooter's own
      // sprite a brief, bounded plant (bulge toward a control point and
      // back to the same spot, via the same _pathCtrl bezier mechanism
      // doDribble/doCarry already use) right at the shot's start. This is
      // purely cosmetic on the shooter — it doesn't delay the scoring
      // decision or ball flight, and everyone else keeps moving/reacting
      // exactly as before ("never freeze everyone").
      carrier._pathCtrl = {
        left: clamp(carrier.left + (rng() - 0.5) * 1.5, 2, 98),
        top: clamp(carrier.top + (carrier.side === "home" ? -1 : 1) * 1.2, 2, 98),
        from: matchMinute,
        until: matchMinute + 0.12,
      };
      carrier.tx = carrier.left;
      carrier.ty = carrier.top;
      // Hold the lock through the plant window so updateTeamShape doesn't
      // overwrite tx/ty with a fresh target before the bulge completes.
      carrier.lockUntil = Math.max(carrier.lockUntil || 0, matchMinute + 0.12);
      const keeper = gkOf(oppOf(carrier.side));
      // Engine fix — reverted the instant "address the shot" snapPinPose
      // that used to live here. Per the user's own report: it could
      // teleport the keeper across goal right as the shot arrived,
      // occasionally landing him on the WRONG side of a shot he'd
      // otherwise have been shaded toward -- a real goal conceded to a
      // keeper who'd just been snapped the wrong way. A keeper shouldn't
      // snap to address a shot at all; he should already be gradually
      // shaded toward the danger by the time it's struck. That continuous
      // shading lives in updateTeamShape's GK branch (gkDanger-scaled
      // lerp toward relBall.x) -- this function no longer fights it by
      // locking the keeper's target the instant a shot fires.
      const atk = sideAttack(carrier.side);
      const def = sideDefend(oppOf(carrier.side));
      // Engine addition — the outfield defender closing this shooter down
      // previously had zero individual say in save/block probability, only
      // the keeper and the diffuse team `def` composite did. tackles90 +
      // duels_won_pct (not interceptions -- this is a physical, in-the-
      // moment contest, same family as doDribble's defender term) reused
      // as blockerCandidate below so there's only one nearestOpponent call.
      const closingDefender = nearestOpponent(carrier, 9)?.pin;
      // DM/CM covering back into the box is a recovery-run/positioning contest,
      // not a settled physical duel -- reuse the existing archetype coverage
      // model (coverageRadius + mobility) rather than the flat tackles90 term
      // alone. Zero for CB/FB (this only fires on role check), so their path
      // is unchanged.
      const closingCoverage =
        closingDefender && (closingDefender.role === "DM" || closingDefender.role === "CM")
          ? defensiveCoverage(closingDefender, carrier.left, carrier.top) * 0.025
          : 0;
      const closingQuality = closingDefender
        ? closingDefender.stats.tackles90 * 0.025 + Math.max(0, closingDefender.stats.duels_won_pct - 50) * 0.002 + closingCoverage
        : 0;
      ballAttached = false;
      phase = "FINISH";
      if (spell) {
        spell.chanceDone = true;
        spell.stage = "FINISH";
        spell.awaitingShot = false;
        spell.awaitingBoxShot = false;
      }
      const boxed = inPenaltyBox(carrier);
      // Bug fix — labeling only checked `boxed`, so a legitimate, correctly-
      // gated near-box effort (edge of the D — a real, fair shooting
      // position, not a bug) still got tagged "long_shot"/"from range" in
      // both the event log and commentary, same as a genuine speculative
      // effort from distance. Only the latter should read as "from range."
      const nearBox = !boxed && nearPenaltyBox(carrier);
      const chanceType =
        boxed &&
        boxOccupationReady(carrier.side) &&
        (possessionDepth(carrier) > 0.82 || carrier.stats.xg90 > 0.32)
          ? "big_chance"
          : "shot";
      // Without box occupation, force a low-xG look (estimateChanceXg hard-caps >0.20)
      const chanceXg = estimateChanceXg(carrier, chanceType);
      liveXg[carrier.side] += chanceXg;
      matchLog.counts[carrier.side].xg = Math.round(liveXg[carrier.side] * 1000) / 1000;
      pushMatchEvent(chanceType, carrier.side, {
        player: carrier.player,
        player_short: carrier.short,
        detail: boxed || nearBox ? "shot" : "long_shot",
        xg: Math.round(chanceXg * 1000) / 1000,
        in_box: boxed,
      });
      // Engine addition — key passes / big chances created. lastPasser is
      // already tracked (assist attribution reuses it too); a pass that
      // put the shooter in THIS position, right before THIS shot, is
      // exactly what "key pass" means regardless of whether the shot goes
      // in. big_chance_created is the same signal, scoped to genuinely
      // clear-cut chances only.
      if (lastPasser && lastPasser.toId === carrier.id && lastPasser.player !== carrier.player) {
        pushMatchEvent("key_pass", carrier.side, {
          player: lastPasser.player,
          player_short: lastPasser.player_short,
          detail: chanceType === "big_chance" ? "big_chance_created" : "key_pass",
          big_chance: chanceType === "big_chance",
        });
      }
      const xgLabel = chanceXg.toFixed(2);
      say(
        chanceType === "big_chance"
          ? `Big chance! ${carrier.short} shoots — xG ${xgLabel}`
          : boxed || nearBox
            ? `${carrier.short} shoots — xG ${xgLabel}`
            : `${carrier.short} from range — xG ${xgLabel}`,
        1.55
      );
      updateHud();
      maybeBroadcast(true);

      // Decide goal / save / wide BEFORE the ball flies, then aim the path to match
      let willScore = false;
      if (replayScore) {
        const due = mustScore || nextScheduledGoal(carrier.side, matchMinute);
        const late = forceLateGoals(matchMinute);
        willScore =
          Boolean(due && due.side === carrier.side) ||
          Boolean(late && late.side === carrier.side && remainingGoals(carrier.side) > 0 && matchMinute >= late.minute - 1);
      } else {
        willScore = Boolean(mustScore) || organicWillScore(carrier, chanceType);
      }
      if (willScore && !replayScore && !mustScore) {
        const form = clamp(finishingForm[carrier.side] ?? 1, 0.2, 1.95);
        // Hot finishing → fewer denied shots; cold → more saves/misses after an on-target look
        const saveScale = clamp(1.05 - (form - 1) * 0.55, 0.52, 1.7);
        const roleFin = isAttackFinisher(carrier);
        const fq = finisherQuality(carrier);
        // Engine rebuild — a shot hit under real pressure (someone closing
        // the shooter down as they strike) is more likely scuffed/rushed and
        // therefore easier to save, not just a function of team/keeper
        // quality. Modest weight since a good finisher can still finish
        // well under pressure.
        const shotPressure = pressureAt(carrier.left, carrier.top, carrier.side);
        const saveP =
          (0.1 +
            def * 0.22 -
            atk * 0.08 -
            carrier.stats.xg90 * (boxed ? (roleFin ? 0.2 : 0.14) : 0.05) -
            carrier.stats.shots90 * (roleFin ? 0.018 : 0.012) -
            (roleFin ? fq * 0.06 : 0) +
            (boxed ? 0 : 0.12) +
            gkPinQuality(keeper) * 0.14 +
            closingQuality +
            shotPressure * 0.06 +
            (rng() - 0.5) * 0.06) *
          saveScale;
        if (rng() < clamp(saveP, 0.04, roleFin && boxed && fq >= 0.7 ? 0.42 : 0.55)) willScore = false;
      }

      // Engine fix — anti-drought bookkeeping (organic path only; replay/forced
      // scorelines don't run this). Tracks consecutive missed big chances so
      // the NEXT one gets the boost applied inside organicWillScore.
      if (chanceType === "big_chance" && !replayScore && !mustScore) {
        if (willScore) {
          carrier._bigMissStreak = 0;
          sideBigMissStreak[carrier.side] = 0;
        } else {
          carrier._bigMissStreak = (carrier._bigMissStreak || 0) + 1;
          sideBigMissStreak[carrier.side] = (sideBigMissStreak[carrier.side] || 0) + 1;
          pushMatchEvent("big_chance_missed", carrier.side, {
            player: carrier.player,
            player_short: carrier.short,
            detail: "big chance missed",
          });
        }
      }

      if (willScore) {
        // Finish into the net (between posts), not short of the line / outside the frame
        const netLeft = attackGoalLeft();
        const netTop = attackGoalTop(carrier.side);
        const goalArc = passArcFor(carrier.left, carrier.top, netLeft, netTop, "through");
        // Flatten loft so the ball reads as entering the mouth, not floating mid-air
        const midL = (carrier.left + netLeft) * 0.5;
        const midT = (carrier.top + netTop) * 0.5;
        const flatCtrl = {
          left: lerp(midL, goalArc.ctrl.left, 0.35),
          top: lerp(midT, goalArc.ctrl.top, 0.35),
        };
        const dur = clamp(goalArc.dur * 0.95, 0.35, 0.55);
        setBallTarget(netLeft, netTop, dur, false, flatCtrl);
        actionTimer = dur + 0.35;
        ballFlight = { outcome: "goal", side: carrier.side };
      } else {
        // Was mislabeled: this used to route every non-scoring shot to the keeper
        // ("save") or wide, with no distinct "blocked by an outfield defender"
        // outcome at all — a real, sizeable share of shots never reach the keeper.
        // Engine rebuild — blockP had zero positional signal at all: a shot
        // could get "blocked" with no defender anywhere near it. A block
        // requires someone genuinely in the lane, so gate/scale it on real
        // pressure at the shooter (pressureAt) instead of team quality alone.
        const shotPressure = pressureAt(carrier.left, carrier.top, carrier.side);
        // Reuses closingDefender (resolved once, above) so the actual
        // candidate blocker's own shot-blocking rate (blocks90) and
        // duel-winning ability can factor into the probability, not just
        // team-level `def`.
        const blockerCandidate =
          closingDefender ||
          pinsOf(oppOf(carrier.side)).find((p) => p.role === "CB") ||
          keeper;
        const blockP =
          0.1 +
          def * 0.18 -
          atk * 0.06 -
          carrier.stats.xg90 * 0.05 +
          (boxed ? 0 : 0.06) +
          shotPressure * 0.16 +
          (blockerCandidate?.stats?.blocks90 || 0) * 0.03 +
          // Blocking is a reactive, physical action -- duels_won_pct fits
          // the same family as blocks90, not interceptions (a passing-lane
          // read, the wrong skill for smothering a shot).
          Math.max(0, (blockerCandidate?.stats?.duels_won_pct || 50) - 50) * 0.004 +
          wallBoost +
          (rng() - 0.5) * 0.06;
        if (rng() < clamp(blockP, 0.03, shotPressure > 0.3 || wallBoost > 0 ? 0.62 : 0.22)) {
          const blocker = blockerCandidate;
          const blockArc = passArcFor(carrier.left, carrier.top, blocker.left, blocker.top, "through");
          setBallTarget(blocker.left, blocker.top, clamp(blockArc.dur * 0.7, 0.2, 0.38), false, blockArc.ctrl);
          actionTimer = clamp(blockArc.dur * 0.7, 0.2, 0.38) + 0.3;
          ballFlight = {
            outcome: "blocked",
            interceptor: blocker,
            against: carrier.side,
            shooterShort: carrier.short,
          };
        } else if (rng() < clamp(0.58 + atk * 0.15, 0.35, 0.78)) {
          // Reaches the keeper — saved.
          const saveArc = passArcFor(carrier.left, carrier.top, keeper.left, keeper.top, "through");
          setBallTarget(keeper.left, keeper.top, clamp(saveArc.dur * 0.9, 0.32, 0.5), false, saveArc.ctrl);
          actionTimer = 0.85;
          ballFlight = {
            outcome: "save",
            interceptor: keeper,
            against: carrier.side,
            shooterShort: carrier.short,
          };
        } else {
          const wideLeft = clamp(50 + (rng() - 0.5) * 28, 18, 82);
          const wideTop = carrier.side === "home" ? 2 : 98;
          const wideArc = passArcFor(carrier.left, carrier.top, wideLeft, wideTop, "through");
          setBallTarget(wideLeft, wideTop, clamp(wideArc.dur * 0.95, 0.35, 0.55), false, wideArc.ctrl);
          actionTimer = clamp(wideArc.dur * 0.95, 0.35, 0.55) + 0.35;
          const defPin = pinsOf(oppOf(carrier.side)).find((p) => p.role === "CB") || keeper;
          ballFlight = {
            outcome: "wide",
            interceptor: defPin,
            against: carrier.side,
            shooterShort: carrier.short,
          };
        }
      }
    }

    const pendingTimers = [];
    function setTimeoutProxy(fn, ms) {
      const id = setTimeout(fn, ms);
      pendingTimers.push(id);
      return id;
    }
    function schedule(fn, ms) {
      return setTimeoutProxy(fn, ms);
    }
    function clearTimers() {
      pendingTimers.forEach(clearTimeout);
      pendingTimers.length = 0;
    }

    /**
     * Diagnostic-only (see decisionDiagRoles above) — the possession-entry
     * state for whichever tracked-role carrier is about to decide. Reuses
     * canPlayForward/throughBallLegal/scorePassingOption exactly as the
     * real decision logic does — this is deliberately NOT a second scoring
     * system, just a read of the same signals the engine itself already
     * computes, taken before we know what the engine will actually pick.
     */
    function possessionSnapshot(carrier, cheap) {
      const stage = spell?.stage || phase;
      const depth = possessionDepth(carrier);
      const nearest = nearestOpponent(carrier, 15);
      const mates = teammates(carrier);
      const forwardEligible = mates.filter((m) => canPlayForward(carrier, m, stage, depth));
      const throughEligible = forwardEligible.filter((m) => throughBallLegal(carrier, m));
      const wideOptions = mates.filter((m) => m.role === "W" && Math.abs(m.left - carrier.left) > 10);
      const boxOptions = mates.filter((m) => possessionDepth(m) >= 0.82);
      let bestScore = -Infinity;
      let bestMate = null;
      // The scorePassingOption pass is the expensive part (one full score
      // per forward-eligible teammate) -- skip it for the all-players/
      // all-matches audit, where the "was a better option available"
      // question isn't what's being asked; keep it for the role-scoped
      // CM/AM diagnostic, which specifically needs it.
      if (!cheap) {
        for (const m of forwardEligible) {
          const s = scorePassingOption(carrier, m);
          if (s > bestScore) {
            bestScore = s;
            bestMate = m;
          }
        }
      }
      return {
        role: carrier.role,
        side: carrier.side,
        depth: Math.round(depth * 100) / 100,
        stage,
        nearestOppDist: nearest ? Math.round(nearest.d * 10) / 10 : null,
        forwardCount: forwardEligible.length,
        forwardRoles: forwardEligible.map((m) => m.role),
        throughCount: throughEligible.length,
        wideCount: wideOptions.length,
        boxCount: boxOptions.length,
        bestOptionScore: Number.isFinite(bestScore) ? Math.round(bestScore * 100) / 100 : null,
        bestOptionRole: bestMate ? bestMate.role : null,
        bestOptionId: bestMate ? bestMate.id : null,
        carrierId: carrier.id,
        minute: Math.round(matchMinute * 10) / 10,
      };
    }

    /**
     * Diagnostic-only — called from doPass/doCarry/doDribble/doShot once
     * the real decision has resolved into an actual action, so it can pair
     * the possession-entry snapshot with what was chosen (and, for passes,
     * whether the chosen target's own scorePassingOption score matched the
     * best-available one captured in the snapshot). One-shot: cleared
     * immediately so a later action in the SAME tick by a different pin
     * can't be mislabeled.
     */
    function logDecisionOutcome(actionType, extra = {}) {
      const snap = pendingDecisionSnapshot;
      pendingDecisionSnapshot = null;
      if (!snap) return;
      if (decisionDiag.samples.length >= 600) decisionDiag.samples.shift();
      decisionDiag.samples.push({ ...snap, actionType, ...extra });
    }

    function decideAction() {
      const carrier = findCarrier();
      if (!carrier || finished || ballFlight) return;
      if (
        (decisionDiagAll || (decisionDiagRoles.size && decisionDiagRoles.has(carrier.role))) &&
        !pendingRestart &&
        !pendingKickoffCarrier &&
        !pendingClear &&
        !pendingSetPiece
      ) {
        pendingDecisionSnapshot = possessionSnapshot(carrier, decisionDiagAll);
      }
      // A goal/restart sequence is already locked in (ball walking back to the
      // centre, kickoff carrier not yet assigned) — actionTimer expires well
      // before this resolves, which let the scoring side grab another decision
      // (and even score again) before kickoff ever happened. Freeze decisions
      // until the restart actually completes.
      if (pendingRestart || pendingKickoffCarrier || pendingClear || pendingSetPiece) return;

      if (!spell || spell.side !== possession) beginSpell(possession, "spell");
      // Hierarchy: state → shape already applied in tickDecision → ball decision here
      syncPossessionState();
      if (spell) {
        spell.actions += 1;
        spell.patience = spell.actions;
      }

      if (pendingShot) {
        actionTimer = Math.max(actionTimer, 0.08);
        return;
      }

      if (spell && spell.awaitingBoxShot && spell.side === possession && !spell.chanceDone) {
        if (carrier.lockUntil > matchMinute) {
          actionTimer = Math.max(actionTimer, 0.15);
          return;
        }
        if (inPenaltyBox(carrier) || (nearPenaltyBox(carrier) && possessionDepth(carrier) >= 0.78)) {
          if (!boxOccupationReady(carrier.side) && countBoxAttackers(carrier.side) < 1) {
            spell.awaitingBoxShot = false;
            // Bug fix — "hot potato in the box" (part 2): this only gave
            // forward roles (forwardInFinalThird = ST/W) a real shot/dribble
            // look via forwardFinalThirdAction; a CM/AM/DM in this exact
            // same boxed/near-box position (already established by the
            // outer check above) got an unconditional backward pass with no
            // shot ever considered. Everyone finisher-eligible gets the same
            // real look here, not just ST/W.
            if (isAttackFinisher(carrier)) {
              forwardFinalThirdAction(carrier);
              return;
            }
            doPass(carrier, backPassTarget(carrier), "pass");
            dropPossessionState(1);
            return;
          }
          spell.awaitingBoxShot = false;
          spell.chanceDone = true;
          spell.stage = "FINISH";
          carrier._boxDriveDone = false;
          doShot(carrier, false);
          return;
        }
        if (!carrier._boxDriveDone && driveIntoBox(carrier)) return;
        spell.awaitingBoxShot = false;
        spell.chanceDone = true;
        carrier._boxDriveDone = false;
        // Bug fix — same class as the attemptSpellChance fixes above: this
        // point is only reached once we already know the carrier isn't
        // boxed/sufficiently near (the branch above returns otherwise), so
        // gate the recycle on his own proximity, not team box-readiness.
        if (!inPenaltyBox(carrier) && !nearPenaltyBox(carrier)) {
          if (forwardInFinalThird(carrier)) {
            forwardFinalThirdAction(carrier);
            return;
          }
          doPass(carrier, backPassTarget(carrier), "pass");
          dropPossessionState(1);
          return;
        }
        spell.stage = "FINISH";
        doShot(carrier, false);
        return;
      }

      if (replayScore) {
        const late = forceLateGoals(matchMinute);
        if (late && late.side === possession && phase !== "BUILD_UP") {
          const shooter = shooterTarget(carrier);
          if (shooter.id !== carrier.id) {
            doPass(carrier, shooter, "through");
            return;
          }
          doShot(carrier, true);
          return;
        }
        if (late && late.side !== possession && matchMinute >= late.minute) {
          const attacker = pinsOf(late.side).find((p) => p.role === "ST" || p.role === "AM" || p.role === "W");
          if (attacker) {
            spell = null;
            giveBall(attacker, `${attacker.short} breaks away`);
            actionTimer = 0.45;
            return;
          }
        }
        const dueGoal = nextScheduledGoal(possession, matchMinute);
        if (dueGoal && possessionDepth(carrier) > 0.5) {
          const shooter = shooterTarget(carrier);
          if (shooter.id !== carrier.id && possessionDepth(carrier) < 0.78) {
            doPass(carrier, shooter, "through");
            return;
          }
          doShot(shooter.id === carrier.id ? carrier : shooter, true);
          return;
        }
      }

      const st = carrier.stats;
      const fav = carrier.id === favoredId && carrier.favorUntil > matchMinute;
      const stage = spell?.stage || "PROGRESSING";
      const threat = nearestOpponent(carrier, 11);
      const depth = possessionDepth(carrier);

      // Bug fix — the spell-timeout resolution below ("you've had the ball
      // long enough, commit to a chance or lose it") used to be checked
      // AFTER evaluateArrivals's pass dispatch. Since evaluateArrivals
      // returns immediately whenever any teammate clears its low 0.15
      // score threshold, a genuinely open group of players (e.g. both
      // wing-backs plus both wingers plus a deep-lying mid) could keep
      // satisfying it indefinitely and the timeout never got a chance to
      // fire -- a small group would carousel possession for 10+ real
      // match-minutes near the box without ever being forced into a shot
      // or losing the ball. Check the timeout first so it always wins once
      // a spell has genuinely overstayed its welcome, regardless of how
      // open the next pass looks.
      if (spell && matchMinute >= spell.end && !spell.chanceDone) {
        if (spell.willAttemptChance || possessionDepth(carrier) > 0.45) {
          attemptSpellChance(carrier);
          return;
        }
        const create = sideCreate(carrier.side);
        if (rng() < 0.55 + create * 0.35) {
          attemptSpellChance(carrier);
          return;
        }
        doTurnover(carrier, "spell broken by the press");
        return;
      }

      // Phase 3: Organic arrival-based decision (early gate before pattern logic)
      // Check if there's a high-value arriving receiver; if so, pass to them immediately
      const arrivalDecision = evaluateArrivals(carrier, stage, depth);
      // Bug fix — this only ever acted on "pass"; evaluateArrivals's "shoot"
      // and "dribble" outcomes were computed and then silently discarded,
      // falling through to older decision logic that doesn't reliably cover
      // either case. That's the direct cause of isolated wingers never
      // attempting a dribble (canDribble fired internally but nothing
      // happened) and boxed finishers never getting a shot from this path.
      if (arrivalDecision.type === "shoot") {
        doShot(carrier, false);
        return;
      }
      if (arrivalDecision.type === "pass" && arrivalDecision.target) {
        // Bug fix — scoreDynamicReceiver never checked whether the target is
        // actually ahead of the carrier with a clear lane (throughBallLegal),
        // unlike every other through-ball dispatch in the file. Downgrade to
        // a normal pass when it isn't a real through-ball position instead of
        // mislabeling a routine pass as "slips it through" every tick.
        doPass(carrier, arrivalDecision.target, throughBallLegal(carrier, arrivalDecision.target) ? "through" : "pass");
        return;
      }
      if (arrivalDecision.type === "dribble") {
        doDribble(carrier);
        return;
      }

      if (!replayScore) {
        let pressMul = 0.34;
        if (
          spell?.willAttemptChance &&
          (stage === "CHANCE_CREATION" || stage === "FINISH" || matchMinute >= spell.end - 3)
        ) {
          pressMul = 0.1;
        } else if (stage === "BOX_OCCUPATION" && spell?.willAttemptChance) {
          pressMul = 0.18;
        } else if (stage === "FINAL_THIRD" && spell?.willAttemptChance) {
          pressMul = 0.24;
        } else if (stage === "PROGRESSING" && spell?.willAttemptChance) {
          pressMul = 0.26;
        }
        if (rng() < pressTurnoverChance(carrier) * pressMul) {
          doTurnover(carrier, "pressed into a mistake");
          return;
        }
      }

      if (threat && threat.d < 5.2 && rng() < 0.42) {
        if (forwardInFinalThird(carrier)) {
          forwardFinalThirdAction(carrier);
          actionTimer = Math.max(actionTimer, spellIdlePause());
          return;
        }
        if (carrier.role === "DM") {
          doPass(carrier, backPassTarget(carrier), "pass");
        } else {
          const conf = spell?.patternConfidence ?? 0;
          const pattern = spell?.pattern;
          // High confidence: stay on pattern channel under press
          if (conf > 55 && pattern && pattern !== "central") {
            const ch = teammates(carrier)
              .filter((m) => patternChannelsPrefer(pattern, m, carrier) > 1)
              .sort((a, b) => dist(carrier, a) - dist(carrier, b));
            if (ch[0]) {
              doPass(carrier, ch[0], "pass");
              actionTimer = Math.max(actionTimer, spellIdlePause());
              return;
            }
          }
          const links = linkedOptions(carrier);
          const cm = teammates(carrier).find((m) => m.role === "CM");
          doPass(carrier, links[0] || cm || backPassTarget(carrier), "pass");
        }
        actionTimer = Math.max(actionTimer, spellIdlePause());
        return;
      }

      if (
        (stage === "CHANCE_CREATION" || stage === "FINISH") &&
        spell &&
        !spell.chanceDone &&
        spell.willAttemptChance
      ) {
        attemptSpellChance(carrier);
        return;
      }

      if (
        spell &&
        !spell.chanceDone &&
        (stage === "FINAL_THIRD" || stage === "BOX_OCCUPATION" || stage === "PROGRESSING") &&
        possessionDepth(carrier) > 0.52
      ) {
        const create = sideCreate(carrier.side);
        const urg = progressionUrgency(spell);
        const ad = attackDefendDelta(carrier.side);
        const vol = possChanceVolumeMul(carrier.side);
        const supp = possessionSuppressionMul(carrier.side);
        const maestroBoost = isMaestroPin(carrier) ? 0.05 : 0;
        const creatorMod = creatorBehaviorModifiers(carrier);
        const probeP =
          ((stage === "BOX_OCCUPATION" ? 0.09 : stage === "FINAL_THIRD" ? 0.075 : 0.045) +
            create * 0.07 +
            carrier.stats.xa90 * 0.045 +
            (spell.willAttemptChance ? 0.03 : 0.014) +
            urg * 0.045 +
            Math.max(0, ad) * 0.06 +
            maestroBoost +
            creatorMod.spellProbeBoost) *
          vol *
          lerp(1, supp, 0.7);
        if (rng() < clamp(probeP, 0.03, 0.28)) {
          if (spell) spell.willAttemptChance = true;
          attemptSpellChance(carrier);
          return;
        }
      }

      // Engine addition — DM stat coefficient. Every other role's flat base
      // probabilities got a stat-scaled term at some point this session
      // (CM/AM via pickAttackPattern, W via wCut/wWing, CB via pressureAt,
      // ST/AM via organicWillScore); DM never did — its decision code was
      // all fixed-probability role gates, unlike its plentiful but purely
      // positional (not decision) role branches elsewhere. A defensively-
      // minded destroyer (high tackles90) plays it safer and recycles more
      // under pressure than a base flat rate assumes.
      const dmRecycleP =
        carrier.role === "DM" ? clamp(0.2 + (carrier.stats.tackles90 || 0) * 0.035, 0.16, 0.4) : 0.12;
      if (stage === "BOX_OCCUPATION" && rng() < dmRecycleP * clamp(1.1 - progressionUrgency(spell) * 0.55, 0.25, 1)) {
        if (commentaryHold <= 0) say(`${carrier.short} recycles possession`, 1.1);
        actionTimer = spellIdlePause();
        return;
      }

      if (carrier.role === "DM" && (stage === "BUILD_UP" || stage === "PROGRESSING")) {
        const cms = teammates(carrier).filter((m) => m.role === "CM");
        // A technically better passer (pass_pct) looks beyond the safe
        // nearest-CM default more often instead of always taking it.
        // Creator archetype modifies this: volume creators recycle more,
        // progressive creators look for forward CMs.
        const creatorMod = creatorBehaviorModifiers(carrier);
        const cmFunnelP = clamp(0.78 - ((carrier.stats.pass_pct || 75) - 75) * 0.006 + creatorMod.dmFunnelAdjust, 0.55, 0.88);
        if (cms.length && rng() < cmFunnelP) {
          cms.sort((a, b) => dist(carrier, a) - dist(carrier, b) + (rng() - 0.5) * 2);
          doPass(carrier, cms[0], "pass");
          actionTimer = Math.max(actionTimer, spellIdlePause());
          return;
        }
      }

      if (stage === "BUILD_UP") {
        if (isDefRole(carrier.role) && rng() < 0.02) {
          const longTo = longBallTarget(carrier);
          if (longTo) {
            doPass(carrier, longTo, "long");
            actionTimer = Math.max(actionTimer, spellIdlePause());
            return;
          }
        }
        if (isDefRole(carrier.role) && rng() < 0.7) {
          const cms = teammates(carrier).filter((m) => m.role === "CM");
          const dms = teammates(carrier).filter((m) => m.role === "DM");
          if (cms.length && rng() < 0.45) {
            doPass(carrier, cms[Math.floor(rng() * cms.length)], "pass");
            actionTimer = Math.max(actionTimer, spellIdlePause());
            return;
          }
          if (dms.length && rng() < 0.65) {
            doPass(carrier, dms[Math.floor(rng() * dms.length)], "pass");
            actionTimer = Math.max(actionTimer, spellIdlePause());
            return;
          }
        }
        if (
          !isDefRole(carrier.role) ||
          carrier.role === "FB" ||
          (carrier.role === "CB" && st.dribbles90 > 0.8)
        ) {
          const dribbleBuildP =
            0.08 +
            st.dribbles90 * 0.055 +
            (carrier.role === "W" || carrier.role === "AM" || carrier.role === "CM" ? 0.06 : 0) +
            (threat && threat.d < 9 ? 0.04 : 0);
          if (threat && threat.d < 9.5 && rng() < dribbleBuildP) {
            doDribble(carrier);
            return;
          }
          if (rng() < 0.12 + st.dribbles90 * 0.04 + (carrier.role === "CM" ? 0.06 : 0)) {
            doCarry(carrier);
            actionTimer = Math.max(actionTimer, spellIdlePause());
            return;
          }
        }
        if (!isDefRole(carrier.role) && possessionDepth(carrier) > 0.32 && rng() < 0.4) {
          if (executeAttackPattern(carrier, stage)) {
            actionTimer = Math.max(actionTimer, spellIdlePause());
            return;
          }
        }
        if (rng() < 0.28) {
          if (forwardInFinalThird(carrier)) forwardFinalThirdAction(carrier);
          else doPass(carrier, backPassTarget(carrier), "pass");
        } else if (rng() < 0.78) doPass(carrier, progressiveTarget(carrier), "pass");
        else doCarry(carrier);
        actionTimer = Math.max(actionTimer, spellIdlePause());
        return;
      }

      // PROGRESSING / FINAL_THIRD / BOX — pattern-driven after shape
      if (
        stage === "PROGRESSING" ||
        stage === "FINAL_THIRD" ||
        stage === "BOX_OCCUPATION" ||
        stage === "CHANCE_CREATION"
      ) {
        if (fav && rng() < 0.28) {
          doPass(carrier, pinById.get(favoredId) || progressiveTarget(carrier), "pass");
          actionTimer = Math.max(actionTimer, spellIdlePause());
          return;
        }
        const urg = progressionUrgency(spell);
        const ad = attackDefendDelta(carrier.side);
        const depthNow = possessionDepth(carrier);
        const earlyThrough = throughRunner(carrier, stage, depthNow);
        if (
          earlyThrough &&
          throughBallAttractive(carrier, earlyThrough) &&
          depthNow >= 0.5 &&
          urg >= 0.45 &&
          rng() < clamp(0.18 + urg * 0.14 + Math.max(0, ad) * 0.35 + carrier.stats.key_passes90 * 0.08, 0.1, 0.55)
        ) {
          doPass(carrier, earlyThrough, "through");
          actionTimer = Math.max(actionTimer, spellIdlePause());
          return;
        }
        if (isDefRole(carrier.role) && rng() < 0.02) {
          const longTo = longBallTarget(carrier);
          if (longTo) {
            doPass(carrier, longTo, "long");
            actionTimer = Math.max(actionTimer, spellIdlePause());
            return;
          }
        }
        if (executeAttackPattern(carrier, stage)) {
          actionTimer = Math.max(actionTimer, spellIdlePause());
          return;
        }
        doPass(carrier, progressiveTarget(carrier), "pass");
        actionTimer = Math.max(actionTimer, spellIdlePause());
      }
    }

    function ensureKickoff() {
      if (kickoffDone) return;
      kickoffDone = true;
      const c = pickKickoffCarrier("home");
      possession = "home";
      phase = "BUILD_UP";
      giveBall(c, "Kick-off");
      actionTimer = 0.8;
    }

    function formatScoreDisplay() {
      const base = `${homeScore}-${awayScore}`;
      if (decidedBy === "pens") return `${base} (${penScore.home}-${penScore.away} pens)`;
      if (decidedBy === "aet") return `${base} AET`;
      return base;
    }

    function resolveMatchWinner() {
      if (isTwoLegLeg1) return null; // leg 1 never decides the tie
      if (isTwoLegLeg2) {
        const aggHome = homeScore + (aggContext.enteringAggHome || 0);
        const aggAway = awayScore + (aggContext.enteringAggAway || 0);
        if (aggHome > aggAway) return homeTeam.name;
        if (aggAway > aggHome) return awayTeam.name;
        // Aggregate level — away-goals rule: home's away goals are fixed
        // from leg 1 (enteringAggHome, since that's the only leg they
        // played away); away's away goals are this leg's own live score
        // (they're the away side right now, in leg 2).
        const homeAwayGoals = aggContext.enteringAggHome || 0;
        const awayAwayGoals = awayScore;
        if (homeAwayGoals > awayAwayGoals) return homeTeam.name;
        if (awayAwayGoals > homeAwayGoals) return awayTeam.name;
        // Away goals also level — fall through to this leg's own ET/pens.
      } else if (homeScore > awayScore) {
        return homeTeam.name;
      } else if (awayScore > homeScore) {
        return awayTeam.name;
      }
      if (decidedBy === "pens") {
        if (penScore.home > penScore.away) return homeTeam.name;
        if (penScore.away > penScore.home) return awayTeam.name;
      }
      return null;
    }

    function clockLabel() {
      if (finished) {
        if (decidedBy === "pens") return "Pens";
        if (decidedBy === "aet" || (ft90Home != null && (homeScore !== ft90Home || awayScore !== ft90Away))) return "AET";
        return "90'";
      }
      if (pensActive || breakKind === "pens") return "Pens";
      return `${Math.floor(matchMinute)}'`;
    }

    function getBroadcastState() {
      const poss = possessionPct();
      let status = "prematch";
      if (finished) status = "ft";
      else if (breakKind === "ht" || halfTimePaused) status = "ht";
      else if (breakKind === "et_intro") status = "ft_et";
      else if (breakKind === "et_half") status = "et_ht";
      else if (breakKind === "pens" || pensActive) status = "pens";
      else if (clockCap > 90 && (kickoffDone || playing || matchMinute > 90)) status = "et";
      else if (kickoffDone || playing || matchMinute > 0) status = "live";
      else if (showPrematch && prematchOverlay && !prematchOverlay.hidden) status = "prematch";
      else status = playing ? "live" : "prematch";
      return {
        status,
        minute: Math.round(matchMinute * 10) / 10,
        score: `${homeScore}-${awayScore}`,
        scoreDisplay: formatScoreDisplay(),
        homeGoals: homeScore,
        awayGoals: awayScore,
        ft90Home,
        ft90Away,
        pensHome: penScore.home,
        pensAway: penScore.away,
        penLog: penLog.slice(),
        decidedBy,
        breakKind,
        clockCap,
        possession: possession,
        phase: spell?.stage || phase,
        phaseLabel: phaseEl?.textContent || "",
        attackPattern: spell?.pattern || null,
        ball: getBallPathState(),
        pins: allPins.map((p) => ({
          id: p.id,
          left: Math.round(p.left * 100) / 100,
          top: Math.round(p.top * 100) / 100,
          tx: Math.round(p.tx * 100) / 100,
          ty: Math.round(p.ty * 100) / 100,
          // Identity — normally static, but a mid-match substitution or
          // formation change mutates these on the host; carrying them in
          // every frame lets viewers pick the change up the same way they
          // pick up any other state change, no separate protocol needed.
          slot: p.slot,
          role: p.role,
          player: p.player,
          short: p.short,
          label: p.label,
          hasBall: p.id === carrierId,
          pressing: Boolean(p._pressing),
          running: Boolean(p._running),
        })),
        possPct: poss,
        xg: {
          home: Math.round(liveXg.home * 100) / 100,
          away: Math.round(liveXg.away * 100) / 100,
        },
        commentary: commentaryLines.slice(-5).map((c) =>
          typeof c === "string" ? c : `${c.minute}' ${c.text}`
        ),
        playing: Boolean(playing),
        finished: Boolean(finished),
        halfTime: Boolean(halfTimePaused || breakKind === "ht"),
        knockout: Boolean(isKnockout),
        // FM Mobile broadcast mode — matchLog itself (counts/events/goals)
        // is never sent frame-by-frame to viewers, only this compact
        // summary, so a spectator's stats panel/scorer strip stay accurate
        // instead of sitting at zero all match. Purely additive to the
        // frame; getMatchLog() (what actually gets recorded server-side —
        // see matchday.js's saveFullTime) is completely untouched.
        mobileStats: mobileBroadcast
          ? {
              home: mobileTeamStats("home"),
              away: mobileTeamStats("away"),
              goals: matchLog.goals.map((g) => ({ side: g.side, minute: g.minute, player_short: g.player_short || g.player })),
              cards: matchLog.events
                .filter((e) => e.type === "yellow_card")
                .map((e) => ({ side: e.side, minute: e.minute, player_short: e.player_short || e.player })),
            }
          : null,
        // FM Mobile broadcast mode — a viewer should just be a watcher of
        // whatever the host is actually showing, not run its own separate
        // "is this a key event" detection (it never sees pushMatchEvent
        // calls at all — those only fire on the host's own simulation).
        // Sync the one bit that matters: is the host's pitch expanded
        // right now. applyBroadcastState below just mirrors it. Includes
        // mobileBuildupActive too -- otherwise a viewer never sees the
        // pre-shot buildup the host's own screen already shows, only the
        // post-event hold once the shot itself has already happened.
        mobileEventLive: mobileBroadcast ? mobileEventUntilTs > 0 || mobileBuildupActive : false,
      };
    }

    function renderPensList(rows) {
      if (!pensListEl) return;
      const list = rows || penLog;
      if (!list.length) {
        pensListEl.hidden = true;
        pensListEl.innerHTML = "";
        return;
      }
      pensListEl.hidden = false;
      pensListEl.innerHTML = list
        .map(
          (k) =>
            `<li class="tactic-pen-row ${k.scored ? "scored" : "missed"}">` +
            `<span class="pen-side">${escHtml(k.side === "home" ? homeTeam.name : awayTeam.name)}</span>` +
            `<span class="pen-player">${escHtml(k.player || "")}</span>` +
            `<span class="pen-result">${k.scored ? "GOAL" : "MISS"}</span></li>`
        )
        .join("");
    }

    function fillBreakOverlay(kind) {
      const poss = possessionPct();
      if (htScoreEl) htScoreEl.textContent = `${homeScore} – ${awayScore}`;
      if (htPossEl) htPossEl.textContent = `${poss.home}%–${poss.away}%`;
      if (htXgEl) htXgEl.textContent = `${liveXg.home.toFixed(2)}–${liveXg.away.toFixed(2)}`;
      if (htScoreLabEl) htScoreLabEl.textContent = `${homeScore}–${awayScore}`;
      if (htStatsEl) {
        htStatsEl.textContent =
          `Possession ${poss.home}%–${poss.away}% · xG ${liveXg.home.toFixed(2)}–${liveXg.away.toFixed(2)}`;
      }
      const showStats = kind !== "pens";
      if (htStatsGrid) htStatsGrid.hidden = !showStats;
      if (breakNoteEl) {
        breakNoteEl.hidden = false;
        if (kind === "ht") {
          breakNoteEl.textContent = "";
          breakNoteEl.hidden = true;
        } else if (kind === "et_intro") {
          breakNoteEl.textContent =
            ft90Home != null
              ? `Full time ${ft90Home}–${ft90Away}. Knockout — extra time (2×15).`
              : "Knockout — extra time (2×15).";
        } else if (kind === "et_half") {
          breakNoteEl.textContent = "End of first period of extra time.";
        } else if (kind === "pens") {
          breakNoteEl.textContent =
            `Still ${homeScore}–${awayScore} after extra time — penalty shoot-out.`;
        }
      }
      if (htTitleEl) {
        htTitleEl.textContent =
          kind === "ht"
            ? "Half time"
            : kind === "et_intro"
              ? "Full time — Extra time"
              : kind === "et_half"
                ? "Extra time — half"
                : kind === "pens"
                  ? "Penalties"
                  : "Break";
      }
      if (htResumeBtn) {
        htResumeBtn.hidden = viewerMode || kind === "pens";
        htResumeBtn.textContent =
          kind === "ht"
            ? "Resume 2nd half"
            : kind === "et_intro"
              ? "Start extra time"
              : kind === "et_half"
                ? "Resume extra time"
                : "Continue";
      }
      if (kind === "pens") renderPensList(penLog);
      else if (pensListEl) {
        pensListEl.hidden = true;
        pensListEl.innerHTML = "";
      }
    }

    function applyViewerBreak(state) {
      if (!htOverlay) return;
      const st = state.status;
      const show =
        st === "ht" || st === "ft_et" || st === "et_ht" || st === "pens";
      htOverlay.hidden = !show;
      if (!show) return;
      const kind =
        st === "ht" ? "ht" : st === "ft_et" ? "et_intro" : st === "et_ht" ? "et_half" : "pens";
      if (state.ft90Home != null) ft90Home = state.ft90Home;
      if (state.ft90Away != null) ft90Away = state.ft90Away;
      if (state.pensHome != null) penScore.home = Number(state.pensHome) || 0;
      if (state.pensAway != null) penScore.away = Number(state.pensAway) || 0;
      if (Array.isArray(state.penLog)) penLog = state.penLog.slice();
      if (state.decidedBy) decidedBy = state.decidedBy;
      fillBreakOverlay(kind);
      if (htResumeBtn) htResumeBtn.hidden = true;
      if (kind === "pens") renderPensList(state.penLog || penLog);
    }

    function applyBroadcastState(state) {
      if (!state || typeof state !== "object") return;
      if (typeof state.minute === "number") {
        matchMinute = state.minute;
      }
      if (state.homeGoals != null) homeScore = Number(state.homeGoals) || 0;
      if (state.awayGoals != null) awayScore = Number(state.awayGoals) || 0;
      scoreEl.textContent = `${homeScore} – ${awayScore}`;
      if (state.possession) possession = state.possession;
      if (state.phaseLabel) phaseEl.textContent = state.phaseLabel;
      else if (state.phase) phase = state.phase;
      if (state.clockCap != null) clockCap = Number(state.clockCap) || clockCap;
      if (state.ft90Home != null) ft90Home = state.ft90Home;
      if (state.ft90Away != null) ft90Away = state.ft90Away;
      if (state.decidedBy) decidedBy = state.decidedBy;

      if (Array.isArray(state.pins)) {
        for (const sp of state.pins) {
          const pin = pinById.get(sp.id);
          if (!pin) continue;
          // Host publishes targets — viewer eases toward tx/ty (never snaps)
          pin.tx = Number.isFinite(sp.tx) ? sp.tx : sp.left;
          pin.ty = Number.isFinite(sp.ty) ? sp.ty : sp.top;
          pin._pressing = Boolean(sp.pressing);
          pin._running = Boolean(sp.running);
          if (sp.hasBall) carrierId = pin.id;
          const el = pinEls.get(pin.id);
          // Identity — only changes on a host-side substitution or
          // formation change; cheap to check every frame, only touches the
          // DOM when it actually differs.
          const identityChanged = sp.player && sp.player !== pin.player;
          if (identityChanged) {
            pin.player = sp.player;
            pin.short = sp.short || pin.short;
            pin.label = sp.label || pin.label;
          }
          if (sp.slot && sp.slot !== pin.slot) pin.slot = sp.slot;
          if (sp.role && sp.role !== pin.role) pin.role = sp.role;
          if (el && identityChanged) {
            el.title = `${pin.player} (${pin.slot}) — click to favor`;
            const labelEl = el.querySelector(".pin-label");
            if (labelEl) labelEl.textContent = pin.label;
          }
          if (el) {
            el.classList.toggle("has-ball", Boolean(sp.hasBall));
            el.classList.toggle("pressing", Boolean(sp.pressing));
            el.classList.toggle("running", Boolean(sp.running) && !sp.hasBall);
          }
        }
      }
      if (state.ball) {
        const b = state.ball;
        const bl = Number(b.left);
        const bt = Number(b.top);
        if (Number.isFinite(bl) && Number.isFinite(bt)) {
          // Prefer host's pre-decided path when present
          if (b.to && Number.isFinite(b.to.left) && Number.isFinite(b.tween) && b.tween < 0.98 && !b.attached) {
            ballFrom = b.from && Number.isFinite(b.from.left) ? { left: b.from.left, top: b.from.top } : { left: ball.left, top: ball.top };
            ballTo = { left: b.to.left, top: b.to.top };
            ballCtrl =
              b.ctrl && Number.isFinite(b.ctrl.left)
                ? { left: b.ctrl.left, top: b.ctrl.top }
                : null;
            ballTween = clamp(Number(b.tween) || 0, 0, 1);
            ballTweenDur = Math.max(0.18, Number(b.tweenDur) || Number(b.dur) || 0.4);
            ballAttached = false;
            // Sync current position along the path
            const u = easeInOut(ballTween);
            if (ballCtrl) {
              ball.left = bezier2(ballFrom.left, ballCtrl.left, ballTo.left, u);
              ball.top = bezier2(ballFrom.top, ballCtrl.top, ballTo.top, u);
            } else {
              ball.left = lerp(ballFrom.left, ballTo.left, u);
              ball.top = lerp(ballFrom.top, ballTo.top, u);
            }
          } else if (b.attached) {
            ballAttached = true;
            ballTo = { left: bl, top: bt };
            ballFrom = { left: ball.left, top: ball.top };
            ballTween = 1;
            ballCtrl = null;
            ball.left = smoothDamp(ball.left, bl, 0.35);
            ball.top = smoothDamp(ball.top, bt, 0.35);
          } else {
            ballFrom = { left: ball.left, top: ball.top };
            ballTo = { left: bl, top: bt };
            const dx = bl - ball.left;
            const dy = bt - ball.top;
            const d = Math.hypot(dx, dy);
            if (d > 4) {
              const midL = (ball.left + bl) * 0.5;
              const midT = (ball.top + bt) * 0.5;
              const nx = d > 1e-6 ? -dy / d : 0;
              const ny = d > 1e-6 ? dx / d : 0;
              ballCtrl = {
                left: clamp(midL + nx * Math.min(8, d * 0.18), 2, 98),
                top: clamp(midT + ny * Math.min(6, d * 0.14), 2, 98),
              };
            } else {
              ballCtrl = null;
            }
            ballTween = 0;
            ballTweenDur = clamp(0.16 + d * 0.008, 0.16, 0.45);
            ballAttached = false;
          }
        }
      }
      if (state.possPct) {
        if (possHEl) possHEl.textContent = String(state.possPct.home ?? 50);
        if (possAEl) possAEl.textContent = String(state.possPct.away ?? 50);
      }
      if (state.xg) {
        liveXg.home = Number(state.xg.home) || 0;
        liveXg.away = Number(state.xg.away) || 0;
        if (xgHEl) xgHEl.textContent = liveXg.home.toFixed(2);
        if (xgAEl) xgAEl.textContent = liveXg.away.toFixed(2);
      }
      if (mobileBroadcast) {
        setMobileLive(Boolean(state.mobileEventLive));
      }
      if (mobileBroadcast && mobileStatsEl) {
        const ms = state.mobileStats;
        const set = (key, val) => {
          if (mobileStatEls[key]) mobileStatEls[key].textContent = val;
        };
        if (state.possPct) {
          set("poss-home", `${state.possPct.home ?? 50}%`);
          set("poss-away", `${state.possPct.away ?? 50}%`);
        }
        if (state.xg) {
          set("xg-home", liveXg.home.toFixed(2));
          set("xg-away", liveXg.away.toFixed(2));
        }
        if (ms) {
          set("bigchances-home", ms.home.bigChances);
          set("bigchances-away", ms.away.bigChances);
          set("shots-home", ms.home.shots);
          set("shots-away", ms.away.shots);
          set("sot-home", ms.home.shotsOnTarget);
          set("sot-away", ms.away.shotsOnTarget);
          set("fouls-home", ms.home.fouls);
          set("fouls-away", ms.away.fouls);
          set("corners-home", ms.home.corners);
          set("corners-away", ms.away.corners);
          if (mobileScorersHomeEl && mobileScorersAwayEl) {
            const rowsFor = (side) => {
              const goalRows = ms.goals
                .filter((g) => g.side === side)
                .map((g) => `<div class="ms-scorer">⚽ ${escHtml(g.player_short)} ${g.minute}'</div>`);
              const cardRows = ms.cards
                .filter((e) => e.side === side)
                .map((e) => `<div class="ms-scorer ms-card">\u{1F7E8} ${escHtml(e.player_short)} ${e.minute}'</div>`);
              return goalRows.concat(cardRows).join("");
            };
            mobileScorersHomeEl.innerHTML = rowsFor("home");
            mobileScorersAwayEl.innerHTML = rowsFor("away");
          }
        }
      }
      if (Array.isArray(state.commentary) && feedEl) {
        feedEl.innerHTML = state.commentary
          .map((line) => {
            const text = typeof line === "string" ? line : `${line.minute || ""}' ${line.text || ""}`;
            const m = typeof line === "string" ? "" : `${line.minute || ""}'`;
            const body = typeof line === "string" ? line : line.text || "";
            return `<div class="tactic-commentary-item"><span class="cm-min">${escHtml(m)}</span>${escHtml(body || text)}</div>`;
          })
          .join("");
        feedEl.scrollTop = feedEl.scrollHeight;
      }
      if (prematchOverlay) {
        prematchOverlay.hidden = state.status !== "prematch";
      }
      finished = Boolean(state.finished) || state.status === "ft";
      halfTimePaused = state.status === "ht";
      breakPaused = ["ht", "ft_et", "et_ht", "pens"].includes(state.status);
      breakKind =
        state.status === "ht"
          ? "ht"
          : state.status === "ft_et"
            ? "et_intro"
            : state.status === "et_ht"
              ? "et_half"
              : state.status === "pens"
                ? "pens"
                : null;
      pensActive = state.status === "pens" && !finished;
      applyViewerBreak(state);
      clockEl.textContent = finished
        ? state.decidedBy === "pens"
          ? "Pens"
          : state.decidedBy === "aet" || (state.minute || 0) >= 105
            ? "AET"
            : "90'"
        : state.status === "pens"
          ? "Pens"
          : `${Math.floor(matchMinute)}'`;
    }

    function maybeBroadcast(force) {
      if (!onBroadcast || viewerMode) return;
      const now = performance.now();
      if (!force && now - lastBroadcastAt < broadcastEvery) return;
      lastBroadcastAt = now;
      try {
        onBroadcast(getBroadcastState());
      } catch (_) {}
    }

    function pauseForBreak(kind) {
      breakKind = kind;
      breakPaused = true;
      halfTimePaused = kind === "ht";
      playing = false;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      lastTs = 0;
      clearFlash();
      clearGoalCard();
      fillBreakOverlay(kind);
      if (htOverlay) htOverlay.hidden = false;
      const playBtn = container.querySelector("[data-tb-play]");
      if (playBtn) playBtn.textContent = "Play";
      updateHud();
      maybeBroadcast(true);
      // Matchday host: auto-continue ET breaks after a short beat (HT stays manual).
      if (hostMode && (kind === "et_intro" || kind === "et_half")) {
        const delay = kind === "et_intro" ? 2200 : 1800;
        schedule(() => {
          if (breakKind === kind && breakPaused && !finished) resumeFromBreak();
        }, delay);
      }
    }

    function enterHalfTime() {
      halfTimeShown = true;
      matchMinute = 45;
      clockEl.textContent = "45'";
      say(`Half time ${homeScore}–${awayScore}`, 2.5);
      pauseForBreak("ht");
    }

    function enterExtraTimeIntro() {
      ft90Home = homeScore;
      ft90Away = awayScore;
      matchMinute = 90;
      clockEl.textContent = "90'";
      say(`Full time ${homeScore}–${awayScore} — extra time`, 2.8);
      pauseForBreak("et_intro");
    }

    function enterEtHalf() {
      matchMinute = 105;
      clockEl.textContent = "105'";
      say(`ET half-time ${homeScore}–${awayScore}`, 2.2);
      pauseForBreak("et_half");
    }

    function enterPensBreak() {
      matchMinute = 120;
      clockEl.textContent = "Pens";
      say(`Penalties — still ${homeScore}–${awayScore}`, 2.5);
      pauseForBreak("pens");
      // Auto-run shoot-out after a short beat (host); viewers follow broadcast.
      if (!viewerMode) {
        schedule(() => startPenalties(), 900);
      }
    }

    function resumeFromBreak() {
      if (!breakPaused && !halfTimePaused) return;
      const kind = breakKind || (halfTimePaused ? "ht" : null);
      if (!kind || kind === "pens") return;
      breakPaused = false;
      halfTimePaused = false;
      breakKind = null;
      if (htOverlay) htOverlay.hidden = true;
      clearFlash();
      clearGoalCard();
      if (kind === "ht") {
        matchMinute = 45.05;
        clockCap = 90;
        clockEl.textContent = "45'";
        say("Second half underway", 1.8);
        // Engine rebuild — finishing form was drawn once at kickoff and held
        // for the entire match; a single unlucky "cold" roll could lock a
        // team out of scoring for the whole 90 minutes regardless of the
        // chances they actually created. Real production data showed exactly
        // this (a team generating 2+ xG and finishing with zero goals).
        // Re-draw for the second half so a bad first half isn't a life
        // sentence - a team really can come out and turn it around.
        redrawFinishingForm();
      } else if (kind === "et_intro") {
        matchMinute = 90.05;
        clockCap = 105;
        clockEl.textContent = "91'";
        say("Extra time — first period", 1.8);
        phaseEl.textContent = "Extra time";
      } else if (kind === "et_half") {
        matchMinute = 105.05;
        clockCap = 120;
        clockEl.textContent = "106'";
        say("Extra time — second period", 1.8);
        phaseEl.textContent = "Extra time";
      }
      play();
      maybeBroadcast(true);
    }

    function resumeSecondHalf() {
      if (breakKind === "ht" || halfTimePaused) resumeFromBreak();
    }

    function pickPenaltyOrder(side) {
      const pins = pinsOf(side).filter((p) => p.role !== "GK");
      const rank = (p) =>
        (p.stats.xg90 || 0) * 2.2 +
        (p.stats.shots90 || 0) * 0.08 +
        // Specialist-taker signal, distinct from open-play threat.
        (p.stats.penalty_goals90 || 0) * 1.5 +
        // Engine addition — a real set-piece-taking midfielder (Lampard,
        // Pirlo on some sides) is a recognized role; smaller than ST/AM/W
        // since it's a secondary job for a CM/DM, not primary.
        (p.role === "ST"
          ? 0.35
          : p.role === "AM"
            ? 0.22
            : p.role === "W"
              ? 0.15
              : p.role === "CM" || p.role === "DM"
                ? 0.1
                : 0);
      return [...pins].sort((a, b) => rank(b) - rank(a));
    }

    function penConvertChance(taker, keeper) {
      const form = clamp(finishingForm[taker.side] ?? 1, 0.55, 1.45);
      const fin = sideFinishing(taker.side);
      // Previously zero opposing-keeper signal existed here at all (team or
      // individual) -- an above-average real keeper now trims conversion
      // odds a little, a below-average one nudges them up.
      const gkAdj = keeper ? (0.5 - gkPinQuality(keeper)) * 0.12 : 0;
      const base =
        0.7 +
        (taker.stats.xg90 || 0) * 0.1 +
        fin * 0.1 +
        (taker.stats.penalty_goals90 || 0) * 0.06 +
        gkAdj +
        (taker.role === "ST" || taker.role === "AM" ? 0.04 : taker.role === "CM" || taker.role === "DM" ? 0.02 : 0);
      return clamp(base * (0.85 + 0.15 * form), 0.52, 0.9);
    }

    function startPenalties() {
      if (pensActive || finished || viewerMode) return;
      pensActive = true;
      breakKind = "pens";
      breakPaused = true;
      playing = false;
      decidedBy = "pens";
      penScore = { home: 0, away: 0 };
      penLog = [];
      fillBreakOverlay("pens");
      if (htOverlay) htOverlay.hidden = false;
      if (htResumeBtn) htResumeBtn.hidden = true;
      phaseEl.textContent = "Penalties";
      maybeBroadcast(true);

      const homeOrder = pickPenaltyOrder("home");
      const awayOrder = pickPenaltyOrder("away");
      const kicks = [];
      for (let i = 0; i < 5; i++) {
        if (homeOrder[i]) kicks.push({ side: "home", pin: homeOrder[i], round: i + 1 });
        if (awayOrder[i]) kicks.push({ side: "away", pin: awayOrder[i], round: i + 1 });
      }
      // Sudden-death pool — cycle takers until a winner (never leave empty)
      for (let sd = 0; sd < 24; sd++) {
        const hi = homeOrder.length ? homeOrder[sd % homeOrder.length] : null;
        const ai = awayOrder.length ? awayOrder[sd % awayOrder.length] : null;
        if (hi) kicks.push({ side: "home", pin: hi, round: 6 + sd, sudden: true });
        if (ai) kicks.push({ side: "away", pin: ai, round: 6 + sd, sudden: true });
      }

      let idx = 0;
      let homeTaken = 0;
      let awayTaken = 0;

      function pensDecided() {
        if (homeTaken < 5 || awayTaken < 5) {
          const hLeft = 5 - homeTaken;
          const aLeft = 5 - awayTaken;
          if (penScore.home > penScore.away + aLeft) return true;
          if (penScore.away > penScore.home + hLeft) return true;
          return false;
        }
        return penScore.home !== penScore.away;
      }

      function fireKick() {
        if (finished) return;
        if (idx >= kicks.length) {
          // Force a winner if somehow still level
          if (penScore.home === penScore.away) {
            if (rng() < 0.5) penScore.home += 1;
            else penScore.away += 1;
          }
          finishMatch();
          return;
        }
        if (homeTaken >= 5 && awayTaken >= 5 && pensDecided()) {
          finishMatch();
          return;
        }

        const kick = kicks[idx++];
        const scored = rng() < penConvertChance(kick.pin, gkOf(oppOf(kick.side)));
        if (kick.side === "home") {
          homeTaken += 1;
          if (scored) penScore.home += 1;
        } else {
          awayTaken += 1;
          if (scored) penScore.away += 1;
        }
        const entry = {
          side: kick.side,
          player: kick.pin.player || kick.pin.short,
          player_short: kick.pin.short,
          scored,
          round: kick.round,
        };
        penLog.push(entry);
        pushMatchEvent("penalty", kick.side, {
          player: entry.player,
          player_short: entry.player_short,
          detail: scored ? "scored" : "missed",
        });
        say(
          `${kick.pin.short || kick.pin.player} (${kick.side === "home" ? homeTeam.name : awayTeam.name}) — ${
            scored ? "scores" : "misses"
          }! ${penScore.home}–${penScore.away}`,
          2.2
        );
        renderPensList(penLog);
        if (breakNoteEl) {
          breakNoteEl.hidden = false;
          breakNoteEl.textContent = `Penalties ${penScore.home}–${penScore.away}`;
        }
        maybeBroadcast(true);

        if (pensDecided()) {
          schedule(() => finishMatch(), 1100);
          return;
        }
        schedule(fireKick, 1250);
      }

      schedule(fireKick, 700);
    }

    // Is the tie still undecided at this instant? For a single-legged tie
    // (or leg 1, which never decides anything) this is just "level on this
    // leg's own score". For leg 2 of a two-legged tie, the aggregate and
    // away-goals rule both have to be exhausted first — see
    // resolveMatchWinner() for the matching post-decision logic.
    function tieStillUndecided() {
      if (isTwoLegLeg1) return false; // leg 1 never goes to ET regardless of its own score
      if (isTwoLegLeg2) {
        const aggHome = homeScore + (aggContext.enteringAggHome || 0);
        const aggAway = awayScore + (aggContext.enteringAggAway || 0);
        if (aggHome !== aggAway) return false;
        const homeAwayGoals = aggContext.enteringAggHome || 0;
        const awayAwayGoals = awayScore;
        return homeAwayGoals === awayAwayGoals;
      }
      return homeScore === awayScore;
    }

    function handleEndOfNinety() {
      if (replayScore) {
        for (const g of scheduled) {
          if (!g.scored) {
            g.scored = true;
            if (g.side === "home") homeScore += 1;
            else awayScore += 1;
          }
        }
        scoreEl.textContent = `${homeScore} – ${awayScore}`;
      }
      ft90Home = homeScore;
      ft90Away = awayScore;
      if (isKnockout && tieStillUndecided()) {
        enterExtraTimeIntro();
        return;
      }
      decidedBy = "ft";
      finishMatch();
    }

    function handleEndOfEtPeriod(cap) {
      if (cap === 105) {
        enterEtHalf();
        return;
      }
      // End of ET2
      if (tieStillUndecided()) {
        enterPensBreak();
        return;
      }
      decidedBy = "aet";
      finishMatch();
    }

    function finishMatch() {
      finished = true;
      playing = false;
      pensActive = false;
      breakPaused = false;
      halfTimePaused = false;
      breakKind = null;
      clearFlash();
      clearGoalCard();
      if (replayScore) {
        homeScore = homeGoalsTarget;
        awayScore = awayGoalsTarget;
        scoreEl.textContent = `${homeScore} – ${awayScore}`;
      }
      if (ft90Home == null) ft90Home = homeScore;
      if (ft90Away == null) ft90Away = awayScore;
      if (decidedBy === "pens" && penScore.home === penScore.away) {
        // Safety: never end pens level
        if (rng() < 0.5) penScore.home += 1;
        else penScore.away += 1;
      }
      if (decidedBy !== "pens" && decidedBy !== "aet") {
        if (ft90Home !== homeScore || ft90Away !== awayScore) decidedBy = "aet";
        else decidedBy = "ft";
      }
      clockEl.textContent = clockLabel();
      updateHud();
      const disp = formatScoreDisplay();
      const winnerName = resolveMatchWinner();
      say(
        decidedBy === "pens"
          ? `Won on penalties ${disp}${winnerName ? ` — ${winnerName}` : ""}`
          : decidedBy === "aet"
            ? `Full time (AET) ${disp}`
            : `Full time ${disp}`,
        3
      );
      if (htOverlay) {
        if (decidedBy === "pens" || decidedBy === "aet" || isKnockout) {
          if (decidedBy === "pens") fillBreakOverlay("pens");
          else {
            if (htStatsGrid) htStatsGrid.hidden = false;
            if (pensListEl) {
              pensListEl.hidden = true;
              pensListEl.innerHTML = "";
            }
            if (htScoreEl) htScoreEl.textContent = `${homeScore} – ${awayScore}`;
          }
          if (htTitleEl) {
            htTitleEl.textContent =
              decidedBy === "pens"
                ? "Won on penalties"
                : decidedBy === "aet"
                  ? "Full time (AET)"
                  : "Full time";
          }
          if (breakNoteEl) {
            breakNoteEl.hidden = false;
            breakNoteEl.textContent = winnerName
              ? `${disp} — ${winnerName} advances`
              : disp;
          }
          if (htResumeBtn) htResumeBtn.hidden = true;
          if (decidedBy === "pens") renderPensList(penLog);
          htOverlay.hidden = false;
        } else {
          htOverlay.hidden = true;
        }
      }
      const playBtn = container.querySelector("[data-tb-play]");
      if (playBtn) playBtn.textContent = "Play";
      setBallTarget(50, 50, 0.6, false);
      ballAttached = false;
      carrierId = null;
      phaseEl.textContent =
        decidedBy === "pens" ? "Penalties complete" : decidedBy === "aet" ? "AET" : "Full time";
      maybeBroadcast(true);
      if (!completeFired && onComplete) {
        completeFired = true;
        const log = getMatchLogPayload();
        if (log && typeof log === "object") {
          log.decided_by = decidedBy;
          log.ft_score = { home: ft90Home, away: ft90Away };
          if (decidedBy === "pens") {
            log.pens = { home: penScore.home, away: penScore.away, kicks: penLog.slice() };
          }
        }
        onComplete({
          homeGoals: homeScore,
          awayGoals: awayScore,
          home: homeTeam.name,
          away: awayTeam.name,
          engine: "tactic_board",
          match_log: log,
          board_events: log.events,
          decided_by: decidedBy,
          ft_home_goals: ft90Home,
          ft_away_goals: ft90Away,
          pens_home: decidedBy === "pens" ? penScore.home : null,
          pens_away: decidedBy === "pens" ? penScore.away : null,
          winner: winnerName,
          score_display: disp,
        });
      }
    }

    function tickDecision() {
      // Hierarchy every decision tick: STATE → SHAPE (both teams) → ball decision
      if (spell && spell.side === possession) syncPossessionState();
      updateTeamShape();
      flushDeferredRestarts();
      if (actionTimer <= 0 && !finished && ballTween >= 1 && !ballFlight) {
        decideAction();
      }
    }

    /**
     * Live Presentation Director -- Phase 1 (experimental, parallel to
     * willAttemptChance/isMobileKeyEvent). Purely observational: computes
     * and (optionally) displays a "how interesting is the current
     * situation becoming" score every render tick, but does not touch
     * possession/spell/carrier/speed/mobileEventUntilTs or drive any real
     * presentation decision yet -- per the user's own staged spec, this
     * stays additive until it's been watched against real matches.
     *
     * Deliberately NOT a shot-probability model: shot opportunity
     * (shotAngleQuality) is the single biggest of six inputs, not the
     * whole score, so a promising buildup that never quite reaches a shot
     * still registers as "interesting". Nothing here calls rng() --
     * estimateChanceXg was ruled out for exactly that reason, since
     * sampling it speculatively every tick (instead of only at real
     * shot-taking) would perturb the seeded match-outcome sequence.
     */
    function computeLiveThreat() {
      const carrier = findCarrier();
      const rel = fromPitchPct(possession, ball.left, ball.top);

      // 1. Ball zone (max 12) -- reuses the engine's own phase bucketing.
      const zoneScore = { BUILD_UP: 0, PROGRESSING: 4, FINAL_THIRD: 8, BOX_OCCUPATION: 12 }[phase] || 0;

      // 2. Progression type (max 10) -- depth trend vs. a slow-lagging
      // baseline (not a single-frame delta), so one backward layoff mid-
      // surge doesn't read as "retreating".
      const depthDelta = rel.depth - threatPrevDepth;
      threatPrevDepth += (rel.depth - threatPrevDepth) * 0.15;
      const progressionScore =
        depthDelta > 0.015 ? 10 * clamp(depthDelta / 0.05, 0, 1) : depthDelta < -0.015 ? 0 : 4;

      // 3. Defensive structure (max 20) -- reuses Phase 3's live, decaying
      // exposure tracking (set the instant a defender is beaten).
      const exposure = defensiveShapeExposure[possession] || { central: 0, wide: 0 };
      const structureScore = 20 * clamp(Math.max(exposure.central, exposure.wide), 0, 1);

      // 4. Numerical situation (max 16) -- attackers vs. defenders actually
      // near the ball, not a whole-pitch count.
      const attackersNear = pinsOf(possession).filter((p) => p.role !== "GK" && dist(p, ball) <= 16).length;
      const defendersNear = pinsOf(oppOf(possession)).filter((p) => p.role !== "GK" && dist(p, ball) <= 16).length;
      const numbersUp = attackersNear - defendersNear;
      const numbersScore = numbersUp >= 2 ? 16 : numbersUp === 1 ? 10 : numbersUp === 0 ? 4 : 0;

      // 5. Player position / zone quality (max 12) -- carrier's box proximity.
      const positionScore = !carrier
        ? 0
        : inPenaltyBox(carrier)
          ? 12
          : nearPenaltyBox(carrier)
            ? 7
            : isWideChannel(carrier) && rel.depth > 0.6
              ? 4
              : 0;

      // 6. Shot opportunity (max 30, deliberately the biggest single
      // component) -- shotAngleQuality is a pure-geometry, RNG-free proxy.
      const shotScore = carrier ? 30 * clamp(shotAngleQuality(carrier) / 1.3, 0, 1) : 0;

      // Engine-flagged build-up bonus -- mobileBuildupActive is already a
      // real "this spell is genuinely heading toward a chance" signal,
      // read-only here, never set/cleared by this function.
      const buildupBonus = mobileBuildupActive ? 8 : 0;

      const rawScore = clamp(
        zoneScore + progressionScore + structureScore + numbersScore + positionScore + shotScore + buildupBonus,
        0,
        100
      );
      threatScoreSmoothed += (rawScore - threatScoreSmoothed) * 0.35;

      // Match context -- score/time urgency nudges the hysteresis
      // thresholds, not the raw score, so an 89th-minute 1-1 counterattack
      // can interrupt sooner without inflating "how interesting" itself.
      const scoreDiff = Math.abs(homeScore - awayScore);
      const closeGame = scoreDiff <= 1 ? 1 : scoreDiff === 2 ? 0.4 : 0;
      const lateGame = matchMinute >= 75 ? clamp((matchMinute - 75) / 15, 0, 1) : 0;
      const contextUrgency = clamp(closeGame * 0.6 + lateGame * 0.6, 0, 1);

      const ENTER_BASE = 70;
      const EXIT_BASE = 30;
      const COOLDOWN_MS_BASE = 4000;
      const OVERRIDE_THRESHOLD = 92;
      const enterThreshold = ENTER_BASE - contextUrgency * 15;
      const cooldownMs = COOLDOWN_MS_BASE * (1 - contextUrgency * 0.5);

      const nowTs = performance.now();
      if (threatMode === "TICKER") {
        const cooldownOk = nowTs - lastThreatHighlightTs > cooldownMs;
        if (threatScoreSmoothed >= enterThreshold && (cooldownOk || threatScoreSmoothed >= OVERRIDE_THRESHOLD)) {
          threatMode = "HIGHLIGHT";
          lastThreatHighlightTs = nowTs;
        }
      } else if (threatScoreSmoothed <= EXIT_BASE) {
        threatMode = "TICKER";
      }

      lastThreatResult = {
        score: threatScoreSmoothed,
        mode: threatMode,
        breakdown: {
          zone: zoneScore,
          progression: progressionScore,
          structure: structureScore,
          numbers: numbersScore,
          position: positionScore,
          shot: shotScore,
          buildup: buildupBonus,
        },
      };
      return lastThreatResult;
    }

    function renderThreatDebug() {
      if (!threatDebugEl || !lastThreatResult) return;
      const b = lastThreatResult.breakdown;
      threatDebugEl.textContent =
        `LIVE THREAT [experimental]\n` +
        `zone........${b.zone.toFixed(0).padStart(4)}\n` +
        `progression.${b.progression.toFixed(0).padStart(4)}\n` +
        `structure...${b.structure.toFixed(0).padStart(4)}\n` +
        `numbers.....${b.numbers.toFixed(0).padStart(4)}\n` +
        `position....${b.position.toFixed(0).padStart(4)}\n` +
        `shot........${b.shot.toFixed(0).padStart(4)}\n` +
        `buildup.....${b.buildup.toFixed(0).padStart(4)}\n` +
        `TOTAL.......${lastThreatResult.score.toFixed(0).padStart(4)}\n` +
        `MODE: ${lastThreatResult.mode}`;
    }

    function tickRender(dt) {
      const moving = stepBallTween(dt);
      if (!moving && ballFlight) {
        resolveBallFlight();
      } else if (!moving && ballAttached) {
        attachBallToCarrier();
      }
      applyPinMotion(dt);
      if (mobileBroadcast) {
        computeLiveThreat();
        if (showThreatDebug) renderThreatDebug();
      }
    }

    // Hardening — tick() drives the whole match via a self-rescheduling
    // requestAnimationFrame loop, and the reschedule call used to be the
    // very last line of the function: any uncaught exception ANYWHERE in
    // the decision tree it calls into (tickDecision/decideAction and
    // everything under them) would exit before that line ever ran, and
    // requestAnimationFrame does not retry on its own — a single bad tick
    // silently froze the match forever, with no server-side trace and no
    // visible error unless devtools happened to be open. Wrapping the body
    // means one bad tick logs and gets skipped instead of permanently
    // killing the match; the loop still reschedules itself either way.
    function tick(ts) {
      try {
        _tickBody(ts);
      } catch (err) {
        console.error("tactic_board: tick() threw, skipping this frame and continuing", err);
        if (playing && !finished) {
          raf = requestAnimationFrame(tick);
        }
      }
    }

    function _tickBody(ts) {
      if (viewerMode) {
        // Viewer: interpolate toward host targets + ball path (no decisions)
        if (!lastTs) lastTs = ts;
        const dt = Math.min(0.05, (ts - lastTs) / 1000);
        lastTs = ts;
        tickRender(dt);
        raf = requestAnimationFrame(tick);
        return;
      }
      if (!playing || halfTimePaused || breakPaused || pensActive || finished) return;
      if (!lastTs) lastTs = ts;
      if (mobileBroadcast && mobileEventUntilTs > 0 && ts >= mobileEventUntilTs) {
        mobileEventUntilTs = 0;
        // Only drop back to fast mode if the buildup spell that triggered
        // this hold has also wrapped up -- otherwise a shot that continues
        // into a corner/rebound within the same spell would flash back to
        // the stats panel and immediately forward again.
        if (!mobileBuildupActive) {
          speed = MOBILE_NORMAL_SPEED;
          setMobileLive(false);
        }
      }
      const dt = Math.min(0.05, ((ts - lastTs) / 1000) * speed);
      lastTs = ts;
      if (mobileBroadcast) updateMobileZone();
      // FM Mobile broadcast mode -- willAttemptChance isn't only set at
      // beginSpell; several mid-spell decision points (progressToward-box
      // probes, etc.) can flip it true well after the possession started.
      // Poll every tick so the buildup view kicks in once a spell that's
      // committed to a chance is actually APPROACHING it (within
      // MOBILE_BUILDUP_WINDOW of spell.end), not the instant the flag
      // turns true -- see the beginSpell comment for why an unbounded
      // trigger blew up the fast/slow ratio for any spell that took a
      // while to resolve.
      if (
        mobileBroadcast &&
        spell &&
        spell.willAttemptChance &&
        !mobileBuildupActive &&
        spell.end - matchMinute <= MOBILE_BUILDUP_WINDOW
      ) {
        mobileBuildupActive = true;
        if (mobileEventUntilTs <= 0) {
          speed = MOBILE_EVENT_SPEED;
          setMobileLive(true);
        }
      }

      ensureKickoff();

      const prevMinute = matchMinute;
      const cap = clockCap || 90;
      matchMinute = Math.min(cap, matchMinute + (dt * 90) / MATCH_WATCH_SECONDS);
      clockEl.textContent = clockLabel();

      if (possession === "home" || possession === "away") {
        possSeconds[possession] += dt;
      }
      if (Math.floor(matchMinute * 2) !== Math.floor(prevMinute * 2)) {
        updateHud();
      }

      if (!halfTimeShown && prevMinute < 45 && matchMinute >= 45) {
        enterHalfTime();
        return;
      }

      if (commentaryHold > 0) commentaryHold -= dt;
      if (flashTimer > 0) {
        flashTimer -= dt;
        if (flashTimer <= 0) clearFlash();
      }
      if (goalCardTimer > 0) {
        goalCardTimer -= dt;
        if (goalCardTimer <= 0) clearGoalCard();
      }
      // Phase 3: Decay defensive shape exposure over time as defenders reset position
      if (defensiveShapeExposure) {
        const exposureDecay = dt * 0.5; // Decays to 0 in ~2 seconds if not refreshed
        defensiveShapeExposure.home.central = Math.max(0, defensiveShapeExposure.home.central - exposureDecay);
        defensiveShapeExposure.home.wide = Math.max(0, defensiveShapeExposure.home.wide - exposureDecay);
        defensiveShapeExposure.away.central = Math.max(0, defensiveShapeExposure.away.central - exposureDecay);
        defensiveShapeExposure.away.wide = Math.max(0, defensiveShapeExposure.away.wide - exposureDecay);
      }

      actionTimer -= dt;
      tickRender(dt);

      decisionAcc += dt;
      // Always flush deferred restarts / pending shots even between shape retargets
      flushDeferredRestarts();
      if (decisionAcc >= nextDecisionIn) {
        decisionAcc = 0;
        nextDecisionIn = DECISION_INTERVAL_MIN + rng() * (DECISION_INTERVAL_MAX - DECISION_INTERVAL_MIN);
        tickDecision();
      } else if (actionTimer <= 0 && !finished && ballTween >= 1 && !ballFlight) {
        // Action ready between cadence ticks — still shape-first, then ball
        if (spell && spell.side === possession) syncPossessionState();
        updateTeamShape();
        decideAction();
      }

      if (commentaryHold <= 0 && !finished) {
        const labels = {
          BUILD_UP: "Building from the back",
          PROGRESSING: "Progressing the ball",
          FINAL_THIRD: "Final third",
          BOX_OCCUPATION: "Occupying the box",
          CHANCE_CREATION: "Chance brewing",
          FINISH: "Chance on!",
          build: "Building from the back",
          progress: "Progressing the ball",
          retain: "Keeping possession",
          final: "Final third",
          chance: "Chance on!",
        };
        const key = spell?.stage || phase;
        if (matchMinute >= 90 && matchMinute < 120) {
          phaseEl.textContent = matchMinute < 105 ? "Extra time (1st)" : "Extra time (2nd)";
        } else {
          phaseEl.textContent = labels[key] || labels[phase] || "In play";
        }
      }

      if (matchMinute >= cap) {
        if (cap <= 90) {
          handleEndOfNinety();
        } else {
          handleEndOfEtPeriod(cap);
        }
        return;
      }
      maybeBroadcast(false);
      raf = requestAnimationFrame(tick);
    }

    function play() {
      if (breakPaused || halfTimePaused) {
        if (breakKind === "pens") return;
        resumeFromBreak();
        return;
      }
      if (finished) reset();
      playing = true;
      lastTs = 0;
      container.querySelector("[data-tb-play]").textContent = "Playing…";
      raf = requestAnimationFrame(tick);
    }

    function pause() {
      playing = false;
      container.querySelector("[data-tb-play]").textContent = "Play";
      if (raf) cancelAnimationFrame(raf);
    }

    function reset() {
      pause();
      clearTimers();
      matchMinute = 0;
      homeScore = 0;
      awayScore = 0;
      finished = false;
      completeFired = false;
      kickoffDone = false;
      halfTimeShown = false;
      halfTimePaused = false;
      breakPaused = false;
      breakKind = null;
      clockCap = 90;
      ft90Home = null;
      ft90Away = null;
      decidedBy = "ft";
      pensActive = false;
      penScore = { home: 0, away: 0 };
      penLog = [];
      if (htOverlay) htOverlay.hidden = true;
      if (pensListEl) {
        pensListEl.hidden = true;
        pensListEl.innerHTML = "";
      }
      if (breakNoteEl) breakNoteEl.hidden = true;
      if (htStatsGrid) htStatsGrid.hidden = false;
      if (htTitleEl) htTitleEl.textContent = "Half time";
      if (htResumeBtn) {
        htResumeBtn.hidden = false;
        htResumeBtn.textContent = "Resume 2nd half";
      }
      possession = "home";
      phase = "BUILD_UP";
      spell = null;
      carrierId = null;
      actionTimer = 0;
      commentaryHold = 0;
      lastGoalMinute = -20;
      favoredId = null;
      matchLog = emptyMatchLog();
      clearLastPasser();
      possSeconds = { home: 0, away: 0 };
      liveXg = { home: 0, away: 0 };
      breachRecoveryUntil = { home: 0, away: 0 };
      pendingSetPiece = null;
      lastTouchSide = null;
      oobStats = {
        outOfBoundsEvents: 0,
        touchlineExits: 0,
        bylineExits: 0,
        cornersGenerated: 0,
        goalKicksGenerated: 0,
        throwInsGenerated: 0,
        falsePositiveOob: 0,
      };
      leadProtectUntil = { home: 0, away: 0 };
      sideBigMissStreak = { home: 0, away: 0 };
      redrawFinishingForm();
      commentaryLines = [];
      if (feedEl) feedEl.innerHTML = "";
      instrHome = 0;
      instrAway = 0;
      instrHomeUntil = 0;
      instrAwayUntil = 0;
      ballAttached = true;
      ball = { left: 50, top: 50 };
      ballFrom = { left: 50, top: 50 };
      ballTo = { left: 50, top: 50 };
      ballCtrl = null;
      ballTween = 1;
      ballFlight = null;
      pendingRestart = null;
      pendingClear = null;
      pendingKickoffCarrier = null;
      pendingShot = null;
      freeKickUntil = 0;
      if (mobileBroadcast) {
        mobileEventUntilTs = 0;
        mobileBuildupActive = false;
        speed = MOBILE_NORMAL_SPEED;
        setMobileLive(false);
      }
      pendingCornerContext = null;
      cornerStats = {
        cornersWon: 0,
        delivery: { near: 0, far: 0, central: 0, edge: 0, short: 0 },
        firstContactsAttack: 0,
        firstContactsDefense: 0,
        clearances: 0,
        secondBalls: 0,
        cornerShots: 0,
      };
      fkStats = {
        directShots: 0,
        directCrosses: 0,
        wideCrosses: 0,
        midfieldRestarts: 0,
        indirectRestarts: 0,
      };
      shortCornerDiag = {
        totalCorners: 0,
        hadCandidate: 0,
        hadReceiver: 0,
        receiverMarked: 0,
        weakTaker: 0,
        aerialDisadvantage: 0,
        gateOpen: 0,
        selected: 0,
        samples: [],
      };
      decisionDiag = { samples: [] };
      pendingDecisionSnapshot = null;
      possessionCounts = {};
      decisionAcc = DECISION_INTERVAL_MAX;
      nextDecisionIn = DECISION_INTERVAL_MIN + rng() * (DECISION_INTERVAL_MAX - DECISION_INTERVAL_MIN);
      scoreEl.textContent = "0 – 0";
      clockEl.textContent = "0'";
      phaseEl.textContent = "Ready";
      clearFlash();
      clearGoalCard();
      updateHud();
      scheduled.forEach((g) => {
        g.scored = false;
      });
      allPins.forEach((p) => {
        const pct = toPitchPct(p.side, p.baseX, p.baseDepth);
        snapPinPose(p, pct.left, pct.top);
        p.lockUntil = 0;
        p.favorUntil = 0;
        p._bigMissStreak = 0;
        p._yellowCards = 0;
        const el = pinEls.get(p.id);
        if (el) {
          el.classList.remove("has-ball", "pressing", "favored");
        }
      });
      ballEl.style.left = "50%";
      ballEl.style.top = "50%";
    }

    container.querySelector("[data-tb-play]").addEventListener("click", play);
    container.querySelector("[data-tb-pause]").addEventListener("click", pause);
    container.querySelector("[data-tb-replay]").addEventListener("click", () => {
      reset();
      play();
    });
    container.querySelectorAll("[data-tb-push]").forEach((btn) => {
      btn.addEventListener("click", () => setInstruction(btn.dataset.tbPush, "push"));
    });
    container.querySelectorAll("[data-tb-sit]").forEach((btn) => {
      btn.addEventListener("click", () => setInstruction(btn.dataset.tbSit, "sit"));
    });
    if (htResumeBtn) htResumeBtn.addEventListener("click", () => resumeFromBreak());

    // Engine addition — mid-match personnel controls UI. Host sees both
    // sides and applies changes directly (it's the browser actually
    // running the sim). A participating team's own browser only sees its
    // OWN side and submits a request via onAction instead — the host's
    // poll loop applies it and the result reaches everyone (including the
    // requester) through the next broadcast frame, same as any other state
    // change. Full re-render on every change rather than incremental DOM
    // patching — the dropdown option lists always need to stay in sync
    // with substitutePlayer/changeFormation mutating homePins/awayPins/
    // benchBySide, and this panel is small.
    const subsEl = container.querySelector("[data-tb-subs]");
    function renderSubsPanel() {
      if (!subsEl || (!hostMode && !participantSide)) return;
      function sideBlock(side, label) {
        const sidePins = side === "home" ? homePins : awayPins;
        const bench = benchBySide[side] || [];
        const outOptions = sidePins
          .map((p) => `<option value="${escHtml(p.id)}">${escHtml(p.short)} (${escHtml(p.slot)})</option>`)
          .join("");
        const inOptions = bench
          .map((b) => `<option value="${escHtml(b.player)}">${escHtml(b.player)}</option>`)
          .join("");
        const teamFormation = side === "home" ? homeTeam.formation : awayTeam.formation;
        const formOptions = Object.keys(FORMATION_LAYOUTS)
          .map(
            (f) =>
              `<option value="${escHtml(f)}"${f === teamFormation ? " selected" : ""}>${escHtml(f)}</option>`
          )
          .join("");
        const subRow = bench.length
          ? `<select data-tb-sub-out="${side}">${outOptions}</select>
             <select data-tb-sub-in="${side}">${inOptions}</select>
             <button type="button" class="btn-ghost btn-sm" data-tb-sub-go="${side}">Sub</button>`
          : `<span class="muted" style="font-size:0.78rem">No bench players</span>`;
        return `<div class="tactic-subs-side">
          <span class="muted" style="font-size:0.78rem">${escHtml(label)}</span>
          ${subRow}
          <select data-tb-formation="${side}">${formOptions}</select>
          <button type="button" class="btn-ghost btn-sm" data-tb-formation-go="${side}">Change</button>
        </div>`;
      }
      const sides = hostMode ? ["home", "away"] : [participantSide];
      subsEl.innerHTML = sides.map((s) => sideBlock(s, s === "home" ? "Home" : "Away")).join("");
      subsEl.querySelectorAll("[data-tb-sub-go]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const side = btn.dataset.tbSubGo;
          const outSel = subsEl.querySelector(`[data-tb-sub-out="${side}"]`);
          const inSel = subsEl.querySelector(`[data-tb-sub-in="${side}"]`);
          if (!outSel || !inSel || !inSel.value) return;
          if (hostMode) {
            if (substitutePlayer(side, outSel.value, inSel.value)) renderSubsPanel();
          } else if (requestAction) {
            btn.disabled = true;
            requestAction({ type: "substitute", side, out_pin_id: outSel.value, bench_player: inSel.value });
          }
        });
      });
      subsEl.querySelectorAll("[data-tb-formation-go]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const side = btn.dataset.tbFormationGo;
          const sel = subsEl.querySelector(`[data-tb-formation="${side}"]`);
          const current = side === "home" ? homeTeam.formation : awayTeam.formation;
          if (!sel || !sel.value || sel.value === current) return;
          if (hostMode) {
            if (changeFormation(side, sel.value)) renderSubsPanel();
          } else if (requestAction) {
            btn.disabled = true;
            requestAction({ type: "formation", side, formation: sel.value });
          }
        });
      });
    }
    renderSubsPanel();

    function fmtUnit(v) {
      const n = Number(v);
      return Number.isFinite(n) ? n.toFixed(2) : "—";
    }
    function prematchUnitsLine(unit) {
      const u = unit || {};
      return `Atk ${fmtUnit(u.attack ?? u.attacking_effectiveness)} · Mid ${fmtUnit(u.midfield)} · Def ${fmtUnit(u.defence ?? u.defensive_unit)} · Fin ${fmtUnit(u.finishing ?? u.finishing_threat)}`;
    }
    function prematchXiList(team) {
      const rows = (team.lineup || []).slice(0, 11);
      if (!rows.length) return `<li class="muted">Lineup unavailable</li>`;
      return rows
        .map(
          (r) =>
            `<li><span class="slot">${escHtml(r.slot || "")}</span><span>${escHtml(r.player || "")}</span></li>`
        )
        .join("");
    }
    function renderPrematch() {
      if (!prematchOverlay || !prematchBody) return;
      prematchBody.innerHTML = `
        <h3 style="text-align:center;margin:0 0 0.25rem">Pre-match</h3>
        <p class="muted" style="text-align:center;margin:0 0 0.75rem">${escHtml(homeTeam.name)} vs ${escHtml(awayTeam.name)}</p>
        <div class="prematch-grid">
          <div class="prematch-side">
            <h4>${escHtml(homeTeam.name)}</h4>
            <p class="prematch-units">${escHtml(homeTeam.formation || "")} · ${prematchUnitsLine(unitHome)}</p>
            <ul class="prematch-xi">${prematchXiList(homeTeam)}</ul>
          </div>
          <div class="prematch-side">
            <h4>${escHtml(awayTeam.name)}</h4>
            <p class="prematch-units">${escHtml(awayTeam.formation || "")} · ${prematchUnitsLine(unitAway)}</p>
            <ul class="prematch-xi">${prematchXiList(awayTeam)}</ul>
          </div>
        </div>
        <div style="text-align:center;margin-top:0.85rem">
          <button type="button" class="btn-primary" data-tb-kickoff>Start match</button>
        </div>`;
      prematchOverlay.hidden = false;
      const kickBtn = prematchBody.querySelector("[data-tb-kickoff]");
      if (kickBtn) {
        kickBtn.addEventListener("click", () => {
          prematchOverlay.hidden = true;
          play();
        });
      }
    }

    reset();
    if (viewerMode) {
      // Start smooth follow loop; frames arrive via applyBroadcastState
      playing = false;
      lastTs = 0;
      raf = requestAnimationFrame(tick);
    } else if (showPrematch) {
      renderPrematch();
    } else if (opts.autoplay) {
      play();
    }

    // Engine addition — mid-match personnel controls (host-side only; a
    // substitution/formation change made here gets picked up by viewers
    // through the next broadcast frame's pin identity fields, same as any
    // other target/state change).
    function getBench(side) {
      return (benchBySide[side] || []).map((b) => b.player);
    }

    function substitutePlayer(side, outPinId, benchPlayerName) {
      const pin = pinById.get(outPinId);
      if (!pin || pin.side !== side) return false;
      const bench = benchBySide[side] || [];
      const idx = bench.findIndex((b) => b.player === benchPlayerName);
      if (idx === -1) return false;
      const incoming = bench[idx];
      // Outgoing player takes the vacated bench spot — same shape as the
      // one being filled, so a sub can be reversed later if needed.
      bench.splice(idx, 1, { player: pin.player, stats: pin.stats });
      pin.player = incoming.player;
      pin.short = shortName(incoming.player);
      pin.label = initials(incoming.player);
      pin.stats = mergeStats(pin.roleFilter || pin.slot, incoming.stats || {});
      const el = pinEls.get(pin.id);
      if (el) {
        el.title = `${pin.player} (${pin.slot}) — click to favor`;
        const labelEl = el.querySelector(".pin-label");
        if (labelEl) labelEl.textContent = pin.label;
      }
      return true;
    }

    function applyFormationSlot(pin, slot, coord) {
      pin.slot = slot;
      pin.role = roleOf(slot);
      pin.roleFilter = "";
      pin.baseX = coord[0];
      pin.baseDepth = coord[1];
      pin.stats = mergeStats(slot, pin.stats);
    }

    function changeFormation(side, newFormation) {
      const layout = FORMATION_LAYOUTS[newFormation];
      if (!layout) return false;
      const sidePins = side === "home" ? homePins : awayPins;
      const newSlots = Object.keys(layout);
      const byRole = new Map();
      for (const slot of newSlots) {
        const role = roleOf(slot);
        if (!byRole.has(role)) byRole.set(role, []);
        byRole.get(role).push(slot);
      }
      const assigned = new Set();
      const usedSlots = new Set();
      // First pass: keep each pin on a same-role slot if one's free — a CB
      // stays a CB, a winger stays a winger, no positions reshuffled just
      // because the formation label changed.
      for (const pin of sidePins) {
        const candidates = byRole.get(pin.role) || [];
        const freeSlot = candidates.find((s) => !usedSlots.has(s));
        if (freeSlot) {
          usedSlots.add(freeSlot);
          assigned.add(pin.id);
          applyFormationSlot(pin, freeSlot, layout[freeSlot]);
        }
      }
      // Second pass: whatever's left (role counts differ between the old
      // and new formation, e.g. 4-4-2 -> 4-3-3) fills remaining slots in
      // whatever order — a coarser fallback, but every pin still lands on
      // a valid slot.
      const leftoverSlots = newSlots.filter((s) => !usedSlots.has(s));
      const leftoverPins = sidePins.filter((p) => !assigned.has(p.id));
      leftoverPins.forEach((pin, i) => {
        const slot = leftoverSlots[i];
        if (slot) applyFormationSlot(pin, slot, layout[slot]);
      });
      if (side === "home") homeTeam.formation = newFormation;
      else awayTeam.formation = newFormation;
      return true;
    }

    return {
      play,
      pause,
      reset,
      getScore: () => ({ homeGoals: homeScore, awayGoals: awayScore }),
      getMatchLog: getMatchLogPayload,
      getOobStats: () => ({ ...oobStats }),
      getCornerStats: () => ({ ...cornerStats, delivery: { ...cornerStats.delivery } }),
      getFkStats: () => ({ ...fkStats }),
      getShortCornerDiag: () => ({ ...shortCornerDiag, samples: shortCornerDiag.samples.slice() }),
      getDecisionDiag: () => ({ samples: decisionDiag.samples.slice() }),
      getPossessionCounts: () => ({ ...possessionCounts }),
      setSpeed: (v) => {
        speed = clamp(Number(v) || 0.5, 0.05, 100);
      },
      getBroadcastState,
      applyBroadcastState,
      getBroadcastFrame: getBroadcastState,
      applyFrame: applyBroadcastState,
      getBench,
      substitutePlayer,
      changeFormation,
      startMirrorLoop: () => {
        if (!viewerMode) return;
        playing = false;
        lastTs = 0;
        if (!raf) raf = requestAnimationFrame(tick);
      },
      destroy: () => {
        pause();
        clearTimers();
        if (raf) cancelAnimationFrame(raf);
        raf = 0;
      },
    };
  }

  function escHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function enrichTeamFromProfiles(team, profile) {
    if (!team) return team;
    const players = profile?.players || [];
    const byName = new Map(players.map((p) => [p.player, p]));
    const extended = profile?.extended || {};
    const lineup = (team.lineup || []).map((row) => {
      const stats = byName.get(row.player) || row.stats || {};
      return { ...row, stats };
    });
    return {
      ...team,
      lineup,
      _unit: {
        pressing_intensity: extended.pressing_intensity,
        press_resistance: extended.press_resistance,
        attacking_effectiveness: extended.attacking_effectiveness,
        finishing_threat: extended.finishing_threat,
        defensive_unit: extended.defensive_unit,
        xga_suppression: extended.xga_suppression,
        chance_creation: extended.chance_creation,
        possession_control: extended.possession_control,
        aerial_defence: extended.aerial_defence,
        creation: extended.creation ?? extended.chance_creation,
        attack: extended.attack ?? (extended.units || {}).attack,
        defence: extended.defence ?? (extended.units || {}).defence,
        midfield: extended.midfield ?? (extended.units || {}).midfield,
        midfield_defence: (extended.units || {}).midfield_defence,
        finishing: (extended.units || {}).finishing ?? extended.finishing,
        goalkeeper: (extended.units || {}).goalkeeper,
      },
    };
  }

  function optsFromReport(report, matchup) {
    const mu = matchup || report?.matchup || {};
    const projection = report?.projection || report?.monte_carlo || {};
    const sample = report?.sample_match || {};
    const profiles = report?.profiles || {};
    const xg = projection.expected_xg || {};
    const home = enrichTeamFromProfiles(mu.home, profiles.home);
    const away = enrichTeamFromProfiles(mu.away, profiles.away);
    return {
      home,
      away,
      live: true,
      organicGoals: true,
      xgHome: xg.home ?? sample?.home?.xg,
      xgAway: xg.away ?? sample?.away?.xg,
      unitHome: home?._unit || {},
      unitAway: away?._unit || {},
      seed: hashSeed(`${mu.home?.name}-${mu.away?.name}-organic`),
    };
  }

  function renderWatchCard() {
    return `
      <section class="card tactic-watch-card" style="margin-top:1rem" data-watch-card>
        <h2>Watch match</h2>
        <p class="muted" style="margin:0 0 0.75rem">Interactive tactic-board match — pin goals are the score you see.</p>
        <div class="btn-stack">
          <button type="button" class="btn-primary" data-watch-match-btn>Watch</button>
        </div>
        <div data-tactic-mount style="margin-top:0.85rem" hidden></div>
      </section>`;
  }

  function wireWatchCard(root, report, matchup, overrides) {
    const card = root.querySelector("[data-watch-card]");
    if (!card) return null;
    const btn = card.querySelector("[data-watch-match-btn]");
    const mount = card.querySelector("[data-tactic-mount]");
    let board = null;
    const baseOpts = { ...optsFromReport(report, matchup), ...(overrides || {}) };

    const start = (autoplay) => {
      mount.hidden = false;
      if (board) board.destroy();
      board = createBoard(mount, { ...baseOpts, autoplay });
      btn.textContent = "Replay from start";
    };

    btn.addEventListener("click", () => start(true));

    if (global.location?.hash === "#watch") {
      start(true);
    }
    return { start };
  }

  function wireMatchdayWatch(root, session) {
    const card = root.querySelector("[data-watch-card]");
    if (!card || !session) return;
    const result = session.result || {};
    const score = String(result.score || "0-0").split("-");
    const report = session.report || result.report;
    let opts;
    if (report) {
      opts = optsFromReport(report);
      // Matchday result already saved — replay that scoreline
      opts.live = false;
      opts.organicGoals = false;
      opts.forceReplayScore = true;
      opts.homeGoals = result.home_goals ?? (parseInt(score[0], 10) || 0);
      opts.awayGoals = result.away_goals ?? (parseInt(score[1], 10) || 0);
      opts.seed = hashSeed(`${session.fixture_id}-${result.score}`);
    } else {
      opts = {
        home: session.team_a,
        away: session.team_b,
        live: false,
        forceReplayScore: true,
        homeGoals: result.home_goals ?? (parseInt(score[0], 10) || 0),
        awayGoals: result.away_goals ?? (parseInt(score[1], 10) || 0),
        xgHome: result.expected_xg?.home,
        xgAway: result.expected_xg?.away,
        seed: hashSeed(`${session.fixture_id}-${result.score}`),
      };
    }
    const btn = card.querySelector("[data-watch-match-btn]");
    const mount = card.querySelector("[data-tactic-mount]");
    let board = null;
    btn.addEventListener("click", () => {
      mount.hidden = false;
      if (board) board.destroy();
      board = createBoard(mount, { ...opts, autoplay: true });
      btn.textContent = "Replay from start";
    });
  }

  function parseScore(score) {
    const parts = String(score || "0-0").split(/[-–]/);
    return {
      homeGoals: parseInt(parts[0], 10) || 0,
      awayGoals: parseInt(parts[1], 10) || 0,
    };
  }

  function stubTeam(name, formation) {
    return {
      name: name || "Team",
      formation: formation || "4-3-3 flat",
      lineup: [],
    };
  }

  /**
   * Open a live or replay board from tournament fixture metadata / board payload.
   * Live Matchday host uses meta.hostMode + meta.onBroadcast; viewers use meta.viewerMode.
   */
  async function openTournamentWatch(mount, meta, { apiFetch } = {}) {
    if (!mount) return null;
    mount.hidden = false;
    mount.innerHTML = `<p class="muted">Loading tactic board…</p>`;

    const boardPayload = meta.boardPayload || meta.board || null;
    const onDone = meta.onFullTime || meta.onComplete || null;
    let opts;

    if (boardPayload) {
      const b = boardPayload;
      const homeTeam = b.home || stubTeam(meta.home);
      const awayTeam = b.away || stubTeam(meta.away);
      opts = {
        home: homeTeam,
        away: awayTeam,
        unitHome: b.unit_home || b.unitHome || homeTeam._unit || {},
        unitAway: b.unit_away || b.unitAway || awayTeam._unit || {},
        live: !meta.viewerMode,
        organicGoals: !meta.viewerMode,
        showPrematch: meta.showPrematch !== false && !meta.viewerMode,
        autoplay: meta.showPrematch === false && meta.autoplay !== false && !meta.viewerMode,
        seed: meta.seed || hashSeed(`${meta.matchId || b.match_id || ""}-live`),
        hostMode: Boolean(meta.hostMode),
        viewerMode: Boolean(meta.viewerMode),
        hideControls: Boolean(meta.hideControls) || Boolean(meta.viewerMode),
        isKnockout: Boolean(meta.isKnockout || meta.knockout),
        isFinal: Boolean(meta.isFinal),
        aggContext: meta.aggContext || null,
        onBroadcast: meta.onBroadcast || null,
        broadcastIntervalMs: meta.broadcastIntervalMs,
        onComplete: onDone,
        onScore: meta.onScore,
        mobileBroadcast: Boolean(meta.mobileBroadcast),
      };
    } else {
      opts = {
        home: stubTeam(meta.home),
        away: stubTeam(meta.away),
        live: false,
        forceReplayScore: Boolean(meta.score),
        ...parseScore(meta.score),
        xgHome: meta.xgHome,
        xgAway: meta.xgAway,
        seed: hashSeed(`${meta.matchId || meta.experimentId || ""}-${meta.score}`),
        autoplay: true,
        onComplete: onDone,
        mobileBroadcast: Boolean(meta.mobileBroadcast),
      };

      if (meta.experimentId && typeof apiFetch === "function") {
        try {
          const data = await apiFetch(`/api/experiments/${meta.experimentId}`);
          const report = data?.experiment?.report;
          if (report) {
            const fromRep = optsFromReport(report, report.matchup);
            opts = {
              ...fromRep,
              live: false,
              organicGoals: false,
              forceReplayScore: true,
              mobileBroadcast: Boolean(meta.mobileBroadcast),
              ...parseScore(meta.score || "0-0"),
              autoplay: true,
              onComplete: onDone,
            };
            if (meta.score) {
              const sc = parseScore(meta.score);
              opts.homeGoals = sc.homeGoals;
              opts.awayGoals = sc.awayGoals;
            }
          }
        } catch (_) {
          /* keep stub teams */
        }
      }
    }

    if (meta.live && !boardPayload) {
      opts.live = true;
      opts.organicGoals = true;
      opts.forceReplayScore = false;
      delete opts.homeGoals;
      delete opts.awayGoals;
    }

    return createBoard(mount, opts);
  }

  function buildMatchScript() {
    return { events: [], totalDuration: MATCH_WATCH_SECONDS, homeGoals: 0, awayGoals: 0 };
  }

  global.TacticBoard = {
    createBoard,
    buildMatchScript,
    optsFromReport,
    renderWatchCard,
    wireWatchCard,
    wireMatchdayWatch,
    openTournamentWatch,
    parseScore,
    stubTeam,
    FORMATION_LAYOUTS,
    MATCH_WATCH_SECONDS,
    /** Empty match-log shape for clients posting complete-from-board. */
    emptyMatchLogShape: () => ({
      goals: [],
      assists: [],
      events: [],
      counts: {
        home: {
          goals: 0,
          assists: 0,
          shots: 0,
          big_chances: 0,
          offsides: 0,
          passes_broken: 0,
          dribbles_won: 0,
          dribbles_lost: 0,
          saves: 0,
          blocked_shots: 0,
          possessions: 0,
          turnovers: 0,
          chances_created: 0,
          xg: 0,
        },
        away: {
          goals: 0,
          assists: 0,
          shots: 0,
          big_chances: 0,
          offsides: 0,
          passes_broken: 0,
          dribbles_won: 0,
          dribbles_lost: 0,
          saves: 0,
          blocked_shots: 0,
          possessions: 0,
          turnovers: 0,
          chances_created: 0,
          xg: 0,
        },
      },
      spells: [],
      possession: { home: 50, away: 50 },
      xg: { home: 0, away: 0 },
    }),
  };
})(typeof window !== "undefined" ? window : globalThis);
