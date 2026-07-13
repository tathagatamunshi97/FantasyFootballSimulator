"""Cloudflare R2 object storage for tournament metadata, analysis files, and large JSON blobs.

This module handles all unstructured file storage (JSON, analysis results, etc.)
Only active when R2_* environment variables are set.
Gracefully falls back to local disk for development.
"""
from __future__ import annotations

import json
import os
from typing import Any
from io import BytesIO

_R2_ENABLED = False
_R2_CLIENT = None

# R2 configuration
_R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
_R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
_R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
_R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "football-simulator")


def _init_r2() -> None:
    """Initialize R2 client if credentials are available."""
    global _R2_ENABLED, _R2_CLIENT

    if not (_R2_ACCOUNT_ID and _R2_ACCESS_KEY_ID and _R2_SECRET_ACCESS_KEY):
        _R2_ENABLED = False
        return

    try:
        import boto3

        # S3-compatible R2 client
        _R2_CLIENT = boto3.client(
            "s3",
            endpoint_url=f"https://{_R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=_R2_ACCESS_KEY_ID,
            aws_secret_access_key=_R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )
        # Test connection
        _R2_CLIENT.head_bucket(Bucket=_R2_BUCKET_NAME)
        _R2_ENABLED = True
    except (ImportError, Exception) as e:
        _R2_ENABLED = False
        _R2_CLIENT = None


# Initialize on module load
_init_r2()


def is_r2_enabled() -> bool:
    """Check if R2 storage is enabled and connected."""
    return _R2_ENABLED


# ============================================================================
# Tournament Metadata Storage
# ============================================================================


def save_tournament_metadata(tournament_id: str, metadata: dict[str, Any]) -> bool:
    """Save tournament metadata to R2. Returns True if saved, False if fell back to local."""
    if not _R2_ENABLED:
        return False

    try:
        key = f"tournaments/{tournament_id}/metadata.json"
        _R2_CLIENT.put_object(
            Bucket=_R2_BUCKET_NAME,
            Key=key,
            Body=json.dumps(metadata, ensure_ascii=False, indent=2),
            ContentType="application/json",
        )
        return True
    except Exception as e:
        print(f"R2: Failed to save tournament metadata: {e}")
        return False


def load_tournament_metadata(tournament_id: str) -> dict[str, Any] | None:
    """Load tournament metadata from R2. Returns None if not found or R2 disabled."""
    if not _R2_ENABLED:
        return None

    try:
        key = f"tournaments/{tournament_id}/metadata.json"
        response = _R2_CLIENT.get_object(Bucket=_R2_BUCKET_NAME, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except Exception:
        return None


def delete_tournament_metadata(tournament_id: str) -> bool:
    """Delete tournament metadata from R2."""
    if not _R2_ENABLED:
        return False

    try:
        key = f"tournaments/{tournament_id}/metadata.json"
        _R2_CLIENT.delete_object(Bucket=_R2_BUCKET_NAME, Key=key)
        return True
    except Exception as e:
        print(f"R2: Failed to delete tournament metadata: {e}")
        return False


def list_tournament_ids() -> list[str]:
    """List all tournament IDs stored in R2."""
    if not _R2_ENABLED:
        return []

    try:
        response = _R2_CLIENT.list_objects_v2(
            Bucket=_R2_BUCKET_NAME,
            Prefix="tournaments/",
            Delimiter="/",
        )
        tournament_ids = []
        for prefix in response.get("CommonPrefixes", []):
            # Extract tournament_id from "tournaments/{tournament_id}/"
            path = prefix["Prefix"]
            tournament_id = path.split("/")[1]
            if tournament_id:
                tournament_ids.append(tournament_id)
        return sorted(tournament_ids)
    except Exception as e:
        print(f"R2: Failed to list tournaments: {e}")
        return []


# ============================================================================
# Match Analysis Storage
# ============================================================================


def save_match_analysis(
    tournament_id: str,
    match_id: str,
    analysis: dict[str, Any],
) -> bool:
    """Save match analysis report to R2. Returns True if successful."""
    if not _R2_ENABLED:
        return False

    try:
        key = f"tournaments/{tournament_id}/analysis/{match_id}.json"
        _R2_CLIENT.put_object(
            Bucket=_R2_BUCKET_NAME,
            Key=key,
            Body=json.dumps(analysis, ensure_ascii=False, indent=2),
            ContentType="application/json",
        )
        return True
    except Exception as e:
        print(f"R2: Failed to save match analysis: {e}")
        return False


def load_match_analysis(tournament_id: str, match_id: str) -> dict[str, Any] | None:
    """Load match analysis from R2. Returns None if not found or R2 disabled."""
    if not _R2_ENABLED:
        return None

    try:
        key = f"tournaments/{tournament_id}/analysis/{match_id}.json"
        response = _R2_CLIENT.get_object(Bucket=_R2_BUCKET_NAME, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except Exception:
        return None


def delete_match_analysis(tournament_id: str, match_id: str) -> bool:
    """Delete match analysis from R2."""
    if not _R2_ENABLED:
        return False

    try:
        key = f"tournaments/{tournament_id}/analysis/{match_id}.json"
        _R2_CLIENT.delete_object(Bucket=_R2_BUCKET_NAME, Key=key)
        return True
    except Exception as e:
        print(f"R2: Failed to delete match analysis: {e}")
        return False


def list_match_analyses(tournament_id: str) -> list[str]:
    """List all match IDs with stored analysis in a tournament."""
    if not _R2_ENABLED:
        return []

    try:
        prefix = f"tournaments/{tournament_id}/analysis/"
        response = _R2_CLIENT.list_objects_v2(
            Bucket=_R2_BUCKET_NAME,
            Prefix=prefix,
        )
        match_ids = []
        for obj in response.get("Contents", []):
            key = obj["Key"]
            # Extract match_id from "tournaments/{tournament_id}/analysis/{match_id}.json"
            match_id = key.split("/")[-1].replace(".json", "")
            if match_id:
                match_ids.append(match_id)
        return sorted(match_ids)
    except Exception as e:
        print(f"R2: Failed to list analyses: {e}")
        return []


# ============================================================================
# Generic JSON Blob Storage
# ============================================================================


def save_json_blob(key: str, data: dict[str, Any] | list) -> bool:
    """Save any JSON data to R2 with a custom key path.

    Key examples:
    - "matchday_sessions/session_123.json"
    - "experiments/exp_456.json"
    - "reports/report_abc.json"
    """
    if not _R2_ENABLED:
        return False

    try:
        full_key = key if key.startswith("/") == False else key[1:]
        _R2_CLIENT.put_object(
            Bucket=_R2_BUCKET_NAME,
            Key=full_key,
            Body=json.dumps(data, ensure_ascii=False, indent=2),
            ContentType="application/json",
        )
        return True
    except Exception as e:
        print(f"R2: Failed to save blob '{key}': {e}")
        return False


def load_json_blob(key: str) -> dict[str, Any] | list | None:
    """Load any JSON data from R2 with a custom key path."""
    if not _R2_ENABLED:
        return None

    try:
        full_key = key if key.startswith("/") == False else key[1:]
        response = _R2_CLIENT.get_object(Bucket=_R2_BUCKET_NAME, Key=full_key)
        data = response["Body"].read().decode("utf-8")
        return json.loads(data)
    except Exception:
        return None


def delete_json_blob(key: str) -> bool:
    """Delete a JSON blob from R2."""
    if not _R2_ENABLED:
        return False

    try:
        full_key = key if key.startswith("/") == False else key[1:]
        _R2_CLIENT.delete_object(Bucket=_R2_BUCKET_NAME, Key=full_key)
        return True
    except Exception as e:
        print(f"R2: Failed to delete blob '{key}': {e}")
        return False


def list_blobs(prefix: str) -> list[str]:
    """List all keys under a prefix in R2."""
    if not _R2_ENABLED:
        return []

    try:
        full_prefix = prefix if prefix.endswith("/") else prefix + "/"
        response = _R2_CLIENT.list_objects_v2(
            Bucket=_R2_BUCKET_NAME,
            Prefix=full_prefix,
        )
        return sorted([obj["Key"] for obj in response.get("Contents", [])])
    except Exception as e:
        print(f"R2: Failed to list blobs under '{prefix}': {e}")
        return []


# ============================================================================
# Backup/Export Functions
# ============================================================================


def backup_tournament(tournament_id: str, all_data: dict[str, Any]) -> bool:
    """Backup entire tournament (metadata + all analyses) in one go."""
    if not _R2_ENABLED:
        return False

    try:
        key = f"backups/tournaments/{tournament_id}/full-backup.json"
        _R2_CLIENT.put_object(
            Bucket=_R2_BUCKET_NAME,
            Key=key,
            Body=json.dumps(all_data, ensure_ascii=False, indent=2),
            ContentType="application/json",
        )
        return True
    except Exception as e:
        print(f"R2: Failed to backup tournament: {e}")
        return False


def restore_tournament(tournament_id: str) -> dict[str, Any] | None:
    """Restore entire tournament from backup."""
    if not _R2_ENABLED:
        return None

    try:
        key = f"backups/tournaments/{tournament_id}/full-backup.json"
        response = _R2_CLIENT.get_object(Bucket=_R2_BUCKET_NAME, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except Exception:
        return None
