"""FotMob client for aerial/duel % and preferred foot."""

from __future__ import annotations



import json

import re

import time

import urllib.error

import urllib.parse

import urllib.request

from pathlib import Path

from typing import Any



from understat_client import normalize_name, normalize_team



DATA_DIR = Path(__file__).resolve().parent / "data"

FOTMOB_CACHE_FILE = DATA_DIR / "fotmob_cache.json"



SEARCH_URL = "https://www.fotmob.com/api/data/search/suggest"

PLAYER_DATA_URL = "https://www.fotmob.com/api/data/playerData"

PLAYER_STATS_URL = "https://www.fotmob.com/api/data/playerStats"

PLAYER_PAGE_URL = "https://www.fotmob.com/players/{player_id}"



DEFAULT_HEADERS = {

    "User-Agent": (

        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "

        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    ),

    "Accept": "application/json, text/html, */*",

}

REQUEST_DELAY_SEC = 0.55



FOTMOB_STAT_KEYS = frozenset(

    {

        "fotmob_id",

        "fotmob_matched",

        "preferred_foot",

        "duels_won_pct",

        "duels_source",

        "aerials_won90",

        "aerials_lost90",

        "aerials_won_pct",

        "aerials_source",

        "fotmob_seasons_blended",

        "fotmob_season_minutes",

    }

)



_SKIP_TOURNAMENT_TERMS = (

    "world cup",

    "cup",

    "olympics",

    "nations league",

    "qualification",

    "community shield",

    "super cup",

    "shield",

)



_STORE_LOCK: bool = False

_last_request_at = 0.0





def _sleep_politely() -> None:

    global _last_request_at

    elapsed = time.monotonic() - _last_request_at

    if elapsed < REQUEST_DELAY_SEC:

        time.sleep(REQUEST_DELAY_SEC - elapsed)

    _last_request_at = time.monotonic()





def _fetch_bytes(url: str) -> bytes:

    _sleep_politely()

    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)

    with urllib.request.urlopen(req, timeout=45) as resp:

        return resp.read()





def _fetch_json(url: str) -> Any:

    return json.loads(_fetch_bytes(url))





def _load_cache() -> dict[str, Any]:

    if not FOTMOB_CACHE_FILE.exists():

        return {"searches": {}, "players": {}, "season_stats": {}}

    try:

        cache = json.loads(FOTMOB_CACHE_FILE.read_text(encoding="utf-8"))

    except (json.JSONDecodeError, OSError):

        return {"searches": {}, "players": {}, "season_stats": {}}

    cache.setdefault("searches", {})

    cache.setdefault("players", {})

    cache.setdefault("season_stats", {})

    return cache





def _save_cache(cache: dict[str, Any]) -> None:

    FOTMOB_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(cache, indent=2, ensure_ascii=False)

    tmp = FOTMOB_CACHE_FILE.with_suffix(".json.tmp")

    last_err: OSError | None = None

    for attempt in range(3):

        try:

            tmp.write_text(content, encoding="utf-8")

            tmp.replace(FOTMOB_CACHE_FILE)

            return

        except PermissionError as exc:

            last_err = exc

            if attempt < 2:

                time.sleep(0.75 * (attempt + 1))

        except OSError as exc:

            if getattr(exc, "winerror", None) in (5, 32):

                last_err = exc

                if attempt < 2:

                    time.sleep(0.75 * (attempt + 1))

                    continue

            raise

    if last_err is not None:

        raise last_err





def _num(value: Any, default: float = 0.0) -> float:

    if value is None:

        return default

    try:

        return float(str(value).replace("%", "").strip())

    except (TypeError, ValueError):

        return default





def _strip_disambiguation(display_name: str) -> str:

    if " (" in display_name:

        return display_name.rsplit(" (", 1)[0]

    return display_name





def _normalize_season_label(label: str) -> str:

    return label.strip().replace("-", "/")





def _team_overlap_score(team_a: str, team_b: str) -> int:

    a = set(normalize_team(team_a).split())

    b = set(normalize_team(team_b).split())

    if not a or not b:

        return 0

    return len(a & b)





def _name_overlap_score(query: str, candidate: str) -> int:

    q = set(normalize_name(query).split())

    c = set(normalize_name(candidate).split())

    if not q or not c:

        return 0

    if q <= c or c <= q:

        return 100 + len(q & c)

    return len(q & c)





def search_player(name: str, *, team: str = "", use_cache: bool = True) -> list[dict[str, Any]]:

    """Return FotMob search hits for a player name."""

    cache = _load_cache() if use_cache else {"searches": {}, "players": {}, "season_stats": {}}

    key = normalize_name(_strip_disambiguation(name))

    if use_cache and key in cache.get("searches", {}):

        return list(cache["searches"][key])



    term = urllib.parse.quote(_strip_disambiguation(name))

    url = f"{SEARCH_URL}?hits=12&lang=en&term={term}"

    payload = _fetch_json(url)

    hits: list[dict[str, Any]] = []

    for block in payload if isinstance(payload, list) else []:

        for item in block.get("suggestions", []):

            if item.get("type") != "player":

                continue

            hits.append(

                {

                    "id": int(item["id"]),

                    "name": str(item.get("name", "")),

                    "team_id": int(item.get("teamId", 0) or 0),

                    "team_name": str(item.get("teamName", "")),

                }

            )



    if use_cache:

        cache.setdefault("searches", {})[key] = hits

        _save_cache(cache)

    return hits





def resolve_player_id(name: str, *, team: str = "", use_cache: bool = True) -> int | None:

    """Pick the best FotMob player id for a cache/sheet display name."""

    from player_names import known_fotmob_id



    known_id = known_fotmob_id(name)

    if known_id is not None:

        return known_id



    hits = search_player(name, team=team, use_cache=use_cache)

    if not hits:

        return None



    scored: list[tuple[int, int, dict[str, Any]]] = []

    for hit in hits:

        name_score = _name_overlap_score(name, hit["name"])

        team_score = _team_overlap_score(team, hit["team_name"]) if team else 0

        scored.append((team_score, name_score, hit))



    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)

    best_team, best_name, best = scored[0]

    if normalize_name(best["name"]) == normalize_name(_strip_disambiguation(name)):

        return best["id"]

    if best_name >= 2 and (not team or best_team > 0):

        return best["id"]

    if len(scored) == 1 and best_name >= 1:

        return best["id"]

    return None





def _parse_preferred_foot(player_information: list[dict[str, Any]]) -> str | None:

    for item in player_information:

        if item.get("translationKey") != "preferred_foot":

            continue

        value = item.get("value") or {}

        key = str(value.get("key") or "").lower()

        fallback = str(value.get("fallback") or "").lower()

        if key in {"left", "right", "both"}:

            return key

        if "left" in fallback:

            return "left"

        if "right" in fallback:

            return "right"

        if "both" in fallback:

            return "both"

    return None





def _iter_stat_items(stats_section: dict[str, Any]):

    for group in stats_section.get("items", []):

        for item in group.get("items", []):

            yield item





def _stat_item(stats_section: dict[str, Any], localized_title_id: str) -> dict[str, Any] | None:

    for item in _iter_stat_items(stats_section):

        if item.get("localizedTitleId") == localized_title_id:

            return item

    return None





def _top_stat_item(top_stat_card: dict[str, Any], localized_title_id: str) -> dict[str, Any] | None:

    for item in top_stat_card.get("items", []):

        if item.get("localizedTitleId") == localized_title_id:

            return item

    return None





def _is_cup_tournament(name: str) -> bool:

    lowered = name.lower()

    return any(term in lowered for term in _SKIP_TOURNAMENT_TERMS)





def _pick_tournament(tournaments: list[dict[str, Any]], main_league_name: str) -> dict[str, Any] | None:

    for tournament in tournaments:

        if tournament.get("name") == main_league_name and tournament.get("hasDeepStats"):

            return tournament

    for tournament in tournaments:

        name = str(tournament.get("name", ""))

        if tournament.get("hasDeepStats") and not _is_cup_tournament(name):

            return tournament

    return None





def _league_season_entries(

    stat_seasons: list[dict[str, Any]],

    main_league_name: str,

    *,

    preferred_seasons: list[str] | None = None,

    limit: int = 2,

) -> list[dict[str, str]]:

    """Resolve main-league entryIds for up to `limit` seasons (newest first)."""

    preferred = {_normalize_season_label(s) for s in (preferred_seasons or [])}

    all_entries: list[dict[str, str]] = []
    for season in stat_seasons or []:

        season_name = str(season.get("seasonName", ""))

        tournament = _pick_tournament(season.get("tournaments", []), main_league_name)

        if not tournament:

            continue

        all_entries.append(

            {

                "season_name": season_name,

                "tournament": str(tournament.get("name", "")),

                "entry_id": str(tournament.get("entryId", "")),

            }

        )



    if preferred:

        matched = [e for e in all_entries if _normalize_season_label(e["season_name"]) in preferred]

        if matched:

            return matched[:limit]



    return all_entries[:limit]





def _extract_season_stats_payload(payload: dict[str, Any]) -> dict[str, float]:

    """Pull duel/aerial rates and minutes from a playerStats API response."""

    stats_section = payload.get("statsSection") or {}

    top_stat_card = payload.get("topStatCard") or {}

    out: dict[str, float] = {}



    minutes_item = _top_stat_item(top_stat_card, "minutes_played")

    if minutes_item is not None:

        out["minutes_played"] = _num(minutes_item.get("statValue"))



    duel_pct = _stat_item(stats_section, "duel_won_percent")

    aerial_pct = _stat_item(stats_section, "aerials_won_percent")

    aerial_won = _stat_item(stats_section, "aerials_won")



    if duel_pct is not None:

        out["duels_won_pct"] = _num(duel_pct.get("statValue"))

    if aerial_pct is not None:

        out["aerials_won_pct"] = _num(aerial_pct.get("statValue"))

    if aerial_won is not None:

        out["aerials_won90"] = _num(aerial_won.get("per90"))

    return out





def _season_cache_key(player_id: int, entry_id: str) -> str:

    return f"{player_id}:{entry_id}"





def get_player_season_stats(

    player_id: int,

    entry_id: str,

    *,

    season_name: str = "",

    tournament: str = "",

    use_cache: bool = True,

) -> dict[str, Any]:

    """Fetch per-tournament season stats from FotMob playerStats API."""

    cache = _load_cache() if use_cache else {"searches": {}, "players": {}, "season_stats": {}}

    key = _season_cache_key(player_id, entry_id)

    if use_cache and key in cache.get("season_stats", {}):

        return dict(cache["season_stats"][key])



    url = (

        f"{PLAYER_STATS_URL}?playerId={player_id}"

        f"&seasonId={urllib.parse.quote(entry_id)}"

        f"&isFirstSeason=false"

    )

    payload = _fetch_json(url)

    stats = _extract_season_stats_payload(payload)

    record = {

        "player_id": player_id,

        "season_name": season_name,

        "tournament": tournament,

        "entry_id": entry_id,

        **stats,

    }

    if use_cache:

        cache.setdefault("season_stats", {})[key] = record

        _save_cache(cache)

    return record





def _blend_season_stats(season_rows: list[dict[str, Any]]) -> dict[str, Any]:

    """Minutes-weighted blend across league seasons."""

    usable = [row for row in season_rows if row.get("minutes_played", 0) > 0]

    if not usable:

        usable = [row for row in season_rows if row.get("duels_won_pct", 0) > 0 or row.get("aerials_won_pct", 0) > 0]

    if not usable:

        return {}



    total_minutes = sum(_num(row.get("minutes_played")) for row in usable)

    if total_minutes <= 0:

        total_minutes = float(len(usable))

        weights = [1.0] * len(usable)

    else:

        weights = [_num(row.get("minutes_played")) for row in usable]



    def _weighted(field: str) -> float:

        vals = [_num(row.get(field)) for row in usable]

        if not any(vals):

            return 0.0

        return sum(v * w for v, w in zip(vals, weights)) / total_minutes



    blended: dict[str, Any] = {

        "duels_won_pct": _weighted("duels_won_pct"),

        "aerials_won_pct": _weighted("aerials_won_pct"),

        "aerials_won90": _weighted("aerials_won90"),

        "fotmob_seasons_blended": [row.get("season_name", "") for row in usable],

        "fotmob_season_minutes": {

            str(row.get("season_name", "")): _num(row.get("minutes_played"))

            for row in usable

        },

    }



    won90 = blended["aerials_won90"]

    pct = blended["aerials_won_pct"] / 100.0

    if won90 > 0 and pct > 0:

        blended["aerials_lost90"] = won90 * (1.0 - pct) / pct

    return blended





def _get_player_data(player_id: int, *, use_cache: bool = True) -> dict[str, Any]:

    cache = _load_cache() if use_cache else {"searches": {}, "players": {}, "season_stats": {}}

    key = str(player_id)

    cached = cache.get("players", {}).get(key, {})

    if use_cache and cached.get("main_league_name") and cached.get("stat_seasons"):
        return cached

    api = _fetch_json(f"{PLAYER_DATA_URL}?id={player_id}")
    main_league = api.get("mainLeague") or {}
    record = {
        "id": player_id,
        "name": api.get("name"),
        "team": (api.get("primaryTeam") or {}).get("teamName", ""),
        "preferred_foot": _parse_preferred_foot(api.get("playerInformation", [])),
        "main_league_name": str(main_league.get("leagueName", "")),
        "stat_seasons": api.get("statSeasons") or [],
    }

    if use_cache:

        cache.setdefault("players", {})[key] = record

        _save_cache(cache)

    return record





def _parse_player_page(html: bytes) -> dict[str, Any]:

    text = html.decode("utf-8", errors="replace")

    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', text, re.DOTALL)

    if not match:

        return {}

    page = json.loads(match.group(1))

    return page.get("props", {}).get("pageProps", {}).get("data") or {}





def get_player_profile(

    player_id: int,

    *,

    seasons_used: list[str] | None = None,

    use_cache: bool = True,

) -> dict[str, Any]:

    """Fetch FotMob bio + minutes-weighted league duel/aerial blend (last 2 seasons)."""

    meta = _get_player_data(player_id, use_cache=use_cache)

    main_league = meta.get("main_league_name", "")
    stat_seasons = meta.get("stat_seasons") or []
    if not stat_seasons:
        page = _parse_player_page(_fetch_bytes(PLAYER_PAGE_URL.format(player_id=player_id)))
        stat_seasons = page.get("statSeasons") or []

        if not main_league:

            main_league = str((page.get("mainLeague") or {}).get("leagueName", ""))



    entries = _league_season_entries(

        stat_seasons,

        main_league,

        preferred_seasons=seasons_used,

        limit=2,

    )

    season_rows: list[dict[str, Any]] = []

    for entry in entries:

        try:

            row = get_player_season_stats(

                player_id,

                entry["entry_id"],

                season_name=entry["season_name"],

                tournament=entry["tournament"],

                use_cache=use_cache,

            )

            if row:

                season_rows.append(row)

        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):

            continue



    blended = _blend_season_stats(season_rows)

    profile = {

        "id": player_id,

        "name": meta.get("name"),

        "team": meta.get("team", ""),

        "preferred_foot": meta.get("preferred_foot"),

        **blended,

    }

    return profile





def get_player_stats(

    player_id: int,

    *,

    seasons_used: list[str] | None = None,

    use_cache: bool = True,

) -> dict[str, Any]:

    """Alias for profile fetch focused on stat extraction."""

    return get_player_profile(player_id, seasons_used=seasons_used, use_cache=use_cache)





def merge_fotmob_for_player(display_name: str, data: dict[str, Any], *, use_cache: bool = True) -> bool:

    """Attach FotMob duel/aerial/foot fields in-place. Returns True when matched."""

    existing_id = data.get("fotmob_id")

    player_id = int(existing_id) if existing_id else resolve_player_id(display_name, team=str(data.get("team", "")), use_cache=use_cache)

    if player_id is None:

        data["fotmob_matched"] = False

        return False



    seasons_used = data.get("seasons_used")

    if not isinstance(seasons_used, list):

        seasons_used = None



    try:

        profile = get_player_profile(player_id, seasons_used=seasons_used, use_cache=use_cache)

    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):

        data["fotmob_matched"] = False

        return False



    data["fotmob_id"] = player_id

    data["fotmob_matched"] = True



    foot = profile.get("preferred_foot")

    if foot:

        data["preferred_foot"] = foot



    if profile.get("duels_won_pct", 0) > 0:

        data["duels_won_pct"] = profile["duels_won_pct"]

        data["duels_source"] = "fotmob"



    if profile.get("aerials_won_pct", 0) > 0:

        data["aerials_won_pct"] = profile["aerials_won_pct"]

        data["aerials_source"] = "fotmob"

    if profile.get("aerials_won90", 0) > 0:

        data["aerials_won90"] = profile["aerials_won90"]

    if profile.get("aerials_lost90", 0) > 0:

        data["aerials_lost90"] = profile["aerials_lost90"]

    elif profile.get("aerials_won90", 0) > 0 and profile.get("aerials_won_pct", 0) > 0:

        won = profile["aerials_won90"]

        pct = profile["aerials_won_pct"] / 100.0

        if pct > 0:

            data["aerials_lost90"] = won * (1.0 - pct) / pct



    if profile.get("fotmob_seasons_blended"):

        data["fotmob_seasons_blended"] = profile["fotmob_seasons_blended"]

    if profile.get("fotmob_season_minutes"):

        data["fotmob_season_minutes"] = profile["fotmob_season_minutes"]



    return True

