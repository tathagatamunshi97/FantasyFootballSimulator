# Admin Match Recording Guide

## Overview

Admin users can now manually record match results and scorers/assisters **retroactively**. This is useful when:
- Matches were run but the results got deleted (e.g., due to Render instance changes)
- You want to record actual matches that happened outside the simulator
- You need to update historical scorelines with player statistics

This functionality stores data **directly in the PostgreSQL database** (when enabled on Render) and is **separate from the simulation override feature**.

## Database Storage

When `DATABASE_URL` is set on Render, three tables store match data:

### `match_results` table
Stores final scoreline for each match:
- `tournament_id` — which tournament
- `match_id` — unique match identifier
- `home_team`, `away_team` — team names
- `home_goals`, `away_goals` — final score
- `stage` — 'group' or 'knockout'
- `group_key` — group letter (A, B, C, etc.) for group-stage matches
- `manually_recorded` — flag indicating this was manually recorded
- `created_at`, `updated_at` — timestamps

### `match_events` table
Stores individual goals and assists:
- `tournament_id`, `match_id` — which match
- `team` — team name
- `player` — scorer/assister name
- `event_type` — 'goal' or 'assist'
- `minute` — optional minute of the goal
- `assister` — name of the assist provider (for goals)

## API Usage (Admin Only)

All endpoints require `X-Admin-Token` header with your `SIM_ADMIN_TOKEN`.

### Record a Match Result

**POST** `/api/admin/tournament/{tournament_id}/matches/{match_id}/record-result`

Records a final scoreline and all player events (goals/assists).

**Request body:**
```json
{
  "home_goals": 2,
  "away_goals": 1,
  "events": [
    {
      "team": "Team A",
      "player": "Player Name",
      "event_type": "goal",
      "minute": 23,
      "assister": "Assister Name"
    },
    {
      "team": "Team A",
      "player": "Another Player",
      "event_type": "goal",
      "minute": 67
    },
    {
      "team": "Team B",
      "player": "Team B Player",
      "event_type": "goal",
      "minute": 45
    }
  ]
}
```

**Response:**
```json
{
  "ok": true,
  "match_id": "match_123",
  "tournament_id": "tournament_456",
  "result": {
    "tournament_id": "tournament_456",
    "match_id": "match_123",
    "home_team": "Team A",
    "away_team": "Team B",
    "home_goals": 2,
    "away_goals": 1,
    "stage": "group",
    "group_key": "A",
    "manually_recorded": true,
    "created_at": "2026-07-13T10:30:00"
  },
  "events": [
    {
      "team": "Team A",
      "player": "Player Name",
      "event_type": "goal",
      "minute": 23,
      "assister": "Assister Name"
    },
    ...
  ],
  "message": "Recorded Team A 2-1 Team B with 3 event(s)"
}
```

### Get a Recorded Match Result

**GET** `/api/admin/tournament/{tournament_id}/matches/{match_id}/recorded-result`

Retrieves a previously recorded match and its events.

**Response:**
```json
{
  "tournament_id": "tournament_456",
  "match_id": "match_123",
  "result": { /* match result */ },
  "events": [ /* all goal/assist events */ ],
  "found": true
}
```

### List All Recorded Results for a Tournament

**GET** `/api/admin/tournament/{tournament_id}/recorded-results`

Lists all manually recorded matches in a tournament.

**Response:**
```json
{
  "tournament_id": "tournament_456",
  "results": [
    { /* match 1 */ },
    { /* match 2 */ }
  ],
  "count": 2
}
```

## Using curl (Command Line)

Record a match result:
```bash
curl -X POST http://localhost:8000/api/admin/tournament/tourn_123/matches/match_456/record-result \
  -H "X-Admin-Token: your_sim_admin_token" \
  -H "Content-Type: application/json" \
  -d '{
    "home_goals": 2,
    "away_goals": 1,
    "events": [
      {
        "team": "Team A",
        "player": "Harry Kane",
        "event_type": "goal",
        "minute": 23,
        "assister": "James Maddison"
      }
    ]
  }'
```

Get recorded results:
```bash
curl -X GET http://localhost:8000/api/admin/tournament/tourn_123/recorded-results \
  -H "X-Admin-Token: your_sim_admin_token"
```

## Tournament Information Storage

**Yes, tournament information is now stored in the database.**

Currently stored in the database:
- ✅ **Match results** (scores, goals, assists) — `match_results` and `match_events` tables
- ✅ **Team lineups** — `team_lineups` table
- ✅ **Manual player profiles** — `manual_profiles` table
- ✅ **Seed seasons** — `seed_seasons` table

**NOT stored in the database (still in JSON):**
- ❌ Tournament structure/metadata (groups, bracket, fixtures) — still in `data/tournaments/{tournament_id}.json`
  - This is because tournament structure changes frequently during setup/draw/bracket generation
  - Keeping it in a single JSON file makes it easier to manage as a unit

### Storing Tournament Metadata in Database (Optional)

If you want to persist tournament structure/metadata in the database too, I can add tables for:
- Tournament metadata (name, status, format, team list)
- Group stage setup (groups, teams per group, advance count)
- Fixtures (which teams play which, in what order)
- Knockout bracket (semifinals, finals, winners)

Would you like me to add this? It would mean:
- No more tournament JSON files in `data/tournaments/`
- Full database-backed tournament system
- Better multi-instance resilience (multiple Render instances could run simultaneously without file conflicts)

For now, the match recording covers your immediate need (retroactive result entry), and tournament structure remains in JSON for simplicity.

## Example Workflow: Recreating Lost Matches

1. **Identify the match**: Look at your tournament structure to find tournament_id and match_id
2. **Record the result**: POST to `/api/admin/tournament/{tournament_id}/matches/{match_id}/record-result` with the scoreline
3. **Add player events**: Include goals/assists in the same request
4. **Verify**: GET `/api/admin/tournament/{tournament_id}/recorded-results` to confirm

Example: Recreate a lost Group A match between Team A (2) and Team B (1):

```bash
curl -X POST http://localhost:8000/api/admin/tournament/my_tournament_123/matches/group_a_1/record-result \
  -H "X-Admin-Token: my_token" \
  -H "Content-Type: application/json" \
  -d '{
    "home_goals": 2,
    "away_goals": 1,
    "events": [
      {"team": "Team A", "player": "Erling Haaland", "event_type": "goal", "minute": 12, "assister": "Phil Foden"},
      {"team": "Team A", "player": "Manuel Akanji", "event_type": "goal", "minute": 78},
      {"team": "Team B", "player": "Mbappe", "event_type": "goal", "minute": 45}
    ]
  }'
```

This creates the match record in the database, ready to be incorporated into final stats and standings.

## Notes

- **Local development**: Recording endpoints return a message that database is not enabled (runs fine with JSON for testing)
- **Re-recording**: Posting to the same tournament/match_id replaces the previous events (useful for corrections)
- **Stats integration**: The recorded scorers/assisters are stored but need to be integrated into your stats board separately (not automatic yet)
