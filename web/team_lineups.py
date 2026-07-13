"""Persist per-team saved lineups from squad hub."""
from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from formation_fit import DEFAULT_FORMATION, FORMATION_SLOTS, normalize_formation
from web.experiments import validate_team_payload

ROOT = Path(__file__).resolve().parent.parent
LINEUPS_PATH = ROOT / "data" / "team_lineups.json"

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_all() -> dict[str, Any]:
    """Load all lineups from database (if enabled) or JSON file."""
    try:
        import db
        if db.is_db_enabled():
            return db.load_all_team_lineups()
    except (ImportError, Exception):
        pass

    # Fall back to JSON file
    if not LINEUPS_PATH.exists():
        return {}
    try:
        return json.loads(LINEUPS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(data: dict[str, Any]) -> None:
    """Save all lineups to database (if enabled) and JSON file."""
    # Always save to JSON (local fallback and development)
    LINEUPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LINEUPS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Also save to database if enabled (on Render)
    try:
        import db
        if db.is_db_enabled():
            for team_name, lineup_data in data.items():
                db.save_team_lineup(team_name, lineup_data)
    except (ImportError, Exception):
        pass


def _resolve_key(team_name: str, store: dict[str, Any]) -> str | None:
    name = team_name.strip()
    if not name:
        return None
    if name in store:
        return name
    lower = name.lower()
    for key in store:
        if key.lower() == lower:
            return key
    return None


def _lineup_config_from_record(record: dict[str, Any], *, snapshot: bool = False) -> dict[str, Any]:
    source = record.get("finalized_snapshot") if snapshot else record
    return {
        "formation": source.get("formation") or record.get("formation"),
        "lineup": copy.deepcopy(source.get("lineup") or record.get("lineup") or []),
        "prime_player": source.get("prime_player") if snapshot else record.get("prime_player", ""),
        "peak_season": copy.deepcopy(
            source.get("peak_season") if snapshot else record.get("peak_season") or {"player": "", "season": ""}
        ),
    }


def get_team_lineup(team_name: str) -> dict[str, Any] | None:
    with _lock:
        store = _load_all()
    key = _resolve_key(team_name, store)
    if not key:
        return None
    return copy.deepcopy(store[key])


def has_saved_lineup(team_name: str) -> bool:
    return get_team_lineup(team_name) is not None


def _build_record_payload(name: str, config: dict[str, Any]) -> dict[str, Any]:
    formation = normalize_formation((config.get("formation") or DEFAULT_FORMATION).strip())
    if formation not in FORMATION_SLOTS:
        raise ValueError(f"Unsupported formation: {formation}")

    lineup = config.get("lineup") or []
    prime = (config.get("prime_player") or "").strip()
    peak = config.get("peak_season") or {}
    if not (peak.get("player") or "").strip():
        peak = {"player": "", "season": ""}

    team_payload = {
        "name": name,
        "formation": formation,
        "lineup": lineup,
        "bench": config.get("bench") or [],
        "prime_player": prime,
        "peak_season": peak,
    }
    errors = validate_team_payload(team_payload, name)
    if errors:
        raise ValueError("; ".join(errors))

    return {
        "team_name": name,
        "formation": formation,
        "lineup": lineup,
        "prime_player": prime,
        "peak_season": peak,
    }


def lineup_status(team_name: str, *, immediate_round_key: str | None = None) -> dict[str, Any]:
    """Return finalized / lock state for squad hub."""
    saved = get_team_lineup(team_name)
    if immediate_round_key is None:
        try:
            from web.tournament import get_team_immediate_round

            immediate_round_key = get_team_immediate_round(team_name).get("round_key")
        except Exception:
            # A transient tournament-lookup failure must never block a lineup save;
            # worst case the lock state is stale until the next successful check.
            immediate_round_key = None

    finalized = bool(saved and saved.get("finalized"))
    finalized_round = (saved or {}).get("finalized_round")
    locked = bool(
        finalized
        and finalized_round
        and immediate_round_key
        and finalized_round == immediate_round_key
    )
    return {
        "finalized": finalized,
        "finalized_at": (saved or {}).get("finalized_at"),
        "finalized_round": finalized_round,
        "immediate_round_key": immediate_round_key,
        "locked": locked,
        "can_edit": not locked,
    }


def save_team_lineup(team_name: str, config: dict[str, Any], *, allow_locked: bool = False) -> dict[str, Any]:
    """Validate and persist a team's saved lineup configuration."""
    name = team_name.strip()
    if not name:
        raise ValueError("Team name is required.")

    if not allow_locked:
        status = lineup_status(name)
        if status["locked"]:
            raise ValueError(
                "Lineup is finalized for the current round. "
                "Wait until matchday completes before editing."
            )

    record = _build_record_payload(name, config)
    record["updated_at"] = _now()

    with _lock:
        store = _load_all()
        existing = store.get(name) or {}
        record["finalized"] = existing.get("finalized", False)
        record["finalized_at"] = existing.get("finalized_at")
        record["finalized_round"] = existing.get("finalized_round")
        record["finalized_round_label"] = existing.get("finalized_round_label")
        record["finalized_snapshot"] = existing.get("finalized_snapshot")
        store[name] = record
        _save_all(store)
    return copy.deepcopy(record)


def finalize_team_lineup(
    team_name: str,
    config: dict[str, Any] | None = None,
    *,
    round_key: str,
    round_label: str | None = None,
) -> dict[str, Any]:
    """Save (optional) and lock lineup for the given tournament round."""
    name = team_name.strip()
    if not name:
        raise ValueError("Team name is required.")
    if not round_key:
        raise ValueError("Round key is required.")

    status = lineup_status(name, immediate_round_key=round_key)
    if status["locked"]:
        raise ValueError("Squad is already finalized for this round.")

    if config is not None:
        record = save_team_lineup(name, config, allow_locked=True)
    else:
        record = get_team_lineup(name)
        if not record:
            raise ValueError("Save your lineup before finalizing.")

    snapshot = _lineup_config_from_record(record)
    record = {
        **record,
        **snapshot,
        "finalized": True,
        "finalized_at": _now(),
        "finalized_round": round_key,
        "finalized_round_label": round_label or round_key,
        "finalized_snapshot": snapshot,
        "updated_at": _now(),
    }

    with _lock:
        store = _load_all()
        store[name] = record
        _save_all(store)
    return copy.deepcopy(record)


def _clear_finalize_fields(record: dict[str, Any]) -> bool:
    """Clear finalize lock fields on a record. Returns True if anything changed."""
    if not record.get("finalized") and not record.get("finalized_round"):
        return False
    record["finalized"] = False
    record["finalized_at"] = None
    record["finalized_round"] = None
    record["finalized_round_label"] = None
    record["finalized_snapshot"] = None
    record["updated_at"] = _now()
    return True


def admin_unfinalize_team_lineup(team_name: str) -> dict[str, Any] | None:
    """Admin clears finalized lock (keeps saved lineup)."""
    name = team_name.strip()
    with _lock:
        store = _load_all()
        key = _resolve_key(name, store)
        if not key:
            return None
        record = store[key]
        _clear_finalize_fields(record)
        store[key] = record
        _save_all(store)
        return copy.deepcopy(record)


def clear_all_finalize_locks() -> int:
    """Clear finalize locks for every team (keeps saved lineups). Returns count cleared."""
    with _lock:
        store = _load_all()
        cleared = 0
        for key, record in store.items():
            if _clear_finalize_fields(record):
                store[key] = record
                cleared += 1
        if cleared:
            _save_all(store)
        return cleared


def apply_team_lineup(
    team_dict: dict[str, Any],
    *,
    round_key: str | None = None,
) -> dict[str, Any]:
    """Merge saved or finalized lineup into a sheet-loaded team payload."""
    name = (team_dict.get("name") or "").strip()
    if not name:
        return team_dict
    saved = get_team_lineup(name)
    if not saved:
        return team_dict

    use_snapshot = bool(
        round_key
        and saved.get("finalized")
        and saved.get("finalized_round") == round_key
        and saved.get("finalized_snapshot")
    )
    cfg = _lineup_config_from_record(saved, snapshot=use_snapshot)

    out = copy.deepcopy(team_dict)
    out["formation"] = cfg.get("formation") or out.get("formation")
    out["lineup"] = copy.deepcopy(cfg.get("lineup") or out.get("lineup"))
    out["prime_player"] = cfg.get("prime_player") or ""
    out["peak_season"] = copy.deepcopy(cfg.get("peak_season") or {"player": "", "season": ""})

    meta = out.get("sheet_meta") or {}
    roster = meta.get("full_roster") or meta.get("roster_players") or []
    lineup_players = {(r.get("player") or "").strip() for r in out.get("lineup", [])}
    if roster:
        out["bench"] = [p for p in roster if p and p not in lineup_players]
    return out


def apply_saved_lineup(team_dict: dict[str, Any]) -> dict[str, Any]:
    """Merge saved squad-hub lineup (not finalized snapshot) into team payload."""
    return apply_team_lineup(team_dict, round_key=None)


def apply_lineup_config(team_dict: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Merge an arbitrary lineup config (e.g. draft from test endpoint)."""
    out = copy.deepcopy(team_dict)
    out["formation"] = config.get("formation") or out.get("formation")
    out["lineup"] = copy.deepcopy(config.get("lineup") or out.get("lineup"))
    out["prime_player"] = config.get("prime_player") or ""
    out["peak_season"] = copy.deepcopy(config.get("peak_season") or {"player": "", "season": ""})

    meta = out.get("sheet_meta") or {}
    roster = meta.get("full_roster") or meta.get("roster_players") or []
    lineup_players = {(r.get("player") or "").strip() for r in out.get("lineup", [])}
    if roster:
        out["bench"] = [p for p in roster if p and p not in lineup_players]
    return out


def list_team_lineups() -> list[dict[str, Any]]:
    with _lock:
        store = _load_all()
    rows = []
    for name, cfg in store.items():
        status = lineup_status(name)
        rows.append(
            {
                "team_name": name,
                "formation": cfg.get("formation"),
                "updated_at": cfg.get("updated_at"),
                "player_count": len([r for r in cfg.get("lineup", []) if (r.get("player") or "").strip()]),
                "finalized": status["finalized"],
                "finalized_at": cfg.get("finalized_at"),
                "finalized_round": cfg.get("finalized_round"),
                "finalized_round_label": cfg.get("finalized_round_label"),
                "locked": status["locked"],
            }
        )
    rows.sort(key=lambda r: (r.get("team_name") or "").lower())
    return rows
