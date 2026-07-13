#!/usr/bin/env python3
"""Export all Google Sheet players with engine-resolved stats + gap flags."""
from __future__ import annotations

import csv
import json
import sys
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CSV_OUT = DATA / "sheet_players_audit_export.csv"
JSON_OUT = DATA / "sheet_players_audit_export.json"

ATTACKER_POS = {"ST", "CF", "LW", "RW", "FW", "FWD", "SS", "LF", "RF"}
ATTACKER_FPL = {"FWD"}


def _load_sheet_or_fallback() -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Return (rosters_by_key, source_label, meta)."""
    meta: dict[str, Any] = {}
    try:
        from google_sheets_teams import (
            fetch_teams_dataframe,
            parse_teams_from_dataframe,
            spreadsheet_config,
            sheet_csv_url,
        )

        sheet_id, gid = spreadsheet_config()
        meta["spreadsheet_id"] = sheet_id
        meta["gid"] = gid
        meta["csv_url"] = sheet_csv_url(sheet_id, gid)
        df = fetch_teams_dataframe()
        rosters = parse_teams_from_dataframe(df)
        if not rosters:
            raise RuntimeError("Sheet returned zero teams")
        return rosters, "live_google_sheet", meta
    except Exception as exc:
        meta["sheet_error"] = f"{type(exc).__name__}: {exc}"
        print(f"Live sheet failed: {exc}", flush=True)

    # Fallback: reconstruct from team_lineups + any sheet-shaped cache in lineups
    from google_sheets_teams import SheetRoster

    lineups_path = DATA / "team_lineups.json"
    if not lineups_path.exists():
        raise RuntimeError("No live sheet and no team_lineups.json fallback")

    raw = json.loads(lineups_path.read_text(encoding="utf-8"))
    rosters: dict[str, SheetRoster] = {}
    for team_name, rec in raw.items():
        if not isinstance(rec, dict):
            continue
        players: list[str] = []
        for row in rec.get("lineup") or []:
            p = (row.get("player") or "").strip()
            if p and p not in players:
                players.append(p)
        for p in rec.get("bench") or []:
            p = str(p).strip()
            if p and p not in players:
                players.append(p)
        if not players:
            continue
        key = team_name.strip().lower()
        rosters[key] = SheetRoster(name=team_name, players=players, budgets=[])
    if not rosters:
        raise RuntimeError("Fallback team_lineups had no players")
    return rosters, "team_lineups_fallback", meta


def _role_slot_for(team: dict[str, Any], player: str) -> tuple[str, str]:
    """Return (role, slot) where role is XI / bench / roster."""
    for row in team.get("lineup") or []:
        if (row.get("player") or "").strip() == player:
            return "XI", str(row.get("slot") or "")
    bench = {str(p).strip() for p in (team.get("bench") or []) if p}
    if player in bench:
        return "bench", ""
    meta = team.get("sheet_meta") or {}
    full = {str(p).strip() for p in (meta.get("full_roster") or []) if p}
    if player in full:
        return "roster", ""
    return "roster", ""


def _same_player(a: str, b: str) -> bool:
    from player_names import names_loosely_match

    return bool(a and b and (a == b or names_loosely_match(a, b)))


def _stat_source(
    team: dict[str, Any],
    raw_name: str,
    resolved_name: str,
    overrides_side: dict[str, Any] | None,
) -> tuple[str, str]:
    """Return (source_kind, season_label)."""
    prime = (team.get("prime_player") or "").strip()
    peak = team.get("peak_season") or {}
    peak_player = (peak.get("player") or "").strip()
    peak_season = (peak.get("season") or "").strip()

    if (prime and _same_player(raw_name, prime)) or (prime and _same_player(resolved_name, prime)):
        season = ""
        if overrides_side and overrides_side.get("prime"):
            season = str(overrides_side["prime"].get("season") or "")
        return "prime", season
    if peak_player and (
        _same_player(raw_name, peak_player) or _same_player(resolved_name, peak_player)
    ):
        season = peak_season
        if overrides_side and overrides_side.get("peak_season"):
            season = str(overrides_side["peak_season"].get("season") or season)
        return "peak_season", season
    return "blend_cache", ""


def _raw_profile_dict(
    store: Any,
    *,
    raw_name: str,
    resolved_name: str,
    source_kind: str,
    season: str,
) -> dict[str, Any] | None:
    """Underlying profile before PlayerStats / gap-normalize (for residual flags)."""
    import copy

    from seasonal_stats import (
        build_prime_stats_dict,
        build_season_stats_dict,
        normalize_season_input,
    )

    try:
        if source_kind == "prime":
            _c, data, _lab = build_prime_stats_dict(raw_name, store, cache_only=True)
            return copy.deepcopy(data)
        if source_kind == "peak_season" and season:
            suffix = normalize_season_input(season)
            _c, data, _lab = build_season_stats_dict(
                raw_name, suffix, store, cache_only=True
            )
            return copy.deepcopy(data)
    except Exception:
        pass

    cached = store._find_cached_player_name(resolved_name) or store._find_cached_player_name(
        raw_name
    )
    if not cached:
        return None
    entry = (store._cache.get("players") or {}).get(cached)
    return copy.deepcopy(entry) if entry else None


def _gap_flags(
    ps: Any | None,
    *,
    unresolved: bool = False,
    raw_data: dict[str, Any] | None = None,
) -> list[str]:
    """Hard gaps (post-engine) + soft residuals (pre-normalize / role defaults)."""
    import copy

    from models import _normalize_stat_gaps

    flags: list[str] = []
    if unresolved or ps is None:
        flags.append("no_stats")
        flags.append("unresolved_name")
        return flags

    minutes = float(getattr(ps, "minutes", 0) or 0)
    games = int(getattr(ps, "games", 0) or 0)
    rating = float(getattr(ps, "rating", 0) or 0)
    pos = str(getattr(ps, "primary_position", "") or "").upper()
    fpl = str(getattr(ps, "fpl_position", "") or "").upper()
    positions = list(getattr(ps, "positions", None) or [])
    pass_pct = float(getattr(ps, "pass_pct", 0) or 0)
    xg90 = float(getattr(ps, "xg90", 0) or 0)
    shots90 = float(getattr(ps, "shots90", 0) or 0)
    understat_xg = float(getattr(ps, "understat_xg90", 0) or 0)
    understat_shots = float(getattr(ps, "understat_shots90", 0) or 0)

    if minutes <= 0 and games <= 0:
        flags.append("minutes_zero")
    if minutes > 0 and minutes < 450:
        flags.append("minutes_very_low")
    if rating <= 0:
        flags.append("rating_zero")
    if pass_pct <= 0:
        flags.append("pass_pct_zero")
    if not pos:
        flags.append("no_position")
    if not positions and not pos:
        flags.append("no_positions")

    is_attacker = fpl in ATTACKER_FPL or pos in ATTACKER_POS
    if is_attacker:
        if xg90 <= 0 and understat_xg <= 0:
            flags.append("attacker_xg_missing")
        if shots90 <= 0 and understat_shots <= 0:
            flags.append("attacker_shots_missing")

    core = [
        float(getattr(ps, "goals90", 0) or 0),
        float(getattr(ps, "assists90", 0) or 0),
        xg90,
        float(getattr(ps, "xa90", 0) or 0),
        shots90,
        float(getattr(ps, "key_passes90", 0) or 0),
        float(getattr(ps, "tackles90", 0) or 0),
        float(getattr(ps, "interceptions90", 0) or 0),
        float(getattr(ps, "dribbles90", 0) or 0),
    ]
    if minutes <= 0 and all(v <= 0 for v in core):
        flags.append("all_core_rates_zero")

    # Soft / residual: inspect raw profile + what normalize fills.
    if raw_data:
        raw = copy.deepcopy(raw_data)
        raw_fpl = str(raw.get("fpl_position") or fpl or "").upper()
        raw_pos = str(raw.get("primary_position") or pos or "").upper()
        raw_attacker = raw_fpl in ATTACKER_FPL or raw_pos in ATTACKER_POS
        raw_min = float(raw.get("minutes") or 0)
        if raw_min <= 0 and int(raw.get("games") or 0) <= 0:
            flags.append("raw_minutes_zero")
        if float(raw.get("pass_pct") or 0) <= 0 and raw_fpl != "GK":
            flags.append("raw_pass_pct_zero")
        if float(raw.get("dribbles90") or 0) <= 0 and raw_fpl not in ("", "GK"):
            flags.append("raw_dribbles_zero")
        if raw_attacker:
            if float(raw.get("xg90") or 0) <= 0 and float(raw.get("understat_xg90") or 0) <= 0:
                flags.append("raw_attacker_xg_missing")
            if float(raw.get("shots90") or 0) <= 0 and float(raw.get("understat_shots90") or 0) <= 0:
                flags.append("raw_attacker_shots_missing")
            if float(raw.get("key_passes90") or 0) <= 0 and float(
                raw.get("understat_key_passes90") or 0
            ) <= 0:
                flags.append("raw_attacker_kp_missing")

        filled = copy.deepcopy(raw_data)
        _normalize_stat_gaps(filled)
        if filled.get("pass_pct_source") == "role_default":
            flags.append("pass_pct_role_default")
        if filled.get("dribbles_source") in ("role_default", "creator_estimate", "winger_estimate"):
            flags.append(f"dribbles_{filled.get('dribbles_source')}")
        if filled.get("dribble_pct_source") == "role_default":
            flags.append("dribble_pct_role_default")
        if filled.get("aerials_source") in ("estimated", "estimated_fwd", "estimated_mid"):
            flags.append(f"aerials_{filled.get('aerials_source')}")
        if filled.get("shots_source") in ("understat_sot_repair", "goals_shots_repair"):
            flags.append(f"shots_{filled.get('shots_source')}")
        if filled.get("sot_source") in ("understat_sot_repair", "goals_sot_repair"):
            flags.append(f"sot_{filled.get('sot_source')}")

        # Still zero after normalize (true residual hole).
        if float(filled.get("dribbles90") or 0) <= 0 and raw_fpl not in ("", "GK"):
            flags.append("dribbles_still_zero")
        if float(filled.get("pass_pct") or 0) <= 0 and raw_fpl != "GK":
            flags.append("pass_pct_still_zero")
        if raw_attacker and float(filled.get("xg90") or 0) <= 0 and float(
            filled.get("understat_xg90") or 0
        ) <= 0:
            flags.append("attacker_xg_still_missing")
        if raw_attacker and float(filled.get("shots90") or 0) <= 0 and float(
            filled.get("understat_shots90") or 0
        ) <= 0:
            flags.append("attacker_shots_still_missing")

    # Dedupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for f in flags:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _row_from_player(
    *,
    team_name: str,
    raw_name: str,
    resolved_name: str | None,
    role: str,
    slot: str,
    source_kind: str,
    season: str,
    ps: Any | None,
    flags: list[str],
    has_bench: bool,
) -> dict[str, Any]:
    def g(attr: str, default: Any = 0):
        if ps is None:
            return default
        return getattr(ps, attr, default)

    return {
        "team": team_name,
        "player_raw": raw_name,
        "player_resolved": resolved_name or "",
        "role": role,
        "slot": slot,
        "stat_source": source_kind,
        "season": season,
        "has_team_bench": has_bench,
        "minutes": float(g("minutes", 0) or 0),
        "games": int(g("games", 0) or 0),
        "primary_position": str(g("primary_position", "") or ""),
        "fpl_position": str(g("fpl_position", "") or ""),
        "positions": "|".join(list(g("positions", []) or [])),
        "rating": float(g("rating", 0) or 0),
        "goals90": float(g("goals90", 0) or 0),
        "assists90": float(g("assists90", 0) or 0),
        "xg90": float(g("xg90", 0) or 0),
        "xa90": float(g("xa90", 0) or 0),
        "shots90": float(g("shots90", 0) or 0),
        "shots_on_target90": float(g("shots_on_target90", 0) or 0),
        "key_passes90": float(g("key_passes90", 0) or 0),
        "pass_pct": float(g("pass_pct", 0) or 0),
        "dribbles90": float(g("dribbles90", 0) or 0),
        "tackles90": float(g("tackles90", 0) or 0),
        "interceptions90": float(g("interceptions90", 0) or 0),
        "understat_xg90": float(g("understat_xg90", 0) or 0),
        "understat_shots90": float(g("understat_shots90", 0) or 0),
        "gap_flags": "|".join(flags),
        "has_gaps": bool(flags),
    }


def main() -> int:
    from google_sheets_teams import team_payload_from_roster
    from sofascore_client import StatsStore
    from stats_resolver import prepare_match_player_stats
    from web.team_lineups import apply_saved_lineup

    print("Loading team list...", flush=True)
    rosters, source, sheet_meta = _load_sheet_or_fallback()
    print(f"Source: {source} ({len(rosters)} teams)", flush=True)

    store = StatsStore()
    rows: list[dict[str, Any]] = []
    team_summaries: list[dict[str, Any]] = []

    for roster in sorted(rosters.values(), key=lambda r: r.name.lower()):
        team = team_payload_from_roster(roster, store=store, resolve_names=True)
        team = apply_saved_lineup(team)
        has_bench = bool(team.get("bench"))

        # Use prepare_match_player_stats with a dummy opponent so prime/peak
        # override metadata is captured the same way as matchday.
        dummy = {
            "name": "__audit_dummy__",
            "formation": "4-3-3",
            "lineup": [],
            "bench": [],
            "prime_player": "",
            "peak_season": {"player": "", "season": ""},
        }
        try:
            player_stats, overrides, name_map = prepare_match_player_stats(
                team, dummy, store, cache_only=True
            )
        except Exception as exc:
            print(f"  WARN {roster.name}: stats resolve failed ({exc}); continuing cache-only map")
            from stats_resolver import prepare_team_player_stats

            player_stats, name_map = prepare_team_player_stats(team, store, cache_only=True)
            overrides = {"team_a": {}, "team_b": {}}

        override_a = overrides.get("team_a") or {}
        meta = team.get("sheet_meta") or {}
        full_resolved = [
            str(p).strip() for p in (meta.get("full_roster") or []) if p and str(p).strip()
        ]
        # One row per sheet squad member (raw nickname -> resolved display name).
        # Prefer sheet_meta.full_roster (engine-facing); zip with sheet raws.
        sheet_raws = [str(p).strip() for p in roster.players if p and str(p).strip()]
        pairs: list[tuple[str, str]] = []
        seen_resolved: set[str] = set()
        if full_resolved:
            for i, resolved in enumerate(full_resolved):
                raw = sheet_raws[i] if i < len(sheet_raws) else resolved
                if resolved in seen_resolved:
                    continue
                seen_resolved.add(resolved)
                pairs.append((raw, resolved))
            # Any saved-lineup XI/bench names not on the sheet roster (rare)
            for row in team.get("lineup") or []:
                p = (row.get("player") or "").strip()
                if p and p not in seen_resolved:
                    seen_resolved.add(p)
                    pairs.append((p, p))
            for p in team.get("bench") or []:
                p = str(p).strip()
                if p and p not in seen_resolved:
                    seen_resolved.add(p)
                    pairs.append((p, p))
        else:
            for raw in sheet_raws:
                resolved = name_map.get(raw) or raw
                if resolved in seen_resolved:
                    continue
                seen_resolved.add(resolved)
                pairs.append((raw, resolved))

        team_gap_count = 0
        for raw, resolved_hint in pairs:
            resolved = name_map.get(resolved_hint) or name_map.get(raw) or resolved_hint
            ps = player_stats.get(resolved)
            if ps is None:
                ps = player_stats.get(resolved_hint)
            if ps is None:
                ps = player_stats.get(raw)
            unresolved = ps is None
            role, slot = _role_slot_for(team, resolved if not unresolved else resolved_hint)
            if role == "roster":
                role2, slot2 = _role_slot_for(team, raw)
                if role2 != "roster":
                    role, slot = role2, slot2

            resolved_label = (ps.player if ps else resolved) or resolved_hint
            source_kind, season = _stat_source(team, raw, resolved_label or "", override_a)
            raw_profile = None
            if not unresolved:
                raw_profile = _raw_profile_dict(
                    store,
                    raw_name=raw,
                    resolved_name=resolved_label,
                    source_kind=source_kind,
                    season=season,
                )
            flags = _gap_flags(ps, unresolved=unresolved, raw_data=raw_profile)
            if flags:
                team_gap_count += 1
            rows.append(
                _row_from_player(
                    team_name=roster.name,
                    raw_name=raw,
                    resolved_name=resolved_label,
                    role=role,
                    slot=slot,
                    source_kind=source_kind,
                    season=season,
                    ps=ps,
                    flags=flags,
                    has_bench=has_bench,
                )
            )

        team_summaries.append(
            {
                "team": roster.name,
                "players": len(pairs),
                "xi": sum(1 for r in rows if r["team"] == roster.name and r["role"] == "XI"),
                "bench": sum(1 for r in rows if r["team"] == roster.name and r["role"] == "bench"),
                "with_gaps": team_gap_count,
                "has_bench": has_bench,
                "prime_player": (team.get("prime_player") or ""),
                "peak_season": team.get("peak_season") or {},
            }
        )
        print(
            f"  {roster.name}: {len(pairs)} players, {team_gap_count} with gaps, "
            f"bench={'yes' if has_bench else 'no'}",
            flush=True,
        )

    flag_counts: Counter[str] = Counter()
    for r in rows:
        for f in (r["gap_flags"] or "").split("|"):
            if f:
                flag_counts[f] += 1

    HARD_FLAGS = {
        "no_stats",
        "unresolved_name",
        "minutes_zero",
        "rating_zero",
        "pass_pct_zero",
        "no_position",
        "no_positions",
        "attacker_xg_missing",
        "attacker_shots_missing",
        "all_core_rates_zero",
        "dribbles_still_zero",
        "pass_pct_still_zero",
        "attacker_xg_still_missing",
        "attacker_shots_still_missing",
        "raw_minutes_zero",
        "raw_attacker_xg_missing",
        "raw_attacker_shots_missing",
    }

    gapped = [r for r in rows if r["has_gaps"]]
    hard_gapped = [
        r
        for r in gapped
        if any(f in HARD_FLAGS for f in (r["gap_flags"] or "").split("|") if f)
    ]
    soft_only = [r for r in gapped if r not in hard_gapped]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roster_source": source,
        "sheet_meta": sheet_meta,
        "team_count": len(team_summaries),
        "player_rows": len(rows),
        "unique_resolved": len({r["player_resolved"] or r["player_raw"] for r in rows}),
        "players_with_gaps": len(gapped),
        "players_with_hard_gaps": len(hard_gapped),
        "players_soft_gaps_only": len(soft_only),
        "players_clean": len(rows) - len(gapped),
        "gap_flag_counts": dict(flag_counts.most_common()),
        "teams_with_bench": sum(1 for t in team_summaries if t["has_bench"]),
        "teams": team_summaries,
        "csv_path": str(CSV_OUT),
        "json_path": str(JSON_OUT),
        "notes": (
            "Hard gaps = missing/unusable engine inputs after resolve. "
            "Soft gaps = raw profile holes filled by role defaults / estimates "
            "(pass_pct_role_default, dribbles_*, aerials_estimated*, etc.)."
        ),
    }

    DATA.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else [
        "team",
        "player_raw",
        "player_resolved",
        "role",
        "slot",
        "stat_source",
        "season",
        "gap_flags",
        "has_gaps",
    ]
    with CSV_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    payload = {
        **summary,
        "players": rows,
        "gapped_players": gapped,
        "hard_gapped_players": hard_gapped,
        "soft_only_players": soft_only,
    }
    JSON_OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== Sheet Players Audit Export ===", flush=True)
    print(f"Source:            {source}", flush=True)
    print(f"Teams:             {summary['team_count']}", flush=True)
    print(f"Player rows:       {summary['player_rows']}", flush=True)
    print(f"With any gaps:     {summary['players_with_gaps']}", flush=True)
    print(f"  hard gaps:       {summary['players_with_hard_gaps']}", flush=True)
    print(f"  soft-only:       {summary['players_soft_gaps_only']}", flush=True)
    print(f"Clean:             {summary['players_clean']}", flush=True)
    print(f"Teams with bench:  {summary['teams_with_bench']}", flush=True)
    print("Top gap types:", flush=True)
    for k, v in flag_counts.most_common(20):
        print(f"  {k}: {v}", flush=True)
    print(f"\nCSV:  {CSV_OUT}", flush=True)
    print(f"JSON: {JSON_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
