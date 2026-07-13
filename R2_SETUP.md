# Cloudflare R2 Setup for Persistent File Storage

## Overview

Your app now uses a **two-tier storage architecture** on Render:

- **PostgreSQL (Database)** — Structured data
  - Match results, lineups, profiles, seed seasons
  - Fast queries, transactional
  
- **Cloudflare R2 (Object Storage)** — Unstructured files
  - Tournament metadata (JSON)
  - Match analysis reports
  - Any large JSON blobs
  - Survives redeploys, instance changes, etc.

- **Local JSON** — Development fallback
  - Uses local `/data/` directory when R2/DB not configured
  - Full functionality locally without external dependencies

## Why R2?

- **Affordable**: ~$0.015/GB stored + $0.20/million requests (vs. $5-20/month for a minimum DB)
- **Durable**: 99.95% uptime SLA, replicated globally
- **Unlimited**: No size limits like a typical database
- **Easy**: S3-compatible API, works with boto3
- **Fast**: CDN-backed for reads

## Step 1: Create Cloudflare R2 Bucket

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com/) → R2 → Create Bucket
2. Bucket name: `football-simulator` (or your choice, update in Step 3 if different)
3. Click Create

## Step 2: Generate R2 API Credentials

1. In Cloudflare, go to R2 → API Tokens
2. Click "Create API Token"
3. **Permission**: Edit (to read/write)
4. **Scope**: Select your bucket or "All buckets"
5. **TTL**: None (no expiration)
6. Create token → copy the credentials:
   - **Account ID**
   - **Access Key ID**
   - **Secret Access Key**

⚠️ **Save these securely** — you won't see the secret again!

## Step 3: Set Environment Variables on Render

In your Render web service → Environment, add:

```
R2_ACCOUNT_ID = <your-account-id>
R2_ACCESS_KEY_ID = <your-access-key-id>
R2_SECRET_ACCESS_KEY = <your-secret-access-key>
R2_BUCKET_NAME = football-simulator
```

**Note**: `R2_BUCKET_NAME` is optional; defaults to `football-simulator`.

Redeploy your service.

## Step 4: Verify Setup

Check logs on startup. You should see:
```
R2 Storage: enabled and connected
```

Or if not enabled:
```
R2 Storage: disabled (not configured)
```

## Data Stored in R2

When R2 is enabled, the following automatically moves to R2:

- **Tournament Metadata** (`tournaments/{tournament_id}/metadata.json`)
  - Group structure, bracket, settings, team assignments
  
- **Match Analyses** (`tournaments/{tournament_id}/analysis/{match_id}.json`)
  - Pre-match analysis, predictions, xG reports
  
- **Other Blobs** (optional)
  - Matchday sessions, experiment results, etc.

## Local Fallback

If R2 credentials are not set (`R2_ACCOUNT_ID`, etc. missing):
- Module gracefully disables (`is_r2_enabled()` returns False)
- All file I/O falls back to local `/data/` directory
- **Full functionality**, just ephemeral on Render
- Perfect for local development without any R2 setup

## API Functions (for developers)

### Tournament Metadata

```python
import r2_storage

# Save tournament metadata
r2_storage.save_tournament_metadata("tournament_123", {
    "name": "My Tournament",
    "format": "group+knockout",
    "teams": ["Team A", "Team B"],
    ...
})

# Load tournament metadata
metadata = r2_storage.load_tournament_metadata("tournament_123")

# Delete tournament
r2_storage.delete_tournament_metadata("tournament_123")

# List all tournaments
tournaments = r2_storage.list_tournament_ids()
```

### Match Analysis

```python
# Save analysis
r2_storage.save_match_analysis("tournament_123", "match_456", {
    "home_team": "Team A",
    "away_team": "Team B",
    "predictions": {...},
    "xg": {...},
    ...
})

# Load analysis
analysis = r2_storage.load_match_analysis("tournament_123", "match_456")

# List all analyses in tournament
match_ids = r2_storage.list_match_analyses("tournament_123")
```

### Generic JSON Blobs

```python
# Save any JSON with custom key
r2_storage.save_json_blob("matchday_sessions/session_123.json", {
    "fixture_id": "match_456",
    "state": "live",
    ...
})

# Load
data = r2_storage.load_json_blob("matchday_sessions/session_123.json")

# List all under prefix
sessions = r2_storage.list_blobs("matchday_sessions")
```

### Backups

```python
# Full tournament backup
r2_storage.backup_tournament("tournament_123", all_tournament_data)

# Restore from backup
data = r2_storage.restore_tournament("tournament_123")
```

## Integration with Tournament Code

To use R2 for tournament storage, update `web/tournament.py` to call R2 functions:

**Before (local JSON only):**
```python
def _save_tournament(t):
    path = _tournament_path(t["id"])
    path.write_text(json.dumps(t, indent=2))
```

**After (R2 + JSON fallback):**
```python
def _save_tournament(t):
    import r2_storage
    
    # Always save to R2 if enabled
    if r2_storage.is_r2_enabled():
        r2_storage.save_tournament_metadata(t["id"], t)
    
    # Also save to JSON as fallback
    path = _tournament_path(t["id"])
    path.write_text(json.dumps(t, indent=2))
```

**Load tournament (R2 first, then JSON):**
```python
def load_tournament(tournament_id):
    import r2_storage
    
    # Try R2 first
    if r2_storage.is_r2_enabled():
        data = r2_storage.load_tournament_metadata(tournament_id)
        if data:
            return data
    
    # Fall back to JSON
    path = _tournament_path(tournament_id)
    if path.exists():
        return json.loads(path.read_text())
    
    return None
```

## Cost Estimate

For typical tournament usage:

- **Storage**: ~5-10 tournaments × ~50KB each = ~500KB/month = **$0.01/month**
- **Requests**: ~1000 reads + 100 writes/month = **~$0.00001/month**
- **Total**: Less than **$0.02/month**

Free tier: 10GB storage + 1M requests included (more than enough for this project)

## Troubleshooting

### R2 Not Connecting?

Check:
1. Environment variables set correctly in Render (no typos)
2. Credentials valid (test in Cloudflare dashboard)
3. Bucket exists and is accessible
4. Check app logs for connection errors

### How to Test Locally?

Set environment variables locally:
```bash
export R2_ACCOUNT_ID="..."
export R2_ACCESS_KEY_ID="..."
export R2_SECRET_ACCESS_KEY="..."
export R2_BUCKET_NAME="football-simulator"
```

Then run app locally:
```bash
python -m uvicorn web.app:app --reload
```

### Disable R2 (Keep JSON Only)

Simply remove the R2 environment variables from Render. The app will continue working with local JSON files.

## Data Resilience Summary

| Data | Storage | Survives Redeploy? | Survives Instance Change? |
|------|---------|-------------------|--------------------------|
| Match results, lineups | PostgreSQL | ✅ Yes | ✅ Yes |
| Tournament metadata | R2 | ✅ Yes | ✅ Yes |
| Analysis reports | R2 | ✅ Yes | ✅ Yes |
| Match events (scorers) | PostgreSQL | ✅ Yes | ✅ Yes |
| Player profiles | PostgreSQL | ✅ Yes | ✅ Yes |
| Matchday sessions | R2 (optional) | ✅ Yes | ✅ Yes |

**Result**: Everything persists across Render redeploys and instance changes. No more data loss! 🎉

## Next Steps

1. Create Cloudflare R2 bucket
2. Generate API credentials
3. Set environment variables on Render → redeploy
4. Check logs for "R2 Storage: enabled"
5. (Optional) Update tournament.py to use R2 functions
6. Done! Your data now survives everything.
