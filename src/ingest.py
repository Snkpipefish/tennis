"""Modul 1 — ingest.py

Laster Sackmann ATP+WTA match-CSV (2005-nå) fra speil, cacher rådata i
data/raw/, og bygger én ren parquet-tabell med kun feltene vi trenger.

Designvalg:
- Cache pr. (tour, år) som rå CSV i data/raw/. Lastes aldri på nytt hvis
  filen finnes. Inneværende/siste år kan re-lastes med force_refresh.
- tourney_date i Sackmann er heltall YYYYMMDD -> ekte datetime.
- Underlag normaliseres: Carpet -> Hard (nær utdødd, for få kamper til egen Elo).
- Rader uten gyldige spiller-id, rank eller underlag droppes ikke på rank
  (rank kan mangle for kvalifik.), men krever gyldige id og dato.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import requests

from . import config

# Kolonner vi henter fra rå Sackmann-CSV.
_USECOLS = [
    "tourney_name",
    "surface",
    "tourney_date",
    "winner_id",
    "loser_id",
    "winner_name",
    "loser_name",
    "winner_rank",
    "loser_rank",
    "winner_age",
    "loser_age",
    "best_of",
    "round",
]


# Sackmanns tourney_date er turneringens STARTDATO — alle kamper i en turnering
# deler samme dato. Innbyrdes rekkefølge må derfor styres av runden, ikke datoen.
# Lavere tall = tidligere i turneringen. Ukjente runder havner midt på.
_ROUND_ORDER = {
    "Q1": 0, "Q2": 1, "Q3": 2, "Q4": 3,
    "RR": 4, "ER": 4,            # round-robin / early rounds før utslagsspill
    "R128": 5, "R64": 6, "R32": 7, "R16": 8,
    "QF": 9, "SF": 10, "BR": 11, "F": 12,  # bronse før finale (OL)
}
_ROUND_DEFAULT = 7


def round_order(round_code: object) -> int:
    return _ROUND_ORDER.get(str(round_code).strip().upper(), _ROUND_DEFAULT)


def _raw_path(tour: str, year: int) -> Path:
    return config.RAW_DIR / f"{tour}_matches_{year}.csv"


def _download(tour: str, year: int, *, retries: int = 3, pause: float = 1.0) -> bytes:
    url = config.SOURCE_URLS[tour].format(year=year)
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200 and resp.content:
                return resp.content
            last_err = RuntimeError(f"HTTP {resp.status_code} for {url}")
        except requests.RequestException as exc:  # nettverksfeil
            last_err = exc
        if attempt < retries:
            time.sleep(pause * attempt)
    raise RuntimeError(f"Klarte ikke laste {tour} {year}: {last_err}")


def fetch_raw(*, force_refresh: bool = False, verbose: bool = True) -> list[Path]:
    """Last ned alle (tour, år)-CSV til data/raw/ med caching. Returner stier."""
    paths: list[Path] = []
    for tour in config.TOURS:
        for year in config.YEARS:
            path = _raw_path(tour, year)
            if path.exists() and not force_refresh:
                paths.append(path)
                continue
            if verbose:
                print(f"  laster {tour} {year} ...", flush=True)
            content = _download(tour, year)
            path.write_bytes(content)
            paths.append(path)
    return paths


def normalize_surface(surface: object) -> str:
    """Map Sackmann-underlag til {Hard, Clay, Grass}. Carpet/ukjent -> Hard."""
    s = str(surface).strip().capitalize()
    if s in ("Clay", "Grass"):
        return s
    return "Hard"  # Hard, Carpet, None, '' -> Hard


def _load_one(tour: str, year: int) -> pd.DataFrame:
    path = _raw_path(tour, year)
    df = pd.read_csv(path, usecols=lambda c: c in _USECOLS, low_memory=False)
    df["tour"] = tour
    df["season"] = year
    return df


def _unify_player_ids(df: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """Kanonisér spiller-id per (tour, navn).

    Speilets 2024-filer bruker REGENERERTE id-er (Sinner er 206173 t.o.m. 2023,
    206570 i 2024) — uten denne fiksen «gjenfødes» alle 2024-aktive spillere som
    ferske i Elo. Vi mapper alle id-er for samme (tour, navn) til id-en fra
    spillerens første opptreden. Navnekollisjoner (to ekte spillere med identisk
    navn på samme tour i samme æra) er neglisjerbart sjeldne mot denne feilen.
    """
    w = df[["tour", "winner_id", "winner_name", "date"]].rename(
        columns={"winner_id": "pid", "winner_name": "name"})
    l = df[["tour", "loser_id", "loser_name", "date"]].rename(
        columns={"loser_id": "pid", "loser_name": "name"})
    long = pd.concat([w, l], ignore_index=True)
    first = long.groupby(["tour", "name", "pid"])["date"].min().reset_index()
    # kanonisk id = id-en med tidligst første opptreden for navnet
    canon = first.sort_values("date").drop_duplicates(["tour", "name"])
    canon_map = dict(zip(zip(canon["tour"], canon["name"]), canon["pid"]))
    n_multi = int(first.groupby(["tour", "name"])["pid"].nunique().gt(1).sum())

    def _remap(tour_col, id_col, name_col):
        keys = list(zip(df[tour_col], df[name_col]))
        return pd.Series([canon_map.get(k) for k in keys], index=df.index).fillna(df[id_col])

    df = df.copy()
    df["winner_id"] = _remap("tour", "winner_id", "winner_name").astype("Int64")
    df["loser_id"] = _remap("tour", "loser_id", "loser_name").astype("Int64")
    if verbose and n_multi:
        print(f"  id-kanonisering: {n_multi:,} navn hadde flere id-er (speil-brudd 2024) — samlet", flush=True)
    return df


def build_matches(*, force_refresh: bool = False, verbose: bool = True, extend: bool = True) -> pd.DataFrame:
    """Bygg den rene match-tabellen og skriv til parquet. Returner den.

    extend=True (default) forlenger Sackmann (stopper medio 2024) med ferske
    resultater fra tennis-data.co.uk via src/extend.py, slik at Elo er
    oppdatert til i dag.
    """
    fetch_raw(force_refresh=force_refresh, verbose=verbose)

    frames = [_load_one(tour, year) for tour in config.TOURS for year in config.YEARS]
    df = pd.concat(frames, ignore_index=True)

    # Dato: YYYYMMDD heltall -> datetime.
    df["date"] = pd.to_datetime(df["tourney_date"], format="%Y%m%d", errors="coerce")

    # Underlag normalisert.
    df["surface"] = df["surface"].map(normalize_surface)

    # Spiller-id som nullbar int.
    for col in ("winner_id", "loser_id"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    # Numeriske felt.
    for col in ("winner_rank", "loser_rank", "winner_age", "loser_age", "best_of"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Krav til gyldig rad: ekte dato og begge spiller-id til stede og ulike.
    before = len(df)
    df = df[df["date"].notna()]
    df = df[df["winner_id"].notna() & df["loser_id"].notna()]
    df = df[df["winner_id"] != df["loser_id"]]
    dropped = before - len(df)

    # Reparer speilets id-brudd (2024-filene har regenererte spiller-id-er).
    df = _unify_player_ids(df, verbose=verbose)
    df = df[df["winner_id"] != df["loser_id"]]

    # Sorter kronologisk — kritisk for Elo. Innen samme turnering (samme dato)
    # styrer rundenummeret rekkefølgen, ellers prosesseres finalen før 1. runde.
    df["round_order"] = df["round"].map(round_order)
    df = df.sort_values(["date", "tour", "tourney_name", "round_order"], kind="stable")
    df = df.reset_index(drop=True)

    out = df[
        [
            "date",
            "season",
            "tour",
            "tourney_name",
            "surface",
            "winner_id",
            "loser_id",
            "winner_name",
            "loser_name",
            "winner_rank",
            "loser_rank",
            "winner_age",
            "loser_age",
            "best_of",
            "round",
        ]
    ].rename(columns={"tourney_name": "tourney"})

    if extend:
        # Forleng med ferske resultater (tennis-data.co.uk) frem til i dag.
        from .extend import build_extension

        ext = build_extension(out, verbose=verbose)
        if len(ext):
            out = pd.concat([out, ext], ignore_index=True)
            out["round_order"] = out["round"].map(round_order)
            out = out.sort_values(["date", "tour", "tourney", "round_order"], kind="stable")
            out = out.drop(columns=["round_order"]).reset_index(drop=True)

    out.to_parquet(config.MATCHES_PARQUET, index=False)
    if verbose:
        print(
            f"  bygde {len(out):,} kamper "
            f"({dropped:,} droppet), -> {config.MATCHES_PARQUET}",
            flush=True,
        )
    return out


def load_matches() -> pd.DataFrame:
    """Les den ferdige match-tabellen fra parquet (bygg hvis den mangler)."""
    if not config.MATCHES_PARQUET.exists():
        return build_matches()
    return pd.read_parquet(config.MATCHES_PARQUET)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    force = "--force" in argv
    df = build_matches(force_refresh=force)
    print(f"Ferdig: {len(df):,} kamper, {df['date'].min().date()}–{df['date'].max().date()}")
    print(df.groupby(["tour"]).size().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
