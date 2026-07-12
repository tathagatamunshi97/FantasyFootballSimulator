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
    ["results", "Results"],
  ];
  return `<nav class="tab-bar">${tabs
    .map(
      ([id, label]) =>
        `<button type="button" class="tab-btn${active === id ? " active" : ""}" data-tab="${id}">${esc(label)}</button>`
    )
    .join("")}</nav>`;
}

function renderLeaderboardTable(rows, countKey, emptyMsg) {
  if (!rows?.length) {
    return `<p class="muted" style="margin:0">${esc(emptyMsg)}</p>`;
  }
  const body = rows
    .map((r, i) => {
      const n = r[countKey] ?? 0;
      return `<tr><td>${i + 1}</td><td>${esc(r.player || "—")}</td><td>${esc(r.team || "—")}</td><td><strong>${n}</strong></td></tr>`;
    })
    .join("");
  const countLabel = countKey === "goals" ? "G" : "A";
  return `<table><thead><tr><th>#</th><th>Player</th><th>Team</th><th>${countLabel}</th></tr></thead><tbody>${body}</tbody></table>`;
}

function renderStats(t) {
  const scorers = t.top_goalscorers || [];
  const assisters = t.top_assisters || [];
  return `<div class="grid-2" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem">
    <div class="card">
      <h3>Top goalscorers</h3>
      ${renderLeaderboardTable(scorers, "goals", "No goals recorded yet — play matches on the tactic board.")}
    </div>
    <div class="card">
      <h3>Top assisters</h3>
      ${renderLeaderboardTable(assisters, "assists", "No assists recorded yet — assists count when a goal follows a teammate's pass.")}
    </div>
  </div>`;
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

function adminReviewControls(fx, result, { isKnockout = false } = {}) {
  if (!getAdminToken() || !fx?.played) return "";
  const mid = esc(fx.id);
  const hg = result?.home_goals ?? 0;
  const ag = result?.away_goals ?? 0;
  const accepted = Boolean(result?.admin_accepted) && !result?.manually_overridden;
  const winnerSelect = isKnockout
    ? `<label class="muted" style="font-size:0.8rem">KO winner (if draw)
        <select class="override-winner" data-match-id="${mid}">
          <option value="">Auto / MC tiebreak</option>
          <option value="${esc(fx.home)}">${esc(fx.home)}</option>
          <option value="${esc(fx.away)}">${esc(fx.away)}</option>
        </select>
      </label>`
    : "";
  return `<div class="admin-review" data-match-id="${mid}" style="margin-top:0.35rem">
    <div class="btn-stack">
      ${
        accepted
          ? `<span class="muted" style="font-size:0.8rem">Accepted</span>`
          : `<button type="button" class="btn-ghost btn-sm accept-result-btn" data-match-id="${mid}">Accept</button>`
      }
      <button type="button" class="btn-ghost btn-sm toggle-override-btn" data-match-id="${mid}">Override score</button>
    </div>
    <div class="override-form" data-match-id="${mid}" hidden style="margin-top:0.4rem;display:none;flex-wrap:wrap;gap:0.4rem;align-items:center">
      <input class="override-home" data-match-id="${mid}" type="number" min="0" step="1" value="${hg}" style="width:3.5rem" aria-label="Home goals" />
      <span>–</span>
      <input class="override-away" data-match-id="${mid}" type="number" min="0" step="1" value="${ag}" style="width:3.5rem" aria-label="Away goals" />
      ${winnerSelect}
      <button type="button" class="btn-primary btn-sm apply-override-btn" data-match-id="${mid}" data-knockout="${isKnockout ? "1" : "0"}">Apply</button>
    </div>
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
  const koLocked = Boolean((t.knockout || {}).rounds?.length);
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
            status = `<div><strong>${esc(fx.score)}</strong>${fx.winner ? ` · ${esc(fx.winner)}` : ""}${reviewBadge(result)}${watch}</div>
              ${analysisControls(fx, result)}
              ${koLocked ? `<span class="muted" style="font-size:0.75rem">Group locked (KO generated)</span>` : adminReviewControls(fx, result)}`;
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
        <table><thead><tr><th>Rd</th><th>Home</th><th>Away</th><th>Result</th></tr></thead><tbody>${rows || "<tr><td colspan='4' class='muted'>—</td></tr>"}</tbody></table></div>`;
    })
    .join("");
}

function renderKnockout(t, { showRun = false } = {}) {
  const ko = t.knockout || {};
  const rounds = ko.rounds || [];
  if (!rounds.length) {
    return `<div class="card"><p class="muted">Knockout bracket not generated.</p><p class="muted">Format: ${esc(ko.format || "single_elim")}</p></div>`;
  }
  return rounds
    .map((rnd) => {
      const rows = (rnd.ties || [])
        .map((tie) => {
          const teams =
            tie.home && tie.away
              ? `${esc(tie.home)} vs ${esc(tie.away)}`
              : `<span class="muted">TBD</span>`;
          const result = resultMeta(t, tie.result_id || tie.id);
          let res;
          if (tie.played) {
            const eid = tie.experiment_id || result?.experiment_id || "";
            const xgH = result?.expected_xg?.home ?? "";
            const xgA = result?.expected_xg?.away ?? "";
            const watch = ` <button type="button" class="btn-ghost btn-sm watch-match-btn"
              data-match-id="${esc(tie.id)}"
              data-home="${esc(tie.home)}"
              data-away="${esc(tie.away)}"
              data-score="${esc(tie.score)}"
              data-experiment-id="${esc(eid)}"
              data-xg-home="${esc(String(xgH))}"
              data-xg-away="${esc(String(xgA))}"
            >Watch</button>`;
            res = `<div><strong>${esc(tie.score)}</strong> · ${esc(tie.winner)}${reviewBadge(result)}${watch}</div>
              ${typeof knockoutScoreNote === "function" ? knockoutScoreNote(result) : ""}
              ${analysisControls(tie, result)}
              ${adminReviewControls(tie, result, { isKnockout: true })}`;
          } else if (showRun && tie.home && tie.away) {
            res = `<button type="button" class="btn-ghost btn-sm run-ko-btn" data-match-id="${esc(tie.id)}">Run</button>
              <a class="btn-link btn-sm" href="/matchday" style="margin-left:0.35rem">Matchday</a>`;
          } else {
            res = `<span class="muted">—</span>`;
          }
          return `<tr><td class="muted">${esc(tie.id)}</td><td>${teams}</td><td>${res}</td></tr>`;
        })
        .join("");
      return `<div class="card"><h3>${esc(rnd.label || rnd.name)}</h3>
        <table><thead><tr><th>ID</th><th>Match</th><th>Result</th></tr></thead><tbody>${rows}</tbody></table></div>`;
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
        <table><thead><tr><th>#</th><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    })
    .join("");
}

function renderTournament(t, activeTab) {
  const settings = t.settings || {};
  const showRun = Boolean(getAdminToken());
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
  else body = renderResults(t);

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
  if (!tournamentId || !getAdminToken()) {
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

async function acceptResult(matchId) {
  if (!tournamentId || !getAdminToken()) return;
  try {
    await api(`/api/tournament/${tournamentId}/matches/${matchId}/accept`, { method: "POST" });
    await loadTournament({ force: true });
  } catch (e) {
    alert(e.message);
  }
}

async function applyOverride(matchId, isKnockout) {
  if (!tournamentId || !getAdminToken()) return;
  const homeEl = document.querySelector(`.override-home[data-match-id="${matchId}"]`);
  const awayEl = document.querySelector(`.override-away[data-match-id="${matchId}"]`);
  const winnerEl = document.querySelector(`.override-winner[data-match-id="${matchId}"]`);
  const home_goals = Number(homeEl?.value);
  const away_goals = Number(awayEl?.value);
  if (!Number.isInteger(home_goals) || !Number.isInteger(away_goals) || home_goals < 0 || away_goals < 0) {
    alert("Enter non-negative whole-number goals.");
    return;
  }
  const body = { home_goals, away_goals };
  if (isKnockout && winnerEl?.value) body.winner = winnerEl.value;
  try {
    await api(`/api/tournament/${tournamentId}/matches/${matchId}/override`, {
      method: "POST",
      json: body,
    });
    await loadTournament({ force: true });
  } catch (e) {
    alert(e.message);
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

function wireReviewButtons() {
  document.querySelectorAll(".accept-result-btn").forEach((btn) => {
    btn.addEventListener("click", () => acceptResult(btn.dataset.matchId));
  });
  document.querySelectorAll(".toggle-override-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const form = document.querySelector(`.override-form[data-match-id="${btn.dataset.matchId}"]`);
      if (!form) return;
      const show = form.style.display === "none" || form.hasAttribute("hidden");
      form.hidden = !show;
      form.style.display = show ? "flex" : "none";
    });
  });
  document.querySelectorAll(".apply-override-btn").forEach((btn) => {
    btn.addEventListener("click", () =>
      applyOverride(btn.dataset.matchId, btn.dataset.knockout === "1")
    );
  });
}

function renderResults(t) {
  const results = Object.values(t.match_results || {}).sort(
    (a, b) => (b.played_at || "").localeCompare(a.played_at || "")
  );
  if (!results.length) return `<div class="card"><p class="muted">No matches played yet.</p></div>`;
  const koLocked = Boolean((t.knockout || {}).rounds?.length);
  const rows = results
    .map((r) => {
      const xg = r.expected_xg ? `xG ${r.expected_xg.home}–${r.expected_xg.away}` : "";
      const fx = { id: r.match_id, home: r.home, away: r.away, played: true, score: r.score, winner: r.winner };
      const isKo = r.stage === "knockout";
      const canReview = getAdminToken() && (isKo || !koLocked);
      const eid = r.experiment_id || "";
      const xgH = r.expected_xg?.home ?? "";
      const xgA = r.expected_xg?.away ?? "";
      const watch = `<button type="button" class="btn-ghost btn-sm watch-match-btn"
        data-match-id="${esc(r.match_id)}"
        data-home="${esc(r.home)}"
        data-away="${esc(r.away)}"
        data-score="${esc(r.score)}"
        data-experiment-id="${esc(eid)}"
        data-xg-home="${esc(String(xgH))}"
        data-xg-away="${esc(String(xgA))}"
      >Watch</button>`;
      return `<tr>
        <td class="muted">${esc(r.match_id)}</td>
        <td>${esc(r.stage)}${r.group ? ` (${esc(r.group)})` : ""}</td>
        <td>${esc(r.home)} vs ${esc(r.away)}</td>
        <td><strong>${esc(r.score)}</strong>${reviewBadge(r)}</td>
        <td>${esc(r.winner || "Draw")}</td>
        <td class="muted">${xg}</td>
        <td>${watch}${analysisControls(fx, r)}${canReview ? adminReviewControls(fx, r, { isKnockout: isKo }) : ""}</td>
      </tr>`;
    })
    .join("");
  return `<div class="card"><h2>Match results</h2>
    <p class="muted" style="margin:0 0 0.75rem">Official scores come from the tactic-board pin match. Watch replays a board toward the saved scoreline. Generate analysis when you want it — it is not built at full time.</p>
    <table><thead><tr><th>ID</th><th>Stage</th><th>Match</th><th>Score</th><th>Winner</th><th>xG</th><th>Actions</th></tr></thead><tbody>${rows}</tbody></table></div>`;
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

function fillAnalysisPanel(matchId, data) {
  const panel = document.querySelector(`.match-analysis-panel[data-match-id="${matchId}"]`);
  if (!panel) return;
  panel.hidden = false;
  const header = `<p class="muted" style="margin:0 0 0.5rem">${esc(data.home || "")} ${esc(data.score || "")} ${esc(data.away || "")}</p>`;
  const analysisHtml = typeof renderAnalysis === "function" ? renderAnalysis(data.analysis) : "";
  const squadHtml = typeof renderSquadAnalysis === "function" ? renderSquadAnalysis(data.squad_analysis) : "";
  panel.innerHTML = header + (analysisHtml || `<p class="muted">No analysis text.</p>`) + (squadHtml || "");
  const btn = document.querySelector(`.view-analysis-btn[data-match-id="${matchId}"]`);
  if (btn) btn.textContent = "Hide analysis";
}

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
  if (!tournamentId || !getAdminToken()) return;
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
  wireRunButtons();
  wireReviewButtons();
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
