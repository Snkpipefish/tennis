"""Modul 5 — nt_odds.py

Henter Norsk Tipping-odds AUTOMATISK. Leif taster aldri inn noe.

NTs "Oddsen" er en egen sportsbok (ikke Kambi). Odds streames via WebSocket
(SockJS) når man navigerer til Tennis. `harvest_nt_odds()` styrer en ekte
nettleser (Playwright, persistent profil) til norsk-tipping.no/sport, velger
Tennis i venstre sportsliste (ligger i en iframe) og åpner turneringene, mens
den samler WS-rammene. `parse_ws_frames()` (ren, testbar) plukker ut kampene:
markedet "Vinner" med to selections, fraksjonsodds i currentpriceup/-down
=> desimal = 1 + up/down. Spillere kobles til Sackmann-id og lagres som slip.

En ekte nettleser er nødvendig fordi NT er bot-beskyttet (Akamai) — direkte
HTTP-kall gir 429. Parseren er enhetstestet mot ekte fangede rammer.

Modus A (manuell inntasting) finnes kun som nødløsning via `interactive()`.
Gamle Kambi-hjelpere (parse_events/ingest_payload) beholdes ubrukt som referanse.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from . import config

_ACTIVE_SINCE = config.YEAR_END - 4


def _norm(s: object) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", s.lower())


def _surname(name: str) -> str:
    toks = re.split(r"\s+", str(name).strip())
    return _norm(toks[-1]) if toks else ""


def _strip_initials(label: str) -> str:
    """'Djokovic N.' -> 'Djokovic' (fjern etterfølgende initialer)."""
    return re.sub(r"(\s+[A-Za-z]\.?)+\s*$", "", str(label).strip()).strip()


# --- spilleroppslag ----------------------------------------------------------
class PlayerIndex:
    """Slår opp Sackmann-spiller-id fra et navn."""

    def __init__(self, players: pd.DataFrame) -> None:
        self.players = players

    @classmethod
    def from_matches(cls, matches: pd.DataFrame | None = None, active_since: int = _ACTIVE_SINCE) -> "PlayerIndex":
        if matches is None:
            from .ingest import load_matches

            matches = load_matches()
        w = matches[["winner_id", "winner_name", "season"]].rename(
            columns={"winner_id": "player_id", "winner_name": "name"})
        l = matches[["loser_id", "loser_name", "season"]].rename(
            columns={"loser_id": "player_id", "loser_name": "name"})
        long = pd.concat([w, l], ignore_index=True).dropna(subset=["player_id"])
        long["player_id"] = long["player_id"].astype(int)
        long = long.sort_values("season")
        canon = long.groupby("player_id").agg(
            name=("name", "last"), last_season=("season", "max"), n_total=("season", "size"),
        ).reset_index()
        recent = long[long["season"] >= active_since].groupby("player_id").size()
        canon["n_recent"] = canon["player_id"].map(recent).fillna(0).astype(int)
        canon["surname"] = canon["name"].map(_surname)
        canon["fullnorm"] = canon["name"].map(_norm)
        return cls(canon)

    def search(self, query: str, *, only_active: bool = True, limit: int = 8) -> pd.DataFrame:
        q = _norm(query)
        if not q:
            return self.players.iloc[0:0]
        df = self.players
        exact = df["surname"] == q
        contains = df["fullnorm"].str.contains(re.escape(q), na=False)
        cand = df[exact | contains].copy()
        cand["score"] = exact.loc[cand.index].astype(int) * 2 + contains.loc[cand.index].astype(int)
        if only_active and (cand["n_recent"] > 0).any():
            cand = cand[cand["n_recent"] > 0]
        cand = cand.sort_values(["score", "n_recent", "last_season"], ascending=False)
        return cand[["player_id", "name", "last_season", "n_recent"]].head(limit).reset_index(drop=True)

    def resolve_one(self, query: str) -> tuple[int, str] | None:
        cand = self.search(query)
        if len(cand) == 0:
            return None
        return int(cand.iloc[0]["player_id"]), str(cand.iloc[0]["name"])

    def resolve_label(self, label: str) -> tuple[int | None, str]:
        """Robust oppslag for Kambi-navn ('Djokovic N.', 'Novak Djokovic', 'N. Djokovic')."""
        toks = re.split(r"\s+", str(label).strip())
        queries = [_strip_initials(label), str(label), toks[-1] if toks else ""]
        for q in queries:
            if not q:
                continue
            res = self.resolve_one(q)
            if res is not None:
                return res
        return None, str(label)


# --- underlag-inferens -------------------------------------------------------
def build_surface_lookup(matches: pd.DataFrame | None = None) -> dict[str, str]:
    """Normalisert turneringsnavn -> vanligste underlag (fra historikk)."""
    if matches is None:
        from .ingest import load_matches

        matches = load_matches()
    df = matches.copy()
    df["tnorm"] = df["tourney"].map(_norm)
    mode = df.groupby("tnorm")["surface"].agg(lambda s: s.value_counts().idxmax())
    return mode.to_dict()


def infer_surface(tournament: str, when: date_cls | None, lookup: dict[str, str]) -> str:
    """Finn underlag fra turneringsnavn; ellers grovt anslag fra årstid."""
    key = _norm(tournament)
    if key in lookup:
        return lookup[key]
    for tnorm, surf in lookup.items():  # delvis treff (f.eks. "wimbledon" i navnet)
        if tnorm and (tnorm in key or key in tnorm):
            return surf
    # Årstid-fallback: grasturneringer juni–juli, grus april–juni, ellers hard.
    m = (when or date_cls.today()).month
    if m in (6, 7):
        return "Grass"
    if m in (4, 5):
        return "Clay"
    return "Hard"


# --- Kambi-klient ------------------------------------------------------------
def fetch_listview(timeout: int = 30) -> dict:
    """Hent rått tennis-tilbud fra NT/Kambi. Reiser ved feil/blokkering."""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.norsk-tipping.no/",
    }
    r = requests.get(config.KAMBI_TENNIS_LISTVIEW, params=config.KAMBI_PARAMS, headers=headers, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(
            f"NT/Kambi svarte {r.status_code}. Trolig IP-blokkering (datasenter-IP). "
            f"Kjør fra norsk hjemme-IP."
        )
    return r.json()


def _classify_tour(text: str) -> str | None:
    t = text.lower()
    if "wta" in t or "women" in t or "damer" in t:
        return "wta"
    if "atp" in t or "herrer" in t or re.search(r"\bmen\b", t):
        return "atp"
    return None  # Challenger/ITF/ukjent -> hopp over


def parse_events(payload: dict) -> list[dict]:
    """Parse Kambi listView -> liste med {home, away, tour, tournament, start, odds_home, odds_away}."""
    out: list[dict] = []
    for item in payload.get("events", []):
        e = item.get("event", {})
        home, away = e.get("homeName"), e.get("awayName")
        name = e.get("name", "")
        if (not home or not away) and " - " in name:
            home, away = (s.strip() for s in name.split(" - ", 1))
        if not home or not away:
            continue
        path_names = [p.get("name", "") for p in e.get("path", []) if isinstance(p, dict)]
        tournament = path_names[-1] if path_names else (e.get("group") or "")
        tour = _classify_tour(" ".join(path_names + [e.get("group", ""), e.get("englishName", ""), name]))
        if tour is None:
            continue

        bo = _match_betoffer(item.get("betOffers", []))
        if bo is None:
            continue
        odds = _outcome_odds(bo, home, away)
        if odds is None:
            continue
        out.append({
            "event_id": e.get("id"),
            "home": home,
            "away": away,
            "tour": tour,
            "tournament": tournament,
            "start": e.get("start"),
            "odds_home": odds[0],
            "odds_away": odds[1],
        })
    return out


def _match_betoffer(betoffers: list[dict]) -> dict | None:
    """Finn 'Match'/vinner-tilbudet med nøyaktig to utfall."""
    for bo in betoffers:
        bt = bo.get("betOfferType", {})
        if (bt.get("name") == "Match" or bt.get("id") == 2) and len(bo.get("outcomes", [])) == 2:
            return bo
    for bo in betoffers:  # fallback: første to-veis tilbud
        if len(bo.get("outcomes", [])) == 2:
            return bo
    return None


def _outcome_odds(betoffer: dict, home: str, away: str) -> tuple[float, float] | None:
    """Map de to utfallene til (odds_home, odds_away). Odds er ×1000 hos Kambi."""
    oh = oa = None
    hn, an = _norm(home), _norm(away)
    for oc in betoffer.get("outcomes", []):
        raw = oc.get("odds")
        if raw is None:
            return None
        dec = raw / 1000.0
        label = _norm(oc.get("participant") or oc.get("label") or "")
        otype = oc.get("type", "")
        if otype == "OT_ONE" or label == hn or (label and label in hn):
            oh = dec
        elif otype == "OT_TWO" or label == an or (label and label in an):
            oa = dec
    if oh is None or oa is None:
        return None
    return oh, oa


# --- lagring -----------------------------------------------------------------
def slip_path(day: date_cls | None = None) -> Path:
    day = day or date_cls.today()
    return Path(config.ODDS_DIR) / f"nt_odds_{day.isoformat()}.json"


def make_entry(*, tour: str, surface: str,
               player_a_id: int | None, player_a_name: str, nt_odds_a: float,
               player_b_id: int | None, player_b_name: str, nt_odds_b: float,
               source: str = "kambi", tournament: str = "", book: str = "nt",
               kind: str = "single", start: str | None = None) -> dict:
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "book": book,
        "kind": kind,          # single | double (double har ingen modell-P)
        "start": start,        # ISO-starttid fra boka, for turneringsplanen
        "tour": tour,
        "surface": surface,
        "tournament": tournament,
        "player_a_id": player_a_id,
        "player_a_name": player_a_name,
        "nt_odds_a": float(nt_odds_a),
        "player_b_id": player_b_id,
        "player_b_name": player_b_name,
        "nt_odds_b": float(nt_odds_b),
    }


def save_slip(entries: list[dict], day: date_cls | None = None, *, replace: bool = False) -> Path:
    """Lagre dagens slip. replace=True overskriver (fersk henting); ellers legges til."""
    path = slip_path(day)
    existing = [] if replace else (load_slip(day) if path.exists() else [])
    path.write_text(json.dumps(existing + entries, indent=2, ensure_ascii=False))
    return path


def load_slip(day: date_cls | None = None) -> list[dict]:
    path = slip_path(day)
    if not path.exists():
        return []
    return json.loads(path.read_text())


# --- automatisk henting (Modus B, standard) ----------------------------------
def ingest_payload(payload: dict, day: date_cls | None = None, *, matches: pd.DataFrame | None = None,
                   index: PlayerIndex | None = None, save: bool = True, verbose: bool = True) -> list[dict]:
    """Bygg en slip fra en allerede HENTET Kambi-payload (f.eks. fra bokmerket).

    Skiller selve hentingen fra parsingen, slik at odds kan komme fra Leifs
    nettleser (der Akamai-cookien er gyldig) i stedet for server-side requests.
    """
    if matches is None:
        from .ingest import load_matches

        matches = load_matches()
    index = index or PlayerIndex.from_matches(matches)
    lookup = build_surface_lookup(matches)

    events = parse_events(payload)
    entries: list[dict] = []
    unresolved = 0
    for ev in events:
        a_id, a_name = index.resolve_label(ev["home"])
        b_id, b_name = index.resolve_label(ev["away"])
        if a_id is None or b_id is None:
            unresolved += 1
        when = pd.to_datetime(ev.get("start"), errors="coerce")
        when = when.date() if pd.notna(when) else (day or date_cls.today())
        surface = infer_surface(ev["tournament"], when, lookup)
        entries.append(make_entry(
            tour=ev["tour"], surface=surface, tournament=ev["tournament"],
            player_a_id=a_id, player_a_name=ev["home"] if a_id is None else a_name, nt_odds_a=ev["odds_home"],
            player_b_id=b_id, player_b_name=ev["away"] if b_id is None else b_name, nt_odds_b=ev["odds_away"],
        ))
    if save and entries:
        save_slip(entries, day)
    if verbose:
        print(f"Bygde {len(entries)} NT-tenniskamper ({unresolved} med uløst spiller-id).")
    return entries


# Kandidat-URLer for Kambi tennis-listView (NT bruker som regel den første).
# ============================================================================
# NTs sportsbok (ekte kilde). Odds streames via WebSocket (SockJS) når man
# navigerer til Tennis. Ramme-format: a["<json>"]; kamper ligger i
# data[].change.events[].markets[] der markedet "Vinner" har 2 selections med
# fraksjonsodds (currentpriceup/currentpricedown). Desimal = 1 + up/down.
# ============================================================================
def _sockjs_unpack(raw: str):
    m = re.match(r"^a\[(.*)\]$", raw, re.S)
    if not m:
        return None
    try:
        inner = json.loads(m.group(1))
        return json.loads(inner) if isinstance(inner, str) else inner
    except Exception:
        return None


def _frac_to_decimal(sel: dict) -> float | None:
    up, down = sel.get("currentpriceup"), sel.get("currentpricedown")
    try:
        d = 1.0 + int(up) / int(down)
        return round(d, 3)
    except Exception:
        return None


def nt_name_to_query(name: str) -> str:
    """NT bruker 'Etternavn, Fornavn' -> 'Fornavn Etternavn' for oppslag."""
    name = str(name).strip()
    if "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return name


def _nt_tour(ev: dict) -> str | None:
    t = " ".join(str(ev.get(k, "")) for k in ("tournamentname", "tournamentgender", "name")).lower()
    if any(w in t for w in ("wta", "women", "kvinner", "dame", "girls")):
        return "wta"
    if any(w in t for w in ("atp", "men", "menn", "herrer", "boys")):
        return "atp"
    return None


def parse_ws_frames(frames: list[str]) -> list[dict]:
    """SockJS WS-rammer -> unike tenniskamper med Vinner-odds."""
    events: dict[str, dict] = {}
    for raw in frames:
        o = _sockjs_unpack(raw)
        if not isinstance(o, dict):
            continue
        for d in o.get("data", []):
            if not isinstance(d, dict):
                continue
            ch = d.get("change")
            if not isinstance(ch, dict):
                continue
            evs = ch.get("events") if isinstance(ch.get("events"), list) else ([ch] if ch.get("markets") else [])
            for ev in evs:
                if isinstance(ev, dict) and "tennis" in (ev.get("sporttypename") or "").lower() and ev.get("idfoevent"):
                    events[ev["idfoevent"]] = ev  # nyeste vinner

    out: list[dict] = []
    for ev in events.values():
        # Double (par med "/" i navnet) tas MED, merket kind="double" —
        # de vises i oversikten men får ingen modell-P (Elo er single).
        nm = ev.get("name", "")
        tn = (ev.get("tournamentname") or "").lower()
        is_double = "/" in nm or "double" in tn or "dobbel" in tn
        win = next((m for m in ev.get("markets", [])
                    if (m.get("name") or "").strip().lower() == "vinner"
                    and len(m.get("selections", [])) == 2), None)
        if not win:
            continue
        sels = sorted(win["selections"], key=lambda s: str(s.get("competitornumber", "9")))
        if any("/" in (s.get("name") or "") for s in sels):
            is_double = True
        dh, da = _frac_to_decimal(sels[0]), _frac_to_decimal(sels[1])
        if not dh or not da:
            continue
        out.append({
            "home": sels[0].get("name"), "away": sels[1].get("name"),
            "odds_home": dh, "odds_away": da,
            "tournament": ev.get("tournamentname", ""),
            "start": ev.get("tsstart"),
            "tour": _nt_tour(ev),
            "kind": "double" if is_double else "single",
        })
    return out


def _accept_consent(page) -> None:
    """Klikk KUN samtykkeknapp hvis synlig, og stopp etter første treff.
    (Brede etiketter som 'OK'/'Lukk' traff feil knapper og ødela navigasjonen.)"""
    for lab in ("Godta alle", "Godta", "Aksepter alle", "Aksepter"):
        try:
            el = page.get_by_role("button", name=lab, exact=False)
            if el.count() > 0 and el.first.is_visible():
                el.first.click(timeout=2000)
                page.wait_for_timeout(700)
                return
        except Exception:
            continue


def _sportsbook_frame(page, wait_ms: int = 20000):
    """Finn sportsbok-iframen (der sportslista og kampene ligger). Poller til
    den finnes — iframen lastes et stykke etter hoveddokumentet."""
    waited = 0
    while waited <= wait_ms:
        for fr in page.frames:
            if "sportsbook/" in fr.url and "betslip" not in fr.url:
                return fr
        page.wait_for_timeout(1000)
        waited += 1000
    return None


def _click_tennis_and_tournaments(page, debug: bool = False) -> object:
    """Velg Tennis i venstre sportsliste (i sportsbok-iframen). Da streamer NT
    single-kampene automatisk via WebSocket — ingen turneringsklikk nødvendig
    (påvist). Returnerer sportsbok-framen."""
    fr = _sportsbook_frame(page)
    if fr is None:
        if debug:
            print("  [klikk] fant ikke sportsbok-iframe", flush=True)
        page.wait_for_timeout(4000)
        return page
    try:
        loc = fr.get_by_text("Tennis", exact=True)
        loc.first.wait_for(state="visible", timeout=15000)
        loc.first.scroll_into_view_if_needed(timeout=3000)
        loc.first.click(timeout=5000)
        if debug:
            print("  [klikk] Tennis klikket", flush=True)
    except Exception as exc:
        if debug:
            print(f"  [klikk] Tennis-klikk feilet: {str(exc)[:100]}", flush=True)
    page.wait_for_timeout(12000)  # la single-kampene strømme inn
    return fr


def harvest_nt_odds(headless: bool = True, timeout: int = 60000, attempts: int = 8, debug: bool = False) -> list[str]:
    """Kjør ekte nettleser mot NT-sport, naviger til tennis, og samle WS-rammer.

    Selv-helbredende: prøver gjentatte ganger (direkte tennis-URL + klikk i
    sportslista) til single-tenniskamper faktisk er i strømmen, eller til
    forsøkene er brukt opp. NT viser fotball som default, og Tennis-klikket i
    iframe-en er ustabilt — derfor loopen.
    """
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import sync_playwright

    frames: list[str] = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(config.ODDS_DIR / "browser_profile"), headless=headless,
            locale="nb-NO", viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def _on_ws(ws):
            def _frame(payload):
                try:
                    if isinstance(payload, (bytes, bytearray)):
                        payload = payload.decode("utf-8", "replace")
                    if payload and len(payload) < 2_000_000 and "idfoevent" in payload:
                        frames.append(payload)
                except Exception:
                    pass
            ws.on("framereceived", _frame)

        page.on("websocket", _on_ws)
        try:
            page.goto("https://www.norsk-tipping.no/sport/oddsen", wait_until="domcontentloaded", timeout=timeout)
        except PWError as exc:
            ctx.close()
            raise RuntimeError(f"Fikk ikke lastet NT-sport: {exc}")
        _accept_consent(page)
        page.wait_for_timeout(5000)

        # Tennis-URL-en laster ikke innhold — man MÅ klikke seg frem i
        # sportslista. Prøv klikke-navigasjonen på nytt til single-tennis er i
        # strømmen (Tennis-klikket i iframe-en er ustabilt).
        # Klikk Tennis, og re-klikk til single-kampene faktisk streamer (WS er
        # treg/ustabil). IKKE reload mellom forsøk — det nullstiller WS-en.
        fr = _sportsbook_frame(page) or page
        for attempt in range(attempts):
            try:
                loc = fr.get_by_text("Tennis", exact=True)
                loc.first.wait_for(state="visible", timeout=12000)
                loc.first.scroll_into_view_if_needed(timeout=3000)
                loc.first.click(timeout=5000)
            except Exception as exc:
                if debug:
                    print(f"  [klikk {attempt+1}] feilet: {str(exc)[:80]}", flush=True)
            page.wait_for_timeout(9000)  # la kampene strømme
            n_single = len(parse_ws_frames(frames))
            if debug:
                print(f"  [harvest {attempt+1}/{attempts}] rammer={len(frames)} single={n_single}", flush=True)
            if n_single:
                break
        ctx.close()

    # Dump alltid rammene til disk (for inspeksjon ved bom, uten ny NT-kjøring).
    try:
        import time as _t
        dbg = config.ODDS_DIR / "capture" / f"harvest_{_t.strftime('%Y%m%d_%H%M%S')}.jsonl"
        dbg.parent.mkdir(parents=True, exist_ok=True)
        with dbg.open("w") as fh:
            for fr in frames:
                fh.write(json.dumps({"type": "ws", "body": fr}) + "\n")
    except Exception:
        pass
    return frames


def fetch_nt_odds(day: date_cls | None = None, *, matches: pd.DataFrame | None = None,
                  index: PlayerIndex | None = None, save: bool = True, verbose: bool = True,
                  headless: bool | None = None) -> list[dict]:
    """Hent dagens NT-tenniskamper via nettleser (WS), koble spillere, lagre slip.

    Kjører headless (usynlig) som standard — påvist å virke mot NT.
    Sett NT_HEADFUL=1 for synlig vindu ved feilsøking."""
    import os as _os
    import subprocess as _sp
    import sys as _sys

    from playwright.sync_api import Error as PWError

    _dbg = bool(_os.environ.get("NT_DEBUG"))
    if headless is None:
        headless = not bool(_os.environ.get("NT_HEADFUL"))

    def _harvest() -> list[str]:
        try:
            return harvest_nt_odds(headless=headless, debug=_dbg)
        except PWError as exc:
            if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc).lower():
                if verbose:
                    print("Laster ned nettlesermotor (engangsjobb) ...", flush=True)
                _sp.run([_sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                return harvest_nt_odds(headless=headless, debug=_dbg)
            raise

    # NTs SPA er ustabil per økt (noen ganger streamer den bare én generisk
    # ramme uansett re-klikk). En HELT fersk nettleserøkt løser det som regel —
    # så prøv flere økter automatisk i stedet for at daily må kjøres på nytt.
    sessions = max(1, int(_os.environ.get("NT_SESSIONS", "3")))
    matches_out: list[dict] = []
    for attempt in range(sessions):
        frames = _harvest()
        matches_out = parse_ws_frames(frames)
        if matches_out:
            break
        if verbose and attempt + 1 < sessions:
            print(f"  Ingen tenniskamper i strømmen — prøver ny nettleserøkt "
                  f"({attempt + 2}/{sessions}) ...", flush=True)
    if not matches_out:
        raise RuntimeError("Fant ingen tenniskamper i NT-strømmen (ingen tennis ute, eller navigasjon feilet).")

    if matches is None:
        from .ingest import load_matches
        matches = load_matches()
    index = index or PlayerIndex.from_matches(matches)
    lookup = build_surface_lookup(matches)

    entries: list[dict] = []
    for m in matches_out:
        kind = m.get("kind", "single")
        if kind == "double":
            a_id = b_id = None
            a_name, b_name = m["home"], m["away"]
        else:
            a_id, a_name = index.resolve_label(nt_name_to_query(m["home"]))
            b_id, b_name = index.resolve_label(nt_name_to_query(m["away"]))
        when = pd.to_datetime(m.get("start"), errors="coerce", utc=True)
        when = when.date() if pd.notna(when) else (day or date_cls.today())
        entries.append(make_entry(
            tour=m.get("tour") or "atp",
            surface=infer_surface(m["tournament"], when, lookup),
            tournament=m["tournament"], kind=kind, start=m.get("start"),
            player_a_id=a_id, player_a_name=m["home"] if a_id is None else a_name, nt_odds_a=m["odds_home"],
            player_b_id=b_id, player_b_name=m["away"] if b_id is None else b_name, nt_odds_b=m["odds_away"],
        ))
    if save and entries:
        save_slip(entries, day, replace=True)  # fersk henting overskriver dagens slip
    if verbose:
        print(f"Hentet {len(entries)} NT-tenniskamper.")
    return entries


# --- manuell nødløsning (Modus A) -------------------------------------------
def interactive(day: date_cls | None = None):
    """NØDLØSNING — manuell inntasting. Ikke del av daglig flyt (Leif taster ikke)."""
    index = PlayerIndex.from_matches()
    print("MANUELL nødinntasting (normalt hentes odds automatisk). Tom 'tour' avslutter.\n")
    entries: list[dict] = []
    while True:
        tour = input("Tour [atp/wta] (blank = ferdig): ").strip().lower()
        if not tour:
            break
        if tour not in config.TOURS:
            print("  Ugyldig tour."); continue
        surface = input("Underlag [Hard/Clay/Grass]: ").strip().capitalize()
        a = index.resolve_one(input("Spiller A: ").strip()) or (None, input("  Fullt navn A: ").strip())
        b = index.resolve_one(input("Spiller B: ").strip()) or (None, input("  Fullt navn B: ").strip())
        try:
            oa = float(input(f"  NT-odds {a[1]}: ").replace(",", "."))
            ob = float(input(f"  NT-odds {b[1]}: ").replace(",", "."))
        except ValueError:
            print("  Ugyldig odds."); continue
        entries.append(make_entry(tour=tour, surface=surface, source="manual",
                                  player_a_id=a[0], player_a_name=a[1], nt_odds_a=oa,
                                  player_b_id=b[0], player_b_name=b[1], nt_odds_b=ob))
    if entries:
        print(f"Lagret {len(entries)} -> {save_slip(entries, day)}")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if "--manual" in argv:
        interactive()
    else:
        fetch_nt_odds()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
