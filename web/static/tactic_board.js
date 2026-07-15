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
   * Decision layer cadence (wall-seconds at 1×). Shape targets refresh here —
   * animation never invents new targets mid-frame.
   */
  const DECISION_INTERVAL_MIN = 0.22;
  const DECISION_INTERVAL_MAX = 0.48;
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
    if (/^(AM|CAM)$/.test(s)) return "AM";
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
    return {
      dribbles90: num(s.dribbles90, g.dribbles90),
      // 0% completion is never real match data — fall back to role norms
      dribble_pct: numPos(s.dribble_pct, g.dribble_pct),
      key_passes90: num(s.key_passes90, g.key_passes90),
      xa90: num(s.xa90, g.xa90),
      xg90: numPos(s.xg90 ?? s.npxg90, g.xg90),
      shots90: shots,
      shots_on_target90: num(s.shots_on_target90, Math.max(0.4, shots * 0.4)),
      goals90: num(s.goals90, 0),
      aerials_won90: num(s.aerials_won90, 0),
      aerials_won_pct: numPos(s.aerials_won_pct, role === "ST" ? 48 : 45),
      tackles90: num(s.tackles90, g.tackles90),
      interceptions90: num(s.interceptions90, g.interceptions90),
      pass_pct: numPos(s.pass_pct, g.pass_pct),
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

    const live = Boolean(opts.live ?? opts.organicGoals ?? opts.mode === "live");
    const viewerMode = Boolean(opts.viewerMode);
    const hostMode = Boolean(opts.hostMode) && !viewerMode;
    const hideControls = Boolean(opts.hideControls) || viewerMode;
    /** Knockout ties: level after 90 → ET (2×15) → pens if still level. Group matches ignore this. */
    const isKnockout = Boolean(opts.isKnockout || opts.knockout) && live && !viewerMode;
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

    container.innerHTML = `
      <div class="tactic-board" data-tactic-board>
        <div class="tactic-scorebar">
          <span class="team-name home">${escHtml(homeTeam.name)}</span>
          <span class="tactic-score" data-tb-score>0 – 0</span>
          <span class="team-name away">${escHtml(awayTeam.name)}</span>
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
        <div class="tactic-meta">
          <span data-tb-clock>0'</span>
          <span class="tactic-ticker" data-tb-phase>Kick-off</span>
        </div>
        <div class="tactic-stage">
          <div class="tactic-pitch-wrap">
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
            </div>
          </div>
          <aside class="tactic-commentary" aria-label="Match commentary">
            <div class="tactic-commentary-head">Commentary</div>
            <div class="tactic-commentary-list" data-tb-feed></div>
          </aside>
        </div>
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
          <button type="button" class="btn-primary btn-sm" data-tb-play>Play</button>
          <button type="button" class="btn-ghost btn-sm" data-tb-pause>Pause</button>
          <button type="button" class="btn-ghost btn-sm" data-tb-replay>Replay</button>
          <label class="tactic-speed muted">
            Speed
            <select data-tb-speed>
              <option value="0.5" selected>0.5×</option>
              <option value="0.75">0.75×</option>
              <option value="1">1×</option>
              <option value="1.5">1.5×</option>
              <option value="2">2×</option>
              <option value="3">3×</option>
            </select>
          </label>
        </div>
        <div class="tactic-instructions" data-tb-instructions ${hideControls ? "hidden" : ""}>
          <span class="muted" style="font-size:0.78rem">Instructions</span>
          <button type="button" class="btn-ghost btn-sm" data-tb-push="home">Home push</button>
          <button type="button" class="btn-ghost btn-sm" data-tb-sit="home">Home sit</button>
          <button type="button" class="btn-ghost btn-sm" data-tb-push="away">Away push</button>
          <button type="button" class="btn-ghost btn-sm" data-tb-sit="away">Away sit</button>
        </div>
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
    const feedEl = container.querySelector("[data-tb-feed]");
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
      el.className = `tactic-pin ${pin.side}`;
      el.dataset.pinId = pin.id;
      el.title = `${pin.player} (${pin.slot}) — click to favor`;
      el.innerHTML = `<span class="pin-dot"></span><span class="pin-label">${escHtml(pin.label)}</span>`;
      el.style.left = `${pin.rx}%`;
      el.style.top = `${pin.ry}%`;
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
        dot.style.left = `${pin.left}%`;
        dot.style.top = `${pin.top}%`;
        pitch.appendChild(dot);
        debugDotEls.set(pin.id, dot);
      }
    });

    pitch.addEventListener("click", (ev) => {
      if (viewerMode || finished || !playing) return;
      const rect = pitch.getBoundingClientRect();
      const left = ((ev.clientX - rect.left) / rect.width) * 100;
      const top = ((ev.clientY - rect.top) / rect.height) * 100;
      triggerZoneSwitch(left, top);
    });

    let playing = false;
    let speed = 0.5;
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
    /**
     * Per-team finishing form for this match (drawn once at reset/kickoff).
     * Multiplies shot conversion; does not invent goals without shots.
     * Mixture biased by unit finishing (avg ≈ cold 8% / hot 12% / normal 80%).
     */
    let finishingForm = { home: 1, away: 1 };
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
    let shapePulse = 0;
    /** Smoothed 0–1 defensive box/chance pressure per side (gradual drop-back). */
    const defPressureSmooth = { home: 0, away: 0 };
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
      matchLog.events.push(entry);
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
    }

    function estimateChanceXg(carrier, chanceType) {
      const d = possessionDepth(carrier);
      const create = sideCreate(carrier.side);
      const boxed = inPenaltyBox(carrier);
      const near = nearPenaltyBox(carrier);
      const ready = boxOccupationReady(carrier.side);
      let kind = chanceType;
      if (kind === "big_chance" && (!boxed || !ready)) kind = "shot";
      let base;
      let floor;
      let ceil;
      if (boxed && ready && kind === "big_chance") {
        base = 0.28 + carrier.stats.xg90 * 0.2 + create * 0.07;
        floor = 0.16 + create * 0.05;
        ceil = 0.68;
      } else if (boxed && ready) {
        base = 0.15 + carrier.stats.xg90 * 0.14 + create * 0.05;
        floor = 0.1 + create * 0.03;
        ceil = 0.42;
      } else if (boxed && !ready) {
        base = 0.1 + carrier.stats.xg90 * 0.06;
        floor = 0.07;
        ceil = 0.18;
      } else if (near) {
        base = 0.07 + carrier.stats.xg90 * 0.05 + create * 0.02;
        floor = 0.04;
        ceil = 0.14;
      } else {
        base = 0.035 + carrier.stats.xg90 * 0.03;
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
      if (isMaestroPin(carrier) && volMul < 0.98) {
        xg *= clamp(1.06 + (1 - volMul) * 0.14, 1, 1.2);
      }
      // Elite ST/W/AM big looks: nudge chance xG toward their season shot quality
      if (isAttackFinisher(carrier) && boxed && ready) {
        const fq = finisherQuality(carrier);
        xg *= clamp(1 + (fq - 0.5) * 0.12, 0.94, 1.14);
        ceil = Math.min(0.75, ceil + (fq >= 0.7 ? 0.04 : 0));
      }
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

    /** Hide GOAL!/OFFSIDE! overlay (display:grid otherwise beats [hidden]). */
    function clearFlash() {
      flashTimer = 0;
      if (flashEl) {
        flashEl.hidden = true;
        flashEl.textContent = "";
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
      ballEl.style.left = `${ball.left}%`;
      ballEl.style.top = `${ball.top}%`;
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
      ballEl.style.left = `${ball.left}%`;
      ballEl.style.top = `${ball.top}%`;
      ballTween = 1;
      ballCtrl = null;

      if (flight.outcome === "intercept" || flight.outcome === "steal") {
        const def = flight.interceptor;
        clearLastPasser();
        if (def) {
          archiveSpell(flight.outcome === "steal" ? "press" : "intercept");
          spell = null;
          giveBall(def, flight.comment || `${def.short} intercepts`);
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
        carrierId = to.id;
        possession = to.side;
        ballAttached = true;
        to._dribbleStreak = 0;
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
        if (opp) giveBall(opp, flight.comment || `${opp.short} wins it`);
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
        say(`Blocked! ${blocker?.short || "defender"} gets across`, 1.3);
        spell = null;
        if (blocker) giveBall(blocker, `${blocker.short} clears the danger`);
        actionTimer = 0.65;
        return;
      }

      if (flight.outcome === "wide") {
        const defPin = flight.interceptor;
        clearLastPasser();
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
            (c.role === "ST" || c.role === "AM") &&
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
          doShot(c, false);
        }
        return;
      }
      if (pendingRestart && matchMinute >= pendingRestart.at && ballTween >= 1 && !ballFlight) {
        const side = pendingRestart.side;
        pendingRestart = null;
        clearFlash();
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
        for (const pin of allPins) {
          const pct = toPitchPct(pin.side, pin.baseX, pin.baseDepth);
          pin.tx = pct.left;
          pin.ty = pct.top;
          pin._pathCtrl = null;
          pin.lockUntil = 0;
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
        const quality = 0.4 + (opp.stats.tackles90 || 0) * 0.08 + (opp.stats.interceptions90 || 0) * 0.04;
        total += proximity * proximity * closing * quality;
      }
      return total;
    }

    function teammates(pin) {
      return pinsOf(pin.side).filter((p) => p.id !== pin.id && p.role !== "GK");
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
        doPass(carrier, prog, throughBallLegal(carrier, prog) ? "through" : "pass");
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
        const d = fromPitchPct(p.side, p.left, p.top).depth;
        return d > 0.78 && (p._running || p.lockUntil > matchMinute);
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

    function isAttackFinisher(pin) {
      return Boolean(pin && (pin.role === "ST" || pin.role === "W" || pin.role === "AM"));
    }

    /** Quality chance gate: ≥2 in box OR 1 in box + arriving runner; urgency/matchup can soften. */
    function boxOccupationReady(side) {
      const boxed = countBoxAttackers(side);
      const arriving = countArrivingRunners(side);
      if (boxed >= 2 || (boxed >= 1 && arriving >= 1)) return true;
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
        for (const s of progressive) {
          if (canPlayForward(carrier, s.m, stage, depth) || isMidRole(s.m.role) || s.m.role === "FB") {
            return s.m;
          }
        }
      }
      for (const s of shortClear) {
        if (canPlayForward(carrier, s.m, stage, depth) || isMidRole(s.m.role) || isDefRole(s.m.role)) {
          return s.m;
        }
      }
      if (shortClear.length) return shortClear[0].m;

      scored.sort((a, b) => b.score - a.score);
      for (const s of scored) {
        if (wouldPassBeOffside(carrier, s.m)) continue;
        if (s.d > 28 && s.nLane >= 1) continue;
        if (isCrossFieldSwitch(carrier, s.m) && !isJustifiedSwitch(carrier, s.m)) continue;
        if (s.d > 32 && Math.abs(s.m.left - carrier.left) > 28) continue;
        if (canPlayForward(carrier, s.m, stage, depth) || isMidRole(s.m.role) || isDefRole(s.m.role)) {
          return s.m;
        }
      }
      return scored[0]?.m || mates[0];
    }

    function longBallTarget(carrier) {
      const runners = teammates(carrier)
        .filter((m) => isFwdRole(m.role) || m.role === "AM")
        .filter((m) => !wouldPassBeOffside(carrier, m));
      if (!runners.length) return null;
      runners.sort(
        (a, b) =>
          b.stats.xg90 * 1.4 + b.stats.xa90 * 1.15 - (a.stats.xg90 * 1.4 + a.stats.xa90 * 1.15) + rng() * 0.2
      );
      return runners[0];
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
            roleBias -
            dist(carrier, m) * 0.03 +
            rng() * 0.3,
        };
      });
      scored.sort((a, b) => b.score - a.score);
      return scored[0]?.m || mates[0];
    }

    function shooterTarget(carrier) {
      const mates = teammates(carrier).filter((m) => m.role === "ST" || m.role === "AM" || m.role === "W");
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
          b.stats.xg90 * 1.55 +
          b.stats.shots90 * 0.16 +
          boxB +
          fb +
          roleB +
          fqB -
          (a.stats.xg90 * 1.55 + a.stats.shots90 * 0.16 + boxA + fa + roleA + fqA)
        );
      });
      const best = mates[0];
      if (inPenaltyBox(carrier) && carrier.stats.xg90 >= best.stats.xg90 * 0.7) return carrier;
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
      const mates = teammates(carrier).filter(
        (m) => m.role === "ST" || m.role === "AM" || (m.role === "W" && Math.abs(m.left - carrier.left) > 18)
      );
      if (!mates.length) return progressiveTarget(carrier);
      const fromLeft = carrier.left < 50;
      mates.sort((a, b) => {
        const aNear = fromLeft ? a.left <= 52 : a.left >= 48;
        const bNear = fromLeft ? b.left <= 52 : b.left >= 48;
        const preferNear = mode === "near" || mode === "cutback";
        const lane = preferNear ? (bNear ? 1 : 0) - (aNear ? 1 : 0) : (aNear ? 1 : 0) - (bNear ? 1 : 0);
        return lane * 2 + (b.stats.xg90 - a.stats.xg90) * 1.55 + (rng() - 0.5) * 0.2;
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
          (m.role === "ST" || m.role === "AM" ? m.stats.xg90 * 0.55 : 0);
        const space = m._running ? 0.9 : 0;
        return { m, score: hub + centralBias + create + space - dist(carrier, m) * 0.02 + rng() * 0.4 };
      });
      scored.sort((a, b) => b.score - a.score);
      return scored[0].m;
    }

    function throughRunner(carrier, stage, depth) {
      const runners = teammates(carrier)
        .filter((m) => m.role === "ST" || m.role === "AM" || m.role === "W")
        .filter((m) => canPlayForward(carrier, m, stage, depth))
        .filter((m) => throughBallLegal(carrier, m));
      if (!runners.length) return null;
      runners.sort((a, b) => {
        const attrA = throughBallAttractive(carrier, a) ? 2.4 : 0;
        const attrB = throughBallAttractive(carrier, b) ? 2.4 : 0;
        return (
          attrB +
          b.stats.xg90 * 1.45 +
          b.stats.xa90 * 0.75 -
          Math.abs(b.left - 50) * 0.01 -
          (attrA + a.stats.xg90 * 1.45 + a.stats.xa90 * 0.75) +
          rng() * 0.25
        );
      });
      return runners[0];
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

      let wCentral =
        1.15 +
        create * 0.85 +
        atk * 0.25 +
        st.key_passes90 * 0.28 +
        st.pass_pct * 0.004 +
        (carrier.role === "CM" || carrier.role === "AM" ? 0.95 : 0.15) +
        (hasCM ? 0.35 : -0.4) +
        (centralBall ? 0.35 : -0.15) +
        Math.max(0, ad) * 0.55;
      if (depth < 0.5) wCentral += 0.25;
      if (stage === "PROGRESSING") wCentral += 0.2;
      if (urg >= 0.85) wCentral += 0.45 + Math.max(0, ad) * 0.35;

      let wSwitch = hasW
        ? 0.35 + create * 0.35 + st.xa90 * 0.55 + (centralBall ? 0.45 : 0.08) + (carrier.role === "CM" ? 0.25 : 0)
        : 0.04;
      if (bestFlankEdge > 0.15 && (edgeL < -0.05 || edgeR < -0.05)) wSwitch += 0.55 + bestFlankEdge * 0.6;
      if (depth >= 0.35 && depth < 0.72) wSwitch += 0.12;

      let wWing =
        carrier.role === "W" || carrier.role === "FB"
          ? 0.95 + st.dribbles90 * 0.4 + st.xa90 * 1.15 + (isWideChannel(carrier) ? 0.55 : 0.1)
          : hasW
            ? 0.4 + create * 0.35 + (depth > 0.42 ? 0.3 : 0)
            : 0.08;
      if (isWideChannel(carrier) && depth >= 0.55) wWing += 0.65;
      wWing += bestFlankEdge * 0.75;
      if (carrier.role === "W" || carrier.role === "FB") {
        wWing += flankMatchupEdge(carrier.side, pinFlank(carrier)) * 0.9;
      }

      let wCut =
        carrier.role === "W"
          ? 0.75 + st.dribbles90 * 0.32 + st.xg90 * 0.75 + (isWideChannel(carrier) ? 0.45 : 0)
          : carrier.role === "AM"
            ? 0.35 + st.dribbles90 * 0.16 + st.xg90 * 0.2
            : 0.12;
      if (depth >= 0.5) wCut += 0.2;
      if (ad > 0.1 && isFinalThirdStage(stage)) wCut += 0.35;

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
        const far = oppositeFlankWinger(carrier);
        if (far && isJustifiedSwitch(carrier, far)) {
          say(`Switch — ${far.short}`, 1.2);
          doPass(carrier, far, "switch");
          return true;
        }
        // Unjustified: prefer local FB/CM/supporting winger
        const local = teammates(carrier)
          .filter((m) => !isCrossFieldSwitch(carrier, m) && (m.role === "CM" || m.role === "FB" || m.role === "W" || m.role === "ST"))
          .filter((m) => isLocalTriangleOption(carrier, m) || dist(carrier, m) < 20)
          .sort((a, b) => scoreAttackSequence(carrier, b) - scoreAttackSequence(carrier, a));
        if (local[0]) {
          doPass(carrier, local[0], "pass");
          return true;
        }
        const cm = teammates(carrier).find((m) => m.role === "CM");
        if (cm) {
          doPass(carrier, cm, "pass");
          return true;
        }
      }

      if (pattern === "wing_carry") {
        if (carrier.role === "W" || carrier.role === "FB") {
          // Used to reroute straight back to decideWideFinalThird (cross/cutback/
          // recycle only) once deep+wide — exactly the situation this pattern
          // exists for, so it silently killed fullback/winger combination play
          // (decideFbWingLink below) whenever it would have mattered most.
          const flankEdge = flankMatchupEdge(carrier.side, pinFlank(carrier));
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
          if (carrier.role === "W") {
            const links = linkedOptions(carrier).filter((m) => canPlayForward(carrier, m, stage, depth) || isMidRole(m.role) || m.role === "FB");
            if (links.length && rng() < 0.72) {
              doPass(carrier, links[0], throughBallLegal(carrier, links[0]) ? "through" : "pass");
              return true;
            }
          }
          if (rng() < 0.32 + st.dribbles90 * 0.14 + (threat && threat.d < 9 ? 0.12 : 0.05)) {
            doDribble(carrier);
            return true;
          }
          if (rng() < 0.4 + st.dribbles90 * 0.04) {
            doCarry(carrier);
            return true;
          }
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
          if (
            depth >= 0.72 &&
            Math.abs(carrier.left - 50) < 28 &&
            rng() < 0.4 + st.xg90 * 0.45 + Math.max(0, ad) * 0.35 + urg * 0.08
          ) {
            if (!boxOccupationReady(carrier.side)) {
              const slip = throughRunner(carrier, stage, depth);
              if (slip && urg >= 0.7) {
                doPass(carrier, slip, "through");
                return true;
              }
              doPass(carrier, progressiveTarget(carrier), "pass");
              return true;
            }
            if (!inPenaltyBox(carrier) && (carrier.role === "AM" || st.xg90 > 0.28 || ad > 0.12)) {
              return driveIntoBox(carrier);
            }
            doShot(carrier, false);
            return true;
          }
          if (rng() < 0.5 + st.dribbles90 * 0.12) {
            const attackSign = carrier.side === "home" ? -1 : 1;
            const sideSign = carrier.left < 50 ? 1 : -1;
            const midX = clamp(carrier.left + sideSign * (6 + rng() * 5), 18, 82);
            const midY = clamp(carrier.top + attackSign * (2 + rng() * 2), 5, 95);
            const nx = clamp(lerp(midX, 50, 0.35) + (rng() - 0.5) * 2, 20, 80);
            const ny = clamp(carrier.top + attackSign * (3.5 + rng() * 2.5), 5, 95);
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
          const slip = throughRunner(carrier, stage, depth) || shooterTarget(carrier);
          if (slip.id !== carrier.id && rng() < 0.55 + urg * 0.12 + Math.max(0, ad) * 0.2) {
            doPass(carrier, slip, throughBallLegal(carrier, slip) ? "through" : "pass");
            return true;
          }
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
      {
        if (threat && threat.d < 9 && rng() < 0.32 + st.dribbles90 * 0.09) {
          doDribble(carrier);
          return true;
        }
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
        if (rng() < (carrier.role === "CM" ? 0.78 : 0.62)) {
          doPass(carrier, centralProgressTarget(carrier, stage, depth), "pass");
          return true;
        }
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
      if (forwardInFinalThird(carrier)) recycleW = 0;
      const pick = weightedPick([
        { id: "cross", w: Math.max(0.05, crossW) },
        { id: "cutback", w: cutbackW },
        { id: "recycle", w: recycleW },
      ]);

      if ((pick === "recycle" || (!ready && rng() < 0.55 - urg * 0.2)) && urg < 1.05) {
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
      const fromLeft = carrier.left < 50;
      const nearX = fromLeft ? 0.38 : 0.62;
      const farX = fromLeft ? 0.64 : 0.36;
      const cutX = fromLeft ? 0.44 : 0.56;
      for (const pin of teammates(carrier)) {
        if (pin.role !== "ST" && pin.role !== "AM") continue;
        const useNear =
          mode === "near" || mode === "cutback" ? pin.baseX < 0.5 === fromLeft : pin.baseX < 0.5 !== fromLeft;
        const tx = mode === "cutback" ? cutX : useNear ? nearX : farX;
        const depthWant = clamp(0.88 + (pin.role === "ST" ? 0.04 : 0.01), 0.85, 0.94);
        // Allow intentional box runs to 0.90+ when occupation state demands
        const safePct = toPitchPct(pin.side, tx, depthWant);
        pin.tx = safePct.left;
        pin.ty = safePct.top;
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
        defLine = clamp(0.2 + shift + pushSit * 0.035, 0.14, 0.4);
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

        defLine = clamp(0.14 + ballD * 0.2 - pushSit * 0.04, 0.1, 0.36);
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
      }
      return { defLine, midLine, atkLine, relBall, threeBack, boxThreat };
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
        const { defLine, midLine, atkLine, relBall, threeBack, boxThreat } = teamBlockLines(side, attacking);
        const pins = pinsOf(side);
        const pending = [];
        const boxedN = attacking ? countBoxAttackers(side) : 0;
        const deepOk = attacking && allowDeepRun(side);

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
            x = lerp(pin.baseX, relBall.x, 0.08);
          } else {
            if (lineKind === "def") depth = defLine + bias;
            else if (lineKind === "mid") depth = midLine + bias;
            else depth = atkLine + bias;
            x = pin.baseX + (pin.baseX - 0.5) * 0.02;

            if (attacking) {
              // --- Ideal positions by possession STATE (before ball attraction) ---
              if (atkStage === "BUILD_UP") {
                if (pin.role === "CB") depth = clamp(0.18 + bias, 0.14, 0.28);
                if (pin.role === "FB") depth = clamp(0.22 + bias, 0.16, 0.34);
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
                if (pin.role === "FB") depth = lerp(depth, midLine + 0.04, 0.45);
                if (pin.role === "CM") depth = lerp(depth, midLine + 0.06, 0.5);
                if (pin.role === "AM") {
                  // Pocket ahead of CMs, behind ST — not on the striker line.
                  // Was atkLine-0.02 for amCamStack (4-3-3 attacking), which the
                  // clamp below only pulled back to atkLine-0.04 — a ~2-4% depth
                  // gap from the striker, reading as the same line. Give it the
                  // same real separation as every other formation.
                  const pocketD = midLine + 0.1;
                  depth = lerp(depth, clamp(pocketD + bias, midLine + 0.04, atkLine - 0.04), 0.45);
                  const halfOsc = Math.sin(shapePulse * 0.65 + h * 2.8);
                  x = lerp(x, clamp(0.5 + halfOsc * 0.14, 0.32, 0.68), 0.35);
                }
                if (pin.role === "W") depth = lerp(depth, atkLine - 0.02, 0.4);
                if (pin.role === "ST") {
                  const offLine = defendingOffsideLine(pin.side);
                  const onsideDepth = offLine - (0.008 + h * 0.012);
                  depth = lerp(depth, Math.min(atkLine, onsideDepth), 0.4);
                }
              } else if (atkStage === "FINAL_THIRD") {
                // ST near/far post onside of last defender; LW half-space; RW far post/wide;
                // CM edge of box; AM pocket / half-spaces (deeper than ST unless 4-3-3 attacking);
                // FB hold width OR overlap (start when ball still central with CM)
                if (pin.role === "ST") {
                  const offLine = defendingOffsideLine(pin.side);
                  const onsideDepth = offLine - (0.008 + h * 0.012);
                  const ballWide = relBall.x < 0.32 || relBall.x > 0.68;
                  const nearPost = relBall.x < 0.5 ? 0.38 : 0.62;
                  const farPost = relBall.x < 0.5 ? 0.64 : 0.36;
                  const osc = (Math.sin(shapePulse * 0.9 + h * 3.5) + 1) * 0.5;
                  x = lerp(nearPost, farPost, osc);
                  depth = clamp(onsideDepth, midLine + 0.1, 0.9);
                  if (ballWide) x = lerp(x, relBall.x, 0.12);
                } else if (pin.role === "W") {
                  // Engine rebuild Phase 2 — was a pure sine wave of elapsed
                  // time picking touchline vs half-space regardless of
                  // pressure, lane, or teammate crowding. Score both real
                  // candidates and hold the better one (small hysteresis so
                  // it doesn't flicker every recompute when scores are close).
                  const touch = flank === "R" ? 0.93 : flank === "L" ? 0.07 : pin.baseX;
                  const half = flank === "R" ? 0.72 : flank === "L" ? 0.28 : 0.5;
                  const depthTouch = 0.72;
                  const depthHalf = 0.78;
                  const scoreTouch = scoreOpenSpace(pin, touch, depthTouch);
                  const scoreHalf = scoreOpenSpace(pin, half, depthHalf);
                  const hysteresis = 0.12;
                  const pickHalf = pin._wPrefHalf
                    ? scoreHalf > scoreTouch - hysteresis
                    : scoreHalf > scoreTouch + hysteresis;
                  pin._wPrefHalf = pickHalf;
                  x = pickHalf ? half : touch;
                  depth = clamp(pickHalf ? depthHalf : depthTouch, 0.66, 0.84);
                  pin._running = true;
                } else if (pin.role === "AM") {
                  const halfL = 0.36;
                  const halfR = 0.64;
                  const ballSideHalf = relBall.x < 0.5 ? halfL : halfR;
                  const oppHalf = relBall.x < 0.5 ? halfR : halfL;
                  const osc = (Math.sin(shapePulse * 0.85 + h * 3.1) + 1) * 0.5;
                  // Was two branches — amCamStack (4-3-3 attacking) deliberately stacked
                  // the AM at 0.68-0.84 depth, nearly the same line as ST (which sits
                  // ~0.8-0.9 here). Use the properly-separated pocket depth for every
                  // formation instead of just the non-stacked one.
                  x = lerp(ballSideHalf, oppHalf, osc * 0.55);
                  x = lerp(x, clamp(relBall.x + (relBall.x > 0.5 ? -0.08 : 0.08), 0.3, 0.7), 0.25);
                  // Edge of box / pocket — clearly deeper than ST near/far posts
                  depth = clamp(0.66 + bias + osc * 0.04, 0.58, 0.74);
                  pin._running = true;
                } else if (pin.role === "CM") {
                  x = lerp(pin.baseX, clamp(0.5 + (pin.baseX - 0.5) * 0.7, 0.28, 0.72), 0.4);
                  depth = clamp(0.7 + bias, 0.64, 0.78); // edge of box
                  pin._running = true;
                } else if (pin.role === "FB") {
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
                  // Overlap starts when ball still central with CM — BEFORE winger receives
                  if ((ballCentral && cmHasBall && sameFlankAsBall) || (atkPattern === "wing_carry" && sameFlankAsBall)) {
                    x = flank === "R" ? 0.92 : 0.08;
                    depth = clamp(0.76 + fbAttackThreat(pin) * 0.1, 0.68, 0.9);
                    pin._running = true;
                    pin._overlapRun = true;
                  } else if (oppFlank) {
                    // Opposite FB tucks
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
                if (pin.role === "ST") {
                  const offLine = defendingOffsideLine(pin.side);
                  const onsideDepth = offLine - (0.008 + h * 0.012);
                  const crashers = pins.filter((p) => p.role === "ST" || p.role === "W");
                  const idx = crashers.findIndex((p) => p.id === pin.id);
                  const nearPost = relBall.x < 0.5 ? 0.4 : 0.6;
                  const farPost = relBall.x < 0.5 ? 0.62 : 0.38;
                  x = idx % 2 === 0 ? nearPost : farPost;
                  depth = clamp(onsideDepth, midLine + 0.12, 0.92);
                } else if (pin.role === "AM") {
                  const halfL = 0.34;
                  const halfR = 0.66;
                  const ballSideHalf = relBall.x < 0.5 ? halfL : halfR;
                  const oppHalf = relBall.x < 0.5 ? halfR : halfL;
                  const osc = (Math.sin(shapePulse * 0.95 + h * 2.6) + 1) * 0.5;
                  // Was two branches — amCamStack (4-3-3 attacking) deliberately stacked
                  // the AM at 0.72-0.88 depth, nearly the same as ST's box-occupation
                  // depth (~midLine+0.12 to 0.92, often 0.8+). Use the properly-separated
                  // pocket depth for every formation instead of just the non-stacked one.
                  x = lerp(ballSideHalf, oppHalf, osc * 0.5);
                  x = lerp(x, clamp(relBall.x + (relBall.x > 0.5 ? -0.1 : 0.1), 0.28, 0.72), 0.3);
                  // Pocket / edge of box — under ST, not crashing same posts
                  depth = clamp(0.68 + bias + osc * 0.05, 0.6, 0.78);
                  pin._running = true;
                } else if (pin.role === "W") {
                  // Cutback lane — wide and slightly deeper than the six-yard
                  x = flank === "R" ? 0.9 : flank === "L" ? 0.1 : lerp(pin.baseX, relBall.x, 0.2);
                  depth = clamp(0.78 + h * 0.04, 0.74, 0.86);
                  pin._running = true;
                } else if (pin.role === "CM") {
                  x = clamp(0.5 + (pin.baseX - 0.5) * 0.55 + (h - 0.5) * 0.04, 0.3, 0.7);
                  depth = clamp(0.72 + bias, 0.68, 0.8);
                  pin._running = true;
                } else if (pin.role === "FB") {
                  if (pin._overlapRun || atkPattern === "wing_carry" || Math.abs(relBall.x - pin.baseX) < 0.35) {
                    x = flank === "R" ? 0.91 : 0.09;
                    depth = clamp(0.8 + fbAttackThreat(pin) * 0.08, 0.72, 0.9);
                    pin._running = true;
                  } else {
                    x = lerp(pin.baseX, 0.5 + sideSign * 0.2, 0.4);
                    depth = clamp(midLine + 0.06, defLine + 0.08, 0.7);
                  }
                } else if (pin.role === "DM") {
                  depth = clamp(0.58 + bias, 0.5, 0.66);
                  x = lerp(pin.baseX, relBall.x, 0.25);
                }
                // Ensure enough crashers when occupation thin
                if (boxedN < 2 && (pin.role === "W" || pin.role === "CM") && h > 0.45) {
                  depth = Math.max(depth, 0.8);
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

                if (stCycle === "drop") {
                  depth = lerp(depth, clamp(relBall.depth - 0.02, midLine, onsideDepth), 0.45);
                  x = lerp(x, relBall.x, 0.25);
                  pin._running = false;
                } else if (stCycle === "pin") {
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
              // real space-scoring above; drive PROGRESSING the same way
              // instead, sharing the same _wPrefHalf flag so a winger
              // doesn't flip preference right at the stage boundary.
              if (pin.role === "W" && atkStage === "PROGRESSING") {
                const touch = flank === "R" ? 0.92 : flank === "L" ? 0.08 : pin.baseX;
                const half = flank === "R" ? 0.7 : flank === "L" ? 0.3 : 0.5;
                const scoreTouch = scoreOpenSpace(pin, touch, depth);
                const scoreHalf = scoreOpenSpace(pin, half, depth);
                const hysteresis = 0.12;
                const pickHalf = pin._wPrefHalf
                  ? scoreHalf > scoreTouch - hysteresis
                  : scoreHalf > scoreTouch + hysteresis;
                pin._wPrefHalf = pickHalf;
                x = lerp(x, pickHalf ? half : touch, 0.5);
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
                const compress =
                  pin.role === "CB" ? 0.18 : pin.role === "DM" ? 0.28 : pin.role === "FB" ? 0.2 : pin.role === "CM" ? 0.24 : 0.12;
                x = lerp(pin.baseX, relBall.x, compress + threat * (pin.role === "CB" || pin.role === "DM" ? 0.1 : 0.05));
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

              const carrier = findCarrier();
              const threats = pinsOf(oppOf(pin.side)).filter(
                (a) =>
                  (a.role === "ST" || a.role === "W" || a.role === "AM" || a.role === "CM") &&
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

              let defMode = "hold";
              const pressEligible =
                pin.role === "DM" ||
                pin.role === "CM" ||
                pin.role === "FB" ||
                pin.role === "CB" ||
                (!threeBack && pin.role === "AM");
              const ranked = pins
                .filter(
                  (p) =>
                    p.role === "DM" ||
                    p.role === "CM" ||
                    p.role === "FB" ||
                    p.role === "CB" ||
                    (!threeBack && p.role === "AM")
                )
                .map((p) => ({
                  id: p.id,
                  d: dist({ left: p.left, top: p.top }, { left: ballLeft, top: ballTop }),
                  mid: p.role === "DM" || p.role === "CM" ? 0 : p.role === "FB" || p.role === "AM" ? 1 : 2,
                }))
                .sort((a, b) => a.mid - b.mid || a.d - b.d);
              const nPressBase = pressEdge > 0.15 ? (press > 0.55 ? 4 : 3) : press > 0.7 ? 3 : press > 0.42 ? 2 : 1;
              // Chance/box pressure: fewer push up; favour cover/retreat
              const nPressScaled = Math.max(1, Math.round(nPressBase * (1 - threat * 0.55)));
              const nPress = threeBack ? Math.min(nPressScaled, 2) : nPressScaled;
              const pressRank = ranked.findIndex((r) => r.id === pin.id);

              if (
                runner &&
                (pin.role === "CB" || pin.role === "FB" || (pin.role === "DM" && defQ > 0.5)) &&
                dist(pin, runner) < 16 + trackBoost * 3
              ) {
                defMode = "track";
              } else if (
                pressEligible &&
                pressRank >= 0 &&
                pressRank < nPress &&
                dBall < pressRadius &&
                !(threat > 0.55 && pin.role === "CB" && pressRank > 0)
              ) {
                defMode = "press";
              } else if (
                (pin.role === "CM" || pin.role === "DM" || (threeBack && pin.role === "AM")) &&
                carrier &&
                (threats.some((t) => t._supportRole === "progressive" || t._supportRole === "third_man") ||
                  defQ > 0.48 ||
                  threat > 0.35)
              ) {
                defMode = "cover";
              } else if (mark && (pin.role === "CB" || pin.role === "FB" || pin.role === "DM" || pin.role === "CM")) {
                defMode = "mark";
              }

              // Goalside cover depth: between ball and own goal (depth ≤ ball)
              const goalside = clamp(Math.min(relBall.depth - 0.02, defLine + 0.02), 0.05, midLine + 0.04);

              if (defMode === "track" && runner) {
                const markRel = fromPitchPct(pin.side, runner.left, runner.top);
                const t = clamp(0.38 + trackBoost * 0.22, 0.32, 0.72);
                const trackX =
                  centralMidCover && isScreenMid
                    ? clamp(markRel.x, 0.28, 0.72)
                    : markRel.x;
                x = lerp(x, trackX, t * (centralMidCover && isScreenMid ? 0.72 : 1));
                const trackDepth = clamp(markRel.depth - 0.005, defLine - 0.04, midLine + 0.1);
                depth = lerp(depth, threat > 0.4 ? Math.min(trackDepth, goalside + 0.04) : trackDepth, t * 0.9);
                pin._pressing = dist(pin, runner) < 8;
              } else if (defMode === "press") {
                pin._pressing = true;
                const nearBoost = dBall < 5 ? 1.4 : dBall < 8 ? 1.1 : 0.7;
                const t = (0.22 + press * 0.32 + pin.stats.tackles90 * 0.04 + Math.max(0, pressEdge) * 0.12) * nearBoost;
                const step = clamp(t * (1 - threat * 0.28), 0.14, 0.62);
                if (centralMidCover && isScreenMid) {
                  const pressX = clamp(relBall.x, 0.3, 0.7);
                  x = lerp(x, pressX, step * 0.55);
                } else {
                  x = lerp(x, relBall.x, step);
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
                const markT = (pin.role === "FB" || pin.role === "CM" ? 0.4 : 0.32) * trackBoost;
                const markX =
                  centralMidCover && isScreenMid
                    ? clamp(markRel.x, 0.3, 0.7)
                    : markRel.x;
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

              // Wingers/CAM sat out of any defensive duty entirely — fine to
              // not track back into their own box, but they shouldn't just
              // stay pinned upfield either while their side defends. Nudge
              // them back toward at least the halfway line under real
              // pressure, well short of the CB/FB/DM low-block retreat above.
              if (threat > 0.12 && (pin.role === "W" || pin.role === "AM")) {
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
            const farCB = byDanger[byDanger.length - 1];
            if (farCB) {
              const coverX = 0.5 + (farCB.pin.baseX - 0.5) * 0.5;
              farCB.x = lerp(farCB.x, coverX, 0.3);
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

        for (const { pin, x, depth } of pending) {
          let dd = clamp(depth, 0.03, 0.96);
          let xx = clamp(x, 0.04, 0.96);
          const h = iHash(pin.id);
          const dx = xx - (pin.x ?? pin.baseX);
          const dd0 = dd - (pin.depth ?? pin.baseDepth);
          const pathLen = Math.hypot(dx, dd0) + 1e-6;
          const perpX = -dd0 / pathLen;
          const perpD = dx / pathLen;
          const arcAmp = (pin._running ? 0.022 : pin._pressing ? 0.012 : 0.008) * (0.75 + h * 0.35);
          const arc = Math.sin(shapePulse * 0.55 + h * 5.1) * arcAmp;
          xx = clamp(xx + perpX * arc, 0.04, 0.96);
          dd = clamp(dd + perpD * arc * 0.45, 0.03, 0.96);
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
          const latBias = jump > 0.35 ? (-jdy / (jump + 1e-6)) * arcAmp * 18 : 0;
          const depthBias = jump > 0.35 ? (jdx / (jump + 1e-6)) * arcAmp * 12 : 0;
          const dampRate = pin._running || pin._pressing ? 0.28 : 0.18;
          if (jump > maxJump) {
            const s = maxJump / jump;
            pin.tx = smoothDamp(pin.tx, pin.tx + jdx * s + latBias, dampRate);
            pin.ty = smoothDamp(pin.ty, pin.ty + jdy * s + depthBias, dampRate);
          } else {
            pin.tx = smoothDamp(pin.tx, pct.left + latBias * 0.35, dampRate);
            pin.ty = smoothDamp(pin.ty, pct.top + depthBias * 0.35, dampRate);
          }
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
        const maxLogical = Math.max(0.04, pinRunSpeedPct(pin) * dt);
        const logical = stepTowardClamped(pin.left, pin.top, wantL, wantT, rate, maxLogical);
        pin.left = logical.left;
        pin.top = logical.top;
        // Render trails logical (slightly softer / slower) — never chases tx directly
        if (pin.rx == null) pin.rx = pin.left;
        if (pin.ry == null) pin.ry = pin.top;
        const maxRender = maxLogical * 0.92;
        const rendered = stepTowardClamped(pin.rx, pin.ry, pin.left, pin.top, rate * 0.88, maxRender);
        pin.rx = rendered.left;
        pin.ry = rendered.top;
        const el = pinEls.get(pin.id);
        if (el) {
          el.style.left = `${pin.rx}%`;
          el.style.top = `${pin.ry}%`;
          el.classList.toggle("has-ball", pin.id === carrierId);
          el.classList.toggle(
            "pressing",
            pin.side !== possession && (pin._pressing || dist(pin, ball) < 8 + sidePress(pin.side) * 5)
          );
          el.classList.toggle("running", Boolean(pin._running) && pin.id !== carrierId);
        }
        const dbg = debugDotEls.get(pin.id);
        if (dbg) {
          dbg.style.left = `${pin.left}%`;
          dbg.style.top = `${pin.top}%`;
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
      pin._pathCtrl = null;
      const el = pinEls.get(pin.id);
      if (el) {
        el.style.left = `${L}%`;
        el.style.top = `${T}%`;
      }
      const dbg = debugDotEls.get(pin.id);
      if (dbg) {
        dbg.style.left = `${L}%`;
        dbg.style.top = `${T}%`;
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
      ballEl.style.left = `${ball.left}%`;
      ballEl.style.top = `${ball.top}%`;
    }

    function giveBall(pin, comment) {
      const prevSide = possession;
      const sideChanged = !spell || pin.side !== prevSide;
      carrierId = pin.id;
      possession = pin.side;
      ballAttached = true;
      ballCtrl = null;
      pin._boxDriveDone = false;
      pin._dribbleStreak = 0;
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
      return clamp(
        (0.42 + create * 0.24 + atk * 0.18 - def * 0.03 + (rng() - 0.5) * 0.05) * vol * lerp(1, supp, 0.45),
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
      };
      phase = "BUILD_UP";
      pushMatchEvent("possession", side, { detail: reason || "builds" });
      if (commentaryHold <= 0.4) {
        const name = side === "home" ? homeTeam.name : awayTeam.name;
        say(`${name} in possession`, 1.4);
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

      // Without box occupation, refuse high-xG path — recycle instead
      if (!ready && !inPenaltyBox(carrier)) {
        if (
          (carrier.role === "ST" || carrier.role === "AM" || maestroShine) &&
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
        if (rng() < 0.45 + (maestroShine ? 0.2 : 0) || forwardInFinalThird(carrier) || maestroShine) {
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
        ((carrier.role === "ST" || carrier.role === "AM" || maestroShine) &&
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
        if (!boxOccupationReady(carrier.side)) {
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
      if (!inPenaltyBox(carrier) && (carrier.role === "ST" || carrier.role === "AM") && rng() < 0.55) {
        spell.awaitingBoxShot = true;
        spell.chanceDone = false;
        if (driveIntoBox(carrier)) return;
        spell.chanceDone = true;
      }
      if (!boxOccupationReady(carrier.side) && !inPenaltyBox(carrier)) {
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
      scoreEl.textContent = `${homeScore} – ${awayScore}`;
      flashEl.hidden = false;
      flashEl.className = `tactic-flash ${side}`;
      flashEl.textContent = "GOAL!";
      flashTimer = 1.35;
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
      const press = sidePress(oppOf(from.side));
      const resist = sideResist(from.side);
      const edge = press - resist;
      const atkU = sideAttack(from.side);
      const defU = sideDefend(oppOf(from.side));
      const possQ = sidePoss(from.side);

      let outcome = "pass";
      let interceptor = null;
      let comment = null;

      if (threat && !(replayScore && nextScheduledGoal(possession, matchMinute))) {
        const def = threat.pin;
        const closePress = pressers[0] ? clamp(1.2 - pressers[0].d / 11, 0.4, 1.25) : 0.55;
        const longPen = passKind === "long" || isLongSkip(from, to) ? 0.2 : 0;
        const laneN = defendersInLane(from, to);
        const lanePen = laneN * 0.055;
        const pIntercept =
          0.035 +
          def.stats.interceptions90 * 0.05 +
          def.stats.tackles90 * 0.03 +
          Math.min(0.08, Math.max(0, edge) * 0.1) * closePress +
          press * 0.025 * closePress +
          defU * 0.07 -
          resist * 0.09 -
          possQ * 0.055 -
          atkU * 0.04 -
          from.stats.pass_pct * 0.0015 -
          from.stats.key_passes90 * 0.008 +
          longPen +
          lanePen;
        const cap = passKind === "long" ? 0.48 : 0.3;
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
      if (
        outcome === "pass" &&
        pressers[0] &&
        pressers[0].d < 5.2 + Math.max(0, edge) * 2.5 &&
        passKind !== "clear"
      ) {
        const p = pressers[0].pin;
        const stealP =
          0.028 +
          Math.max(0, edge) * 0.09 +
          press * 0.025 +
          p.stats.tackles90 * 0.035 -
          resist * 0.07 -
          from.stats.dribble_pct * 0.0012;
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
        tx = interceptor.left;
        ty = interceptor.top;
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
        // Contested header vs aerial defence / CB positioning — decided before flight
        if (outcome === "pass") {
          const aerial = sideAerial(oppOf(from.side));
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
          const attAerial =
            0.32 +
            to.stats.xg90 * 0.36 +
            toAerial +
            (to.role === "ST" ? 0.14 : 0.05) +
            from.stats.xa90 * 0.3 +
            atkU * 0.08 +
            strikerAerialThreat(from.side) * 0.22;
          const defAerial =
            aerial * 0.85 +
            (bestCb ? 0.18 + bestCb.stats.interceptions90 * 0.045 + bestCb.stats.tackles90 * 0.02 : 0.12) +
            (bestD < 11 ? 0.14 : bestD < 16 ? 0.06 : 0) +
            defU * 0.08;
          const winP = clamp(0.4 + attAerial - defAerial + (rng() - 0.5) * 0.1, 0.16, 0.8);
          if (rng() > winP && bestCb) {
            outcome = "intercept";
            interceptor = bestCb;
            comment = `${bestCb.short} wins the aerial`;
            tx = bestCb.left;
            ty = bestCb.top;
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
      const threat = nearestOpponent(carrier, 12);
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
      const successP =
        0.28 +
        carrier.stats.dribbles90 * 0.07 +
        carrier.stats.dribble_pct * 0.0035 +
        resist * 0.16 +
        atkU * 0.06 -
        Math.max(0, fieldPressure - resist * 1.6) * 0.16 -
        defU * 0.08 -
        (threat ? threat.pin.stats.tackles90 * 0.07 : 0) -
        (threat ? threat.pin.stats.interceptions90 * 0.02 : 0) -
        Math.min(streak, 4) * 0.11 +
        (rng() - 0.5) * 0.08;

      const won = rng() < clamp(successP, 0.1, 0.72);
      const attackSign = carrier.side === "home" ? -1 : 1;
      const ahead = 2.2 + carrier.stats.dribbles90 * 0.55 + rng() * 1.5;
      const jink = (rng() < 0.5 ? 1 : -1) * (2.2 + rng() * 2.8);
      const midX = clamp(carrier.left + jink, 6, 94);
      const midY = clamp(carrier.top + attackSign * ahead * 0.4, 5, 95);
      const nx = clamp(midX - jink * 0.35 + (rng() - 0.5) * 1.4, 6, 94);
      const ny = clamp(carrier.top + attackSign * ahead, 5, 95);

      carrier._pathCtrl = { left: midX, top: midY, from: matchMinute, until: matchMinute + 0.45 };
      carrier.tx = nx;
      carrier.ty = ny;
      carrier.lockUntil = matchMinute + 0.9;
      ballAttached = true;
      const dur = 0.65;
      setBallTarget(nx, ny + attackSign * -0.5, dur, true);
      actionTimer = dur + 0.12 + spellIdlePause() * 0.35;

      if (won) {
        carrier._dribbleStreak = streak + 1;
        pushMatchEvent("dribble_won", carrier.side, {
          player: carrier.player,
          player_short: carrier.short,
          detail: threat ? `past ${threat.pin.short}` : "past the press",
        });
        say(`${carrier.short} dribbles past ${threat?.pin.short || "the press"}`, 1.4);
        ballFlight = { outcome: "dribble_won" };
      } else {
        const opp = threat?.pin || nearestOpponent(carrier, 30)?.pin || pinsOf(oppOf(carrier.side))[3];
        pushMatchEvent("dribble_lost", carrier.side, {
          player: carrier.player,
          player_short: carrier.short,
          by: opp?.player,
          detail: opp ? `stopped by ${opp.short}` : "loses possession",
        });
        say(opp ? `${opp.short} stops ${carrier.short}` : `${carrier.short} loses it`, 1.4);
        // Ball ends at the tackler's feet — path decided now
        if (opp) {
          ballAttached = false;
          const arc = passArcFor(ball.left, ball.top, opp.left, opp.top, "pass");
          setBallTarget(opp.left, opp.top, Math.min(dur, arc.dur), false, arc.ctrl);
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
      // Was unconditionally safe even with a defender right next to the
      // carrier — a free, guaranteed advance regardless of pressure, while
      // doDribble (the only contestable forward action) only fires on a
      // separate dice roll. Give a nearby defender a real, if modest, chance
      // to close a carry down instead of always standing there doing nothing.
      const threat = nearestOpponent(carrier, 9);
      // Engine rebuild Phase 1 — also gate on the real pressure field, not
      // just the single nearest defender, so a converging 2v1 (neither
      // defender alone inside the old 8.5-unit cutoff) still counts as real
      // pressure instead of being invisible to this check.
      const fieldPressure = pressureAt(carrier.left, carrier.top, carrier.side);
      if ((threat && threat.d < 8.5) || fieldPressure > 0.35) {
        const resist = sideResist(carrier.side);
        const def = sideDefend(oppOf(carrier.side));
        const closeMul = threat ? clamp(1.2 - threat.d / 9, 0.55, 1.2) : 0.7;
        const dispossessP =
          (0.05 +
            def * 0.1 +
            (threat ? threat.pin.stats.tackles90 * 0.05 : 0) -
            resist * 0.08 -
            carrier.stats.dribbles90 * 0.03 +
            fieldPressure * 0.09 +
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
      }
      const attackSign = carrier.side === "home" ? -1 : 1;
      const push = 2.2 + rng() * 2.4 + carrier.stats.dribbles90 * 0.35;
      const jink = (rng() < 0.55 ? 1 : -1) * (1.6 + rng() * 2.6);
      const midX = clamp(carrier.left + jink, 8, 92);
      const midY = clamp(carrier.top + attackSign * push * 0.38, 5, 95);
      const nx = clamp(midX - jink * 0.28 + (rng() - 0.5) * 1.2, 8, 92);
      const ny = clamp(carrier.top + attackSign * push, 5, 95);
      carrier._pathCtrl = { left: midX, top: midY, from: matchMinute, until: matchMinute + 0.4 };
      carrier.tx = nx;
      carrier.ty = ny;
      carrier.lockUntil = matchMinute + 0.75;
      ballAttached = true;
      setBallTarget(nx, ny + attackSign * -0.8, 0.7, true);
      actionTimer = 0.55 + rng() * 0.25 + spellIdlePause() * 0.5;
      if (commentaryHold <= 0) say(`${carrier.short} drives forward`, 1.0);
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
      const pCold = clamp(0.08 - bias * 0.12, 0.02, 0.18);
      const pHot = clamp(0.12 + bias * 0.16, 0.04, 0.28);
      const u = rng();
      if (u < pCold) {
        // Cold day — goals << xG: factor ~0.35–0.72 (was 0.22–0.65; less blank-night extreme)
        return clamp(0.35 + rng() * 0.37, 0.32, 0.72);
      }
      if (u < pCold + pHot) {
        // Hot day — goals > xG (e.g. 4–5 from ~3): factor ~1.35–1.95
        return clamp(1.35 + rng() * 0.6, 1.3, 1.95);
      }
      // Normal — triangular-ish around 1.0 (+ mild finishing mean shift)
      const noise = (rng() + rng() + rng() - 1.5) * 0.22;
      const meanShift = bias * 0.06;
      return clamp(1.0 + meanShift + noise, 0.78, 1.22);
    }

    function redrawFinishingForm() {
      finishingForm = { home: drawFinishingForm("home"), away: drawFinishingForm("away") };
    }

    function organicWillScore(carrier) {
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
      const p =
        (0.05 +
          carrier.stats.xg90 * xgW +
          carrier.stats.shots90 * shW +
          goals * goalsW +
          clinical +
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
      return rng() < clamp(p, lo, hi);
    }

    function doShot(carrier, mustScore) {
      if (ballFlight) return;
      const keeper = gkOf(oppOf(carrier.side));
      const atk = sideAttack(carrier.side);
      const def = sideDefend(oppOf(carrier.side));
      const gk = sideGoalkeeper(oppOf(carrier.side));
      ballAttached = false;
      phase = "FINISH";
      if (spell) {
        spell.chanceDone = true;
        spell.stage = "FINISH";
        spell.awaitingShot = false;
        spell.awaitingBoxShot = false;
      }
      const boxed = inPenaltyBox(carrier);
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
        detail: boxed ? "shot" : "long_shot",
        xg: Math.round(chanceXg * 1000) / 1000,
        in_box: boxed,
      });
      const xgLabel = chanceXg.toFixed(2);
      say(
        chanceType === "big_chance"
          ? `Big chance! ${carrier.short} shoots — xG ${xgLabel}`
          : boxed
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
        willScore = Boolean(mustScore) || organicWillScore(carrier);
      }
      if (willScore && !replayScore && !mustScore) {
        const form = clamp(finishingForm[carrier.side] ?? 1, 0.2, 1.95);
        // Hot finishing → fewer denied shots; cold → more saves/misses after an on-target look
        const saveScale = clamp(1.05 - (form - 1) * 0.55, 0.52, 1.7);
        const roleFin = isAttackFinisher(carrier);
        const fq = finisherQuality(carrier);
        const saveP =
          (0.1 +
            def * 0.22 -
            atk * 0.08 -
            carrier.stats.xg90 * (boxed ? (roleFin ? 0.2 : 0.14) : 0.05) -
            carrier.stats.shots90 * (roleFin ? 0.018 : 0.012) -
            (roleFin ? fq * 0.06 : 0) +
            (boxed ? 0 : 0.12) +
            gk * 0.14 +
            (rng() - 0.5) * 0.06) *
          saveScale;
        if (rng() < clamp(saveP, 0.04, roleFin && boxed && fq >= 0.7 ? 0.42 : 0.55)) willScore = false;
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
        const blockP =
          0.28 + def * 0.22 - atk * 0.08 - carrier.stats.xg90 * 0.06 + (boxed ? 0 : 0.1) + (rng() - 0.5) * 0.08;
        if (rng() < clamp(blockP, 0.18, 0.5)) {
          const blocker =
            nearestOpponent(carrier, 9)?.pin ||
            pinsOf(oppOf(carrier.side)).find((p) => p.role === "CB") ||
            keeper;
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

    function decideAction() {
      const carrier = findCarrier();
      if (!carrier || finished || ballFlight) return;
      // A goal/restart sequence is already locked in (ball walking back to the
      // centre, kickoff carrier not yet assigned) — actionTimer expires well
      // before this resolves, which let the scoring side grab another decision
      // (and even score again) before kickoff ever happened. Freeze decisions
      // until the restart actually completes.
      if (pendingRestart || pendingKickoffCarrier || pendingClear) return;

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
            if (forwardInFinalThird(carrier)) {
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
        if (!boxOccupationReady(carrier.side)) {
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
        const probeP =
          ((stage === "BOX_OCCUPATION" ? 0.09 : stage === "FINAL_THIRD" ? 0.075 : 0.045) +
            create * 0.07 +
            carrier.stats.xa90 * 0.045 +
            (spell.willAttemptChance ? 0.03 : 0.014) +
            urg * 0.045 +
            Math.max(0, ad) * 0.06 +
            maestroBoost) *
          vol *
          lerp(1, supp, 0.7);
        if (rng() < clamp(probeP, 0.03, 0.28)) {
          if (spell) spell.willAttemptChance = true;
          attemptSpellChance(carrier);
          return;
        }
      }

      if (stage === "BOX_OCCUPATION" && rng() < (carrier.role === "DM" ? 0.28 : 0.12) * clamp(1.1 - progressionUrgency(spell) * 0.55, 0.25, 1)) {
        if (commentaryHold <= 0) say(`${carrier.short} recycles possession`, 1.1);
        actionTimer = spellIdlePause();
        return;
      }

      if (carrier.role === "DM" && (stage === "BUILD_UP" || stage === "PROGRESSING")) {
        const cms = teammates(carrier).filter((m) => m.role === "CM");
        if (cms.length && rng() < 0.78) {
          cms.sort((a, b) => dist(carrier, a) - dist(carrier, b) + (rng() - 0.5) * 2);
          doPass(carrier, cms[0], "pass");
          actionTimer = Math.max(actionTimer, spellIdlePause());
          return;
        }
      }

      if (stage === "BUILD_UP") {
        if (isDefRole(carrier.role) && rng() < 0.04) {
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
        if (isDefRole(carrier.role) && rng() < 0.04) {
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
      if (homeScore > awayScore) return homeTeam.name;
      if (awayScore > homeScore) return awayTeam.name;
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
      if (kind === "ht") {
        matchMinute = 45.05;
        clockCap = 90;
        clockEl.textContent = "45'";
        say("Second half underway", 1.8);
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
        (p.role === "ST" ? 0.35 : p.role === "AM" ? 0.22 : p.role === "W" ? 0.15 : 0);
      return [...pins].sort((a, b) => rank(b) - rank(a));
    }

    function penConvertChance(taker) {
      const form = clamp(finishingForm[taker.side] ?? 1, 0.55, 1.45);
      const fin = sideFinishing(taker.side);
      const base =
        0.7 +
        (taker.stats.xg90 || 0) * 0.1 +
        fin * 0.1 +
        (taker.role === "ST" || taker.role === "AM" ? 0.04 : 0);
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
        const scored = rng() < penConvertChance(kick.pin);
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
      if (isKnockout && homeScore === awayScore) {
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
      if (homeScore === awayScore) {
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

    function tickRender(dt) {
      const moving = stepBallTween(dt);
      if (!moving && ballFlight) {
        resolveBallFlight();
      } else if (!moving && ballAttached) {
        attachBallToCarrier();
      }
      applyPinMotion(dt);
    }

    function tick(ts) {
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
      const dt = Math.min(0.05, ((ts - lastTs) / 1000) * speed);
      lastTs = ts;

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
      decisionAcc = DECISION_INTERVAL_MAX;
      nextDecisionIn = DECISION_INTERVAL_MIN + rng() * (DECISION_INTERVAL_MAX - DECISION_INTERVAL_MIN);
      scoreEl.textContent = "0 – 0";
      clockEl.textContent = "0'";
      phaseEl.textContent = "Ready";
      clearFlash();
      updateHud();
      scheduled.forEach((g) => {
        g.scored = false;
      });
      allPins.forEach((p) => {
        const pct = toPitchPct(p.side, p.baseX, p.baseDepth);
        snapPinPose(p, pct.left, pct.top);
        p.lockUntil = 0;
        p.favorUntil = 0;
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
    container.querySelector("[data-tb-speed]").addEventListener("change", (e) => {
      speed = Number(e.target.value) || 0.5;
    });
    container.querySelectorAll("[data-tb-push]").forEach((btn) => {
      btn.addEventListener("click", () => setInstruction(btn.dataset.tbPush, "push"));
    });
    container.querySelectorAll("[data-tb-sit]").forEach((btn) => {
      btn.addEventListener("click", () => setInstruction(btn.dataset.tbSit, "sit"));
    });
    if (htResumeBtn) htResumeBtn.addEventListener("click", () => resumeFromBreak());

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

    return {
      play,
      pause,
      reset,
      getScore: () => ({ homeGoals: homeScore, awayGoals: awayScore }),
      getMatchLog: getMatchLogPayload,
      getBroadcastState,
      applyBroadcastState,
      getBroadcastFrame: getBroadcastState,
      applyFrame: applyBroadcastState,
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
    const mc = report?.monte_carlo || {};
    const sample = report?.sample_match || {};
    const profiles = report?.profiles || {};
    const xg = mc.expected_xg || {};
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
        onBroadcast: meta.onBroadcast || null,
        broadcastIntervalMs: meta.broadcastIntervalMs,
        onComplete: onDone,
        onScore: meta.onScore,
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
