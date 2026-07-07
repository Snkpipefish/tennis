# PLAN.md — Tennis +EV-maskin for Norsk Tipping

Dette dokumentet er master-planen. Les hele før du skriver kode.
Bygg ALLE moduler i denne sesjonen, i rekkefølge, men RESPEKTER stopp-punktet.

## Mål
Lokalt Python-verktøy som hver dag produserer tennis-veddemål med positiv
forventet verdi (+EV) målt mot Norsk Tippings odds. Veddemål legges inn
MANUELT hos NT. Ingen automatisk innsats.

## Strategi
Elo-på-tennis er løst mange ganger. Bruk disse KUN som matematisk referanse,
ikke kopier strukturen (begge er rotete notebooks):
- https://github.com/evsnts/tennis_elo
- https://github.com/hdai/elo_tennis
Det som ikke finnes ferdig, og som er poenget her:
1. Norsk Tipping odds-integrasjon.
2. Kalibrering som FORUTSETNING før veddemål produseres.

## Lisens
Sackmann-data: CC BY-NC-SA 4.0. Kun ikke-kommersiell privat bruk.
Krediter kilden i README. NT-skraping kun lavt volum, eget bruk.

## Prosjektstruktur
tennis-ev/
  data/raw/          Sackmann CSV-cache
  data/odds/         tennis-data.co.uk + NT-logg
  src/ingest.py      Modul 1
  src/elo.py         Modul 2
  src/calibrate.py   Modul 3  <-- STOPP ETTER DENNE
  src/market_check.py Modul 4
  src/nt_odds.py     Modul 5
  src/ev_engine.py   Modul 6
  src/track.py       Modul 7
  reports/  main.py  README.md  tests/  PROGRESS.md

## Byggerekkefølge og det ENE stopp-punktet
Bygg Modul 1 -> 2 -> 3. Etter Modul 3: kjør kalibreringen, skriv
reports/calibration.md, og STOPP. Skriv tydelig i chatten:
"KALIBRERING FERDIG - venter på godkjenning før Modul 4-7."
Ikke bygg videre før jeg sier ok. Hvis kalibreringen er dårlig er
resten verdiløst. Dette er den eneste harde porten.

## Modul 1 — ingest.py
- Last Sackmann tennis_atp + tennis_wta CSV (2005-nå) via
  raw.githubusercontent.com. Cache i data/raw/, ikke last på nytt.
- Ren parquet-tabell: dato, turnering, underlag, winner_id, loser_id,
  rank begge, alder begge.
- Test: radantall > 0, winner alltid en av de to spillerne.

## Modul 2 — elo.py
- Surface-spesifikk Elo (hard/clay/grass) + samlet, kronologisk.
- K-faktor avtar med antall kamper spilt. Bruk Betfair-formelen som
  evsnts-repoet refererer til.
- Lagre Elo-tilstand til disk for inkrementell oppdatering.
- Output: rå P(spiller A vinner) via logistisk formel.

## Modul 3 — calibrate.py  (VIKTIGST)
- Tren Elo kun på data FØR de siste 2 sesongene. Hold 2 siste som
  out-of-sample test-sett.
- Reliability diagram, Brier-score, log-loss.
- Dårlig kalibrert -> isotonisk regresjon eller Platt scaling.
- Skriv reports/calibration.md med tall + plott. SO STOPP (se over).

## Modul 4 — market_check.py
- Last closing odds fra tennis-data.co.uk (Pinnacle + Bet365, ATP/WTA).
- De-vig Pinnacle til ren implisitt P.
- Sammenlign kalibrert P mot Pinnacle. Skriv reports/market_validation.md.

## Modul 5 — nt_odds.py
- Modus A først: CLI der jeg skriver inn dagens kamper + NT-odds,
  lagres med tidsstempel i data/odds/.
- Modus B (scraper) kun hvis jeg ber om det.

## Modul 6 — ev_engine.py
- Per kamp: EV = kalibrert_P * NT_odds - 1. Veddemål kun hvis EV > 0,05.
- Innsats: 1/4-Kelly på oppgitt bankroll. Aldri full Kelly.
- Output reports/today_bets.md + terminaltabell:
  Kamp | Spill på | Modell-P | NT-odds | Implisitt-P | EV% | Innsats kr
  sortert etter EV.

## Modul 7 — track.py
- Logg utfall, innsats, gevinst/tap. Faktisk ROI vs forventet +
  kalibreringskurve på MINE veddemål. reports/track_record.md.

## main.py
Daglig flyt: oppdater data -> oppdater Elo -> les NT-odds -> today_bets.md.

## PROGRESS.md
Oppdater denne filen etter HVER modul: hva er gjort, hva gjenstår,
kjente problemer. Slik at en ny sesjon kan fortsette uten å miste tråden.
