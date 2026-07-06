if (!requireAuth()) throw new Error("auth");
if (isTeamUser()) {
  window.location.replace("/squad");
  throw new Error("redirect");
}

document.getElementById("userLabel").textContent = getUser() || "";
document.getElementById("logoutBtn").addEventListener("click", async () => {
  try {
    await api("/api/logout", { method: "POST" });
  } catch (_) {}
  clearSession();
  window.location.href = "/login";
});

async function refresh() {
  try {
    const data = await api("/api/experiments");
    const app = document.getElementById("app");
    app.innerHTML = renderExperimentList(data.experiments || [], { showDelete: true });
    app.querySelectorAll(".delete-exp").forEach((btn) => {
      btn.addEventListener("click", () => deleteExperiment(btn.dataset.id, btn.dataset.label));
    });
  } catch (e) {
    if (e.message.includes("401") || e.message.includes("Login")) {
      clearSession();
      window.location.href = "/login";
      return;
    }
    document.getElementById("app").innerHTML = `<div class="empty">Failed to load: ${esc(e.message)}</div>`;
  }
}

async function deleteExperiment(expId, label) {
  if (!confirm(`Delete experiment "${label}"? This cannot be undone.`)) return;
  try {
    await api(`/api/experiments/${expId}`, { method: "DELETE" });
    await refresh();
  } catch (e) {
    alert(`Delete failed: ${e.message}`);
  }
}

refresh();
setInterval(refresh, 5000);
