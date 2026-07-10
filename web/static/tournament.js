let tournamentId = null;
let pollTimer = null;
let currentTournament = null;

function qsParam(name) {
  return new URLSearchParams(window.location.search).get(name);
}

function tabBar(active) {
  const tabs = [
    ["draw", "Group draw"],
    ["fixtures", "Fixtures"],
    ["table", "Tables"],
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
            status = `<div><strong>${esc(fx.score)}</strong>${fx.winner ? ` · ${esc(fx.winner)}` : ""}${reviewBadge(result)}</div>
              ${koLocked ? `<span class="muted" style="font-size:0.75rem">Group locked (KO generated)</span>` : adminReviewControls(fx, result)}`;
          } else if (showRun) {
            status = `<button type="button" class="btn-ghost btn-sm run-fixture-btn" data-match-id="${esc(fx.id)}">Run</button>`;
          } else {
            status = `<span class="muted">Scheduled</span>`;
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
            res = `<div><strong>${esc(tie.score)}</strong> · ${esc(tie.winner)}${reviewBadge(result)}</div>
              ${adminReviewControls(tie, result, { isKnockout: true })}`;
          } else if (showRun && tie.home && tie.away) {
            res = `<button type="button" class="btn-ghost btn-sm run-ko-btn" data-match-id="${esc(tie.id)}">Run</button>`;
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
        ? `<p class="muted">Admin token detected — Run starts matchday; Accept / Override score reviews completed results.</p>`
        : ""
    }
  </div>`;

  let body = "";
  if (activeTab === "draw") body = renderDraw(t);
  else if (activeTab === "fixtures") body = renderFixtures(t, { showRun });
  else if (activeTab === "table") body = renderTables(t);
  else if (activeTab === "knockout") body = renderKnockout(t, { showRun });
  else body = renderResults(t);

  return meta + tabBar(activeTab) + `<div class="tab-panel">${body}</div>`;
}

async function runFixture(matchId, isKnockout = false) {
  if (!tournamentId || !getAdminToken()) return;
  const path = isKnockout
    ? `/api/tournament/${tournamentId}/knockout/matches/${matchId}/run`
    : `/api/tournament/${tournamentId}/matches/${matchId}/run`;
  try {
    await api(path, { method: "POST" });
    window.location.href = "/matchday";
  } catch (e) {
    alert(e.message);
  }
}

async function acceptResult(matchId) {
  if (!tournamentId || !getAdminToken()) return;
  try {
    await api(`/api/tournament/${tournamentId}/matches/${matchId}/accept`, { method: "POST" });
    await loadTournament();
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
    await loadTournament();
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
      return `<tr>
        <td class="muted">${esc(r.match_id)}</td>
        <td>${esc(r.stage)}${r.group ? ` (${esc(r.group)})` : ""}</td>
        <td>${esc(r.home)} vs ${esc(r.away)}</td>
        <td><strong>${esc(r.score)}</strong>${reviewBadge(r)}</td>
        <td>${esc(r.winner || "Draw")}</td>
        <td class="muted">${xg}</td>
        <td>${canReview ? adminReviewControls(fx, r, { isKnockout: isKo }) : ""}</td>
      </tr>`;
    })
    .join("");
  return `<div class="card"><h2>Match results</h2>
    <table><thead><tr><th>ID</th><th>Stage</th><th>Match</th><th>Score</th><th>Winner</th><th>xG</th><th>Admin</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

let activeTab = "draw";

function bindTabs(t) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTab = btn.dataset.tab;
      document.getElementById("app").innerHTML = renderTournament(t, activeTab);
      bindTabs(t);
    });
  });
  wireRunButtons();
  wireReviewButtons();
}

async function loadTournament() {
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
  document.getElementById("app").innerHTML = renderTournament(t, activeTab);
  bindTabs(t);
}

async function init() {
  const user = getUser();
  if (user) document.getElementById("userLabel").textContent = user;
  tournamentId = qsParam("id");
  document.getElementById("refreshBtn").addEventListener("click", () => loadTournament().catch(showErr));
  await loadTournament().catch(showErr);
  pollTimer = setInterval(() => loadTournament().catch(() => {}), 15000);
}

function showErr(err) {
  document.getElementById("app").innerHTML = `<div class="empty error-msg">${esc(err.message)}</div>`;
}

init();
