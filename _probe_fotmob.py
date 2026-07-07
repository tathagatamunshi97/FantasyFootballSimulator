"""Temporary probe script for FotMob API exploration."""
import json
import re
import urllib.request

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main() -> None:
    pid = 255610
    data = fetch_json(f"https://www.fotmob.com/api/data/playerData?id={pid}")
    print("preferred foot from playerInformation:")
    for item in data.get("playerInformation", []):
        if "foot" in str(item.get("title", "")).lower():
            print(item)

    # Try season stats endpoints
    entry = None
    for s in data.get("statSeasons", []):
        for t in s.get("tournaments", []):
            if t.get("name") == "Premier League" and t.get("hasDeepStats"):
                entry = t.get("entryId")
                season = s.get("seasonName")
                tid = t.get("tournamentId")
                print(f"\nseason={season} entry={entry} tid={tid}")
                candidates = [
                    f"https://www.fotmob.com/api/data/playerstats?playerId={pid}&tournamentId={tid}&season={season.replace('/', '-')}",
                    f"https://www.fotmob.com/api/data/playerSeasonStats?playerId={pid}&entryId={entry}",
                    f"https://www.fotmob.com/api/data/playerSeasonStats?playerId={pid}&tournamentId={tid}",
                    f"https://www.fotmob.com/api/data/playerstats?playerId={pid}&entryId={entry}",
                    f"https://www.fotmob.com/api/data/stats/player?playerId={pid}&entryId={entry}",
                ]
                for url in candidates:
                    try:
                        d = fetch_json(url)
                        print("OK", url)
                        print(" keys:", list(d.keys())[:15] if isinstance(d, dict) else type(d))
                        blob = json.dumps(d).lower()
                        for term in ("aerial", "duel"):
                            if term in blob:
                                print(f"  contains {term}")
                    except Exception as e:
                        print("FAIL", url.split("?")[1], e)
                break

    # HTML page
    url = f"https://www.fotmob.com/players/{pid}/harry-maguire"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        nd = json.loads(m.group(1))
        pp = nd.get("props", {}).get("pageProps", {})
        print("\npageProps keys:", list(pp.keys()))
        d = pp.get("data") or {}
        blob = json.dumps(d).lower()
        for term in ("aerial", "duel", "preferred"):
            print(f"page data has {term}:", term in blob)
        # dump paths containing duel/aerial
        def walk(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    p = f"{path}.{k}" if path else k
                    if any(t in str(k).lower() for t in ("aerial", "duel", "foot")):
                        print("PATH", p, "=>", str(v)[:200])
                    walk(v, p)
            elif isinstance(obj, list):
                for i, v in enumerate(obj[:50]):
                    walk(v, f"{path}[{i}]")

        walk(d)
        # save sample for inspection
        with open("_probe_fotmob_page.json", "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
    # Compare API vs page for firstSeasonStats
    api = fetch_json(f"https://www.fotmob.com/api/data/playerData?id={pid}")
    print("\nAPI has firstSeasonStats:", "firstSeasonStats" in api)
    print("page has firstSeasonStats:", "firstSeasonStats" in d)

    # Try season stats URL patterns from network research
    for url in [
        f"https://www.fotmob.com/api/data/playerSeasonStats?playerId={pid}",
        f"https://www.fotmob.com/api/data/playerSeasonStats?id={pid}",
        f"https://www.fotmob.com/api/data/playerSeasonStats?playerid={pid}&season=0-0",
        f"https://www.fotmob.com/api/data/playerSeasonStats?playerId={pid}&entryId=0-0",
        f"https://www.fotmob.com/api/data/playerSeasonStats?playerId={pid}&seasonId=0-0",
        f"https://www.fotmob.com/api/data/playerSeasonStats?playerId={pid}&tournamentSeasonKey=0-0",
    ]:
        try:
            r = fetch_json(url)
            print("season OK", url, list(r.keys())[:10])
        except Exception as e:
            print("season FAIL", url.split("?")[1], e)


if __name__ == "__main__":
    main()
