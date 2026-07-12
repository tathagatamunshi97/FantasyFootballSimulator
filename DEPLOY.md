# Deploy to Render — fixed URL, no domain required

## No domain? Use this

You do **not** need Cloudflare, a custom domain, or quick tunnels (`*.trycloudflare.com` links that change every restart).

**GitHub + Render** gives you a **permanent** public URL:

| What | Value |
|------|-------|
| **Your fixed URL** | `https://fantasy-football-simulator.onrender.com` |
| **Viewer login** | `https://fantasy-football-simulator.onrender.com/login` |
| **Matchday (watch live)** | `https://fantasy-football-simulator.onrender.com/matchday` |
| **Admin panel** | `https://fantasy-football-simulator.onrender.com/admin` |
| **Tournament admin** | Same URL — `/admin#tournament` tab |
| **Team lab** | `https://fantasy-football-simulator.onrender.com/lab` |

The service name comes from `render.yaml` (`fantasy-football-simulator`). Render lowercases it for the hostname. **The URL stays the same** across redeploys unless you rename the service.

GitHub **Pages** and **Actions** cannot run this app (FastAPI/Python needs a real server). Render builds your `Dockerfile` on every push — no GitHub Actions workflow required.

---

## Do this now (numbered steps)

### 1. Create a GitHub repo

1. Go to [github.com/new](https://github.com/new)
2. Name it e.g. `fantasy-football-simulator` (any name works; the **Render URL** is fixed by `render.yaml`, not the repo name)
3. Leave it **empty** — do not add README, `.gitignore`, or license (you already have those locally)

### 2. Initialize git and push (first time only)

**Current status:** this folder is **not** a git repo yet. Run these locally from `fantasy_football_simulator/`:

```powershell
cd "C:\Users\Admin\OneDrive - Mojro Technologies\Desktop\Code Repo\Driver Assignment Engine\v2.2\fantasy_football_simulator"

git init
git add .
git commit -m "Initial commit with Render deploy config"
git branch -M main
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

Replace `YOUR_USER/YOUR_REPO` with your GitHub username and repo name.

**`data/player_stats_cache.json`:** ~3.8 MB — well under GitHub’s 100 MB file limit. **Git LFS is not needed.** This file must be committed so player stats are baked into the Docker image.

Verify it is tracked:

```powershell
git ls-files data/player_stats_cache.json
```

To refresh stats before a later push:

```powershell
python fetch_stats.py
git add data/player_stats_cache.json
git commit -m "Update player stats cache"
git push
```

### 3. Sign up on Render with GitHub

1. Go to [render.com](https://render.com/) → **Get Started**
2. Choose **Sign up with GitHub** and authorize Render

### 4. Create the web service (Blueprint — recommended)

1. [Render Dashboard](https://dashboard.render.com/) → **New** → **Blueprint**
2. Connect GitHub and select your repo
3. Render reads `render.yaml` at the repo root and creates **`fantasy-football-simulator`**
4. Click **Apply**

**Manual alternative:** **New** → **Web Service** → connect repo → Runtime: **Docker** → Health check: `/api/health` → Plan: **Free**. Set env vars from the table below.

### 5. Set / copy `SIM_ADMIN_TOKEN`

The blueprint **auto-generates** `SIM_ADMIN_TOKEN`. After deploy:

1. Open the service → **Environment**
2. Copy the value of `SIM_ADMIN_TOKEN` (use this at `/admin`)

If you created the service manually, add `SIM_ADMIN_TOKEN` yourself — a long random string (32+ characters).

### 6. Wait for deploy, then open your fixed URL

First build takes ~3–5 minutes. When status is **Live**:

```
https://fantasy-football-simulator.onrender.com/login
```

Use `/admin` with your `SIM_ADMIN_TOKEN` to run simulations. Admin web login at `/login` uses username **`admin`** and password **`SIM_ADMIN_TOKEN`** (not the literal word "admin"). Share `/login` with viewers; teams land on `/matchday` to watch live admin fixtures. See [MATCHDAY.md](MATCHDAY.md) for the full admin + player workflow.

Every future `git push` to `main` triggers an automatic redeploy. **The URL never changes.**

---

## Tradeoffs vs running locally

| | **Render (this guide)** | **Local + quick tunnel** | **Local + named tunnel** |
|--|-------------------------|--------------------------|--------------------------|
| **Fixed URL** | ✅ `https://fantasy-football-simulator.onrender.com` | ❌ Random each restart | ✅ Custom subdomain (needs domain) |
| **Domain required** | ❌ No | ❌ No | ✅ Yes |
| **Laptop must stay on** | ❌ No | ✅ Yes | ✅ Yes |
| **Cold start** | ~30–60 s after ~15 min idle (free tier) | None while PC is on | None while PC is on |
| **Data persistence** | Ephemeral disk — tournaments/experiments reset on redeploy | Full local `data/` | Full local `data/` |
| **Player stats cache** | ✅ In Docker image (from git) | ✅ Local file | ✅ Local file |
| **Google Sheets teams** | ✅ Fetched live | ✅ Fetched live | ✅ Fetched live |
| **Cost** | Free tier | Free | Free (+ domain) |

**Choose Render** when you want a **stable share link without a domain or a PC running 24/7**. Accept that runtime writes under `data/` (tournaments, experiments, sessions) are **lost on redeploy** on the free tier.

**Choose local hosting** when you need zero cold start or full disk persistence. See [setup_named_tunnel.md](setup_named_tunnel.md) only if you have a domain; otherwise use Render or accept quick-tunnel URL churn.

---

## Environment variables

| Variable | Required | Notes |
|----------|----------|-------|
| `SIM_ADMIN_TOKEN` | **Yes** | Secret for `/admin`. Blueprint auto-generates. |
| `GOOGLE_SHEETS_ID` | No | Default sheet is bundled. |
| `GOOGLE_SHEETS_TEAMS_GID` | No | Default works out of the box. |
| `SIM_HOST` | No | `0.0.0.0` (set in `render.yaml`). |
| `PORT` | Auto | Render sets this — **do not** set `SIM_PORT`. |

Google Sheets must be **"Anyone with the link can view"** (public CSV export). No Google API key required.

---

## Free tier limitations

| Limitation | Impact |
|------------|--------|
| **Sleeps after ~15 min idle** | First visitor after sleep waits **30–60 s**. A quiet Matchday tab may not count as traffic if nobody hits the API — keep `/matchday` open and refreshing. |
| **~512 MB RAM** | Live pin matches + many viewers are OK; **do not** run Chrome/`soccerdata` live fetches on Render during matchday (OOM → instant restart). |
| **Process restarts** | Health-check failures, OOM, deploys, or platform blips **wipe in-memory Matchday** and force re-login. Bandwidth spikes on the graph often line up with a crash/restart, not “reset by itself.” |
| **Ephemeral filesystem** | Runtime `data/` writes vanish on **redeploy**. Within one deploy, disk files usually survive a process restart. |
| **750 free instance hours/month** | One service fits comfortably |
| **No custom domain on free** | URL stays `*.onrender.com` |

### What survives a Render stop vs what does not

| State | Where it lives | Survive process restart (same deploy)? | Survive redeploy / free rebuild? |
|-------|----------------|----------------------------------------|----------------------------------|
| **Live Matchday board** (minute, score, events) | Memory + `data/matchday_session.json` snapshot | **Yes** (restored from snapshot on startup) | **No** (disk wiped) |
| **Login sessions** | `data/sessions.json` (cleared on every startup by design) | **No** — everyone must log in again | **No** |
| **Tournament brackets / completed scores** | `data/tournaments/*.json` | Yes, if already saved | **No** unless committed or on a paid disk |
| **Team lineups** | `data/team_lineups.json` | Yes | **No** unless committed |
| **Team passwords** | `data/team_passwords.json` | Yes | **No** unless committed |
| **Player stats cache** | Baked into Docker image | Yes | Yes (from git) |

**Root cause of “reset everything” mid-match on free Render:** the service process stopped (sleep, OOM, health check, or deploy). Matchday used to be **memory-only**, so the live board vanished; startup also **clears all logins**. Completed tournament scores are only safe if `complete-from-board` finished writing the tournament JSON *before* the crash.

**Honest options for reliable live matchdays:**
1. **Paid Render** (always-on) + optional **persistent disk** for `data/`
2. **Host on your PC** (local + tunnel) during tournament days — full disk persistence
3. Stay on free: expect cold starts; avoid Chrome/stats fetches during matches; redeploy only between matchdays; commit passwords/tournaments if you must survive rebuilds

### Persistent data on Render

| Data | On free Render | Workaround |
|------|----------------|------------|
| **Player stats cache** | ✅ Persists (in image) | Commit `data/player_stats_cache.json`; re-push after `fetch_stats.py` |
| **Matchday mid-match snapshot** | ⚠️ Survives process restart; lost on redeploy | Auto-written to `data/matchday_session.json` |
| **Latest simulation** | ⚠️ Lost on redeploy | Re-run from admin |
| **Tournaments / experiments / passwords** | ⚠️ Lost on redeploy | Re-create, commit hashes carefully, or add [Render persistent disk](https://render.com/docs/disks) (paid) |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Deploy fails health check | Check logs; confirm `/api/health` returns `{"ok": true}` |
| Admin token rejected | Copy exact `SIM_ADMIN_TOKEN` from Render **Environment** |
| Empty player stats | Commit `data/player_stats_cache.json` and redeploy |
| Google Sheets error | Sheet must be publicly viewable |
| Port binding error | Remove `SIM_PORT` env var; let Render set `PORT` |
| Push rejected (large file) | Only if a single file exceeds 100 MB — current cache is ~3.8 MB, OK |
| Mid-match “everything reset” | Process restarted (sleep/OOM/deploy). Check Render **Events** + **Logs**. Matchday snapshot restores score/events after process restart; redeploy still wipes `data/`. |
| “Invalid login” after redeploy | Passwords on ephemeral disk were wiped — teams must set passwords again (or bake `team_passwords.json` into the image) |

---

## Local Docker test (optional)

Before pushing:

```powershell
docker build -t fantasy-sim .
docker run -p 8080:8080 -e SIM_ADMIN_TOKEN=test-secret -e PORT=8080 fantasy-sim
```

Open `http://localhost:8080/login`.

---

## See also

- [README.md](README.md) — features and local development
- [MATCHDAY.md](MATCHDAY.md) — admin run live fixtures, player watch flow
- [setup_named_tunnel.md](setup_named_tunnel.md) — optional; only if you have a domain and want local hosting with a fixed URL
