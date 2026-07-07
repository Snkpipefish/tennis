"""Modul 4 — market_check.py

Validerer den kalibrerte modellen mot det skarpeste markedet (Pinnacle).
Pinnacle er notorisk effektivt; ligger modellen tett på Pinnacles de-viggede
sannsynligheter og er like godt kalibrert, kan vi stole på den. Store avvik
fra Pinnacle er som regel modellfeil, ikke kant — dette forteller oss hvor
store reelle kanter vi realistisk kan vente (mot NT, ikke mot Pinnacle).

Flyt:
1. Last closing odds fra tennis-data.co.uk (Pinnacle PSW/PSL + Bet365), ATP+WTA.
2. De-vig Pinnacle til ren implisitt P.
3. Koble hver kamp til modellens kalibrerte P (navn + årstall-join).
4. Sammenlign kalibrering (modell vs marked) og skriv reports/market_validation.md.
"""
from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from . import config
from .calibrate import winner_oriented_holdout
from .calibrate import metrics, reliability_table

# Hvilke sesonger vi validerer mot marked = holdout-sesongene der vi har OOS-preds.
_VALIDATION_SEASONS = list(range(config.YEAR_END - config.HOLDOUT_SEASONS + 1, config.YEAR_END + 1))


# --- navnenormalisering ------------------------------------------------------
def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _norm(s: object) -> str:
    return re.sub(r"[^a-z]", "", _strip_accents(str(s)).lower())


def sackmann_surname_key(name: object) -> str:
    """Sackmann 'Fornavn Etternavn(e)' -> normalisert etternavn (dropp fornavn)."""
    toks = re.split(r"\s+", str(name).strip())
    rest = toks[1:] if len(toks) > 1 else toks
    return _norm("".join(rest))


def tennis_data_surname_key(name: object) -> str:
    """tennis-data 'Etternavn X.' -> normalisert etternavn (dropp initialer)."""
    # Fjern etterfølgende initialer som 'M.' / 'J.M.' / 'D.E.'
    cleaned = re.sub(r"(\s+[A-Za-z]\.?)+\s*$", "", str(name).strip())
    return _norm(cleaned)


def devig_two_way(odds_a: float, odds_b: float) -> float:
    """De-vig to-veis marked -> ren implisitt P for utfall A (normalisert til 1)."""
    ia, ib = 1.0 / odds_a, 1.0 / odds_b
    return ia / (ia + ib)


# --- nedlasting --------------------------------------------------------------
def _td_cache_path(tour: str, year: int) -> Path:
    return config.TENNIS_DATA_CACHE / f"{tour}_{year}.xlsx"


def fetch_tennis_data(seasons: list[int] | None = None, *, force_refresh: bool = False, verbose: bool = True) -> None:
    """Last tennis-data-xlsx til cache.

    Ferdigspilte sesonger caches for alltid; INNEVÆRENDE sesong får nye
    resultater fortløpende og lastes derfor på nytt når cachen er eldre enn
    12 timer — det er slik modellen trener seg på ferske resultater. Feiler
    oppfriskingen beholdes den gamle filen (bedre gammelt enn ingenting)."""
    import datetime as _dt

    seasons = seasons or _VALIDATION_SEASONS
    this_year = _dt.date.today().year
    for tour in config.TOURS:
        for year in seasons:
            path = _td_cache_path(tour, year)
            stale = (year >= this_year and path.exists()
                     and time.time() - path.stat().st_mtime > 12 * 3600)
            if path.exists() and not force_refresh and not stale:
                continue
            url = config.TENNIS_DATA_URLS[tour].format(year=year)
            if verbose:
                print(f"  laster odds {tour} {year} ...", flush=True)
            for attempt in range(3):
                try:
                    r = requests.get(url, timeout=60)
                    if r.status_code == 200 and r.content:
                        path.write_bytes(r.content)
                        break
                except requests.RequestException:
                    pass
                time.sleep(1.0 * (attempt + 1))
            else:
                if path.exists():  # oppfrisking feilet -> behold gammel cache
                    if verbose:
                        print(f"  klarte ikke oppdatere {tour} {year} — bruker cachet fil")
                    continue
                raise RuntimeError(f"Klarte ikke laste odds {tour} {year}")


def load_odds(seasons: list[int] | None = None, *, force_refresh: bool = False) -> pd.DataFrame:
    """Last + rens tennis-data odds, de-vig Pinnacle og Bet365."""
    seasons = seasons or _VALIDATION_SEASONS
    fetch_tennis_data(seasons, force_refresh=force_refresh)
    frames = []
    for tour in config.TOURS:
        for year in seasons:
            df = pd.read_excel(_td_cache_path(tour, year))
            df["tour"] = tour
            df["season"] = year
            frames.append(df)
    odds = pd.concat(frames, ignore_index=True)

    # Behold reelle kamper med Pinnacle-odds. Walkover droppes (ingen kamp).
    odds = odds[odds["Comment"].isin(["Completed", "Retired"])]
    odds = odds.dropna(subset=["PSW", "PSL", "Winner", "Loser"])
    odds = odds[(odds["PSW"] > 1.0) & (odds["PSL"] > 1.0)]

    odds["date_odds"] = pd.to_datetime(odds["Date"], errors="coerce")
    odds["wkey"] = odds["Winner"].map(tennis_data_surname_key)
    odds["lkey"] = odds["Loser"].map(tennis_data_surname_key)

    # De-vig: implisitt P normalisert slik at de to summerer til 1.
    iw, il = 1.0 / odds["PSW"], 1.0 / odds["PSL"]
    over = iw + il
    odds["pinn_p_winner"] = iw / over
    odds["pinn_overround"] = over - 1.0  # margin (vig)
    if {"B365W", "B365L"}.issubset(odds.columns):
        bw, bl = 1.0 / odds["B365W"], 1.0 / odds["B365L"]
        odds["b365_p_winner"] = bw / (bw + bl)
    else:
        odds["b365_p_winner"] = np.nan

    return odds[
        ["season", "tour", "date_odds", "Tournament", "Surface", "Winner", "Loser",
         "wkey", "lkey", "PSW", "PSL", "pinn_p_winner", "pinn_overround", "b365_p_winner"]
    ].reset_index(drop=True)


# --- kobling modell <-> marked ----------------------------------------------
def match_model_to_market(seasons: list[int] | None = None) -> pd.DataFrame:
    """Koble modellens OOS-preds til Pinnacle-odds via (sesong, etternavn-par)."""
    seasons = seasons or _VALIDATION_SEASONS
    model = winner_oriented_holdout()
    model = model[model["season"].isin(seasons)].copy()
    model["wkey"] = model["winner_name"].map(sackmann_surname_key)
    model["lkey"] = model["loser_name"].map(sackmann_surname_key)
    model = model[(model["wkey"] != "") & (model["lkey"] != "")]

    odds = load_odds(seasons)
    odds = odds[(odds["wkey"] != "") & (odds["lkey"] != "")].copy()
    odds["odds_row"] = np.arange(len(odds))

    merged = odds.merge(model, on=["season", "tour", "wkey", "lkey"], how="inner", suffixes=("", "_m"))
    if merged.empty:
        return merged
    # Ved flere kandidater (samme par to ganger på et år): velg nærmest i dato.
    merged["datediff"] = (merged["date_odds"] - merged["date"]).abs()
    merged = merged.sort_values("datediff").drop_duplicates("odds_row", keep="first")
    return merged.reset_index(drop=True)


# --- analyse + rapport -------------------------------------------------------
def _reference_orientation(merged: pd.DataFrame) -> dict:
    """Re-orienter til spiller med lavest id for balanserte labels (reliability)."""
    ref_is_winner = merged["winner_id"] < merged["loser_id"]
    y = ref_is_winner.astype(int).to_numpy()
    p_model = np.where(ref_is_winner, merged["p_winner_cal"], 1 - merged["p_winner_cal"])
    p_pinn = np.where(ref_is_winner, merged["pinn_p_winner"], 1 - merged["pinn_p_winner"])
    return {"y": y, "p_model": p_model, "p_pinn": p_pinn}


def make_plot(merged: pd.DataFrame) -> str:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ref = _reference_orientation(merged)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    ax1.plot([0, 1], [0, 1], "k--", lw=1, label="Perfekt")
    for p, name, style in ((ref["p_model"], "Modell (kalibrert)", "o-"), (ref["p_pinn"], "Pinnacle (de-vigget)", "s-")):
        t = reliability_table(ref["y"], p)
        t = t[t["n"] > 0]
        ax1.plot(t["mean_pred"], t["frac_pos"], style, label=name)
    ax1.set_xlabel("Predikert P"); ax1.set_ylabel("Observert frekvens")
    ax1.set_title("Kalibrering: modell vs Pinnacle"); ax1.legend(); ax1.grid(alpha=0.3)

    ax2.scatter(merged["pinn_p_winner"], merged["p_winner_cal"], s=4, alpha=0.2)
    ax2.plot([0, 1], [0, 1], "k--", lw=1)
    ax2.set_xlabel("Pinnacle P(vinner)"); ax2.set_ylabel("Modell P(vinner)")
    ax2.set_title("Modell vs marked (per kamp)"); ax2.grid(alpha=0.3)

    fig.tight_layout()
    out = config.REPORTS_DIR / "market_validation.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out.name


def run_market_check(verbose: bool = True) -> dict:
    merged = match_model_to_market()
    if merged.empty:
        raise RuntimeError("Ingen kamper koblet modell<->marked — sjekk navnematching.")
    ref = _reference_orientation(merged)
    y = ref["y"]
    res = {
        "merged": merged,
        "model_metrics": metrics(y, ref["p_model"]),
        "pinn_metrics": metrics(y, ref["p_pinn"]),
        "n_matched": len(merged),
        "edge": merged["p_winner_cal"] - merged["pinn_p_winner"],
        "corr": float(np.corrcoef(merged["p_winner_cal"], merged["pinn_p_winner"])[0, 1]),
        "mean_overround": float(merged["pinn_overround"].mean()),
    }
    if verbose:
        print(f"  koblet {res['n_matched']:,} kamper modell<->Pinnacle")
        print(f"  modell:   {res['model_metrics']}")
        print(f"  Pinnacle: {res['pinn_metrics']}")
        print(f"  korrelasjon modell~Pinnacle: {res['corr']:.3f}")
    return res


def write_report(res: dict) -> None:
    merged = res["merged"]
    plot_name = make_plot(merged)
    mm, pm = res["model_metrics"], res["pinn_metrics"]
    edge = res["edge"]
    big_edges = (edge.abs() > 0.05).mean()

    L: list[str] = []
    L.append("# Markedsvalidering — Modul 4")
    L.append("")
    L.append("_Modellens kalibrerte sannsynligheter sammenlignet med Pinnacles "
             "closing odds (de-vigget). Pinnacle er referansen for et effektivt marked._")
    L.append("")
    L.append("## Sammendrag")
    L.append("")
    L.append(f"- Koblede kamper: **{res['n_matched']:,}** (sesongene {_VALIDATION_SEASONS[0]}–{_VALIDATION_SEASONS[-1]}, ATP+WTA).")
    L.append(f"- Korrelasjon modell vs Pinnacle: **{res['corr']:.3f}**.")
    L.append(f"- Pinnacles snittmargin (overround): **{res['mean_overround']*100:.1f} %**.")
    L.append(f"- Andel kamper med |modell − Pinnacle| > 5 %-poeng: **{big_edges*100:.1f} %**.")
    L.append("")
    L.append("| Kilde | Brier | Log-loss | ECE | n |")
    L.append("|---|---|---|---|---|")
    L.append(f"| Modell (kalibrert) | {mm['brier']:.4f} | {mm['logloss']:.4f} | {mm['ece']:.4f} | {mm['n']:,} |")
    L.append(f"| Pinnacle (de-vigget) | {pm['brier']:.4f} | {pm['logloss']:.4f} | {pm['ece']:.4f} | {pm['n']:,} |")
    L.append("")
    gap = mm["logloss"] - pm["logloss"]
    if gap <= 0.005:
        verdict = "Modellen er på høyde med Pinnacle på dette utvalget."
    elif gap <= 0.02:
        verdict = "Modellen er litt bak Pinnacle (forventet — markedet er skarpt), men konkurransedyktig."
    else:
        verdict = "Modellen er merkbart bak Pinnacle. Vær varsom: store avvik er trolig modellfeil, ikke kant."
    L.append(f"**Vurdering:** {verdict} Log-loss-gap modell − Pinnacle = {gap:+.4f}.")
    L.append("")
    L.append("## Hva betyr dette for +EV mot Norsk Tipping?")
    L.append("")
    L.append("Mot Pinnacle finnes nesten ingen kant. Reelle kanter oppstår der NTs "
             "odds avviker fra den skarpe konsensus. Bruk Pinnacle-avstanden som "
             "sanity-sjekk: er modellens P langt fra Pinnacle, stol mer på Pinnacle. "
             "Modul 6 leter etter NT-odds som er for høye relativt til den kalibrerte P-en "
             "som her er vist å ligge nær markedet.")
    L.append("")
    L.append("## Avvik (modell − Pinnacle), persentiler")
    L.append("")
    qs = edge.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
    L.append("| Persentil | Avvik (%-poeng) |")
    L.append("|---|---|")
    for q, v in qs.items():
        L.append(f"| {int(q*100)}% | {v*100:+.1f} |")
    L.append("")
    L.append("## Plott")
    L.append("")
    L.append(f"![Markedsvalidering]({plot_name})")
    L.append("")
    L.append("_Venstre: kalibreringskurver. Høyre: modell-P mot Pinnacle-P per kamp._")
    L.append("")

    (config.REPORTS_DIR / "market_validation.md").write_text("\n".join(L))


def main() -> int:
    res = run_market_check()
    write_report(res)
    print(f"Skrev {config.REPORTS_DIR / 'market_validation.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
