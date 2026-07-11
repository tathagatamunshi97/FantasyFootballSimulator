## Tournament press resistance ranking (higher = better)

Formula: mean of DEF/MID XI `_player_press_resistance` = `scale(dribbles90, 2.5) * scale(dribble_pct, 100) * (0.55 + 0.45 * slot_fit)` (FWD/GK excluded from the average).

**Lineup source:** Google Sheets roster → auto starting XI + slot assign for formation **4-3-3**; Round-3 peak seasons via `default_peak_season` (same path as `_transition_risk_rank.py`). Not manual lineups.

| Rank | Team | Press resistance | Top contributors (slot score) |
| ---: | --- | ---: | --- |
| 1 | DDR | 0.210 | Lamine Yamal (AM 0.54), Felix Nmecha (CM 0.29), Arda Güler (LW 0.25) |
| 2 | Chintu | 0.202 | Jérémy Doku (AM 0.58), Djed Spence (LB 0.30), Noussair Mazraoui (RB 0.16) |
| 3 | Rishav | 0.199 | Kingsley Coman (AM 0.53), Alejandro Balde (LB 0.29), Antoine Semenyo (RB 0.25) |
| 4 | Raktim | 0.191 | Takefusa Kubo (AM 0.48), Eberechi Eze (DM 0.36), Youri Tielemans (CM 0.15) |
| 5 | Moga+Sanmitro | 0.182 | Rayan Cherki (AM 0.46), Jude Bellingham (CM 0.35), Riccardo Calafiori (RB 0.18) |
| 6 | Subhadro+Shubhajit | 0.164 | Nuno Mendes (RB 0.34), Vitinha (Paris Saint-Germain) (AM 0.23), Guéla Doué (LB 0.19) |
| 7 | Sugata | 0.164 | Florian Wirtz (AM 0.45), Scott McTominay (DM 0.18), Theo Hernández (LB 0.15) |
| 8 | KP+SS | 0.163 | Jamal Musiala (AM 0.53), Alphonso Davies (LB 0.34), Luka Modrić (DM 0.12) |
| 9 | Kinjal+Sayan C | 0.127 | Michael Olise (AM 0.50), Jules Koundé (LB 0.16), João Neves (CM 0.15) |
| 10 | Anindo | 0.110 | Luis Díaz (AM 0.40), Josip Stanišić (LB 0.11), Declan Rice (CM 0.08) |
| 11 | Dilshad | 0.104 | Elliot Anderson (DM 0.26), Matheus Nunes (RB 0.18), Federico Valverde (CM 0.14) |
| 12 | Rohan + AnaC | 0.097 | Mateus Fernandes (CM 0.24), Mohamed Salah (AM 0.15), Micky van de Ven (CB2 0.09) |
| 13 | Ryan | 0.090 | Dominik Szoboszlai (AM 0.15), Bernardo Silva (CM 0.14), Alejandro Grimaldo (LB 0.13) |
| 14 | Sohom+Mayukh | 0.075 | Pedri (DM 0.35), Joshua Kimmich (CM 0.09), Federico Dimarco (AM 0.03) |
