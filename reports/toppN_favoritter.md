# Topp-N-favoritter per runde — hvor mange går inn, og finnes det en kant?

_Spørsmål (Leif, 2026-09-05): plukk de 10/15/20/25 mest sannsynlige kampene hver runde og sett dem samtidig —
hvor mange går vanligvis som oddsen sier, og kan det gi en kant?_

Datagrunnlag: 102 983 hovedtour-kamper (ATP 2005–2026, WTA 2007–2026) med closing-odds fra tennis-data.co.uk
(Pinnacle som primærbok, Bet365 der Pinnacle mangler: 2009 og nesten hele 2026; markedssnitt og beste pris fra 2010).
Retired = void (odds 1,00) som hovedregel — slik Pinnacle, Bet365 og Norsk Tipping gjør opp.
Åtte uavhengige analyser, hver etterregnet av 1–2 uavhengige kontrollører. Bare tall som er bekreftet står her.

## Svaret kort

- **Oddsen er kalibrert.** Favorittene går inn nøyaktig så ofte som prisen sier — i alle perioder, begge tourer,
  alle styrkenivåer. Det finnes ingen gruppe favoritter som systematisk «går inn oftere enn oddsen sier».
- **Topp-10 per dag: 7,6 av 10 går inn** (alle 10 på 14 % av dagene). Topp-15: 11,1 (alle på 4,8 %). Topp-20:
  14,7 (1,9 %). Topp-25: 18,2 (0,9 %). Problemet er at den 10. sterkeste favoritten på en vanlig dag bare er en
  67 %-favoritt, og den 25. en 59 %-favoritt — da er kupongen dømt til å ryke.
- **Ingen kant.** Enkeltspill på favorittene taper ca. 1,4 % hos Pinnacle og 3–4 % hos en vanlig bok. En kupong
  ganger opp dette tapet: 10-kombinasjon på dagens topp-10 taper 5–6 % hos Pinnacle og ca. 24 % hos Bet365; 25-
  kombinasjon taper 76–85 %. Systemspill endrer variansen, ikke forventningen.
- **Nærmest break-even:** bare favoritter med P ≥ 0,85–0,90 (2–3 kamper per dag) hos Pinnacle, som singler eller
  kombo: ROI −0,2 til +0,1 %. Det er null, ikke pluss.
- **Prosjektets egen modell hjelper ikke:** markedets rangering treffer 3,4 prosentpoeng oftere per kamp enn
  modellens, og der modellen er uenig med markedet har markedet rett.

## 1. Hvor mange av topp-N går inn (kalenderdag, ATP+WTA samlet, 2005–2026)

Topp-N = de N kampene med høyest de-vigget Pinnacle-sannsynlighet den dagen. Bare dager med minst N kamper teller.

| N | Dager | Snitt treff (av avgjorte) | Forventet fra oddsen | Alle inn | Maks 1 tap | Maks 2 tap | Median P for N-te pick | Median samlet odds |
|---|---|---|---|---|---|---|---|---|
| 10 | 3 985 | 7,62 av 9,71 (78,5 %) | 78,6 % | 14,0 % | 37,9 % | 64,1 % | 0,675 | 10,7 |
| 15 | 3 033 | 11,12 av 14,54 (76,4 %) | 76,4 % | 4,9 % | 16,0 % | 33,5 % | 0,625 | 61 |
| 20 | 1 970 | 14,70 av 19,38 (75,8 %) | 75,8 % | 1,9 % | 6,9 % | 18,4 % | 0,608 | 301 |
| 25 | 1 370 | 18,20 av 24,23 (75,1 %) | 75,1 % | 0,9 % | 3,7 % | 9,1 % | 0,589 | 1 573 |

«Forventet» er regnet med potens-de-vigging (den som passer utfallene best). Observert og forventet er like innenfor
±0,3 prosentpoeng for alle N — markedet er kalibrert. (Proporsjonal de-vigging, som prosjektet bruker i dag, gir
1–2 pp «for lav» forventning for sterke favoritter; det er en regnefeil i de-viggingen, ikke en kant. Se pkt. 7.)

Fordeling av antall tap per dag:

| N | 0 tap | 1 | 2 | 3 | 4 | 5 | 6+ |
|---|---|---|---|---|---|---|---|
| 10 | 14 % | 24 % | 26 % | 19 % | 11 % | 4 % | 2 % |
| 15 | 5 % | 11 % | 18 % | 21 % | 18 % | 14 % | 14 % |
| 20 | 2 % | 5 % | 12 % | 14 % | 17 % | 16 % | 35 % |
| 25 | 1 % | 3 % | 5 % | 9 % | 11 % | 14 % | 57 % |

Stabilt over tid: andelen dager der alle 10 går inn var 15,8 % (2005–2015), 12,1 % (2016–2020), 12,5 % (2021–2026),
og forventningen fulgte med ned fordi oddsen er blitt jevnere (færre storfavoritter), ikke fordi kalibreringen er dårligere.
Utfallene innen en dag er uavhengige: variansen i antall treff er 0,96–1,07 av det uavhengighet tilsier (≈ 1), overraskelser
klynger seg ikke (samme turnering, underlag eller tour), og det finnes ingen «gode og dårlige uker».

## 2. Andre måter å definere «runde» på

| Gruppering | Runder/år | P for 10. pick | Alle 10 inn | Kommentar |
|---|---|---|---|---|
| Kalenderdag, begge tourer | ~182 | 0,675 | 14,0 % | Det Leif faktisk kan sette kvelden før |
| Kalenderdag per tour | ~200 | 0,624 | 9,8 % | Svakest |
| Turnering × runde | ~155 | 0,643 | 12,4 % | Ikke bedre enn dag |
| Kalenderuke, begge tourer | ~44 | 0,843 | 39,8 % | **Ikke settbart**: 64 % av pickene er runde 2+ som ikke finnes mandag |
| Grand Slam runde 1, begge tourer | 4 | 0,925 | 83,7 % | 86 runder; spilles over 2–4 dager |
| Grand Slam R1–R2-dager | ~17 | 0,851 | 47,2 % | 375 dager; eneste dager med 10–25 sterke favoritter |

Grand Slam-dagene er den eneste situasjonen der det finnes 10–25 sterke favoritter samtidig (snitt 14 favoritter med
P ≥ 0,80 per dag mot 3,2 på en vanlig dag). På slike dager går alle topp-10 inn 47 % av gangene, alle topp-15 23 %,
alle topp-20 10 %, alle topp-25 3,5 % — nøyaktig som oddsen tilsier. Kombo-ROI på GS-dagene: +0,4 % (topp-10, KI
−12 til +13), −18 % (topp-20), −48 % (topp-25). Slam runde 1 med begge tourer samlet viser +15 % på 10-kombo, men
det er ett av 166 testede oppsett, finnes ikke per tour, ikke i runde 2, og favorittene i den samme populasjonen
gir −0,3 % som singler. Støy, ikke kant.

## 3. Hva oddsen sier vs. hva som skjer (favoritter, Pinnacle closing)

| Favorittens P (de-vigget) | n | Vant | Rå 1/odds | Flat ROI Pinnacle | Flat ROI Bet365 |
|---|---|---|---|---|---|
| 0,50–0,60 | 25 248 | 55,0 % | 56,8 % | −3,0 % | −7,3 % |
| 0,60–0,70 | 26 063 | 65,3 % | 66,4 % | −1,8 % | −5,2 % |
| 0,70–0,80 | 20 635 | 76,0 % | 76,5 % | −0,7 % | −3,4 % |
| 0,80–0,85 | 7 382 | 83,4 % | 84,3 % | −1,1 % | −3,6 % |
| 0,85–0,90 | 5 728 | 89,5 % | 89,3 % | +0,3 % | −1,7 % |
| 0,90–1,00 | 5 243 | 95,5 % | 95,3 % | +0,2 % | −0,7 % |
| **P ≥ 0,85 samlet** | 10 971 | 92,4 % | 92,2 % | +0,2 % [−0,3; +0,8] | −1,2 % [−1,8; −0,7] |

Alle kamper med Pinnacle-odds 2005–2026 (retired void); Bet365-kolonnen er samme kamper til Bet365s pris.

Pinnacle legger nesten hele marginen på underdog-siden: sterke favoritter (P ≥ 0,85) prises rått riktig, så kostnaden
per ledd er ≈ 0 (±0,8 pp) ved closing. Bet365 legger 2,3–4,3 pp margin på favorittsiden — negativt i alle bånd, også
de sterkeste. Svake favoritter (odds over 1,50) taper 2,5–3,2 % selv hos Pinnacle. Beste pris i markedet (Max over
mange bøker) gir +1,4 % på P ≥ 0,85 — men det er prisgapet Pinnacle→beste bok, og en kupong må ligge hos én bok.

Om morgenen (Pinnacle-snapshots 9.7–5.9.2026, 971 koblede hovedtour-kamper, 90 %): morgenoddsen er like godt kalibrert som closing,
morgenfavoritten er den samme som closingfavoritten i 98 % av kampene (alle byttene er i 50–60 %-kamper), og
CLV for morgenfavoritten er −2,75 % — nøyaktig morgen-vigen (3,3 % mot 2,9 % ved closing). Det finnes ingen
«feilpriset favoritt» å ta om morgenen; kostnaden per ledd er ca. 0,4–0,6 pp høyere enn ved closing.

## 4. Kombinasjonsøkonomi (topp-N per dag, realisert ROI 2005–2026)

| N | Singler (primærbok) | Kombo Pinnacle | Kombo Bet365 | Vinnerdager | Lengste tapsrekke (dager) |
|---|---|---|---|---|---|
| 3 | | −1,3 % | −7,9 % | | |
| 5 | −0,8 % | −3,0 % (−4,3 % inkl. B365-dager) | −13,5 % | 41,5 % | |
| 8 | −1,5 % | −3,9 % | −20,1 % | 21,1 % | |
| 10 | −1,4 % | −5,0 % [−16; +7] | −23,9 % | 13,6 % | 50 |
| 15 | −1,4 % | −30 % (−18 % inkl. B365-dager) | −38 % | 4,8 % | 128 |
| 20 | −1,3 % | −49 % | −67 % | 1,9 % | 161 |
| 25 | −1,4 % | −73 % | −85 % | 0,9 % | 247 |

Singler-kolonnen inkluderer Bet365-dagene (2009/2026); kun Pinnacle-dager er 0,3–0,4 pp mindre negativt (N=10: −1,0 %).
Regelen: kombo-ROI ≈ (1 + singel-ROI)^N − 1. Med −1,4 % per ledd hos Pinnacle gir 10 ledd −13 % forventet, 25 ledd −30 %;
med −3,5 % per ledd hos en vanlig bok gir 10 ledd −30 % og 25 ledd −59 %. Realisert er enda verre for N ≥ 15 fordi de
svakeste leddene (P 0,5–0,65) er de dyreste. Bet365-tallene er nærmeste proxy for Norsk Tipping/nordiske bøker
(høyere margin på favoritter); Norsk Tipping er ikke i datasettet.

Systemspill (k-av-N, f.eks. 7/8/9/10 av 10): flere gevinstdager (28 % netto pluss, 83 % minst én rekke inn) og lavere
varians, men samme ROI som per-ledd-marginen tilsier: −5 % hos Pinnacle, −20 % hos Bet365.

Terskel i stedet for fast N (alle favoritter med P ≥ 0,85 den dagen som én kupong, snitt 3–4 kamper): Pinnacle
+0,1 % [−2,8; +3,1], per periode −0,3 / +1,4 / +0,2 %; P ≥ 0,90: −0,1 til −1,0 %. Break-even. Hos Bet365 negativt.

Retired teller: hvis boka avgjør kampen etter ett sett i stedet for å annullere, blir alt tydelig verre (10-kombo
Pinnacle −5 % → −11 %), fordi det uforholdsmessig ofte er favoritten som trekker seg.

## 5. Modell vs. marked (70 048 kamper 2010–2026 der begge finnes)

| Rangering per dag | Topp-10 treff | Alle 10 inn | ROI singler (Bet365) |
|---|---|---|---|
| Marked (Pinnacle) | 7,52 | 11,6 % | −3,4 % |
| Blanding 0,7/0,3 (produksjon) | 7,50 | 12,4 % | −3,4 % |
| Modell (Elo) | 7,17 | 8,1 % | −3,9 % |

Modellens valg vinner 3,4 prosentpoeng sjeldnere per kamp uansett N. Gitt markedets P tilfører modellen ingen
informasjon (koeffisient −0,03, aldri positiv). Der modellen er uenig med markedet (14 % av kampene) vinner markeds-
favoritten 59,0 % — nøyaktig markedets 58,4 %, langt fra modellens 43,8 %; å følge modellen der gir −8 %.
Konsensusfilter (bare kamper der modellen er enig) endrer ingenting.

## 6. Konklusjon og anbefaling

1. **Ikke sett 10/15/20/25-kombinasjoner på dagens mest sannsynlige kamper.** Forventet tap er 5–25 % (N=10) og
   70–85 % (N=25) av innsatsen, og det er ikke uflaks: den 10.–25. favoritten er en 59–68 %-favoritt. Systemspill
   flytter bare tapet utover flere dager.
2. **Hvis han vil sette kombo likevel:** bare Grand Slam-dager (runde 1–2, ca. 17 dager per år) har 10–25 favoritter
   med P over 0,80. Der går alle topp-10 inn annenhver gang og alle topp-15 hver fjerde gang. Forventet ROI er fortsatt
   null hos Pinnacle og negativ hos vanlige bøker.
3. **Nærmest en kant er ingen kant:** singler eller små kuponger på favoritter med P ≥ 0,85 hos Pinnacle (2–3 per
   dag) er break-even over 20 år. Hos bøker med margin på favorittsiden (Bet365-type, Norsk Tipping) taper de 1–2 %
   per ledd.
4. **Kanten må komme fra prisen, ikke fra utvalget.** Det eneste som ga pluss i 20 år er å få beste pris i markedet
   på sterke favoritter (+1,4 %), altså prisjakt over flere bøker — ikke kombinerbart, og små beløp.

## 7. Konsekvens for prosjektet

Proporsjonal de-vigging (`devig_two_way`, brukt i `mkt_p_winner`/markedsankeret i EV-motoren) undervurderer sterke
favoritter med ca. 2 prosentpoeng (P ≥ 0,85: observert 92,3 % mot proporsjonal 90,2 %, potens-de-vig 91,8 %, rå
1/odds 92,2 %). Potens-de-vigging har lavest log-loss og bør erstatte proporsjonal i markedsankeret. Det gjør
tipsene riktigere for storfavoritter; det gir ingen kant.

## Metode og forbehold

- Topp-N er valgt på closing-odds, som Leif ikke ser når han setter. Morgen-snapshots 2026 viser at utvalget er det
  samme i 94–97 % av leddene og at kostnaden per ledd er 0,4–0,6 pp høyere om morgenen.
- Bootstrap-KI er over dager; kombo-ROI for N ≥ 15 bygger på 13–148 vinnerdager og har KI på ±50–100 pp — bruk
  forventningen fra per-ledd-marginen, ikke punktestimatet.
- 2009 og nesten hele 2026 mangler Pinnacle; Bet365 brukes der og drar samlet singel-ROI ca. 0,3 pp ned.
- Ca. 40 segmenter og 166 rundeoppsett er testet; ved så mange tester ventes 3–4 «signifikante» funn av støy, og det
  er omtrent hva som ble funnet (Slam R1 begge tourer; WTA P ≥ 0,90 2016–2020). Ingen holder per tour, per periode
  og i populasjonen samtidig.
- Skript og fulle tabeller: scratchpad `agents/*/tabeller.md` (sesjon 2026-09-05); datasettbygger `build_dataset.py`.
