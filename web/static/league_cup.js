// League + Cup admin/viewer page: create the competition, run friendlies /
// league / cup fixtures through the shared Matchday board, and browse
// standings, the cup bracket, and League/Cup-toggled stats.

let lcTournament = null;
let lcTournamentId = new URLSearchParams(window.location.search).get("id");
let lcActiveTab = "fixtures";
let lcStatsCompetition = "league";
let lcStatView = "player"; // "player" | "team"
let lcActiveStatCategory = "attacking";
let lcOpenAnalysisMatchId = null;
let lcAnalysisCache = {};

function lcIsAdmin() {
  return Boolean((getToken() && isAdminUser()) || getAdminToken());
}

function lcCompTag(comp) {
  const label = { friendly: "Friendly", league: "League", cup: "Cup" }[comp] || comp;
  const cls = { friendly: "muted", league: "home", cup: "away" }[comp] || "";
  return `<span class="badge ${cls}">${esc(label)}</span>`;
}

async function lcFindActiveTournament() {
  const data = await api("/api/tournament");
  const rows = (data.tournaments || []).filter((r) => r.id); // list is format-agnostic
  // list_tournaments() doesn't expose format in the summary; fetch each
  // candidate (newest first, already sorted) until we find a league_cup one.
  for (const row of rows) {
    try {
      const full = await api(`/api/league-cup/${row.id}`);
      if (full?.tournament) return full.tournament;
    } catch (_) {
      // not a league_cup tournament (or 404) -- keep looking
    }
  }
  return null;
}

async function lcLoad() {
  const app = document.getElementById("app");
  try {
    if (lcTournamentId) {
      const data = await api(`/api/league-cup/${lcTournamentId}`);
      lcTournament = data.tournament;
    } else {
      lcTournament = await lcFindActiveTournament();
      if (lcTournament) lcTournamentId = lcTournament.id;
    }
  } catch (e) {
    app.innerHTML = `<div class="empty"><p>Failed to load: ${esc(e.message)}</p></div>`;
    return;
  }

  document.getElementById("userLabel").textContent = getUser() ? `Signed in as ${getUser()}` : "";
  const statusBadge = document.getElementById("statusBadge");
  if (lcTournament) {
    statusBadge.textContent = lcTournament.status;
    statusBadge.className = `badge ${lcTournament.status === "complete" ? "ready" : "live"}`;
    document.getElementById("leagueCupTitle").textContent = lcTournament.name;
  } else {
    statusBadge.textContent = "—";
  }

  app.innerHTML = lcTournament ? lcRenderApp() : lcRenderCreateForm();
  lcWire();
}

// ---------------------------------------------------------------------------
// Create form (admin, no active tournament yet)
// ---------------------------------------------------------------------------

function lcRenderCreateForm() {
  if (!lcIsAdmin()) {
    return `<div class="empty"><p>No League + Cup competition has been created yet.</p><p class="muted">Ask an admin to set one up.</p></div>`;
  }
  const rows = Array.from({ length: 10 }, (_, i) => `
    <div>
      <label for="lcTeam${i}">Team ${i + 1}</label>
      <select id="lcTeam${i}" class="lc-team-select"></select>
    </div>`).join("");
  return `
    <div class="card">
      <h2>Create League + Cup</h2>
      <p class="muted">Exactly 10 competing teams, double round-robin, mid-season cup from GW10. Every team also plays one pre-season friendly against the friendly opponent below.</p>
      <div style="margin:0.75rem 0">
        <label for="lcName">Name</label>
        <input type="text" id="lcName" value="League + Cup" />
      </div>
      <div style="margin:0.75rem 0">
        <label for="lcFriendlyOpponent">Friendly opponent</label>
        <input type="text" id="lcFriendlyOpponent" value="Organ's XI" />
      </div>
      <div class="grid grid-2" style="gap:0.75rem">${rows}</div>
      <button type="button" id="lcCreateBtn" class="btn-primary" style="margin-top:1rem">Create</button>
      <div id="lcCreateError" class="muted" style="margin-top:0.5rem"></div>
    </div>`;
}

async function lcPopulateTeamSelects() {
  let teams = [];
  try {
    const data = await api("/api/sheets/teams");
    teams = (data.teams || []).map((t) => t.name || t);
  } catch (_) {
    return;
  }
  document.querySelectorAll(".lc-team-select").forEach((sel, i) => {
    sel.innerHTML =
      `<option value="">— pick team —</option>` +
      teams.map((name) => `<option value="${esc(name)}"${i < teams.length && teams[i] === name ? " selected" : ""}>${esc(name)}</option>`).join("");
    if (teams[i]) sel.value = teams[i];
  });
}

async function lcCreate() {
  const errorEl = document.getElementById("lcCreateError");
  errorEl.textContent = "";
  const name = document.getElementById("lcName").value.trim() || "League + Cup";
  const friendlyOpponent = document.getElementById("lcFriendlyOpponent").value.trim() || "Organ's XI";
  const teamNames = Array.from({ length: 10 }, (_, i) => document.getElementById(`lcTeam${i}`).value.trim());
  if (teamNames.some((t) => !t)) {
    errorEl.textContent = "Pick all 10 teams.";
    return;
  }
  try {
    const data = await api("/api/league-cup", { method: "POST", json: { name, team_names: teamNames, friendly_opponent: friendlyOpponent } });
    lcTournament = data.tournament;
    lcTournamentId = lcTournament.id;
    await lcLoad();
  } catch (e) {
    errorEl.textContent = e.message || "Create failed";
  }
}

// ---------------------------------------------------------------------------
// Main app shell
// ---------------------------------------------------------------------------

const LC_TABS = [
  ["friendlies", "Friendlies"],
  ["fixtures", "Fixtures"],
  ["table", "Table"],
  ["cup", "Cup"],
  ["stats", "Stats"],
  ["analysis", "Analysis"],
];

function lcRenderApp() {
  const tabs = `<nav class="tab-bar">${LC_TABS.map(
    ([id, label]) => `<button type="button" class="tab-btn${lcActiveTab === id ? " active" : ""}" data-lc-tab="${id}">${esc(label)}</button>`
  ).join("")}</nav>`;
  let body = "";
  if (lcActiveTab === "friendlies") body = lcRenderFriendlies();
  else if (lcActiveTab === "fixtures") body = lcRenderFixtures();
  else if (lcActiveTab === "table") body = lcRenderTable();
  else if (lcActiveTab === "cup") body = lcRenderCup();
  else if (lcActiveTab === "stats") body = lcRenderStats();
  else if (lcActiveTab === "analysis") body = lcRenderAnalysisTab();
  return `${tabs}<div style="margin-top:1rem">${body}</div>`;
}

function lcSwitchTab(tab) {
  lcActiveTab = tab;
  document.getElementById("app").innerHTML = lcRenderApp();
  lcWire();
}

// ---------------------------------------------------------------------------
// Friendlies
// ---------------------------------------------------------------------------

function lcRunButtonHtml(matchId, played) {
  if (played || !lcIsAdmin()) return "";
  return `<button type="button" class="btn-ghost lc-run-btn" data-match-id="${esc(matchId)}">Run</button>`;
}

function lcRenderFriendlies() {
  const rows = (lcTournament.friendlies.fixtures || [])
    .map((fx) => {
      const score = fx.played ? `<strong>${esc(fx.score)}</strong>` : `<span class="muted">not played</span>`;
      return `<tr>
        <td>${esc(fx.home)}</td>
        <td class="muted">vs</td>
        <td>${esc(fx.away)}</td>
        <td>${score}</td>
        <td>${lcRunButtonHtml(fx.id, fx.played)}</td>
      </tr>`;
    })
    .join("");
  return `
    <div class="card">
      <h2>Pre-season friendlies</h2>
      <p class="muted">Every team plays ${esc(lcTournament.friendly_opponent)} once. No effect on league/cup standings or stats.</p>
      <div class="report-table-wrap"><table><thead><tr><th>Home</th><th></th><th>Away</th><th>Score</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Fixtures (league + cup, tagged, with gw + postponement note)
// ---------------------------------------------------------------------------

function lcPostponeNote(fx) {
  if (!fx.postponements || !fx.postponements.length) return "";
  return `<span class="muted" title="Originally GW${fx.original_gw}">↺ was GW${fx.original_gw}</span>`;
}

function lcAllCupLegs() {
  const out = [];
  const pushTie = (ti, roundLabel) => {
    for (const leg of ti.legs || []) {
      out.push({ tie: ti, leg, roundLabel, gw: leg.leg === 1 ? ti.gw_leg1 : ti.gw_leg2 });
    }
  };
  for (const ti of lcTournament.cup.playoff.ties || []) pushTie(ti, "Playoff");
  for (const rnd of lcTournament.cup.rounds || []) {
    for (const ti of rnd.ties || []) pushTie(ti, rnd.label);
  }
  return out;
}

function lcRenderFixtures() {
  const leagueRows = (lcTournament.league.fixtures || [])
    .slice()
    .sort((a, b) => a.scheduled_gw - b.scheduled_gw || a.id.localeCompare(b.id))
    .map(
      (fx) => `<tr>
        <td>${lcCompTag("league")}</td>
        <td>GW${fx.scheduled_gw} ${lcPostponeNote(fx)}</td>
        <td>${esc(fx.home)} vs ${esc(fx.away)}</td>
        <td>${fx.played ? `<strong>${esc(fx.score)}</strong>` : `<span class="muted">—</span>`}</td>
        <td>${lcRunButtonHtml(fx.id, fx.played)}</td>
      </tr>`
    )
    .join("");

  const cupRows = lcAllCupLegs()
    .filter((row) => row.leg.home && row.leg.away)
    .sort((a, b) => (a.gw || 999) - (b.gw || 999))
    .map(
      (row) => `<tr>
        <td>${lcCompTag("cup")}</td>
        <td>${row.gw != null ? `GW${row.gw}` : "—"} <span class="muted">${esc(row.roundLabel)} leg ${row.leg.leg}</span></td>
        <td>${esc(row.leg.home)} vs ${esc(row.leg.away)}</td>
        <td>${row.leg.played ? `<strong>${esc(row.leg.score)}</strong>` : `<span class="muted">—</span>`}</td>
        <td>${lcRunButtonHtml(row.leg.id, row.leg.played)}</td>
      </tr>`
    )
    .join("");

  return `
    <div class="card">
      <h2>Fixtures</h2>
      <div class="report-table-wrap"><table><thead><tr><th>Comp</th><th>GW</th><th>Match</th><th>Score</th><th></th></tr></thead>
      <tbody>${leagueRows}${cupRows}</tbody></table></div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

function lcSortStandings(table) {
  return Object.keys(table).sort((a, b) => {
    const ta = table[a], tb = table[b];
    return tb.pts - ta.pts || tb.gd - ta.gd || tb.gf - ta.gf || a.toLowerCase().localeCompare(b.toLowerCase());
  });
}

function lcRenderTable() {
  const table = lcTournament.league.table || {};
  const ranked = lcSortStandings(table);
  const rows = ranked
    .map((team, i) => {
      const row = table[team];
      const cupZone = i < 6 ? ' title="Auto-qualifies for the cup"' : i < 10 ? ' title="Playoff zone"' : "";
      return `<tr${cupZone}>
        <td>${i + 1}</td>
        <td>${esc(team)}</td>
        <td>${row.played}</td>
        <td>${row.w}</td>
        <td>${row.d}</td>
        <td>${row.l}</td>
        <td>${row.gf}</td>
        <td>${row.ga}</td>
        <td>${row.gd}</td>
        <td><strong>${row.pts}</strong></td>
      </tr>`;
    })
    .join("");
  return `
    <div class="card">
      <h2>League table</h2>
      <p class="muted">Top 6 auto-qualify for the cup; 7th–10th play a two-legged playoff.</p>
      <div class="report-table-wrap"><table><thead><tr><th>#</th><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Cup
// ---------------------------------------------------------------------------

function lcRenderTieCard(ti) {
  const legs = (ti.legs || [])
    .map((leg) => {
      const score = leg.played ? `<strong>${esc(leg.score)}</strong>` : `<span class="muted">not played</span>`;
      return `<div class="slot-row"><span>Leg ${leg.leg}: ${esc(leg.home)} vs ${esc(leg.away)}</span><span>${score} ${lcRunButtonHtml(leg.id, leg.played)}</span></div>`;
    })
    .join("");
  const winner = ti.played ? `<p class="muted">Winner: <strong>${esc(ti.winner)}</strong> (${esc(ti.score || "")})</p>` : "";
  return `<div class="card">
    <h4 style="margin:0 0 0.5rem">${esc(ti.home || "TBD")} vs ${esc(ti.away || "TBD")}</h4>
    ${legs}
    ${winner}
  </div>`;
}

function lcRenderCup() {
  const playoffTies = lcTournament.cup.playoff.ties || [];
  const playoffSection = playoffTies.length
    ? `<h3>Playoff (7th–10th)</h3><div class="grid grid-2">${playoffTies.map(lcRenderTieCard).join("")}</div>`
    : `<p class="muted">Playoff not yet started — completes once all GW1-9 league fixtures are played.</p>`;

  const rounds = lcTournament.cup.rounds || [];
  const drawBtn =
    lcIsAdmin() && !rounds.length && playoffTies.length === 2 && playoffTies.every((t) => t.played)
      ? `<button type="button" id="lcDrawBtn" class="btn-primary" style="margin:1rem 0">Draw Round of 8</button>`
      : "";
  const roundsSection = rounds
    .map((rnd) => `<h3>${esc(rnd.label)}</h3><div class="grid grid-2">${rnd.ties.map(lcRenderTieCard).join("")}</div>`)
    .join("");

  return `
    <div class="card">
      <h2>Cup</h2>
      ${playoffSection}
      ${drawBtn}
      ${roundsSection}
    </div>`;
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

// Stat boards/categories/player-vs-team leaderboard tables are shared with
// tournament.js (see common.js: STAT_CATEGORIES, STAT_BOARDS,
// renderLeaderboardTable, renderTeamLeaderboardTable, aggregateTeamTallies,
// teamBoard) -- this used to be a separate, thinner 7-board/player-only
// implementation that had silently drifted out of parity with the old
// tournament page (missing the player/team toggle, category grouping, and
// 4 of the 11 stat boards). league_boards/cup_boards already carry the full
// player_leaderboards() shape (including player_tallies, needed for the
// team-aggregate view) from web/league_cup.py's tournament_for_api -- the
// gap was purely this file never rendering it.
function lcRenderStats() {
  const boards = lcStatsCompetition === "league" ? lcTournament.league_boards : lcTournament.cup_boards;
  const compToggle = `
    <div style="display:flex;gap:0.5rem;margin-bottom:1rem">
      <button type="button" class="tab-btn${lcStatsCompetition === "league" ? " active" : ""}" data-lc-stats="league">League</button>
      <button type="button" class="tab-btn${lcStatsCompetition === "cup" ? " active" : ""}" data-lc-stats="cup">Cup</button>
    </div>`;
  const viewToggle = ["player", "team"]
    .map(
      (v) =>
        `<button type="button" class="subtab-btn view-toggle-btn${lcStatView === v ? " active" : ""}" data-lc-view="${v}">${v === "player" ? "Players" : "Teams"}</button>`
    )
    .join("");
  const subtabs = STAT_CATEGORIES.map(
    ([id, label]) =>
      `<button type="button" class="subtab-btn${lcActiveStatCategory === id ? " active" : ""}" data-lc-cat="${id}">${esc(label)}</button>`
  ).join("");
  const categoryBoards = STAT_BOARDS.filter((b) => b.category === lcActiveStatCategory);
  const teamTallies = lcStatView === "team" ? aggregateTeamTallies(boards?.player_tallies) : null;
  const cards = categoryBoards
    .map((b) => {
      const table =
        lcStatView === "team"
          ? renderTeamLeaderboardTable(teamBoard(teamTallies, b.field), b.field, b.label, b.empty, { suffix: b.suffix || "" })
          : renderLeaderboardTable((boards && boards[b.key]) || [], b.field, b.label, b.empty, { suffix: b.suffix || "" });
      return `<div class="card"><h3>${esc(b.title)}</h3>${table}</div>`;
    })
    .join("");
  return `
    <div class="card">
      <h2>Stats</h2>
      ${compToggle}
      <div class="stat-view-row" style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:0.75rem;align-items:center">
        <nav class="subtab-bar">${subtabs}</nav>
        <nav class="subtab-bar">${viewToggle}</nav>
      </div>
      <div class="grid-2" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:1.25rem;margin-top:1rem">${cards}</div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Analysis -- was missing entirely (no tab, no per-fixture button), even
// though the deterministic analysis backend for League + Cup matches
// already existed (web/league_cup.py's get_match_analysis/
// generate_match_analysis, wired to /api/league-cup/.../analysis). Only
// league and cup fixtures get a report here -- friendlies are commentary-
// only by design (see web/league_cup.py's _load_played_match_result),
// so they're deliberately excluded from this list.
// ---------------------------------------------------------------------------

function lcPlayedAnalysisRows() {
  const rows = [];
  for (const fx of lcTournament.league.fixtures || []) {
    if (fx.played) {
      rows.push({
        resultId: fx.result_id || fx.id,
        home: fx.home,
        away: fx.away,
        score: fx.score,
        comp: "league",
        label: `GW${fx.scheduled_gw}`,
      });
    }
  }
  for (const row of lcAllCupLegs()) {
    if (row.leg.played) {
      rows.push({
        resultId: row.leg.result_id || row.leg.id,
        home: row.leg.home,
        away: row.leg.away,
        score: row.leg.score,
        comp: "cup",
        label: `${row.roundLabel} leg ${row.leg.leg}`,
      });
    }
  }
  return rows;
}

function lcAnalysisButtonLabel(matchId) {
  const has = Boolean(
    (lcTournament.match_results || {})[matchId]?.has_analysis || lcAnalysisCache[matchId]?.analysis
  );
  return has ? "See analysis" : "Generate analysis";
}

function lcAnalysisControls(row) {
  const mid = esc(row.resultId);
  return `<div class="analysis-controls" style="margin-top:0.35rem">
    <div class="btn-stack">
      <button type="button" class="btn-ghost btn-sm view-analysis-btn" data-match-id="${mid}">${lcAnalysisButtonLabel(row.resultId)}</button>
    </div>
    <div class="match-analysis-panel" data-match-id="${mid}" hidden style="margin-top:0.5rem"></div>
  </div>`;
}

function lcRenderAnalysisTab() {
  const rows = lcPlayedAnalysisRows();
  if (!rows.length) {
    return `<div class="card"><p class="muted">No league/cup matches played yet — analysis appears here once fixtures are hosted live. (Friendlies get commentary only, on Matchday.)</p></div>`;
  }
  return rows
    .map(
      (row) => `<div class="card" style="margin-bottom:0.75rem">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem">
          <div>${lcCompTag(row.comp)} <strong>${esc(row.home)} ${esc(row.score || "")} ${esc(row.away)}</strong> <span class="muted">${esc(row.label)}</span></div>
        </div>
        ${lcAnalysisControls(row)}
      </div>`
    )
    .join("");
}

async function lcFetchMatchAnalysis(matchId, { force = false } = {}) {
  const data = await fetchTournamentMatchAnalysis(lcTournamentId, matchId, { force, apiBase: "/api/league-cup" });
  lcAnalysisCache[matchId] = data;
  if (lcTournament?.match_results?.[matchId]) {
    lcTournament.match_results[matchId].has_analysis = Boolean(data?.analysis);
  }
  return data;
}

async function lcToggleAnalysis(matchId) {
  const panel = document.querySelector(`.match-analysis-panel[data-match-id="${matchId}"]`);
  const btn = document.querySelector(`.view-analysis-btn[data-match-id="${matchId}"]`);
  if (lcOpenAnalysisMatchId === matchId && panel && !panel.hidden) {
    panel.hidden = true;
    lcOpenAnalysisMatchId = null;
    if (btn) btn.textContent = lcAnalysisButtonLabel(matchId);
    return;
  }
  if (lcOpenAnalysisMatchId && lcOpenAnalysisMatchId !== matchId) {
    const prev = document.querySelector(`.match-analysis-panel[data-match-id="${lcOpenAnalysisMatchId}"]`);
    const prevBtn = document.querySelector(`.view-analysis-btn[data-match-id="${lcOpenAnalysisMatchId}"]`);
    if (prev) prev.hidden = true;
    if (prevBtn) prevBtn.textContent = lcAnalysisButtonLabel(lcOpenAnalysisMatchId);
  }
  lcOpenAnalysisMatchId = matchId;
  const hadCached = Boolean(lcAnalysisCache[matchId]?.analysis);
  if (panel) {
    panel.hidden = false;
    panel.innerHTML = `<p class="muted">${hadCached ? "Loading analysis…" : "Generating analysis…"}</p>`;
  }
  if (btn && !hadCached) btn.textContent = "Generating…";
  try {
    let data = lcAnalysisCache[matchId];
    if (!data?.analysis) {
      try {
        data = await lcFetchMatchAnalysis(matchId);
      } catch (err) {
        // Bug fix -- leaving lcOpenAnalysisMatchId set to this matchId made
        // the NEXT click on the same button hit the "already open, toggle
        // closed" branch above instead of retrying: it would silently hide
        // the panel (wiping the error message) without ever calling the
        // API again. Reset it here so a failed fetch can be retried.
        lcOpenAnalysisMatchId = null;
        if (panel) panel.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
        if (btn) btn.textContent = lcAnalysisButtonLabel(matchId);
        return;
      }
    }
    fillAnalysisPanel(matchId, data);
  } catch (e) {
    if (panel) panel.innerHTML = `<p class="error-msg">${esc(e.message)}</p>`;
    if (btn) btn.textContent = lcAnalysisButtonLabel(matchId);
  }
}

function lcWireAnalysisButtons() {
  document.querySelectorAll(".view-analysis-btn").forEach((btn) => {
    btn.onclick = () => lcToggleAnalysis(btn.dataset.matchId);
  });
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

async function lcRunFixture(matchId) {
  try {
    const res = await api(`/api/league-cup/${lcTournamentId}/matches/${matchId}/run`, { method: "POST" });
    window.location.href = res?.redirect || "/matchday";
  } catch (e) {
    alert(e.message || "Run failed");
  }
}

async function lcDrawCup() {
  try {
    const data = await api(`/api/league-cup/${lcTournamentId}/cup/draw`, { method: "POST", json: {} });
    lcTournament = data.tournament;
    document.getElementById("app").innerHTML = lcRenderApp();
    lcWire();
  } catch (e) {
    alert(e.message || "Draw failed");
  }
}

function lcWire() {
  document.querySelectorAll("[data-lc-tab]").forEach((btn) => {
    btn.addEventListener("click", () => lcSwitchTab(btn.dataset.lcTab));
  });
  document.querySelectorAll("[data-lc-stats]").forEach((btn) => {
    btn.addEventListener("click", () => {
      lcStatsCompetition = btn.dataset.lcStats;
      document.getElementById("app").innerHTML = lcRenderApp();
      lcWire();
    });
  });
  document.querySelectorAll("[data-lc-cat]").forEach((btn) => {
    btn.addEventListener("click", () => {
      lcActiveStatCategory = btn.dataset.lcCat;
      document.getElementById("app").innerHTML = lcRenderApp();
      lcWire();
    });
  });
  document.querySelectorAll("[data-lc-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      lcStatView = btn.dataset.lcView;
      document.getElementById("app").innerHTML = lcRenderApp();
      lcWire();
    });
  });
  document.querySelectorAll(".lc-run-btn").forEach((btn) => {
    btn.addEventListener("click", () => lcRunFixture(btn.dataset.matchId));
  });
  const drawBtn = document.getElementById("lcDrawBtn");
  if (drawBtn) drawBtn.addEventListener("click", lcDrawCup);
  const createBtn = document.getElementById("lcCreateBtn");
  if (createBtn) {
    createBtn.addEventListener("click", lcCreate);
    lcPopulateTeamSelects();
  }
  lcWireAnalysisButtons();
}

document.getElementById("refreshBtn").addEventListener("click", lcLoad);
lcLoad();
setInterval(() => {
  if (lcTournamentId) lcLoad();
}, 15000);
