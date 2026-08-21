if (!requireAuthOrAdmin()) throw new Error("auth");

const expId = window.location.pathname.split("/").pop();
const fromMatchday = new URLSearchParams(window.location.search).get("from") === "matchday";

if (isTeamUser() && !fromMatchday) {
  window.location.replace("/matchday");
  throw new Error("redirect");
}

const canHostLive = isAdminUser() || getAdminToken();
if (canHostLive) {
  document.getElementById("adminLink").hidden = false;
}
document.getElementById("navBack").innerHTML = fromMatchday || isTeamUser()
  ? '<a href="/matchday" class="btn-link">← Matchday</a>'
  : '<a href="/admin" class="btn-link">← Admin</a>';

function setStatus(exp) {
  const badge = document.getElementById("statusBadge");
  badge.textContent = exp.status || "unknown";
  badge.className = `badge ${exp.status || ""}`;
  document.getElementById("pageTitle").textContent = `${exp.team_a?.name || "Team A"} vs ${exp.team_b?.name || "Team B"}`;
  document.getElementById("pageSub").textContent = `By ${exp.user || "—"}`;
}

let _expWired = false;

function renderLiveResultCard(liveResult) {
  const scorers = (liveResult.board_events || []).filter((e) => e.type === "goal");
  const rows = scorers
    .map((g) => {
      const side = g.side === "home" ? liveResult.home : liveResult.away;
      const assist = g.assist ? ` (assist: ${esc(g.assist)})` : "";
      const minute = g.minute != null ? `${Math.round(g.minute)}'` : "—";
      return `<tr><td>${minute}</td><td>${esc(side)}</td><td>${esc(g.player || "—")}${assist}</td></tr>`;
    })
    .join("");
  return `
    <div class="card" style="margin-bottom:1rem">
      <h2>Result — played on the live tactic board</h2>
      <p style="font-size:1.4rem;font-weight:600">${esc(liveResult.home)} ${liveResult.home_goals}–${liveResult.away_goals} ${esc(liveResult.away)}</p>
      ${rows ? `<table style="width:100%"><thead><tr><th>Min</th><th>Team</th><th>Scorer</th></tr></thead><tbody>${rows}</tbody></table>` : `<p class="muted">No goal-by-goal detail recorded.</p>`}
    </div>`;
}

async function hostLiveMatch() {
  const btn = document.getElementById("hostLiveBtn");
  if (btn) btn.disabled = true;
  try {
    await api(`/api/experiments/${expId}/start-live`, { method: "POST" });
    window.location.href = "/matchday";
  } catch (e) {
    alert(`Could not start live match: ${e.message}`);
    if (btn) btn.disabled = false;
  }
}

function renderHostLiveCard() {
  return `
    <div class="card" style="margin-bottom:1rem">
      <h2>Play this match live</h2>
      <p class="muted">Host these two teams on the live tactic board — the actual scorers/assists/result get recorded here once played.</p>
      <button type="button" id="hostLiveBtn" class="btn-primary">Host live match</button>
    </div>`;
}

async function refresh() {
  try {
    const data = await api(`/api/experiments/${expId}`);
    const exp = data.experiment;
    setStatus(exp);
    const app = document.getElementById("app");

    if (exp.status === "error") {
      _expWired = false;
      app.innerHTML = `<div class="empty"><span class="badge error">Error</span><p>${esc(exp.message)}</p><p>${document.getElementById("navBack").innerHTML}</p></div>`;
      return;
    }

    const watching = Boolean(document.querySelector("[data-tactic-mount]:not([hidden])"));
    if (_expWired && watching) return;

    let html = "";
    if (exp.live_result) {
      html = renderLiveResultCard(exp.live_result);
    } else if (canHostLive) {
      html = renderHostLiveCard();
    } else {
      html = `<div class="empty"><p>Waiting for this match to be hosted live.</p></div>`;
    }
    app.innerHTML = html;
    const hostBtn = document.getElementById("hostLiveBtn");
    if (hostBtn) hostBtn.addEventListener("click", hostLiveMatch);
    _expWired = true;
  } catch (e) {
    if (e.message.includes("403")) {
      window.location.replace("/matchday");
      return;
    }
    document.getElementById("app").innerHTML = `<div class="empty">Failed to load: ${esc(e.message)}</div>`;
  }
}

refresh();
setInterval(refresh, 5000);
