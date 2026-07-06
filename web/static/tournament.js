let tournamentId = null;
let pollTimer = null;

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

function renderFixtures(t) {
  const groups = t.groups || {};
  const keys = Object.keys(groups).sort();
  if (!keys.length) return `<div class="card"><p class="muted">No fixtures yet.</p></div>`;
  return keys
    .map((k) => {
      const rows = (groups[k].fixtures || [])
        .map((fx) => {
          const status = fx.played
            ? `<strong>${esc(fx.score)}</strong>${fx.winner ? ` · ${esc(fx.winner)}` : ""}`
            : `<span class="muted">Scheduled</span>`;
          return `<tr><td>R${fx.round}</td><td>${esc(fx.home)}</td><td>${esc(fx.away)}</td><td>${status}</td></tr>`;
        })
        .join("");
      return `<div class="card"><h3>Group ${esc(k)} fixtures</h3>
        <table><thead><tr><th>Rd</th><th>Home</th><th>Away</th><th>Result</th></tr></thead><tbody>${rows || "<tr><td colspan='4' class='muted'>—</td></tr>"}</tbody></table></div>`;
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

function renderKnockout(t) {
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
          const res = tie.played
            ? `<strong>${esc(tie.score)}</strong> · ${esc(tie.winner)}`
            : `<span class="muted">—</span>`;
          return `<tr><td class="muted">${esc(tie.id)}</td><td>${teams}</td><td>${res}</td></tr>`;
        })
        .join("");
      return `<div class="card"><h3>${esc(rnd.name)}</h3>
        <table><thead><tr><th>ID</th><th>Match</th><th>Result</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    })
    .join("");
}

function renderResults(t) {
  const results = Object.values(t.match_results || {}).sort(
    (a, b) => (b.played_at || "").localeCompare(a.played_at || "")
  );
  if (!results.length) return `<div class="card"><p class="muted">No matches played yet.</p></div>`;
  const rows = results
    .map((r) => {
      const xg = r.expected_xg ? `xG ${r.expected_xg.home}–${r.expected_xg.away}` : "";
      return `<tr>
        <td class="muted">${esc(r.match_id)}</td>
        <td>${esc(r.stage)}${r.group ? ` (${esc(r.group)})` : ""}</td>
        <td>${esc(r.home)} vs ${esc(r.away)}</td>
        <td><strong>${esc(r.score)}</strong></td>
        <td>${esc(r.winner || "Draw")}</td>
        <td class="muted">${xg}</td>
      </tr>`;
    })
    .join("");
  return `<div class="card"><h2>Match results</h2>
    <table><thead><tr><th>ID</th><th>Stage</th><th>Match</th><th>Score</th><th>Winner</th><th>xG</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderTournament(t, activeTab) {
  const settings = t.settings || {};
  const meta = `<div class="card" style="margin-bottom:1rem">
    <p><strong>${esc(t.name)}</strong> · ${(t.team_names || []).length} teams ·
    ${settings.group_count || "?"} groups × ${settings.teams_per_group || "?"} ·
    top ${settings.advance_per_group || "?"} advance</p>
  </div>`;

  let body = "";
  if (activeTab === "draw") body = renderDraw(t);
  else if (activeTab === "fixtures") body = renderFixtures(t);
  else if (activeTab === "table") body = renderTables(t);
  else if (activeTab === "knockout") body = renderKnockout(t);
  else body = renderResults(t);

  return meta + tabBar(activeTab) + `<div class="tab-panel">${body}</div>`;
}

let activeTab = "draw";

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
  document.getElementById("tournamentTitle").textContent = t.name || "Tournament";
  const badge = document.getElementById("statusBadge");
  badge.textContent = t.status || "—";
  badge.className = `badge ${esc(t.status || "")}`;
  document.getElementById("app").innerHTML = renderTournament(t, activeTab);
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTab = btn.dataset.tab;
      document.getElementById("app").innerHTML = renderTournament(t, activeTab);
      bindTabs(t);
    });
  });
}

function bindTabs(t) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTab = btn.dataset.tab;
      document.getElementById("app").innerHTML = renderTournament(t, activeTab);
      bindTabs(t);
    });
  });
}

async function init() {
  if (!requireAuth()) return;
  document.getElementById("userLabel").textContent = getUser() || "";
  tournamentId = qsParam("id");
  document.getElementById("refreshBtn").addEventListener("click", () => loadTournament().catch(showErr));
  await loadTournament().catch(showErr);
  pollTimer = setInterval(() => loadTournament().catch(() => {}), 15000);
}

function showErr(err) {
  document.getElementById("app").innerHTML = `<div class="empty error-msg">${esc(err.message)}</div>`;
}

init();
