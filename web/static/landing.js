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

// League + Cup tournaments (web/league_cup.py) share the same tournament
// list/storage as the group+knockout format above but have a completely
// different shape (t.league.fixtures / t.cup.rounds, no t.groups at all) --
// reusing renderHero() on one silently renders "0 fixtures" with nowhere to
// click through to the real /league-cup page. Bug: players creating a
// League+Cup competition via Admin had no way to find it from the homepage.
function renderHeroLeagueCup(summary, t) {
  const fixtures = (t.league && t.league.fixtures) || [];
  const played = fixtures.filter((fx) => fx.played);
  const unplayed = fixtures.filter((fx) => !fx.played);
  const cupTies = ((t.cup && t.cup.rounds) || []).reduce((n, r) => n + (r.ties || []).length, 0);
  const totalMatches = fixtures.length + cupTies;
  let matchdayLabel = "—";
  if (unplayed.length) {
    const nextGw = Math.min(...unplayed.map((fx) => fx.scheduled_gw ?? fx.original_gw ?? 1));
    matchdayLabel = `GW ${nextGw}`;
  } else if (fixtures.length) {
    matchdayLabel = "League complete";
  }

  const href = `/league-cup?id=${encodeURIComponent(summary.id)}`;
  document.getElementById("heroBody").innerHTML = `
    <h2>${esc(summary.name || "Untitled tournament")}</h2>
    <div class="hero-meta">
      <div class="hero-meta-item"><div class="val">${summary.team_count ?? "—"}</div><div class="lab">Teams</div></div>
      <div class="hero-meta-item"><div class="val">${played.length} / ${totalMatches || "—"}</div><div class="lab">Matches played</div></div>
      <div class="hero-meta-item"><div class="val">${esc(matchdayLabel)}</div><div class="lab">Current gameweek</div></div>
    </div>
    <a href="${href}" class="btn-primary">View League + Cup →</a>
  `;

  if (played.length) {
    const recent = played.slice(-6).reverse();
    document.getElementById("resultsSection").hidden = false;
    document.getElementById("resultsStrip").innerHTML = recent
      .map(
        (fx) => `
        <div class="result-chip">
          <span class="rc-round">GW${esc(String(fx.scheduled_gw ?? fx.original_gw ?? ""))}</span>
          <span>${esc(fx.home)}</span>
          <span class="rc-score">${esc(fx.score || "")}</span>
          <span>${esc(fx.away)}</span>
        </div>`
      )
      .join("");
  }

  if (unplayed.length) {
    const nextGw = Math.min(...unplayed.map((fx) => fx.scheduled_gw ?? fx.original_gw ?? 1));
    const next = unplayed.find((fx) => (fx.scheduled_gw ?? fx.original_gw ?? 1) === nextGw);
    if (next) {
      document.getElementById("matchdayDetail").innerHTML =
        `Next up — <strong>${esc(next.home)} vs ${esc(next.away)}</strong> · Gameweek ${esc(String(nextGw))}`;
    }
  } else if (fixtures.length) {
    document.getElementById("matchdayDetail").textContent = "League complete — cup fixtures continue on Matchday.";
  }

  // The Tournament module card is the old group+knockout viewer -- point it
  // at the real League + Cup page instead of a page that will show nothing.
  const tournamentCard = document.getElementById("tournamentDetail")?.closest("a");
  if (tournamentCard) tournamentCard.href = href;
  document.getElementById("tournamentDetail").innerHTML =
    `<strong>${esc(summary.name || "")}</strong> · ${played.length} of ${totalMatches || fixtures.length} matches played (League + Cup)`;
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
    if (summary.format === "league_cup") {
      const full = await api(`/api/league-cup/${summary.id}`);
      renderHeroLeagueCup(summary, full.tournament || {});
      return;
    }
    const full = await api(`/api/tournament/${summary.id}`);
    renderHero(summary, full.tournament || {});
  } catch (err) {
    renderHeroEmpty("Couldn't load tournament status right now.");
  }
}

initNav();
initSquadCard();
loadActiveTournament();
