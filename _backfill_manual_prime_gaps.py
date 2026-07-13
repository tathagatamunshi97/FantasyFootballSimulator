"""Persist _normalize_stat_gaps repairs into manual_profiles.json + seed_seasons.json.

FBref-era primes often store literal 0 for pass_pct / dribble_pct / KP / shots90 while
Understat mirrors already sit on the same record. Runtime normalize patched some of this,
but board lookups should not depend on that forever.

Usage:
  python _backfill_manual_prime_gaps.py
  python _backfill_manual_prime_gaps.py --dry-run
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from models import _normalize_stat_gaps
from manual_profiles import MANUAL_PROFILES_FILE, reload_manual_profiles

DATA_DIR = Path(__file__).resolve().parent / "data"
SEED_FILE = DATA_DIR / "seed_seasons.json"
REPORT_FILE = DATA_DIR / "_prime_gap_backfill_report.json"

# Fields we intentionally write back when normalize fills/repairs them.
PERSIST_FIELDS = (
    "shots90",
    "shots_on_target90",
    "xg90",
    "xa90",
    "npxg90",
    "key_passes90",
    "dribbles90",
    "dribble_pct",
    "pass_pct",
    "aerials_won90",
    "aerials_lost90",
    "aerials_won_pct",
    "understat_xg90",
    "understat_xa90",
    "understat_key_passes90",
    "understat_shots90",
    "shots_source",
    "pass_pct_source",
    "dribble_pct_source",
    "dribbles_source",
    "aerials_source",
    "sot_source",
)

BOARD_FIELDS = (
    "shots90",
    "shots_on_target90",
    "goals90",
    "xg90",
    "xa90",
    "key_passes90",
    "dribbles90",
    "pass_pct",
    "dribble_pct",
    "aerials_won90",
)

# Elite legend quality (same spirit as fixed CR7) — applied after normalize so
# board-ready dribbles/pass% aren't stuck on generic role defaults.
LEGEND_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("Lionel Messi", "14/15"): {
        "pass_pct": 85.0,
        "dribble_pct": 55.0,
        "dribbles90": 4.2,
        "pass_pct_source": "legend_override",
        "dribble_pct_source": "legend_override",
        "dribbles_source": "legend_override",
    },
    ("Neymar", "14/15"): {
        "pass_pct": 81.0,
        "dribble_pct": 54.0,
        "dribbles90": 3.8,
        "primary_position": "LW",
        "positions": ["LW", "ST", "AM"],
        "fpl_position": "FWD",
        "pass_pct_source": "legend_override",
        "dribble_pct_source": "legend_override",
        "dribbles_source": "legend_override",
    },
    ("Cristiano Ronaldo", "14/15"): {
        "dribbles90": 1.85,
        "dribbles_source": "legend_override",
    },
}


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _profile_type_key(raw: str) -> str | None:
    key = str(raw or "").strip().lower().replace("-", " ").replace("_", " ")
    if key in {"prime", "prime season"}:
        return "prime"
    if key in {"season pick", "seasonpick", "peak season"}:
        return "season_pick"
    return None


def _atomic_write_json(path: Path, payload: Any) -> None:
    content = json.dumps(payload, indent=2, ensure_ascii=False)
    tmp = path.with_suffix(path.suffix + ".tmp")
    last_err: OSError | None = None
    for attempt in range(3):
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(0.75 * (attempt + 1))
        except OSError as exc:
            if getattr(exc, "winerror", None) in (5, 32) and attempt < 2:
                last_err = exc
                time.sleep(0.75 * (attempt + 1))
                continue
            raise
    if last_err is not None:
        raise last_err


def _snapshot(stats: dict[str, Any]) -> dict[str, Any]:
    return {k: stats.get(k) for k in BOARD_FIELDS}


def _incomplete_reasons(stats: dict[str, Any]) -> list[str]:
    fpl = str(stats.get("fpl_position") or "").upper()
    reasons: list[str] = []
    if fpl == "GK":
        return reasons
    goals = _num(stats.get("goals90"))
    sot = _num(stats.get("shots_on_target90"))
    shots = _num(stats.get("shots90"))
    if goals >= 0.4 and (sot <= 0 or sot < goals * 0.85):
        reasons.append("impossible_sot_vs_goals")
    if shots <= 0 and (_num(stats.get("understat_shots90")) > 0 or goals >= 0.25):
        reasons.append("shots90_missing")
    for field in ("pass_pct", "dribble_pct"):
        if _num(stats.get(field)) <= 0:
            reasons.append(f"{field}_zero")
    # Creators / attackers should have KP when Understat has it.
    if _num(stats.get("key_passes90")) <= 0 and _num(stats.get("understat_key_passes90")) > 0:
        reasons.append("kp_not_promoted")
    if _num(stats.get("xa90")) <= 0 and _num(stats.get("understat_xa90")) > 0:
        reasons.append("xa_not_promoted")
    if fpl in {"FWD", "MID"} and _num(stats.get("dribbles90")) <= 0:
        reasons.append("dribbles90_zero")
    if fpl in {"FWD", "DEF"} and _num(stats.get("aerials_won90")) <= 0:
        reasons.append("aerials_missing")
    return reasons


def _apply_and_collect(
    stats: dict[str, Any],
    *,
    player_name: str = "",
    season_suffix: str = "",
) -> tuple[dict[str, Any], dict[str, tuple[Any, Any]], list[str]]:
    before = _snapshot(stats)
    repaired = copy.deepcopy(stats)
    _normalize_stat_gaps(repaired)
    legend = LEGEND_OVERRIDES.get((player_name, season_suffix)) or {}
    for key, value in legend.items():
        repaired[key] = value
    changes: dict[str, tuple[Any, Any]] = {}
    for field in (*PERSIST_FIELDS, "primary_position", "positions", "fpl_position"):
        old = stats.get(field)
        new = repaired.get(field)
        if old != new and new is not None:
            changes[field] = (old, new)
            stats[field] = new
    after_reasons = _incomplete_reasons(stats)
    return before, changes, after_reasons if after_reasons else []


def backfill(*, dry_run: bool = False) -> dict[str, Any]:
    payload = json.loads(MANUAL_PROFILES_FILE.read_text(encoding="utf-8"))
    profiles: list[dict[str, Any]] = payload.get("profiles") or []
    seed: dict[str, Any] = {}
    if SEED_FILE.exists():
        seed = json.loads(SEED_FILE.read_text(encoding="utf-8"))

    repaired_profiles: list[dict[str, Any]] = []
    still_incomplete: list[dict[str, Any]] = []
    examples: dict[str, Any] = {}
    spot = ("Lionel Messi", "Neymar", "Gonzalo Higuaín", "Cristiano Ronaldo", "Ayoub El Kaabi")

    prime_or_pick = 0
    for profile in profiles:
        ptype = _profile_type_key(str(profile.get("profile_type", "")))
        if ptype is None:
            continue
        prime_or_pick += 1
        stats = profile.get("stats") or {}
        if not isinstance(stats, dict):
            continue
        name = str(profile.get("player_name") or "")
        season = str(profile.get("season_suffix") or "")
        before, changes, after_reasons = _apply_and_collect(
            stats, player_name=name, season_suffix=season
        )
        if changes:
            repaired_profiles.append(
                {
                    "player": name,
                    "profile_type": ptype,
                    "season": season,
                    "changed_fields": sorted(changes.keys()),
                    "before": before,
                    "after": _snapshot(stats),
                    "changes": {k: {"from": v[0], "to": v[1]} for k, v in changes.items()},
                }
            )
        if after_reasons:
            still_incomplete.append(
                {
                    "player": name,
                    "profile_type": ptype,
                    "season": season,
                    "fpl": stats.get("fpl_position"),
                    "reasons": after_reasons,
                    "data_source": stats.get("data_source") or stats.get("auto_populate_source"),
                }
            )
        if name in spot:
            examples[f"{name}|{ptype}|{season}"] = {
                "before": before,
                "after": _snapshot(stats),
                "changed": sorted(changes.keys()),
                "still": after_reasons,
            }

        # Mirror into seed_seasons when we have a player_id.
        pid = stats.get("player_id")
        if pid is not None and season and changes:
            pid_key = str(int(pid))
            seed.setdefault(pid_key, {})
            entry = seed[pid_key].get(season)
            if isinstance(entry, dict):
                for field, (_old, new) in changes.items():
                    entry[field] = new
            else:
                # Create a thin seed mirror from repaired stats.
                seed[pid_key][season] = {
                    k: stats.get(k)
                    for k in (
                        "team",
                        "league",
                        "primary_position",
                        "fpl_position",
                        "positions",
                        "minutes",
                        "games",
                        "starts",
                        "player_id",
                        "player_name",
                        "data_source",
                        "stat_profile",
                        *PERSIST_FIELDS,
                        "goals90",
                        "assists90",
                        "rating",
                        "seasons_used",
                        "teams_by_season",
                        "season_profile",
                        "understat_matched",
                        "fbref_matched",
                    )
                    if k in stats
                }
                seed[pid_key][season]["player_name"] = name
                seed[pid_key][season]["stat_profile"] = "seeded_season"

    report = {
        "prime_or_pick_count": prime_or_pick,
        "repaired_count": len(repaired_profiles),
        "still_incomplete_count": len(still_incomplete),
        "repaired": repaired_profiles,
        "still_incomplete": still_incomplete,
        "spot_examples": examples,
        "dry_run": dry_run,
        "notes": [
            "Accuracy sourced from existing Understat mirrors on each profile, "
            "SoT/shots consistency repairs, and role defaults for pass_pct/"
            "dribble_pct/dribbles/aerials when FBref left literal zeros.",
            "Peak seasons left unchanged when they already match ROUND3_SEASON_PICKS "
            "/ team_lineups (e.g. Higuaín 15/16).",
        ],
    }

    if not dry_run:
        payload["profiles"] = profiles
        payload["prime_gap_backfill_report"] = {
            "repaired_count": len(repaired_profiles),
            "still_incomplete_count": len(still_incomplete),
        }
        _atomic_write_json(MANUAL_PROFILES_FILE, payload)
        _atomic_write_json(SEED_FILE, seed)
        reload_manual_profiles()

    _atomic_write_json(REPORT_FILE, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = backfill(dry_run=args.dry_run)
    print(
        f"profiles={report['prime_or_pick_count']} "
        f"repaired={report['repaired_count']} "
        f"still_incomplete={report['still_incomplete_count']} "
        f"dry_run={args.dry_run}"
    )
    for key, ex in (report.get("spot_examples") or {}).items():
        print(f"\nSPOT {key}")
        print(f"  before={ex['before']}")
        print(f"  after ={ex['after']}")
        print(f"  changed={ex['changed']}")
        if ex["still"]:
            print(f"  still={ex['still']}")
    if report["still_incomplete"]:
        print("\nStill incomplete (sample):")
        for row in report["still_incomplete"][:25]:
            print(
                f"  {row['player']} [{row['profile_type']} {row['season']}] "
                f"{row['reasons']} src={row.get('data_source')}"
            )
    print(f"\nWrote {REPORT_FILE}")


if __name__ == "__main__":
    main()
