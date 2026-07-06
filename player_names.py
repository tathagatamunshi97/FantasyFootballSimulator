"""Resolve player names from Excel / shorthand to canonical cache keys."""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sofascore_client import StatsStore

# Shorthand and Excel truncations -> canonical name in player_stats_cache.json
ALIASES: dict[str, str] = {
    "trent alexander ar": "Trent Alexander-Arnold",
    "trent alexander-arnold": "Trent Alexander-Arnold",
    "trent alexander arnold": "Trent Alexander-Arnold",
    "saliba": "William Saliba",
    "william saliba": "William Saliba",
    "upamecano": "Dayot Upamecano",
    "dayot upamecano": "Dayot Upamecano",
    "hakimi": "Achraf Hakimi",
    "achraf hakimi": "Achraf Hakimi",
    "rice": "Declan Rice",
    "declan rice": "Declan Rice",
    "willian pacho": "Willian Pacho",
    "william pacho": "Willian Pacho",
    "pacho": "Willian Pacho",
    "pau cubarsi": "Pau Cubarsí",
    "cubarsi": "Pau Cubarsí",
    "theo hernandez": "Theo Hernández",
    "theo hernández": "Theo Hernández",
    "joao neves": "João Neves",
    "joão neves": "João Neves",
    "bruno guimaraes": "Bruno Guimarães",
    "bruno guimarães": "Bruno Guimarães",
    "kylian mbappe": "Kylian Mbappé",
    "kylian mbappé": "Kylian Mbappé",
    "mbappe": "Kylian Mbappé",
    "nuno mendes": "Nuno Mendes",
    "vitinha": "Vitinha (Paris Saint-Germain)",
    "desire doue": "Désiré Doué",
    "désiré doué": "Désiré Doué",
    "doue": "Désiré Doué",
    "ousmane dembele": "Ousmane Dembélé",
    "ousmane dembélé": "Ousmane Dembélé",
    "dembele": "Ousmane Dembélé",
    "lamine yamal": "Lamine Yamal",
    "yamal": "Lamine Yamal",
    "lucas chevalier": "Lucas Chevalier",
    "chevalier": "Lucas Chevalier",
    "david raya": "David Raya",
    "erling haaland": "Erling Haaland",
    "haaland": "Erling Haaland",
    "bukayo saka": "Bukayo Saka",
    "saka": "Bukayo Saka",
    "bruno fernandes": "Bruno Fernandes",
    "pedri": "Pedri",
    "piero hincapie": "Piero Hincapié",
    "hincapie": "Piero Hincapié",
    "jules kounde": "Jules Koundé",
    "kounde": "Jules Koundé",
    "kai havertz": "Kai Havertz",
    "havertz": "Kai Havertz",
    "joan garcia": "Joan García",
    "gabriel magalhaes": "Gabriel Magalhães",
    "gabriel": "Gabriel Magalhães",
    "khvicha kvaratskhelia": "Khvicha Kvaratskhelia",
    "kvaratskhelia": "Khvicha Kvaratskhelia",
    "kvaratskhel": "Khvicha Kvaratskhelia",
    "cristiano ronaldo": "Cristiano Ronaldo",
    "ronaldo": "Cristiano Ronaldo",
    "lionel messi": "Lionel Messi",
    "messi": "Lionel Messi",
    "ngolo kante": "N'Golo Kanté",
    "n'golo kante": "N'Golo Kanté",
    "kante": "N'Golo Kanté",
    "edinson cavani": "Edinson Cavani",
    "cavani": "Edinson Cavani",
    "dani alves": "Dani Alves",
    "marcelo": "Marcelo",
    "giovanni lo celso": "Giovanni Lo Celso",
    "lo celso": "Giovanni Lo Celso",
    "gonzalo higuain": "Gonzalo Higuaín",
    "higuain": "Gonzalo Higuaín",
    "diego godin": "Diego Godín",
    "godin": "Diego Godín",
    "luis suarez": "Luis Suárez",
    "suarez": "Luis Suárez",
    "arturo vidal": "Arturo Vidal",
    "vidal": "Arturo Vidal",
    "angel di maria": "Ángel Di María",
    "di maria": "Ángel Di María",
    "fernandinho": "Fernandinho",
    "roberto firmino": "Roberto Firmino",
    "firmino": "Roberto Firmino",
    "neymar": "Neymar",
    "alexis sanchez": "Alexis Sánchez",
    "sanchez": "Alexis Sánchez",
    "radamel falcao": "Radamel Falcao",
    "falcao": "Radamel Falcao",
    "cr7": "Cristiano Ronaldo",
    "bruno g": "Bruno Guimarães",
    "bruno": "Bruno Fernandes",
    "vvd": "Virgil van Dijk",
    "virgil van dijk": "Virgil van Dijk",
    "kdb": "Kevin De Bruyne",
    "kevin de bruyyne": "Kevin De Bruyne",
    "vinicius": "Vinícius Júnior",
    "vinícius": "Vinícius Júnior",
    "salah": "Mohamed Salah",
    "modric": "Luka Modrić",
    "modrić": "Luka Modrić",
    "rudiger": "Antonio Rüdiger",
    "rüdiger": "Antonio Rüdiger",
    "raphinha": "Raphinha",
    "kimmich": "Joshua Kimmich",
    "neuer": "Manuel Neuer",
    "marquinhos": "Marquinhos",
    "dumfries": "Denzel Dumfries",
    "raya": "David Raya",
    "mbappe": "Kylian Mbappé",
    "olise": "Michael Olise",
    "kane": "Harry Kane",
    "casemiro": "Casemiro",
    "bastoni": "Alessandro Bastoni",
    "carvajal": "Dani Carvajal",
    "bounou": "Yassine Bounou",
    "tchouameni": "Aurélien Tchouaméni",
    "alisson": "Alisson",
    "el kaabi": "Ayoub El Kaabi",
    "aymen el kaabi": "Ayoub El Kaabi",
    "ayoub el kaabi": "Ayoub El Kaabi",
    "bernard": "Bernardo Silva",
    "marcos llorente": "Marcos Llorente",
    "cucurella": "Marc Cucurella",
    "enzo f": "Enzo Fernández",
    "enzo fernandez": "Enzo Fernández",
    "ruiz": "Fabián Ruiz",
    "khvicha": "Khvicha Kvaratskhelia",
    "rodri": "Rodri",
    "julian alvarez": "Julián Álvarez",
    "emiliano martinez": "Emiliano Martínez",
    "guirassy": "Serhou Guirassy",
    "nuno": "Nuno Mendes",
    "porro": "Pedro Porro",
    "de ligt": "Matthijs de Ligt",
    "alaba": "David Alaba",
    "brahim diaz": "Brahim Díaz",
    "diogo dalot": "Diogo Dalot",
    "fede valverde": "Federico Valverde",
    "dani olmo": "Dani Olmo",
    "nico paz": "Nico Paz",
    "lautaro martinez": "Lautaro Martínez",
    "marcus thuram": "Marcus Thuram",
    "sergio ramos": "Sergio Ramos",
    "jurien timber": "Jurriën Timber",
    "jurrien timber": "Jurriën Timber",
    "timber": "Jurriën Timber",
    "bellingham": "Jude Bellingham",
    "maignan": "Mike Maignan",
    "stanisic": "Josip Stanišić",
    "doku": "Jérémy Doku",
    "barella": "Nicolò Barella",
    "gravenberch": "Ryan Gravenberch",
    "van hecke": "Jan Paul van Hecke",
    "laimer": "Konrad Laimer",
    "nunes": "Matheus Nunes",
    "caicedo": "Moisés Caicedo",
    "cherki": "Rayan Cherki",
    "courtois": "Thibaut Courtois",
    "calafiori": "Riccardo Calafiori",
    "calvert-lewin": "Dominic Calvert-Lewin",
    "donnarumma": "Gianluigi Donnarumma",
    "eze": "Eberechi Eze",
    "gvardiol": "Joško Gvardiol",
    "semenyo": "Antoine Semenyo",
    "szoboszlai": "Dominik Szoboszlai",
    "szoboszalai": "Dominik Szoboszlai",
    "tielemans": "Youri Tielemans",
    "schlotterbeck": "Nico Schlotterbeck",
    "konate": "Ibrahima Konaté",
    "mbuemo": "Bryan Mbeumo",
    "mctominay": "Scott McTominay",
    "laporte": "Aymeric Laporte",
    "musiala": "Jamal Musiala",
    "lewandowski": "Robert Lewandowski",
    "kenan yildiz": "Kenan Yıldız",
    "pulisic": "Christian Pulišić",
    "pavlovic": "Aleksandar Pavlović",
    "gundogan": "İlkay Gündoğan",
    "ilkay gundogan": "İlkay Gündoğan",
    "gyokeres": "Viktor Gyökeres",
    "viktor gyokeres": "Viktor Gyökeres",
    "eder militao": "Éder Militão",
    "militao": "Éder Militão",
    "tapsoba": "Edmond Tapsoba",
    "edmond tapsoba": "Edmond Tapsoba",
    "rrahmani": "Amir Rrahmani",
    "amir rrahmani": "Amir Rrahmani",
    "alex grimaldo": "Alejandro Grimaldo",
    "grimaldo": "Alejandro Grimaldo",
    "sean lammens": "Senne Lammens",
    "senne lammens": "Senne Lammens",
    "lammens": "Senne Lammens",
    "stones": "John Stones",
    "john stones": "John Stones",
    "mahrez": "Riyad Mahrez",
    "riyad mahrez": "Riyad Mahrez",
}

# Bypass Sofascore search when rate-limited or names are ambiguous.
KNOWN_SOFASCORE_IDS: dict[str, int] = {
    "kante": 234148,
    "n'golo kante": 234148,
    "ngolo kante": 234148,
    "cristiano ronaldo": 750,
    "ronaldo": 750,
    "lionel messi": 12994,
    "messi": 12994,
    "edinson cavani": 21521,
    "cavani": 21521,
    "dani alves": 4419,
    "marcelo": 17787,
    "giovanni lo celso": 892219,
    "lo celso": 892219,
    "gonzalo higuain": 19438,
    "higuain": 19438,
    "diego godin": 14933,
    "godin": 14933,
    "luis suarez": 16943,
    "suarez": 16943,
    "arturo vidal": 91047,
    "vidal": 91047,
    "angel di maria": 30027,
    "di maria": 30027,
    "fernandinho": 13630,
    "roberto firmino": 143697,
    "firmino": 143697,
    "neymar": 124712,
    "alexis sanchez": 34120,
    "sanchez": 34120,
    "radamel falcao": 25682,
    "falcao": 25682,
    "gundogan": 45853,
    "ilkay gundogan": 45853,
    "sergio ramos": 146219,
    "militao": 822519,
    "eder militao": 822519,
    "el kaabi": 919793,
    "ayoub el kaabi": 919793,
    "aymen el kaabi": 919793,
    "stones": 152077,
    "john stones": 152077,
    "mahrez": 158213,
    "riyad mahrez": 158213,
    "rodri": 827606,
    "rodri hernandez": 827606,
    "kevin de bruyne": 70996,
    "kdb": 70996,
    "casemiro": 122951,
}

KNOWN_PLAYER_POSITIONS: dict[int, str] = {
    234148: "M",
    750: "F",
    12994: "F",
    21521: "F",
    4419: "D",
    17787: "D",
    892219: "M",
    19438: "F",
    14933: "D",
    16943: "F",
    91047: "M",
    30027: "M",
    13630: "M",
    143697: "F",
    124712: "F",
    34120: "F",
    25682: "F",
    45853: "M",
    146219: "D",
    822519: "D",
    919793: "F",
    152077: "D",
    158213: "F",
    827606: "M",
    70996: "M",
    122951: "M",
}


KNOWN_DISPLAY_NAMES: dict[int, str] = {
    234148: "N'Golo Kanté",
    750: "Cristiano Ronaldo",
    12994: "Lionel Messi",
}

KNOWN_PRIME_SEASON_SUFFIX: dict[int, str] = {
    234148: "16/17",
    750: "14/15",
    12994: "20/21",
    152077: "24/25",
    158213: "22/23",
    827606: "23/24",
    70996: "19/20",
    124712: "14/15",
    146219: "14/15",
    122951: "17/18",
}

# Expected club for historical season picks / primes (Understat fallback when Sofascore blocked).
KNOWN_SEASON_CONTEXT: dict[int, dict[str, dict[str, str]]] = {
    21521: {"16/17": {"team": "Paris Saint-Germain", "league": "Ligue 1"}},
    4419: {"17/18": {"team": "Paris Saint-Germain", "league": "Ligue 1"}},
    17787: {"16/17": {"team": "Real Madrid", "league": "LaLiga"}},
    892219: {"18/19": {"team": "Real Betis", "league": "LaLiga"}},
    19438: {"15/16": {"team": "Napoli", "league": "Serie A"}},
    14933: {"15/16": {"team": "Atletico Madrid", "league": "LaLiga"}},
    16943: {"15/16": {"team": "Barcelona", "league": "LaLiga"}},
    91047: {"15/16": {"team": "Bayern Munich", "league": "Bundesliga"}},
    30027: {"13/14": {"team": "Real Madrid", "league": "LaLiga"}},
    13630: {"17/18": {"team": "Manchester City", "league": "Premier League"}},
    143697: {"17/18": {"team": "Liverpool", "league": "Premier League"}},
    124712: {"14/15": {"team": "Barcelona", "league": "LaLiga"}},
    34120: {"16/17": {"team": "Arsenal", "league": "Premier League"}},
    25682: {"16/17": {"team": "Monaco", "league": "Ligue 1"}},
    234148: {"16/17": {"team": "Chelsea", "league": "Premier League"}},
    750: {"14/15": {"team": "Real Madrid", "league": "LaLiga"}},
    12994: {"20/21": {"team": "Barcelona", "league": "LaLiga"}},
    152077: {"24/25": {"team": "Manchester City", "league": "Premier League"}},
    158213: {"22/23": {"team": "Manchester City", "league": "Premier League"}},
    827606: {"23/24": {"team": "Manchester City", "league": "Premier League"}},
    70996: {"19/20": {"team": "Manchester City", "league": "Premier League"}},
    122951: {"17/18": {"team": "Real Madrid", "league": "LaLiga"}},
    146219: {"14/15": {"team": "Real Madrid", "league": "LaLiga"}},
}


def known_season_context(player_id: int, season_suffix: str) -> dict[str, str] | None:
    ctx = KNOWN_SEASON_CONTEXT.get(player_id, {}).get(season_suffix)
    return dict(ctx) if ctx else None


def loose_name_key(name: str) -> str:
    return normalize_key(name).replace("'", "").replace("-", " ")


def names_loosely_match(a: str, b: str) -> bool:
    return loose_name_key(a) == loose_name_key(b)


def canonical_name(raw: str) -> str:
    key = normalize_key(raw)
    return ALIASES.get(key, str(raw).strip())


def known_sofascore_id(raw: str) -> int | None:
    for key in (normalize_key(raw), normalize_key(canonical_name(raw))):
        player_id = KNOWN_SOFASCORE_IDS.get(key)
        if player_id is not None:
            return player_id
    return None


def known_display_name(raw: str) -> str | None:
    player_id = known_sofascore_id(raw)
    if player_id is None:
        return None
    return KNOWN_DISPLAY_NAMES.get(player_id, canonical_name(raw))


def normalize_key(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name).strip())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s+", " ", text).lower()
    return text


def fuzzy_surname_match(raw: str, candidates: list[str], *, threshold: float = 0.82) -> str | None:
    """Match typo'd names when surname matches and given name is close (e.g. Jurien → Jurriën)."""
    parts = normalize_key(raw).split()
    if len(parts) < 2:
        return None
    surname = parts[-1]
    given = " ".join(parts[:-1])
    scored: list[tuple[str, float]] = []
    for name in candidates:
        name_parts = normalize_key(name).split()
        if len(name_parts) < 2 or name_parts[-1] != surname:
            continue
        given_name = " ".join(name_parts[:-1])
        score = difflib.SequenceMatcher(None, given, given_name).ratio()
        if score >= threshold:
            scored.append((name, score))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[1])
    if len(scored) == 1:
        return scored[0][0]
    if scored[0][1] - scored[1][1] >= 0.08:
        return scored[0][0]
    return None


def resolve_player_name(raw: str, store: StatsStore | None = None) -> str:
    """Map a raw Excel / user string to a canonical player name in the stats cache."""
    if not raw or str(raw).strip().lower() in {"", "nan", "none"}:
        raise ValueError("Empty player name")

    cleaned = str(raw).strip()
    key = normalize_key(cleaned)

    if key in ALIASES:
        return ALIASES[key]

    if store is not None:
        if cleaned in store.players:
            return cleaned
        for name in store.players:
            if names_loosely_match(cleaned, name):
                return name
        # Case-insensitive exact match
        for name in store.players:
            if normalize_key(name) == key:
                return name
        # Prefix / contains match (handles truncated Excel cells)
        matches = [
            name
            for name in store.players
            if normalize_key(name).startswith(key) or key.startswith(normalize_key(name))
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            matches.sort(key=lambda n: abs(len(normalize_key(n)) - len(key)))
            return matches[0]
        fuzzy = fuzzy_surname_match(cleaned, list(store.players))
        if fuzzy:
            return fuzzy

    return cleaned
