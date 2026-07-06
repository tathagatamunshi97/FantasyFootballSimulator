"""Persist per-team saved lineups from squad hub."""
from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from formation_fit import FORMATION_SLOTS
from web.experiments import validate_team_payload

ROOT = Path(__file__).resolve().parent.parent
LINEUPS_PATH = ROOT / "data" / "team_lineups.json"

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_all() -> dict[str, Any]:
    if not LINEUPS_PATH.exists():
        return {}
    try:
        return json.loads(LINEUPS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(data: dict[str, Any]) -> None:
    LINEUPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LINEUPS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


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


def get_team_lineup(team_name: str) -> dict[str, Any] | None:
    with _lock:
        store = _load_all()
    key = _resolve_key(team_name, store)
    if not key:
        return None
    return copy.deepcopy(store[key])


def has_saved_lineup(team_name: str) -> bool:
    return get_team_lineup(team_name) is not None


def save_team_lineup(team_name: str, config: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist a team's saved lineup configuration."""
    name = team_name.strip()
    if not name:
        raise ValueError("Team name is required.")

    formation = (config.get("formation") or "4-3-3").strip()
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

    record = {
        "team_name": name,
        "formation": formation,
        "lineup": lineup,
        "prime_player": prime,
        "peak_season": peak,
        "updated_at": _now(),
    }

    with _lock:
        store = _load_all()
        store[name] = record
        _save_all(store)
    return copy.deepcopy(record)


def apply_saved_lineup(team_dict: dict[str, Any]) -> dict[str, Any]:
    """Merge saved squad-hub lineup into a sheet-loaded team payload if available."""
    name = (team_dict.get("name") or "").strip()
    if not name:
        return team_dict
    saved = get_team_lineup(name)
    if not saved:
        return team_dict

    out = copy.deepcopy(team_dict)
    out["formation"] = saved.get("formation") or out.get("formation")
    out["lineup"] = copy.deepcopy(saved.get("lineup") or out.get("lineup"))
    out["prime_player"] = saved.get("prime_player") or ""
    out["peak_season"] = copy.deepcopy(saved.get("peak_season") or {"player": "", "season": ""})

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
        rows.append(
            {
                "team_name": name,
                "formation": cfg.get("formation"),
                "updated_at": cfg.get("updated_at"),
                "player_count": len([r for r in cfg.get("lineup", []) if (r.get("player") or "").strip()]),
            }
        )
    rows.sort(key=lambda r: (r.get("team_name") or "").lower())
    return rows
