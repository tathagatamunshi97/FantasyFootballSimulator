"""Offline audit: which tournament / sheet players lack a manual prime."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from manual_profiles import list_manual_profiles, lookup_manual_prime, reload_manual_profiles
from player_names import (
    KNOWN_DISPLAY_NAMES,
    KNOWN_PRIME_SEASON_SUFFIX,
    known_sofascore_id,
)
from seasonal_stats import build_prime_stats_dict
from sofascore_client import StatsStore

DATA = Path("data")
OUT = DATA / "_prime_gap_audit.json"


def _collect_sheet_players() -> dict[str, list[str]]:
    try:
        from google_sheets_teams import list_sheet_teams

        teams = list_sheet_teams()
    except Exception as exc:
        print(f"sheet load failed: {exc}")
        return {}
    out: dict[str, list[str]] = {}
    for t in teams:
        name = t.get("name") or "?"
        players = [str(p).strip() for p in (t.get("players") or []) if p and str(p).strip()]
        out[name] = players
    return out


def main() -> None:
    reload_manual_profiles()
    profiles = list_manual_profiles()
    primes = [p for p in profiles if p.get("profile_type") == "prime"]
    prime_names = sorted({p["player_name"] for p in primes})

    sheet = _collect_sheet_players()
    all_players: set[str] = set()
    for ps in sheet.values():
        all_players.update(ps)

    # lineups / experiments primes
    current_primes: set[str] = set()
    tl = json.loads((DATA / "team_lineups.json").read_text(encoding="utf-8"))
    for rec in tl.values():
        if isinstance(rec, dict) and rec.get("prime_player"):
            current_primes.add(rec["prime_player"].strip())

    exp_dir = DATA / "experiments"
    if exp_dir.exists():
        for f in exp_dir.glob("*.json"):
            d = json.loads(f.read_text(encoding="utf-8"))
            for side in ("team_a", "team_b"):
                t = d.get(side) or {}
                if isinstance(t, dict) and t.get("prime_player"):
                    current_primes.add(str(t["prime_player"]).strip())

    missing_sheet = []
    for p in sorted(all_players):
        if not lookup_manual_prime(p, cache_only=True):
            pid = known_sofascore_id(p)
            missing_sheet.append(
                {
                    "player": p,
                    "pid": pid,
                    "known_suffix": KNOWN_PRIME_SEASON_SUFFIX.get(pid) if pid else None,
                }
            )

    # verify critical names cache_only
    store = StatsStore()
    critical = sorted(
        current_primes
        | {KNOWN_DISPLAY_NAMES.get(pid, f"id:{pid}") for pid in KNOWN_PRIME_SEASON_SUFFIX}
        | set(prime_names)
    )
    # keep critical list manageable: current primes + known + a sample of sheet missing with known suffix
    verify_names = sorted(
        current_primes
        | {r["player"] for r in missing_sheet if r.get("known_suffix")}
        | {
            KNOWN_DISPLAY_NAMES[pid]
            for pid in KNOWN_PRIME_SEASON_SUFFIX
            if pid in KNOWN_DISPLAY_NAMES
        }
    )
    # also verify all existing primes by name
    verify_names = sorted(set(verify_names) | set(prime_names) | current_primes)

    verify = []
    for n in verify_names:
        try:
            c, d, lab = build_prime_stats_dict(n, store, cache_only=True)
            verify.append(
                {
                    "raw": n,
                    "ok": True,
                    "canon": c,
                    "season": lab,
                    "source": d.get("data_source"),
                    "manual": d.get("manual_profile_type"),
                }
            )
        except Exception as exc:
            verify.append({"raw": n, "ok": False, "error": str(exc)})

    report = {
        "manual_prime_count": len(primes),
        "manual_prime_names": prime_names,
        "sheet_team_count": len(sheet),
        "sheet_player_count": len(all_players),
        "sheet_missing_prime_count": len(missing_sheet),
        "sheet_missing_prime": missing_sheet,
        "sheet_missing_with_known_suffix": [r for r in missing_sheet if r.get("known_suffix")],
        "current_prime_players": sorted(current_primes),
        "verify": verify,
        "verify_failures": [r for r in verify if not r.get("ok")],
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"manual primes: {len(primes)}")
    print(f"sheet teams: {len(sheet)} players: {len(all_players)}")
    print(f"sheet missing prime: {len(missing_sheet)}")
    print(f"missing with known suffix: {len(report['sheet_missing_with_known_suffix'])}")
    print(f"verify failures: {len(report['verify_failures'])}")
    for r in report["verify_failures"][:30]:
        print(" FAIL", r)
    for r in report["sheet_missing_with_known_suffix"][:30]:
        print(" NEED", r)
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
