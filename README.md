# Tennis-tips — kalibrert Elo + markedssentiment

Maskin som predikerer vinnersannsynlighet for alle profesjonelle tenniskamper
(ATP/WTA, Challenger, ITF — single og double) og flagger eventuelle odds med
positiv forventet verdi. Kjører helt automatisk i GitHub Actions og publiserer
dagens tips på:

**https://snkpipefish.github.io/tennis/**

Siden oppdateres fire ganger daglig uten manuelle steg. Privat,
ikke-kommersiell bruk.

## Slik virker det

1. **Resultater**: Jeff Sackmanns historiske data (2005–2024) skjøtes med
   tennis-data.co.uk (til ~1–2 uker siden) og ESPNs åpne scoreboard-API
   (frem til i går kveld). Modellen er alltid trent på ferske resultater.
2. **Modell**: kronologisk Elo (samlet + per underlag), avtagende K-faktor
   `K(n) = 250/(n+5)^0.4`, nye spillere seedes fra ranking. Sannsynlighetene
   Platt-kalibreres out-of-sample (Brier 0.217, ECE 0.021 på urørt testsesong).
3. **Markedssentiment**: de-viggede odds fra Pinnacles åpne gjeste-API
   (verdens skarpeste bok) vektes 70/30 mot modellens P — markedet priser inn
   skader, form og nyheter som Elo ikke ser.
4. **Tips og verdi**: hver kamp får maskinens favoritt + prosent. Spill
   flagges kun når EV > 5 % **og** oddsen slår markedets fair pris — og aldri
   på spillere modellen ikke kjenner. Innsats: 1/4-Kelly, maks 5 % av
   bankroll, oppgitt per 1000 kr.

## Kjør selv (valgfritt)

```bash
python3 main.py ui      # lokalt dashbord på http://127.0.0.1:5057
python3 main.py daily   # samme pipeline fra kommandolinjen
python3 main.py setup   # full rebygging inkl. kalibrering og markedsvalidering
python3 -m src.publish  # generer den statiske siden til site/
.venv/bin/python -m pytest -q
```

`main.py` oppretter `.venv` og installerer avhengigheter automatisk første
gang. Skypubliseringen styres av `.github/workflows/publish.yml`.

## Arkitektur

- `src/config.py` — stier, kilder, parametre.
- `src/ingest.py` — historiske data (Sackmann-speil) -> ren parquet.
- `src/extend.py` — skjøter på tennis-data.co.uk (2024–nå).
- `src/results.py` — tetter resultat-gapet med ESPN-scoreboard (samme dag).
- `src/elo.py` — Elo-modellen, inkrementell lagring.
- `src/calibrate.py` — out-of-sample kalibrering (den harde porten).
- `src/market_check.py` — validering mot Pinnacle/Bet365 closing odds.
- `src/odds_sources.py` — dagens odds fra Pinnacle (åpent API, ingen nøkkel).
- `src/ev_engine.py` — blandet P, EV, markeds-vakt, Kelly-innsats.
- `src/track.py` — loggfører spill, auto-avgjør mot nye resultater, ROI.
- `src/ui.py` — lokalt Flask-dashbord.
- `src/publish.py` — statisk side for GitHub Pages.
- `src/nt_odds.py` — *dormant*: tidligere Norsk Tipping-henting, droppet fra
  flyten (krevde norsk hjemme-IP og nettleser). Reaktiveres kun via
  `config.INCLUDE_NT`.

## Datakilder og lisens

- Historiske kamper: © Jeff Sackmann / Tennis Abstract
  ([tennis_atp](https://github.com/JeffSackmann/tennis_atp) /
  [tennis_wta](https://github.com/JeffSackmann/tennis_wta)),
  **CC BY-NC-SA 4.0** — ikke-kommersiell bruk med kreditering.
  Originalrepoene var nede ved bygging; data hentes fra et speil med de
  uendrede filene (se `src/config.py`).
- Nyere resultater og closing odds: tennis-data.co.uk.
- Ferske resultater: ESPNs offentlige scoreboard-API.
- Dagens odds: Pinnacles offentlige gjeste-API.

Tips er sannsynligheter, ikke garantier — spill ansvarlig.
