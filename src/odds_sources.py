"""Odds-kilder utover Norsk Tipping + markedssentiment.

Bakgrunn: NTs tennistilbud er tynt og nettleser-hentingen flaky. Pinnacle
(verdens skarpeste bok) har et åpent gjeste-API uten konto/innlogging som
dekker langt flere kamper. Oddsene derfra brukes til to ting:

1) FLERE KAMPER: Pinnacle-kampene legges i samme slip som NT-kampene,
   merket med `book`, og får EV på lik linje.
2) MARKEDSSENTIMENT: de-vigget Pinnacle-P er markedets konsensus om kampen.
   Markedet priser inn skader, form, trener­bytter og nyheter som Elo aldri
   ser. ev_engine blander denne med modellens kalibrerte P
   (config.MARKET_BLEND_WEIGHT), slik at rene modellfeil ikke lenger ser ut
   som gigantiske kanter.

Kambi-bøker (Unibet m.fl.) ble undersøkt og er stengt bak Akamai/sesjonsvern
— se PROGRESS.md. Nye kilder legges til som en funksjon her + et kall i
`fetch_all_odds`.
"""
from __future__ import annotations

import re
from datetime import date as date_cls
from datetime import datetime, timezone

import pandas as pd
import requests

from . import config
from .nt_odds import (
    PlayerIndex,
    build_surface_lookup,
    infer_surface,
    make_entry,
    save_slip,
)

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "X-API-Key": config.PINNACLE_GUEST_KEY,
    "Accept": "application/json",
}

# Ligaer modellen ikke dekker (Sackmann = hovedtour). Ukjent-spiller-vakten i
# ev_engine fanger det meste, men etternavns-kollisjoner kan feilkoble — så
# lavere nivåer filtreres bort allerede her.
_SKIP_LEAGUE = re.compile(r"challenger|itf|utr|exhibition|double", re.I)


def american_to_decimal(price: float) -> float:
    """Pinnacle bruker amerikanske odds: +138 -> 2.38, -165 -> 1.606."""
    p = float(price)
    return round(1.0 + (p / 100.0 if p > 0 else 100.0 / abs(p)), 3)


def _tour_from_league(name: str) -> str | None:
    if _SKIP_LEAGUE.search(name):
        return None
    low = name.lower()
    if low.startswith("wta") or "wta" in low:
        return "wta"
    if low.startswith("atp") or "atp" in low:
        return "atp"
    return None


def fetch_pinnacle_raw(timeout: int = 20) -> tuple[list, list]:
    """Hent matchups + moneyline-markeder for tennis fra gjeste-API-et."""
    sid = config.PINNACLE_TENNIS_SPORT_ID
    mu = requests.get(f"{config.PINNACLE_API}/sports/{sid}/matchups",
                      headers=_HEADERS, timeout=timeout)
    mk = requests.get(f"{config.PINNACLE_API}/sports/{sid}/markets/straight",
                      params={"primaryOnly": "true"}, headers=_HEADERS, timeout=timeout)
    mu.raise_for_status()
    mk.raise_for_status()
    return mu.json(), mk.json()


def parse_pinnacle(matchups: list, markets: list) -> list[dict]:
    """Pinnacle-JSON -> samme event-form som NT-parseren gir."""
    prices: dict[int, dict] = {}
    for m in markets:
        if m.get("type") == "moneyline" and m.get("period") == 0 and m.get("status") == "open":
            prices[m["matchupId"]] = m

    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for mu in matchups:
        if mu.get("type") != "matchup" or mu.get("parent") or mu.get("isLive"):
            continue
        league = (mu.get("league") or {}).get("name", "")
        tour = _tour_from_league(league)
        if tour is None:
            continue
        mk = prices.get(mu.get("id"))
        if mk is None:
            continue
        start = pd.to_datetime(mu.get("startTime"), errors="coerce", utc=True)
        if pd.notna(start) and start.to_pydatetime() < now:
            continue  # allerede i gang
        parts = {p.get("alignment"): p.get("name") for p in mu.get("participants", [])}
        home, away = parts.get("home"), parts.get("away")
        side = {p.get("designation"): p.get("price") for p in mk.get("prices", [])}
        if not home or not away or side.get("home") is None or side.get("away") is None:
            continue
        out.append({
            "home": home, "away": away, "tour": tour,
            "tournament": league, "start": mu.get("startTime"),
            "odds_home": american_to_decimal(side["home"]),
            "odds_away": american_to_decimal(side["away"]),
        })
    return out


def events_to_entries(events: list[dict], *, book: str, index: PlayerIndex,
                      lookup: dict[str, str], day: date_cls | None = None) -> list[dict]:
    """Felles: rå eventer -> slip-entries med spiller-id, underlag og bok."""
    entries: list[dict] = []
    for ev in events:
        a_id, a_name = index.resolve_label(ev["home"])
        b_id, b_name = index.resolve_label(ev["away"])
        when = pd.to_datetime(ev.get("start"), errors="coerce", utc=True)
        when = when.date() if pd.notna(when) else (day or date_cls.today())
        entries.append(make_entry(
            tour=ev.get("tour") or "atp",
            surface=infer_surface(ev["tournament"], when, lookup),
            tournament=ev["tournament"], source=book, book=book,
            player_a_id=a_id, player_a_name=ev["home"] if a_id is None else a_name,
            nt_odds_a=ev["odds_home"],
            player_b_id=b_id, player_b_name=ev["away"] if b_id is None else b_name,
            nt_odds_b=ev["odds_away"],
        ))
    return entries


def fetch_pinnacle(day: date_cls | None = None, *, matches: pd.DataFrame | None = None,
                   index: PlayerIndex | None = None, verbose: bool = True) -> list[dict]:
    """Hent dagens Pinnacle-tennisodds (hovedtour, singel, prematch)."""
    if matches is None:
        from .ingest import load_matches
        matches = load_matches()
    index = index or PlayerIndex.from_matches(matches)
    lookup = build_surface_lookup(matches)
    events = parse_pinnacle(*fetch_pinnacle_raw())
    entries = events_to_entries(events, book="pinnacle", index=index, lookup=lookup, day=day)
    if verbose:
        print(f"Hentet {len(entries)} kamper fra Pinnacle.")
    return entries


def fetch_all_odds(day: date_cls | None = None, *, matches: pd.DataFrame | None = None,
                   include_nt: bool = True, save: bool = True,
                   verbose: bool = True) -> tuple[list[dict], list[str]]:
    """Hent odds fra alle kilder til ÉN samlet slip (overskriver dagens).

    Pinnacle først (raskt HTTP-kall, gir sentiment-anker + mange kamper),
    deretter NT via nettleser (tregt/flaky — feil er ikke fatale).
    Returnerer (entries, advarsler).
    """
    if matches is None:
        from .ingest import load_matches
        matches = load_matches()
    index = PlayerIndex.from_matches(matches)

    entries: list[dict] = []
    warnings: list[str] = []

    try:
        entries += fetch_pinnacle(day, matches=matches, index=index, verbose=verbose)
    except Exception as exc:
        warnings.append(f"Pinnacle feilet: {exc}")

    if include_nt:
        try:
            from .nt_odds import fetch_nt_odds
            entries += fetch_nt_odds(day, matches=matches, index=index,
                                     save=False, verbose=verbose)
        except Exception as exc:
            warnings.append(f"Norsk Tipping feilet: {exc}")

    if not entries:
        raise RuntimeError("Ingen odds fra noen kilde. " + "; ".join(warnings))
    if save:
        save_slip(entries, day, replace=True)
    if verbose:
        for w in warnings:
            print(f"  ADVARSEL: {w}")
    return entries, warnings
