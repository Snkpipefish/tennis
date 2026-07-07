"""Delte stier og konstanter for hele tennis-EV-prosjektet.

Alt av filplassering og data-kilde samles her, slik at modulene ikke
hardkoder stier. Endrer du datakilde eller årsspenn er dette eneste sted.
"""
from __future__ import annotations

from pathlib import Path

# --- Prosjektrot og kataloger ------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
ODDS_DIR = DATA_DIR / "odds"
REPORTS_DIR = ROOT / "reports"
MODELS_DIR = ROOT / "models"

for _d in (RAW_DIR, ODDS_DIR, REPORTS_DIR, MODELS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Data-kilde --------------------------------------------------------------
# Jeff Sackmanns originale repo (JeffSackmann/tennis_atp + tennis_wta) ligger
# nede (404 pr. juni 2026). Vi bruker et speil som inneholder de RÅ Sackmann-
# CSV-ene i uendret format for begge tourer. Kilden krediteres i README.
# Lisens: CC BY-NC-SA 4.0 — kun ikke-kommersiell privat bruk.
_MIRROR = "https://raw.githubusercontent.com/dsw225/TennisPredictionModel/main/breakpoint/data/csvs"

# URL-mal pr. tour. {year} fylles inn. Mellomrom i stien er URL-enkodet.
SOURCE_URLS = {
    "atp": _MIRROR + "/ATP%20(Mens)/tennis_atp/atp_matches_{year}.csv",
    "wta": _MIRROR + "/WTA%20(Womens)/tennis_wta/wta_matches_{year}.csv",
}

# tennis-data.co.uk closing odds (Pinnacle + Bet365). {year} fylles inn.
# ATP: /YYYY/YYYY.xlsx, WTA: /YYYYw/YYYY.xlsx
TENNIS_DATA_URLS = {
    "atp": "http://www.tennis-data.co.uk/{year}/{year}.xlsx",
    "wta": "http://www.tennis-data.co.uk/{year}w/{year}.xlsx",
}
TENNIS_DATA_CACHE = ODDS_DIR / "tennis_data_cache"
TENNIS_DATA_CACHE.mkdir(parents=True, exist_ok=True)

# Norsk Tipping ("Oddsen") drives av Kambi. Odds hentes automatisk herfra —
# Leif taster ALDRI inn noe manuelt. Odds-felt er desimalodds × 1000.
# NB: datasenter-IP blokkeres (429); fungerer fra norsk hjemme-IP.
KAMBI_BASE = "https://eu-offering-api.kambicdn.com/offering/v2018/ntno"
KAMBI_TENNIS_LISTVIEW = KAMBI_BASE + "/listView/tennis.json"
KAMBI_PARAMS = {"lang": "en_GB", "market": "NO", "client_id": "2", "channel_id": "1"}

# Årsspenn iht. PLAN.md ("2005-nå"). Speilet dekker t.o.m. 2024.
YEAR_START = 2005
YEAR_END = 2024
YEARS = list(range(YEAR_START, YEAR_END + 1))
TOURS = ("atp", "wta")

# --- Filer som produseres ----------------------------------------------------
MATCHES_PARQUET = RAW_DIR / "matches.parquet"
TRACK_LOG = ODDS_DIR / "track_record.json"
ELO_STATE_PARQUET = MODELS_DIR / "elo_state.parquet"
ELO_META_JSON = MODELS_DIR / "elo_meta.json"
CALIBRATOR_PKL = MODELS_DIR / "calibrator.pkl"

# --- Elo-parametre -----------------------------------------------------------
ELO_INIT = 1500.0
# Betfair/538-formel for avtagende K (referert av evsnts-repoet):
#   K = K_FACTOR / (n + K_SHIFT) ** K_DECAY
ELO_K_FACTOR = 250.0
ELO_K_SHIFT = 5.0
ELO_K_DECAY = 0.4
# Vekt på underlags-Elo vs samlet Elo i blandet prediksjon.
ELO_SURFACE_WEIGHT = 0.5

# Underlag vi modellerer separat. Carpet er nær utdødd og slås sammen til Hard.
SURFACES = ("Hard", "Clay", "Grass")

# Kaldstart: nye spillere seedes fra inngangsrankingen i stedet for flatt 1500,
# via   elo0 = A + B * ln(rank)   (klippet til [SEED_MIN, SEED_MAX]).
# Defaultene er fittet på treningsdata (2005–2022, established spillere) og
# refittes i praksis ved hver build_elo. Spillere uten kjent rank -> ELO_INIT.
RANK_SEED_A = 2231.8
RANK_SEED_B = -128.3
SEED_MIN = 1300.0
SEED_MAX = 2400.0

# --- Kalibrering -------------------------------------------------------------
# Hold de siste N sesongene som out-of-sample. Nest siste brukes til å fitte
# kalibratoren, siste til endelig (urørt) evaluering.
HOLDOUT_SEASONS = 2
RELIABILITY_BINS = 10
