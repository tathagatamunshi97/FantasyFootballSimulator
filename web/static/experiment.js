if (!requireAuthOrAdmin()) throw new Error("auth");

const expId = window.location.pathname.split("/").pop();

function setStatus(exp) {
  const badge = document.getElementById("statusBadge");
  badge.textContent = exp.status || "unknown";
  badge.className = `badge ${exp.status || ""}`;
  document.getElementById("pageTitle").textContent = `${exp.team_a?.name || "Team A"} vs ${exp.team_b?.name || "Team B"}`;
  document.getElementById("pageSub").textContent = `By ${exp.user || "—"} · ${exp.simulations?.toLocaleString() || "—"} simulations`;
}

async function refresh() {
  try {
    const data = await api(`/api/experiments/${expId}`);
    const exp = data.experiment;
    setStatus(exp);
    const app = document.getElementById("app");

    if (exp.running || exp.status === "running" || exp.status === "queued") {
      app.innerHTML = `<div class="empty"><span class="badge running">${esc(exp.status)}</span><p>${esc(exp.message)}</p><p class="muted">Refreshing every 5 seconds…</p></div>`;
      return;
    }

    if (exp.status === "error") {
      app.innerHTML = `<div class="empty"><span class="badge error">Error</span><p>${esc(exp.message)}</p><p><a href="/lab">Try again</a></p></div>`;
      return;
    }

    if (!exp.report) {
      app.innerHTML = `<div class="empty"><p>No report yet.</p></div>`;
      return;
    }

    app.innerHTML = renderReport(exp.report, exp.report.matchup);
  } catch (e) {
    document.getElementById("app").innerHTML = `<div class="empty">Failed to load: ${esc(e.message)}</div>`;
  }
}

refresh();
setInterval(refresh, 5000);
