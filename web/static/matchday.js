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

async function refresh() {
  try {
    const data = await api("/api/matchday");
    document.getElementById("app").innerHTML = renderMatchdayList(data.experiments || []);
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
setInterval(refresh, 5000);
