## Tournament midfield ranking (higher = better)

**Primary sort key:** `UnitRatings.midfield` — mean across non-GK XI of `_player_midfield_contrib × slot midfield weight` (progression + creation + defensive mid work − turnover penalty, × slot fit). This is the engine's midfield unit used in overall strength / midfield battle.

**Secondary columns:** `midfield_defence` (ball-winning shield unit), `midfield_control` (TeamComposites blend of midfield + possession + mid-def).

**Lineup source:** Google Sheets roster → auto starting XI + slot assign for formation **4-3-3** (normalizes to attacking 4-3-3: DM/CM/AM); Round-3 peak seasons via `default_peak_season` (same path as press resistance / pressing intensity). Not manual lineups.

| Rank | Team | Midfield | Mid-def | Mid control | Midfield trio |
| ---: | --- | ---: | ---: | ---: | --- |
| 1 | Sohom+Mayukh | 0.725 | 0.343 | 0.651 | DM: Pedri; CM: Joshua Kimmich; AM: Federico Dimarco |
| 2 | Moga+Sanmitro | 0.702 | 0.411 | 0.644 | DM: Rodri; CM: Jude Bellingham; AM: Rayan Cherki |
| 3 | Kinjal+Sayan C | 0.687 | 0.457 | 0.656 | DM: Casemiro; CM: João Neves; AM: Michael Olise |
| 4 | Subhadro+Shubhajit | 0.679 | 0.548 | 0.692 | DM: N'Golo Kanté; CM: Frenkie de Jong; AM: Vitinha (Paris Saint-Germain) |
| 5 | Rishav | 0.643 | 0.291 | 0.587 | DM: Aleksandar Pavlović; CM: Kevin De Bruyne; AM: Kingsley Coman |
| 6 | Dilshad | 0.635 | 0.434 | 0.631 | DM: Elliot Anderson; CM: Federico Valverde; AM: Hakan Çalhanoğlu |
| 7 | Chintu | 0.620 | 0.297 | 0.544 | DM: Nicolò Barella; CM: Bruno Fernandes; AM: Jérémy Doku |
| 8 | Anindo | 0.615 | 0.416 | 0.620 | DM: Manuel Locatelli; CM: Declan Rice; AM: Luis Díaz |
| 9 | DDR | 0.609 | 0.442 | 0.600 | DM: Ryan Gravenberch; CM: Felix Nmecha; AM: Lamine Yamal |
| 10 | Ryan | 0.558 | 0.299 | 0.549 | DM: Granit Xhaka; CM: Bernardo Silva; AM: Dominik Szoboszlai |
| 11 | Sugata | 0.539 | 0.276 | 0.490 | DM: Scott McTominay; CM: İlkay Gündoğan; AM: Florian Wirtz |
| 12 | KP+SS | 0.533 | 0.317 | 0.535 | DM: Luka Modrić; CM: Giovani Lo Celso; AM: Jamal Musiala |
| 13 | Rohan + AnaC | 0.506 | 0.480 | 0.540 | DM: Aurélien Tchouaméni; CM: Mateus Fernandes; AM: Mohamed Salah |
| 14 | Raktim | 0.438 | 0.292 | 0.487 | DM: Eberechi Eze; CM: Youri Tielemans; AM: Takefusa Kubo |

### Per-slot midfield contrib (trio)

| Team | DM / CM / AM scores |
| --- | --- |
| Sohom+Mayukh | Pedri (DM 0.79), Joshua Kimmich (CM 0.82), Federico Dimarco (AM 0.57) |
| Moga+Sanmitro | Rodri (DM 0.72), Jude Bellingham (CM 0.63), Rayan Cherki (AM 0.76) |
| Kinjal+Sayan C | Casemiro (DM 0.53), João Neves (CM 0.74), Michael Olise (AM 0.79) |
| Subhadro+Shubhajit | N'Golo Kanté (DM 0.47), Frenkie de Jong (CM 0.87), Vitinha (Paris Saint-Germain) (AM 0.70) |
| Rishav | Aleksandar Pavlović (DM 0.69), Kevin De Bruyne (CM 0.60), Kingsley Coman (AM 0.64) |
| Dilshad | Elliot Anderson (DM 0.50), Federico Valverde (CM 0.71), Hakan Çalhanoğlu (AM 0.70) |
| Chintu | Nicolò Barella (DM 0.59), Bruno Fernandes (CM 0.65), Jérémy Doku (AM 0.62) |
| Anindo | Manuel Locatelli (DM 0.66), Declan Rice (CM 0.56), Luis Díaz (AM 0.62) |
| DDR | Ryan Gravenberch (DM 0.56), Felix Nmecha (CM 0.55), Lamine Yamal (AM 0.72) |
| Ryan | Granit Xhaka (DM 0.49), Bernardo Silva (CM 0.58), Dominik Szoboszlai (AM 0.60) |
| Sugata | Scott McTominay (DM 0.35), İlkay Gündoğan (CM 0.67), Florian Wirtz (AM 0.60) |
| KP+SS | Luka Modrić (DM 0.71), Giovani Lo Celso (CM 0.25), Jamal Musiala (AM 0.64) |
| Rohan + AnaC | Aurélien Tchouaméni (DM 0.66), Mateus Fernandes (CM 0.44), Mohamed Salah (AM 0.42) |
| Raktim | Eberechi Eze (DM 0.30), Youri Tielemans (CM 0.61), Takefusa Kubo (AM 0.40) |
