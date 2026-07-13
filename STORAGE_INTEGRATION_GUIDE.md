# Storage Integration Guide

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Your App (Render)                     │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌──────────────────┐    ┌──────────────────────────┐   │
│  │   PostgreSQL DB  │    │   Cloudflare R2 Storage  │   │
│  │  (Structured)    │    │   (Unstructured Files)   │   │
│  │                  │    │                          │   │
│  │ • Match results  │    │ • Tournament metadata    │   │
│  │ • Lineups        │    │ • Analysis reports       │   │
│  │ • Profiles       │    │ • Match analysis JSONs   │   │
│  │ • Seed seasons   │    │ • Matchday sessions      │   │
│  │ • Match events   │    │ • Experiment results     │   │
│  └──────────────────┘    └──────────────────────────┘   │
│         ▲                          ▲                      │
│         │                          │                      │
│         └──────────────┬───────────┘                      │
│                        │                                  │
│              ┌──────────────────────┐                    │
│              │   Application Code   │                    │
│              │   (db.py, r2.py)     │                    │
│              └──────────────────────┘                    │
│                        ▲                                  │
│                        │                                  │
│              ┌──────────────────────┐                    │
│              │   Fallback: Local    │                    │
│              │   JSON Files (dev)   │                    │
│              └──────────────────────┘                    │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

## What Goes Where?

### PostgreSQL (Structured Data)
✅ **Store in PostgreSQL:**
- Match results (goals, assists) — from `match_results`, `match_events` tables
- Team lineups and finalization status
- Manual player profiles (primes, season picks)
- Seed season overrides
- Experiments and simulation metadata

❌ **Don't store in PostgreSQL:**
- Large JSON blobs (analysis reports, tournament structure)
- File-like data (tournament metadata, analysis files)
- Data that changes frequently as a unit

### R2 Storage (Files & Blobs)
✅ **Store in R2:**
- Tournament metadata (groups, bracket, fixtures, settings)
- Match analysis reports (pre-match, post-match)
- Matchday session snapshots
- Experiment result reports
- Tournament backups
- Anything that's a JSON file-like object

❌ **Don't store in R2:**
- Data that needs transactional consistency
- Small structured records better suited to DB
- Data that needs frequent partial updates

### Local JSON (Development Only)
- Use locally when R2/DB not configured
- Graceful fallback for testing
- No setup required

## Integration Examples

### 1. Tournament Metadata (R2)

**Current (local JSON):**
```python
# web/tournament.py
def _tournament_path(tournament_id):
    return TOURNAMENTS_DIR / f"{tournament_id}.json"

def load_tournament(tournament_id):
    path = _tournament_path(tournament_id)
    if path.exists():
        return json.loads(path.read_text())
    return None

def _save_tournament(t):
    path = _tournament_path(t["id"])
    path.write_text(json.dumps(t, indent=2))
```

**Updated (R2 + JSON fallback):**
```python
import r2_storage

def load_tournament(tournament_id):
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

def _save_tournament(t):
    # Save to R2 if enabled
    if r2_storage.is_r2_enabled():
        r2_storage.save_tournament_metadata(t["id"], t)
    
    # Always save to JSON as backup
    path = _tournament_path(t["id"])
    path.write_text(json.dumps(t, indent=2))

def delete_tournament(tournament_id):
    # Delete from R2
    if r2_storage.is_r2_enabled():
        r2_storage.delete_tournament_metadata(tournament_id)
    
    # Delete from JSON
    path = _tournament_path(tournament_id)
    if path.exists():
        path.unlink()
    
    return {"ok": True, "tournament_id": tournament_id}

def list_tournaments():
    # List from R2 if enabled (more authoritative)
    if r2_storage.is_r2_enabled():
        ids = r2_storage.list_tournament_ids()
        if ids:
            tournaments = []
            for tid in ids:
                t = load_tournament(tid)
                if t:
                    tournaments.append(tournament_for_api(t))
            return tournaments
    
    # Fall back to JSON directory
    tournaments = []
    if TOURNAMENTS_DIR.exists():
        for path in TOURNAMENTS_DIR.glob("*.json"):
            try:
                t = json.loads(path.read_text())
                tournaments.append(tournament_for_api(t))
            except Exception:
                pass
    return tournaments
```

### 2. Match Analysis (R2)

**Current (local JSON):**
```python
ANALYSIS_DIR = ROOT / "data" / "analyses"

def save_analysis(tournament_id, match_id, analysis):
    path = ANALYSIS_DIR / f"{tournament_id}_{match_id}.json"
    path.write_text(json.dumps(analysis, indent=2))

def load_analysis(tournament_id, match_id):
    path = ANALYSIS_DIR / f"{tournament_id}_{match_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None
```

**Updated (R2 + JSON fallback):**
```python
import r2_storage

def save_analysis(tournament_id, match_id, analysis):
    # Save to R2
    if r2_storage.is_r2_enabled():
        r2_storage.save_match_analysis(tournament_id, match_id, analysis)
    
    # Also save to JSON
    path = ANALYSIS_DIR / f"{tournament_id}_{match_id}.json"
    path.write_text(json.dumps(analysis, indent=2))

def load_analysis(tournament_id, match_id):
    # Try R2 first
    if r2_storage.is_r2_enabled():
        analysis = r2_storage.load_match_analysis(tournament_id, match_id)
        if analysis:
            return analysis
    
    # Fall back to JSON
    path = ANALYSIS_DIR / f"{tournament_id}_{match_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    
    return None
```

### 3. Matchday Session (R2 or Local)

**Current (local JSON):**
```python
# web/matchday_session.py
SESSION_FILE = ROOT / "data" / "matchday_session.json"

def active_status():
    if not SESSION_FILE.exists():
        return {"active": False}
    try:
        return json.loads(SESSION_FILE.read_text())
    except Exception:
        return {"active": False}

def _save_session(session):
    SESSION_FILE.write_text(json.dumps(session, indent=2))
```

**Updated (R2):**
```python
import r2_storage

def active_status():
    # Try R2 first
    if r2_storage.is_r2_enabled():
        session = r2_storage.load_json_blob("matchday_sessions/active.json")
        if session:
            return session
    
    # Fall back to JSON
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text())
        except Exception:
            pass
    
    return {"active": False}

def _save_session(session):
    # Save to R2
    if r2_storage.is_r2_enabled():
        r2_storage.save_json_blob("matchday_sessions/active.json", session)
    
    # Always save to JSON
    SESSION_FILE.write_text(json.dumps(session, indent=2))
```

## Database (Structured) vs R2 (Files) Examples

### Example: Storing a Match

```python
# MATCH RESULT (Structured → PostgreSQL)
import db
db.save_match_result(
    "tournament_123",
    "match_456",
    "Team A",
    "Team B",
    2,  # home_goals
    1,  # away_goals
    stage="group",
    group_key="A",
)

# MATCH SCORERS (Structured → PostgreSQL)
db.record_match_event("tournament_123", "match_456", "Team A", "Player 1", "goal", minute=20, assister="Player 2")
db.record_match_event("tournament_123", "match_456", "Team A", "Player 3", "goal", minute=65)
db.record_match_event("tournament_123", "match_456", "Team B", "Player 4", "goal", minute=45)

# MATCH ANALYSIS (Unstructured → R2)
import r2_storage
r2_storage.save_match_analysis("tournament_123", "match_456", {
    "home_team": "Team A",
    "away_team": "Team B",
    "xg_home": 1.8,
    "xg_away": 0.6,
    "predictions": {"home_win": 0.72, "draw": 0.18, "away_win": 0.10},
    "key_stats": {...},
    "narrative": "Team A dominated possession..."
})
```

### Example: Querying Match Data

```python
# Get match result (PostgreSQL)
result = db.get_match_result("tournament_123", "match_456")
print(f"Score: {result['home_team']} {result['home_goals']}-{result['away_goals']} {result['away_team']}")

# Get scorers (PostgreSQL)
events = db.get_match_events("tournament_123", "match_456")
for event in events:
    if event["event_type"] == "goal":
        assister_str = f" ({event['assister']})" if event["assister"] else ""
        print(f"Goal: {event['player']}{assister_str}")

# Get analysis (R2)
analysis = r2_storage.load_match_analysis("tournament_123", "match_456")
print(f"Expected goals: {analysis['xg_home']} - {analysis['xg_away']}")
```

## Deployment Checklist

- [ ] **PostgreSQL**: Set `DATABASE_URL` in Render environment
- [ ] **R2 Storage**: Create Cloudflare R2 bucket
- [ ] **R2 Credentials**: Generate API token in Cloudflare
- [ ] **R2 Environment**: Set `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` in Render
- [ ] **Dependencies**: Ensure `psycopg2-binary>=2.9` and `boto3>=1.26` in `requirements.txt`
- [ ] **Test Locally**: Run app locally with environment vars set
- [ ] **Deploy**: Push code to Render, redeploy
- [ ] **Verify**: Check logs for "PostgreSQL enabled" and "R2 Storage: enabled"
- [ ] **Migrate**: Run `python migrate_to_db.py` if you have existing data to move

## Performance Considerations

- **PostgreSQL**: ~10-100ms for queries, good for frequent updates
- **R2**: ~100-300ms for reads (cached locally after first read), good for occasional access
- **Local JSON**: ~1-10ms, only for development

**Strategy**: Cache frequently-accessed R2 data in memory after first load. Load tournament metadata once at startup, not on every request.

## Disaster Recovery

**Full backup (everything):**
```bash
# Export PostgreSQL data
pg_dump $DATABASE_URL > backup.sql

# Backup R2 files
# (Cloudflare dashboard → R2 → Download bucket, or use CLI)

# Backup local JSON files
tar -czf data_backup.tar.gz data/
```

**Restore:**
```bash
# Restore PostgreSQL
psql $DATABASE_URL < backup.sql

# Restore R2 (via dashboard or CLI)

# Restore JSON
tar -xzf data_backup.tar.gz
```

## Monitoring

Check storage status via Render logs or API:

```python
import db
import r2_storage

print(f"PostgreSQL: {'enabled' if db.is_db_enabled() else 'disabled'}")
print(f"R2 Storage: {'enabled' if r2_storage.is_r2_enabled() else 'disabled'}")
```

Monitor R2 usage via Cloudflare dashboard → R2 → Analytics.
