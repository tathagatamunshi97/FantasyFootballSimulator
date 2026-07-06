"""Derive multi-position profiles from played roles across data sources."""
from __future__ import annotations

from collections import Counter
from typing import Any

from models import FplPosition, SOFASCORE_POSITION_TO_PRIMARY

GRANULAR_POSITIONS = frozenset(
    {"GK", "CB", "LB", "RB", "WB", "DM", "CM", "AM", "RW", "LW", "ST"}
)

# Prefer specific roles over generic midfield/defence buckets when picking primary.
PRIMARY_PRIORITY: dict[str, int] = {
    "GK": 100,
    "ST": 90,
    "RW": 88,
    "LW": 88,
    "AM": 82,
    "DM": 80,
    "LB": 78,
    "RB": 78,
    "WB": 76,
    "CB": 74,
    "CM": 60,
}

SOFASCORE_BUCKET_POSITIONS: dict[str, list[str]] = {
    "G": ["GK"],
    "D": ["CB", "LB", "RB"],
    "M": ["CM", "DM", "AM"],
    "F": ["ST", "RW", "LW"],
}


def _norm_pos(value: str) -> str:
    text = str(value or "").strip().upper()
    aliases = {
        "GK": "GK",
        "G": "GK",
        "DF": "CB",
        "DEF": "CB",
        "FB": "RB",
        "MF": "CM",
        "MID": "CM",
        "FW": "ST",
        "FWD": "ST",
        "CF": "ST",
        "RM": "RW",
        "LM": "LW",
    }
    return aliases.get(text, text)


def normalize_positions(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for raw in values or []:
        pos = _norm_pos(raw)
        if pos in GRANULAR_POSITIONS and pos not in out:
            out.append(pos)
    return out


def parse_fbref_positions(pos_raw: str) -> list[str]:
    """Expand FBref comma-separated pos field (e.g. 'MF,DF', 'DF,MF') into granular roles."""
    text = str(pos_raw or "M").upper().replace(" ", "")
    tokens = [t for t in text.split(",") if t]
    if not tokens:
        tokens = ["M"]

    positions: list[str] = []
    for tok in tokens:
        if "GK" in tok:
            positions.append("GK")
        elif tok in {"RW", "RM"} or "RW" in tok:
            positions.append("RW")
        elif tok in {"LW", "LM"} or "LW" in tok:
            positions.append("LW")
        elif any(tag in tok for tag in ("FW", "ST", "CF")):
            positions.append("ST")
        elif "DM" in tok:
            positions.append("DM")
        elif "AM" in tok:
            positions.append("AM")
        elif "CM" in tok:
            positions.append("CM")
        elif tok == "MF":
            positions.append("CM")
        elif "LB" in tok:
            positions.append("LB")
        elif "RB" in tok:
            positions.append("RB")
        elif "WB" in tok:
            positions.append("WB")
        elif "CB" in tok or tok == "DF":
            positions.append("CB")
        else:
            positions.append("CM")

    token_set = set(tokens)
    if "MF" in token_set and "DF" in token_set:
        df_idx = tokens.index("DF") if "DF" in tokens else -1
        mf_idx = tokens.index("MF") if "MF" in tokens else -1
        if df_idx >= 0 and mf_idx >= 0 and df_idx < mf_idx:
            # Fullback who sometimes pushes into midfield (e.g. Reece James "DF,MF").
            positions = ["RB" if p == "CB" else p for p in positions]
            positions = ["CM" if p == "DM" else p for p in positions]
        else:
            # Holding midfielder who can drop into defence (e.g. Rodri "MF,DF").
            positions = ["DM" if p == "CM" else p for p in positions]

    return list(dict.fromkeys(positions))


def infer_fpl_from_primary(primary: str, positions: list[str] | None = None) -> FplPosition:
    pos_set = {primary.upper()} | {p.upper() for p in (positions or [])}
    if "GK" in pos_set:
        return "GK"
    if pos_set & {"RW", "LW", "ST", "CF", "FW"}:
        if primary.upper() in {"RW", "LW", "ST", "CF", "FW"}:
            return "FWD"
        if not pos_set & {"CM", "DM", "AM", "MF", "MID"}:
            return "FWD"
        if primary.upper() in {"RW", "LW", "ST"}:
            return "FWD"
    if pos_set <= {"CB", "LB", "RB", "WB", "DF", "DEF"} or primary.upper() in {"CB", "LB", "RB", "WB", "DF", "DEF"}:
        return "DEF"
    if primary.upper() in {"RW", "LW", "ST", "CF", "FW"}:
        return "FWD"
    if primary.upper() in {"CB", "LB", "RB", "WB", "DF", "DEF"}:
        return "DEF"
    return "MID"


def refine_defensive_line_positions(stats: dict[str, Any], positions: list[str]) -> list[str]:
    """Disambiguate generic CB from fullback using per-90 profile."""
    if not positions:
        return positions

    pos_set = set(positions)
    if not pos_set & {"CB", "LB", "RB", "WB"}:
        return positions

    clearances = float(stats.get("clearances90") or 0)
    tackles = float(stats.get("tackles90") or 0)
    key_passes = float(stats.get("key_passes90") or 0)
    assists = float(stats.get("assists90") or 0)
    dribbles = float(stats.get("dribbles90") or 0)

    centre_back_profile = clearances >= 3.5 and key_passes < 1.2
    fullback_profile = key_passes >= 0.75 or assists >= 0.12 or dribbles >= 0.9
    midfield_anchors = pos_set & {"DM", "CM", "AM"}

    out = list(positions)
    if centre_back_profile and "CB" not in out:
        out.insert(0, "CB")
    if fullback_profile and "CB" in out and not midfield_anchors:
        out = [p for p in out if p != "CB"]
        if "LB" not in out and "RB" not in out and "WB" not in out:
            out.extend(["LB", "RB"])
    elif fullback_profile and pos_set == {"CB"}:
        out = [p for p in out if p != "CB"]
        if "LB" not in out and "RB" not in out and "WB" not in out:
            out.extend(["LB", "RB"])
    return list(dict.fromkeys(out))


def pick_primary_position(weights: Counter[str]) -> str:
    if not weights:
        return "CM"

    def score(pos: str) -> tuple[float, int]:
        return (weights[pos], PRIMARY_PRIORITY.get(pos, 50))

    return max(weights.keys(), key=score)


def _add_signals(
    sink: Counter[str],
    positions: list[str],
    weight: float,
) -> None:
    for pos in normalize_positions(positions):
        sink[pos] += weight


def _positions_from_stats_blob(blob: dict[str, Any], weight: float) -> tuple[list[str], float]:
    positions = normalize_positions(blob.get("positions"))
    primary = _norm_pos(blob.get("primary_position", ""))
    if primary and primary not in positions:
        positions = [primary, *positions]
    if not positions and primary:
        positions = [primary]
    positions = refine_defensive_line_positions(blob, positions)
    return positions, weight


def collect_position_signals(
    *,
    cache_entry: dict[str, Any],
    manual_stats: list[dict[str, Any]] | None = None,
    seed_entry: dict[str, Any] | None = None,
    seed_season_entries: list[dict[str, Any]] | None = None,
    fbref_season_hits: list[tuple[str, dict[str, Any]]] | None = None,
    sofascore_bucket: str | None = None,
    known_override: dict[str, Any] | None = None,
) -> Counter[str]:
    """Aggregate weighted position evidence from all available sources."""
    weights: Counter[str] = Counter()

    if known_override:
        override_positions, w = _positions_from_stats_blob(known_override, 12.0)
        _add_signals(weights, override_positions, w)

    for blob, w in (
        (cache_entry, 2.0),
        *((stats, 4.0) for stats in (manual_stats or [])),
        *((stats, 3.5) for stats in (seed_season_entries or [])),
    ):
        if not blob:
            continue
        positions, weight = _positions_from_stats_blob(blob, w)
        _add_signals(weights, positions, weight)

    if seed_entry:
        positions, weight = _positions_from_stats_blob(seed_entry, 3.0)
        _add_signals(weights, positions, weight)

    for season_label, hit in fbref_season_hits or []:
        pos_raw = hit.get("pos_raw") or hit.get("pos") or ""
        if pos_raw:
            parsed = parse_fbref_positions(str(pos_raw))
        else:
            parsed = normalize_positions(hit.get("positions"))
        parsed = refine_defensive_line_positions({**cache_entry, **hit}, parsed)
        season_weight = 5.0
        if cache_entry.get("seasons_used"):
            if season_label == cache_entry["seasons_used"][-1]:
                season_weight = 7.0
            elif season_label in cache_entry["seasons_used"]:
                season_weight = 6.0
        _add_signals(weights, parsed, season_weight)

    if sofascore_bucket and sofascore_bucket.upper() in SOFASCORE_BUCKET_POSITIONS:
        bucket_positions = list(SOFASCORE_BUCKET_POSITIONS[sofascore_bucket.upper()])
        refined = refine_defensive_line_positions(cache_entry, bucket_positions)
        _add_signals(weights, refined, 1.0)

    return weights


def derive_position_profile(
    weights: Counter[str],
    *,
    fallback_primary: str = "CM",
) -> tuple[str, FplPosition, list[str]]:
    if not weights:
        primary = _norm_pos(fallback_primary)
        positions = [primary]
        return primary, infer_fpl_from_primary(primary, positions), positions

    primary = pick_primary_position(weights)
    ordered = sorted(
        weights.keys(),
        key=lambda p: (-weights[p], -PRIMARY_PRIORITY.get(p, 50)),
    )
    positions = list(dict.fromkeys(ordered))
    if primary not in positions:
        positions.insert(0, primary)
    fpl = infer_fpl_from_primary(primary, positions)
    return primary, fpl, positions


def enrich_entry_positions(
    entry: dict[str, Any],
    *,
    manual_stats: list[dict[str, Any]] | None = None,
    seed_entry: dict[str, Any] | None = None,
    seed_season_entries: list[dict[str, Any]] | None = None,
    fbref_season_hits: list[tuple[str, dict[str, Any]]] | None = None,
    sofascore_bucket: str | None = None,
    known_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return primary_position, fpl_position, positions for a cache entry."""
    weights = collect_position_signals(
        cache_entry=entry,
        manual_stats=manual_stats,
        seed_entry=seed_entry,
        seed_season_entries=seed_season_entries,
        fbref_season_hits=fbref_season_hits,
        sofascore_bucket=sofascore_bucket,
        known_override=known_override,
    )
    fallback = entry.get("primary_position") or SOFASCORE_POSITION_TO_PRIMARY.get(sofascore_bucket or "", "CM")
    primary, fpl, positions = derive_position_profile(weights, fallback_primary=str(fallback))
    if known_override and known_override.get("primary_position"):
        primary = _norm_pos(str(known_override["primary_position"]))
        if known_override.get("fpl_position"):
            fpl = known_override["fpl_position"]  # type: ignore[assignment]
        else:
            fpl = infer_fpl_from_primary(primary, positions)
        override_positions = normalize_positions(known_override.get("positions"))
        positions = list(dict.fromkeys([primary, *override_positions, *positions]))
    positions = refine_defensive_line_positions(entry, positions)
    if known_override and known_override.get("positions"):
        override_only = normalize_positions(known_override.get("positions"))
        positions = list(dict.fromkeys([primary, *override_only, *[p for p in positions if p in override_only or weights.get(p, 0) >= 4.0]]))
    if primary == "CB" and "LB" in positions and "RB" in positions:
        if float(entry.get("key_passes90") or 0) >= 0.75:
            primary = "LB" if weights.get("LB", 0) >= weights.get("RB", 0) else "RB"
    ranked = sorted(
        positions,
        key=lambda p: (-weights.get(p, 0), -PRIMARY_PRIORITY.get(p, 50)),
    )
    trimmed = [p for p in ranked if p == primary or weights.get(p, 0) >= 3.5][:6]
    positions = list(dict.fromkeys([primary, *trimmed]))
    return {
        "primary_position": primary,
        "fpl_position": fpl,
        "positions": positions,
    }


def positions_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    for key in ("primary_position", "fpl_position", "positions"):
        if before.get(key) != after.get(key):
            return True
    return False
