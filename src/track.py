"""Modul 7 — track.py

Sporing av faktiske veddemål: logg innsats og utfall, og sammenlign faktisk
ROI mot forventet, pluss en kalibreringskurve på MINE egne veddemål (vinner de
prosentandelen modellen lovet?).

Flyt:
- `log`    — loggfør dagens anbefalte veddemål (fra slip + bankroll) som åpne.
- `settle` — registrer utfall (vant/tapte) på et veddemål.
- `report` — skriv reports/track_record.md med ROI og kalibrering.

Logg lagres i data/odds/track_record.json. Hvert veddemål får en id.
"""
from __future__ import annotations

import json
import sys
from datetime import date as date_cls

import numpy as np
import pandas as pd

from . import config


# --- lagring -----------------------------------------------------------------
def load_log() -> list[dict]:
    if not config.TRACK_LOG.exists():
        return []
    return json.loads(config.TRACK_LOG.read_text())


def save_log(records: list[dict]) -> None:
    config.TRACK_LOG.write_text(json.dumps(records, indent=2, ensure_ascii=False))


def _next_id(records: list[dict]) -> int:
    return (max((r["bet_id"] for r in records), default=0)) + 1


# --- logging av veddemål -----------------------------------------------------
def log_bets(day: date_cls | None = None, bankroll: float = 1000.0) -> list[dict]:
    """Evaluer dagens slip og loggfør anbefalte veddemål som 'pending'."""
    from .ev_engine import evaluate_slip
    from .nt_odds import load_slip

    day = day or date_cls.today()
    entries = load_slip(day)
    if not entries:
        print(f"Ingen slip for {day}.")
        return load_log()
    df = evaluate_slip(entries, bankroll)
    bets = df[df["bet"]]

    records = load_log()
    existing_keys = {(r["placed_date"], r["match"], r["bet_on"]) for r in records}
    added = 0
    for r in bets.itertuples(index=False):
        key = (day.isoformat(), r.match, r.bet_on)
        if key in existing_keys:
            continue  # idempotent — ikke dobbeltloggfør samme veddemål
        records.append({
            "bet_id": _next_id(records),
            "placed_date": day.isoformat(),
            "book": getattr(r, "book", "nt"),
            "tour": r.tour,
            "surface": r.surface,
            "match": r.match,
            "bet_on": r.bet_on,
            "model_p": float(r.model_p),
            "nt_odds": float(r.nt_odds),
            "implied_p": float(r.implied_p),
            "ev": float(r.ev),
            "stake_kr": float(r.stake_kr),
            "status": "pending",
            "profit_kr": 0.0,
        })
        added += 1
    save_log(records)
    print(f"Loggførte {added} nye veddemål (totalt {len(records)} i loggen).")
    return records


def settle(bet_id: int, won: bool) -> dict:
    """Registrer utfall på et veddemål og regn ut gevinst/tap."""
    records = load_log()
    for r in records:
        if r["bet_id"] == bet_id:
            r["status"] = "won" if won else "lost"
            r["profit_kr"] = round(r["stake_kr"] * (r["nt_odds"] - 1.0) if won else -r["stake_kr"], 2)
            save_log(records)
            return r
    raise KeyError(f"Fant ikke veddemål {bet_id}")


def auto_settle(matches: pd.DataFrame, verbose: bool = True) -> int:
    """Avgjør åpne veddemål automatisk fra kampresultatene i datasettet.

    Kjøres etter hver dataoppdatering: finner resultatet for hvert åpne
    veddemål (samme spillerpar, spilt fra dagen før innsats og 14 dager frem)
    og registrerer vant/tapte uten at noen trykker på noe. Knappene i UI-et
    finnes fortsatt for kamper resultatkilden ikke har fått ennå.
    """
    from .nt_odds import _norm

    records = load_log()
    pending = [r for r in records if r["status"] == "pending"]
    if not pending:
        return 0
    n = 0
    for r in pending:
        if " – " not in r["match"]:
            continue
        a, b = (_norm(s) for s in r["match"].split(" – ", 1))
        placed = pd.Timestamp(r["placed_date"])
        cand = matches[(matches["date"] >= placed - pd.Timedelta(days=1))
                       & (matches["date"] <= placed + pd.Timedelta(days=14))]
        wn = cand["winner_name"].map(_norm)
        ln = cand["loser_name"].map(_norm)
        hit = cand[((wn == a) & (ln == b)) | ((wn == b) & (ln == a))]
        if hit.empty:
            continue
        row = hit.iloc[-1]
        won = _norm(row["winner_name"]) == _norm(r["bet_on"])
        settle(r["bet_id"], won)
        n += 1
        if verbose:
            print(f"  auto-avgjort #{r['bet_id']}: {r['bet_on']} {'VANT' if won else 'tapte'}")
    if n:
        write_report(load_log())
    return n


def settle_match(match_substr: str, bet_on: str, won: bool) -> dict:
    """Hjelper: registrer utfall via kamp-/spillernavn i stedet for id."""
    records = load_log()
    for r in records:
        if match_substr.lower() in r["match"].lower() and bet_on.lower() in r["bet_on"].lower() and r["status"] == "pending":
            return settle(r["bet_id"], won)
    raise KeyError(f"Fant ikke åpent veddemål for '{match_substr}' / '{bet_on}'")


# --- statistikk + rapport ----------------------------------------------------
def compute_stats(records: list[dict]) -> dict:
    df = pd.DataFrame(records)
    settled = df[df["status"].isin(["won", "lost"])] if not df.empty else df
    stats = {
        "n_total": len(df),
        "n_pending": int((df["status"] == "pending").sum()) if not df.empty else 0,
        "n_settled": len(settled),
        "n_won": int((settled["status"] == "won").sum()) if len(settled) else 0,
    }
    if len(settled):
        stake = settled["stake_kr"].sum()
        profit = settled["profit_kr"].sum()
        stats.update({
            "total_stake": float(stake),
            "total_profit": float(profit),
            "actual_roi": float(profit / stake) if stake else 0.0,
            "expected_profit": float((settled["stake_kr"] * settled["ev"]).sum()),
            "expected_roi": float((settled["stake_kr"] * settled["ev"]).sum() / stake) if stake else 0.0,
            "win_rate": float((settled["status"] == "won").mean()),
            "mean_model_p": float(settled["model_p"].mean()),
        })
    return stats


def calibration_on_bets(records: list[dict], bins: int = 5) -> pd.DataFrame:
    """Reliability på egne avgjorte veddemål: lovet P vs faktisk treff."""
    df = pd.DataFrame([r for r in records if r["status"] in ("won", "lost")])
    if df.empty:
        return pd.DataFrame(columns=["bin", "n", "mean_model_p", "win_rate"])
    df["won"] = (df["status"] == "won").astype(int)
    edges = np.linspace(df["model_p"].min(), df["model_p"].max() + 1e-9, bins + 1)
    df["b"] = np.clip(np.digitize(df["model_p"], edges[1:-1]), 0, bins - 1)
    out = df.groupby("b").agg(
        n=("won", "size"), mean_model_p=("model_p", "mean"), win_rate=("won", "mean")
    ).reset_index(drop=True)
    out.insert(0, "bin", [f"{i+1}" for i in range(len(out))])
    return out


def write_report(records: list[dict]) -> None:
    s = compute_stats(records)
    L: list[str] = []
    L.append("# Track record — Modul 7")
    L.append("")
    try:
        log_ref = config.TRACK_LOG.relative_to(config.ROOT)
    except ValueError:
        log_ref = config.TRACK_LOG
    L.append(f"_Egne veddemål logget i `{log_ref}`._")
    L.append("")
    L.append("## Status")
    L.append("")
    L.append(f"- Veddemål totalt: **{s['n_total']}** (åpne: {s['n_pending']}, avgjort: {s['n_settled']}).")
    if s["n_settled"]:
        sign = "+" if s["total_profit"] >= 0 else ""
        L.append(f"- Avgjorte: {s['n_won']}/{s['n_settled']} vunnet (treff {s['win_rate']*100:.1f} %).")
        L.append(f"- Innsats: {s['total_stake']:,.0f} kr. Resultat: **{sign}{s['total_profit']:,.0f} kr**.")
        L.append(f"- **Faktisk ROI: {s['actual_roi']*100:+.1f} %** mot forventet {s['expected_roi']*100:+.1f} %.")
        L.append(f"- Snitt modell-P på veddemålene: {s['mean_model_p']*100:.1f} % (faktisk treff {s['win_rate']*100:.1f} %).")
        L.append("")
        L.append("> Forventet ROI = innsatsvektet snitt-EV. Faktisk over/under dette er "
                 "variasjon på kort sikt; over mange veddemål skal de konvergere hvis "
                 "modellen er riktig kalibrert OG NT-oddsene faktisk ga kant.")
        L.append("")
        cal = calibration_on_bets(records)
        if not cal.empty and s["n_settled"] >= 10:
            L.append("## Kalibrering på egne veddemål")
            L.append("")
            L.append("| Bin | n | Snitt modell-P | Faktisk treff |")
            L.append("|---|---|---|---|")
            for r in cal.itertuples(index=False):
                L.append(f"| {r.bin} | {r.n} | {r.mean_model_p*100:.1f} % | {r.win_rate*100:.1f} % |")
            L.append("")
            _plot_track(records, L)
        else:
            L.append("_For få avgjorte veddemål (<10) til en meningsfull kalibreringskurve ennå._")
            L.append("")
    else:
        L.append("- Ingen avgjorte veddemål ennå — kjør `settle` etter hvert som resultatene kommer.")
        L.append("")
    L.append("## Åpne veddemål")
    L.append("")
    pend = [r for r in records if r["status"] == "pending"]
    if pend:
        L.append("| id | Dato | Bok | Kamp | Spill på | Modell-P | Odds | Innsats kr |")
        L.append("|---|---|---|---|---|---|---|---|")
        for r in pend:
            book = config.BOOK_LABELS.get(r.get("book", "nt"), r.get("book", "nt"))
            L.append(f"| {r['bet_id']} | {r['placed_date']} | {book} | {r['match']} | {r['bet_on']} | "
                     f"{r['model_p']*100:.1f} % | {r['nt_odds']:.2f} | {r['stake_kr']:.0f} |")
    else:
        L.append("_Ingen åpne veddemål._")
    L.append("")
    (config.REPORTS_DIR / "track_record.md").write_text("\n".join(L))


def _plot_track(records: list[dict], L: list[str]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cal = calibration_on_bets(records)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="Perfekt")
    ax.plot(cal["mean_model_p"], cal["win_rate"], "o-", label="Egne veddemål")
    ax.set_xlabel("Modell-P (lovet)"); ax.set_ylabel("Faktisk treff")
    ax.set_title("Kalibrering på egne veddemål"); ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout()
    out = config.REPORTS_DIR / "track_record.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    L.append(f"![Track-kalibrering]({out.name})")
    L.append("")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else "report"
    if cmd == "log":
        bankroll = 1000.0
        for i, a in enumerate(argv):
            if a in ("--bankroll", "-b") and i + 1 < len(argv):
                bankroll = float(argv[i + 1].replace(",", "."))
        log_bets(bankroll=bankroll)
        write_report(load_log())
    elif cmd == "settle":
        # track settle <bet_id> <win|loss>
        bet_id = int(argv[1])
        won = argv[2].lower() in ("win", "won", "w", "1", "ja")
        r = settle(bet_id, won)
        print(f"Avgjort #{bet_id}: {r['status']}, resultat {r['profit_kr']:+.0f} kr")
        write_report(load_log())
    else:  # report
        write_report(load_log())
        print(f"Skrev {config.REPORTS_DIR / 'track_record.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
