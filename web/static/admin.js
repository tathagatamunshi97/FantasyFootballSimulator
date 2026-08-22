const ADMIN_KEY = "sim_admin_token";

let sheetTeams = [];
let tournaments = [];
let currentId = null;
let currentTournament = null;

function getAdminTokenFromUI() {
  const el = document.getElementById("token");
  const value = (el?.value || getAdminToken() || "").trim();
  if (value) setAdminToken(value);
  return value;
}

function formatApiError(data, statusText) {
  const detail = data?.detail;
  if (!detail) return statusText || "Request failed";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
  }
  return String(detail);
}

async function adminApi(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = getAdminTokenFromUI();
  if (!token) {
    throw new Error("Enter the admin token (same value as SIM_ADMIN_TOKEN on the server).");
  }
  headers["X-Admin-Token"] = token;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
    delete options.json;
  }
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401) {
      throw new Error("Invalid admin token. It must match SIM_ADMIN_TOKEN on the server.");
    }
    throw new Error(formatApiError(data, res.statusText));
  }
  return data;
}

function tLog(msg) {
  const el = document.getElementById("tLog");
  if (el) el.textContent = msg;
}

// --- Tabs ---

function showTab(name) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === name);
  });
  document.getElementById("panel-tournament").hidden = name !== "tournament";
  document.getElementById("panel-teams").hidden = name !== "teams";
  document.getElementById("panel-lineups").hidden = name !== "lineups";
  if (name === "tournament" && getAdminTokenFromUI()) {
    loadTournamentPanel().catch((e) => tLog(e.message));
  }
  if (name === "teams" && getAdminTokenFromUI()) {
    loadTeamPasswords().catch((e) => pwLog(e.message));
  }
  if (name === "lineups" && getAdminTokenFromUI()) {
    loadTeamLineups().catch((e) => lineupsLog(e.message));
  }
  if (location.hash !== `#${name}`) {
    history.replaceState(null, "", `#${name}`);
  }
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
});

// --- Tournament ---

function renderTeamPicker() {
  const el = document.getElementById("teamPicker");
  if (!sheetTeams.length) {
    el.innerHTML = "<p class='muted'>No teams on sheet.</p>";
    return;
  }
  el.innerHTML = sheetTeams
    .map((t) => {
      const ok = t.ready ? "" : " (incomplete)";
      return `<label class="check-row"><input type="checkbox" class="team-cb" value="${esc(t.name)}" checked /> ${esc(t.name)} <span class="muted">${t.player_count}/11${ok}</span></label>`;
    })
    .join("");
}

function selectedTeams() {
  return [...document.querySelectorAll(".team-cb:checked")].map((cb) => cb.value);
}

async function loadSheetTeams() {
  const data = await adminApi("/api/sheets/teams");
  sheetTeams = data.teams || [];
  renderTeamPicker();
}

async function loadTournamentList() {
  const data = await adminApi("/api/tournament");
  tournaments = data.tournaments || [];
  const sel = document.getElementById("tSelect");
  sel.innerHTML =
    `<option value="">— select —</option>` +
    tournaments.map((t) => `<option value="${esc(t.id)}">${esc(t.name)} (${esc(t.status)})</option>`).join("");
  if (currentId) sel.value = currentId;
  renderTournamentListTable();
}

function renderTournamentListTable() {
  const el = document.getElementById("tournamentList");
  if (!el) return;
  if (!tournaments.length) {
    el.innerHTML = "<p class='muted'>No tournaments yet.</p>";
    return;
  }
  const rows = tournaments
    .map(
      (t) => `<tr>
        <td><a href="/tournament?id=${esc(t.id)}" target="_blank">${esc(t.name)}</a></td>
        <td><span class="badge ${esc(t.status)}">${esc(t.status)}</span></td>
        <td class="muted">${t.team_count ?? "—"}</td>
        <td class="muted">${t.updated_at ? new Date(t.updated_at).toLocaleString() : "—"}</td>
        <td><button type="button" class="btn-ghost delete-tournament" data-id="${esc(t.id)}" data-name="${esc(t.name)}">Delete</button></td>
      </tr>`
    )
    .join("");
  el.innerHTML = `<div class="report-table-wrap"><table>
    <thead><tr><th>Name</th><th>Status</th><th>Teams</th><th>Updated</th><th>Actions</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
  el.querySelectorAll(".delete-tournament").forEach((btn) => {
    btn.addEventListener("click", () => deleteTournament(btn.dataset.id, btn.dataset.name));
  });
}

async function deleteTournament(tournamentId, name) {
  if (!confirm(`Delete tournament "${name}"? This cannot be undone.`)) return;
  try {
    tLog(`Deleting tournament ${name}…`);
    await adminApi(`/api/tournament/${tournamentId}`, { method: "DELETE" });
    if (currentId === tournamentId) {
      currentId = null;
      currentTournament = null;
      document.getElementById("controls").innerHTML = "";
      document.getElementById("matchControls").innerHTML = "";
    }
    await loadTournamentList();
    tLog(`Deleted tournament "${name}".`);
  } catch (err) {
    tLog(`Error: ${err.message}`);
  }
}

function validGroupCounts(teamCount) {
  if (teamCount < 4) return teamCount >= 2 ? [1] : [];
  const out = [];
  for (let g = 1; g <= teamCount; g++) {
    if (teamCount % g === 0 && teamCount / g >= 2) out.push(g);
  }
  return out;
}

function validAdvanceOptions(groupCount, teamsPerGroup) {
  const validTotals = [2, 4, 8, 16];
  const opts = [];
  for (let a = 1; a <= teamsPerGroup; a++) {
    const total = groupCount * a;
    if (validTotals.includes(total)) opts.push(a);
  }
  return opts;
}

function knockoutPreview(groupCount, advancePerGroup) {
  const total = groupCount * advancePerGroup;
  let rounds;
  if (total <= 2) rounds = ["Final"];
  else if (total <= 4) rounds = ["Semi-finals", "Final"];
  else if (total <= 8) rounds = ["Quarter-finals", "Semi-finals", "Final"];
  else rounds = ["Round of 16", "Quarter-finals", "Semi-finals", "Final"];
  return { total, rounds };
}

function renderAdvancePreview(groupCount, advancePerGroup) {
  const { total, rounds } = knockoutPreview(groupCount, advancePerGroup);
  return `${advancePerGroup} per group → ${total} teams → ${rounds.join(", ")}`;
}

function anyKnockoutMatchPlayed(t) {
  for (const rnd of (t.knockout || {}).rounds || []) {
    for (const tie of rnd.ties || []) {
      if (tie.played) return true;
      for (const leg of tie.legs || []) {
        if (leg.played) return true;
      }
    }
  }
  return false;
}

function renderGroupSettings(t) {
  const n = (t.team_names || []).length;
  const st = t.status;
  const koGenerated = ((t.knockout || {}).rounds || []).length > 0;
  if (!["draft", "group_draw", "group_stage", "knockout"].includes(st) || n < 2) {
    return "";
  }

  if (koGenerated) {
    const played = anyKnockoutMatchPlayed(t);
    const fmt = t.knockout?.format === "single_elim" ? "Single match" : "Two-legged";
    return `
    <div class="form-row inline" style="margin-top:0.5rem">
      <p class="muted">Knockout bracket generated (${esc(fmt)}).</p>
      <button type="button" class="btn-ghost" id="resetKnockoutBtn" ${played ? "disabled" : ""}>Reset knockout bracket</button>
    </div>
    <p class="muted">${played ? "Cannot reset — a knockout match has already been played." : "Clears the bracket so you can change the knockout format and regenerate."}</p>`;
  }

  const gCount = t.settings?.group_count ?? 1;
  const perGroup = t.settings?.teams_per_group ?? n;
  const advanceOpts = validAdvanceOptions(gCount, perGroup);
  const curAdvance = t.settings?.advance_per_group ?? advanceOpts[0] ?? 1;
  const advanceOptions = advanceOpts
    .map((a) => {
      const sel = a === curAdvance ? " selected" : "";
      return `<option value="${a}"${sel}>${a} per group</option>`;
    })
    .join("");

  const layoutRow =
    st === "draft"
      ? (() => {
          const opts = validGroupCounts(n);
          if (!opts.length) return "";
          const cur = gCount;
          const options = opts
            .map((g) => {
              const per = n / g;
              const sel = g === cur ? " selected" : "";
              return `<option value="${g}"${sel}>${g} group${g === 1 ? "" : "s"} × ${per} teams</option>`;
            })
            .join("");
          return `
    <div class="form-row inline" style="margin-top:0.5rem">
      <label for="groupCount">Group layout</label>
      <select id="groupCount">${options}</select>
    </div>`;
        })()
      : `<p class="muted">Group layout: ${gCount} groups × ${perGroup} teams (locked after draw)</p>`;

  const curFormat = t.settings?.knockout_format === "single_elim" ? "single_elim" : "two_leg";
  const formatOptions = `
      <option value="two_leg"${curFormat === "two_leg" ? " selected" : ""}>Two-legged (Final single match)</option>
      <option value="single_elim"${curFormat === "single_elim" ? " selected" : ""}>Single match</option>`;

  return `
    ${layoutRow}
    <div class="form-row inline" style="margin-top:0.5rem">
      <label for="advancePerGroup">Knockout qualifiers</label>
      <select id="advancePerGroup">${advanceOptions}</select>
    </div>
    <div class="form-row inline" style="margin-top:0.5rem">
      <label for="knockoutFormat">Knockout format</label>
      <select id="knockoutFormat">${formatOptions}</select>
      <button type="button" class="btn-ghost" id="saveGroupBtn">Save settings</button>
    </div>
    <p class="muted" id="advancePreview">${esc(renderAdvancePreview(gCount, curAdvance))}</p>`;
}

function renderControls(t) {
  const el = document.getElementById("controls");
  const st = t.status;
  const groupSettings = renderGroupSettings(t);
  el.innerHTML = `
    <div>
      <p><strong>${esc(t.name)}</strong></p>
      <p class="muted">Status: ${esc(st)} · ${(t.team_names || []).length} teams</p>
      <p class="muted">${t.settings?.group_count || "?"} groups × ${t.settings?.teams_per_group || "?"} teams · top ${t.settings?.advance_per_group || "?"} advance</p>
      ${groupSettings}
    </div>
    <div class="btn-stack">
      <button type="button" class="btn-ghost" data-action="draw" ${st !== "draft" && st !== "group_draw" ? "disabled" : ""}>Run group draw</button>
      <button type="button" class="btn-ghost" data-action="fixtures" ${!t.groups || !Object.keys(t.groups).length ? "disabled" : ""}>Generate fixtures</button>
      <button type="button" class="btn-ghost" data-action="knockout" ${st !== "group_stage" && st !== "knockout" ? "disabled" : ""}>Generate knockout</button>
      <button type="button" class="btn-primary" data-action="refresh">Refresh state</button>
      <a href="/tournament?id=${esc(t.id)}" class="btn-link" target="_blank">Open viewer</a>
    </div>`;
  el.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => runAction(btn.dataset.action));
  });
  const saveBtn = document.getElementById("saveGroupBtn");
  if (saveBtn) {
    saveBtn.addEventListener("click", () => saveGroupSettings().catch((e) => tLog(e.message)));
  }
  const resetKoBtn = document.getElementById("resetKnockoutBtn");
  if (resetKoBtn) {
    resetKoBtn.addEventListener("click", () => resetKnockoutBracket().catch((e) => tLog(e.message)));
  }
  const advanceSel = document.getElementById("advancePerGroup");
  const groupSel = document.getElementById("groupCount");
  const previewEl = document.getElementById("advancePreview");
  const updatePreview = () => {
    if (!previewEl || !advanceSel) return;
    const gCount = groupSel ? Number(groupSel.value) : (t.settings?.group_count ?? 1);
    const advance = Number(advanceSel.value);
    previewEl.textContent = renderAdvancePreview(gCount, advance);
  };
  if (advanceSel) advanceSel.addEventListener("change", updatePreview);
  if (groupSel) {
    groupSel.addEventListener("change", () => {
      const n = (t.team_names || []).length;
      const gCount = Number(groupSel.value);
      const perGroup = n / gCount;
      const opts = validAdvanceOptions(gCount, perGroup);
      if (advanceSel && opts.length) {
        advanceSel.innerHTML = opts
          .map((a) => `<option value="${a}">${a} per group</option>`)
          .join("");
        if (!opts.includes(Number(advanceSel.value))) {
          advanceSel.value = String(opts.includes(2) ? 2 : opts[opts.length - 1]);
        }
      }
      updatePreview();
    });
  }
}

async function saveGroupSettings() {
  if (!currentId) return;
  const advanceSel = document.getElementById("advancePerGroup");
  const groupSel = document.getElementById("groupCount");
  const formatSel = document.getElementById("knockoutFormat");
  const payload = {};
  if (groupSel) payload.group_count = Number(groupSel.value);
  if (advanceSel) payload.advance_per_group = Number(advanceSel.value);
  if (formatSel) payload.knockout_format = formatSel.value;
  if (!Object.keys(payload).length) return;
  tLog("Saving tournament settings…");
  await adminApi(`/api/tournament/${currentId}/settings`, {
    method: "PATCH",
    json: payload,
  });
  await loadCurrent();
  tLog("Tournament settings saved");
}

async function resetKnockoutBracket() {
  if (!currentId) return;
  if (!confirm("Reset the knockout bracket? This discards the generated (unplayed) fixtures so you can change settings and regenerate.")) {
    return;
  }
  tLog("Resetting knockout bracket…");
  await adminApi(`/api/tournament/${currentId}/knockout/reset`, { method: "POST" });
  await loadCurrent();
  tLog("Knockout bracket reset");
}

function renderMatchControls(t) {
  const el = document.getElementById("matchControls");
  const parts = [];

  for (const [gkey, group] of Object.entries(t.groups || {}).sort()) {
    const pending = (group.fixtures || []).filter((fx) => !fx.played);
    if (!pending.length) continue;
    parts.push(`<h3 style="font-size:0.9rem;margin:0.5rem 0">Group ${esc(gkey)} — pending</h3>`);
    parts.push(
      pending
        .map(
          (fx) =>
            `<button type="button" class="btn-ghost run-match" data-id="${esc(fx.id)}">${esc(fx.home)} vs ${esc(fx.away)}</button>`
        )
        .join(" ")
    );
  }

  for (const rnd of (t.knockout || {}).rounds || []) {
    const pending = (rnd.ties || []).filter((tie) => !tie.played && tie.home && tie.away);
    if (!pending.length) continue;
    parts.push(`<h3 style="font-size:0.9rem;margin:0.5rem 0">${esc(rnd.label || rnd.name)} — pending</h3>`);
    parts.push(
      pending
        .map(
          (tie) =>
            `<button type="button" class="btn-ghost run-ko" data-id="${esc(tie.id)}">${esc(tie.home)} vs ${esc(tie.away)}</button>`
        )
        .join(" ")
    );
  }

  el.innerHTML = parts.length
    ? `<div class="card"><h2>Run matches</h2>${parts.join("")}</div>`
    : `<p class="muted">No pending matches.</p>`;

  el.querySelectorAll(".run-match").forEach((btn) => {
    btn.addEventListener("click", () => runGroupMatch(btn.dataset.id));
  });
  el.querySelectorAll(".run-ko").forEach((btn) => {
    btn.addEventListener("click", () => runKoMatch(btn.dataset.id));
  });
}

async function loadCurrent() {
  if (!currentId) return;
  const data = await adminApi(`/api/tournament/${currentId}`);
  currentTournament = data.tournament;
  renderControls(currentTournament);
  renderMatchControls(currentTournament);
}

async function runAction(action) {
  if (!currentId) return;
  try {
    tLog(`Running ${action}…`);
    if (action === "draw") {
      await adminApi(`/api/tournament/${currentId}/group-draw`, { method: "POST", json: {} });
    } else if (action === "fixtures") {
      await adminApi(`/api/tournament/${currentId}/group-fixtures`, { method: "POST" });
    } else if (action === "knockout") {
      await adminApi(`/api/tournament/${currentId}/knockout/generate`, { method: "POST" });
    } else if (action === "refresh") {
      await loadCurrent();
      tLog("Refreshed.");
      return;
    }
    await loadCurrent();
    tLog(`Done: ${action}`);
  } catch (err) {
    tLog(`Error: ${err.message}`);
  }
}

function findPlayedFixture(t, matchId) {
  for (const group of Object.values(t.groups || {})) {
    const fx = (group.fixtures || []).find((f) => f.id === matchId);
    if (fx?.played) return fx;
  }
  for (const rnd of t.knockout?.rounds || []) {
    const tie = (rnd.ties || []).find((item) => item.id === matchId);
    if (tie?.played) return tie;
  }
  return null;
}

async function waitForTournamentMatch(matchId, experimentId) {
  const deadline = Date.now() + 180000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    if (experimentId) {
      const expData = await adminApi(`/api/experiments/${experimentId}`);
      const exp = expData.experiment;
      if (exp?.status === "error") {
        throw new Error(exp.message || "Simulation failed");
      }
    }
    const data = await adminApi(`/api/tournament/${currentId}`);
    currentTournament = data.tournament;
    const played = findPlayedFixture(currentTournament, matchId);
    if (played) {
      renderControls(currentTournament);
      renderMatchControls(currentTournament);
      return played;
    }
  }
  throw new Error(
    experimentId
      ? `Timed out waiting for ${matchId}. Open /experiment/${experimentId} for status.`
      : `Timed out waiting for ${matchId}. Click Refresh state.`
  );
}

async function runGroupMatch(matchId) {
  if (!currentId) return;
  try {
    tLog(`Opening Matchday for ${matchId}…`);
    await adminApi(`/api/tournament/${currentId}/matches/${matchId}/run`, { method: "POST" });
    tLog(`Matchday session ready — redirecting to live board.`);
    window.location.href = "/matchday";
  } catch (err) {
    tLog(`Error: ${err.message}`);
  }
}

async function runKoMatch(matchId) {
  if (!currentId) return;
  try {
    tLog(`Opening Matchday knockout for ${matchId}…`);
    await adminApi(`/api/tournament/${currentId}/knockout/matches/${matchId}/run`, {
      method: "POST",
    });
    tLog(`Matchday session ready — redirecting to live board.`);
    window.location.href = "/matchday";
  } catch (err) {
    tLog(`Error: ${err.message}`);
  }
}

async function createTournament() {
  const name = document.getElementById("tName").value.trim() || "Fantasy Cup";
  const team_names = selectedTeams();
  if (team_names.length < 2) {
    tLog("Select at least 2 teams.");
    return;
  }
  try {
    tLog("Creating tournament…");
    const res = await adminApi("/api/tournament", { method: "POST", json: { name, team_names } });
    currentId = res.tournament.id;
    await loadTournamentList();
    document.getElementById("tSelect").value = currentId;
    await loadCurrent();
    tLog(`Created ${res.tournament.name} (${res.tournament.id})`);
  } catch (err) {
    tLog(`Error: ${err.message}`);
  }
}

async function loadTournamentPanel() {
  await loadSheetTeams();
  await loadTournamentList();
  if (tournaments.length && !currentId) {
    currentId = tournaments[0].id;
    document.getElementById("tSelect").value = currentId;
    await loadCurrent();
  }
}

// --- Team passwords ---

function pwLog(msg) {
  const el = document.getElementById("pwLog");
  if (el) el.textContent = msg;
}

function renderPasswordTable(teams) {
  if (!teams.length) return "<p class='muted'>No teams on sheet.</p>";
  const rows = teams
    .map((t) => {
      const status = t.has_password
        ? "<span class='badge ready'>Password set</span>"
        : "<span class='badge'>Needs setup</span>";
      const resetBtn = t.has_password
        ? `<button type="button" class="btn-ghost reset-pw" data-team="${esc(t.name)}">Reset</button>`
        : "—";
      return `<tr>
        <td>${esc(t.name)}</td>
        <td class="muted">${t.player_count}/11</td>
        <td>${status}</td>
        <td>${resetBtn}</td>
      </tr>`;
    })
    .join("");
  return `<div class="report-table-wrap"><table>
    <thead><tr><th>Team</th><th>Roster</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}

async function loadTeamPasswords() {
  const data = await adminApi("/api/admin/team-passwords");
  const teams = data.teams || [];
  document.getElementById("pwTable").innerHTML = renderPasswordTable(teams);
  document.getElementById("pwTable").querySelectorAll(".reset-pw").forEach((btn) => {
    btn.addEventListener("click", () => resetTeamPassword(btn.dataset.team));
  });
  const set = teams.filter((t) => t.has_password).length;
  pwLog(`Loaded ${teams.length} team(s); ${set} with password set.`);
}

async function resetTeamPassword(teamName) {
  if (!confirm(`Reset password for "${teamName}"? They will need to set a new password on next login.`)) {
    return;
  }
  try {
    pwLog(`Resetting password for ${teamName}…`);
    const res = await adminApi("/api/admin/team-passwords/reset", {
      method: "POST",
      json: { team_name: teamName },
    });
    pwLog(res.message || "Password reset.");
    await loadTeamPasswords();
  } catch (err) {
    pwLog(`Error: ${err.message}`);
  }
}

// --- Squad lineups / finalize locks ---

function lineupsLog(msg) {
  const el = document.getElementById("lineupsLog");
  if (el) el.textContent = msg;
}

function renderLineupsTable(teams) {
  if (!teams.length) return "<p class='muted'>No saved lineups yet.</p>";
  const rows = teams
    .map((t) => {
      const lockBadge = t.locked
        ? "<span class='badge ready'>Locked</span>"
        : t.finalized
          ? "<span class='badge muted'>Prior round</span>"
          : "<span class='badge'>Open</span>";
      const roundLabel = t.finalized_round_label || t.finalized_round || "—";
      const unfinalizeBtn = t.finalized
        ? `<button type="button" class="btn-ghost unfinalize-team" data-team="${esc(t.team_name)}">Unfinalize</button>`
        : "—";
      return `<tr>
        <td>${esc(t.team_name)}</td>
        <td class="muted">${esc(t.formation || "—")}</td>
        <td>${lockBadge}</td>
        <td class="muted">${esc(roundLabel)}</td>
        <td>${unfinalizeBtn}</td>
      </tr>`;
    })
    .join("");
  return `<div class="report-table-wrap"><table>
    <thead><tr><th>Team</th><th>Formation</th><th>Status</th><th>Finalized for</th><th>Actions</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}

async function loadTeamLineups() {
  const data = await adminApi("/api/admin/team-lineups");
  const teams = data.teams || [];
  document.getElementById("lineupsTable").innerHTML = renderLineupsTable(teams);
  document.getElementById("lineupsTable").querySelectorAll(".unfinalize-team").forEach((btn) => {
    btn.addEventListener("click", () => unfinalizeTeam(btn.dataset.team));
  });
  const locked = teams.filter((t) => t.locked).length;
  const finalized = teams.filter((t) => t.finalized).length;
  lineupsLog(`Loaded ${teams.length} lineup(s); ${finalized} finalized (${locked} locked for current round).`);
}

async function unfinalizeTeam(teamName) {
  if (!confirm(`Unfinalize "${teamName}"? They will be able to edit their squad again.`)) return;
  try {
    lineupsLog(`Unfinalizing ${teamName}…`);
    await adminApi(`/api/admin/team-lineups/${encodeURIComponent(teamName)}/unfinalize`, {
      method: "POST",
    });
    lineupsLog(`Unfinalized ${teamName}.`);
    await loadTeamLineups();
  } catch (err) {
    lineupsLog(`Error: ${err.message}`);
  }
}

async function unfinalizeAllTeams() {
  if (!confirm("Unfinalize all teams? Every squad lock will be cleared (saved lineups are kept).")) {
    return;
  }
  try {
    lineupsLog("Unfinalizing all teams…");
    const res = await adminApi("/api/admin/team-lineups/unfinalize-all", { method: "POST" });
    lineupsLog(res.message || "Done.");
    await loadTeamLineups();
  } catch (err) {
    lineupsLog(`Error: ${err.message}`);
  }
}

// --- Init ---

document.getElementById("token").value = getAdminToken() || "";
document.getElementById("token").addEventListener("input", (e) => {
  setAdminToken(e.target.value.trim());
});

document.getElementById("createBtn").addEventListener("click", () => createTournament().catch((e) => tLog(e.message)));
document.getElementById("refreshPwBtn").addEventListener("click", () => loadTeamPasswords().catch((e) => pwLog(e.message)));
document.getElementById("refreshLineupsBtn").addEventListener("click", () => loadTeamLineups().catch((e) => lineupsLog(e.message)));
document.getElementById("unfinalizeAllBtn").addEventListener("click", () => unfinalizeAllTeams().catch((e) => lineupsLog(e.message)));
document.getElementById("tSelect").addEventListener("change", (e) => {
  currentId = e.target.value || null;
  if (currentId) loadCurrent().catch((err) => tLog(err.message));
});

function _storageBadge(label, status) {
  const color = status.ok ? "var(--success)" : status.enabled ? "var(--warn)" : "var(--muted)";
  const bg = status.ok ? "var(--success-soft)" : status.enabled ? "var(--warn-soft)" : "var(--panel2)";
  const icon = status.ok ? "✓" : status.enabled ? "⚠" : "—";
  return `
    <div style="flex:1;min-width:220px;padding:0.75rem;border-radius:8px;background:${bg};border:1px solid ${color}">
      <div style="font-weight:600;color:${color}">${icon} ${label}</div>
      <div style="font-size:0.85rem;color:var(--text);margin-top:0.25rem">${esc(status.message || "")}</div>
    </div>
  `;
}

async function checkStorageStatus() {
  const el = document.getElementById("storageStatus");
  el.innerHTML = `<p class="muted">Checking...</p>`;
  try {
    const res = await adminApi("/api/admin/storage-status");
    el.innerHTML =
      _storageBadge("PostgreSQL (structured data)", res.postgres) +
      _storageBadge(`R2 (${res.r2.bucket || "tournament files"})`, res.r2);
  } catch (e) {
    el.innerHTML = `<p class="muted">Error: ${esc(e.message)}</p>`;
  }
}

document.getElementById("storageCheckBtn").addEventListener("click", checkStorageStatus);

const initialTab =
  location.hash === "#teams"
    ? "teams"
    : location.hash === "#lineups"
      ? "lineups"
      : "tournament";
showTab(initialTab);
