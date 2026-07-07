"""Modul 1c — results.py: tetter resultat-gapet med ESPNs åpne scoreboard.

tennis-data.co.uk (extend.py) publiserer 1–2 uker etter turnering. ESPN har
ferdige resultater SAMME DAG via åpent JSON-API (site.api.espn.com) med fulle
navn og vinner-flagg. Denne modulen henter STATUS_FINAL-singlekamper for
dagene etter siste resultat i datasettet og skjøter dem på, slik at Elo alltid
er à jour — Wimbledon-resultater er med samme kveld.

Caching: én JSON per (tour, dag) i data/raw/results_cache/. Gamle dager
caches for alltid; i dag/i går hentes på nytt (kamper avsluttes fortløpende).
Dedup: ESPN-eventer inneholder HELE turneringen uansett spørredato, så det
dedupliseres på competition-id, og kun kamper datert ETTER datasettets slutt
(per tour) brukes — når tennis-data tar igjen, tar dens rader over.
"""
from __future__ import annotations

import json
import time
from datetime import date as date_cls
from datetime import timedelta

import numpy as np
import pandas as pd
import requests

from . import config

_ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard"
_CACHE_DIR = config.RAW_DIR / "results_cache"
_MAX_GAP_DAYS = 30      # hent aldri mer enn dette bakover; eldre venter på tennis-data
_FRESH_MAX_AGE = 6 * 3600  # i dag/i går: hent på nytt hvis cache er eldre enn dette


def _cache_path(tour: str, day: date_cls):
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{tour}_{day.isoformat()}.json"


def fetch_day(tour: str, day: date_cls, timeout: int = 20) -> dict:
    """Hent scoreboard for én dag med caching. Nettverksfeil -> cache/{}."""
    path = _cache_path(tour, day)
    fresh_day = day >= date_cls.today() - timedelta(days=1)
    if path.exists() and not (fresh_day and time.time() - path.stat().st_mtime > _FRESH_MAX_AGE):
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    try:
        r = requests.get(_ESPN_URL.format(tour=tour),
                         params={"dates": day.strftime("%Y%m%d")},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        if r.status_code == 200:
            path.write_text(r.text)
            return r.json()
    except requests.RequestException:
        pass
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def parse_scoreboard(payload: dict) -> list[dict]:
    """ESPN-scoreboard -> ferdige singlekamper (hoveddraw)."""
    out: list[dict] = []
    for ev in payload.get("events", []):
        tournament = ev.get("name", "")
        for grp in ev.get("groupings", []):
            gname = (grp.get("grouping", {}).get("displayName") or "").lower()
            if "singles" not in gname or "qualif" in gname:
                continue
            tour = "wta" if "women" in gname else "atp"
            for comp in grp.get("competitions", []):
                status = (comp.get("status", {}).get("type", {}) or {}).get("name")
                if status != "STATUS_FINAL":
                    continue
                sides = comp.get("competitors", [])
                if len(sides) != 2:
                    continue
                names = [(s.get("athlete", {}) or {}).get("displayName") for s in sides]
                wins = [bool(s.get("winner")) for s in sides]
                if not all(names) or sum(wins) != 1:
                    continue
                winner = names[0] if wins[0] else names[1]
                loser = names[1] if wins[0] else names[0]
                when = pd.to_datetime(comp.get("date"), errors="coerce", utc=True)
                if pd.isna(when):
                    continue
                out.append({
                    "espn_id": comp.get("id"),
                    "date": when.tz_convert("Europe/Oslo").normalize().tz_localize(None),
                    "tour": tour,
                    "tournament": tournament,
                    "winner_name": winner,
                    "loser_name": loser,
                })
    return out


def build_results_extension(base: pd.DataFrame, *, verbose: bool = True) -> pd.DataFrame:
    """Kamper fra ESPN for dagene ETTER siste resultat i `base` (per tour)."""
    from .extend import NameResolver
    from .nt_odds import PlayerIndex, build_surface_lookup, infer_surface

    cutoffs = {t: d.normalize() for t, d in base.groupby("tour")["date"].max().items()}
    today = date_cls.today()
    start = min(c.date() for c in cutoffs.values()) + timedelta(days=1)
    start = max(start, today - timedelta(days=_MAX_GAP_DAYS))
    if start > today:
        return pd.DataFrame()

    rows: list[dict] = []
    seen: set = set()
    for tour in config.TOURS:
        for i in range((today - start).days + 1):
            day = start + timedelta(days=i)
            for r in parse_scoreboard(fetch_day(tour, day)):
                key = r["espn_id"] or (r["tour"], r["winner_name"], r["loser_name"], str(r["date"]))
                if key in seen:
                    continue
                seen.add(key)
                if r["date"] <= cutoffs.get(r["tour"], pd.Timestamp.min):
                    continue  # dekket av tennis-data allerede
                rows.append(r)

    if not rows:
        if verbose:
            print("  resultat-gap: ingen nye kamper fra ESPN")
        return pd.DataFrame()

    index = PlayerIndex.from_matches(base)
    lookup = build_surface_lookup(base)
    out_rows = []
    unresolved = 0
    for r in rows:
        wid, wname = index.resolve_label(r["winner_name"])
        lid, lname = index.resolve_label(r["loser_name"])
        if wid is None:
            wid, unresolved = NameResolver.synthetic_id(r["winner_name"]), unresolved + 1
        if lid is None:
            lid, unresolved = NameResolver.synthetic_id(r["loser_name"]), unresolved + 1
        if wid == lid:
            continue
        out_rows.append({
            "date": r["date"],
            "season": int(r["date"].year),
            "tour": r["tour"],
            "tourney": r["tournament"],
            "surface": infer_surface(r["tournament"], r["date"].date(), lookup),
            "winner_id": wid, "loser_id": lid,
            "winner_name": wname, "loser_name": lname,
            "winner_rank": np.nan, "loser_rank": np.nan,
            "winner_age": np.nan, "loser_age": np.nan,
            "best_of": np.nan, "round": "R32",
        })
    out = pd.DataFrame(out_rows)
    if verbose and len(out):
        print(f"  resultat-gap (ESPN): {len(out):,} kamper "
              f"({out['date'].min().date()}–{out['date'].max().date()}), "
              f"{unresolved} uløste navn (syntetisk id)")
    return out
