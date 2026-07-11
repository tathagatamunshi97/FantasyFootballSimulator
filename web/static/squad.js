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
let meta = null;
let lineupData = null;
let currentTeam = null;

function playerSelectOptions(players, selected) {
  const opts = ['<option value="">— pick player —</option>'];
  players.forEach((p) => {
    opts.push(`<option value="${esc(p)}" ${p === selected ? "selected" : ""}>${esc(p)}</option>`);
  });
  return opts.join("");
}

function seasonSelectOptions(selected) {
  return (meta?.seasons || [])
    .map(
      (s) =>
        `<option value="${esc(s.suffix)}" ${s.suffix === selected ? "selected" : ""}>${esc(s.label)}</option>`
    )
    .join("");
}

function renderLineupBuilder(data) {
  const config = data.lineup || {};
  const roster = data.roster || [];
  const formation = config.formation || "4-3-3 flat";
  const formations = meta?.formations?.formations || ["4-3-3 flat", "4-4-2", "3-5-2"];
  const slots = meta?.formations?.slots?.[formation] || [];
  const { map: lineupMap, filters: roleFilters } = lineupMapFromConfig(config);
  const prime = config.prime_player || "";
  const peak = config.peak_season || {};
  const peakPlayer = peak.player || "";
  const peakSeason = peak.season || "23/24";
  const locked = Boolean(data.locked);
  const disabled = locked ? "disabled" : "";
  const roundLabel = data.immediate_round?.label || "current round";

  const formationOpts = formations
    .map((f) => `<option value="${esc(f)}" ${f === formation ? "selected" : ""}>${esc(f)}</option>`)
    .join("");

  const slotRows = slots
    .map((slot) =>
      renderSlotRow(slot, lineupMap[slot] || "", roster, formation, roleFilters[slot] || "", locked)
    )
    .join("");

  const savedBadge = data.saved
    ? `<span class="badge ready">Saved lineup</span>`
    : `<span class="badge muted">Using auto lineup — save to persist</span>`;
  const finalizedBadge = locked
    ? `<span class="badge ready">Squad finalized ✓ — locked for ${esc(roundLabel)}</span>`
    : data.finalized
      ? `<span class="badge muted">Finalized for a prior round — edit and re-finalize for ${esc(roundLabel)}</span>`
      : `<span class="badge muted">Not finalized for ${esc(roundLabel)}</span>`;

  return `
    <div class="card" style="margin-bottom:1rem">
      <h2>Lineup builder — ${esc(data.team_name)}</h2>
      <p class="muted">Select your starting XI from your ${roster.length}-player roster. Role dropdowns appear on AM/CM/DM and wide/fullback slots (GK/CB/ST stay locked). Live fit scores use the current engine. Finalize locks your XI for the current tournament matchday.</p>
      <p style="margin:0.5rem 0;display:flex;gap:0.5rem;flex-wrap:wrap">${savedBadge}${finalizedBadge}</p>
      <div class="form-row" style="margin-top:0.75rem">
        <label for="lineupFormation">Formation</label>
        <select id="lineupFormation" ${disabled}>${formationOpts}</select>
      </div>
      <div class="slot-grid">${slotRows}</div>
      <div class="season-picks" style="margin-top:1rem;padding-top:0.75rem;border-top:1px solid var(--border)">
        <h3 style="font-size:0.9rem;margin:0 0 0.5rem">Season overrides</h3>
        <div class="form-row">
          <label for="lineupPrime">Prime player</label>
          <select id="lineupPrime" ${disabled}>${playerSelectOptions(roster, prime)}</select>
        </div>
        <div class="form-row">
          <label for="lineupPeakPlayer">Peak season player</label>
          <select id="lineupPeakPlayer" ${disabled}>${playerSelectOptions(roster, peakPlayer)}</select>
        </div>
        <div class="form-row">
          <label for="lineupPeakSeason">Season</label>
          <select id="lineupPeakSeason" ${disabled}>${seasonSelectOptions(peakSeason)}</select>
        </div>
      </div>
      <div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:1rem">
        <button type="button" id="saveLineupBtn" class="btn-primary" ${disabled}>Save lineup</button>
        <button type="button" id="testSquadBtn" class="btn-ghost">Test squad</button>
        <button type="button" id="finalizeSquadBtn" class="btn-ghost" ${locked ? "disabled" : ""}>Finalize squad</button>
      </div>
      <p id="lineupStatus" class="muted" style="margin-top:0.5rem"></p>
    </div>`;
}

function slotPlayerControl(slot, val, roster, locked = false) {
  const disabled = locked ? "disabled" : "";
  const opts = ['<option value="">— pick player —</option>'];
  roster.forEach((p) => {
    opts.push(`<option value="${esc(p)}" data-slot="${esc(slot)}" ${p === val ? "selected" : ""}>${esc(p)}</option>`);
  });
  return `<select data-slot="${esc(slot)}" ${disabled}>${opts.join("")}</select>`;
}

function lineupMapFromConfig(config) {
  const map = {};
  const filters = {};
  (config?.lineup || []).forEach((r) => {
    map[r.slot] = r.player || "";
    filters[r.slot] = (r.role_filter || "").trim().toUpperCase();
  });
  return { map, filters };
}

function roleFilterOptionsFor(slot, formation) {
  const byForm = meta?.formations?.role_filters?.[formation] || {};
  if (byForm[slot]?.length) return byForm[slot];
  const key = String(slot || "")
    .toUpperCase()
    .replace(/^(CM|DM|CB|ST|CF)\d+$/, "$1");
  return meta?.formations?.role_filter_options?.[key] || [];
}

function roleFilterControl(slot, formation, selected, locked = false) {
  const opts = roleFilterOptionsFor(slot, formation);
  if (!opts.length) return "";
  const disabled = locked ? "disabled" : "";
  const cur = (selected || opts[0] || "").toUpperCase();
  const options = opts
    .map((r) => `<option value="${esc(r)}" ${r === cur ? "selected" : ""}>${esc(r)}</option>`)
    .join("");
  return `<label class="role-filter-wrap" title="Role filter for ${esc(slot)}">
      <span class="role-filter-label">Role</span>
      <select class="role-filter" data-role-filter-slot="${esc(slot)}" aria-label="Role filter ${esc(slot)}" ${disabled}>${options}</select>
    </label>`;
}

function slotFitBadge(slot) {
  const fitMap = lineupData?.slot_fits || {};
  const fit = fitMap[slot];
  if (fit == null || Number.isNaN(Number(fit))) return "";
  const n = Number(fit);
  const cls = n >= 0.9 ? "fit-good" : n >= 0.62 ? "fit-ok" : "fit-weak";
  return `<span class="slot-fit ${cls}" title="Live formation fit">${n.toFixed(2)}</span>`;
}

function renderSlotRow(slot, val, roster, formation, roleFilter, locked) {
  const filterCtrl = roleFilterControl(slot, formation, roleFilter, locked);
  return `<div class="form-row slot-row">
      <label>${esc(slot)}</label>
      <div class="slot-controls">
        ${slotPlayerControl(slot, val, roster, locked)}
        ${filterCtrl}
        ${slotFitBadge(slot)}
      </div>
    </div>`;
}

function renderAdminTeamPicker() {
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

function collectLineupPayload() {
  const formation = document.getElementById("lineupFormation")?.value || "4-3-3 flat";
  const slots = meta?.formations?.slots?.[formation] || [];
  const lineup = slots.map((slot) => {
    const el = document.querySelector(`select[data-slot="${slot}"]`);
    const filterEl = document.querySelector(`[data-role-filter-slot="${slot}"]`);
    const natural = roleFilterOptionsFor(slot, formation)[0] || "";
    const roleFilter = (filterEl?.value || "").trim().toUpperCase();
    return {
      slot,
      player: (el?.value || "").trim(),
      captain: false,
      vice_captain: false,
      role_filter: roleFilter && roleFilter !== natural ? roleFilter : roleFilter || "",
    };
  });
  return {
    formation,
    lineup,
    prime_player: document.getElementById("lineupPrime")?.value || "",
    peak_season: {
      player: document.getElementById("lineupPeakPlayer")?.value || "",
      season: document.getElementById("lineupPeakSeason")?.value || "",
    },
  };
}

async function onFormationChange() {
  if (lineupData?.locked) return;
  const formation = document.getElementById("lineupFormation")?.value;
  const roster = lineupData?.roster || [];
    const players = [...document.querySelectorAll("select[data-slot]")]
      .map((el) => el.value.trim())
      .filter(Boolean);
  const status = document.getElementById("lineupStatus");
  if (status) status.textContent = "Reassigning slots…";
  try {
    const data = await api("/api/lineup/assign", {
      method: "POST",
      json: { formation, players: players.length ? players : roster.slice(0, 11) },
    });
    const slots = meta.formations.slots[formation] || [];
    const lineupMap = {};
    (data.lineup || []).forEach((r) => {
      lineupMap[r.slot] = r.player;
    });
    const grid = document.querySelector(".slot-grid");
    if (grid) {
      grid.innerHTML = slots
        .map((slot) => renderSlotRow(slot, lineupMap[slot] || "", roster, formation, "", lineupData?.locked))
        .join("");
    }
    if (status) status.textContent = "";
  } catch (e) {
    if (status) status.textContent = `Could not reassign: ${e.message}`;
  }
}

async function saveLineup() {
  const status = document.getElementById("lineupStatus");
  const q = currentTeam ? `?team=${encodeURIComponent(currentTeam)}` : "";
  try {
    const payload = collectLineupPayload();
    await api(`/api/my-lineup${q}`, { method: "PUT", json: payload });
    if (status) status.textContent = "Lineup saved.";
    lineupData = await loadLineup(currentTeam);
    document.getElementById("lineupSection").innerHTML = renderLineupBuilder(lineupData);
    wireLineupBuilder();
  } catch (e) {
    if (status) status.textContent = `Save failed: ${e.message}`;
  }
}

async function testSquad() {
  const status = document.getElementById("lineupStatus");
  const q = currentTeam ? `?team=${encodeURIComponent(currentTeam)}` : "";
  document.getElementById("mySquadSection").innerHTML =
    '<div class="empty">Running squad evaluation…</div>';
  try {
    const payload = collectLineupPayload();
    const data = await api(`/api/my-squad/test${q}`, { method: "POST", json: payload });
    document.getElementById("mySquadSection").innerHTML = renderSingleSquadEval(
      data.squad.evaluation,
      data.squad.team
    );
    if (status) status.textContent = "Test report generated (not saved).";
  } catch (e) {
    document.getElementById("mySquadSection").innerHTML = `<div class="empty"><span class="badge error">Error</span><p>${esc(e.message)}</p></div>`;
    if (status) status.textContent = `Test failed: ${e.message}`;
  }
}

async function finalizeSquad() {
  const roundLabel = lineupData?.immediate_round?.label || "the current round";
  const ok = window.confirm(
    `This locks your XI for ${roundLabel}. You cannot edit until that matchday is complete. Continue?`
  );
  if (!ok) return;
  const status = document.getElementById("lineupStatus");
  const q = currentTeam ? `?team=${encodeURIComponent(currentTeam)}` : "";
  try {
    const payload = collectLineupPayload();
    await api(`/api/my-lineup/finalize${q}`, { method: "POST", json: payload });
    if (status) status.textContent = "Squad finalized for this round.";
    lineupData = await loadLineup(currentTeam);
    document.getElementById("lineupSection").innerHTML = renderLineupBuilder(lineupData);
    wireLineupBuilder();
    await refreshSquad(currentTeam);
  } catch (e) {
    if (status) status.textContent = `Finalize failed: ${e.message}`;
  }
}

async function loadLineup(teamName) {
  const q = teamName ? `?team=${encodeURIComponent(teamName)}` : "";
  return (await api(`/api/my-lineup${q}`));
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

function wireAdminPicker(allTeams, teamName) {
  const select = document.getElementById("adminTeamSelect");
  if (!select) return;
  const names = [...new Set((allTeams || []).map((t) => t.name))].sort((a, b) =>
    a.localeCompare(b)
  );
  if (teamName && !names.includes(teamName)) names.unshift(teamName);
  select.innerHTML = names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
  if (teamName) select.value = teamName;
  select.addEventListener("change", () => reloadTeam(select.value));
}

function wireLineupBuilder() {
  if (!lineupData?.locked) {
    document.getElementById("lineupFormation")?.addEventListener("change", onFormationChange);
    document.getElementById("saveLineupBtn")?.addEventListener("click", saveLineup);
  }
  document.getElementById("testSquadBtn")?.addEventListener("click", testSquad);
  document.getElementById("finalizeSquadBtn")?.addEventListener("click", finalizeSquad);
}

async function reloadTeam(teamName) {
  currentTeam = teamName;
  lineupData = await loadLineup(teamName);
  document.getElementById("lineupSection").innerHTML = renderLineupBuilder(lineupData);
  wireLineupBuilder();
  if (lineupData.locked) {
    await refreshSquad(teamName);
  } else {
    document.getElementById("mySquadSection").innerHTML =
      '<div class="empty">Use Test squad to preview your lineup report, then finalize before matchday.</div>';
  }
}

async function init() {
  try {
    const sessionInfo = await api("/api/session");
    if (sessionInfo.can_simulate) {
      document.getElementById("adminLinks").hidden = false;
    }
    meta = await api("/api/meta");
    const oppData = await loadOpponents();
    const isAdmin = isAdminUser();
    currentTeam = isAdmin ? oppData.my_team || null : getUser();

    document.getElementById("app").innerHTML = `
      ${isAdmin ? renderAdminTeamPicker() : ""}
      <section id="lineupSection"></section>
      <section id="mySquadSection"><div class="empty">Use Test squad to preview your lineup report, then finalize before matchday.</div></section>
      ${renderOpponentScoutPanel()}
    `;

    if (isAdmin) {
      const allTeams = [...(oppData.teams || [])];
      wireAdminPicker(allTeams, currentTeam);
      if (!currentTeam && allTeams.length) currentTeam = allTeams[0].name;
    }

    if (currentTeam) {
      await reloadTeam(currentTeam);
    } else if (isAdmin) {
      document.getElementById("lineupSection").innerHTML =
        `<div class="card"><p class="muted">Select a team to configure lineup.</p></div>`;
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
