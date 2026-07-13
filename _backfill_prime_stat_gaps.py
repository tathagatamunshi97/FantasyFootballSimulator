"""Persist runtime `_normalize_stat_gaps` repairs into manual_profiles + seed_seasons.

FBref-era primes often store literal zeros for pass_pct / dribbles / KP / shots90
while Understat already has real volume. Runtime normalize patches those gaps, but
primes should store the repaired values so the board is not forever runtime-dependent.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from models import _normalize_stat_gaps
from manual_profiles import reload_manual_profiles
from seasonal_stats import season_label_from_suffix

ROOT = Path(__file__).resolve().parent
MANUAL = ROOT / "data" / "manual_profiles.json"
SEED = ROOT / "data" / "seed_seasons.json"
REPORT = ROOT / "data" / "_prime_stat_gap_backfill_report.json"

# Fields we want persisted after normalize (board / finishing / on-ball).
PERSIST_KEYS = (
    "shots90",
    "shots_on_target90",
    "key_passes90",
    "dribbles90",
    "dribble_pct",
    "pass_pct",
    "aerials_won90",
    "aerials_lost90",
    "aerials_won_pct",
    "aerials_source",
    "pass_pct_source",
    "dribble_pct_source",
    "shots_source",
    "xg90",
    "xa90",
)

# Elite legend overrides (same spirit as fixed CR7 pass/dribble %) — applied after
# systemic normalize so board-ready values aren't forever on role defaults.
LEGEND_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("Lionel Messi", "14/15"): {
        "pass_pct": 85.0,
        "dribble_pct": 55.0,
        "pass_pct_source": "legend_override",
        "dribble_pct_source": "legend_override",
        # Barca 14/15 Messi ~4+ successful dribbles/90; heuristic understates creators.
        "dribbles90": 4.2,
    },
    ("Neymar", "14/15"): {
        "pass_pct": 81.0,
        "dribble_pct": 54.0,
        "pass_pct_source": "legend_override",
        "dribble_pct_source": "legend_override",
        "dribbles90": 3.8,
        "primary_position": "LW",
        "positions": ["LW", "ST", "AM"],
        "fpl_position": "FWD",
    },
    ("Cristiano Ronaldo", "14/15"): {
        # Keep existing CR7 quality; ensure dribbles filled if still zero.
        "dribbles90": 1.85,
    },
    ("Gonzalo Higuaín", "15/16"): {
        "pass_pct": 78.0,
        "dribble_pct": 48.0,
        "pass_pct_source": "role_default",
        "dribble_pct_source": "role_default",
    },
}

ATTACK_POS = {"ST", "CF", "FW", "RW", "LW", "RM", "LM", "CAM", "AM", "SS"}
TRACK = (
    "shots90",
    "shots_on_target90",
    "key_passes90",
    "dribbles90",
    "pass_pct",
    "dribble_pct",
    "aerials_won90",
)


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_attacker_or_creator(stats: dict[str, Any]) -> bool:
    pos = str(stats.get("primary_position") or "").upper()
    positions = {str(x).upper() for x in (stats.get("positions") or [])}
    fpl = str(stats.get("fpl_position") or "").upper()
    if pos in ATTACK_POS or positions & ATTACK_POS or fpl == "FWD":
        return True
    if fpl == "MID" and (
        _num(stats.get("understat_key_passes90")) >= 1.2
        or _num(stats.get("assists90")) >= 0.2
        or _num(stats.get("key_passes90")) >= 1.2
    ):
        return True
    # Also repair sparse FBref stubs that already have understat shot volume.
    if _num(stats.get("understat_shots90")) > 0 and _num(stats.get("shots90")) <= 0:
        return True
    if _num(stats.get("pass_pct")) <= 0 and _num(stats.get("minutes")) > 0 and fpl != "GK":
        # Broad pass_pct zero repair for non-GK primes/picks
        return True
    return False


def _needs_repair(stats: dict[str, Any]) -> bool:
    if _num(stats.get("minutes")) <= 0:
        return False
    fpl = str(stats.get("fpl_position") or "").upper()
    if fpl == "GK":
        return False
    if _num(stats.get("shots90")) <= 0 and _num(stats.get("understat_shots90")) > 0:
        return True
    if _num(stats.get("key_passes90")) <= 0 and _num(stats.get("understat_key_passes90")) > 0:
        return True
    if _num(stats.get("pass_pct")) <= 0:
        return True
    if stats.get("dribble_pct") in (None, "", 0, 0.0) or _num(stats.get("dribble_pct")) <= 0:
        return True
    if _num(stats.get("dribbles90")) <= 0 and (
        str(stats.get("primary_position") or "").upper() in {"RW", "LW", "RM", "LM"}
        or _num(stats.get("understat_key_passes90")) >= 1.2
    ):
        return True
    if stats.get("aerials_won90") in (None, "") and (
        _num(stats.get("clearances90")) > 0
        or (
            fpl == "FWD"
            and (
                _num(stats.get("shots90")) >= 3.0
                or _num(stats.get("understat_shots90")) >= 3.0
                or _num(stats.get("xg90") or stats.get("npxg90")) >= 0.35
            )
        )
    ):
        return True
    return False


def _round_persist(stats: dict[str, Any]) -> None:
    for k, v in list(stats.items()):
        if not isinstance(v, float):
            continue
        if k.endswith("90") or k.endswith("_pct") or k in {"pass_pct", "dribble_pct", "aerials_won_pct"}:
            stats[k] = round(v, 3)


def _apply_legend_overrides(name: str, suffix: str, stats: dict[str, Any]) -> dict[str, Any]:
    ov = LEGEND_OVERRIDES.get((name, suffix))
    if not ov:
        return {}
    applied = {}
    for k, v in ov.items():
        # Only override zeros / missing, or always for explicit legend quality fields.
        if k in {"pass_pct", "dribble_pct", "dribbles90", "primary_position", "positions", "fpl_position"} or k.endswith("_source"):
            before = stats.get(k)
            stats[k] = v
            if before != v:
                applied[k] = {"before": before, "after": v}
        elif _num(stats.get(k)) <= 0 and _num(v) > 0:
            before = stats.get(k)
            stats[k] = v
            applied[k] = {"before": before, "after": v}
    return applied


def _sync_seed(seed: dict[str, Any], stats: dict[str, Any], name: str, suffix: str) -> None:
    pid = stats.get("player_id")
    if not pid:
        return
    entry = {
        k: v
        for k, v in stats.items()
        if k
        not in {
            "stat_profile",
            "prime_season",
            "manual_profile_type",
            "manual_season_suffix",
            "auto_populate_source",
        }
    }
    entry["player_name"] = name
    entry.setdefault("stat_profile", "seeded_season")
    seed.setdefault(str(int(pid)), {})[suffix] = entry


def backfill(*, dry_run: bool = False) -> dict[str, Any]:
    payload = json.loads(MANUAL.read_text(encoding="utf-8"))
    profiles: list[dict[str, Any]] = list(payload.get("profiles") or [])
    seed: dict[str, Any] = {}
    if SEED.exists():
        seed = json.loads(SEED.read_text(encoding="utf-8"))

    repaired: list[dict[str, Any]] = []
    skipped = 0

    for prof in profiles:
        ptype = str(prof.get("profile_type") or "")
        if ptype not in {"prime", "season pick", "season_pick"}:
            continue
        name = prof["player_name"]
        suffix = str(prof.get("season_suffix") or "")
        stats = prof.get("stats") or {}
        in_legend = (name, suffix) in LEGEND_OVERRIDES
        # Prefer legend upgrades; otherwise only touch sparse attacker/creator gaps.
        if not in_legend:
            if not _is_attacker_or_creator(stats):
                skipped += 1
                continue
            if not _needs_repair(stats) and stats.get("stat_gaps_backfilled"):
                skipped += 1
                continue
            if not _needs_repair(stats):
                # Already filled by prior systemic backfill — still stamp + sync seed once.
                if not dry_run:
                    stats["stat_gaps_backfilled"] = True
                    _sync_seed(seed, stats, name, suffix)
                skipped += 1
                continue

        before = {k: stats.get(k) for k in TRACK}
        repaired_stats = copy.deepcopy(stats)
        _normalize_stat_gaps(repaired_stats)
        legend_applied = _apply_legend_overrides(name, suffix, repaired_stats)
        _round_persist(repaired_stats)

        after = {k: repaired_stats.get(k) for k in TRACK}
        changed = {
            k: {"before": before[k], "after": after[k]}
            for k in TRACK
            if (before[k] or 0) != (after[k] or 0)
        }
        if legend_applied:
            for k, pair in legend_applied.items():
                if k in TRACK or k in {"primary_position", "positions", "fpl_position"}:
                    changed[k] = pair

        if not changed and not legend_applied:
            skipped += 1
            continue

        for k in PERSIST_KEYS:
            if k in repaired_stats:
                stats[k] = repaired_stats[k]
        for k in ("primary_position", "positions", "fpl_position"):
            if k in repaired_stats and repaired_stats[k] != stats.get(k):
                stats[k] = repaired_stats[k]
        stats["stat_gaps_backfilled"] = True

        if not dry_run:
            _sync_seed(seed, stats, name, suffix)

        repaired.append(
            {
                "player": name,
                "profile_type": ptype,
                "season": suffix,
                "changed": changed,
                "legend_overrides": legend_applied,
            }
        )

    report = {
        "repaired_count": len(repaired),
        "skipped": skipped,
        "dry_run": dry_run,
        "repaired": repaired,
        "examples": {
            r["player"]: r
            for r in repaired
            if r["player"]
            in {
                "Lionel Messi",
                "Neymar",
                "Gonzalo Higuaín",
                "Cristiano Ronaldo",
                "Edinson Cavani",
                "Radamel Falcao",
            }
        },
        "prior_systemic_backfill": "See data/_prime_gap_backfill_report.json (60 profiles)",
    }

    if not dry_run:
        payload["profiles"] = profiles
        payload["prime_stat_gap_backfill"] = {
            "repaired_count": len(repaired),
            "note": "Legend overrides + normalize persist; systemic zeros fixed in prior backfill",
        }
        MANUAL.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        SEED.write_text(json.dumps(seed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        reload_manual_profiles()

    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> None:
    dry = "--dry-run" in sys.argv
    report = backfill(dry_run=dry)
    print(f"repaired={report['repaired_count']} skipped={report['skipped']} dry_run={dry}")
    for name in ("Lionel Messi", "Neymar", "Gonzalo Higuaín", "Cristiano Ronaldo"):
        ex = report["examples"].get(name)
        if not ex:
            print(f"  {name}: (no change / not flagged)")
            continue
        print(f"  {name} {ex['season']}:")
        for k, pair in (ex.get("changed") or {}).items():
            print(f"    {k}: {pair['before']} -> {pair['after']}")
    print("Wrote", REPORT)


if __name__ == "__main__":
    main()
