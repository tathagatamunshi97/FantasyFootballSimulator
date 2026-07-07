#!/usr/bin/env python3
"""Generate Excel matchup file for Team A vs Team B (from user roster)."""
from __future__ import annotations

from pathlib import Path

from excel_loader import write_excel_template

TEAM_A = {
    "name": "Team A",
    "formation": "4-3-3 flat",
    "captain": "Kylian Mbappé",
    "vice_captain": "Lamine Yamal",
    "players": [
        "David Raya",
        "Piero Hincapié",
        "Pau Cubarsí",
        "William Saliba",
        "Jules Koundé",
        "Vitinha",
        "Pedri",
        "Bruno Guimarães",
        "Kylian Mbappé",
        "Kai Havertz",
        "Lamine Yamal",
    ],
}

TEAM_B = {
    "name": "Team B",
    "formation": "4-2-3-1",
    "captain": "Bruno Fernandes",
    "vice_captain": "Erling Haaland",
    "players": [
        "Joan García",
        "Nuno Mendes",
        "Gabriel Magalhães",
        "Dayot Upamecano",
        "Achraf Hakimi",
        "Declan Rice",
        "João Neves",
        "Bruno Fernandes",
        "Khvicha Kvaratskhelia",
        "Erling Haaland",
        "Ousmane Dembélé",
    ],
}


def main() -> None:
    out = Path(__file__).resolve().parent / "data" / "team_a_vs_b.xlsx"
    write_excel_template(out, TEAM_A, TEAM_B)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
