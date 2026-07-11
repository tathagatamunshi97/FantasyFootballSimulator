if (!requireAuthOrAdmin()) throw new Error("auth");

const expId = window.location.pathname.split("/").pop();
const fromMatchday = new URLSearchParams(window.location.search).get("from") === "matchday";

if (isTeamUser() && !fromMatchday) {
  window.location.replace("/matchday");
  throw new Error("redirect");
}

if (isAdminUser() || getAdminToken()) {
  document.getElementById("adminLink").hidden = false;
}
document.getElementById("navBack").innerHTML = fromMatchday || isTeamUser()
  ? '<a href="/matchday" class="btn-link">← Matchday</a>'
  : '<a href="/home" class="btn-link">My experiments</a>';

function setStatus(exp) {
  const badge = document.getElementById("statusBadge");
  badge.textContent = exp.status || "unknown";
  badge.className = `badge ${exp.status || ""}`;
  document.getElementById("pageTitle").textContent = `${exp.team_a?.name || "Team A"} vs ${exp.team_b?.name || "Team B"}`;
  document.getElementById("pageSub").textContent = `By ${exp.user || "—"} · ${exp.simulations?.toLocaleString() || "—"} simulations`;
}

let _expWired = false;

async function refresh() {
  try {
    const data = await api(`/api/experiments/${expId}`);
    const exp = data.experiment;
    setStatus(exp);
    const app = document.getElementById("app");

    if (exp.running || exp.status === "running" || exp.status === "queued") {
      _expWired = false;
      app.innerHTML = `<div class="empty"><span class="badge live">Live</span><p>${esc(exp.message)}</p><p class="muted">Refreshing every 5 seconds…</p></div>`;
      return;
    }

    if (exp.status === "error") {
      _expWired = false;
      app.innerHTML = `<div class="empty"><span class="badge error">Error</span><p>${esc(exp.message)}</p><p>${document.getElementById("navBack").innerHTML}</p></div>`;
      return;
    }

    if (!exp.report) {
      app.innerHTML = `<div class="empty"><p>No report yet.</p></div>`;
      return;
    }

    const watching = Boolean(document.querySelector("[data-tactic-mount]:not([hidden])"));
    if (_expWired && (watching || exp.status === "ready")) return;

    app.innerHTML = renderReport(exp.report, exp.report.matchup);
    if (typeof TacticBoard !== "undefined") {
      TacticBoard.wireWatchCard(app, exp.report, exp.report.matchup);
    }
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
