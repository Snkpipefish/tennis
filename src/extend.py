"""Modul 1b — extend.py

Forlenger Sackmann-datasettet (stopper medio 2024) med ferske resultater fra
tennis-data.co.uk (2024–nå, ATP+WTA), slik at Elo er oppdatert til i dag.

Utfordringer som håndteres her:
- Navneformat: tennis-data bruker "Sinner J." — kobles til Sackmann-spiller-id
  via etternavn + forbokstav (mest nylig aktive vinner ved tvil). Ukjente
  spillere får stabil syntetisk id (rank-seeding gjør dem fortsatt brukbare).
- Duplikater i skjøten: Sackmann-snapshotet slutter midt i sesongen, og
  tourney_date er turneringens STARTdato. Vi tar med tennis-data-rader fra
  45 dager før skjøten og dedupliserer på (tour, vinner, taper, ±nær dato).
- Runder: tennis-data har "1st Round"/"Quarterfinals" osv. — mappes til
  Sackmann-koder slik at kronologisk sortering innen turnering blir riktig.
  tennis-data har dessuten EKTE kampdato (bedre enn Sackmanns startdato).
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

from . import config
from .market_check import fetch_tennis_data, _td_cache_path

# Sesonger vi forlenger med. 2024 er med pga. skjøten (Sackmann stopper juli 2024).
EXT_SEASONS = [2024, 2025, 2026]

_ROUND_MAP = {
    "1st round": "R128", "2nd round": "R64", "3rd round": "R32", "4th round": "R16",
    "round robin": "RR", "quarterfinals": "QF", "semifinals": "SF", "the final": "F",
}

_SPLICE_LOOKBACK_DAYS = 45   # ta med td-rader fra så lenge før Sackmann-slutt
_DEDUP_WINDOW_DAYS = 21      # samme par innen +/- dette regnes som samme kamp


def _norm(s: object) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", s.lower())


def _td_key(name: str) -> tuple[str, str]:
    """tennis-data 'Etternavn F.' -> (etternavn-nøkkel, forbokstav)."""
    name = str(name).strip()
    m = re.search(r"^(.*?)((\s+[A-Za-z]\.?)+)\s*$", name)
    if m:
        surname, initials = m.group(1), m.group(2)
        first_initial = re.sub(r"[^A-Za-z]", "", initials)[:1].lower()
        return _norm(surname), first_initial
    return _norm(name), ""


def _sack_key(name: str) -> tuple[str, str]:
    """Sackmann 'Fornavn Mellomnavn Etternavn' -> (etternavn-nøkkel, forbokstav).

    Etternavn kan være flerdelt (Auger Aliassime, Davidovich Fokina, Van De
    Zandschulp) — bruk alt unntatt første token som etternavn, og fall tilbake
    til siste token.
    """
    toks = re.split(r"\s+", str(name).strip())
    if len(toks) >= 2:
        return _norm("".join(toks[1:])), _norm(toks[0])[:1]
    return _norm(name), ""


class NameResolver:
    """Kobler tennis-data-navn til Sackmann-spiller-id."""

    def __init__(self, matches: pd.DataFrame) -> None:
        w = matches[["winner_id", "winner_name", "date"]].rename(columns={"winner_id": "pid", "winner_name": "name"})
        l = matches[["loser_id", "loser_name", "date"]].rename(columns={"loser_id": "pid", "loser_name": "name"})
        long = pd.concat([w, l], ignore_index=True)
        agg = long.groupby(["pid", "name"]).agg(last=("date", "max"), n=("date", "size")).reset_index()
        # to indekser: (etternavn, initial) og bare etternavn — flerdelte
        # etternavn indekseres også på siste token (td kan bruke bare det).
        self.by_full: dict[tuple[str, str], list] = {}
        self.by_surname: dict[str, list] = {}
        for row in agg.itertuples(index=False):
            sk, ini = _sack_key(row.name)
            rec = (int(row.pid), str(row.name), row.last, int(row.n))
            self.by_full.setdefault((sk, ini), []).append(rec)
            self.by_surname.setdefault(sk, []).append(rec)
            toks = re.split(r"\s+", str(row.name).strip())
            if len(toks) > 2:  # også siste token som etternavn
                sk2 = _norm(toks[-1])
                if sk2 != sk:
                    self.by_full.setdefault((sk2, ini), []).append(rec)
                    self.by_surname.setdefault(sk2, []).append(rec)

    @staticmethod
    def _pick(cands: list) -> tuple[int, str]:
        best = max(cands, key=lambda r: (r[2], r[3]))  # sist aktiv, flest kamper
        return best[0], best[1]

    def resolve(self, td_name: str) -> tuple[int | None, str]:
        sk, ini = _td_key(td_name)
        # sammensatte td-etternavn kan ha mellomrom fjernet av _norm allerede
        for key in ((sk, ini),):
            if key in self.by_full:
                return self._pick(self.by_full[key])
        if sk in self.by_surname:
            cands = self.by_surname[sk]
            if len({c[0] for c in cands}) == 1 or not ini:
                return self._pick(cands)
            # flere med samme etternavn og ukjent initial-match -> mest aktive
            return self._pick(cands)
        return None, td_name

    @staticmethod
    def synthetic_id(td_name: str) -> int:
        """Stabil syntetisk id for spillere som ikke finnes hos Sackmann."""
        import zlib

        return 90_000_000 + zlib.crc32(_norm(td_name).encode()) % 1_000_000


def _load_td_season(tour: str, year: int) -> pd.DataFrame:
    df = pd.read_excel(_td_cache_path(tour, year))
    df["tour"] = tour
    return df


def build_extension(sackmann: pd.DataFrame, *, verbose: bool = True) -> pd.DataFrame:
    """Bygg forlengelses-rader (samme skjema som ingest) fra tennis-data."""
    fetch_tennis_data(EXT_SEASONS, verbose=verbose)
    resolver = NameResolver(sackmann)

    frames = [_load_td_season(tour, y) for tour in config.TOURS for y in EXT_SEASONS]
    td = pd.concat(frames, ignore_index=True)
    td = td.rename(columns={"Best of": "best_of_td"})
    td = td[td["Comment"].isin(["Completed", "Retired", "Awarded"])].copy()
    td["date"] = pd.to_datetime(td["Date"], errors="coerce")
    td = td[td["date"].notna() & td["Winner"].notna() & td["Loser"].notna()]

    # Skjøt pr. tour: fra 45 dager før Sackmann-slutt og fremover.
    cutoffs = sackmann.groupby("tour")["date"].max().to_dict()
    keep = []
    for tour, cut in cutoffs.items():
        m = (td["tour"] == tour) & (td["date"] >= cut - pd.Timedelta(days=_SPLICE_LOOKBACK_DAYS))
        keep.append(td[m])
    td = pd.concat(keep, ignore_index=True)

    # Dedupliser mot Sackmann i skjøtevinduet: samme (tour, vinner, taper) nær i tid.
    sack_pairs: dict[tuple, list] = {}
    for tour, cut in cutoffs.items():
        recent = sackmann[(sackmann["tour"] == tour)
                          & (sackmann["date"] >= cut - pd.Timedelta(days=90))]
        for r in recent.itertuples(index=False):
            k = (tour, _sack_key(r.winner_name)[0], _sack_key(r.loser_name)[0])
            sack_pairs.setdefault(k, []).append(r.date)

    rows = []
    dropped_dup = 0
    unresolved = 0
    for r in td.itertuples(index=False):
        wkey, _ = _td_key(r.Winner)
        lkey, _ = _td_key(r.Loser)
        k = (r.tour, wkey, lkey)
        dates = sack_pairs.get(k, [])
        if any(abs((r.date - d).days) <= _DEDUP_WINDOW_DAYS + 14 for d in dates):
            dropped_dup += 1
            continue  # allerede i Sackmann (tourney_date kan avvike -> romslig vindu)

        wid, wname = resolver.resolve(r.Winner)
        lid, lname = resolver.resolve(r.Loser)
        if wid is None:
            wid = NameResolver.synthetic_id(r.Winner)
            unresolved += 1
        if lid is None:
            lid = NameResolver.synthetic_id(r.Loser)
            unresolved += 1

        surface = str(getattr(r, "Surface", "Hard")).strip().capitalize()
        if surface not in config.SURFACES:
            surface = "Hard"
        rnd = _ROUND_MAP.get(str(getattr(r, "Round", "")).strip().lower(), "R32")
        rows.append({
            "date": r.date,
            "season": int(r.date.year),
            "tour": r.tour,
            "tourney": str(getattr(r, "Tournament", "")),
            "surface": surface,
            "winner_id": wid, "loser_id": lid,
            "winner_name": wname, "loser_name": lname,
            "winner_rank": pd.to_numeric(getattr(r, "WRank", None), errors="coerce"),
            "loser_rank": pd.to_numeric(getattr(r, "LRank", None), errors="coerce"),
            "winner_age": np.nan, "loser_age": np.nan,
            "best_of": pd.to_numeric(getattr(r, "best_of_td", None), errors="coerce"),
            "round": rnd,
        })

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out[out["winner_id"] != out["loser_id"]]
    if verbose:
        span = f"{out['date'].min().date()}–{out['date'].max().date()}" if len(out) else "-"
        print(f"  forlengelse: {len(out):,} kamper ({span}), "
              f"{dropped_dup:,} duplikater droppet, {unresolved:,} uløste navn (syntetisk id)")
    return out
