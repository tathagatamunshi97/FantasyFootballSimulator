// Public homepage — no auth required to view, but the header/module cards
// personalize when a session exists.

function initNav() {
  const token = getToken();
  const admin = isAdminUser();
  document.getElementById("navAdminLink").hidden = !admin;
  document.getElementById("navLoginLink").hidden = Boolean(token);
  const logoutBtn = document.getElementById("navLogoutBtn");
  logoutBtn.hidden = !token;
  logoutBtn.addEventListener("click", async () => {
    try {
      await api("/api/logout", { method: "POST" });
    } catch (_) {}
    clearSession();
    window.location.reload();
  });
}

function initSquadCard() {
  const token = getToken();
  const el = document.getElementById("squadDetail");
  if (!token) return; // keep the generic marketing copy
  if (isAdminUser()) {
    el.innerHTML = `Signed in as <strong>admin</strong> — full squad tooling for every team.`;
  } else {
    el.innerHTML = `Welcome back, <strong>${esc(getUser() || "")}</strong>. Jump back into your lineup.`;
  }
}

function fixturesFromGroups(t) {
  const groups = t.groups || {};
  const all = [];
  Object.values(groups).forEach((g) => {
    (g.fixtures || []).forEach((fx) => all.push(fx));
  });
  return all;
}

function renderHeroEmpty(message) {
  document.getElementById("heroBody").innerHTML = `<div class="hero-empty">${message}</div>`;
}

function renderHero(summary, t) {
  const fixtures = fixturesFromGroups(t);
  const played = fixtures.filter((fx) => fx.played);
  const unplayed = fixtures.filter((fx) => !fx.played);
  const totalMatches = fixtures.length + ((t.knockout || {}).rounds || []).reduce(
    (n, r) => n + (r.ties || []).length,
    0
  );
  let matchdayLabel = "—";
  if (unplayed.length) {
    const nextRound = Math.min(...unplayed.map((fx) => fx.round || 1));
    matchdayLabel = `MD ${nextRound}`;
  } else if (fixtures.length) {
    matchdayLabel = "Group stage complete";
  }

  document.getElementById("heroBody").innerHTML = `
    <h2>${esc(summary.name || "Untitled tournament")}</h2>
    <div class="hero-meta">
      <div class="hero-meta-item"><div class="val">${summary.team_count ?? "—"}</div><div class="lab">Teams</div></div>
      <div class="hero-meta-item"><div class="val">${played.length} / ${totalMatches || "—"}</div><div class="lab">Matches played</div></div>
      <div class="hero-meta-item"><div class="val">${esc(matchdayLabel)}</div><div class="lab">Current round</div></div>
    </div>
    <a href="/tournament" class="btn-primary">View tournament →</a>
  `;

  // Recent results strip — best-effort recency (fixture list order), only
  // shown when there's actually something played.
  if (played.length) {
    const recent = played.slice(-6).reverse();
    document.getElementById("resultsSection").hidden = false;
    document.getElementById("resultsStrip").innerHTML = recent
      .map(
        (fx) => `
        <div class="result-chip">
          <span class="rc-round">R${esc(String(fx.round ?? ""))}</span>
          <span>${esc(fx.home)}</span>
          <span class="rc-score">${esc(fx.score || "")}</span>
          <span>${esc(fx.away)}</span>
        </div>`
      )
      .join("");
  }

  // Matchday module: next scheduled fixture, if any.
  if (unplayed.length) {
    const nextRound = Math.min(...unplayed.map((fx) => fx.round || 1));
    const next = unplayed.find((fx) => (fx.round || 1) === nextRound);
    if (next) {
      document.getElementById("matchdayDetail").innerHTML =
        `Next up — <strong>${esc(next.home)} vs ${esc(next.away)}</strong> · Matchday ${esc(String(nextRound))}`;
    }
  } else if (fixtures.length) {
    document.getElementById("matchdayDetail").textContent = "Group stage complete — knockout fixtures continue on Matchday.";
  }

  document.getElementById("tournamentDetail").innerHTML =
    `<strong>${esc(summary.name || "")}</strong> · ${played.length} of ${totalMatches || fixtures.length} matches played`;
}

async function loadActiveTournament() {
  try {
    const data = await api("/api/tournament");
    const tournaments = data.tournaments || [];
    if (!tournaments.length) {
      renderHeroEmpty(
        'No tournament running yet. <a href="/admin">Set one up from Admin</a> to get started.'
      );
      return;
    }
    const summary = tournaments[0];
    const full = await api(`/api/tournament/${summary.id}`);
    renderHero(summary, full.tournament || {});
  } catch (err) {
    renderHeroEmpty("Couldn't load tournament status right now.");
  }
}

initNav();
initSquadCard();
loadActiveTournament();
