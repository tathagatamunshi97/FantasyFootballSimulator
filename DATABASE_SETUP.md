# PostgreSQL Database Setup for Render

This document explains how to set up persistent PostgreSQL storage for the football simulator **on Render only**. Local development continues to use JSON files.

## Architecture

- **Local development**: Uses JSON files (`data/manual_profiles.json`, `data/team_lineups.json`, `data/seed_seasons.json`)
- **Render production**: Uses PostgreSQL database when `DATABASE_URL` is set
- **Fallback**: If database fails, both modes fall back to JSON files

## Why Database Storage on Render?

Render's ephemeral filesystem means data stored in `/data/*.json` files is lost when:
- The app restarts after inactivity
- A new instance is deployed
- The service is redeployed
- Render performs maintenance

By using PostgreSQL, your data persists across all these events. Local development is unaffected—it continues to use JSON files as before.

## Quick Start (Render Only)

**Local development?** You don't need to do anything—just use the simulator as normal with JSON files.

### 1. Get Your DATABASE_URL from Render

Go to your Render PostgreSQL database service:
1. Log into [https://dashboard.render.com](https://dashboard.render.com)
2. Click on your PostgreSQL service (`postgresql-fantasyfootballsimulator`)
3. In the "Connections" section, copy the **External Database URL** (marked "Recommended")
   - It will look like: `postgresql://user:password@host:port/dbname?sslmode=require`

### 2. Set the Environment Variable on Render

In your Render web service (the one running the football simulator):
1. Go to "Environment" in the left sidebar
2. Add a new environment variable:
   - **Key**: `DATABASE_URL`
   - **Value**: [paste the URL from step 1]
3. Click "Save Changes"
4. The service will automatically redeploy with the new environment variable

### 3. Install Dependencies

Make sure `psycopg2-binary` is in `requirements.txt` (it's been added automatically):
```
psycopg2-binary>=2.9
```

Deploy this change:
```bash
git add requirements.txt
git commit -m "Add psycopg2-binary for PostgreSQL support"
git push
```

### 4. Migrate Existing Data to Database (One-Time, Render Only)

If you have existing data in `manual_profiles.json`, `team_lineups.json`, or `seed_seasons.json` and want to migrate it to PostgreSQL (so it persists on Render), run the migration script via a **Render one-off job**:

**Via Render one-off job**:
```bash
# From your project directory
render deploy --option run_command="python migrate_to_db.py"
```

Or via Render dashboard:
1. Go to your web service
2. Click "One-off Jobs" in the left sidebar
3. Create a new job with command: `python migrate_to_db.py`

The script will migrate:
- All manual player profiles
- All saved team lineups
- All seed season entries

### 5. Restart and Verify

1. Redeploy or restart your web service on Render
2. Check logs: you should see `Database: tables initialized successfully`
3. Your data is now persisted in PostgreSQL!

## Database Schema

The database creates three main tables:

### `manual_profiles`
Stores manual player prime/season-pick stat overrides:
- `player_name`: Player name
- `profile_type`: 'prime' or 'season_pick'
- `season_suffix`: e.g., '23/24' or '24/25'
- `season_label`: e.g., '2023-2024'
- `stats`: JSON object with all player stats

### `team_lineups`
Stores saved team lineups and finalization state:
- `team_name`: Unique team identifier
- `formation`: e.g., '4-3-3 flat'
- `lineup`: JSON array of slot/player assignments
- `bench`: JSON array of bench players
- `prime_player`: Name of prime player override
- `peak_season`: JSON object for seasonal pick override
- Finalization metadata (`finalized`, `finalized_at`, `finalized_round`, etc.)

### `seed_seasons`
Stores seed season overrides (player historical stats):
- `player_id`: Sofascore player ID
- `season_suffix`: e.g., '23/24'
- `stats`: JSON object with per-90 stats

## How It Works

**Local (no DATABASE_URL):**
- Reads data from JSON files
- Writes data to JSON files
- Fully functional, data persists in your local `/data/` directory

**Render (DATABASE_URL set):**
- Reads data from PostgreSQL first, falls back to JSON if database fails
- Writes data to JSON files (always, for backup) + PostgreSQL (if enabled)
- Data persists across redeploys, restarts, and instance changes

## Monitoring and Troubleshooting

### Check Database Connection
The app logs will show:
```
Database: tables initialized successfully
```

If you see:
```
Database: warning - running without database: ...
```

Then check:
1. Is `DATABASE_URL` set in Render environment variables?
2. Is the PostgreSQL database running and accessible?
3. Can you connect manually with the connection string?

### Inspect Database Contents
Connect directly to your Render PostgreSQL:
```bash
psql "postgresql://user:password@host:port/dbname?sslmode=require"
```

List tables:
```sql
\dt
```

View manual profiles:
```sql
SELECT player_name, profile_type, season_suffix FROM manual_profiles LIMIT 10;
```

View team lineups:
```sql
SELECT team_name, formation, updated_at FROM team_lineups;
```

### Clear All Data
To reset the database and start fresh:
```sql
DROP TABLE IF EXISTS manual_profiles, team_lineups, seed_seasons CASCADE;
```

Then run `migrate_to_db.py` again to repopulate from JSON files (if they still exist locally).

## Storage Usage

With the 1GB limit on your Render PostgreSQL:
- ~10,000 player profiles with full stats: ~50 MB
- ~100 team lineups with full history: ~5 MB
- ~50,000 seed season entries: ~200 MB
- **Total typical usage: ~300 MB** (well within 1GB limit)

You have plenty of headroom for growth.

## Next Steps

1. ✅ Copy DATABASE_URL to Render environment
2. ✅ Deploy with psycopg2-binary in requirements.txt
3. ✅ Run migration script (if migrating existing data)
4. ✅ Restart app and verify logs
5. ✅ Test by saving/loading lineups — data now persists!

## Questions?

- Database connection issues → Check Environment variables on Render dashboard
- Data not migrating → Check migration script output for errors
- Performance concerns → Database queries are cached heavily in app code
