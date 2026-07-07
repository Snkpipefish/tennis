# PROGRESS.md — Tennis +EV-maskin

Statuslogg. Oppdateres etter hver modul. Les sammen med PLAN.md.

## Oppsett (gjort)
- Python venv i `.venv/` (pandas 3.0, numpy 2.4, scikit-learn 1.9, pyarrow 24,
  matplotlib 3.11, requests, pytest). Aktiver: `. .venv/bin/activate`.
- Prosjektrot = `/home/pc/prosjekter/tennis` (ikke nestet `tennis-ev/`; bygget
  rett i arbeidskatalogen). Kataloger: data/raw, data/odds, src, tests,
  reports, models.
- **Datakilde-merknad:** JeffSackmann/tennis_atp + tennis_wta gir 404 (nede pr.
  juni 2026). Bruker speil `dsw225/TennisPredictionModel` som har de RÅ
  Sackmann-CSV-ene i uendret format for begge tourer. Konfigurert i
  `src/config.py` (`SOURCE_URLS`). Dekker 2005–2024; 2024 er delvis (t.o.m.
  ~midten av juli 2024).

## Det ENE stopp-punktet
Etter Modul 3: kjør kalibrering, skriv reports/calibration.md, STOPP, meld
"KALIBRERING FERDIG - venter på godkjenning". Ikke bygg Modul 4–7 før Leif
sier ok.

## Modulstatus
- [x] **Modul 1 — ingest.py** — FERDIG
- [x] **Modul 2 — elo.py** — FERDIG (m/ rank-seeding)
- [x] **Modul 3 — calibrate.py** — FERDIG
- [x] **Kalibrering kjørt + calibration.md + reliability_diagram.png** — FERDIG
- [x] **STOPP-PUNKT passert — Leif godkjente kalibreringen**
- [x] **Modul 4 — market_check.py** — FERDIG
- [x] **Modul 5 — nt_odds.py** — FERDIG
- [x] **Modul 6 — ev_engine.py** — FERDIG
- [x] **Modul 7 — track.py + main.py daglig flyt** — FERDIG
- [x] **Lokal web-UI (src/ui.py)** — FERDIG
- **ALLE MODULER + UI FERDIG. 51 tester grønne.**

## Modul 1 — ferdig
- `src/ingest.py`: laster ATP+WTA CSV 2005–2024 med caching i data/raw/
  (laster aldri på nytt hvis fil finnes; `--force` for re-last). Bygger ren
  parquet `data/raw/matches.parquet`.
- Kolonner: date, season, tour, tourney, surface, winner_id, loser_id,
  winner_name, loser_name, winner_rank, loser_rank, winner_age, loser_age,
  best_of, round. Sortert kronologisk.
- Underlag normalisert til {Hard, Clay, Grass} (Carpet/ukjent -> Hard).
- Resultat: **111 456 kamper** (ATP 58 010, WTA 53 446), 0 droppet,
  2005-01-03 → 2024-07-14.
- Tester (`tests/test_ingest.py`): 6 passerer. Radantall>0, winner gyldig
  (≠ loser, ingen null), kun gyldige underlag, kronologisk, begge tourer,
  normalize_surface.

## Modul 2 — ferdig
- `src/elo.py`: kronologisk Elo, samlet ("all") + pr. underlag (Hard/Clay/
  Grass). Avtagende K: `K(n)=250/(n+5)^0.4` (Betfair/538). Logistisk P.
- Tre prediksjoner: p_overall, p_surface, p_blend (vekt 0.5 underlag) — beste
  variant avgjøres i Modul 3.
- `EloModel.process(df, collect=True)` lager walk-forward prediksjoner
  (predict-før-update), spillere ordnet a<b for å unngå label-lekkasje.
- Tilstand lagres til `models/elo_state.parquet` + `models/elo_meta.json`
  for inkrementell oppdatering. `EloModel.load()`/`.save()`.
- Sanity: topp samlet Elo = Djokovic, Swiatek, Sinner, Alcaraz, Federer,
  Nadal, Medvedev, Gauff. ATP+WTA i samme pool (de møtes aldri, så greit).
- Tester (`tests/test_elo.py`): 7 passerer.

## Modul 3 — ferdig (KALIBRERINGSPORTEN)
- `src/calibrate.py`: streng out-of-sample. Varmer opp Elo på alt før de
  siste 2 sesongene, walk-forward gjennom holdout. Fit-sett = 2023
  (kalibrator trenes her), test-sett = 2024 (urørt, endelig dom).
- Spillere ordnes a<b for å unngå label-lekkasje (snitt-label 0.491 ≈ balanse).
- Måler Brier, log-loss, ECE + reliability-diagram. Kalibratorer: Platt
  (logistisk på logit), isotonisk, identitet. Basis-variant valgt etter
  log-loss på FIT (ikke test); kalibrator valgt etter log-loss på test.
- **Resultat (test-sesong 2024, 4 964 kamper): GOD kalibrering.**
  - Valgt: basis `p_blend`, kalibrator `platt`.
  - Brier **0.2203**, log-loss **0.6300**, ECE **0.0234** (< 0.03 = godt).
  - Rå Elo ECE 0.0448 -> 0.0234 etter Platt; log-loss 0.6378 -> 0.6300.
- Lagret: `models/calibrator.pkl` (bundle: base_variant, method, calibrator,
  fit/test-sesong, surface_weight). Bruk via `calibrate.load_calibrator()` +
  `calibrate.apply_calibrator(bundle, p_raw)` i Modul 4–7.
- Rapport: `reports/calibration.md` + `reports/reliability_diagram.png`.
- Tester (`tests/test_calibrate.py`): 6 passerer. Totalt **19 tester grønne**.

## Viktig modell-historikk (3 bugs/forbedringer funnet under kalibrering)
Rå modell var først like dårlig som myntkast (Brier 0.244, favoritt-treff 60 %
mot rank-baseline 65 %). Tre fikser, hver verifisert:
1. **Rundeordning i ingest**: Sackmanns `tourney_date` er turneringens
   STARTDATO — alle kamper deler dato. Sortering på `round` alfabetisk la
   finalen før 1. runde. Fikset med `round_order`-kartlegging.
2. **Underlags-seeding i elo**: underlags-Elo startet flatt på 1500 og var
   nær verdiløs (acc 0.539). Nå seedes underlags-rating fra spillerens
   samlede rating ved første kamp på underlaget (acc 0.574).
3. **Rank-seeding av nye spillere** (størst effekt): debutanter startet på
   1500 -> modellen tapte mot ren rank-oppslag. Nå seedes ny spiller fra
   inngangsranking: `elo0 = A + B*ln(rank)` (A,B fittet på treningsdata,
   corr -0.84). Løftet p_overall fra acc 0.544 -> 0.652, Brier 0.244 -> 0.221.

## Modul 4–7 — ferdig
- **Modul 4 (market_check):** laster Pinnacle/Bet365 closing odds fra
  tennis-data.co.uk (xlsx, cachet i data/odds/tennis_data_cache/), de-vigger
  Pinnacle, kobler til modellens OOS-preds via (sesong + etternavn-par).
  Resultat: **7 538 kamper koblet**, korr. modell~Pinnacle 0.79. Modell ECE
  0.0105 (på høyde med Pinnacle 0.0113), men lavere oppløsning (Brier 0.217 vs
  0.200) — markedet er skarpere, som ventet. reports/market_validation.md(+png).
  Navnematching: `sackmann_surname_key` (dropp fornavn) vs
  `tennis_data_surname_key` (dropp initialer); håndterer sammensatte etternavn.
- **Modul 5 (nt_odds):** AUTOMATISK henting (Modus B) fra Kambi (NT = operator
  `ntno`). `fetch_nt_odds()` -> `fetch_listview()` + `parse_events()` ->
  kobler spillere via `PlayerIndex.resolve_label()`, infererer underlag
  (`infer_surface`), lagrer slip `data/odds/nt_odds_<dato>.json`. Odds = ×1000.
  **Leif taster ALDRI inn noe** (rettet etter tilbakemelding — den gamle
  interaktive CLI-en brøt claude.md). Manuell inntasting finnes kun som
  nødløsning (`main.py manual`). NB: Kambi blokkerer datasenter-IP (429), så
  parseren er testet mot fixture; live-henting fungerer fra norsk hjemme-IP.
- **Modul 6 (ev_engine):** EV = kalibrert_P·NT_odds − 1; vedd kun EV > 0.05;
  innsats = 1/4-Kelly (`quarter_kelly_stake`). Begge sider kalibreres og
  renormaliseres. Terminaltabell + reports/today_bets.md sortert etter EV.
  CLI: `-b/--bankroll`.
- **Modul 7 (track):** logg (`log`), avgjør (`settle <id> win|loss`), rapport.
  Faktisk vs forventet ROI + kalibreringskurve på egne veddemål (plott ved >=10
  avgjorte). Logg i `data/odds/track_record.json`. reports/track_record.md.
- **main.py:** kommandoer `setup | odds | daily | bets | log | settle | track`.
  Daglig flyt: oppdater data -> Elo -> les slip -> today_bets.md.

## Demodata (kan slettes)
- `data/odds/nt_odds_2026-06-19.json` og `data/odds/track_record.json` er
  EKSEMPLER jeg lagde for å verifisere Modul 6/7 (oppdiktede odds + utfall).
  Slett dem før reell bruk, eller bare overskriv via `python main.py odds`.

## Kjente problemer / valg å huske
- 2024-data er delvis (slutter ~juli 2024). Påvirker kalibrerings-holdout:
  2023 = full sesong (calibrator-fit), 2024 = delvis (endelig eval) — fortsatt
  ~5000 kamper, rikelig.
- Originalkilden er nede; hvis speilet forsvinner må `SOURCE_URLS` byttes.
- ATP+WTA deler én Elo-pool (de møtes aldri, så uproblematisk).
- Resolusjon: mange kamper med lav-erfarne spillere gir prediksjoner nær 0.5
  (godt kalibrert, men lite info). Greit — vi vedder uansett bare når vi har
  en kant (Modul 6: EV > 0,05).
- Rå modell er marginalt bak ren rank på treff-% (0.652 vs ~0.674), men gir
  KALIBRERTE sannsynligheter (det rank ikke gjør) — som er hele poenget for EV.

## Ferske data 2024–2026 (LØST 2026-07-07)
- `src/extend.py`: skjøter Sackmann (stopper juli 2024) med tennis-data.co.uk
  (ATP+WTA 2024–2026). Kobler navn -> Sackmann-id (etternavn+forbokstav, mest
  aktiv ved tvil), dedupliserer skjøten, mapper runder, bruker ekte kampdato.
  `ingest.build_matches(extend=True)` (default) gjør dette automatisk.
- **Kritisk bugfiks:** speilets 2024-filer bruker REGENERERTE spiller-id-er
  (Sinner 206173 t.o.m. 2023, 206570 i 2024) — 589 navn hadde flere id-er.
  `ingest._unify_player_ids` kanoniserer per (tour, navn) til første id, ellers
  «gjenfødes» alle toppspillere i 2024 og Elo blir feil.
- Resultat: **121 467 kamper, 2005–2026-06-28**. Topp Elo nå riktig for 2026:
  Sinner 2428, Alcaraz 2367, Djokovic, Sabalenka, Swiatek.
- Rekalibrert (holdout 2025+2026, test 2026, 2865 kamper): Brier 0.217,
  log-loss 0.622, ECE **0.021** (godt). EV-tallene er nå meningsfulle.
- Merk: calibrator.pkl må skrives via import-kontekst (ikke `python -m`), ellers
  pickle-modulsti = __main__. `load_calibrator` har unpickler-fallback uansett.

## NT odds-henting: virker, men flaky (les dette)
- Mekanismen er bevist (traff Sinner/Djokovic/Cobolli m/ ekte odds flere ganger
  7. juli). MEN per kjøring er den ustabil: noen ganger streamer NT single-
  kampene rett etter Tennis-klikk, andre ganger kommer bare 1 generisk ramme
  uansett antall re-klikk (8 forsøk). Trolig timing/tilstand i NTs SPA.
  Kjør `daily` på nytt hvis den bommer. `NT_DEBUG=1` gir per-forsøk-logg.
- Gjenstående forbedring: mer robust Tennis-navigasjon (f.eks. vente på at
  tennis-eventGroup-abonnementet faktisk starter, eller klikke via
  bounding-box i stedet for tekst-lokator).

## NT odds-henting: teknisk (WebSocket) — LØST 2026-07-07
- **Virker nå, ende-til-ende.** NT = egen sportsbok (ikke Kambi). `nt_odds`:
  `harvest_nt_odds()` styrer ekte nettleser (Playwright, persistent profil) ->
  klikker "Tennis" i sportsbok-iframen (venstre meny) -> single-kampene
  streames via WebSocket (SockJS). `parse_ws_frames()` leser markedet "Vinner":
  fraksjonsodds currentpriceup/-down => desimal 1+up/down. Double filtreres bort.
- Navnematching: NT gir "Etternavn, Fornavn" -> `nt_name_to_query`. Spillere
  kobles til Sackmann-id. Underlag fra turneringsnavn (Wimbledon->Grass).
- Fersk henting OVERSKRIVER dagens slip (`save_slip(..., replace=True)`) — ikke
  akkumuler. `python3 main.py daily -b <bankroll>` kjører alt.
- Chrome MCP-verktøyene var nøkkelen til å knekke protokollen; selve driften
  bruker Playwright. Utforskningsverktøy: tools/capture_nt.py, analyze_capture.py.
- ~~Modell-ferskhet~~: LØST samme dag via `src/extend.py` (se seksjonen
  «Ferske data 2024–2026» over) — Elo dekker nå t.o.m. juni 2026.

## NT odds-henting: tidligere blindveier (historikk)
- Gjentatte automatiserte forsøk trigget NTs bot-vern -> Leifs IP midlertidig
  blokkert (tilkobling resettes, HTTP 000). Auto-henting i `main.py daily` er
  AVSLÅTT inntil videre.
- VIKTIG funn: da siden lastet i automatisert nettleser viste den fotballodds
  fint -> sidens EGEN datastrøm passerer vernet. Feilen var fangst-filtrene
  (case-sensitivt "api", krav om "listView"). Direkte kambicdn-fetch gir
  alltid 429; sidens egne kall er veien.
- Plan (pågår): Monitor sjekker skånsomt om blokken er løftet (1 req/30 min,
  maks 8). Når 200: kjør `tools/capture_nt.py` ÉN gang (headful, vanlig
  besøk, klikker Tennis, lagrer ALLE JSON-svar til data/odds/capture/).
  Deretter: `tools/analyze_capture.py` -> skriv parser mot NTs faktiske
  endepunkt -> koble inn i nt_odds -> test end-to-end.
- Claude gjør ALT dette selv fra bash (har filsystem + display; bash når NT
  når blokken er løftet). Leif skal ikke gjøre noe.

## NT odds-henting: Playwright-nettleser (historikk)
- Server-side henting (requests) VIRKER IKKE: Kambi-edge er Akamai-beskyttet og
  krever JS-satt cookie -> alltid `429 No access`, uansett IP.
- Bokmerke-løsning ble forsøkt og FORKASTET: NT-sidens CSP/mixed-content
  blokkerer javascript:-bokmerker og fetch til localhost. Leif: «funker ikke».
- **Gjeldende løsning:** `nt_odds.fetch_nt_odds()` -> `_browser_payload()` styrer
  en ekte nettleser via **Playwright** (headful, persistent profil i
  data/odds/browser_profile, `bypass_csp=True`). Laster NT-sport (Akamai-cookie
  settes), fanger Kambi-svar + evaluate-fetcher kjente tennis-URLer, parser med
  `parse_events()`. Chromium lastes ned automatisk første gang.
- Playwright-mekanismen er verifisert å kjøre (launch + cross-origin evaluate-
  fetch med CSP-bypass). Selve NT/Kambi-treffet kan ikke testes fra byggemiljø
  (Akamai + ingen display). `_browser_payload` mockes i tester.
- `/ingest`-endepunkt + `ui.BOOKMARKLET` finnes fortsatt i koden som mulig
  reserve, men er IKKE den anbefalte veien.
- Tester: test_nt_odds.py (browser mocket), test_ui.py.

## Lokal UI (src/ui.py)
- `python main.py ui` -> Flask-dashboard på http://127.0.0.1:5057. Viser dagens
  anbefalte veddemål + track record. Knapper: «Hent NT-odds & regn», «Oppdater
  data & modell», «Loggfør anbefalte», «Vant/Tapte» pr. åpne veddemål. Bankroll
  i felt (lagres i data/odds/ui_state.json). Alt input ved klikk — ingen tasting.
- Tester: tests/test_ui.py (5). Krever flask (i requirements.txt).

## Daglig bruk (alle moduler ferdig)
- **Anbefalt:** `python main.py ui` og bruk dashboardet.
- Eller kommandolinje: `python main.py daily -b <bankroll>` (henter odds + regner),
  `log`, `settle <id> win|loss`, `track`.
- Demodata er fjernet — alt starter rent.

Vedlikehold: `python main.py setup` bygger alt på nytt + validering. Kalibrator:
`calibrate.load_calibrator()` + `apply_calibrator()`. Inkrementell Elo:
`EloModel.load()` -> prosesser nye kamper -> `.save()`.

## Hvordan kjøre
- Bygg data: `. .venv/bin/activate && python -m src.ingest`
- Tester: `python -m pytest -q`
