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
  if (!res.ok) throw new Error(data.detail || res.statusText);
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

function barRow(label, value, max = 100) {
  const w = Math.min(100, (Number(value) / max) * 100);
  return `<div class="bar-row"><span style="width:5rem">${esc(label)}</span><div class="bar-track"><div class="bar-fill" style="width:${w}%"></div></div><span style="width:3rem;text-align:right">${esc(value)}%</span></div>`;
}

function renderLineup(team) {
  return team.lineup
    .map((p) => `<div class="slot-row"><span>${esc(p.slot)}</span><span>${esc(p.player)}</span></div>`)
    .join("");
}

function renderUnits(u) {
  if (!u) return "";
  return `
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
      ${renderUnits(u)}
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
      return `<div class="squad-section"><h4>${esc(s.title)}</h4><ul class="analysis-bullets">${bullets}</ul></div>`;
    })
    .join("");
  const strengths = (side.strengths || []).map((s) => `<li>${esc(s)}</li>`).join("");
  const weaknesses = (side.weaknesses || []).map((s) => `<li>${esc(s)}</li>`).join("");
  const lineup = team?.lineup?.length
    ? `<div class="lineup-mini" style="margin-top:0.75rem">${renderLineup(team)}</div>`
    : "";
  const units = side.units ? renderUnits(side.units) : "";
  return `
    <div class="card squad-card">
      <h2 style="margin-bottom:0.5rem">Squad evaluation</h2>
      <h3>${esc(side.name)} <span class="muted">${esc(side.formation || team?.formation || "")}</span></h3>
      <p class="muted">${esc(side.summary || "")}</p>
      ${units}
      ${lineup}
      ${strengths ? `<h4 style="font-size:0.85rem;margin:0.75rem 0 0.25rem">Strengths</h4><ul class="analysis-bullets strengths">${strengths}</ul>` : ""}
      ${weaknesses ? `<h4 style="font-size:0.85rem;margin:0.75rem 0 0.25rem">Weaknesses</h4><ul class="analysis-bullets weaknesses">${weaknesses}</ul>` : ""}
      <div class="squad-sections" style="margin-top:0.75rem">${sections}</div>
    </div>`;
}

function renderScoutReport(scout) {
  if (!scout) return "";
  const comparisons = (scout.comparisons || [])
    .map((c) => {
      const cls = c.verdict === "advantage" ? "scout-adv" : c.verdict === "disadvantage" ? "scout-dis" : "scout-even";
      return `<div class="scout-row ${cls}"><span class="scout-area">${esc(c.area)}</span><span>${esc(c.summary)}</span></div>`;
    })
    .join("");
  const notes = (scout.scout_notes || []).map((n) => `<li>${esc(n)}</li>`).join("");
  const roster = scout.roster_overview || {};
  const bench = (roster.bench || []).length
    ? `<p class="muted" style="margin-top:0.5rem">Bench: ${esc((roster.bench || []).join(", "))}</p>`
    : "";
  const lineup = scout.expected_lineup?.length
    ? `<div class="lineup-mini">${renderLineup({ lineup: scout.expected_lineup })}</div>`
    : "";
  return `
    <div class="card scout-card">
      <h3>${esc(scout.opponent)} <span class="muted">expected ${esc(scout.formation)}</span></h3>
      <p class="muted">${esc(scout.summary || "")}</p>
      <h4 style="font-size:0.85rem;margin:1rem 0 0.35rem">Expected lineup</h4>
      ${lineup}
      ${bench}
      <h4 style="font-size:0.85rem;margin:1rem 0 0.35rem">Compared to ${esc(scout.my_team)}</h4>
      <div class="scout-comparisons">${comparisons}</div>
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

  return `
    <section class="card analysis-card" style="margin-top:1rem">
      <h2>Why this result?</h2>
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
  if (!items.length) {
    return `<div class="empty"><p>No matchday simulations yet.</p><p class="muted">When the admin runs a match simulation, it will appear here for all logged-in teams.</p></div>`;
  }
  const rows = items
    .map((e) => {
      const xg =
        e.expected_xg_home != null
          ? `xG ${e.expected_xg_home}–${e.expected_xg_away}`
          : "—";
      let outcome = esc(e.message || e.status);
      if (e.status === "ready") {
        outcome = `${pct(e.home_win_pct)} win · ${pct(e.draw_pct)} draw · ${pct(e.away_win_pct)} win`;
      }
      const topScores = (e.top_scorelines || [])
        .map((r) => `${esc(r.score)} (${num(r.pct, 1)}%)`)
        .join(", ");
      const scoresCell = e.status === "ready" && topScores ? topScores : "—";
      const running = e.running || e.status === "running" || e.status === "queued";
      const statusCls = running ? "running" : esc(e.status);
      return `<tr class="${running ? "matchday-live" : ""}">
        <td><a href="/experiment/${esc(e.id)}?from=matchday">${esc(e.team_a_name)} vs ${esc(e.team_b_name)}</a></td>
        <td class="muted">${esc(e.team_a_formation)} / ${esc(e.team_b_formation)}</td>
        <td><span class="badge ${statusCls}">${esc(e.status)}</span></td>
        <td>${xg}</td>
        <td class="muted">${outcome}</td>
        <td class="muted">${scoresCell}</td>
      </tr>`;
    })
    .join("");
  return `
    <div class="card">
      <h2>Admin matchday</h2>
      <p class="muted">Simulations run by the admin. Click a match for full results, scorelines, and analysis. Refreshes every 5 seconds while running.</p>
      <table>
        <thead><tr><th>Matchup</th><th>Formations</th><th>Status</th><th>xG</th><th>Win probs</th><th>Top scores</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function renderExperimentList(items) {
  if (!items.length) {
    return `<div class="empty"><p>No experiments yet.</p><p><a href="/lab">Create your first matchup</a></p></div>`;
  }
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
      return `<tr>
        <td><a href="/experiment/${esc(e.id)}">${esc(e.team_a_name)} vs ${esc(e.team_b_name)}</a></td>
        <td class="muted">${esc(e.team_a_formation)} / ${esc(e.team_b_formation)}</td>
        <td><span class="badge ${esc(e.status)}">${esc(e.status)}</span></td>
        <td>${xg}</td>
        <td class="muted">${outcome}</td>
      </tr>`;
    })
    .join("");
  return `
    <div class="card">
      <h2>Your experiments</h2>
      <table>
        <thead><tr><th>Matchup</th><th>Formations</th><th>Status</th><th>xG</th><th>Result</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}
