"""Modul 6 — ev_engine.py

Regner forventet verdi (EV) for hver kamp på dagens NT-slip, og foreslår
veddemål med innsats.

Regler (PLAN.md):
- EV = kalibrert_P * NT_odds − 1. Vedd kun hvis EV > 0,05 (5 %).
- Innsats = 1/4-Kelly på oppgitt bankroll. Aldri full Kelly.
- Output: reports/today_bets.md + terminaltabell sortert etter EV.

Den kalibrerte P-en er den samme som ble validert mot Pinnacle i Modul 4.
EV-terskelen på 5 % er en sikkerhetsmargin mot modellstøy: små kanter er som
regel støy, og NT er en softere bok enn Pinnacle slik at reelle kanter dukker
opp der NTs odds er for høye mot vår markedsnære P.
"""
from __future__ import annotations

import sys
from datetime import date as date_cls

import numpy as np
import pandas as pd

from . import config
from .calibrate import apply_calibrator, load_calibrator
from .elo import EloModel

EV_THRESHOLD = 0.05
KELLY_FRACTION = 0.25  # 1/4-Kelly
MAX_STAKE_FRACTION = 0.05  # aldri mer enn 5 % av bankroll på ett veddemål


def _model_p_a(model: EloModel, a_id, b_id, surface: str, base_variant: str) -> float:
    """Rå modell-P(A vinner) for valgt basis-variant. None-id -> 1500-default."""
    a = a_id if a_id is not None else -1
    b = b_id if b_id is not None else -2
    return model.probabilities(int(a), int(b), surface)[base_variant]


def _match_key(e: dict) -> tuple[int, int] | None:
    a, b = e.get("player_a_id"), e.get("player_b_id")
    if a is None or b is None:
        return None
    return (min(int(a), int(b)), max(int(a), int(b)))


def market_anchor(entries: list[dict]) -> dict[tuple[int, int], float]:
    """Markedssentiment: de-vigget Pinnacle-P per kamp.

    Nøkkel = (lavest, høyest spiller-id), verdi = P(spilleren med lavest id
    vinner) implisitt i Pinnacle-oddsene etter at vig-en er fjernet.
    """
    anchor: dict[tuple[int, int], float] = {}
    for e in entries:
        if e.get("book") != "pinnacle":
            continue
        key = _match_key(e)
        if key is None:
            continue
        ia, ib = 1.0 / e["nt_odds_a"], 1.0 / e["nt_odds_b"]
        p_a = ia / (ia + ib)
        anchor[key] = p_a if int(e["player_a_id"]) == key[0] else 1.0 - p_a
    return anchor


def quarter_kelly_stake(p: float, odds: float, bankroll: float) -> float:
    """1/4-Kelly innsats i kroner, aldri over MAX_STAKE_FRACTION av bankroll.
    0 hvis ingen kant."""
    b = odds - 1.0
    if b <= 0:
        return 0.0
    f_star = (p * odds - 1.0) / b  # full Kelly-andel
    f = min(max(0.0, f_star * KELLY_FRACTION), MAX_STAKE_FRACTION)
    return bankroll * f


def evaluate_slip(entries: list[dict], bankroll: float,
                  model: EloModel | None = None, bundle: dict | None = None) -> pd.DataFrame:
    """Vurder hver kamp/side og returner en tabell med EV og foreslått innsats."""
    model = model or EloModel.load()
    bundle = bundle or load_calibrator()
    base = bundle["base_variant"]

    anchor = market_anchor(entries)
    w = config.MARKET_BLEND_WEIGHT

    rows: list[dict] = []
    for e in entries:
        # Kamper der en spiller ikke fins i modellen får default-rating (P≈0.5),
        # som gir FALSKE kanter på høye odds. Vurder dem, men vedd aldri.
        known = e.get("player_a_id") is not None and e.get("player_b_id") is not None
        p_a_raw = _model_p_a(model, e.get("player_a_id"), e.get("player_b_id"), e["surface"], base)
        p_b_raw = 1.0 - p_a_raw
        # Kalibrer begge sider og renormaliser for koherens (sum = 1).
        ca = float(apply_calibrator(bundle, [p_a_raw])[0])
        cb = float(apply_calibrator(bundle, [p_b_raw])[0])
        s = ca + cb
        ca, cb = ca / s, cb / s

        # Markedssentiment: bland med de-vigget Pinnacle-P når den finnes.
        # Markedet ser skader/form/nyheter som Elo ikke gjør; uten anker
        # brukes ren modell-P som før.
        key = _match_key(e)
        p_mkt_a = None
        if key is not None and key in anchor:
            p = anchor[key]
            p_mkt_a = p if int(e["player_a_id"]) == key[0] else 1.0 - p
        fa = w * p_mkt_a + (1.0 - w) * ca if p_mkt_a is not None else ca
        fb = 1.0 - fa

        for side, name, opp, odds, p_use, p_elo in (
            ("A", e["player_a_name"], e["player_b_name"], e["nt_odds_a"], fa, ca),
            ("B", e["player_b_name"], e["player_a_name"], e["nt_odds_b"], fb, cb),
        ):
            ev = p_use * odds - 1.0
            # Vedd aldri MOT markedet: når et anker finnes må oddsen slå den
            # de-viggede Pinnacle-prisen ("beat the sharp line"). Ellers er
            # "kanten" bare modellstøy forsterket av høye odds.
            p_mkt = (p_mkt_a if side == "A" else 1.0 - p_mkt_a) if p_mkt_a is not None else None
            beats_market = p_mkt is None or p_mkt * odds - 1.0 > 0.0
            bet = ev > EV_THRESHOLD and known and beats_market
            rows.append({
                "book": e.get("book", "nt"),
                "tour": e["tour"],
                "surface": e["surface"],
                "match": f"{e['player_a_name']} – {e['player_b_name']}",
                "side": side,
                "bet_on": name,
                "opponent": opp,
                "model_p": p_use,  # P-en veddemålet faktisk bruker (blandet)
                "elo_p": p_elo,
                "market_p": p_mkt if p_mkt is not None else float("nan"),
                "nt_odds": odds,
                "implied_p": 1.0 / odds,
                "ev": ev,
                "known": known,
                "stake_kr": round(quarter_kelly_stake(p_use, odds, bankroll), 1) if bet else 0.0,
                "bet": bet,
            })
    df = pd.DataFrame(rows)
    return df.sort_values("ev", ascending=False).reset_index(drop=True)


def _fmt_pct(x: float) -> str:
    return "–" if pd.isna(x) else f"{x*100:.1f}%"


def _book_label(book: str) -> str:
    return config.BOOK_LABELS.get(book, book)


def render_table(df: pd.DataFrame, bets_only: bool = True) -> str:
    """Terminaltabell: Kamp | Bok | Spill på | P | Marked-P | Odds | EV% | Innsats kr."""
    view = df[df["bet"]] if bets_only else df
    if view.empty:
        return "(ingen veddemål over EV-terskelen)"
    headers = ["Kamp", "Bok", "Spill på", "P", "Marked-P", "Odds", "EV%", "Innsats kr"]
    lines = [headers]
    for r in view.itertuples(index=False):
        lines.append([
            r.match, _book_label(r.book), r.bet_on, _fmt_pct(r.model_p), _fmt_pct(r.market_p),
            f"{r.nt_odds:.2f}", f"{r.ev*100:+.1f}", f"{r.stake_kr:.0f}",
        ])
    widths = [max(len(row[i]) for row in lines) for i in range(len(headers))]
    out = []
    for j, row in enumerate(lines):
        out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
        if j == 0:
            out.append("  ".join("-" * widths[i] for i in range(len(headers))))
    return "\n".join(out)


def write_report(df: pd.DataFrame, bankroll: float, day: date_cls | None = None) -> None:
    day = day or date_cls.today()
    bets = df[df["bet"]]
    total_stake = bets["stake_kr"].sum()
    L: list[str] = []
    L.append(f"# Dagens veddemål — {day.isoformat()}")
    L.append("")
    L.append(f"_Bankroll: {bankroll:,.0f} kr. EV-terskel: {EV_THRESHOLD*100:.0f} %. "
             f"Innsats: {KELLY_FRACTION:g}-Kelly (maks {MAX_STAKE_FRACTION*100:.0f} % av bankroll). "
             f"P = {config.MARKET_BLEND_WEIGHT*100:.0f} % markedssentiment (de-vigget Pinnacle) "
             f"+ {100-config.MARKET_BLEND_WEIGHT*100:.0f} % kalibrert Elo der markedet har kampen; ellers ren Elo. "
             f"Vedd kun når oddsen i tillegg slår markedets de-viggede pris._")
    L.append("")
    n_matches = df["match"].nunique() if not df.empty else 0
    L.append(f"**{len(bets)} anbefalt(e) veddemål** av {n_matches} vurderte kamper. "
             f"Samlet innsats: {total_stake:,.0f} kr.")
    L.append("")
    if bets.empty:
        L.append("Ingen kamper passerte EV-terskelen i dag.")
    else:
        L.append("| Kamp | Bok | Spill på | P | Marked-P | Odds | EV% | Innsats kr |")
        L.append("|---|---|---|---|---|---|---|---|")
        for r in bets.itertuples(index=False):
            L.append(f"| {r.match} | {_book_label(r.book)} | {r.bet_on} | {_fmt_pct(r.model_p)} | "
                     f"{_fmt_pct(r.market_p)} | {r.nt_odds:.2f} | {r.ev*100:+.1f} | {r.stake_kr:.0f} |")
    L.append("")
    L.append("## Alle vurderte kamper (beste side/bok per kamp)")
    L.append("")
    L.append("| Kamp | Bok | Beste side | P | Marked-P | Odds | EV% | Vedd? |")
    L.append("|---|---|---|---|---|---|---|---|")
    best = df.sort_values("ev", ascending=False).drop_duplicates("match")
    for r in best.itertuples(index=False):
        verdict = "JA" if r.bet else ("nei (ukjent spiller)" if not r.known else "nei")
        L.append(f"| {r.match} | {_book_label(r.book)} | {r.bet_on} | {_fmt_pct(r.model_p)} | "
                 f"{_fmt_pct(r.market_p)} | {r.nt_odds:.2f} | {r.ev*100:+.1f} | {verdict} |")
    L.append("")
    (config.REPORTS_DIR / "today_bets.md").write_text("\n".join(L))


def run(bankroll: float, day: date_cls | None = None, verbose: bool = True) -> pd.DataFrame:
    from .nt_odds import load_slip

    entries = load_slip(day)
    if not entries:
        print(f"Ingen NT-odds lagret for {day or date_cls.today()}. Kjør Modul 5 (nt_odds) først.")
        return pd.DataFrame()
    df = evaluate_slip(entries, bankroll)
    write_report(df, bankroll, day)
    if verbose:
        print(render_table(df))
        print()
        print(f"Skrev {config.REPORTS_DIR / 'today_bets.md'}")
    return df


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    bankroll = 1000.0
    for i, a in enumerate(argv):
        if a in ("--bankroll", "-b") and i + 1 < len(argv):
            bankroll = float(argv[i + 1].replace(",", "."))
    run(bankroll)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
