## Tournament pressing intensity ranking (higher = more intense)

Formula: `pressing_base = scale(avg(tackles90+interceptions90), 4.5)` then `pressing_intensity = clamp(pressing_base * 0.72 + scale(avg_duel_won_pct, 100) * 0.28)` when duel% available (else full weight on pressing_base). Full XI average.

**Lineup source:** Google Sheets roster → auto starting XI + slot assign for formation **4-3-3**; Round-3 peak seasons via `default_peak_season` (same path as `_press_resistance_rank.py` / `_transition_risk_rank.py`). Not manual lineups.

| Rank | Team | Pressing intensity | Top contributors (T+I) |
| ---: | --- | ---: | --- |
| 1 | Subhadro+Shubhajit | 0.558 | N'Golo Kanté (DM T+I 5.7, duel% 56), Frenkie de Jong (CM T+I 3.4, duel% 67), Guéla Doué (LB T+I 3.3, duel% 56) |
| 2 | Kinjal+Sayan C | 0.536 | Diego Godín (CB2 T+I 5.1), Casemiro (DM T+I 4.2, duel% 53), Willian Pacho (RB T+I 3.5, duel% 62) |
| 3 | DDR | 0.516 | Ryan Gravenberch (DM T+I 3.4, duel% 57), Álvaro Carreras (LB T+I 3.1, duel% 54), Felix Nmecha (CM T+I 3.0, duel% 57) |
| 4 | Dilshad | 0.498 | Elliot Anderson (DM T+I 4.0, duel% 54), Nordi Mukiele (LB T+I 3.5, duel% 58), Kim Min-jae (CB2 T+I 3.1) |
| 5 | Chintu | 0.492 | Noussair Mazraoui (RB T+I 4.7, duel% 62), Maxence Lacroix (CB1 T+I 3.3, duel% 60), Djed Spence (LB T+I 3.0, duel% 51) |
| 6 | Rohan + AnaC | 0.488 | Mateus Fernandes (CM T+I 3.9, duel% 55), Nathaniel Brown (RB T+I 3.8, duel% 58), Aurélien Tchouaméni (DM T+I 3.5, duel% 67) |
| 7 | Sohom+Mayukh | 0.473 | Dani Alves (RB T+I 3.5), Pedri (DM T+I 2.9, duel% 59), Harry Maguire (CB2 T+I 2.7, duel% 68) |
| 8 | KP+SS | 0.472 | Reece James (RB T+I 3.7, duel% 59), Luka Modrić (DM T+I 2.9, duel% 53), Dean Huijsen (CB1 T+I 2.7, duel% 59) |
| 9 | Raktim | 0.472 | Trent Alexander-Arnold (LB T+I 3.9, duel% 47), Mikel Merino (LW T+I 3.4, duel% 48), Youri Tielemans (CM T+I 3.4, duel% 59) |
| 10 | Anindo | 0.457 | Manuel Locatelli (DM T+I 3.6, duel% 58), Dayot Upamecano (CB2 T+I 3.4, duel% 57), Declan Rice (CM T+I 2.8, duel% 56) |
| 11 | Sugata | 0.456 | Pedro Porro (RB T+I 3.5, duel% 51), Diogo Dalot (CB2 T+I 3.1, duel% 57), Matthijs de Ligt (CB1 T+I 2.7, duel% 64) |
| 12 | Moga+Sanmitro | 0.452 | Rodri (DM T+I 3.3, duel% 67), Jurriën Timber (LB T+I 3.1, duel% 56), Jude Bellingham (CM T+I 3.1, duel% 57) |
| 13 | Ryan | 0.439 | Cristian Romero (CB2 T+I 3.9, duel% 64), Marcos Llorente (RB T+I 3.2, duel% 57), Bernardo Silva (CM T+I 2.5) |
| 14 | Rishav | 0.382 | Aleksandar Pavlović (DM T+I 2.6, duel% 55), William Saliba (CB2 T+I 2.1, duel% 61), Marquinhos (CB1 T+I 2.1, duel% 61) |
