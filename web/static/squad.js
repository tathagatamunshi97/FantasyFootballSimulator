if (!requireAuth()) throw new Error("auth");

document.getElementById("userLabel").textContent = getUser() || "";
document.getElementById("logoutBtn").addEventListener("click", async () => {
  try {
    await api("/api/logout", { method: "POST" });
  } catch (_) {}
  clearSession();
  window.location.href = "/login";
});

let opponents = [];
let sessionInfo = null;

function renderAdminTeamPicker(selectedTeam) {
  return `
    <div class="card" style="margin-bottom:1rem">
      <h2>Admin — select squad</h2>
      <label for="adminTeamSelect">Team</label>
      <select id="adminTeamSelect" class="input-wide">
        <option value="">Loading teams…</option>
      </select>
    </div>`;
}

function renderOpponentScoutPanel() {
  if (!opponents.length) {
    return `<div class="card"><h2>Scout opponents</h2><p class="muted">No other sheet teams available.</p></div>`;
  }
  const opts = opponents
    .map((t) => `<option value="${esc(t.name)}">${esc(t.name)} (${t.player_count}/11)</option>`)
    .join("");
  return `
    <div class="card">
      <h2>Scout opponents</h2>
      <p class="muted">Limited report: expected shape, lineup overview, and how they compare to your squad. No score predictions.</p>
      <div style="display:flex;gap:0.75rem;flex-wrap:wrap;align-items:flex-end;margin-top:0.75rem">
        <div style="flex:1;min-width:200px">
          <label for="scoutSelect">Opponent</label>
          <select id="scoutSelect" class="input-wide">${opts}</select>
        </div>
        <button type="button" id="scoutBtn" class="btn-primary">Scout team</button>
      </div>
      <div id="scoutResult" style="margin-top:1rem"></div>
    </div>`;
}

function renderPage(squadData) {
  const isAdmin = isAdminUser();
  const adminPicker = isAdmin ? renderAdminTeamPicker(squadData?.team?.name) : "";
  const evalHtml = squadData ? renderSingleSquadEval(squadData.evaluation, squadData.team) : "";
  return `
    ${adminPicker}
    <section id="mySquadSection">${evalHtml}</section>
    ${renderOpponentScoutPanel()}
  `;
}

async function loadSquad(teamName) {
  const q = teamName ? `?team=${encodeURIComponent(teamName)}` : "";
  const data = await api(`/api/my-squad${q}`);
  return data.squad;
}

async function loadOpponents() {
  const data = await api("/api/squad/opponents");
  opponents = data.teams || [];
  return data;
}

async function refreshSquad(teamName) {
  document.getElementById("mySquadSection").innerHTML =
    '<div class="empty">Loading squad evaluation…</div>';
  try {
    const squad = await loadSquad(teamName);
    document.getElementById("mySquadSection").innerHTML = renderSingleSquadEval(
      squad.evaluation,
      squad.team
    );
  } catch (e) {
    document.getElementById("mySquadSection").innerHTML = `<div class="empty"><span class="badge error">Error</span><p>${esc(e.message)}</p></div>`;
  }
}

async function runScout(opponentName) {
  const el = document.getElementById("scoutResult");
  el.innerHTML = '<p class="muted">Scouting…</p>';
  try {
    const myTeam = isAdminUser() ? document.getElementById("adminTeamSelect")?.value : null;
    const q = myTeam ? `?my_team=${encodeURIComponent(myTeam)}` : "";
    const data = await api(`/api/scout/${encodeURIComponent(opponentName)}${q}`);
    el.innerHTML = renderScoutReport(data.scout);
  } catch (e) {
    el.innerHTML = `<div class="empty"><span class="badge error">Error</span><p>${esc(e.message)}</p></div>`;
  }
}

function wireScoutPanel() {
  const btn = document.getElementById("scoutBtn");
  const sel = document.getElementById("scoutSelect");
  if (!btn || !sel) return;
  btn.addEventListener("click", () => runScout(sel.value));
}

function wireAdminPicker(allTeams, currentTeam) {
  const select = document.getElementById("adminTeamSelect");
  if (!select) return;
  const names = [...new Set((allTeams || []).map((t) => t.name))].sort((a, b) =>
    a.localeCompare(b)
  );
  if (currentTeam && !names.includes(currentTeam)) names.unshift(currentTeam);
  select.innerHTML = names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
  if (currentTeam) select.value = currentTeam;
  select.addEventListener("change", () => refreshSquad(select.value));
}

async function init() {
  try {
    sessionInfo = await api("/api/session");
    if (sessionInfo.can_simulate) {
      document.getElementById("adminLinks").hidden = false;
    }
    const oppData = await loadOpponents();
    let squad = null;
    try {
      squad = await loadSquad(isAdminUser() ? oppData.my_team || undefined : undefined);
    } catch (e) {
      if (!isAdminUser()) throw e;
    }
    document.getElementById("app").innerHTML = renderPage(squad);
    if (isAdminUser()) {
      const allTeams = [...(oppData.teams || [])];
      if (squad?.team?.name) allTeams.push({ name: squad.team.name, player_count: 11 });
      wireAdminPicker(allTeams, squad?.team?.name);
      if (!squad && allTeams.length) await refreshSquad(allTeams[0].name);
    }
    wireScoutPanel();
  } catch (e) {
    if (e.message.includes("401") || e.message.includes("Login")) {
      clearSession();
      window.location.href = "/login?next=/squad";
      return;
    }
    document.getElementById("app").innerHTML = `<div class="empty">Failed to load: ${esc(e.message)}</div>`;
  }
}

init();
