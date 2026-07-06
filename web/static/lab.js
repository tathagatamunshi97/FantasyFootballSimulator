if (!requireAuth()) throw new Error("auth");
if (isTeamUser()) {
  window.location.replace("/squad");
  throw new Error("redirect");
}

let meta = null;
/** Squad player lists per side after loading from Google Sheet or random gen (enables slot dropdowns). */
let teamSquads = { a: null, b: null };
/** Per-side source mode: "sheet" | "random". */
let teamSource = { a: "sheet", b: "sheet" };
/** Last sheet-loaded team payloads (for sheet_meta on submit). */
let loadedSheetTeams = { a: null, b: null };

function lineupPlayersFromSide(side) {
  return [...document.querySelectorAll(`[data-side="${side}"][data-slot]`)].map((el) => el.value.trim()).filter(Boolean);
}

function extractRoster(team) {
  const meta = team.sheet_meta || {};
  if (meta.full_roster?.length) {
    return [...meta.full_roster].sort((a, b) => a.localeCompare(b));
  }
  const roster = meta.roster_players || [];
  const bench = meta.bench_players || team.bench || [];
  const lineup = (team.lineup || []).map((r) => r.player).filter(Boolean);
  return [...new Set([...roster, ...bench, ...lineup])].sort((a, b) => a.localeCompare(b));
}

function squadPlayersForSide(side) {
  if (teamSquads[side]?.length) return teamSquads[side];
  return lineupPlayersFromSide(side);
}

function catalogPosition(name) {
  const row = (meta.players || []).find((p) => p.name === name);
  return (row?.position || row?.primary || "MID").toUpperCase();
}

function slotPositionGroup(slot) {
  if (slot === "GK") return "GK";
  if (/^(CB|RB|LB|RWB|LWB)/.test(slot)) return "DEF";
  if (/^(DM|CM|AM|RM|LM)/.test(slot)) return "MID";
  return "FWD";
}

function positionCompatible(playerPos, slotGroup) {
  const p = playerPos.toUpperCase();
  if (p === slotGroup) return true;
  if (slotGroup === "MID" && p === "DEF") return true;
  if (slotGroup === "FWD" && (p === "MID" || p === "DEF")) return true;
  if (slotGroup === "DEF" && p === "MID") return true;
  return false;
}

/** Fallback when /api/lineup/assign fails — map players to slots by position similarity. */
function fallbackLineupByPosition(formation, players) {
  const slots = meta.formations.slots[formation] || [];
  const remaining = [...players];
  const lineup = slots.map((slot) => ({
    slot,
    player: "",
    captain: false,
    vice_captain: false,
  }));

  const gkIdx = slots.indexOf("GK");
  if (gkIdx >= 0) {
    const gk = remaining.find((p) => catalogPosition(p) === "GK");
    if (gk) {
      lineup[gkIdx].player = gk;
      remaining.splice(remaining.indexOf(gk), 1);
    }
  }

  for (let i = 0; i < slots.length; i++) {
    if (lineup[i].player) continue;
    const group = slotPositionGroup(slots[i]);
    const pick =
      remaining.find((p) => catalogPosition(p) === group) ||
      remaining.find((p) => positionCompatible(catalogPosition(p), group)) ||
      remaining[0];
    if (pick) {
      lineup[i].player = pick;
      remaining.splice(remaining.indexOf(pick), 1);
    }
  }
  return lineup;
}

async function reassignLineup(formation, players) {
  if (!players.length) {
    const slots = meta.formations.slots[formation] || [];
    return slots.map((slot) => ({ slot, player: "", captain: false, vice_captain: false }));
  }
  try {
    const data = await api("/api/lineup/assign", {
      method: "POST",
      json: { formation, players },
    });
    return data.lineup;
  } catch {
    return fallbackLineupByPosition(formation, players);
  }
}

function slotPlayerControl(side, slot, val, squad) {
  if (squad && squad.length) {
    const opts = ['<option value="">— pick player —</option>'];
    squad.forEach((p) => {
      opts.push(`<option value="${esc(p)}" ${p === val ? "selected" : ""}>${esc(p)}</option>`);
    });
    return `<select data-side="${side}" data-slot="${esc(slot)}">${opts.join("")}</select>`;
  }
  return `<input type="text" list="playerList" data-side="${side}" data-slot="${esc(slot)}" value="${esc(val)}" placeholder="Player name" ${val ? "required" : ""} />`;
}

function playerSelectOptions(players, selected) {
  const opts = ['<option value="">— none —</option>'];
  players.forEach((p) => {
    opts.push(`<option value="${esc(p)}" ${p === selected ? "selected" : ""}>${esc(p)}</option>`);
  });
  return opts.join("");
}

function seasonSelectOptions(selected) {
  return (meta.seasons || [])
    .map(
      (s) =>
        `<option value="${esc(s.suffix)}" ${s.suffix === selected ? "selected" : ""}>${esc(s.label)}</option>`
    )
    .join("");
}

function refreshSeasonPickers(side) {
  const players = squadPlayersForSide(side);
  const primeEl = document.getElementById(`prime_${side}`);
  const peakEl = document.getElementById(`peak_player_${side}`);
  if (!primeEl || !peakEl) return;
  const curPrime = primeEl.value;
  const curPeak = peakEl.value;
  primeEl.innerHTML = playerSelectOptions(players, players.includes(curPrime) ? curPrime : "");
  peakEl.innerHTML = playerSelectOptions(players, players.includes(curPeak) ? curPeak : "");
}

function bindLineupListeners(side) {
  document.querySelectorAll(`[data-side="${side}"][data-slot]`).forEach((el) => {
    el.addEventListener("change", () => refreshSeasonPickers(side));
    if (el.tagName === "INPUT") {
      el.addEventListener("input", () => refreshSeasonPickers(side));
    }
  });
}

function renderTeamPanel(side, teamData) {
  const label = side === "a" ? "Team A" : "Team B";
  const formations = meta.formations.formations;
  const slotsByForm = meta.formations.slots;
  const formation = teamData.formation || "4-3-3";
  const slots = slotsByForm[formation] || [];
  const lineupMap = {};
  (teamData.lineup || []).forEach((r) => {
    lineupMap[r.slot] = r.player;
  });
  const squad = teamSquads[side];
  const seasonPickPlayers = squad?.length ? squad : Object.values(lineupMap).filter(Boolean);

  const prime = teamData.prime_player || "";
  const peak = teamData.peak_season || {};
  const peakPlayer = peak.player || "";
  const peakSeason = peak.season || "23/24";

  const formationOpts = formations
    .map((f) => `<option value="${esc(f)}" ${f === formation ? "selected" : ""}>${esc(f)}</option>`)
    .join("");

  const slotRows = slots
    .map((slot) => {
      const val = lineupMap[slot] || "";
      return `<div class="form-row slot-row">
        <label>${esc(slot)}</label>
        ${slotPlayerControl(side, slot, val, squad)}
      </div>`;
    })
    .join("");

  return `
    <h2>${label}</h2>
    <div class="form-row">
      <label>Team name</label>
      <input type="text" id="name_${side}" value="${esc(teamData.name || label)}" required />
    </div>
    <div class="form-row">
      <label>Formation</label>
      <select id="formation_${side}">${formationOpts}</select>
    </div>
    <div class="slot-grid">${slotRows}</div>
    <div class="season-picks" style="margin-top:1rem;padding-top:0.75rem;border-top:1px solid var(--border)">
      <h3 style="font-size:0.9rem;margin:0 0 0.5rem">Season overrides</h3>
      <p class="muted" style="margin:0 0 0.75rem">One prime + one pick-season per team. Stats replace current form entirely (2013-14+).</p>
      <div class="form-row">
        <label>Prime player (auto best season)</label>
        <select id="prime_${side}">${playerSelectOptions(seasonPickPlayers, prime)}</select>
      </div>
      <div class="form-row">
        <label>Pick-season player</label>
        <select id="peak_player_${side}">${playerSelectOptions(seasonPickPlayers, peakPlayer)}</select>
      </div>
      <div class="form-row">
        <label>Pick season</label>
        <select id="peak_season_${side}">${seasonSelectOptions(peakSeason)}</select>
      </div>
    </div>
  `;
}

function mountPanels(teamA, teamB) {
  document.getElementById("teamAPanel").innerHTML = renderTeamPanel("a", teamA);
  document.getElementById("teamBPanel").innerHTML = renderTeamPanel("b", teamB);

  ["a", "b"].forEach((side) => {
    bindLineupListeners(side);
    refreshSeasonPickers(side);
    document.getElementById(`formation_${side}`).addEventListener("change", async () => {
      const name = document.getElementById(`name_${side}`).value.trim();
      const prime = document.getElementById(`prime_${side}`)?.value || "";
      const peakPlayer = document.getElementById(`peak_player_${side}`)?.value || "";
      const peakSeason = document.getElementById(`peak_season_${side}`)?.value || "";
      const players = lineupPlayersFromSide(side);
      const newFormation = document.getElementById(`formation_${side}`).value;
      const lineup = await reassignLineup(newFormation, players);
      const team = {
        name,
        formation: newFormation,
        lineup,
        prime_player: prime,
        peak_season: { player: peakPlayer, season: peakSeason },
      };
      if (side === "a") mountPanels(team, collectTeam("b"));
      else mountPanels(collectTeam("a"), team);
    });
  });
}

function collectTeam(side) {
  const formation = document.getElementById(`formation_${side}`).value;
  const slots = meta.formations.slots[formation] || [];
  const lineup = slots.map((slot) => {
    const el = document.querySelector(`[data-side="${side}"][data-slot="${slot}"]`);
    return { slot, player: (el?.value || "").trim(), captain: false, vice_captain: false };
  });
  const team = {
    name: document.getElementById(`name_${side}`).value.trim(),
    formation,
    lineup,
    prime_player: document.getElementById(`prime_${side}`)?.value || "",
    peak_season: {
      player: document.getElementById(`peak_player_${side}`)?.value || "",
      season: document.getElementById(`peak_season_${side}`)?.value || "",
    },
  };
  const sheet = loadedSheetTeams[side];
  if (sheet?.sheet_meta) {
    team.sheet_meta = sheet.sheet_meta;
    if (sheet.bench) team.bench = sheet.bench;
  }
  return team;
}

function setSourceMode(side, mode) {
  teamSource[side] = mode;
  const root = document.querySelector(`.source-side[data-side="${side}"]`);
  if (!root) return;
  root.querySelectorAll(".source-tabs .tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.source === mode);
  });
  root.querySelector(".sheet-panel").hidden = mode !== "sheet";
  root.querySelector(".random-panel").hidden = mode !== "random";
}

async function generateRandomTeam(side) {
  const err = document.getElementById("formError");
  const status = document.getElementById("sheetStatus");
  const btn = document.getElementById(side === "a" ? "genRandomA" : "genRandomB");
  err.hidden = true;
  const formation = document.getElementById(`formation_${side}`)?.value || "4-3-3";
  const cur = collectTeam(side);
  btn.disabled = true;
  status.textContent = `Generating random Team ${side.toUpperCase()}…`;
  try {
    const data = await api("/api/lineup/random", {
      method: "POST",
      json: { formation, count: 11, seed: Date.now() + (side === "b" ? 1 : 0) },
    });
    teamSquads[side] = [...data.players].sort((a, b) => a.localeCompare(b));
    loadedSheetTeams[side] = null;
    const team = {
      name: cur.name || (side === "a" ? "Random Team A" : "Random Team B"),
      formation: data.formation,
      lineup: data.lineup,
      prime_player: cur.prime_player,
      peak_season: cur.peak_season,
    };
    if (side === "a") mountPanels(team, collectTeam("b"));
    else mountPanels(collectTeam("a"), team);
    await api("/api/players/ensure", { method: "POST", json: { names: data.players } });
    status.textContent = `Random squad loaded for Team ${side.toUpperCase()} (${data.players.length} players). Edit slots as needed.`;
  } catch (ex) {
    status.textContent = "";
    err.textContent = ex.message;
    err.hidden = false;
  } finally {
    btn.disabled = false;
  }
}

function isLabAdmin() {
  return !!getAdminToken();
}

function configureSheetAccessForUser() {
  const admin = isLabAdmin();
  const note = document.getElementById("sheetAdminNote");
  const sheetLoad = document.querySelector(".sheet-load");
  if (admin) {
    if (note) note.hidden = true;
    return;
  }
  if (note) note.hidden = false;
  teamSource = { a: "random", b: "random" };
  ["a", "b"].forEach((side) => {
    setSourceMode(side, "random");
    const root = document.querySelector(`.source-side[data-side="${side}"]`);
    if (!root) return;
    root.querySelectorAll('.source-tabs .tab-btn[data-source="sheet"]').forEach((btn) => {
      btn.disabled = true;
      btn.title = "Google Sheet teams require admin token";
    });
    const sheetPanel = root.querySelector(".sheet-panel");
    if (sheetPanel) sheetPanel.hidden = true;
  });
  const refreshBtn = document.getElementById("refreshSheetTeams");
  const loadBtn = document.getElementById("loadSheetTeams");
  if (refreshBtn) refreshBtn.hidden = true;
  if (loadBtn) loadBtn.hidden = true;
  if (sheetLoad) {
    const intro = sheetLoad.querySelector("p.muted");
    if (intro && !intro.id) intro.textContent = "Generate random squads from the player catalog (Google Sheet loading is admin-only).";
  }
}

async function loadSheetTeamList() {
  if (!isLabAdmin()) {
    document.getElementById("sheetStatus").textContent =
      "Google Sheet teams require admin access (/admin with SIM_ADMIN_TOKEN).";
    return [];
  }
  const status = document.getElementById("sheetStatus");
  status.textContent = "Loading teams from Google Sheet…";
  const data = await api("/api/sheets/teams");
  const teams = data.teams || [];
  const opts = ['<option value="">— select team —</option>'];
  teams.forEach((t) => {
    const label = t.ready ? t.name : `${t.name} (${t.player_count}/11)`;
    opts.push(`<option value="${esc(t.name)}">${esc(label)}</option>`);
  });
  document.getElementById("sheetTeamA").innerHTML = opts.join("");
  document.getElementById("sheetTeamB").innerHTML = opts.join("");
  const ready = teams.filter((t) => t.ready).length;
  status.textContent = `${teams.length} teams loaded (${ready} ready with 11 players).`;
  return teams;
}

async function init() {
  meta = await api("/api/meta");
  configureSheetAccessForUser();
  const dl = document.getElementById("playerList");
  dl.innerHTML = meta.players.map((p) => `<option value="${esc(p.name)}">`).join("");
  const def = meta.default_matchup;
  mountPanels(def.team_a, def.team_b);

  document.querySelectorAll(".source-side").forEach((root) => {
    const side = root.dataset.side;
    root.querySelectorAll(".source-tabs .tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => setSourceMode(side, btn.dataset.source));
    });
  });
  document.getElementById("genRandomA").addEventListener("click", () => generateRandomTeam("a"));
  document.getElementById("genRandomB").addEventListener("click", () => generateRandomTeam("b"));

  document.getElementById("refreshSheetTeams").addEventListener("click", () => {
    loadSheetTeamList().catch((e) => {
      const msg =
        e.message === "Not Found"
          ? "Sheets API not available — restart the web server (python run_web.py)."
          : e.message;
      document.getElementById("sheetStatus").textContent = msg;
    });
  });
  document.getElementById("loadSheetTeams").addEventListener("click", async () => {
    if (!isLabAdmin()) {
      document.getElementById("formError").textContent =
        "Loading Google Sheet teams requires admin access. Use Random squad or open /admin.";
      document.getElementById("formError").hidden = false;
      return;
    }
    const err = document.getElementById("formError");
    const status = document.getElementById("sheetStatus");
    const loadBtn = document.getElementById("loadSheetTeams");
    err.hidden = true;
    const nameA = teamSource.a === "sheet" ? document.getElementById("sheetTeamA").value : "";
    const nameB = teamSource.b === "sheet" ? document.getElementById("sheetTeamB").value : "";
    if (!nameA && !nameB) {
      status.textContent = "Select at least one sheet team to load (or use Random squad).";
      return;
    }
    loadBtn.disabled = true;
    status.textContent = "Loading teams from sheet…";
    try {
      const formationA = document.getElementById("formation_a")?.value || "4-3-3";
      const formationB = document.getElementById("formation_b")?.value || "4-3-3";
      const warnings = [];
      const [teamA, teamB] = await Promise.all([
        nameA
          ? api(
              `/api/sheets/team?name=${encodeURIComponent(nameA)}&formation=${encodeURIComponent(formationA)}`
            ).then((d) => d.team)
          : Promise.resolve(collectTeam("a")),
        nameB
          ? api(
              `/api/sheets/team?name=${encodeURIComponent(nameB)}&formation=${encodeURIComponent(formationB)}`
            ).then((d) => d.team)
          : Promise.resolve(collectTeam("b")),
      ]);
      if (nameA && teamA.sheet_meta && !teamA.sheet_meta.ready) {
        warnings.push(`Team A has ${teamA.sheet_meta.player_count}/11 players — fill empty slots before running.`);
      }
      if (nameB && teamB.sheet_meta && !teamB.sheet_meta.ready) {
        warnings.push(`Team B has ${teamB.sheet_meta.player_count}/11 players — fill empty slots before running.`);
      }
      teamSquads.a = nameA ? extractRoster(teamA) : teamSquads.a;
      teamSquads.b = nameB ? extractRoster(teamB) : teamSquads.b;
      loadedSheetTeams.a = nameA ? teamA : loadedSheetTeams.a;
      loadedSheetTeams.b = nameB ? teamB : loadedSheetTeams.b;
      mountPanels(teamA, teamB);
      status.textContent = warnings.length
        ? warnings.join(" ")
        : `Loaded ${teamA.name || "Team A"} vs ${teamB.name || "Team B"}. Fetching player stats…`;
      const allPlayers = [
        ...new Set([
          ...(teamSquads.a || []),
          ...(teamSquads.b || []),
          ...lineupPlayersFromSide("a"),
          ...lineupPlayersFromSide("b"),
        ]),
      ].filter(Boolean);
      if (allPlayers.length) {
        await api("/api/players/ensure", { method: "POST", json: { names: allPlayers } });
      }
      status.textContent = warnings.length
        ? warnings.join(" ")
        : `Loaded ${teamA.name} vs ${teamB.name}.`;
    } catch (ex) {
      status.textContent = "";
      err.textContent = ex.message;
      err.hidden = false;
    } finally {
      loadBtn.disabled = false;
    }
  });

  loadSheetTeamList().catch(() => {
    document.getElementById("sheetStatus").textContent =
      "Could not load sheet teams (check sheet is shared for viewing).";
  });
}

document.getElementById("labForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = document.getElementById("formError");
  const btn = document.getElementById("submitBtn");
  err.hidden = true;
  btn.disabled = true;
  try {
    const payload = {
      team_a: collectTeam("a"),
      team_b: collectTeam("b"),
      simulations: Number(document.getElementById("sims").value) || 10000,
    };
    const data = await api("/api/experiments", { method: "POST", json: payload });
    window.location.href = `/experiment/${data.experiment.id}`;
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
    btn.disabled = false;
  }
});

init().catch((e) => {
  document.getElementById("formError").textContent = e.message;
  document.getElementById("formError").hidden = false;
});
