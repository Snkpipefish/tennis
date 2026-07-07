# Tennis +EV-maskin for Norsk Tipping

Lokalt Python-verktøy som produserer tennis-veddemål med positiv forventet
verdi (+EV) målt mot Norsk Tippings odds. Veddemål legges inn **manuelt** hos
NT — ingen automatisk innsats. Privat, ikke-kommersiell bruk.

## Status
Alle moduler (1–7) er bygget, testet og kjørt. Kalibreringsporten er passert
(godkjent). Detaljert status i `PROGRESS.md`, overordnet plan i `plan.md`.

## Oppsett
Ingenting å sette opp manuelt. `main.py` oppretter `.venv` og installerer
avhengigheter automatisk ved første kjøring, og bruker alltid riktig miljø.

## Bruk
**Enkleste bruk — lokal web-UI** (ingen terminal i det daglige):
```bash
python3 main.py ui              # åpne http://127.0.0.1:5057 i nettleseren
```
Dashboardet viser dagens anbefalte veddemål og track record, med knapper for å
hente NT-odds, regne på nytt, loggføre og registrere utfall. Bankroll settes i
et felt. Alt skjer ved klikk.

Kommandolinje (samme funksjoner, om ønskelig):
```bash
python3 main.py setup           # bygg/oppdater data, Elo, kalibrering, markedssjekk
python3 main.py daily -b 5000   # hent NT-odds, oppdater + regn dagens veddemål
python3 main.py log   -b 5000   # loggfør anbefalte veddemål
python3 main.py settle <id> win # registrer utfall
.venv/bin/python -m pytest -q   # 51 tester
```
### Henting av NT-odds
Norsk Tipping er bot-beskyttet (Akamai), så odds kan ikke hentes med en vanlig
HTTP-forespørsel. I stedet styrer maskinen en ekte nettleser (Playwright):
knappen «Hent NT-odds & regn» (eller `python3 main.py daily`) åpner et
nettleservindu, laster NT, henter dagens tennisodds og lukker igjen — helt
automatisk, ingen tasting. Første gang lastes nettlesermotoren ned (engangs,
~1 min). (`python3 main.py manual` finnes som siste nødløsning.)

## Arkitektur
- `src/config.py` — stier, datakilde, parametre.
- `src/ingest.py` — **Modul 1**: laster Sackmann ATP+WTA CSV (2005–2024) med
  caching i `data/raw/`, bygger ren parquet-tabell.
- `src/elo.py` — **Modul 2**: kronologisk Elo (samlet + underlag), avtagende
  K, rank-seeding av nye spillere, inkrementell lagring.
- `src/calibrate.py` — **Modul 3**: out-of-sample kalibrering (Brier, log-loss,
  ECE, reliability-diagram, Platt/isotonisk). Den harde porten.
- `src/market_check.py` — **Modul 4**: laster Pinnacle/Bet365 closing odds fra
  tennis-data.co.uk, de-vigger, validerer modellen mot markedet.
- `src/nt_odds.py` — **Modul 5**: henter NT-odds AUTOMATISK fra Kambi
  (operator `ntno`, Modus B), kobler kamper til spiller-id, infererer underlag.
  Ingen manuell inntasting. NB: Kambi blokkerer datasenter-IP — kjør fra norsk
  nett. Manuell inntasting finnes kun som nødløsning (`main.py manual`).
- `src/ev_engine.py` — **Modul 6**: EV = kalibrert_P·NT_odds − 1, vedd kun ved
  EV > 5 %, 1/4-Kelly innsats. Skriver `reports/today_bets.md`.
- `src/track.py` — **Modul 7**: logger utfall, faktisk vs forventet ROI,
  kalibreringskurve på egne veddemål. Skriver `reports/track_record.md`.
- `src/ui.py` — lokal Flask-web-UI (`python main.py ui`): dashboard med dagens
  veddemål, track record, og knapper for henting/loggføring/utfall.

## Modell (kort)
Surface-blandet Elo med logistisk sannsynlighet
`P(A) = 1 / (1 + 10^((R_B − R_A)/400))`, avtagende K-faktor
`K(n) = 250/(n+5)^0.4` (Betfair/538), nye spillere seedet fra inngangsranking.
Sannsynlighetene Platt-kalibreres mot out-of-sample-utfall.

## Datakilde og lisens
Match-data er Jeff Sackmanns tennis-CSV-er
([tennis_atp](https://github.com/JeffSackmann/tennis_atp) /
[tennis_wta](https://github.com/JeffSackmann/tennis_wta)), lisensiert under
**CC BY-NC-SA 4.0** — kun ikke-kommersiell bruk, med kreditering og deling på
samme vilkår. Originalrepoene var utilgjengelige (404) ved bygging, så data
hentes fra et speil som inneholder de uendrede Sackmann-filene (konfigurert i
`src/config.py`). Eventuell Norsk Tipping-skraping skjer kun i lavt volum til
eget bruk.

Kreditering: data © Jeff Sackmann / Tennis Abstract.
