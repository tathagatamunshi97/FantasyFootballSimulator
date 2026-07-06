"""Estimate missing Understat per-90 stats from Sofascore/FBref cache fields."""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models import _infer_fpl_position

UNDERSTAT_FIELDS = (
    "understat_xg90",
    "understat_xa90",
    "understat_key_passes90",
    "understat_shots90",
)

DEFAULT_RATIOS: dict[str, float] = {
    "xg": 1.098,
    "xa": 1.117,
    "kp": 0.998,
    "sh": 0.999,
}

DEFAULT_RATING_BY_FPL: dict[str, float] = {
    "GK": 6.5,
    "DEF": 6.45,
    "MID": 6.5,
    "FWD": 6.55,
}

_SHOTS_PER_GOAL: dict[str, float] = {
    "GK": 0.0,
    "DEF": 5.0,
    "MID": 4.0,
    "FWD": 3.5,
}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fpl_bucket(data: dict[str, Any]) -> str:
    fpl = data.get("fpl_position")
    if fpl:
        return str(fpl)
    return _infer_fpl_position(str(data.get("primary_position", "MF")))


def _understat_fully_missing(data: dict[str, Any]) -> bool:
    if data.get("understat_matched"):
        return False
    return all(_num(data.get(field)) <= 0 for field in UNDERSTAT_FIELDS)


def _field_missing(data: dict[str, Any], field: str) -> bool:
    return _num(data.get(field)) <= 0


def compute_calibration_ratios(players: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Median Sofascore→Understat ratios from players with real Understat matches."""
    buckets: dict[str, list[float]] = {"xg": [], "xa": [], "kp": [], "sh": []}
    for data in players.values():
        if not data.get("understat_matched"):
            continue
        xg = _num(data.get("xg90")) or _num(data.get("npxg90"))
        uxg = _num(data.get("understat_xg90"))
        if xg > 0 and uxg > 0:
            buckets["xg"].append(uxg / xg)
        xa = _num(data.get("xa90"))
        uxa = _num(data.get("understat_xa90"))
        if xa > 0 and uxa > 0:
            buckets["xa"].append(uxa / xa)
        kp = _num(data.get("key_passes90"))
        ukp = _num(data.get("understat_key_passes90"))
        if kp > 0 and ukp > 0:
            buckets["kp"].append(ukp / kp)
        sh = _num(data.get("shots90"))
        ush = _num(data.get("understat_shots90"))
        if sh > 0 and ush > 0:
            buckets["sh"].append(ush / sh)

    ratios = dict(DEFAULT_RATIOS)
    for key, values in buckets.items():
        if values:
            ratios[key] = statistics.median(values)
    return ratios


def estimate_understat_stats(
    data: dict[str, Any],
    *,
    ratios: dict[str, float] | None = None,
) -> bool:
    """
    Fill missing Understat fields from Sofascore/FBref stats and position heuristics.
    Returns True when any field was estimated.
    """
    if data.get("understat_matched"):
        return False

    cal = ratios or DEFAULT_RATIOS
    fpl = _fpl_bucket(data)
    changed = False

    if fpl == "GK" and _understat_fully_missing(data):
        for field in UNDERSTAT_FIELDS:
            if _field_missing(data, field):
                data[field] = 0.0
        data["understat_estimated"] = True
        return True

    xg_src = _num(data.get("xg90")) or _num(data.get("npxg90"))
    if _field_missing(data, "understat_xg90") and xg_src > 0:
        data["understat_xg90"] = xg_src * cal["xg"]
        changed = True

    xa_src = _num(data.get("xa90"))
    if _field_missing(data, "understat_xa90"):
        if xa_src > 0:
            data["understat_xa90"] = xa_src * cal["xa"]
            changed = True
        elif _num(data.get("assists90")) > 0:
            data["understat_xa90"] = _num(data.get("assists90")) * 0.35
            changed = True

    kp_src = _num(data.get("key_passes90"))
    if _field_missing(data, "understat_key_passes90"):
        if kp_src > 0:
            data["understat_key_passes90"] = kp_src * cal["kp"]
            changed = True
        elif _num(data.get("assists90")) > 0:
            data["understat_key_passes90"] = _num(data.get("assists90")) * 1.8
            changed = True

    sh_src = _num(data.get("shots90"))
    if _field_missing(data, "understat_shots90"):
        if sh_src > 0:
            data["understat_shots90"] = sh_src * cal["sh"]
            changed = True
        elif _num(data.get("goals90")) > 0:
            data["understat_shots90"] = _num(data.get("goals90")) * _SHOTS_PER_GOAL.get(fpl, 4.0)
            changed = True
        elif _num(data.get("understat_xg90")) > 0:
            xg_per_shot = 0.08 if fpl == "DEF" else (0.10 if fpl == "MID" else 0.12)
            data["understat_shots90"] = _num(data.get("understat_xg90")) / xg_per_shot
            changed = True

    if changed:
        data["understat_estimated"] = True
    return changed


def ensure_minimum_rating(data: dict[str, Any]) -> bool:
    """Assign a sensible default rating when minutes exist but rating is zero."""
    rating = _num(data.get("rating"))
    minutes = _num(data.get("minutes"))
    if rating > 0 or minutes <= 0:
        return False
    fpl = _fpl_bucket(data)
    data["rating"] = DEFAULT_RATING_BY_FPL.get(fpl, 6.5)
    data["rating_estimated"] = True
    return True


def fill_stat_gaps(
    data: dict[str, Any],
    *,
    ratios: dict[str, float] | None = None,
) -> bool:
    """Estimate Understat gaps and minimum rating; returns True if anything changed."""
    changed = estimate_understat_stats(data, ratios=ratios)
    changed = ensure_minimum_rating(data) or changed
    return changed


def apply_estimates_to_cache(
    cache: dict[str, Any],
    *,
    sheet_names: set[str] | None = None,
) -> dict[str, Any]:
    """
    Apply estimation to cache players. When sheet_names is set, only those entries
    get minimum-rating enforcement; Understat estimation runs for all missing entries.
    """
    players = cache.get("players") or {}
    ratios = compute_calibration_ratios(players)
    understat_fixed = 0
    rating_fixed = 0
    names_fixed: list[str] = []

    for name, data in players.items():
        if not isinstance(data, dict):
            continue
        had_gaps = not data.get("understat_matched") and any(
            _field_missing(data, f) for f in UNDERSTAT_FIELDS
        )
        before_rating = _num(data.get("rating")) <= 0 and _num(data.get("minutes")) > 0

        us_changed = estimate_understat_stats(data, ratios=ratios)
        rt_changed = False
        if sheet_names is None or name in sheet_names or any(
            n.lower() == name.lower() for n in (sheet_names or set())
        ):
            rt_changed = ensure_minimum_rating(data)

        if us_changed or (had_gaps and not any(_field_missing(data, f) for f in UNDERSTAT_FIELDS)):
            understat_fixed += 1
            names_fixed.append(name)
        if rt_changed or (before_rating and _num(data.get("rating")) > 0):
            rating_fixed += 1

    meta = cache.setdefault("meta", {})
    meta["understat_estimation_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["understat_estimation_ratios"] = {k: round(v, 4) for k, v in ratios.items()}
    meta["understat_estimated_count"] = understat_fixed
    meta["rating_estimated_count"] = rating_fixed

    return {
        "ratios": ratios,
        "understat_fixed": understat_fixed,
        "rating_fixed": rating_fixed,
        "names_fixed": names_fixed,
    }


def main() -> int:
    from sofascore_client import load_cache, save_cache

    root = Path(__file__).resolve().parent
    cache_path = root / "data" / "player_stats_cache.json"
    cache = load_cache(cache_path)
    report = apply_estimates_to_cache(cache)
    save_cache(cache, cache_path)
    print(f"Understat estimated: {report['understat_fixed']} players")
    print(f"Rating defaults applied: {report['rating_fixed']} players")
    print(f"Calibration ratios: {report['ratios']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
