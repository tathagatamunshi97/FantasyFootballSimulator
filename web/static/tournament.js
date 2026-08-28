let tournamentId = null;
let pollTimer = null;
let currentTournament = null;
let openAnalysisMatchId = null;
let analysisCache = {};

function qsParam(name) {
  return new URLSearchParams(window.location.search).get(name);
}

function tabBar(active) {
  const tabs = [
    ["draw", "Group draw"],
    ["fixtures", "Fixtures"],
    ["table", "Tables"],
    ["stats", "Stats"],
    ["knockout", "Knockout"],
    ["analysis", "Analysis"],
  ];
  return `<nav class="tab-bar">${tabs
    .map(
      ([id, label]) =>
        `<button type="button" class="tab-btn${active === id ? " active" : ""}" data-tab="${id}">${esc(label)}</button>`
    )
    .join("")}</nav>`;
}

// renderLeaderboardTable/renderTeamLeaderboardTable/TALLY_FIELDS/
// aggregateTeamTallies/teamBoard/STAT_CATEGORIES/STAT_BOARDS moved to
// common.js so league_cup.js's Stats tab can share the same implementation
// instead of drifting out of parity (it had shipped without the player/
// team toggle, category grouping, or 4 of the 11 stat boards).

let activeStatCategory = "attacking";
let statView = "player"; // "player" | "team"

function renderStats(t) {
  const viewToggle = ["player", "team"]
    .map(
      (v) =>
        `<button type="button" class="subtab-btn view-toggle-btn${statView === v ? " active" : ""}" data-view="${v}">${v === "player" ? "Players" : "Teams"}</button>`
    )
    .join("");
  const subtabs = STAT_CATEGORIES.map(
    ([id, label]) =>
      `<button type="button" class="subtab-btn${activeStatCategory === id ? " active" : ""}" data-cat="${id}">${esc(label)}</button>`
  ).join("");
  const boards = STAT_BOARDS.filter((b) => b.category === activeStatCategory);
  const teamTallies = statView === "team" ? aggregateTeamTallies(t.player_tallies) : null;
  const cards = boards
    .map((b) => {
      const table = b.teamOnly
        ? renderTeamOnlyBoard(t[b.key] || [], b)
        : statView === "team"
          ? renderTeamLeaderboardTable(teamBoard(teamTallies, b.field), b.field, b.label, b.empty, { suffix: b.suffix || "" })
          : renderLeaderboardTable(t[b.key] || [], b.field, b.label, b.empty, { suffix: b.suffix || "" });
      return `<div class="card">
      <h3>${esc(b.title)}</h3>
      ${table}
    </div>`;
    })
    .join("");
  return `<div class="stat-view-row" style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:0.75rem;align-items:center">
      <nav class="subtab-bar">${subtabs}</nav>
      <nav class="subtab-bar">${viewToggle}</nav>
    </div>
    <div class="grid-2" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:1.25rem">${cards}</div>`;
}

function resultMeta(t, matchId) {
  return (t.match_results || {})[matchId] || null;
}

function reviewBadge(result) {
  if (!result) return "";
  if (result.manually_overridden) {
    const eng =
      result.engine_home_goals != null
        ? ` (engine ${result.engine_home_goals}-${result.engine_away_goals})`
        : "";
    return `<span class="muted"> · overridden${eng}</span>`;
  }
  if (result.admin_accepted) return `<span class="muted"> · accepted</span>`;
  return `<span class="muted"> · pending review</span>`;
}

function analysisControls(fx, result) {
  if (!fx?.played) return "";
  const mid = esc(fx.id);
  const has = Boolean(result?.has_analysis || analysisCache[fx.id]?.analysis);
  const label = has ? "See analysis" : "Generate analysis";
  return `<div class="analysis-controls" style="margin-top:0.35rem">
    <div class="btn-stack">
      <button type="button" class="btn-ghost btn-sm view-analysis-btn" data-match-id="${mid}">${label}</button>
    </div>
    <div class="match-analysis-panel" data-match-id="${mid}" hidden style="margin-top:0.5rem"></div>
  </div>`;
}

function renderDraw(t) {
  const groups = t.groups || {};
  const keys = Object.keys(groups).sort();
  if (!keys.length) {
    return `<div class="card"><p class="muted">Group draw not performed yet.</p><p>Teams entered: ${(t.team_names || []).map(esc).join(", ") || "—"}</p></div>`;
  }
  return keys
    .map((k) => {
      const g = groups[k];
      const teams = (g.teams || []).map((tm) => `<li>${esc(tm)}</li>`).join("");
      return `<div class="card"><h3>Group ${esc(k)}</h3><ul class="team-list">${teams}</ul></div>`;
    })
    .join("");
}

function renderFixtures(t, { showRun = false } = {}) {
  const groups = t.groups || {};
  const keys = Object.keys(groups).sort();
  if (!keys.length) return `<div class="card"><p class="muted">No fixtures yet.</p></div>`;
  return keys
    .map((k) => {
      const rows = (groups[k].fixtures || [])
        .map((fx) => {
          const result = resultMeta(t, fx.result_id || fx.id);
          let status;
          if (fx.played) {
            const eid = fx.experiment_id || result?.experiment_id || "";
            const xgH = result?.expected_xg?.home ?? "";
            const xgA = result?.expected_xg?.away ?? "";
            const watch = ` <button type="button" class="btn-ghost btn-sm watch-match-btn"
              data-match-id="${esc(fx.id)}"
              data-home="${esc(fx.home)}"
              data-away="${esc(fx.away)}"
              data-score="${esc(fx.score)}"
              data-experiment-id="${esc(eid)}"
              data-xg-home="${esc(String(xgH))}"
              data-xg-away="${esc(String(xgA))}"
            >Watch</button>`;
            status = `<div><strong>${esc(fx.score)}</strong>${fx.winner ? ` · ${esc(fx.winner)}` : ""}${reviewBadge(result)}${watch}</div>`;
          } else if (showRun) {
            status = `<button type="button" class="btn-ghost btn-sm run-fixture-btn" data-match-id="${esc(fx.id)}">Run</button>
              <a class="btn-link btn-sm" href="/matchday" style="margin-left:0.35rem">Matchday</a>`;
          } else {
            status = `<span class="muted">Scheduled</span> <a class="btn-link btn-sm" href="/matchday">Watch Matchday</a>`;
          }
          return `<tr><td>R${fx.round}</td><td>${esc(fx.home)}</td><td>${esc(fx.away)}</td><td>${status}</td></tr>`;
        })
        .join("");
      return `<div class="card"><h3>Group ${esc(k)} fixtures</h3>
        <div class="report-table-wrap"><table><thead><tr><th>Rd</th><th>Home</th><th>Away</th><th>Result</th></tr></thead><tbody>${rows || "<tr><td colspan='4' class='muted'>—</td></tr>"}</tbody></table></div></div>`;
    })
    .join("");
}

function renderAnalysisTab(t) {
  const results = Object.values(t.match_results || {}).filter(Boolean);
  if (!results.length) {
    return `<div class="card"><p class="muted">No matches played yet — analysis appears here once fixtures are hosted live.</p></div>`;
  }
  const rows = results
    .map((r) => {
      const fx = { id: r.match_id, home: r.home, away: r.away, played: true, score: r.score, winner: r.winner };
      const stageLabel = `${esc(r.stage || "")}${r.group ? ` (${esc(r.group)})` : ""}`;
      return `<div class="card" style="margin-bottom:0.75rem">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem">
          <div><strong>${esc(r.home)} ${esc(r.score || "")} ${esc(r.away)}</strong> <span class="muted">${stageLabel}</span></div>
        </div>
        ${analysisControls(fx, r)}
      </div>`;
    })
    .join("");
  return rows;
}

function legWatchBtn(leg, t) {
  const result = resultMeta(t, leg.result_id || leg.id);
  const eid = leg.experiment_id || result?.experiment_id || "";
  const xgH = result?.expected_xg?.home ?? "";
  const xgA = result?.expected_xg?.away ?? "";
  return ` <button type="button" class="btn-ghost btn-sm watch-match-btn"
    data-match-id="${esc(leg.id)}"
    data-home="${esc(leg.home)}"
    data-away="${esc(leg.away)}"
    data-score="${esc(leg.score)}"
    data-experiment-id="${esc(eid)}"
    data-xg-home="${esc(String(xgH))}"
    data-xg-away="${esc(String(xgA))}"
  >Watch</button>`;
}

function renderKnockoutTieCell(t, tie, { showRun = false } = {}) {
  const legs = tie.legs || [];
  if (legs.length <= 1) {
    // Single-legged tie (the Final, or a legacy single_elim tournament) —
    // unchanged behavior, keyed by the tie's own id.
    const result = resultMeta(t, tie.result_id || tie.id);
    if (tie.played) {
      return `<div><strong>${esc(tie.score)}</strong> · ${esc(tie.winner)}${reviewBadge(result)}${legWatchBtn(legs[0] || tie, t)}</div>
        ${typeof knockoutScoreNote === "function" ? knockoutScoreNote(result) : ""}
        ${analysisControls(legs[0] || tie, result)}`;
    }
    if (showRun && tie.home && tie.away) {
      return `<button type="button" class="btn-ghost btn-sm run-ko-btn" data-match-id="${esc(tie.id)}">Run</button>
        <a class="btn-link btn-sm" href="/matchday" style="margin-left:0.35rem">Matchday</a>`;
    }
    return `<span class="muted">—</span>`;
  }

  // Two-legged tie.
  const legLines = legs
    .map((leg) => {
      const result = resultMeta(t, leg.result_id || leg.id);
      if (leg.played) {
        return `<div>Leg ${leg.leg}: <strong>${esc(leg.home)} ${leg.home_goals}-${leg.away_goals} ${esc(leg.away)}</strong>${reviewBadge(result)}${legWatchBtn(leg, t)}
          ${analysisControls(leg, result)}</div>`;
      }
      const canPlay = leg.leg === 1 ? true : Boolean(legs[0].played);
      const legTeams =
        leg.home && leg.away ? `${esc(leg.home)} vs ${esc(leg.away)}` : `<span class="muted">TBD</span>`;
      if (showRun && canPlay && leg.home && leg.away) {
        return `<div>Leg ${leg.leg}: ${legTeams} — <button type="button" class="btn-ghost btn-sm run-ko-btn" data-match-id="${esc(leg.id)}">Run</button>
          <a class="btn-link btn-sm" href="/matchday" style="margin-left:0.35rem">Matchday</a></div>`;
      }
      return `<div class="muted">Leg ${leg.leg}: ${canPlay ? legTeams : "awaiting leg 1"}</div>`;
    })
    .join("");
  const tieSummary = tie.played
    ? `<div style="margin-top:0.25rem"><strong>${esc(tie.score)}</strong> · ${esc(tie.winner)} advance</div>`
    : "";
  return `${legLines}${tieSummary}`;
}

function renderKnockout(t, { showRun = false } = {}) {
  const ko = t.knockout || {};
  const rounds = ko.rounds || [];
  if (!rounds.length) {
    return `<div class="card"><p class="muted">Knockout bracket not generated.</p><p class="muted">Format: ${esc(ko.format === "two_leg" ? "Two-legged (Final single match)" : ko.format || "single_elim")}</p></div>`;
  }
  return rounds
    .map((rnd) => {
      const rows = (rnd.ties || [])
        .map((tie) => {
          const teams =
            tie.home && tie.away
              ? `${esc(tie.home)} vs ${esc(tie.away)}`
              : `<span class="muted">TBD</span>`;
          const res = renderKnockoutTieCell(t, tie, { showRun });
          return `<tr><td class="muted">${esc(tie.id)}</td><td>${teams}</td><td>${res}</td></tr>`;
        })
        .join("");
      return `<div class="card"><h3>${esc(rnd.label || rnd.name)}</h3>
        <div class="report-table-wrap"><table><thead><tr><th>ID</th><th>Match</th><th>Result</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
    })
    .join("");
}

function renderTables(t) {
  const groups = t.groups || {};
  const keys = Object.keys(groups).sort();
  if (!keys.length) return `<div class="card"><p class="muted">No standings yet.</p></div>`;
  return keys
    .map((k) => {
      const table = groups[k].table || {};
      const ranked = Object.keys(table).sort(
        (a, b) =>
          table[b].pts - table[a].pts ||
          table[b].gd - table[a].gd ||
          table[b].gf - table[a].gf ||
          a.localeCompare(b)
      );
      const rows = ranked
        .map((tm, i) => {
          const r = table[tm];
          return `<tr><td>${i + 1}</td><td>${esc(tm)}</td><td>${r.played}</td><td>${r.w}</td><td>${r.d}</td><td>${r.l}</td><td>${r.gf}</td><td>${r.ga}</td><td>${r.gd}</td><td><strong>${r.pts}</strong></td></tr>`;
        })
        .join("");
      return `<div class="card"><h3>Group ${esc(k)}</h3>
        <div class="report-table-wrap emphasize-top"><table><thead><tr><th>#</th><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
    })
    .join("");
}

function renderTournament(t, activeTab) {
  const settings = t.settings || {};
  const showRun = Boolean(getAdminToken()) || isAdminUser();
  const advance = settings.advance_per_group || "?";
  const koTeams =
    settings.group_count && advance !== "?"
      ? Number(settings.group_count) * Number(advance)
      : "?";
  const meta = `<div class="card" style="margin-bottom:1rem">
    <p><strong>${esc(t.name)}</strong> · ${(t.team_names || []).length} teams ·
    ${settings.group_count || "?"} groups × ${settings.teams_per_group || "?"} ·
    top ${advance} advance (${koTeams} knockout teams)</p>
    ${
      showRun
        ? `<p class="muted">Admin — <strong>Run</strong> opens Matchday for everyone (pre-match → live tactic board → FT). Knockout draws go to extra time, then pens. Pin goals are the official score.</p>`
        : `<p class="muted">Live fixtures play on <a href="/matchday">Matchday</a>. Knockout draws go to extra time, then pens.</p>`
    }
    <div id="liveMatchdayBanner" hidden class="badge live" style="display:none;margin-top:0.5rem"></div>
  </div>`;

  let body = "";
  if (activeTab === "draw") body = renderDraw(t);
  else if (activeTab === "fixtures") body = renderFixtures(t, { showRun });
  else if (activeTab === "table") body = renderTables(t);
  else if (activeTab === "stats") body = renderStats(t);
  else if (activeTab === "knockout") body = renderKnockout(t, { showRun });
  else if (activeTab === "analysis") body = renderAnalysisTab(t);

  return meta + tabBar(activeTab) + `<div class="tab-panel">${body}</div>` + `<div class="card tactic-watch-card" id="tournamentWatchDock" style="margin-top:1rem" hidden>
    <div style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem;flex-wrap:wrap">
      <h2 style="margin:0">Watch replay</h2>
      <button type="button" class="btn-ghost btn-sm" id="closeTournamentWatch">Close</button>
    </div>
    <p class="muted" id="tournamentWatchTitle" style="margin:0.5rem 0 0.75rem"></p>
    <div data-tactic-mount></div>
  </div>`;
}

async function runFixture(matchId, isKnockout = false) {
  if (!tournamentId || !(Boolean(getAdminToken()) || isAdminUser())) {
    alert("Admin token required to Run a fixture.");
    return;
  }
  const path = isKnockout
    ? `/api/tournament/${tournamentId}/knockout/matches/${matchId}/run`
    : `/api/tournament/${tournamentId}/matches/${matchId}/run`;
  try {
    const res = await api(path, { method: "POST" });
    const phase = res?.matchday?.session?.phase || res?.matchday?.phase;
    if (!res?.redirect && !phase) {
      alert("Run did not open a Matchday session. Restart the web server and try again.");
      return;
    }
    window.location.href = res?.redirect || "/matchday";
  } catch (e) {
    alert(e.message || "Run failed");
  }
}

function wireRunButtons() {
  document.querySelectorAll(".run-fixture-btn").forEach((btn) => {
    btn.addEventListener("click", () => runFixture(btn.dataset.matchId, false));
  });
  document.querySelectorAll(".run-ko-btn").forEach((btn) => {
    btn.addEventListener("click", () => runFixture(btn.dataset.matchId, true));
  });
}

let activeTab = "draw";
let _tournamentWatchBoard = null;
let _watchingMatchKey = "";

function closeTournamentWatch() {
  if (_tournamentWatchBoard && typeof _tournamentWatchBoard.destroy === "function") {
    _tournamentWatchBoard.destroy();
  }
  _tournamentWatchBoard = null;
  _watchingMatchKey = "";
  const dock = document.getElementById("tournamentWatchDock");
  if (dock) dock.hidden = true;
}

async function openWatchFromButton(btn) {
  if (typeof TacticBoard === "undefined") {
    alert("Tactic board not loaded.");
    return;
  }
  const dock = document.getElementById("tournamentWatchDock");
  const mount = dock?.querySelector("[data-tactic-mount]");
  const title = document.getElementById("tournamentWatchTitle");
  if (!dock || !mount) return;

  const meta = {
    matchId: btn.dataset.matchId,
    home: btn.dataset.home,
    away: btn.dataset.away,
    score: btn.dataset.score,
    experimentId: btn.dataset.experimentId || "",
    xgHome: btn.dataset.xgHome ? Number(btn.dataset.xgHome) : undefined,
    xgAway: btn.dataset.xgAway ? Number(btn.dataset.xgAway) : undefined,
  };
  _watchingMatchKey = `${meta.matchId}|${meta.score}`;
  dock.hidden = false;
  if (title) title.textContent = `${meta.home} ${meta.score} ${meta.away}`;
  dock.scrollIntoView({ behavior: "smooth", block: "nearest" });

  if (_tournamentWatchBoard && typeof _tournamentWatchBoard.destroy === "function") {
    _tournamentWatchBoard.destroy();
  }
  _tournamentWatchBoard = await TacticBoard.openTournamentWatch(mount, meta, { apiFetch: api });
}

function wireWatchButtons() {
  document.querySelectorAll(".watch-match-btn").forEach((btn) => {
    btn.addEventListener("click", () => openWatchFromButton(btn));
  });
  const closeBtn = document.getElementById("closeTournamentWatch");
  if (closeBtn) closeBtn.addEventListener("click", closeTournamentWatch);
}

// fillAnalysisPanel moved to common.js (shared with league_cup.js).

function analysisButtonLabel(matchId) {
  const has = Boolean(
    currentTournament?.match_results?.[matchId]?.has_analysis || analysisCache[matchId]?.analysis
  );
  return has ? "See analysis" : "Generate analysis";
}

async function fetchMatchAnalysis(matchId, { force = false } = {}) {
  const data = await fetchTournamentMatchAnalysis(tournamentId, matchId, { force });
  analysisCache[matchId] = data;
  if (currentTournament?.match_results?.[matchId]) {
    currentTournament.match_results[matchId].has_analysis = Boolean(data?.analysis);
  }
  return data;
}

async function toggleAnalysis(matchId) {
  const panel = document.querySelector(`.match-analysis-panel[data-match-id="${matchId}"]`);
  const btn = document.querySelector(`.view-analysis-btn[data-match-id="${matchId}"]`);
  if (openAnalysisMatchId === matchId && panel && !panel.hidden) {
    panel.hidden = true;
    openAnalysisMatchId = null;
    if (btn) btn.textContent = analysisButtonLabel(matchId);
    return;
  }
  // Close any other open panel in-place (keeps Watch dock alive).
  if (openAnalysisMatchId && openAnalysisMatchId !== matchId) {
    const prev = document.querySelector(`.match-analysis-panel[data-match-id="${openAnalysisMatchId}"]`);
    const prevBtn = document.querySelector(`.view-analysis-btn[data-match-id="${openAnalysisMatchId}"]`);
    if (prev) prev.hidden = true;
    if (prevBtn) prevBtn.textContent = analysisButtonLabel(openAnalysisMatchId);
  }
  openAnalysisMatchId = matchId;
  const hadCached = Boolean(analysisCache[matchId]?.analysis);
  if (panel) {
    panel.hidden = false;
    panel.innerHTML = `<p class="muted">${hadCached ? "Loading analysis…" : "Generating analysis…"}</p>`;
  }
  if (btn && !hadCached) btn.textContent = "Generating…";
  try {
    let data = analysisCache[matchId];
    if (!data?.analysis) {
      try {
        data = await fetchMatchAnalysis(matchId);
      } catch (err) {
        if (panel) {
          panel.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
        }
        if (btn) btn.textContent = analysisButtonLabel(matchId);
        return;
      }
    }
    fillAnalysisPanel(matchId, data);
  } catch (e) {
    if (panel) panel.innerHTML = `<p class="error-msg">${esc(e.message)}</p>`;
    if (btn) btn.textContent = analysisButtonLabel(matchId);
  }
}

async function generateAnalysis(matchId) {
  if (!tournamentId || !(Boolean(getAdminToken()) || isAdminUser())) return;
  openAnalysisMatchId = matchId;
  const panel = document.querySelector(`.match-analysis-panel[data-match-id="${matchId}"]`);
  const btn = document.querySelector(`.view-analysis-btn[data-match-id="${matchId}"]`);
  if (panel) {
    panel.hidden = false;
    panel.innerHTML = `<p class="muted">Generating analysis…</p>`;
  }
  if (btn) btn.textContent = "Generating…";
  try {
    const data = await fetchMatchAnalysis(matchId, { force: true });
    fillAnalysisPanel(matchId, data);
  } catch (e) {
    alert(e.message);
    if (btn) btn.textContent = analysisButtonLabel(matchId);
  }
}

function wireAnalysisButtons() {
  document.querySelectorAll(".view-analysis-btn").forEach((btn) => {
    btn.onclick = () => toggleAnalysis(btn.dataset.matchId);
  });
}

function bindTabs(t) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      closeTournamentWatch();
      openAnalysisMatchId = null;
      activeTab = btn.dataset.tab;
      document.getElementById("app").innerHTML = renderTournament(t, activeTab);
      bindTabs(t);
    });
  });
  document.querySelectorAll(".subtab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.view) statView = btn.dataset.view;
      else activeStatCategory = btn.dataset.cat;
      document.getElementById("app").innerHTML = renderTournament(t, activeTab);
      bindTabs(t);
    });
  });
  wireRunButtons();
  wireAnalysisButtons();
  wireWatchButtons();
}

async function loadTournament({ force = false } = {}) {
  if (!tournamentId) {
    const list = await api("/api/tournament");
    const items = list.tournaments || [];
    if (!items.length) {
      document.getElementById("app").innerHTML =
        `<div class="empty"><p>No tournament yet.</p><p><a href="/admin#tournament">Create one in admin</a></p></div>`;
      return;
    }
    tournamentId = items[0].id;
  }
  const data = await api(`/api/tournament/${tournamentId}`);
  const t = data.tournament;
  // League+Cup tournaments (web/league_cup.py) share this same tournament
  // store/id-space but have a completely different shape (t.league.fixtures/
  // t.cup.rounds, no t.groups) -- rendering one with this classic
  // group+knockout UI always shows a nonsensical "Group draw not performed
  // yet" for a format that never has a group draw. Every entry point into
  // this page (matchday/squad/league_cup nav links, bookmarks, the classic
  // tournament-list fallback below) funnels through here, so redirecting at
  // the single point the format is known fixes all of them at once instead
  // of patching each link.
  if (t.format === "league_cup") {
    if (pollTimer) clearInterval(pollTimer);
    window.location.replace(`/league-cup?id=${encodeURIComponent(tournamentId)}`);
    return;
  }
  currentTournament = t;
  document.getElementById("tournamentTitle").textContent = t.name || "Tournament";
  const badge = document.getElementById("statusBadge");
  badge.textContent = t.status || "—";
  badge.className = `badge ${esc(t.status || "")}`;

  const watching = Boolean(
    _watchingMatchKey && document.querySelector("#tournamentWatchDock:not([hidden])")
  );
  const analysisOpen = Boolean(
    openAnalysisMatchId &&
      document.querySelector(`.match-analysis-panel[data-match-id="${openAnalysisMatchId}"]:not([hidden])`)
  );
  if (!force && (watching || analysisOpen)) return;

  if (_tournamentWatchBoard) {
    try {
      _tournamentWatchBoard.destroy();
    } catch (_) {}
    _tournamentWatchBoard = null;
  }
  _watchingMatchKey = "";

  document.getElementById("app").innerHTML = renderTournament(t, activeTab);
  bindTabs(t);
}

async function init() {
  const user = getUser();
  if (user) document.getElementById("userLabel").textContent = user;
  tournamentId = qsParam("id");
  document.getElementById("refreshBtn").addEventListener("click", () =>
    loadTournament({ force: true }).catch(showErr)
  );
  await loadTournament({ force: true }).catch(showErr);

  // Surface active Matchday fixture on the tournament page
  try {
    const md = await api("/api/matchday/active");
    const banner = document.getElementById("liveMatchdayBanner");
    const mdSession = md?.active ? md.session : null;
    if (banner && mdSession && ["setup", "live", "running"].includes(mdSession.phase)) {
      banner.hidden = false;
      banner.style.display = "inline-block";
      banner.innerHTML = `Live on Matchday: ${esc(mdSession.home)} vs ${esc(mdSession.away)} — <a href="/matchday" style="color:inherit">Open Matchday</a>`;
    }
  } catch (_) {}

  pollTimer = setInterval(() => loadTournament().catch(() => {}), 15000);
}

function showErr(err) {
  document.getElementById("app").innerHTML = `<div class="empty error-msg">${esc(err.message)}</div>`;
}

init();
