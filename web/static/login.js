function redirectAfterLogin(user) {
  const defaultNext = user === "admin" ? "/home" : "/squad";
  const next = new URLSearchParams(window.location.search).get("next") || defaultNext;
  window.location.href = next;
}

function showPasswordSetup(teamName) {
  document.getElementById("loginCard").hidden = true;
  document.getElementById("setupCard").hidden = false;
  document.getElementById("setupTeamLabel").textContent = teamName;
  document.getElementById("setupTeamName").value = teamName;
  document.getElementById("newPassword").focus();
}

function showLoginForm() {
  document.getElementById("setupCard").hidden = true;
  document.getElementById("loginCard").hidden = false;
  document.getElementById("setupError").hidden = true;
}

document.getElementById("setupBackBtn").addEventListener("click", showLoginForm);

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
    if (data.needs_password_setup) {
      showPasswordSetup(data.user);
      return;
    }
    setSession(data.token, data.user);
    redirectAfterLogin(data.user);
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  }
});

document.getElementById("setupForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = document.getElementById("setupError");
  err.hidden = true;
  try {
    const name = document.getElementById("setupTeamName").value;
    const new_password = document.getElementById("newPassword").value;
    const confirm_password = document.getElementById("confirmPassword").value;
    const data = await fetch("/api/set-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, new_password, confirm_password }),
    }).then(async (r) => {
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || "Could not set password");
      return j;
    });
    setSession(data.token, data.user);
    redirectAfterLogin(data.user);
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  }
});

if (getToken()) {
  window.location.href = isAdminUser() ? "/home" : "/squad";
}
