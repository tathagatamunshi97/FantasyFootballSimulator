"""Resolve player names from Excel / shorthand to canonical cache keys."""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sofascore_client import StatsStore

# Shorthand and Excel truncations -> canonical name in player_stats_cache.json
ALIASES: dict[str, str] = {
    "trent alexander ar": "Trent Alexander-Arnold",
    "trent alexander-arnold": "Trent Alexander-Arnold",
    "trent alexander arnold": "Trent Alexander-Arnold",
    "trent": "Trent Alexander-Arnold",
    "ayoub bouaddi": "Ayyoub Bouaddi",
    "ayyoub bouaddi": "Ayyoub Bouaddi",
    "bouaddi": "Ayyoub Bouaddi",
    "caiomhin kelleher": "Caoimhin Kelleher",
    "caoimhin kelleher": "Caoimhin Kelleher",
    "kelleher": "Caoimhin Kelleher",
    "christian romero": "Cristian Romero",
    "cristian romero": "Cristian Romero",
    "eliott anderson": "Elliot Anderson",
    "elliot anderson": "Elliot Anderson",
    "kim min jae": "Kim Min-jae",
    "kim min-jae": "Kim Min-jae",
    "min jae": "Kim Min-jae",
    "mateusz fernandes": "Mateus Fernandes",
    "mateus fernandes": "Mateus Fernandes",
    "matvei safonov": "Matvey Safonov",
    "matvey safonov": "Matvey Safonov",
    "safonov": "Matvey Safonov",
    "tijjiani reijnders": "Tijjani Reijnders",
    "tijjani reijnders": "Tijjani Reijnders",
    "reijnders": "Tijjani Reijnders",
    "warren zaire emery": "Warren Zaïre-Emery",
    "warren zaire-emery": "Warren Zaïre-Emery",
    "zaire emery": "Warren Zaïre-Emery",
    "yan sommer": "Yann Sommer",
    "yann sommer": "Yann Sommer",
    "sommer": "Yann Sommer",
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
    "eric garcia": "Eric García",
    "eric garcía": "Eric García",
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
    "guela doue": "Guéla Doué",
    "guéla doué": "Guéla Doué",
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
    "luis diaz": "Luis Díaz",
    "luis díaz": "Luis Díaz",
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
    "mesut ozil": "Mesut Özil",
    "mesut özil": "Mesut Özil",
    "ozil": "Mesut Özil",
    "özil": "Mesut Özil",
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
    "mohamed salah": "Mohamed Salah",
    "mohammed salah": "Mohamed Salah",
    "modric": "Luka Modrić",
    "modrić": "Luka Modrić",
    "luka modric": "Luka Modrić",
    "rudiger": "Antonio Rüdiger",
    "rüdiger": "Antonio Rüdiger",
    "antonio rudiger": "Antonio Rüdiger",
    "ruben dias": "Rúben Dias",
    "rúben dias": "Rúben Dias",
    "griezmann": "Antoine Griezmann",
    "antoine griezmann": "Antoine Griezmann",
    "harry maguire": "Harry Maguire",
    "maguire": "Harry Maguire",
    "manuel neuer": "Manuel Neuer",
    "david alaba": "Alaba",
    "aymeric laporte": "Aymeric Laporte",
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
    "carvajal": "Carvajal",
    "dani carvajal": "Carvajal",
    "bounou": "Yassine Bounou",
    "tchouameni": "Aurélien Tchouaméni",
    "alisson": "Alisson",
    "el kaabi": "Ayoub El Kaabi",
    "aymen el kaabi": "Ayoub El Kaabi",
    "ayoub el kaabi": "Ayoub El Kaabi",
    "bernard": "Bernardo Silva",
    "bernardo": "Bernardo Silva",
    "bernardo silva": "Bernardo Silva",
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
    "alaba": "Alaba",
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
    "ilkay gündogan": "İlkay Gündoğan",
    "gyokeres": "Viktor Gyökeres",
    "viktor gyokeres": "Viktor Gyökeres",
    "eder militao": "Éder Militão",
    "éder militão": "Éder Militão",
    "militao": "Éder Militão",
    "tapsoba": "Edmond Tapsoba",
    "edmond tapsoba": "Edmond Tapsoba",
    "rrahmani": "Amir Rrahmani",
    "amir rrahmani": "Amir Rrahmani",
    "alex grimaldo": "Alejandro Grimaldo",
    "alejandro grimaldo": "Alejandro Grimaldo",
    "álex grimaldo": "Alejandro Grimaldo",
    "grimaldo": "Alejandro Grimaldo",
    "sean lammens": "Senne Lammens",
    "senne lammens": "Senne Lammens",
    "lammens": "Senne Lammens",
    "stones": "John Stones",
    "john stones": "John Stones",
    "mahrez": "Riyad Mahrez",
    "riyad mahrez": "Riyad Mahrez",
    "cole palmer": "Cole Palmer",
    "palmer": "Cole Palmer",
    "alexander sorloth": "Alexander Sørloth",
    "sorloth": "Alexander Sørloth",
    "el kaabi": "Ayoub El Kaabi",
    "ayoub el kaabi": "Ayoub El Kaabi",
    "aymen el kaabi": "Ayoub El Kaabi",
    "diogo costa": "Diogo Costa",
    "ismael saibari": "Ismael Saibari",
    "saibari": "Ismael Saibari",
    "jamie vardy": "Jamie Vardy",
    "vardy": "Jamie Vardy",
    "francesco acerbi": "Francesco Acerbi",
    "fran acerbi": "Francesco Acerbi",
    "acerbi": "Francesco Acerbi",
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
    "bernardo silva": 331209,
    "grimaldo": 177177,
    "alex grimaldo": 177177,
    "alejandro grimaldo": 177177,
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
    "mesut ozil": 16176,
    "mesut özil": 16176,
    "ozil": 16176,
    "özil": 16176,
    "rodri": 827606,
    "rodri hernandez": 827606,
    "kevin de bruyne": 70996,
    "kdb": 70996,
    "casemiro": 122951,
    "cole palmer": 982780,
    "palmer": 982780,
    "ismael saibari": 1063767,
    "saibari": 1063767,
    "alexander sorloth": 309078,
    "sorloth": 309078,
    "diogo costa": 843115,
    "carvajal": 138572,
    "dani carvajal": 138572,
    "ruben dias": 614446,
    "rúben dias": 614446,
    "mohamed salah": 159665,
    "mohammed salah": 159665,
    "salah": 159665,
    "griezmann": 8574,
    "antoine griezmann": 8574,
    "rudiger": 86202,
    "rüdiger": 86202,
    "antonio rudiger": 86202,
    "harry maguire": 14992,
    "maguire": 14992,
    "modric": 15466,
    "modrić": 15466,
    "luka modric": 15466,
    "neuer": 75407,
    "manuel neuer": 75407,
    "alaba": 66492,
    "david alaba": 66492,
    "laporte": 149734,
    "aymeric laporte": 149734,
    "cr7": 750,
    "hakimi": 814594,
    "achraf hakimi": 814594,
    "jamie vardy": 173827,
    "vardy": 173827,
    "francesco acerbi": 126816,
    "fran acerbi": 126816,
    "acerbi": 126816,
}

# Bypass FotMob search when names are ambiguous or search terms fail.
KNOWN_FOTMOB_IDS: dict[str, int] = {
    "alaba": 121633,
    "david alaba": 121633,
    "gabriel magalhaes": 795179,
    "marcelo": 28467,
    "kenan yildiz": 1412132,
    "kenan y ld z": 1412132,
    "pape matar sarr": 1107280,
    "pape sarr": 1107280,
    "eli junior kroupi": 1460534,
    "junior kroupi": 1460534,
    "hakimi": 770881,
    "achraf hakimi": 770881,
    "jamie vardy": 286119,
    "vardy": 286119,
    "francesco acerbi": 73024,
    "fran acerbi": 73024,
    "acerbi": 73024,
}

# Primary slot codes when FBref/Sofascore bucket wingers as ST or generic MF/F.
KNOWN_PLAYER_PRIMARY: dict[int, dict[str, Any]] = {
    30027: {
        "primary_position": "RW",
        "fpl_position": "FWD",
        "positions": ["RW", "LW", "RM"],
    },
    827606: {
        "primary_position": "DM",
        "fpl_position": "MID",
        "positions": ["DM", "CM", "CB"],
    },
    4419: {
        "primary_position": "RB",
        "fpl_position": "DEF",
        "positions": ["RB", "RM"],
    },
    17787: {
        "primary_position": "LB",
        "fpl_position": "DEF",
        "positions": ["LB", "LM"],
    },
    138572: {
        "primary_position": "RB",
        "fpl_position": "DEF",
        "positions": ["RB", "RM"],
    },
    892219: {
        "primary_position": "CAM",
        "fpl_position": "MID",
        "positions": ["CAM", "CM"],
    },
    158213: {
        "primary_position": "RW",
        "fpl_position": "MID",
        "positions": ["RW", "LW", "RM"],
    },
    34120: {
        "primary_position": "LW",
        "fpl_position": "FWD",
        "positions": ["LW", "ST", "RW", "CM"],
    },
    124712: {
        "primary_position": "LW",
        "fpl_position": "FWD",
        "positions": ["LW", "RW", "ST", "CM"],
    },
    177177: {
        "primary_position": "LB",
        "fpl_position": "DEF",
        "positions": ["LB", "LM", "LW", "CM"],
    },
    814594: {
        "primary_position": "RB",
        "fpl_position": "DEF",
        "positions": ["RB", "RWB", "RM"],
    },
    173827: {
        "primary_position": "ST",
        "fpl_position": "FWD",
        "positions": ["ST"],
    },
    126816: {
        "primary_position": "CB",
        "fpl_position": "DEF",
        "positions": ["CB"],
    },
    331209: {
        "primary_position": "CM",
        "fpl_position": "MID",
        "positions": ["CM", "AM", "RW", "LW"],
    },
}

# Curated positions for players mis-tagged in cache / FBref (keyed by canonical cache name).
KNOWN_PLAYER_POSITIONS_BY_NAME: dict[str, dict[str, Any]] = {
    "Dayot Upamecano": {
        "primary_position": "CB",
        "fpl_position": "DEF",
        "positions": ["CB"],
    },
    "Pau Cubarsí": {
        "primary_position": "CB",
        "fpl_position": "DEF",
        "positions": ["CB"],
    },
    "Dean Huijsen": {
        "primary_position": "CB",
        "fpl_position": "DEF",
        "positions": ["CB"],
    },
    "Eric García": {
        "primary_position": "CB",
        "fpl_position": "DEF",
        "positions": ["CB", "CM"],
    },
    # FBref/Sofascore often label Díaz as CM; he is a natural wide forward.
    "Luis Díaz": {
        "primary_position": "LW",
        "fpl_position": "MID",
        "positions": ["LW", "RW", "LM"],
    },
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
    982780: "M",
    614446: "D",
    159665: "F",
    8574: "F",
    814594: "D",
    173827: "F",
    126816: "D",
    86202: "D",
    14992: "D",
    15466: "M",
    75407: "G",
    66492: "D",
    149734: "D",
    138572: "D",
    16176: "M",
    21521: "F",
    4419: "D",
    17787: "D",
    892219: "M",
    19438: "F",
    14933: "D",
    16943: "F",
    91047: "M",
    13630: "M",
    143697: "F",
    34120: "F",
    25682: "F",
    30027: "M",
}


KNOWN_DISPLAY_NAMES: dict[int, str] = {
    234148: "N'Golo Kanté",
    750: "Cristiano Ronaldo",
    12994: "Lionel Messi",
    614446: "Rúben Dias",
    159665: "Mohamed Salah",
    8574: "Antoine Griezmann",
    86202: "Antonio Rüdiger",
    14992: "Harry Maguire",
    15466: "Luka Modrić",
    75407: "Manuel Neuer",
    66492: "Alaba",
    149734: "Aymeric Laporte",
    138572: "Carvajal",
    982780: "Cole Palmer",
    814594: "Achraf Hakimi",
    173827: "Jamie Vardy",
    126816: "Francesco Acerbi",
    16176: "Mesut Özil",
    21521: "Edinson Cavani",
    4419: "Dani Alves",
    17787: "Marcelo",
    892219: "Giovanni Lo Celso",
    19438: "Gonzalo Higuaín",
    14933: "Diego Godín",
    16943: "Luis Suárez",
    91047: "Arturo Vidal",
    13630: "Fernandinho",
    143697: "Roberto Firmino",
    34120: "Alexis Sánchez",
    25682: "Radamel Falcao",
    30027: "Ángel Di María",
    124712: "Neymar",
    158213: "Riyad Mahrez",
    152077: "John Stones",
    827606: "Rodri",
    122951: "Casemiro",
    70996: "Kevin De Bruyne",
    331209: "Bernardo Silva",
    45853: "İlkay Gündoğan",
    822519: "Éder Militão",
    177177: "Alejandro Grimaldo",
    309078: "Alexander Sørloth",
    843115: "Diogo Costa",
    919793: "Ayoub El Kaabi",
    1063767: "Ismael Saibari",
}

KNOWN_PRIME_SEASON_SUFFIX: dict[int, str] = {
    234148: "16/17",
    750: "14/15",
    12994: "14/15",
    152077: "22/23",  # City title season (1852' PL; 24/25 only 539')
    158213: "22/23",
    827606: "23/24",
    70996: "19/20",
    124712: "14/15",
    146219: "14/15",
    122951: "17/18",
    982780: "23/24",
    614446: "20/21",
    138572: "16/17",
    159665: "17/18",
    8574: "15/16",
    86202: "21/22",
    14992: "18/19",
    15466: "17/18",
    149734: "21/22",
    75407: "13/14",
    66492: "19/20",
    814594: "20/21",  # Inter Scudetto season (manual prime)
    173827: "15/16",  # Leicester title season (24 PL goals)
    126816: "19/20",  # Lazio Serie A peak (36 apps, 3162', rating 7.25)
    # Round-3 season-pick players (also usable as primes)
    21521: "16/17",
    4419: "17/18",
    17787: "16/17",
    892219: "18/19",
    19438: "15/16",
    14933: "15/16",
    16943: "15/16",
    91047: "15/16",
    13630: "17/18",
    143697: "17/18",
    34120: "16/17",
    25682: "16/17",
    30027: "13/14",
    16176: "15/16",  # Arsenal PL peak (assists)
    331209: "21/22",  # Bernardo Silva Man City
    45853: "23/24",  # Gundogan Barcelona
    822519: "21/22",  # Eder Militao Real Madrid
    177177: "23/24",  # Grimaldo Leverkusen title season
    309078: "24/25",  # Sørloth (cache blend; no top-5 Understat peak wired)
    843115: "24/25",  # Diogo Costa
    919793: "24/25",  # El Kaabi
    1063767: "24/25",  # Saibari
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
    12994: {"14/15": {"team": "Barcelona", "league": "LaLiga"}},
    152077: {"22/23": {"team": "Manchester City", "league": "Premier League"}, "24/25": {"team": "Manchester City", "league": "Premier League"}},
    158213: {"22/23": {"team": "Manchester City", "league": "Premier League"}},
    827606: {"23/24": {"team": "Manchester City", "league": "Premier League"}},
    70996: {"19/20": {"team": "Manchester City", "league": "Premier League"}},
    122951: {"17/18": {"team": "Real Madrid", "league": "LaLiga"}},
    146219: {"14/15": {"team": "Real Madrid", "league": "LaLiga"}},
    982780: {"23/24": {"team": "Chelsea", "league": "Premier League"}},
    614446: {"20/21": {"team": "Manchester City", "league": "Premier League"}},
    138572: {"16/17": {"team": "Real Madrid", "league": "LaLiga"}},
    159665: {"17/18": {"team": "Liverpool", "league": "Premier League"}},
    8574: {"15/16": {"team": "Atletico Madrid", "league": "LaLiga"}},
    86202: {"21/22": {"team": "Chelsea", "league": "Premier League"}},
    14992: {"18/19": {"team": "Leicester City", "league": "Premier League"}},
    15466: {"17/18": {"team": "Real Madrid", "league": "LaLiga"}},
    149734: {
        "20/21": {"team": "Manchester City", "league": "Premier League"},
        "21/22": {"team": "Manchester City", "league": "Premier League"},
    },
    75407: {"13/14": {"team": "Bayern Munich", "league": "Bundesliga"}},
    66492: {"19/20": {"team": "Bayern Munich", "league": "Bundesliga"}},
    814594: {
        "19/20": {"team": "Borussia Dortmund", "league": "Bundesliga"},
        "20/21": {"team": "Inter", "league": "Serie A"},
    },
    173827: {"15/16": {"team": "Leicester City", "league": "Premier League"}},
    126816: {"19/20": {"team": "Lazio", "league": "Serie A"}},
    16176: {"15/16": {"team": "Arsenal", "league": "Premier League"}},
    331209: {"21/22": {"team": "Manchester City", "league": "Premier League"}},
    45853: {"23/24": {"team": "Barcelona", "league": "LaLiga"}},
    822519: {"21/22": {"team": "Real Madrid", "league": "LaLiga"}},
    177177: {"23/24": {"team": "Bayer Leverkusen", "league": "Bundesliga"}},
    309078: {"24/25": {"team": "Atletico Madrid", "league": "LaLiga"}},
    843115: {"24/25": {"team": "FC Porto", "league": "Primeira Liga"}},
    919793: {"24/25": {"team": "Olympiacos", "league": "Super League Greece"}},
    1063767: {"24/25": {"team": "PSV Eindhoven", "league": "Eredivisie"}},
}


def known_season_context(player_id: int, season_suffix: str) -> dict[str, str] | None:
    ctx = KNOWN_SEASON_CONTEXT.get(player_id, {}).get(season_suffix)
    return dict(ctx) if ctx else None


def apply_known_position_overrides(data: dict[str, Any], player_id: int | None) -> None:
    """Apply curated primary/fpl positions for players mis-tagged by FBref."""
    if player_id is None:
        return
    override = KNOWN_PLAYER_PRIMARY.get(int(player_id))
    if override:
        data.update(override)


def apply_known_position_overrides_by_name(data: dict[str, Any], player_name: str) -> None:
    """Apply curated positions keyed by canonical cache player name."""
    override = KNOWN_PLAYER_POSITIONS_BY_NAME.get(str(player_name).strip())
    if override:
        data.update(override)


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


def known_fotmob_id(raw: str) -> int | None:
    from understat_client import normalize_name

    for key in (
        normalize_key(raw),
        normalize_key(canonical_name(raw)),
        normalize_name(raw),
        normalize_name(canonical_name(raw)),
    ):
        player_id = KNOWN_FOTMOB_IDS.get(key)
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
        aliased = ALIASES[key]
        if store is None or aliased in store.players:
            return aliased

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
            # Prefer the longest (most specific) name when Excel truncates e.g. "Bernardo" → Bernardo Silva.
            matches.sort(
                key=lambda n: (-len(normalize_key(n)), abs(len(normalize_key(n)) - len(key)))
            )
            return matches[0]
        fuzzy = fuzzy_surname_match(cleaned, list(store.players))
        if fuzzy:
            return fuzzy

    return cleaned
