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

let activeSquadTab = "lineup";
let scoutTabLoaded = false;
let analysisTabLoaded = false;
let statsTabLoaded = false;

const SQUAD_TABS = [
  ["lineup", "Lineup Builder"],
  ["scout", "Scout Opponent"],
  ["analysis", "Analysis"],
  ["stats", "Statistics"],
];

function renderSquadTabBar() {
  return `<nav class="tab-bar">${SQUAD_TABS.map(
    ([id, label]) =>
      `<button type="button" class="tab-btn${activeSquadTab === id ? " active" : ""}" data-squad-tab="${id}">${esc(label)}</button>`
  ).join("")}</nav>`;
}

function switchSquadTab(tab) {
  activeSquadTab = tab;
  document.querySelectorAll(".tab-btn[data-squad-tab]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.squadTab === tab);
  });
  const panels = { lineup: "tabPanelLineup", scout: "tabPanelScout", analysis: "tabPanelAnalysis", stats: "tabPanelStats" };
  for (const [id, elId] of Object.entries(panels)) {
    const el = document.getElementById(elId);
    if (el) el.hidden = id !== tab;
  }
  if (tab === "scout" && !scoutTabLoaded) {
    scoutTabLoaded = true;
    initScoutTab();
  }
  if (tab === "analysis" && !analysisTabLoaded) {
    analysisTabLoaded = true;
    loadAnalysisTab();
  }
  if (tab === "stats" && !statsTabLoaded) {
    statsTabLoaded = true;
    loadStatsTab();
  }
}

function wireSquadTabBar() {
  document.querySelectorAll("[data-squad-tab]").forEach((btn) => {
    btn.addEventListener("click", () => switchSquadTab(btn.dataset.squadTab));
  });
}

function renderLineupBuilder(data) {
  const config = data.lineup || {};
  const roster = data.roster || [];
  const formation = config.formation || "4-3-3 flat";
  const formations = meta?.formations?.formations || ["4-3-3 flat", "4-4-2", "3-5-2"];
  const slots = meta?.formations?.slots?.[formation] || [];
  const { map: lineupMap, filters: roleFilters } = lineupMapFromConfig(config);
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

  const assignedNow = new Set(Object.values(lineupMap).filter(Boolean));
  const subsNow = roster.filter((p) => !assignedNow.has(p));

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
      <p class="muted">Select your starting XI from your ${roster.length}-player roster. Role dropdowns appear on AM/CM/DM and wide/fullback slots (GK/CB/ST stay locked). Finalize locks your XI for the current tournament matchday.</p>
      <p style="margin:0.5rem 0;display:flex;gap:0.5rem;flex-wrap:wrap">${savedBadge}${finalizedBadge}</p>
      <div class="form-row" style="margin-top:0.75rem">
        <label for="lineupFormation">Formation</label>
        <select id="lineupFormation" ${disabled}>${formationOpts}</select>
      </div>
      <div class="slot-grid">${slotRows}</div>
      <div class="bench-section" style="margin-top:1.25rem">
        <h3 style="font-size:0.95rem;margin:0 0 0.5rem">Subs</h3>
        <p class="muted" style="margin:0 0 0.5rem">Roster players not in the starting XI (<span id="benchCount">${subsNow.length}</span> of ${roster.length}).</p>
        <div class="bench-list" id="benchList">${
          subsNow.length
            ? subsNow.map((p) => `<span class="bench-chip">${esc(p)}</span>`).join("")
            : '<span class="muted">No subs — full roster is in the starting XI.</span>'
        }</div>
      </div>
      <div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:1rem">
        <button type="button" id="saveLineupBtn" class="btn-primary" ${disabled}>Save lineup</button>
        <button type="button" id="testSquadBtn" class="btn-ghost">Test squad</button>
        <button type="button" id="finalizeSquadBtn" class="btn-ghost" ${locked ? "disabled" : ""}>Finalize squad</button>
        ${
          (isAdminUser() || getAdminToken()) && data.finalized
            ? `<button type="button" id="unfinalizeSquadBtn" class="btn-ghost">Unfinalize</button>`
            : ""
        }
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

function renderSlotRow(slot, val, roster, formation, roleFilter, locked) {
  const filterCtrl = roleFilterControl(slot, formation, roleFilter, locked);
  return `<div class="form-row slot-row">
      <label>${esc(slot)}</label>
      <div class="slot-controls">
        ${slotPlayerControl(slot, val, roster, locked)}
        ${filterCtrl}
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

let scoutOpponentName = null;
let scoutOpponentRoster = [];

function renderScoutTabShell() {
  if (!opponents.length) {
    return `<div class="card"><h2>Scout opponent</h2><p class="muted">No other sheet teams available.</p></div>`;
  }
  const opts = opponents
    .map((t) => `<option value="${esc(t.name)}">${esc(t.name)} (${t.player_count}/11)</option>`)
    .join("");
  return `
    <div class="card">
      <h2>Scout opponent</h2>
      <p class="muted">Load their expected lineup, then change any slot to scout a different XI (e.g. their best available team). No score predictions.</p>
      <div style="display:flex;gap:0.75rem;flex-wrap:wrap;align-items:flex-end;margin-top:0.75rem">
        <div style="flex:1;min-width:200px">
          <label for="scoutSelect">Opponent</label>
          <select id="scoutSelect" class="input-wide">${opts}</select>
        </div>
        <button type="button" id="scoutLoadBtn" class="btn-primary">Load opponent</button>
      </div>
    </div>
    <div id="scoutLineupEditor"></div>
    <div id="scoutResult" style="margin-top:1rem"></div>`;
}

function initScoutTab() {
  const panel = document.getElementById("tabPanelScout");
  if (!panel) return;
  panel.innerHTML = renderScoutTabShell();
  document.getElementById("scoutLoadBtn")?.addEventListener("click", () => {
    const sel = document.getElementById("scoutSelect");
    if (sel?.value) loadScoutOpponent(sel.value);
  });
}

function scoutMyTeamQuery() {
  const myTeam = isAdminUser() ? document.getElementById("adminTeamSelect")?.value : null;
  return myTeam ? `?my_team=${encodeURIComponent(myTeam)}` : "";
}

async function loadScoutOpponent(opponentName) {
  scoutOpponentName = opponentName;
  const editorEl = document.getElementById("scoutLineupEditor");
  const resultEl = document.getElementById("scoutResult");
  if (editorEl) editorEl.innerHTML = '<div class="empty">Loading opponent…</div>';
  if (resultEl) resultEl.innerHTML = "";
  try {
    const data = await api(`/api/scout/${encodeURIComponent(opponentName)}${scoutMyTeamQuery()}`);
    const scout = data.scout;
    // Must be resolved player names (matching expected_lineup), not the raw
    // sheet roster from /api/squad/opponents -- a raw name like "J P Van
    // Hecke" doesn't match its resolved form "Jan Paul van Hecke", so the
    // <option> for the seeded starter silently wouldn't exist and the slot
    // would render empty despite the API correctly naming a starter there.
    const overview = scout.roster_overview || {};
    scoutOpponentRoster = [...new Set([...(overview.starting_xi || []), ...(overview.bench || [])])];
    if (editorEl) editorEl.innerHTML = renderScoutLineupEditor(scout);
    wireScoutLineupEditor();
    if (resultEl) {
      resultEl.innerHTML = renderScoutReport(scout);
      wireGamePlanButton();
    }
  } catch (e) {
    if (editorEl) editorEl.innerHTML = "";
    if (resultEl) resultEl.innerHTML = `<div class="empty"><span class="badge error">Error</span><p>${esc(e.message)}</p></div>`;
  }
}

function oppSlotPlayerControl(slot, val, roster) {
  const opts = ['<option value="">— pick player —</option>'];
  roster.forEach((p) => {
    opts.push(`<option value="${esc(p)}" ${p === val ? "selected" : ""}>${esc(p)}</option>`);
  });
  return `<select data-oslot="${esc(slot)}">${opts.join("")}</select>`;
}

function renderOppSlotGrid(formation, lineupMap) {
  const slots = meta?.formations?.slots?.[formation] || [];
  return slots
    .map(
      (slot) => `
    <div class="form-row slot-row">
      <label>${esc(slot)}</label>
      <div class="slot-controls">${oppSlotPlayerControl(slot, (lineupMap && lineupMap[slot]) || "", scoutOpponentRoster)}</div>
    </div>`
    )
    .join("");
}

function renderScoutLineupEditor(scout) {
  const formation = scout.formation || meta?.formations?.formations?.[0] || "4-3-3 flat";
  const formations = meta?.formations?.formations || [formation];
  const lineupMap = {};
  (scout.expected_lineup || []).forEach((r) => {
    lineupMap[r.slot] = r.player || "";
  });
  const formationOpts = formations
    .map((f) => `<option value="${esc(f)}" ${f === formation ? "selected" : ""}>${esc(f)}</option>`)
    .join("");
  return `
    <div class="card" style="margin-top:1rem">
      <h3 style="font-size:0.95rem;margin:0 0 0.35rem">Their lineup — ${esc(scoutOpponentName)}</h3>
      <p class="muted" style="margin:0 0 0.75rem">Seeded from their saved lineup.</p>
      <div class="form-row">
        <label for="scoutFormation">Formation</label>
        <select id="scoutFormation">${formationOpts}</select>
      </div>
      <div class="slot-grid" id="scoutSlotGrid" style="margin-top:0.75rem">${renderOppSlotGrid(formation, lineupMap)}</div>
      <button type="button" id="scoutRescoutBtn" class="btn-primary" style="margin-top:1rem">Scout this XI</button>
      <p id="scoutEditorStatus" class="muted" style="margin-top:0.5rem"></p>
    </div>`;
}

function wireScoutLineupEditor() {
  document.getElementById("scoutFormation")?.addEventListener("change", () => {
    const formation = document.getElementById("scoutFormation").value;
    const grid = document.getElementById("scoutSlotGrid");
    if (grid) grid.innerHTML = renderOppSlotGrid(formation, {});
  });
  document.getElementById("scoutRescoutBtn")?.addEventListener("click", rescoutWithCustomLineup);
}

// A blank slot or the same player picked twice both fail server-side
// validation with a terse error -- catch it here first so the message is
// actually useful ("CB1 is empty" beats a raw exception string).
function validateLineupSlots(lineup) {
  const empty = lineup.filter((r) => !r.player);
  if (empty.length) return `Pick a player for: ${empty.map((r) => r.slot).join(", ")}.`;
  const seen = new Map();
  for (const r of lineup) {
    if (seen.has(r.player)) return `${r.player} is picked twice (${seen.get(r.player)} and ${r.slot}).`;
    seen.set(r.player, r.slot);
  }
  return null;
}

async function rescoutWithCustomLineup() {
  const formation = document.getElementById("scoutFormation")?.value;
  const slots = meta?.formations?.slots?.[formation] || [];
  const lineup = slots.map((slot) => {
    const el = document.querySelector(`select[data-oslot="${slot}"]`);
    return { slot, player: (el?.value || "").trim(), captain: false, vice_captain: false };
  });
  const status = document.getElementById("scoutEditorStatus");
  const resultEl = document.getElementById("scoutResult");
  const validationError = validateLineupSlots(lineup);
  if (validationError) {
    if (status) status.textContent = validationError;
    return;
  }
  if (status) status.textContent = "Scouting…";
  try {
    const data = await api(`/api/scout/${encodeURIComponent(scoutOpponentName)}${scoutMyTeamQuery()}`, {
      method: "POST",
      json: { formation, lineup },
    });
    if (resultEl) {
      resultEl.innerHTML = renderScoutReport(data.scout);
      wireGamePlanButton();
    }
    if (status) status.textContent = "Scouted with your custom XI.";
  } catch (e) {
    if (status) status.textContent = `Scout failed: ${e.message}`;
  }
}

function wireGamePlanButton() {
  const container = document.getElementById("gamePlanContainer");
  if (!container) return;
  container.innerHTML = `<button type="button" id="gamePlanBtn" class="btn-ghost">Generate AI game plan</button>`;
  document.getElementById("gamePlanBtn")?.addEventListener("click", generateGamePlan);
}

async function generateGamePlan() {
  const container = document.getElementById("gamePlanContainer");
  if (!container || !scoutOpponentName) return;
  container.innerHTML = '<p class="muted">Thinking through the matchup…</p>';
  const formation = document.getElementById("scoutFormation")?.value;
  const slots = meta?.formations?.slots?.[formation] || [];
  const hasCustom = slots.some((slot) => document.querySelector(`select[data-oslot="${slot}"]`));
  const body = hasCustom
    ? {
        formation,
        lineup: slots.map((slot) => {
          const el = document.querySelector(`select[data-oslot="${slot}"]`);
          return { slot, player: (el?.value || "").trim(), captain: false, vice_captain: false };
        }),
      }
    : { formation: "", lineup: [] };
  try {
    const data = await api(`/api/scout/${encodeURIComponent(scoutOpponentName)}/game-plan${scoutMyTeamQuery()}`, {
      method: "POST",
      json: body,
    });
    container.innerHTML = data.game_plan
      ? renderGamePlan(data.game_plan)
      : '<p class="muted">AI game plan isn\'t available right now — the deterministic scout report above still stands on its own.</p>';
  } catch (e) {
    container.innerHTML = `<p class="muted">Game plan failed: ${esc(e.message)}</p>`;
  }
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
    updateBenchList();
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
    document.getElementById("mySquadSection").innerHTML =
      renderSingleSquadEval(data.squad.evaluation, data.squad.team) + renderWhatIfPanel(data.squad.team);
    wireWhatIfPanel();
    if (status) status.textContent = "Test report generated (not saved).";
  } catch (e) {
    document.getElementById("mySquadSection").innerHTML = `<div class="empty"><span class="badge error">Error</span><p>${esc(e.message)}</p></div>`;
    if (status) status.textContent = `Test failed: ${e.message}`;
  }
}

const _WHATIF_UNIT_LABELS = [
  ["attack", "Attack", true],
  ["finishing", "Finishing", true],
  ["chance_creation", "Creation", true],
  ["midfield", "Midfield", true],
  ["defence", "Defence", true],
  ["midfield_defence", "Mid-def", true],
  ["transition_risk", "Trans risk", false],
  ["goalkeeper", "GK", true],
  ["overall", "Overall", true],
];
const _WHATIF_COMPOSITE_LABELS = [
  ["creativity", "Creativity", true],
  ["midfield_control", "Mid control", true],
  ["possession_control", "Possession", true],
  ["finishing_threat", "Fin threat", true],
  ["defensive_solidity", "Def solidity", true],
  ["attacking_effectiveness", "Atk effect", true],
  ["pressing_intensity", "Pressing", true],
  ["press_resistance", "Press resist", true],
  ["transition_threat", "Trans threat", true],
  ["aerial_defence", "Aerial def", true],
  ["overall", "Overall", true],
];

function renderWhatIfPanel(team) {
  const lineup = team?.lineup || [];
  const bench = team?.bench || [];
  if (!lineup.length || !bench.length) return "";
  const slotOpts = lineup
    .map((r) => `<option value="${esc(r.slot)}">${esc(r.slot)} — ${esc(r.player)}</option>`)
    .join("");
  const playerOpts = bench.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
  return `
    <div class="card whatif-card" style="margin-top:1rem">
      <h3 style="font-size:0.95rem;margin:0 0 0.35rem">What if?</h3>
      <p class="muted" style="margin:0 0 0.75rem">Swap a bench player into a slot and see how the ratings move. Not saved.</p>
      <div style="display:flex;gap:0.75rem;flex-wrap:wrap;align-items:flex-end">
        <div style="flex:1;min-width:170px">
          <label for="whatifSlot">Slot (out)</label>
          <select id="whatifSlot">${slotOpts}</select>
        </div>
        <div style="flex:1;min-width:170px">
          <label for="whatifPlayer">Bring in</label>
          <select id="whatifPlayer">${playerOpts}</select>
        </div>
        <button type="button" id="whatifBtn" class="btn-ghost">Compare</button>
      </div>
      <div id="whatifResult" style="margin-top:0.85rem"></div>
    </div>`;
}

function whatifRow(label, block, higherBetter) {
  if (!block) return "";
  const d = block.delta;
  if (Math.abs(d) < 0.005) {
    return `<div class="whatif-row"><span class="wr-label">${esc(label)}</span><span class="muted">${num(
      block.before
    )} → ${num(block.after)} · no change</span></div>`;
  }
  const good = higherBetter ? d > 0 : d < 0;
  const cls = good ? "wr-up" : "wr-down";
  const sign = d > 0 ? "+" : "";
  return `<div class="whatif-row ${cls}"><span class="wr-label">${esc(label)}</span><span>${num(
    block.before
  )} → ${num(block.after)} <strong>(${sign}${num(d)})</strong></span></div>`;
}

function renderWhatIfResult(whatif) {
  const unitRows = _WHATIF_UNIT_LABELS.map(([k, l, hb]) => whatifRow(l, whatif.units[k], hb)).join("");
  const compRows = _WHATIF_COMPOSITE_LABELS.map(([k, l, hb]) => whatifRow(l, whatif.team_composites[k], hb)).join(
    ""
  );
  return `
    <div class="whatif-summary">
      <p><strong>${esc(whatif.out_player)}</strong> out, <strong>${esc(whatif.in_player)}</strong> in (${esc(
    whatif.slot
  )})</p>
      <h4 style="font-size:0.8rem;margin:0.75rem 0 0.25rem">Unit ratings</h4>
      <div class="whatif-grid">${unitRows}</div>
      <h4 style="font-size:0.8rem;margin:0.75rem 0 0.25rem">Team profile</h4>
      <div class="whatif-grid">${compRows}</div>
    </div>`;
}

function compareSlotControl(prefix, slot, val, roster) {
  const opts = ['<option value="">— pick player —</option>'];
  roster.forEach((p) => {
    opts.push(`<option value="${esc(p)}" ${p === val ? "selected" : ""}>${esc(p)}</option>`);
  });
  return `<select data-cslot="${esc(prefix)}:${esc(slot)}">${opts.join("")}</select>`;
}

function renderCompareSlotGrid(prefix, formation, lineupMap, roster) {
  const slots = meta?.formations?.slots?.[formation] || [];
  return slots
    .map(
      (slot) => `
    <div class="form-row slot-row">
      <label>${esc(slot)}</label>
      <div class="slot-controls">${compareSlotControl(prefix, slot, (lineupMap && lineupMap[slot]) || "", roster)}</div>
    </div>`
    )
    .join("");
}

function renderCompareLineupSide(prefix, label, team) {
  const formation = team?.formation || meta?.formations?.formations?.[0] || "4-3-3 flat";
  const formations = meta?.formations?.formations || [formation];
  const roster = team?.roster || [];
  const lineupMap = {};
  (team?.lineup || []).forEach((r) => {
    lineupMap[r.slot] = r.player || "";
  });
  const formationOpts = formations
    .map((f) => `<option value="${esc(f)}" ${f === formation ? "selected" : ""}>${esc(f)}</option>`)
    .join("");
  return `
    <div class="compare-side">
      <h4 style="font-size:0.85rem;margin:0 0 0.5rem">${esc(label)}</h4>
      <div class="form-row">
        <label for="compareFormation_${prefix}">Formation</label>
        <select id="compareFormation_${prefix}" data-compare-formation="${prefix}">${formationOpts}</select>
      </div>
      <div class="slot-grid" id="compareSlotGrid_${prefix}" style="margin-top:0.6rem">${renderCompareSlotGrid(
    prefix,
    formation,
    lineupMap,
    roster
  )}</div>
    </div>`;
}

function renderCompareLineupsPanel() {
  if (!lineupData) return "";
  const team = { formation: lineupData.lineup?.formation, lineup: lineupData.lineup?.lineup, roster: lineupData.roster };
  return `
    <div class="card compare-lineups-card" style="margin-top:1rem">
      <h3 style="font-size:0.95rem;margin:0 0 0.35rem">Compare two lineups</h3>
      <p class="muted" style="margin:0 0 0.85rem">Set up two full XIs of your own squad and see which rates stronger, and where. Both start from your current lineup — edit either side. Not saved.</p>
      <div class="compare-lineups-grid">
        ${renderCompareLineupSide("a", "Lineup A", team)}
        ${renderCompareLineupSide("b", "Lineup B", team)}
      </div>
      <button type="button" id="compareLineupsBtn" class="btn-primary" style="margin-top:1rem">Compare</button>
      <div id="compareLineupsResult" style="margin-top:0.85rem"></div>
    </div>`;
}

function wireCompareLineupsPanel() {
  document.querySelectorAll("[data-compare-formation]").forEach((sel) => {
    sel.addEventListener("change", () => {
      const prefix = sel.dataset.compareFormation;
      const formation = sel.value;
      const roster = lineupData?.roster || [];
      const grid = document.getElementById(`compareSlotGrid_${prefix}`);
      if (grid) grid.innerHTML = renderCompareSlotGrid(prefix, formation, {}, roster);
    });
  });
  document.getElementById("compareLineupsBtn")?.addEventListener("click", runCompareLineups);
}

function collectCompareLineup(prefix) {
  const formation = document.getElementById(`compareFormation_${prefix}`)?.value || "4-3-3 flat";
  const slots = meta?.formations?.slots?.[formation] || [];
  const lineup = slots.map((slot) => {
    const el = document.querySelector(`select[data-cslot="${prefix}:${slot}"]`);
    return { slot, player: (el?.value || "").trim(), captain: false, vice_captain: false };
  });
  return { formation, lineup };
}

function compareLineupsRow(label, block, higherBetter) {
  return whatifRow(label, block, higherBetter);
}

function renderCompareLineupsResult(compare) {
  const unitRows = _WHATIF_UNIT_LABELS.map(([k, l, hb]) => compareLineupsRow(l, compare.units[k], hb)).join("");
  const compRows = _WHATIF_COMPOSITE_LABELS.map(([k, l, hb]) => compareLineupsRow(l, compare.team_composites[k], hb)).join(
    ""
  );
  return `
    <div class="whatif-summary">
      <p><strong>${esc(compare.verdict)}</strong></p>
      <p class="muted" style="margin:0.25rem 0 0">A: ${esc(compare.formation_a)} · B: ${esc(compare.formation_b)} — deltas shown are B minus A.</p>
      <h4 style="font-size:0.8rem;margin:0.75rem 0 0.25rem">Unit ratings</h4>
      <div class="whatif-grid">${unitRows}</div>
      <h4 style="font-size:0.8rem;margin:0.75rem 0 0.25rem">Team profile</h4>
      <div class="whatif-grid">${compRows}</div>
    </div>`;
}

async function runCompareLineups() {
  const resultEl = document.getElementById("compareLineupsResult");
  if (!resultEl) return;
  const lineupA = collectCompareLineup("a");
  const lineupB = collectCompareLineup("b");
  const errA = validateLineupSlots(lineupA.lineup);
  const errB = validateLineupSlots(lineupB.lineup);
  if (errA || errB) {
    resultEl.innerHTML = `<p class="muted">${errA ? `Lineup A: ${esc(errA)}` : ""}${errA && errB ? "<br>" : ""}${errB ? `Lineup B: ${esc(errB)}` : ""}</p>`;
    return;
  }
  resultEl.innerHTML = '<p class="muted">Comparing…</p>';
  const q = currentTeam ? `?team=${encodeURIComponent(currentTeam)}` : "";
  try {
    const data = await api(`/api/my-squad/compare-lineups${q}`, {
      method: "POST",
      json: { lineup_a: lineupA, lineup_b: lineupB },
    });
    resultEl.innerHTML = renderCompareLineupsResult(data.compare);
  } catch (e) {
    resultEl.innerHTML = `<p class="muted">Compare failed: ${esc(e.message)}</p>`;
  }
}

function wireWhatIfPanel() {
  const btn = document.getElementById("whatifBtn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const slot = document.getElementById("whatifSlot")?.value;
    const newPlayer = document.getElementById("whatifPlayer")?.value;
    const resultEl = document.getElementById("whatifResult");
    if (!slot || !newPlayer || !resultEl) return;
    resultEl.innerHTML = '<p class="muted">Comparing…</p>';
    const q = currentTeam ? `?team=${encodeURIComponent(currentTeam)}` : "";
    try {
      const data = await api(`/api/my-squad/whatif${q}`, {
        method: "POST",
        json: { slot, new_player: newPlayer, lineup: collectLineupPayload() },
      });
      resultEl.innerHTML = renderWhatIfResult(data.whatif);
    } catch (e) {
      resultEl.innerHTML = `<p class="muted">Compare failed: ${esc(e.message)}</p>`;
    }
  });
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

async function unfinalizeSquad() {
  const team = currentTeam || lineupData?.team_name;
  if (!team) return;
  if (!confirm(`Unfinalize "${team}"? They will be able to edit their squad again.`)) return;
  const status = document.getElementById("lineupStatus");
  try {
    await api(`/api/admin/team-lineups/${encodeURIComponent(team)}/unfinalize`, {
      method: "POST",
    });
    if (status) status.textContent = "Squad unfinalized — editing unlocked.";
    lineupData = await loadLineup(currentTeam);
    document.getElementById("lineupSection").innerHTML = renderLineupBuilder(lineupData);
    wireLineupBuilder();
  } catch (e) {
    if (status) status.textContent = `Unfinalize failed: ${e.message}`;
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

function formResultChip(r) {
  const cls = r === "W" ? "form-w" : r === "L" ? "form-l" : "form-d";
  return `<span class="form-chip ${cls}">${esc(r)}</span>`;
}

// Season diagnostics card -- aggregated PPDA/conversion/passing numbers
// across every match the team has played this tournament, from
// tournament.py's team_analysis_summary. Reuses common.js's pctPill/
// pctTierClass (the same percentile-badge visual language the ratings-based
// percentiles use elsewhere in Squad Hub) rather than inventing a new one --
// pctPill expects a flat {key: percentile} object, not the unit-rating
// shape it's normally called with, so build that mapping here.
function seasonMetricTile(label, value, pillHtml, trendHtml) {
  return `<div class="metric"><div class="label">${esc(label)}</div><div class="value">${esc(value)}${pillHtml || ""}${trendHtml || ""}</div></div>`;
}

function seasonTrendBadge(trend) {
  if (!trend || trend === "steady") return "";
  const cls = trend === "improving" ? "pct-strength" : "pct-weakness";
  return ` <span class="pct-pill ${cls}">${esc(trend)}</span>`;
}

function renderSeasonDiagnosticsCard(season) {
  if (!season) {
    return `<div class="card" style="margin-top:1rem">
      <div class="report-eyebrow">Season diagnostics</div>
      <p class="muted" style="margin:0.35rem 0 0">No matches played yet this tournament — diagnostics will show up here once you have results.</p>
    </div>`;
  }
  const percentiles = { ppda: season.ppda_percentile, shot_conversion: season.shot_conversion_percentile };
  const leagueSize = season.league_size;
  return `
    <div class="card" style="margin-top:1rem">
      <div class="report-eyebrow">Season diagnostics</div>
      <p style="margin:0.35rem 0 0.85rem">${esc(season.summary || "")}</p>
      <div class="metric-grid">
        ${seasonMetricTile("PPDA", num(season.ppda, 1), pctPill("ppda", percentiles, leagueSize), seasonTrendBadge(season.ppda_trend))}
        ${seasonMetricTile("Shot conv %", pct(season.shot_conversion_pct), pctPill("shot_conversion", percentiles, leagueSize))}
        ${seasonMetricTile("Pass %", pct(season.pass_completion_pct))}
        ${seasonMetricTile("Possession %", season.possession_pct == null ? "—" : `${num(season.possession_pct, 0)}%`)}
        ${seasonMetricTile("xG for", num(season.xg_for))}
        ${seasonMetricTile("xG against", num(season.xg_against), "", seasonTrendBadge(season.xg_against_trend))}
      </div>
      <p class="muted" style="margin:0.6rem 0 0;font-size:0.78rem">Across ${season.matches} match${season.matches === 1 ? "" : "es"} played this tournament${leagueSize >= 4 ? ` · percentile vs. the other ${leagueSize - 1} teams` : ""}.</p>
    </div>`;
}

// Manager-dashboard project -- Manager Insight card: the "Keep / Consider
// / Watch" synthesis from tournament.py's _manager_insight, built last
// server-side since it reads every other section's own conclusions.
function renderManagerInsightCard(season) {
  const insight = season && season.manager_insight;
  if (!insight) return "";
  const conf = season.confidence;
  const confBadge = conf
    ? ` <span class="pct-pill" style="margin-left:0.4rem">${esc(conf.label)} · ${conf.matches} match${conf.matches === 1 ? "" : "es"}</span>`
    : "";
  const list = (title, items) =>
    items && items.length
      ? `<div style="margin-top:0.6rem"><div class="muted" style="font-size:0.75rem;text-transform:uppercase;letter-spacing:0.03em">${esc(title)}</div>
         <ul style="margin:0.3rem 0 0;padding-left:1.1rem">${items.map((i) => `<li style="margin:0.15rem 0">${esc(i)}</li>`).join("")}</ul></div>`
      : "";
  return `
    <div class="card">
      <div class="report-eyebrow">🧠 Manager insight${confBadge}</div>
      <p style="margin:0.5rem 0 0;font-weight:600">${esc(insight.headline || "")}</p>
      ${list("Keep", insight.keep)}
      ${list("Consider", insight.consider)}
      ${list("Watch", insight.watch)}
    </div>`;
}

// Tactical Identity card -- possession/press/pass/directness with league
// percentile pills, reusing common.js's pctPill exactly as the existing
// Season diagnostics card already does.
function renderTacticalIdentityCard(season) {
  const identity = season && season.tactical_identity;
  if (!identity) return "";
  const percentiles = { ppda: identity.ppda_percentile, shot_conversion: identity.shot_conversion_percentile };
  const leagueSize = season.league_size;
  return `
    <div class="card" style="margin-top:1rem">
      <div class="report-eyebrow">⚽ How we play</div>
      <p style="margin:0.35rem 0 0.85rem;font-weight:600">${(identity.labels || []).map(esc).join(" · ")}</p>
      <div class="metric-grid">
        ${seasonMetricTile("Possession", identity.possession_pct == null ? "—" : `${num(identity.possession_pct, 0)}%`)}
        ${seasonMetricTile("PPDA", num(identity.ppda, 1), pctPill("ppda", percentiles, leagueSize))}
        ${seasonMetricTile("Pass %", pct(identity.pass_completion_pct))}
        ${seasonMetricTile("Directness", identity.directness_pct == null ? "—" : `${num(identity.directness_pct, 0)}%`)}
        ${seasonMetricTile("Shot conv %", pct(identity.shot_conversion_pct), pctPill("shot_conversion", percentiles, leagueSize))}
      </div>
    </div>`;
}

function zoneBar(zonePct) {
  if (!zonePct) return `<p class="muted" style="margin:0.5rem 0 0;font-size:0.82rem">No zone data yet for matches played before this feature shipped.</p>`;
  const row = (label, v) => `
    <div style="display:flex;align-items:center;gap:0.5rem;margin:0.25rem 0">
      <div style="width:4.5rem;font-size:0.78rem" class="muted">${esc(label)}</div>
      <div style="flex:1;background:var(--bg-2,#1a1a22);border-radius:4px;overflow:hidden;height:0.6rem">
        <div style="width:${v}%;height:100%;background:var(--accent,#7c8cff)"></div>
      </div>
      <div style="width:2.5rem;text-align:right;font-size:0.78rem">${v}%</div>
    </div>`;
  return `<div style="margin-top:0.6rem">${row("Left", zonePct.left || 0)}${row("Central", zonePct.central || 0)}${row("Right", zonePct.right || 0)}</div>`;
}

function renderAttackingAnalysisCard(season) {
  const att = season && season.attacking_analysis;
  if (!att) return `<div class="card" style="margin-top:1rem"><div class="report-eyebrow">🔥 Attacking analysis</div><p class="muted" style="margin:0.35rem 0 0">No shots recorded yet this tournament.</p></div>`;
  return `
    <div class="card" style="margin-top:1rem">
      <div class="report-eyebrow">🔥 Attacking analysis</div>
      ${att.diagnosis ? `<p style="margin:0.35rem 0 0.6rem">${att.diagnosis_positive ? "🟢" : "🟡"} ${esc(att.diagnosis)}</p>` : ""}
      <div class="metric-grid">
        ${seasonMetricTile("xG", num(att.xg_for))}
        ${seasonMetricTile("Shots", String(att.shots ?? "—"))}
        ${seasonMetricTile("On target", String(att.shots_on_target ?? "—"))}
        ${seasonMetricTile("Big chances", String(att.big_chances ?? "—"))}
        ${seasonMetricTile("Goals", String(att.goals ?? "—"))}
        ${seasonMetricTile("xG/shot", num(att.xg_per_shot))}
      </div>
      <div class="muted" style="font-size:0.75rem;text-transform:uppercase;letter-spacing:0.03em;margin-top:0.7rem">Where chances came from</div>
      ${zoneBar(att.zone_breakdown_pct)}
    </div>`;
}

function renderDefensiveAnalysisCard(season) {
  const def = season && season.defensive_analysis;
  if (!def) return "";
  return `
    <div class="card" style="margin-top:1rem">
      <div class="report-eyebrow">🛡 Defensive analysis</div>
      ${def.diagnosis ? `<p style="margin:0.35rem 0 0.6rem">${def.diagnosis_positive ? "🟢" : "🟡"} ${esc(def.diagnosis)}</p>` : ""}
      <div class="metric-grid">
        ${seasonMetricTile("xG against", num(def.xg_against))}
        ${seasonMetricTile("Shots conceded", String(def.shots_against ?? "—"))}
        ${seasonMetricTile("Big chances conceded", String(def.big_chances_against ?? "—"))}
        ${seasonMetricTile("Goals conceded", String(def.goals_against ?? "—"))}
        ${seasonMetricTile("PPDA", num(def.ppda, 1))}
      </div>
    </div>`;
}

function renderPlayerImpactCard(season) {
  const rows = (season && season.player_impact) || [];
  if (!rows.length) return "";
  return `
    <div class="card" style="margin-top:1rem">
      <div class="report-eyebrow">👥 Player impact</div>
      <div class="report-table-wrap" style="margin-top:0.5rem"><table>
        <thead><tr><th>Player</th><th>xG+A</th><th>Goals</th><th>Assists</th><th>Key passes</th><th>Defensive actions</th></tr></thead>
        <tbody>${rows
          .map(
            (r) =>
              `<tr><td>${esc(r.player || "—")}</td><td>${num(r.xg_plus_assists)}</td><td>${r.goals ?? 0}</td><td>${r.assists ?? 0}</td><td>${r.key_passes ?? 0}</td><td>${r.defensive_actions ?? 0}</td></tr>`
          )
          .join("")}</tbody>
      </table></div>
      <p class="muted" style="margin:0.5rem 0 0;font-size:0.75rem">"Defensive actions" = tackles + interceptions, a proxy for defensive activity — this engine doesn't track per-player pressing events.</p>
    </div>`;
}

function renderNextMatchGamePlanCard(analysis) {
  const next = analysis.next_match;
  const plan = analysis.next_match_game_plan;
  const form = analysis.recent_form || [];
  const formStrip = form.length ? `<div class="form-strip" style="margin:0.5rem 0 0.6rem">${form.map((f) => formResultChip(f.result)).join("")}</div>` : "";
  if (!next) {
    return `<div class="card" style="margin-top:1rem"><div class="report-eyebrow">🎯 Next match</div>${formStrip}<p class="muted" style="margin:0.35rem 0 0">No fixture scheduled yet.</p></div>`;
  }
  const advantages = (plan && plan.advantages) || [];
  const advHtml = advantages.length
    ? `<div style="margin-top:0.6rem">
        <div class="muted" style="font-size:0.75rem;text-transform:uppercase;letter-spacing:0.03em">Where we can hurt them</div>
        <ul style="margin:0.3rem 0 0;padding-left:1.1rem">${advantages
          .map((a) => `<li style="margin:0.15rem 0">🟢 <strong>${esc(a.my_player || "")}</strong> (${esc(a.my_slot || "")}) vs ${esc(a.opp_player || "")} (${esc(a.opp_slot || "")}) — edge +${num(a.edge, 2)}</li>`)
          .join("")}</ul>
      </div>`
    : plan
      ? `<p class="muted" style="margin:0.5rem 0 0;font-size:0.82rem">No standout individual matchup edges found yet for this opponent.</p>`
      : "";
  return `
    <div class="card" style="margin-top:1rem">
      <div class="report-eyebrow">🎯 Next match: ${esc((next.opponent || "TBD").toUpperCase())}</div>
      ${formStrip}
      <p style="margin:0.35rem 0 0"><strong>${esc(next.opponent || "TBD")}</strong> <span class="muted">${next.home ? "(home)" : "(away)"} · ${esc(next.round_label || "")}</span></p>
      ${advHtml}
    </div>`;
}

// Season Trends -- the one new visual primitive in this project. No chart
// library exists anywhere in this codebase, so this is a small,
// dependency-free inline SVG polyline, not a library integration.
function renderTrendChart(label, series, color) {
  if (!series || series.length < 2) return "";
  const w = 520, h = 90, pad = 8;
  const max = Math.max(...series, 0.01);
  const min = Math.min(...series, 0);
  const range = max - min || 1;
  const pts = series.map((v, i) => {
    const x = pad + (i / (series.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return `
    <div style="margin-top:0.6rem">
      <div class="muted" style="font-size:0.75rem;text-transform:uppercase;letter-spacing:0.03em">${esc(label)} (${num(series[0])} → ${num(series[series.length - 1])})</div>
      <svg viewBox="0 0 ${w} ${h}" style="width:100%;height:${h}px;margin-top:0.25rem" preserveAspectRatio="none">
        <polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="2" />
      </svg>
    </div>`;
}

function renderSeasonTrendsCard(season) {
  const ts = season && season.trend_series;
  if (!ts || (ts.xg_for || []).length < 2) {
    return `<div class="card" style="margin-top:1rem"><div class="report-eyebrow">📊 Season trends</div><p class="muted" style="margin:0.35rem 0 0">Needs a few more matches before a trend is meaningful.</p></div>`;
  }
  return `
    <div class="card" style="margin-top:1rem">
      <div class="report-eyebrow">📊 Season trends</div>
      ${renderTrendChart("xG for", ts.xg_for, "#5ad17a")}
      ${renderTrendChart("xG against", ts.xg_against, "#e0607a")}
      ${renderTrendChart("PPDA (lower = more pressing)", ts.ppda, "#7c8cff")}
    </div>`;
}

function renderAnalysisTab(analysis) {
  if (!analysis || !analysis.tournament_id) {
    return `<div class="card"><h2>Analysis</h2><p class="muted">No active tournament for this team right now.</p></div>`;
  }
  const table = analysis.table_row;
  const tableCard = table
    ? `
    <div class="card">
      <div class="report-eyebrow">Tournament form</div>
      <h2 style="margin:0 0 0.35rem">${esc(analysis.tournament_name || "")}${analysis.group ? ` · Group ${esc(String(analysis.group).toUpperCase())}` : ""}</h2>
      <div class="metric-grid" style="margin-top:0.75rem">
        ${metric("Played", String(table.played ?? 0))}
        ${metric("W-D-L", `${table.w ?? 0}-${table.d ?? 0}-${table.l ?? 0}`)}
        ${metric("GF-GA", `${table.gf ?? 0}-${table.ga ?? 0}`)}
        ${metric("GD", String(table.gd ?? 0))}
        ${metric("Points", String(table.pts ?? 0))}
      </div>
    </div>`
    : "";

  const season = analysis.season_stats;
  const insightCard = renderManagerInsightCard(season);
  const identityCard = renderTacticalIdentityCard(season);
  const diagnosticsCard = renderSeasonDiagnosticsCard(season);
  const attackingCard = renderAttackingAnalysisCard(season);
  const defensiveCard = renderDefensiveAnalysisCard(season);
  const playerImpactCard = renderPlayerImpactCard(season);
  const nextCard = renderNextMatchGamePlanCard(analysis);
  const trendsCard = renderSeasonTrendsCard(season);

  return `${insightCard}${identityCard}${tableCard}${diagnosticsCard}${attackingCard}${defensiveCard}${playerImpactCard}${nextCard}${trendsCard}`;
}

// Statistics tab -- full per-player stats for this team's own roster, from
// tournament.py's team_player_stats (reuses the exact same
// aggregate_player_tallies pipeline the tournament-wide Stats tab uses,
// filtered to this team). Grouped into a few readable tables instead of one
// very wide one; each column pulls straight off the player_tallies row
// shape (raw counts + the derived ratio fields tournament.py already
// computed, e.g. shot_conversion_pct, pass_completion_pct).
const STATS_TABLE_GROUPS = [
  {
    title: "Attacking",
    columns: [
      ["goals", "G"],
      ["assists", "A"],
      ["shots", "Shots"],
      ["shot_conversion_pct", "Conv %", "pct"],
      ["xg", "xG", "num1"],
      ["xg_diff", "G-xG", "num1"],
      ["big_chances", "BC"],
      ["big_chance_goals", "BC Goals"],
      ["big_chance_conversion_pct", "BC Conv %", "pct"],
      ["penalty_goals", "Pens"],
      ["dribbles", "Dribbles"],
      ["distance_carried", "Dist (m)"],
    ],
  },
  {
    title: "Creation & Passing",
    columns: [
      ["key_passes", "KP"],
      ["big_chances_created", "BC Created"],
      ["progressive_passes", "Prog Passes"],
      ["passes_attempted", "Pass Att"],
      ["passes_completed", "Pass Comp"],
      ["pass_completion_pct", "Pass %", "pct"],
      ["crosses_attempted", "Cross Att"],
      ["cross_accuracy_pct", "Cross %", "pct"],
      ["through_attempted", "TB Att"],
      ["through_ball_completion_pct", "TB %", "pct"],
    ],
  },
  {
    title: "Defending & Goalkeeping",
    columns: [
      ["tackles", "Tackles"],
      ["interceptions", "Int"],
      ["clean_sheets", "CS"],
      ["saves", "Saves"],
      ["goals_conceded", "Conceded"],
      ["save_pct", "Save %", "pct"],
      ["big_chances_missed", "BC Missed"],
      ["fouls", "Fouls"],
      ["cards", "Cards"],
      ["red_cards", "Red"],
    ],
  },
];

function statsCell(row, field, kind) {
  const v = row[field];
  if (kind === "pct") return pct(v);
  if (kind === "num1") return num(v, 1);
  return v == null ? "—" : String(v);
}

function renderStatsTable(players, group) {
  const rows = players
    .map(
      (row) =>
        `<tr><td style="white-space:nowrap">${esc(row.player)}</td>${group.columns
          .map(([field, , kind]) => `<td class="num">${statsCell(row, field, kind)}</td>`)
          .join("")}</tr>`
    )
    .join("");
  const headCells = group.columns.map(([, label]) => `<th style="white-space:nowrap">${esc(label)}</th>`).join("");
  // Deliberately bare .report-table-wrap, not .rank-table -- that modifier's
  // fixed-width first-column treatment (9%) was tuned for a 3-4 column
  // leaderboard and squeezes/wraps player names badly on a table this wide
  // (up to 12 columns). overflow-x:auto scrolls the wide table horizontally
  // instead, same principle as every other wide-content container.
  return `<div class="card" style="margin-bottom:1rem">
    <h3 style="font-size:0.95rem;margin:0 0 0.5rem">${esc(group.title)}</h3>
    <div class="report-table-wrap" style="overflow-x:auto"><table><thead><tr><th style="white-space:nowrap">Player</th>${headCells}</tr></thead><tbody>${rows}</tbody></table></div>
  </div>`;
}

function renderStatsTab(data) {
  const players = data?.players || [];
  if (!players.length) {
    return `<div class="card"><p class="muted" style="margin:0">No stats yet — play some matches in your active tournament and player stats will show up here.</p></div>`;
  }
  const header = `<p class="muted" style="margin:0 0 1rem">${esc(data.tournament_name || "Active tournament")} — every player who has featured for your team, across all played matches.</p>`;
  return header + STATS_TABLE_GROUPS.map((group) => renderStatsTable(players, group)).join("");
}

async function loadStatsTab() {
  const panel = document.getElementById("tabPanelStats");
  if (!panel) return;
  panel.innerHTML = '<div class="empty">Loading player statistics…</div>';
  try {
    const q = currentTeam ? `?team=${encodeURIComponent(currentTeam)}` : "";
    const data = await api(`/api/my-team/stats${q}`);
    panel.innerHTML = renderStatsTab(data);
  } catch (e) {
    panel.innerHTML = `<div class="empty"><span class="badge error">Error</span><p>${esc(e.message)}</p></div>`;
  }
}

async function loadAnalysisTab() {
  const panel = document.getElementById("tabPanelAnalysis");
  if (!panel) return;
  panel.innerHTML = '<div class="empty">Loading analysis…</div>';
  try {
    const q = currentTeam ? `?team=${encodeURIComponent(currentTeam)}` : "";
    const data = await api(`/api/my-team/analysis${q}`);
    panel.innerHTML = renderAnalysisTab(data.analysis);
  } catch (e) {
    panel.innerHTML = `<div class="empty"><span class="badge error">Error</span><p>${esc(e.message)}</p></div>`;
  }
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

function wireAdminPicker(allTeams, teamName) {
  const select = document.getElementById("adminTeamSelect");
  if (!select) return;
  const names = [...new Set((allTeams || []).map((t) => t.name))].sort((a, b) =>
    a.localeCompare(b)
  );
  if (teamName && !names.includes(teamName)) names.unshift(teamName);
  select.innerHTML = names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
  if (teamName) select.value = teamName;
  select.addEventListener("change", () => {
    // Admin switched teams -- Scout/Analysis tabs cached data for the old
    // team; force them to reload fresh on next visit instead of showing
    // stale content for whoever's now selected.
    scoutTabLoaded = false;
    analysisTabLoaded = false;
    statsTabLoaded = false;
    const scoutPanel = document.getElementById("tabPanelScout");
    if (scoutPanel) scoutPanel.innerHTML = "";
    const analysisPanel = document.getElementById("tabPanelAnalysis");
    if (analysisPanel) analysisPanel.innerHTML = "";
    const statsPanel = document.getElementById("tabPanelStats");
    if (statsPanel) statsPanel.innerHTML = "";
    reloadTeam(select.value);
  });
}

function updateBenchList() {
  const listEl = document.getElementById("benchList");
  const countEl = document.getElementById("benchCount");
  if (!listEl || !lineupData) return;
  const roster = lineupData.roster || [];
  const assigned = new Set(
    [...document.querySelectorAll("select[data-slot]")].map((el) => el.value.trim()).filter(Boolean)
  );
  const subs = roster.filter((p) => !assigned.has(p));
  listEl.innerHTML = subs.length
    ? subs.map((p) => `<span class="bench-chip">${esc(p)}</span>`).join("")
    : '<span class="muted">No subs — full roster is in the starting XI.</span>';
  if (countEl) countEl.textContent = String(subs.length);
}

let _benchDelegationWired = false;

function wireLineupBuilder() {
  if (!lineupData?.locked) {
    document.getElementById("lineupFormation")?.addEventListener("change", onFormationChange);
    document.getElementById("saveLineupBtn")?.addEventListener("click", saveLineup);
  }
  document.getElementById("testSquadBtn")?.addEventListener("click", testSquad);
  document.getElementById("finalizeSquadBtn")?.addEventListener("click", finalizeSquad);
  document.getElementById("unfinalizeSquadBtn")?.addEventListener("click", unfinalizeSquad);
  if (!_benchDelegationWired) {
    document.addEventListener("change", (e) => {
      if (e.target.matches && e.target.matches("select[data-slot]")) updateBenchList();
    });
    _benchDelegationWired = true;
  }
  updateBenchList();
}

async function reloadTeam(teamName) {
  currentTeam = teamName;
  lineupData = await loadLineup(teamName);
  document.getElementById("lineupSection").innerHTML = renderLineupBuilder(lineupData);
  wireLineupBuilder();
  const compareSection = document.getElementById("compareLineupsSection");
  if (compareSection) {
    compareSection.innerHTML = renderCompareLineupsPanel();
    wireCompareLineupsPanel();
  }
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
      ${renderSquadTabBar()}
      <div id="tabPanelLineup">
        <section id="lineupSection"></section>
        <section id="mySquadSection"><div class="empty">Use Test squad to preview your lineup report, then finalize before matchday.</div></section>
        <section id="compareLineupsSection"></section>
      </div>
      <div id="tabPanelScout" hidden></div>
      <div id="tabPanelAnalysis" hidden></div>
      <div id="tabPanelStats" hidden></div>
    `;
    wireSquadTabBar();

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
