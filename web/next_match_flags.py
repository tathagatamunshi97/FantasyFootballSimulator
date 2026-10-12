"""One-shot, next-match player flags (explicit admin request).

A flag is *armed* by an entry below and stays armed until the flagged player
actually gets the outcome in a completed match, at which point it is recorded
as consumed and never fires again. A match the player isn't in (or that never
completes) leaves it armed, so "next match" means the next one he plays.

Arming lives in code on purpose: the consumed record is the only mutable
state, persisted R2 + disk like the matchday checkpoints, so a redeploy can't
silently re-arm a flag that already fired. To re-arm a player, change their
token (any new string).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from player_names import normalize_key

ROOT = Path(__file__).resolve().parent.parent
_CONSUMED_FILE = ROOT / "data" / "next_match_flags_consumed.json"
_R2_KEY = "next_match_flags/consumed.json"
_lock = threading.Lock()

# player -> token. Guaranteed straight red in the player's next match.
FORCED_RED: dict[str, str] = {
    "Michael Olise": "2026-10-12",
}

_FORCED_RED_BY_KEY = {normalize_key(n): (n, tok) for n, tok in FORCED_RED.items()}


def _load_consumed() -> set[str]:
    try:
        import r2_storage

        if r2_storage.is_r2_enabled():
            data = r2_storage.load_json_blob(_R2_KEY)
            if isinstance(data, dict):
                return set(data.get("consumed") or [])
    except Exception:
        pass
    try:
        if _CONSUMED_FILE.exists():
            data = json.loads(_CONSUMED_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return set(data.get("consumed") or [])
    except (OSError, json.JSONDecodeError):
        pass
    return set()


def _save_consumed(consumed: set[str]) -> None:
    payload = {"consumed": sorted(consumed)}
    try:
        import r2_storage

        if r2_storage.is_r2_enabled():
            r2_storage.save_json_blob(_R2_KEY, payload)
    except Exception:
        pass
    try:
        _CONSUMED_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONSUMED_FILE.write_text(json.dumps(payload), encoding="utf-8")
    except OSError as exc:
        print(f"next_match_flags: failed to persist consumed flags: {exc}")


def _flag_id(name: str, token: str) -> str:
    return f"forced_red:{name}:{token}"


def is_forced_red(player_name: str) -> bool:
    hit = _FORCED_RED_BY_KEY.get(normalize_key(str(player_name or "").strip()))
    if not hit:
        return False
    with _lock:
        return _flag_id(*hit) not in _load_consumed()


def consume_after_match(events: Any) -> list[str]:
    """Mark forced-red flags consumed for any flagged player who was sent off
    in this completed match. Returns the player names consumed."""
    if not isinstance(events, list):
        return []
    sent_off = {
        normalize_key(str(e.get("player") or "").strip())
        for e in events
        if isinstance(e, dict) and e.get("type") == "red_card" and e.get("player")
    }
    done: list[str] = []
    with _lock:
        consumed = _load_consumed()
        for key in sent_off:
            hit = _FORCED_RED_BY_KEY.get(key)
            if hit and _flag_id(*hit) not in consumed:
                consumed.add(_flag_id(*hit))
                done.append(hit[0])
        if done:
            _save_consumed(consumed)
    return done
