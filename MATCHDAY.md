# Matchday — live admin simulations

Matchday is the **broadcast view** for admin-run simulations. Teams log in to **watch** live and recently finished matches. Only the admin can **start** simulations.

## Roles

| Role | Can start sims | Can watch matchday | Can browse full history (`/home`, `/lab`) |
|------|----------------|--------------------|-------------------------------------------|
| **Admin** (`admin` + `SIM_ADMIN_TOKEN`) | Yes | Yes | Yes |
| **Team** (sheet team + password) | No | Yes (live + last 24h) | No |

---

## Admin: run a tournament fixture live

1. Open **`/admin`** and paste your `SIM_ADMIN_TOKEN`.
2. Go to the **Tournament** tab.
3. Create or select a tournament → add teams → **Run group draw** → **Generate fixtures**.
4. Under **Run matches**, click a fixture (e.g. `Team A vs Team B`).
5. The simulation starts in the background and appears on **`/matchday`** with a **Live** badge.
6. Share **`/matchday`** with players — they refresh automatically every 5 seconds.
7. When finished, the tournament table updates and the match stays watchable for 24 hours.

Knockout fixtures work the same way after **Generate knockout**.

**Tip:** Open **`/matchday`** in another tab while running matches to confirm the broadcast.

---

## Admin: ad-hoc test simulation

1. **`/admin`** → **Quick simulation** tab — pick two teams and run.
2. Or **`/lab`** → build a custom matchup and submit (admin login only).
3. Both appear on **`/matchday`** for viewers.

---

## Players: what you see

1. Log in at **`/login`** (team name + password).
2. You land on **`/matchday`** by default.
3. **Live** matches show a green pulsing badge; click the matchup for full analysis.
4. Recently finished matches (last 24 hours) stay visible.
5. Use **My Squad** for squad evaluation and opponent scouting.
6. You **cannot** create simulations or browse the full experiment archive.

Empty state: *"Admin hasn't started a match yet."*

---

## Persistence & Render caveats

Matchday keeps the live board in **memory** and also writes a snapshot to **`data/matchday_session.json`** (about every 2s while frames publish, and immediately on kickoff / HT / FT / clear). After a **process restart**, the server reloads that snapshot so viewers still see the last score/events.

That does **not** fully replay the pin engine from scratch — it restores the last published frame. Tournament table scores are only permanent after **complete-from-board** saves the tournament JSON.

On **Render free tier**:
- Idle spin-down, OOM, health-check kills, and redeploys can still interrupt a live match.
- Redeploy **wipes** runtime `data/` (including the snapshot and tournaments).
- Prefer **paid always-on** (and a persistent disk) or **local hosting** for important matchdays.
- See [DEPLOY.md](DEPLOY.md) for the full memory vs disk table.

---

## URLs

| Page | URL | Who |
|------|-----|-----|
| Login | `/login` | Everyone |
| Matchday (watch) | `/matchday` | Admin + teams |
| Squad hub | `/squad` | Admin + teams |
| Admin panel | `/admin` | Admin token |
| Tournament viewer | `/tournament` | Everyone (read-only bracket) |
| Team lab | `/lab` | Admin only |
| Experiment archive | `/home` | Admin only |

---

## API (for integrators)

- `GET /api/matchday` — any logged-in session; teams get live + recent broadcasts only.
- `GET /api/experiments/{id}` — teams allowed only for matchday-flagged experiments that are running or finished within 24 hours.
- `POST /api/tournament/{id}/matches/{match_id}/run` — admin token; starts background sim linked to matchday.
