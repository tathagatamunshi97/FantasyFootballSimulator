document.getElementById("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = document.getElementById("error");
  err.hidden = true;
  try {
    const name = document.getElementById("name").value;
    const password = document.getElementById("password").value;
    const data = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, password }),
    }).then(async (r) => {
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || "Login failed");
      return j;
    });
    setSession(data.token, data.user);
    const next = new URLSearchParams(window.location.search).get("next") || "/home";
    window.location.href = next;
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  }
});

if (getToken()) {
  window.location.href = "/home";
}
