const SESSION_KEY = "sim_session_token";
const USER_KEY = "sim_user_name";

function getToken() {
  return localStorage.getItem(SESSION_KEY);
}

function getUser() {
  return localStorage.getItem(USER_KEY);
}

function isAdminUser() {
  return getUser() === "admin";
}

function isTeamUser() {
  return Boolean(getToken()) && !isAdminUser();
}

function setSession(token, user) {
  localStorage.setItem(SESSION_KEY, token);
  localStorage.setItem(USER_KEY, user);
}

function clearSession() {
  localStorage.removeItem(SESSION_KEY);
  localStorage.removeItem(USER_KEY);
  // Bug fix — real user report: an admin password was set up specifically
  // to control admin access, but any browser that ever had the raw
  // SIM_ADMIN_TOKEN entered (admin.js's own "Admin token" field) kept full
  // admin rights forever afterward -- requireAuthOrAdmin() accepts EITHER
  // credential, and this function never cleared the raw token, so "Log
  // out" didn't actually log that device out at all for anything gated by
  // it. Logout now clears both, so the password is the only way back in.
  localStorage.removeItem("sim_admin_token");
}

function formatApiError(data, res) {
  const detail = data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => (item && typeof item.msg === "string" ? item.msg : JSON.stringify(item)))
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  if (detail && typeof detail === "object") {
    if (typeof detail.message === "string" && detail.message.trim()) return detail.message;
    try {
      return JSON.stringify(detail);
    } catch (_) {}
  }
  if (typeof data?.message === "string" && data.message.trim()) return data.message;
  if (res.statusText && res.statusText.trim()) return res.statusText;
  return `HTTP ${res.status || "error"}`;
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = getToken();
  if (token) headers["X-Session-Token"] = token;
  const adminToken = getAdminToken();
  if (adminToken) headers["X-Admin-Token"] = adminToken;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
    delete options.json;
  }
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(formatApiError(data, res));
  return data;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Poll match analysis until ready (202 generating → 200 ready). `apiBase`
 * picks the format-specific endpoint prefix -- "/api/tournament" (default,
 * groups+knockout) or "/api/league-cup" (league/cup matches only --
 * friendlies have no deterministic analysis to poll for). */
async function fetchTournamentMatchAnalysis(tournamentId, matchId, { force = false, apiBase = "/api/tournament" } = {}) {
  const path = `${apiBase}/${tournamentId}/matches/${matchId}/analysis`;
  const maxAttempts = 90;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const data =
      force && attempt === 0
        ? await api(path, { method: "POST" })
        : await api(path);
    if (data?.status === "error") {
      throw new Error(data.message || "Analysis generation failed");
    }
    if (data?.analysis || data?.status === "ready" || data?.has_analysis) {
      return data;
    }
    // status === "generating" (HTTP 202) or missing payload — keep polling
    await sleep(2000);
  }
  throw new Error("Analysis is still generating — try again in a moment.");
}

function getAdminToken() {
  return localStorage.getItem("sim_admin_token") || "";
}

function setAdminToken(token) {
  if (token) localStorage.setItem("sim_admin_token", token);
  else localStorage.removeItem("sim_admin_token");
}

function requireAuth() {
  if (!getToken()) {
    window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
    return false;
  }
  return true;
}

/** Logged-in user OR admin token (for viewing any experiment). */
function requireAuthOrAdmin() {
  if (getToken() || getAdminToken()) return true;
  window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
  return false;
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

// ---------------------------------------------------------------------------
// Shared stat-leaderboard rendering -- used by both tournament.js (old
// group+knockout viewer) and league_cup.js (League + Cup viewer), which
// both read the same player_leaderboards()-shaped boards from the backend.
// Lived only in tournament.js originally; league_cup.js's Stats tab shipped
// without the player/team toggle, category grouping, or 4 of the 11 stat
// boards as a result -- moved here so both pages share one implementation
// instead of the League + Cup page silently drifting out of parity again.
// ---------------------------------------------------------------------------

function renderLeaderboardTable(rows, countKey, countLabel, emptyMsg, { suffix = "" } = {}) {
  if (!rows?.length) {
    return `<p class="muted" style="margin:0">${esc(emptyMsg)}</p>`;
  }
  const body = rows
    .map((r, i) => {
      const n = r[countKey] ?? 0;
      return `<tr><td>${i + 1}</td><td>${esc(r.player || "—")}</td><td>${esc(r.team || "—")}</td><td class="num"><strong>${esc(String(n))}${suffix}</strong></td></tr>`;
    })
    .join("");
  return `<div class="report-table-wrap rank-table emphasize-top"><table><thead><tr><th>#</th><th>Player</th><th>Team</th><th>${esc(countLabel)}</th></tr></thead><tbody>${body}</tbody></table></div>`;
}

// Team view -- same leaderboard shape as renderLeaderboardTable, minus the
// Player column, for a table aggregated per team instead of per player.
function renderTeamLeaderboardTable(rows, countKey, countLabel, emptyMsg, { suffix = "" } = {}) {
  if (!rows?.length) {
    return `<p class="muted" style="margin:0">${esc(emptyMsg)}</p>`;
  }
  const body = rows
    .map((r, i) => {
      const n = r[countKey] ?? 0;
      return `<tr><td>${i + 1}</td><td>${esc(r.team || "—")}</td><td class="num"><strong>${esc(String(n))}${suffix}</strong></td></tr>`;
    })
    .join("");
  return `<div class="report-table-wrap rank-table emphasize-top"><table><thead><tr><th>#</th><th>Team</th><th>${esc(countLabel)}</th></tr></thead><tbody>${body}</tbody></table></div>`;
}

// Team-only boards (e.g. team_ppda) are already server-sorted -- this is a
// thin wrapper so the same renderTeamLeaderboardTable can render them
// without going through teamBoard()/aggregateTeamTallies at all.
function renderTeamOnlyBoard(rows, board) {
  return renderTeamLeaderboardTable(rows, board.field, board.label, board.empty, { suffix: board.suffix || "" });
}

// Mirrors web/tournament.py's _TALLY_FIELDS exactly -- every field a
// player_tallies row carries, so a team total is a plain per-field sum
// across every player who's ever turned out for that team. clean_sheets
// works out correctly here too: only the match's actual GK is credited
// per clean sheet server-side, so summing by team already equals that
// team's real clean-sheet count, not a double-count.
const TALLY_FIELDS = [
  "goals", "assists", "shots", "dribbles", "distance_carried",
  "tackles", "interceptions", "key_passes", "big_chances_created",
  "big_chances_missed", "clean_sheets",
  // Conversion/passing stats project -- raw counters only; the derived
  // ratio fields (xg_diff, shot_conversion_pct, etc.) are computed after
  // summing, by addDerivedTallyFields below -- never summed directly,
  // same reasoning as tournament.py's _TALLY_FIELDS comment.
  "xg", "big_chances", "big_chance_goals", "saves", "goals_conceded",
  "passes_attempted", "passes_completed", "crosses_attempted",
  "crosses_completed", "through_attempted", "through_completed",
  // Discipline/progression stats project.
  "fouls", "cards", "penalty_goals", "progressive_passes",
];

// Mirrors web/tournament.py's _add_derived_tally_fields/_ratio_pct exactly
// (same formulas, same qualification minimums) so a team-view ratio and
// the equivalent player-view ratio never disagree. Used here for team rows
// (aggregateTeamTallies sums raw counts only); player rows already arrive
// from the server with these fields pre-computed.
const RATIO_MIN_DENOMINATOR = {
  shot_conversion_pct: 3,
  big_chance_conversion_pct: 2,
  pass_completion_pct: 15,
  cross_accuracy_pct: 5,
  through_ball_completion_pct: 3,
  save_pct: 3,
};
const XG_DIFF_MIN_SHOTS = 2;

function ratioPct(numerator, denominator, field) {
  if (denominator < RATIO_MIN_DENOMINATOR[field]) return null;
  return Math.round((numerator / denominator) * 1000) / 10;
}

function addDerivedTallyFields(row) {
  const shots = Number(row.shots || 0);
  const goals = Number(row.goals || 0);
  row.xg_diff = shots >= XG_DIFF_MIN_SHOTS ? Math.round((goals - Number(row.xg || 0)) * 100) / 100 : null;
  row.shot_conversion_pct = ratioPct(goals, shots, "shot_conversion_pct");
  row.big_chance_conversion_pct = ratioPct(Number(row.big_chance_goals || 0), Number(row.big_chances || 0), "big_chance_conversion_pct");
  row.pass_completion_pct = ratioPct(Number(row.passes_completed || 0), Number(row.passes_attempted || 0), "pass_completion_pct");
  row.cross_accuracy_pct = ratioPct(Number(row.crosses_completed || 0), Number(row.crosses_attempted || 0), "cross_accuracy_pct");
  row.through_ball_completion_pct = ratioPct(Number(row.through_completed || 0), Number(row.through_attempted || 0), "through_ball_completion_pct");
  const saves = Number(row.saves || 0);
  const conceded = Number(row.goals_conceded || 0);
  row.save_pct = ratioPct(saves, saves + conceded, "save_pct");
  return row;
}

function aggregateTeamTallies(playerTallies) {
  const teams = {};
  for (const row of playerTallies || []) {
    const team = row.team || "—";
    if (!teams[team]) {
      teams[team] = { team };
      for (const f of TALLY_FIELDS) teams[team][f] = 0;
    }
    for (const f of TALLY_FIELDS) teams[team][f] += Number(row[f] || 0);
  }
  // Bug fix -- distance_carried is the one non-integer field here; each
  // player row already comes pre-rounded to 1 decimal from the server,
  // but summing several rounded floats in JS can still land on something
  // like 222.60000000000002 (plain binary floating-point, the same
  // reason 0.1 + 0.2 !== 0.3) -- round again after the sum, same 1-decimal
  // convention the backend already uses for the player-level values.
  for (const row of Object.values(teams)) {
    row.distance_carried = Math.round(row.distance_carried * 10) / 10;
    addDerivedTallyFields(row);
  }
  return Object.values(teams);
}

function teamBoard(teamTallies, field, limit = 10) {
  return teamTallies
    .filter((r) => Number(r[field] || 0) > 0)
    .sort((a, b) => Number(b[field]) - Number(a[field]) || String(a.team).localeCompare(String(b.team)))
    .slice(0, limit);
}

const STAT_CATEGORIES = [
  ["attacking", "Attacking"],
  ["creation", "Creation"],
  ["control", "Control"],
  ["defending", "Defending"],
];

const STAT_BOARDS = [
  { key: "top_goalscorers", field: "goals", title: "Top goalscorers", label: "G", empty: "No goals recorded yet — play matches on the tactic board.", category: "attacking" },
  { key: "top_shooters", field: "shots", title: "Most shots", label: "Shots", empty: "No shots recorded yet.", category: "attacking" },
  { key: "top_big_chances_missed", field: "big_chances_missed", title: "Most big chances missed", label: "BCM", empty: "No big chances missed yet.", category: "attacking" },
  { key: "top_assisters", field: "assists", title: "Top assisters", label: "A", empty: "No assists recorded yet — assists count when a goal follows a teammate's pass.", category: "creation" },
  { key: "top_key_passers", field: "key_passes", title: "Most key passes", label: "KP", empty: "No key passes recorded yet.", category: "creation" },
  { key: "top_big_chances_created", field: "big_chances_created", title: "Most big chances created", label: "BCC", empty: "No big chances created yet.", category: "creation" },
  { key: "top_dribblers", field: "dribbles", title: "Most dribbles", label: "Dribbles", empty: "No completed take-ons recorded yet.", category: "control" },
  { key: "top_distance_carried", field: "distance_carried", title: "Most distance carried", label: "Metres", empty: "No carries recorded yet.", suffix: "m", category: "control" },
  { key: "top_clean_sheets", field: "clean_sheets", title: "Most clean sheets", label: "CS", empty: "No clean sheets recorded yet.", category: "defending" },
  { key: "top_tacklers", field: "tackles", title: "Most tackles", label: "Tackles", empty: "No tackles recorded yet.", category: "defending" },
  { key: "top_interceptors", field: "interceptions", title: "Most interceptions", label: "Int", empty: "No interceptions recorded yet.", category: "defending" },
  { key: "team_ppda", field: "ppda", title: "Best pressing (PPDA)", label: "PPDA", empty: "No matches played yet.", category: "defending", teamOnly: true, sortAsc: true },
  // Conversion/passing stats project.
  { key: "top_xg_overperformers", field: "xg_diff", title: "Goals vs xG (overperformance)", label: "G-xG", empty: "No qualifying shot samples yet.", category: "attacking" },
  { key: "top_finishers", field: "shot_conversion_pct", title: "Best shot conversion", label: "Conv %", empty: "No qualifying shot samples yet.", suffix: "%", category: "attacking" },
  { key: "top_big_chance_takers", field: "big_chance_conversion_pct", title: "Best big-chance conversion", label: "BC Conv %", empty: "No qualifying big-chance samples yet.", suffix: "%", category: "attacking" },
  { key: "top_passers", field: "pass_completion_pct", title: "Best pass completion", label: "Pass %", empty: "No qualifying pass samples yet.", suffix: "%", category: "control" },
  { key: "top_crossers", field: "cross_accuracy_pct", title: "Best cross accuracy", label: "Cross %", empty: "No qualifying cross samples yet.", suffix: "%", category: "creation" },
  { key: "top_through_ball_creators", field: "through_ball_completion_pct", title: "Best through-ball completion", label: "TB %", empty: "No qualifying through-ball samples yet.", suffix: "%", category: "creation" },
  { key: "top_keepers", field: "save_pct", title: "Best save %", label: "Save %", empty: "No qualifying shots-faced samples yet.", suffix: "%", category: "defending" },
  // Discipline/progression stats project.
  { key: "top_cards", field: "cards", title: "Most cards", label: "Cards", empty: "No cards shown yet.", category: "defending" },
  { key: "top_fouls", field: "fouls", title: "Most fouls committed", label: "Fouls", empty: "No fouls recorded yet.", category: "defending" },
  { key: "top_penalty_scorers", field: "penalty_goals", title: "Most penalties scored", label: "Pens", empty: "No penalties scored yet.", category: "attacking" },
  { key: "top_progressive_passers", field: "progressive_passes", title: "Most progressive passes", label: "Prog Passes", empty: "No progressive passes recorded yet.", category: "creation" },
];

// Renders one played-match analysis result into its `.match-analysis-panel`
// -- shared by tournament.js and league_cup.js's analysis-toggle wiring.
function fillAnalysisPanel(matchId, data) {
  const panel = document.querySelector(`.match-analysis-panel[data-match-id="${matchId}"]`);
  if (!panel) return;
  panel.hidden = false;
  const header = `<p class="muted" style="margin:0 0 0.5rem">${esc(data.home || "")} ${esc(data.score || "")} ${esc(data.away || "")}</p>`;
  const analysisHtml = typeof renderAnalysis === "function" ? renderAnalysis(data.analysis) : "";
  const aiHtml = typeof renderAiVerdict === "function" ? renderAiVerdict(data.ai_verdict) : "";
  const aiCommentaryHtml = typeof renderAiCommentary === "function" ? renderAiCommentary(data.ai_commentary) : "";
  const squadHtml = typeof renderSquadAnalysis === "function" ? renderSquadAnalysis(data.squad_analysis, data.matchup) : "";
  panel.innerHTML = header + (analysisHtml || `<p class="muted">No analysis text.</p>`) + aiHtml + aiCommentaryHtml + (squadHtml || "");
  const btn = document.querySelector(`.view-analysis-btn[data-match-id="${matchId}"]`);
  if (btn) btn.textContent = "Hide analysis";
}

function pct(v) {
  return v == null ? "—" : `${Number(v).toFixed(1)}%`;
}

function num(v, d = 2) {
  return v == null ? "—" : Number(v).toFixed(d);
}

function metric(label, value) {
  return `<div class="metric"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`;
}

/** Brief explanations for unit ratings (from team_ratings.py). */
const UNIT_RATING_HELP = {
  attack: "Combined forward threat: 56% finishing + 44% chance creation, weighted by each player’s role in your formation.",
  finishing: "Shooting quality — npxG/xG, shots on target, big chances, dribbles, plus progressive buildup in attack chains.",
  chance_creation: "Supply into the box — key passes, xA, xG buildup/chain, assists, and big chances created.",
  midfield: "DM/CM/AM slots only — passing progression, chance creation, tackles/interceptions, minus possession lost.",
  defence: "Back-line stopping power — tackles, interceptions, clearances, plus FotMob duel/aerial wins and dribble-based press resistance.",
  midfield_defence: "Midfield shield — ball-winning and screening (tackles, interceptions, clearances, duel wins, press resistance).",
  transition_risk: "Counter-attack exposure when fullbacks or wingbacks push up, minus midfield shielding and (in 3-at-the-back) extra centre-back cover behind the wingbacks. Lower is safer.",
  goalkeeper: "Keeper quality — goals prevented, rating, goals conceded, pass accuracy; low-minute keepers are regressed toward average.",
};

const TEAM_COMPOSITE_HELP = {
  creativity: "Whole-XI chance creation — key passes, xA, big chances, and xG chain across all starters.",
  midfield_control: "Team shape in the middle third — blends midfield-slot unit, possession, shield, and pressing.",
  possession_control: "Ball retention across the XI — passing volume, accuracy, buildup, and turnovers.",
  finishing_threat: "Team-wide goal threat — forward xG/shots blended with the finishing unit.",
  defensive_solidity: "Structural defending — back-line stats, unit defence, goalkeeper, plus duel-win and aerial signals.",
  attacking_effectiveness: "Overall attacking output — forward threat plus attack unit rating.",
  pressing_intensity: "Collective pressing — tackles/interceptions across the XI, enhanced by FotMob duel-win % from mids and defenders.",
  press_resistance: "Build-up under pressure — avg dribbles90 × dribble success % from defenders and midfielders (Sofascore).",
  transition_threat: "Counter-attacking dribble threat from forwards and midfielders.",
  aerial_defence: "Aerial/clearance strength from defenders (FotMob aerials when available).",
  overall: "Weighted blend of team-profile composites.",
};

const TIER_LABELS = {
  strength: "Strength",
  moderate_strength: "Moderate strength",
  balanced: "Balanced",
  moderate_weakness: "Moderate weakness",
  weakness: "Weakness",
};

const TIER_ORDER = ["strength", "moderate_strength", "balanced", "moderate_weakness", "weakness"];

const SQUAD_SECTION_HELP = {
  Defence: "Structural defending — back line, midfield shield, xGA suppression, aerial defence, and transition safety.",
  "Squad depth": "Bench composition — standout substitutes by per-90 numbers. Informational only, does not affect ratings.",
};

// Mirrors analysis_explainer.py's _PERCENTILE_TIER_THRESHOLDS / _classify_tier
// / _ordinal exactly, so the badge's tier color always agrees with the
// tier_labels text generated server-side for the same percentile value.
const PCT_TIER_THRESHOLDS = { strength: 85, moderate_strength: 65, moderate_weakness: 35, weakness: 15 };
const MIN_LEAGUE_SIZE_FOR_PERCENTILE = 4;

function pctTierClass(pct) {
  if (pct >= PCT_TIER_THRESHOLDS.strength) return "pct-strength";
  if (pct >= PCT_TIER_THRESHOLDS.moderate_strength) return "pct-moderate_strength";
  if (pct <= PCT_TIER_THRESHOLDS.weakness) return "pct-weakness";
  if (pct <= PCT_TIER_THRESHOLDS.moderate_weakness) return "pct-moderate_weakness";
  return "pct-balanced";
}

function ordinal(n) {
  const r = Math.round(n);
  const mod100 = r % 100;
  if (mod100 >= 10 && mod100 <= 20) return `${r}th`;
  const suffix = { 1: "st", 2: "nd", 3: "rd" }[r % 10] || "th";
  return `${r}${suffix}`;
}

function pctPill(key, percentiles, leagueSize) {
  if (!percentiles || !leagueSize || leagueSize < MIN_LEAGUE_SIZE_FOR_PERCENTILE) return "";
  const pct = percentiles[key];
  if (pct == null) return "";
  return `<span class="pct-pill ${pctTierClass(pct)}">${ordinal(pct)} of ${leagueSize}</span>`;
}

function unitMetric(label, value, noteKey, pctHtml) {
  const note = UNIT_RATING_HELP[noteKey];
  const noteHtml = note ? `<p class="metric-note" title="${esc(note)}">${esc(note)}</p>` : "";
  return `<div class="metric metric-explained"><div class="metric-head"><div class="label">${esc(label)}</div>${pctHtml || ""}</div><div class="value">${esc(value)}</div>${noteHtml}</div>`;
}

function renderUnits(u, options = {}) {
  if (!u) return "";
  const showNotes = options.showNotes !== false;
  const pct = options.percentiles;
  const leagueSize = options.leagueSize;
  const p = (key) => pctPill(key, pct, leagueSize);
  const grid = showNotes
    ? `
    <div class="metric-grid unit-ratings-grid">
      ${unitMetric("Attack", num(u.attack), "attack", p("attack"))}
      ${unitMetric("Finishing", num(u.finishing), "finishing", p("finishing"))}
      ${unitMetric("Creation", num(u.chance_creation), "chance_creation", p("chance_creation"))}
      ${unitMetric("Midfield", num(u.midfield), "midfield", p("midfield"))}
      ${unitMetric("Defence", num(u.defence), "defence", p("defence"))}
      ${unitMetric("Mid-def", num(u.midfield_defence), "midfield_defence", p("midfield_defence"))}
      ${unitMetric("Trans risk", num(u.transition_risk), "transition_risk", p("transition_risk"))}
      ${unitMetric("GK", num(u.goalkeeper), "goalkeeper", p("goalkeeper"))}
    </div>`
    : `
    <div class="metric-grid">
      ${metric("Attack", num(u.attack))}
      ${metric("Finishing", num(u.finishing))}
      ${metric("Creation", num(u.chance_creation))}
      ${metric("Midfield", num(u.midfield))}
      ${metric("Defence", num(u.defence))}
      ${metric("Mid-def", num(u.midfield_defence))}
      ${metric("Trans risk", num(u.transition_risk))}
      ${metric("GK", num(u.goalkeeper))}
    </div>`;
  if (!showNotes) return grid;
  return `
    <div class="unit-ratings-block">
      <p class="muted unit-ratings-intro">Unit ratings (0–1) from slot-relevant players only — no whole-XI dilution. Hover a tile for the full note.${
        leagueSize >= MIN_LEAGUE_SIZE_FOR_PERCENTILE ? ` Percentile is this squad's rank against the other ${leagueSize} squads.` : ""
      }</p>
      ${grid}
    </div>`;
}

function teamCompositeMetric(label, value, noteKey, pctHtml) {
  const note = TEAM_COMPOSITE_HELP[noteKey];
  const noteHtml = note ? `<p class="metric-note" title="${esc(note)}">${esc(note)}</p>` : "";
  return `<div class="metric metric-explained"><div class="metric-head"><div class="label">${esc(label)}</div>${pctHtml || ""}</div><div class="value">${esc(value)}</div>${noteHtml}</div>`;
}

function renderTeamComposites(tc, options = {}) {
  if (!tc) return "";
  const showNotes = options.showNotes !== false;
  const pct = options.percentiles;
  const leagueSize = options.leagueSize;
  const p = (key) => pctPill(key, pct, leagueSize);
  const grid = showNotes
    ? `
    <div class="metric-grid team-profile-grid">
      ${teamCompositeMetric("Creativity", num(tc.creativity), "creativity", p("creativity"))}
      ${teamCompositeMetric("Mid control", num(tc.midfield_control), "midfield_control", p("midfield_control"))}
      ${teamCompositeMetric("Possession", num(tc.possession_control), "possession_control", p("possession_control"))}
      ${teamCompositeMetric("Fin threat", num(tc.finishing_threat), "finishing_threat", p("finishing_threat"))}
      ${teamCompositeMetric("Def solidity", num(tc.defensive_solidity), "defensive_solidity", p("defensive_solidity"))}
      ${teamCompositeMetric("Atk effect", num(tc.attacking_effectiveness), "attacking_effectiveness", p("attacking_effectiveness"))}
      ${teamCompositeMetric("Pressing", num(tc.pressing_intensity), "pressing_intensity", p("pressing_intensity"))}
      ${teamCompositeMetric("Press resist", num(tc.press_resistance), "press_resistance", p("press_resistance"))}
      ${teamCompositeMetric("Trans threat", num(tc.transition_threat), "transition_threat", p("transition_threat"))}
      ${teamCompositeMetric("Aerial def", num(tc.aerial_defence), "aerial_defence", p("aerial_defence"))}
    </div>`
    : `
    <div class="metric-grid">
      ${metric("Creativity", num(tc.creativity))}
      ${metric("Mid control", num(tc.midfield_control))}
      ${metric("Possession", num(tc.possession_control))}
      ${metric("Fin threat", num(tc.finishing_threat))}
      ${metric("Def solidity", num(tc.defensive_solidity))}
      ${metric("Atk effect", num(tc.attacking_effectiveness))}
      ${metric("Pressing", num(tc.pressing_intensity))}
      ${metric("Press resist", num(tc.press_resistance))}
      ${metric("Trans threat", num(tc.transition_threat))}
      ${metric("Aerial def", num(tc.aerial_defence))}
    </div>`;
  if (!showNotes) return grid;
  return `
    <div class="team-profile-block">
      <p class="muted team-profile-intro">Team profile composites (0–1) across the full starting XI shape.</p>
      ${grid}
    </div>`;
}

function renderTierLabels(tierLabels) {
  if (!tierLabels) return "";
  const blocks = TIER_ORDER.map((tier) => {
    const items = tierLabels[tier] || [];
    if (!items.length) return "";
    const lis = items.map((t) => `<li>${esc(t)}</li>`).join("");
    return `<div class="tier-block tier-${tier}"><h4 class="tier-heading">${esc(TIER_LABELS[tier])}</h4><ul class="analysis-bullets tier-list">${lis}</ul></div>`;
  }).join("");
  if (!blocks.trim()) return "";
  return `<div class="tier-labels" style="margin-top:0.75rem">${blocks}</div>`;
}

function renderScoutComparisons(rows, title) {
  if (!rows?.length) return "";
  const body = rows
    .map((c) => {
      const cls = c.verdict === "advantage" ? "scout-adv" : c.verdict === "disadvantage" ? "scout-dis" : "scout-even";
      const vals =
        c.my_value != null && c.opp_value != null
          ? ` <span class="muted">(you ${num(c.my_value)} · them ${num(c.opp_value)})</span>`
          : "";
      return `<div class="scout-row ${cls}"><span class="scout-area">${esc(c.area)}</span><span>${esc(c.summary)}${vals}</span></div>`;
    })
    .join("");
  return `<h4 style="font-size:0.85rem;margin:1rem 0 0.35rem">${esc(title)}</h4><div class="scout-comparisons">${body}</div>`;
}

function renderLineup(team) {
  return team.lineup
    .map((p) => `<div class="slot-row"><span class="rl-slot">${esc(p.slot)}</span><span>${esc(p.player)}</span></div>`)
    .join("");
}

function renderSquadAnalysis(squadAnalysis, matchup) {
  if (!squadAnalysis) return "";

  function renderSide(side, team, sideKey) {
    if (!side) return "";
    return renderSingleSquadEval(side, team, sideKey);
  }

  return `
    <section class="card" style="margin-top:1rem">
      <h2>Squad strengths &amp; weaknesses</h2>
      <p class="muted">Per-team breakdown from player stats, formation fit, unit ratings, and bench depth.</p>
      <div class="grid grid-2" style="margin-top:1rem">
        ${renderSide(squadAnalysis.home, matchup?.home, "home")}
        ${renderSide(squadAnalysis.away, matchup?.away, "away")}
      </div>
    </section>`;
}

function renderSingleSquadEval(evaluation, team, sideKey) {
  if (!evaluation) return "";
  const side = evaluation;
  const sections = (side.sections || [])
    .map((s) => {
      const bullets = (s.bullets || []).map((b) => `<li>${esc(b)}</li>`).join("");
      const sectionHelp = SQUAD_SECTION_HELP[s.title];
      const helpHtml = sectionHelp
        ? `<p class="section-note muted">${esc(sectionHelp)}</p>`
        : "";
      return `<div class="squad-section"><h4>${esc(s.title)}</h4>${helpHtml}<ul class="analysis-bullets">${bullets}</ul></div>`;
    })
    .join("");
  const tierHtml = renderTierLabels(side.tier_labels);
  const lineup = team?.lineup?.length
    ? `<div class="lineup-mini report-lineup" style="margin-top:0.75rem">${renderLineup(team)}</div>`
    : "";
  const units = side.units
    ? renderUnits(side.units, { showNotes: true, percentiles: side.percentiles, leagueSize: side.league_size })
    : "";
  const teamProfile = side.team_composites
    ? renderTeamComposites(side.team_composites, {
        showNotes: true,
        percentiles: side.percentiles,
        leagueSize: side.league_size,
      })
    : "";
  const headClass = sideKey === "home" ? "home" : sideKey === "away" ? "away" : "";
  return `
    <div class="card squad-card">
      <div class="report-eyebrow">Squad evaluation</div>
      <div class="report-team-head ${headClass}">
        <h3>${esc(side.name)}</h3>
        <span class="rt-formation">${esc(side.formation || team?.formation || "")}</span>
      </div>
      <p class="muted">${esc(side.summary || "")}</p>
      <h4 style="font-size:0.85rem;margin:0.75rem 0 0.25rem">Unit ratings</h4>
      ${units}
      <h4 style="font-size:0.85rem;margin:1rem 0 0.25rem">Team profile</h4>
      ${teamProfile}
      ${tierHtml}
      ${lineup}
      <div class="squad-sections" style="margin-top:0.75rem">${sections}</div>
    </div>`;
}

function renderTacticalMatchup(tm, myTeamName, opponentName) {
  if (!tm || (!tm.my_biggest_advantage && !tm.their_biggest_advantage)) return "";
  const rows = [
    tm.my_biggest_advantage
      ? { label: `Your biggest advantage`, value: tm.my_biggest_advantage, cls: "tm-good" }
      : null,
    tm.their_biggest_advantage
      ? { label: `Their biggest advantage`, value: tm.their_biggest_advantage, cls: "tm-bad" }
      : null,
    tm.secondary_advantage ? { label: "Also in your favor", value: tm.secondary_advantage, cls: "tm-good" } : null,
    tm.secondary_concern ? { label: "Also a concern", value: tm.secondary_concern, cls: "tm-bad" } : null,
  ].filter(Boolean);
  const grid = rows
    .map((r) => `<div class="tm-row ${r.cls}"><span class="tm-label">${esc(r.label)}</span><span>${esc(r.value)}</span></div>`)
    .join("");
  const routes = [tm.exploit_route, tm.key_concern].filter(Boolean);
  return `
    <div class="card scout-card tactical-matchup-card">
      <div class="report-eyebrow">Tactical matchup</div>
      <h3 style="margin:0 0 0.5rem">${esc(myTeamName)} vs ${esc(opponentName)}</h3>
      <div class="tm-grid">${grid}</div>
      ${routes.length ? `<ul class="analysis-bullets" style="margin-top:0.85rem">${routes.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
    </div>`;
}

function renderKeyBattles(battles) {
  if (!battles?.length) return "";
  const verdictLabel = { advantage: "You win this", disadvantage: "They win this", even: "Evenly matched" };
  const rows = battles
    .map((b) => {
      const cls = b.verdict === "advantage" ? "kb-adv" : b.verdict === "disadvantage" ? "kb-dis" : "kb-even";
      return `<div class="kb-row ${cls}">
        <div class="kb-players">
          <span>${esc(b.my_player)} <span class="muted">(${esc(b.my_slot)})</span></span>
          <span class="kb-vs">vs</span>
          <span>${esc(b.opp_player)} <span class="muted">(${esc(b.opp_slot)})</span></span>
        </div>
        <span class="kb-verdict">${esc(verdictLabel[b.verdict] || b.verdict)}</span>
      </div>`;
    })
    .join("");
  return `
    <div class="card scout-card">
      <div class="report-eyebrow">Key battles</div>
      <p class="muted" style="margin:0 0 0.75rem">Your starters against whoever's most likely to actually face them, read off existing per-90 stats — a real signal, not a precise prediction.</p>
      <div class="kb-list">${rows}</div>
    </div>`;
}

function renderGamePlan(plan) {
  if (!plan) return "";
  const rows = [
    ["In possession", plan.in_possession],
    ["Out of possession", plan.out_of_possession],
    ["Transitions", plan.transitions],
    ["Biggest danger", plan.biggest_danger],
  ].filter(([, v]) => v);
  return `
    <div class="card scout-card ai-verdict-card">
      <h2><span class="ai-badge">AI</span>${esc(plan.headline || "Game plan")}</h2>
      ${rows.map(([label, text]) => `<div class="analysis-block"><h3>${esc(label)}</h3><p>${esc(text)}</p></div>`).join("")}
    </div>`;
}

function renderScoutReport(scout) {
  if (!scout) return "";
  const notes = (scout.scout_notes || []).map((n) => `<li>${esc(n)}</li>`).join("");
  const roster = scout.roster_overview || {};
  const bench = (roster.bench || []).length
    ? `<p class="muted" style="margin-top:0.5rem">Bench: ${esc((roster.bench || []).join(", "))}</p>`
    : "";
  const lineup = scout.expected_lineup?.length
    ? `<div class="lineup-mini">${renderLineup({ lineup: scout.expected_lineup })}</div>`
    : "";
  const oppUnits = scout.opponent_units ? renderUnits(scout.opponent_units, { showNotes: false }) : "";
  const oppTeam = scout.opponent_team_composites
    ? renderTeamComposites(scout.opponent_team_composites, { showNotes: false })
    : "";
  const unitCmp = renderScoutComparisons(
    scout.unit_comparisons || scout.comparisons,
    `Unit ratings vs ${scout.my_team}`
  );
  const teamCmp = renderScoutComparisons(scout.team_comparisons, `Team profile vs ${scout.my_team}`);
  const tacticalMatchup = renderTacticalMatchup(scout.tactical_matchup, scout.my_team, scout.opponent);
  const keyBattles = renderKeyBattles(scout.key_battles);
  const customBadge = scout.opponent_lineup_is_custom
    ? `<span class="badge muted" style="margin-left:0.5rem">Custom XI you set up</span>`
    : `<span class="badge muted" style="margin-left:0.5rem">Their saved lineup</span>`;
  return `
    ${tacticalMatchup}
    ${keyBattles}
    <div class="card scout-card">
      <h3>${esc(scout.opponent)} <span class="muted">${esc(scout.formation)}</span>${customBadge}</h3>
      <p class="muted">${esc(scout.summary || "")}</p>
      <h4 style="font-size:0.85rem;margin:1rem 0 0.35rem">Lineup scouted</h4>
      ${lineup}
      ${bench}
      <h4 style="font-size:0.85rem;margin:1rem 0 0.35rem">Their unit ratings</h4>
      ${oppUnits}
      <h4 style="font-size:0.85rem;margin:1rem 0 0.35rem">Their team profile</h4>
      ${oppTeam}
      ${unitCmp}
      ${teamCmp}
      ${notes ? `<h4 style="font-size:0.85rem;margin:1rem 0 0.35rem">Scout notes</h4><ul class="analysis-bullets">${notes}</ul>` : ""}
    </div>
    <div id="gamePlanContainer" style="margin-top:1rem"></div>`;
}

function renderAnalysis(analysis) {
  if (!analysis) return "";
  const factors = (analysis.key_factors || [])
    .map(
      (f) =>
        `<li><strong>${esc(f.factor)}</strong> — ${esc(f.explanation)} <span class="muted">(H ${num(f.home)} / A ${num(f.away)})</span></li>`
    )
    .join("");

  const sections = (analysis.sections || [])
    .map((s) => {
      const paras = (s.paragraphs || []).map((p) => `<p>${esc(p)}</p>`).join("");
      const bullets = (s.bullets || []).length
        ? `<ul class="analysis-bullets">${s.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>`
        : "";
      return `<div class="analysis-block"><h3>${esc(s.title)}</h3>${paras}${bullets}</div>`;
    })
    .join("");

  const heading = analysis.board_result ? "Match analysis" : "Why this result?";
  const boardXg = analysis.board_result?.xg;
  const boardXgHtml =
    boardXg && (boardXg.home != null || boardXg.away != null)
      ? `<p class="muted" style="margin:0.35rem 0 0">Pin-board live xG: <strong>${esc(
          String(boardXg.home ?? "—")
        )} – ${esc(String(boardXg.away ?? "—"))}</strong> (official chance volume, not the pre-match projection)</p>`
      : "";
  return `
    <section class="card analysis-card" style="margin-top:1rem">
      <h2>${heading}</h2>
      <p class="analysis-verdict">${esc(analysis.summary)}</p>
      ${boardXgHtml}
      ${factors ? `<h3 style="font-size:0.9rem;margin-top:1rem">Key factors</h3><ul class="analysis-bullets">${factors}</ul>` : ""}
      <div class="analysis-sections" style="margin-top:1rem">${sections}</div>
    </section>`;
}

function renderAiVerdict(v) {
  if (!v) return "";
  const takeaways = (v.key_takeaways || []).map((k) => `<li>${esc(k)}</li>`).join("");
  return `
    <section class="card analysis-card ai-verdict-card" style="margin-top:1rem">
      <h2><span class="ai-badge">AI</span>${esc(v.headline || "AI verdict")}</h2>
      <p class="analysis-verdict">${esc(v.verdict || "")}</p>
      ${v.turning_point ? `<div class="analysis-block"><h3>Turning point</h3><p>${esc(v.turning_point)}</p></div>` : ""}
      ${v.tactical_analysis ? `<div class="analysis-block"><h3>Tactical read</h3><p>${esc(v.tactical_analysis)}</p></div>` : ""}
      ${takeaways ? `<ul class="analysis-bullets" style="margin-top:0.75rem">${takeaways}</ul>` : ""}
    </section>`;
}

function renderAiCommentary(c) {
  const paragraphs = c?.narrative || [];
  if (!paragraphs.length) return "";
  const body = paragraphs.map((p) => `<p>${esc(p)}</p>`).join("");
  return `
    <section class="card analysis-card ai-verdict-card" style="margin-top:1rem">
      <h2><span class="ai-badge">AI</span>${esc(c.headline || "Match recap")}</h2>
      <p class="muted" style="margin:0 0 0.75rem">Narrated after the fact from the actual match events — not the live commentary feed above.</p>
      ${body}
    </section>`;
}

function renderMatchdayList(items) {
  return renderMatchdaySession(null);
}

function phaseLabel(phase) {
  const labels = {
    setup: "Pre-match",
    live: "Live",
    running: "Live",
    result: "Full time",
  };
  return labels[phase] || phase || "—";
}

/** Extra line under KO scorelines (FT / AET / pens). */
function knockoutScoreNote(r) {
  if (!r || !r.decided_by || r.decided_by === "ft") return "";
  const bits = [];
  if (r.ft_home_goals != null && r.ft_away_goals != null) {
    bits.push(`90' ${r.ft_home_goals}–${r.ft_away_goals}`);
  }
  if (r.decided_by === "aet") bits.push("after extra time");
  if (r.decided_by === "pens") {
    if (r.pens_home != null && r.pens_away != null) {
      bits.push(`pens ${r.pens_home}–${r.pens_away}`);
    } else {
      bits.push("penalties");
    }
  }
  return bits.length ? `<p class="muted" style="margin:0.2rem 0 0">${bits.join(" · ")}</p>` : "";
}

function renderMatchdayTeamCard(team, label) {
  if (!team) return "";
  const lineup = (team.lineup || [])
    .map((p) => `<div class="slot-row"><span>${esc(p.slot)}</span><span>${esc(p.player)}</span></div>`)
    .join("");
  const prime = team.prime_player ? `<p class="muted">Prime: ${esc(team.prime_player)}</p>` : "";
  const peak = team.peak_season?.player
    ? `<p class="muted">Peak: ${esc(team.peak_season.player)} (${esc(team.peak_season.season || "")})</p>`
    : "";
  return `
    <div class="card">
      <h3>${esc(label)} — ${esc(team.name)}</h3>
      <p class="muted">Formation ${esc(team.formation || "—")}</p>
      ${prime}${peak}
      <div class="lineup-mini">${lineup}</div>
    </div>`;
}

function renderMatchdaySession(status, { isAdmin = false } = {}) {
  const session = status && typeof status === "object" ? status.session ?? null : null;
  if (!status?.active || !session) {
    return `<div class="empty">
      <p>No live match — waiting for admin to Run a fixture</p>
      <p class="muted">When the admin clicks <strong>Run</strong> on a tournament fixture, everyone watches the live tactic board here.</p>
      <p class="muted"><a href="/tournament">View tournament standings</a> · <a href="/squad">Configure your lineup</a></p>
    </div>`;
  }

  const phase = session.phase;
  const badgeClass = phase === "live" || phase === "running" ? "live" : phase === "result" ? "ready" : "";
  const header = `
    <div class="card" style="margin-bottom:1rem">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap">
        <div>
          <h2>${esc(session.home)} vs ${esc(session.away)}</h2>
          <p class="muted">${esc(session.tournament_name || "Tournament")} · ${esc(session.stage || "")} · ${esc(session.fixture_id || "")}</p>
        </div>
        <span class="badge ${badgeClass}">${esc(phaseLabel(phase))}</span>
      </div>
      <p class="muted" style="margin-top:0.5rem">${esc(session.message || "")}</p>
    </div>`;

  const boardMount = `<div class="card" data-matchday-board-card style="margin-top:0.5rem">
      <div id="matchdayHostTakeover" hidden style="margin-bottom:0.75rem"></div>
      <div data-tactic-mount></div>
    </div>`;

  let phaseBody = "";
  if (phase === "setup") {
    const myTeam = getUser();
    const involved = myTeam && (myTeam === session.home || myTeam === session.away);
    const teamsMeta = session.teams_meta || {};
    const unfinalized = [session.home, session.away].filter((t) => teamsMeta[t] && !teamsMeta[t].finalized);
    const warnUnfinalized = unfinalized.length
      ? `<p class="badge error" style="display:inline-block;margin-top:0.75rem">Not finalized: ${unfinalized.map(esc).join(", ")} — <a href="/squad">finalize on Squad hub</a></p>`
      : "";
    const myFinalized = myTeam && teamsMeta[myTeam]?.finalized;
    const myWarn =
      involved && !myFinalized
        ? `<p class="badge error" style="display:inline-block">Your squad is not finalized for this matchday.</p>`
        : involved && myFinalized
          ? `<p class="badge ready" style="display:inline-block">Your squad is finalized ✓</p>`
          : "";
    const squadLink = involved
      ? `<p><a href="/squad" class="btn-link">Configure your lineup on Squad hub</a> and finalize before kick-off.</p>${myWarn}`
      : `<p class="muted">Involved teams can configure and finalize lineups on <a href="/squad">Squad hub</a>.</p>`;
    const adminRun =
      isAdmin || getAdminToken()
        ? `<button type="button" id="matchdayRunBtn" class="btn-primary" style="margin-top:1rem">Start match</button>${
            warnUnfinalized
              ? `<p class="muted" style="margin-top:0.5rem">Admin: ${unfinalized.length} team(s) have not finalized.</p>`
              : ""
          }`
        : `<p class="muted">Waiting for admin to start the match…</p>`;
    phaseBody = `
      <section>
        <h3 style="margin-bottom:0.75rem">Pre-match lineups</h3>
        <div class="grid grid-2">${renderMatchdayTeamCard(session.team_a, "Home")}${renderMatchdayTeamCard(session.team_b, "Away")}</div>
        ${squadLink}
        ${warnUnfinalized && !isAdmin && !getAdminToken() ? warnUnfinalized : ""}
        ${adminRun}
      </section>`;
  } else if (phase === "live" || phase === "running") {
    const waiting =
      session.engine === "tactic_board" || session.board
        ? `<p class="muted" style="margin:0 0 0.75rem">Shared live tactic board — possession and xG update for everyone.</p>`
        : `<p class="muted" style="margin:0 0 0.75rem">Simulation in progress…</p>`;
    phaseBody = `
      <div>
        ${waiting}
        ${session.board || session.engine === "tactic_board" ? boardMount : `<div class="card"><div class="grid grid-2">${renderMatchdayTeamCard(session.team_a, "Home")}${renderMatchdayTeamCard(session.team_b, "Away")}</div></div>`}
      </div>`;
  } else if (phase === "result") {
    const r = session.result || {};
    const topScores = (r.top_scorelines || [])
      .map((row) => `${esc(row.score)} (${num(row.pct, 1)}%)`)
      .join(", ");
    const expLink = r.experiment_id
      ? `<p><a href="/experiment/${esc(r.experiment_id)}?from=matchday">Full match analysis</a></p>`
      : "";
    // League + Cup: friendlies never get a deterministic analysis report
    // (commentary, attached at completion time, is the whole report);
    // league/cup matches do get one, generated on click same as the
    // groups+knockout format, just via the league-cup-specific endpoint.
    const isFriendlyStage = session?.stage === "friendly";
    const analysisBtnLabel =
      r.has_analysis || r.analysis || r.report
        ? "See analysis"
        : isFriendlyStage
          ? r.ai_commentary
            ? "See commentary"
            : "No commentary"
          : "Generate analysis";
    const analysisBtn = `<button type="button" class="btn-primary" id="matchdaySeeAnalysisBtn" style="margin-top:0.75rem">${analysisBtnLabel}</button>`;
    const dismissBtn =
      isAdmin || getAdminToken()
        ? `<button type="button" id="matchdayDismissBtn" class="btn-ghost" style="margin-top:1rem">Dismiss</button>`
        : "";
    const watchCard =
      typeof TacticBoard !== "undefined" && TacticBoard.renderWatchCard
        ? TacticBoard.renderWatchCard()
        : "";
    const scoreBits =
      r.engine === "tactic_board" || (!r.home_win_pct && r.score)
        ? `<p class="muted">Official pin-board result${r.expected_xg ? ` · xG ${esc(String(r.expected_xg.home))}–${esc(String(r.expected_xg.away))}` : ""}</p>`
        : `<p><strong>${esc(r.winner || "Draw")}</strong> · ${pct(r.home_win_pct)} home · ${pct(r.draw_pct)} draw · ${pct(r.away_win_pct)} away</p>`;
    phaseBody = `
      <div class="card">
        <h3 style="font-size:2rem;margin:0">${esc(r.score || "—")}</h3>
        ${knockoutScoreNote(r)}
        ${scoreBits}
        ${r.winner != null ? `<p><strong>${esc(r.winner || "Draw")}</strong></p>` : ""}
        ${topScores ? `<p class="muted">Top scorelines: ${topScores}</p>` : ""}
        <p class="muted"><a href="/tournament?id=${esc(session.tournament_id)}">Updated on tournament table</a></p>
        ${expLink}
        ${analysisBtn}
        ${dismissBtn}
      </div>
      ${watchCard}
      <div id="matchdayAnalysisPanel" hidden style="margin-top:1rem"></div>`;
  }

  return header + phaseBody;
}

let _matchdayPollStarted = false;

function startMatchdayBroadcastPoll() {
  if (_matchdayPollStarted) return;
  if (!getToken() && !getAdminToken()) return;
  _matchdayPollStarted = true;
  setInterval(async () => {
    if (window.location.pathname === "/matchday") return;
    try {
      const data = await api("/api/matchday/active");
      if (data?.active && data?.redirect) {
        window.location.href = "/matchday";
      }
    } catch (_) {}
  }, 3000);
}

if (typeof document !== "undefined" && (getToken() || getAdminToken())) {
  startMatchdayBroadcastPoll();
}

function renderExperimentList(items, { showDelete = false } = {}) {
  if (!items.length) {
    return `<div class="empty"><p>No experiments yet.</p><p><a href="/lab">Create your first matchup</a></p></div>`;
  }
  const deleteHeader = showDelete ? "<th>Actions</th>" : "";
  const rows = items
    .map((e) => {
      const xg =
        e.expected_xg_home != null
          ? `xG ${e.expected_xg_home}–${e.expected_xg_away}`
          : "—";
      const outcome =
        e.status === "ready"
          ? `${pct(e.home_win_pct)} / ${pct(e.away_win_pct)}`
          : esc(e.message || e.status);
      const deleteCell = showDelete
        ? `<td><button type="button" class="btn-ghost delete-exp" data-id="${esc(e.id)}" data-label="${esc(e.team_a_name)} vs ${esc(e.team_b_name)}">Delete</button></td>`
        : "";
      return `<tr>
        <td><a href="/experiment/${esc(e.id)}">${esc(e.team_a_name)} vs ${esc(e.team_b_name)}</a></td>
        <td class="muted">${esc(e.team_a_formation)} / ${esc(e.team_b_formation)}</td>
        <td><span class="badge ${esc(e.status)}">${esc(e.status)}</span></td>
        <td>${xg}</td>
        <td class="muted">${outcome}</td>
        ${deleteCell}
      </tr>`;
    })
    .join("");
  return `
    <div class="card">
      <h2>Your experiments</h2>
      <div class="report-table-wrap">
        <table>
          <thead><tr><th>Matchup</th><th>Formations</th><th>Status</th><th>xG</th><th>Result</th>${deleteHeader}</tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
}
