if (!requireAuth()) throw new Error("auth");

document.getElementById("userLabel").textContent = getUser() || "";
if (isAdminUser()) {
  document.getElementById("adminLinks").hidden = false;
}

document.getElementById("logoutBtn").addEventListener("click", async () => {
  try {
    await api("/api/logout", { method: "POST" });
  } catch (_) {}
  clearSession();
  window.location.href = "/login";
});

function wireMatchdayActions() {
  const runBtn = document.getElementById("matchdayRunBtn");
  if (runBtn) {
    runBtn.addEventListener("click", async () => {
      runBtn.disabled = true;
      try {
        await api("/api/matchday/run", { method: "POST" });
        await refresh();
      } catch (e) {
        alert(e.message);
        runBtn.disabled = false;
      }
    });
  }
  const dismissBtn = document.getElementById("matchdayDismissBtn");
  if (dismissBtn) {
    dismissBtn.addEventListener("click", async () => {
      try {
        await api("/api/matchday/dismiss", { method: "POST" });
        await refresh();
      } catch (e) {
        alert(e.message);
      }
    });
  }
}

async function refresh() {
  try {
    const data = await api("/api/matchday");
    const isAdmin = isAdminUser() || Boolean(getAdminToken());
    document.getElementById("app").innerHTML = renderMatchdaySession(data, { isAdmin });
    wireMatchdayActions();
  } catch (e) {
    if (e.message.includes("401") || e.message.includes("Login")) {
      clearSession();
      window.location.href = "/login?next=/matchday";
      return;
    }
    document.getElementById("app").innerHTML = `<div class="empty">Failed to load: ${esc(e.message)}</div>`;
  }
}

refresh();
setInterval(refresh, 3000);
