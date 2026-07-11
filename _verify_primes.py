"""Verify prime coverage and cache_only lookups."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from manual_profiles import list_manual_profiles, lookup_manual_prime, reload_manual_profiles
from player_names import KNOWN_DISPLAY_NAMES, KNOWN_PRIME_SEASON_SUFFIX
from seasonal_stats import build_prime_stats_dict
from sofascore_client import StatsStore

OUT = Path("data/_verify_primes_out.json")


def main() -> None:
    reload_manual_profiles()
    profiles = list_manual_profiles()
    primes = [p for p in profiles if p.get("profile_type") == "prime"]
    picks = [p for p in profiles if p.get("profile_type") == "season_pick"]

    picks_missing = []
    for p in picks:
        if not lookup_manual_prime(p["player_name"], cache_only=True):
            picks_missing.append({"player": p["player_name"], "season": p["season_suffix"]})

    known_status = []
    for pid, suf in sorted(KNOWN_PRIME_SEASON_SUFFIX.items()):
        name = KNOWN_DISPLAY_NAMES.get(pid, f"id:{pid}")
        hit = lookup_manual_prime(name, cache_only=True)
        if not hit:
            for p in primes:
                if p.get("stats", {}).get("player_id") == pid:
                    hit = True
                    name = p["player_name"]
                    break
        known_status.append(
            {"pid": pid, "name": name, "suffix": suf, "ok": bool(hit)}
        )

    checks = [
        "Cole Palmer",
        "Rodri",
        "Casemiro",
        "Neymar",
        "Riyad Mahrez",
        "John Stones",
        "Mesut Ozil",
        "Mesut Özil",
        "N'Golo Kanté",
        "Cristiano Ronaldo",
        "Modric",
        "Luka Modrić",
        "Kevin De Bruyne",
        "Achraf Hakimi",
        "Alexis Sanchez",
        "Angel Di Maria",
        "Edinson Cavani",
        "Diego Godin",
        "Sergio Ramos",
        "Jamie Vardy",
        "Francesco Acerbi",
    ]
    store = StatsStore()
    lookup_results = []
    for n in checks:
        try:
            c, d, lab = build_prime_stats_dict(n, store, cache_only=True)
            lookup_results.append(
                {
                    "raw": n,
                    "ok": True,
                    "canon": c,
                    "season": lab,
                    "source": d.get("data_source"),
                    "manual_type": d.get("manual_profile_type"),
                }
            )
            print(f"OK {n} -> {c} {lab} src={d.get('data_source')}")
        except Exception as exc:
            lookup_results.append({"raw": n, "ok": False, "error": str(exc)})
            print(f"FAIL {n}: {exc}")

    report = {
        "prime_count": len(primes),
        "pick_count": len(picks),
        "prime_names": sorted(f"{p['player_name']}|{p['season_suffix']}" for p in primes),
        "picks_missing_prime": picks_missing,
        "known_status": known_status,
        "known_missing": [r for r in known_status if not r["ok"]],
        "lookup_results": lookup_results,
        "lookup_failures": [r for r in lookup_results if not r["ok"]],
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nprimes={len(primes)} picks={len(picks)} picks_missing={len(picks_missing)}")
    print(f"known_missing={len(report['known_missing'])} lookup_fail={len(report['lookup_failures'])}")
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
