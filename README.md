# Football Match Simulator

Monte Carlo **real match** simulator between two custom lineups. Stats from **Sofascore** (`datafc`) plus **Understat** enrichment (`soccerdata`) for xGChain / xGBuildup / npxG. Seasons **2024-25** and **2025-26** blended 50/50.

## Quick start

```bash
cd fantasy_football_simulator
pip install -r requirements.txt
python fetch_stats.py              # Sofascore + Understat (~2-5 min)
python main.py monte-carlo -n 20000
```

## Data sources

| Source | Stats |
|--------|-------|
| **Sofascore** | xG, xA, shots, key passes, tackles, interceptions, clearances, dribbles, passing, long balls, big chances, possession lost, saves, goals prevented, rating |
| **Understat** | npxG, xGChain, xGBuildup (progression / involvement in attacks) |

Understat fills gaps Sofascore lacks (build-up play, chain involvement). Pressures, blocks, and aerials are still unavailable from either source.

## Match model

Four **unit ratings** (0–1) per team:

- **Attack** — npxG, xG, shots, big chances, xGChain, dribbles
- **Midfield** — xGBuildup, passing volume/accuracy, key passes, tackles, minus possession lost
- **Defence** — tackles, interceptions, clearances
- **Goalkeeper** — goals prevented, saves

Then:

1. **Midfield battle** — better midfield gets a chance-creation multiplier (~±8%)
2. **Attack vs defence** — attack rating converted to xG, suppressed by opponent DEF+GK
3. **Formation fit** — tactical slot fit tweaks output
4. **Poisson goals** — scoreline sampled; scorers assigned by xG/xA shares

## Web dashboard (share results with viewers)

You run simulations; others watch live on the dashboard.

### Recommended: Render (no domain, fixed URL)

For a **stable public link without a domain or your PC running**, deploy to **[Render](https://render.com/)** — see **[DEPLOY.md](DEPLOY.md)**. You get `https://fantasy-football-simulator.onrender.com` (never changes). Trade-off: free tier cold starts and ephemeral runtime data.

### Alternative: local server + named Cloudflare tunnel (requires domain)

Your laptop hosts the app. **All data stays in `data/` on disk**. Cloudflare provides a fixed URL (e.g. `https://sim.yourdomain.com`).

**One-time setup:** follow **[setup_named_tunnel.md](setup_named_tunnel.md)** (Cloudflare account + domain).

**Every time you share (Windows):**

```powershell
# Edit start_local.ps1 once, then:
start_local.bat
```

Or manually:

```powershell
set SIM_ADMIN_TOKEN=your-secret-token
set CLOUDFLARE_PUBLIC_URL=https://sim.yourdomain.com
python run_public.py
```

Validate setup without starting the tunnel:

```powershell
python share_public.py --check
```

| URL | Who |
|-----|-----|
| `https://sim.yourdomain.com/login` | **Viewers** |
| `https://sim.yourdomain.com/admin` | **You** — run simulations (admin token) |
| `https://sim.yourdomain.com/lab` | Team lab |

Keep the terminal open while others use the link. Press Ctrl+C to stop.

### Local-only (no internet)

```powershell
set SIM_ADMIN_TOKEN=your-secret-token
python run_web.py
```

| URL | Who |
|-----|-----|
| `http://localhost:8080/` | **Viewers** — lineups, profiles, Monte Carlo results (auto-refresh every 5s) |
| `http://localhost:8080/admin` | **You** — run simulations (requires admin token) |

**LAN sharing:** use your machine's IP, e.g. `http://192.168.1.10:8080/`

### Quick tunnel (no Cloudflare account — random URL each restart)

```powershell
set SIM_ADMIN_TOKEN=your-secret-token
python run_public.py
```

Uses Cloudflare quick tunnel (`*.trycloudflare.com`). The link is printed and saved to `data/public_url.txt`. **URL changes every restart** — use named tunnel for a stable link.

### Local data (persists on your laptop)

| Path | Contents |
|------|----------|
| `data/experiments/` | Saved experiment runs |
| `data/tournaments/` | Tournament brackets |
| `data/player_stats_cache.json` | Player stats (Sofascore + Understat) |
| `data/web_state.json` | Latest simulation on the dashboard |
| `data/sessions.json` | Viewer sessions |
| `data/public_url.txt` | Last public URL (when tunnel runs) |

Nothing in `data/` is wiped when you restart the server or tunnel.

### Cloud hosting summary

Full step-by-step: **[DEPLOY.md](DEPLOY.md)**. Fixed URL: `https://fantasy-football-simulator.onrender.com`. No domain or Cloudflare account required.

Results are saved to `data/web_state.json` so viewers always see the latest completed run.

## CLI

```bash
python main.py simulate
python main.py monte-carlo -n 20000
python main.py formation-fit
```

Input: `data/team_a_vs_b.xlsx` (Team A 4-3-3 vs Team B 4-2-3-1).
