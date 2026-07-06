# Fixed public URL — local server + Cloudflare named tunnel (free)



Run the simulator on **your laptop**. All data stays in the local `data/` folder. Cloudflare gives you the **same URL every time** (e.g. `https://sim.yourdomain.com`).



**Requirements:** free [Cloudflare account](https://dash.cloudflare.com/sign-up), [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) installed, and a domain added to Cloudflare (any registrar; Cloudflare DNS is free).



---



## Run once vs every time



| When | What you run |

|------|----------------|

| **Once** | Install cloudflared, `cloudflared tunnel login`, create tunnel, DNS route, edit `cloudflared-config.yml` and `start_local.ps1` |

| **Every time you share** | Double-click `start_local.bat` **or** `python run_public.py` (keep the window open) |



**URL you get:** `https://sim.yourdomain.com` (or whatever hostname you chose) — **same link every restart**, as long as your PC is on and the tunnel is running.



**Data:** experiments, tournaments, stats cache, and simulation results live under `data/` on your laptop and **survive restarts**. Nothing is uploaded to Render or Cloudflare.



---



## One-time setup (copy-paste)



Run these in **PowerShell** from the `fantasy_football_simulator` folder.



### 1. Install cloudflared



```powershell

winget install Cloudflare.cloudflared

```



Close and reopen the terminal, then verify:



```powershell

cloudflared --version

python share_public.py --check

```



### 2. Create a Cloudflare account and add your domain



1. Sign up: https://dash.cloudflare.com/sign-up  

2. **Add a site** → enter your domain → follow the steps to point nameservers to Cloudflare (or transfer DNS).  

3. Wait until the domain shows **Active** in the Cloudflare dashboard.



You do **not** need a paid Cloudflare plan for tunnels.



### 3. Log in to Cloudflare (interactive — opens browser)



```powershell

cloudflared tunnel login

```



A browser tab opens. Log in, then **select the zone (domain)** you will use for the simulator (e.g. `yourdomain.com`).



This creates `C:\Users\YOUR_USER\.cloudflared\cert.pem` on your machine.



### 4. Create a named tunnel



```powershell

cloudflared tunnel create fantasy-football-sim

```



Note the output:



- **Tunnel UUID** (e.g. `abc12345-6789-...`)

- **Credentials file**, e.g. `C:\Users\YOUR_USER\.cloudflared\abc12345-....json`



List tunnels anytime:



```powershell

cloudflared tunnel list

```



### 5. Edit `cloudflared-config.yml`



The repo includes `cloudflared-config.yml` (gitignored). Open it and replace **two placeholders**:



```yaml

tunnel: fantasy-football-sim

credentials-file: C:\Users\YOUR_USER\.cloudflared\PASTE-UUID-HERE.json



ingress:

  - hostname: sim.yourdomain.com

    service: http://127.0.0.1:8080

  - service: http_status:404

```



- `credentials-file` → full path from step 4  

- `hostname` → your subdomain (must be a domain on Cloudflare)



### 6. Create DNS route (maps hostname → tunnel)



Replace `sim.yourdomain.com` with your real hostname:



```powershell

cloudflared tunnel route dns fantasy-football-sim sim.yourdomain.com

```



Cloudflare creates a CNAME automatically. Check **DNS** in the dashboard if needed.



### 7. Set secrets in `start_local.ps1`



Edit the top of `start_local.ps1`:



```powershell

$env:SIM_ADMIN_TOKEN = "pick-a-long-random-secret"

$env:CLOUDFLARE_PUBLIC_URL = "https://sim.yourdomain.com"

```



### 8. Validate (no tunnel started yet)



```powershell

python share_public.py --check

```



Fix anything marked `[!]` until status is **READY**.



---



## Every time you want to share



**Option A — double-click (Windows):**



```

start_local.bat

```



**Option B — PowerShell:**



```powershell

cd fantasy_football_simulator

$env:SIM_ADMIN_TOKEN = "your-secret"

$env:CLOUDFLARE_PUBLIC_URL = "https://sim.yourdomain.com"

python run_public.py

```



Keep the terminal open. Share with viewers:



| Page | URL |

|------|-----|

| Login | `https://sim.yourdomain.com/login` |

| Dashboard | `https://sim.yourdomain.com/` |

| Team lab | `https://sim.yourdomain.com/lab` |

| Admin (private) | `https://sim.yourdomain.com/admin` |



Stop sharing: press **Ctrl+C** in the terminal. Your `data/` folder is unchanged.



---



## Alternative: dashboard token (no local config file)



If you prefer the Cloudflare Zero Trust UI instead of `cloudflared-config.yml`:



1. Zero Trust → **Networks** → **Tunnels** → your tunnel → **Configure**  

2. **Public Hostname:** `sim.yourdomain.com` → `http://localhost:8080`  

3. Copy the **Run connector** token  

4. Set before starting:



```powershell

$env:CLOUDFLARE_TUNNEL_TOKEN = "eyJhIjoi..."

$env:CLOUDFLARE_PUBLIC_URL = "https://sim.yourdomain.com"

$env:SIM_ADMIN_TOKEN = "your-secret"

python run_public.py

```



---



## Quick tunnel fallback (no Cloudflare account)



If named tunnel is **not** configured, `share_public.py` falls back to a **quick tunnel**:



```powershell

python run_public.py

```



You get a random URL like `https://something-random.trycloudflare.com` — **new URL every restart**. Fine for a one-off demo; use named tunnel for a stable link.



---



## Environment variables



| Variable | Purpose |

|----------|---------|

| `SIM_ADMIN_TOKEN` | Admin API password (required for production) |

| `CLOUDFLARE_PUBLIC_URL` | Stable URL, e.g. `https://sim.yourdomain.com` |

| `CLOUDFLARE_TUNNEL_TOKEN` | Named tunnel via dashboard token (optional) |

| `CLOUDFLARE_TUNNEL_NAME` | Tunnel name for `cloudflared tunnel run <name>` (optional) |

| `CLOUDFLARE_TUNNEL_CONFIG` | Path to config YAML (default: `./cloudflared-config.yml`) |

| `SIM_PORT` | Local port (default `8080`; must match ingress `service`) |



---



## Local data paths (everything stays on your laptop)



| Path | Contents |

|------|----------|

| `data/experiments/` | Saved experiment runs |

| `data/tournaments/` | Tournament brackets and state |

| `data/player_stats_cache.json` | Sofascore/Understat player stats |

| `data/web_state.json` | Latest simulation shown on the dashboard |

| `data/sessions.json` | Viewer login sessions |

| `data/public_url.txt` | Last public URL (written when tunnel starts) |

| `data/manual_profiles.json` | Custom player profiles |



These files are **not** deleted when you stop the tunnel or restart the app.



---



## Troubleshooting



| Issue | Fix |

|-------|-----|

| `cloudflared not found` | `winget install Cloudflare.cloudflared`; reopen terminal |

| `--check` shows placeholder values | Edit `cloudflared-config.yml` and `start_local.ps1` |

| Tunnel up but 502 | Ensure `run_public.py` is running; port in config must match `SIM_PORT` (8080) |

| Wrong URL in UI | Set `CLOUDFLARE_PUBLIC_URL` and restart |

| DNS not resolving | Re-run `cloudflared tunnel route dns ...` or add CNAME in Cloudflare DNS |

| `tunnel login` needed again | Run `cloudflared tunnel login` if cert expired or user changed |



Validate anytime:



```powershell

python share_public.py --check

```



---



## Optional: cloud hosting without your laptop



If you need the app online **without keeping your PC on**, see **[DEPLOY.md](DEPLOY.md)** (Render). Trade-offs: free tier sleeps after idle, and runtime `data/` on Render is ephemeral — **local hosting keeps full persistence in `data/`.**


