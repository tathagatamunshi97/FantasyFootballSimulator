[07/09/26 13:06:31] INFO     No custom team name replacements      _config.py:92
                             found. You can configure these in                  
                             C:\Users\Admin\soccerdata\config\team              
                             name_replacements.json.                            
                    INFO     No custom league dict found. You can _config.py:190
                             configure additional leagues in                    
                             C:\Users\Admin\soccerdata\config\lea               
                             gue_dict.json.                                     
[07/09/26 13:06:33] INFO     Saving cached data to                _common.py:250
                             C:\Users\Admin\soccerdata\data\Under               
                             stat                                               
python : [2026-07-09 13:06:33] INFO     TLSLibrary:_load_library:397 - Successfully loaded TLS library: C:\Users\Admin\
AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\tls_requests\bin\tls-client-xgo-1.13.1-windows-amd64.dll
At C:\Users\Admin\AppData\Local\Temp\ps-script-8948cfa8-4acd-46a7-9136-b741a9b05089.ps1:109 char:158
+ ... YTHONIOENCODING='utf-8'; python _transition_risk_rank.py 2>&1 | Out-F ...
+                              ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: ([2026-07-09 13:...ndows-amd64.dll:String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
 
                    INFO     Successfully loaded TLS library:   libraries.py:397
                             C:\Users\Admin\AppData\Local\Pytho                 
                             n\pythoncore-3.14-64\Lib\site-pack                 
                             ages\tls_requests\bin\tls-client-x                 
                             go-1.13.1-windows-amd64.dll                        
## Tournament transition risk ranking (lower = safer)

Formula: max fullback/wingback exposure ├ù uncovered shielding; mid cover is formation-aware (equal three-mid block, dual-DM blend, or DM-heavy default).

| Rank | Team | Transition risk | Defensive quartet |
| ---: | --- | ---: | --- |
| 1 | Moga+Sanmitro | 0.142 | RB: Riccardo Calafiori, CB: R├║ben Dias, CB: Jo┼íko Gvardiol, LB: Jurri├½n Timber |
| 2 | Chintu | 0.173 | RB: Noussair Mazraoui, CB: Maxence Lacroix, CB: Malick Thiaw, LB: Djed Spence |
| 3 | Rohan + AnaC | 0.194 | RB: Nathaniel Brown, CB: Gabriel Magalh├úes, CB: Micky van de Ven, LB: Alessandro Bastoni |
| 4 | Dilshad | 0.197 | RB: Matheus Nunes, CB: Amir Rrahmani, CB: Kim Min-jae, LB: Nordi Mukiele |
| 5 | **Kinjal+Sayan C** | 0.218 | RB: Willian Pacho, CB: J├⌐r├⌐my Jacquet, CB: Diego God├¡n, LB: Jules Kound├⌐ |
| 6 | Anindo | 0.258 | RB: Edmond Tapsoba, CB: Pau Cubars├¡, CB: Dayot Upamecano, LB: Josip Stani┼íi─ç |
| 7 | DDR | 0.271 | RB: Konrad Laimer, CB: Marc Gu├⌐hi, CB: Jan Paul van Hecke, LB: ├ülvaro Carreras |
| 8 | Rishav | 0.275 | RB: Antoine Semenyo, CB: Marquinhos, CB: William Saliba, LB: Alejandro Balde |
| 9 | Subhadro+Shubhajit | 0.284 | RB: Nuno Mendes, CB: Ibrahima Konat├⌐, CB: Nico Schlotterbeck, LB: Gu├⌐la Dou├⌐ |
| 10 | Sugata | 0.316 | RB: Pedro Porro, CB: Matthijs de Ligt, CB: Diogo Dalot, LB: Theo Hern├índez |
| 11 | Sohom+Mayukh | 0.343 | RB: Dani Alves, CB: Francesco Acerbi, CB: Harry Maguire, LB: Antonio R├╝diger |
| 12 | KP+SS | 0.344 | RB: Reece James, CB: Dean Huijsen, CB: Aymeric Laporte, LB: Alphonso Davies |
| 13 | Ryan | 0.472 | RB: Marcos Llorente, CB: Virgil van Dijk, CB: Cristian Romero, LB: Alejandro Grimaldo |
| 14 | Raktim | 0.480 | RB: Achraf Hakimi, CB: Jonathan Tah, CB: David Raum, LB: Trent Alexander-Arnold |

**Kinjal+Sayan C** rank: **#5** of 14 (transition_risk **0.218**).

### Midfield cover (optional)

| Team | DM / CM / AM |
| --- | --- |
| Moga+Sanmitro | DM: Rodri; CM: Jude Bellingham; AM: Rayan Cherki |
| Chintu | DM: Nicol├▓ Barella; CM: Bruno Fernandes; AM: J├⌐r├⌐my Doku |
| Rohan + AnaC | DM: Aur├⌐lien Tchouam├⌐ni; CM: Mateus Fernandes; AM: Mohamed Salah |
| Dilshad | DM: Elliot Anderson; CM: Federico Valverde; AM: Hakan ├çalhano─ƒlu |
| Kinjal+Sayan C | DM: Casemiro; CM: Jo├úo Neves; AM: Michael Olise |
| Anindo | DM: Manuel Locatelli; CM: Declan Rice; AM: Luis D├¡az |
| DDR | DM: Ryan Gravenberch; CM: Felix Nmecha; AM: Lamine Yamal |
| Rishav | DM: Aleksandar Pavlovi─ç; CM: Kevin De Bruyne; AM: Kingsley Coman |
| Subhadro+Shubhajit | DM: N'Golo Kant├⌐; CM: Frenkie de Jong; AM: Vitinha (Paris Saint-Germain) |
| Sugata | DM: Scott McTominay; CM: ─░lkay G├╝ndo─ƒan; AM: Florian Wirtz |
| Sohom+Mayukh | DM: Pedri; CM: Joshua Kimmich; AM: Federico Dimarco |
| KP+SS | DM: Luka Modri─ç; CM: Giovani Lo Celso; AM: Jamal Musiala |
| Ryan | DM: Granit Xhaka; CM: Bernardo Silva; AM: Dominik Szoboszlai |
| Raktim | DM: Eberechi Eze; CM: Youri Tielemans; AM: Takefusa Kubo |
