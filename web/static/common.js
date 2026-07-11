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
  Attack: "How your XI generates shots and xG — effectiveness index, chance creation, and the finishing vs creation split.",
  Midfield: "Control of the middle — midfield unit rating (DM/CM/AM slots only), possession, pass completion, and pressing intensity.",
  Defence: "Structural defending — back line, midfield shield, xGA suppression, aerial defence, and transition safety.",
  "Formation fit": "How well each starter’s stats suit their slot in your chosen formation (0–1 per player).",
  "Squad depth": "Bench quality — whether substitutes add small boosts to attack, creation, or defence.",
  "Team profile": "Whole-XI composite scores — creativity, midfield control, possession, and finishing threat across all starters.",
};

function unitMetric(label, value, noteKey) {
  const note = UNIT_RATING_HELP[noteKey];
  const noteHtml = note ? `<p class="metric-note" title="${esc(note)}">${esc(note)}</p>` : "";
  return `<div class="metric metric-explained"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div>${noteHtml}</div>`;
}

function renderUnits(u, options = {}) {
  if (!u) return "";
  const showNotes = options.showNotes !== false;
  const grid = showNotes
    ? `
    <div class="metric-grid unit-ratings-grid">
      ${unitMetric("Attack", num(u.attack), "attack")}
      ${unitMetric("Finishing", num(u.finishing), "finishing")}
      ${unitMetric("Creation", num(u.chance_creation), "chance_creation")}
      ${unitMetric("Midfield", num(u.midfield), "midfield")}
      ${unitMetric("Defence", num(u.defence), "defence")}
      ${unitMetric("Mid-def", num(u.midfield_defence), "midfield_defence")}
      ${unitMetric("Trans risk", num(u.transition_risk), "transition_risk")}
      ${unitMetric("GK", num(u.goalkeeper), "goalkeeper")}
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
      <p class="muted unit-ratings-intro">Unit ratings (0–1) from slot-relevant players only — no whole-XI dilution. Hover a tile for the full note.</p>
      ${grid}
    </div>`;
}

function teamCompositeMetric(label, value, noteKey) {
  const note = TEAM_COMPOSITE_HELP[noteKey];
  const noteHtml = note ? `<p class="metric-note" title="${esc(note)}">${esc(note)}</p>` : "";
  return `<div class="metric metric-explained"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div>${noteHtml}</div>`;
}

function renderTeamComposites(tc, options = {}) {
  if (!tc) return "";
  const showNotes = options.showNotes !== false;
  const grid = showNotes
    ? `
    <div class="metric-grid team-profile-grid">
      ${teamCompositeMetric("Creativity", num(tc.creativity), "creativity")}
      ${teamCompositeMetric("Mid control", num(tc.midfield_control), "midfield_control")}
      ${teamCompositeMetric("Possession", num(tc.possession_control), "possession_control")}
      ${teamCompositeMetric("Fin threat", num(tc.finishing_threat), "finishing_threat")}
      ${teamCompositeMetric("Def solidity", num(tc.defensive_solidity), "defensive_solidity")}
      ${teamCompositeMetric("Atk effect", num(tc.attacking_effectiveness), "attacking_effectiveness")}
      ${teamCompositeMetric("Pressing", num(tc.pressing_intensity), "pressing_intensity")}
      ${teamCompositeMetric("Press resist", num(tc.press_resistance), "press_resistance")}
      ${teamCompositeMetric("Trans threat", num(tc.transition_threat), "transition_threat")}
      ${teamCompositeMetric("Aerial def", num(tc.aerial_defence), "aerial_defence")}
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

function barRow(label, value, max = 100) {
  const w = Math.min(100, (Number(value) / max) * 100);
  return `<div class="bar-row"><span style="width:5rem">${esc(label)}</span><div class="bar-track"><div class="bar-fill" style="width:${w}%"></div></div><span style="width:3rem;text-align:right">${esc(value)}%</span></div>`;
}

function renderLineup(team) {
  return team.lineup
    .map((p) => `<div class="slot-row"><span>${esc(p.slot)}</span><span>${esc(p.player)}</span></div>`)
    .join("");
}

function renderTeamProfile(side, teamName) {
  const ext = side.extended;
  const u = ext.units;
  const fb = side.fullbacks;
  const fbRows = (fb.fullbacks || [])
    .map(
      (f) =>
        `<tr><td>${esc(f.player)}</td><td>${esc(f.slot)}</td><td>${f.xa90}</td><td>${f.creation_score}</td><td>${f.attack_exposure}</td></tr>`
    )
    .join("");

  return `
    <div class="card">
      <h3>${esc(teamName)}</h3>
      ${renderUnits(u, { showNotes: false })}
      <p class="muted" style="margin:0.75rem 0 0">
        Possession ${num(ext.possession_control)} · Chance creation ${num(ext.chance_creation)} ·
        Fit ${num(ext.formation_fit)} · xGA suppress ${num(ext.xga_suppression, 3)}
      </p>
      <p class="muted">Raw xG: fin ${ext.xg_split?.finishing} + create ${ext.xg_split?.creation} = ${ext.xg_split?.total_raw}</p>
      ${fbRows ? `<h3 style="margin-top:1rem;font-size:0.9rem">Fullbacks</h3>
        <table><thead><tr><th>Player</th><th>Slot</th><th>xA</th><th>Create</th><th>Exposure</th></tr></thead><tbody>${fbRows}</tbody></table>
        <p class="muted">Transition risk ${num(fb.transition_risk, 3)}</p>` : ""}
    </div>`;
}

function renderSquadAnalysis(squadAnalysis) {
  if (!squadAnalysis) return "";

  function renderSide(side) {
    if (!side) return "";
    return renderSingleSquadEval(side);
  }

  return `
    <section class="card" style="margin-top:1rem">
      <h2>Squad strengths &amp; weaknesses</h2>
      <p class="muted">Per-team breakdown from player stats, formation fit, unit ratings, and bench depth.</p>
      <div class="grid grid-2" style="margin-top:1rem">
        ${renderSide(squadAnalysis.home)}
        ${renderSide(squadAnalysis.away)}
      </div>
    </section>`;
}

function renderSingleSquadEval(evaluation, team) {
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
    ? `<div class="lineup-mini" style="margin-top:0.75rem">${renderLineup(team)}</div>`
    : "";
  const units = side.units ? renderUnits(side.units, { showNotes: true }) : "";
  const teamProfile = side.team_composites ? renderTeamComposites(side.team_composites, { showNotes: true }) : "";
  return `
    <div class="card squad-card">
      <h2 style="margin-bottom:0.5rem">Squad evaluation</h2>
      <h3>${esc(side.name)} <span class="muted">${esc(side.formation || team?.formation || "")}</span></h3>
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
  return `
    <div class="card scout-card">
      <h3>${esc(scout.opponent)} <span class="muted">expected ${esc(scout.formation)}</span></h3>
      <p class="muted">${esc(scout.summary || "")}</p>
      <h4 style="font-size:0.85rem;margin:1rem 0 0.35rem">Expected lineup</h4>
      ${lineup}
      ${bench}
      <h4 style="font-size:0.85rem;margin:1rem 0 0.35rem">Their unit ratings</h4>
      ${oppUnits}
      <h4 style="font-size:0.85rem;margin:1rem 0 0.35rem">Their team profile</h4>
      ${oppTeam}
      ${unitCmp}
      ${teamCmp}
      ${notes ? `<h4 style="font-size:0.85rem;margin:1rem 0 0.35rem">Scout notes</h4><ul class="analysis-bullets">${notes}</ul>` : ""}
    </div>`;
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
  return `
    <section class="card analysis-card" style="margin-top:1rem">
      <h2>${heading}</h2>
      <p class="analysis-verdict">${esc(analysis.summary)}</p>
      ${factors ? `<h3 style="font-size:0.9rem;margin-top:1rem">Key factors</h3><ul class="analysis-bullets">${factors}</ul>` : ""}
      <div class="analysis-sections" style="margin-top:1rem">${sections}</div>
    </section>`;
}

function renderReport(report, matchup) {
  const mc = report.monte_carlo;
  const home = matchup.home.name;
  const away = matchup.away.name;
  const topScores = (mc.scorelines || [])
    .slice(0, 8)
    .map((r) => barRow(r.score, r.pct, 10))
    .join("");

  const sample = report.sample_match;
  let sampleHtml = "";
  if (sample) {
    sampleHtml = `
      <div class="card">
        <h2>Sample match</h2>
        <p style="font-size:1.35rem;font-weight:700;text-align:center">
          ${esc(sample.home.team)} <strong>${sample.home.goals} – ${sample.away.goals}</strong> ${esc(sample.away.team)}
        </p>
        <p class="muted" style="text-align:center">xG ${sample.home.xg} – ${sample.away.xg} · Winner: ${esc(sample.winner || "Draw")}</p>
      </div>`;
  }

  const watchCard =
    typeof TacticBoard !== "undefined" && TacticBoard.renderWatchCard
      ? TacticBoard.renderWatchCard()
      : "";

  return `
    <section class="card scoreboard">
      <div>
        <div class="team-name home">${esc(home)}</div>
        <div class="muted">${esc(matchup.home.formation)}</div>
      </div>
      <div>
        <div style="font-size:0.85rem;color:var(--muted)">Expected xG</div>
        <div style="font-size:1.6rem;font-weight:800">${mc.expected_xg.home} – ${mc.expected_xg.away}</div>
        <div class="muted">Avg goals ${mc.home_goals_avg} – ${mc.away_goals_avg}</div>
      </div>
      <div>
        <div class="team-name away">${esc(away)}</div>
        <div class="muted">${esc(matchup.away.formation)}</div>
      </div>
    </section>

    ${watchCard}

    ${renderAnalysis(report.analysis)}

    ${renderSquadAnalysis(report.squad_analysis)}

    <section class="card" style="margin-top:1rem">
      <h2>Outcome probabilities (${mc.simulations.toLocaleString()} runs)</h2>
      <div class="prob-bar">
        <div class="prob-seg"><div class="val" style="color:var(--home)">${pct(mc.home_win_pct)}</div><div class="muted">${esc(home)} win</div></div>
        <div class="prob-seg"><div class="val">${pct(mc.draw_pct)}</div><div class="muted">Draw</div></div>
        <div class="prob-seg"><div class="val" style="color:var(--away)">${pct(mc.away_win_pct)}</div><div class="muted">${esc(away)} win</div></div>
      </div>
      <div class="metric-grid" style="margin-top:1rem">
        ${metric("BTTS", pct(mc.btts_pct))}
        ${metric("Over 2.5", pct(mc.over_2_5_pct))}
        ${metric("Total goals", num(mc.total_goals_avg))}
      </div>
    </section>

    <div class="grid grid-2" style="margin-top:1rem">
      <div class="card">
        <h2>Top scorelines</h2>
        ${topScores || "<p class='muted'>—</p>"}
      </div>
      ${sampleHtml}
    </div>

    <div class="grid grid-2" style="margin-top:1rem">
      ${renderTeamProfile(report.profiles.home, home)}
      ${renderTeamProfile(report.profiles.away, away)}
    </div>

    <section class="card lineup" style="margin-top:1rem">
      <div>
        <h2>${esc(home)} lineup</h2>
        ${renderLineup(matchup.home)}
      </div>
      <div>
        <h2>${esc(away)} lineup</h2>
        ${renderLineup(matchup.away)}
      </div>
    </section>
  `;
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
        ? `<p class="muted" style="margin:0 0 0.75rem">Shared live tactic board — possession, xG and momentum update for everyone.</p>`
        : `<p class="muted" style="margin:0 0 0.75rem">Monte Carlo in progress…</p>`;
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
    const analysisBtn =
      r.has_analysis || r.analysis || r.report
        ? `<button type="button" class="btn-primary" id="matchdaySeeAnalysisBtn" style="margin-top:0.75rem">See analysis</button>`
        : "";
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
      <table>
        <thead><tr><th>Matchup</th><th>Formations</th><th>Status</th><th>xG</th><th>Result</th>${deleteHeader}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}
