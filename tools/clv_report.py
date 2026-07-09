"""CLV-rapport: slår våre tidlig-odds closing-linjen?

Sammenligner odds-snapshots (data/odds_history/*.jsonl, logget 4x/dag av
publish-workflowen) med Pinnacles closing-odds fra tennis-data.co.uk.

CLV (closing line value) per spill-side = snapshot-odds * de-vigget closing-P
− 1. Systematisk positiv CLV på modellens flaggede kanter er den eneste
kanten som ikke kan backtestes historisk — dette verktøyet måler den
etter hvert som snapshots samler seg opp.

Kjør: python -m tools.clv_report
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config, market_check  # noqa: E402

HISTORY_DIR = config.DATA_DIR / "odds_history"
MIN_MATCHED = 30  # under dette er tallene bare støy


def load_snapshots() -> pd.DataFrame:
    rows = []
    for f in sorted(glob.glob(str(HISTORY_DIR / "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            rows.extend(json.loads(line) for line in fh if line.strip())
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["start"] = pd.to_datetime(df["start"], utc=True, errors="coerce")
    return df


def earliest_per_side(df: pd.DataFrame) -> pd.DataFrame:
    """Tidligste snapshot per (kamp, side) = mest ledetid mot closing."""
    df = df[(df["known"] == True) & df["start"].notna()].copy()  # noqa: E712
    names = df["match"].str.split(" – ", n=1, expand=True)
    df["key_a"] = names[0].map(market_check.sackmann_surname_key)
    df["key_b"] = names[1].map(market_check.sackmann_surname_key)
    df["pair"] = [tuple(sorted(t)) for t in zip(df["key_a"], df["key_b"])]
    df["date"] = df["start"].dt.tz_convert(None).dt.normalize()
    df = df.sort_values("ts")
    return df.drop_duplicates(["pair", "date", "side"], keep="first")


def join_closing(snap: pd.DataFrame) -> pd.DataFrame:
    seasons = sorted(snap["date"].dt.year.unique())
    odds = market_check.load_odds(seasons)
    odds = odds[(odds["wkey"] != "") & (odds["lkey"] != "")].copy()
    odds["pair"] = [tuple(sorted(t)) for t in zip(odds["wkey"], odds["lkey"])]
    merged = snap.merge(
        odds[["pair", "date_odds", "Winner", "Loser", "wkey", "lkey",
              "PSW", "PSL", "pinn_p_winner"]],
        on="pair", how="inner")
    merged["datediff"] = (merged["date_odds"] - merged["date"]).abs().dt.days
    merged = merged[merged["datediff"] <= 3]
    merged = merged.sort_values("datediff").drop_duplicates(
        ["pair", "date", "side"], keep="first")

    bet_key = merged["bet_on"].map(market_check.sackmann_surname_key)
    on_winner = bet_key == merged["wkey"]
    merged["closed_p"] = np.where(on_winner, merged["pinn_p_winner"],
                                  1 - merged["pinn_p_winner"])
    merged["won"] = on_winner
    merged["clv"] = merged["nt_odds"] * merged["closed_p"] - 1.0
    merged["odds_close"] = np.where(on_winner, merged["PSW"], merged["PSL"])
    return merged.reset_index(drop=True)


def report(m: pd.DataFrame) -> str:
    L = ["# CLV-rapport — tidlig-odds mot closing", ""]

    def block(sub: pd.DataFrame, label: str) -> None:
        if sub.empty:
            L.append(f"- {label}: ingen spill ennå.")
            return
        roi = (np.where(sub["won"], sub["nt_odds"] - 1, -1.0)).mean()
        L.append(f"- {label}: n={len(sub)}, snitt-CLV {sub['clv'].mean()*100:+.2f} %, "
                 f"median {sub['clv'].median()*100:+.2f} %, "
                 f"flat ROI {roi*100:+.1f} %")

    block(m, "alle sider (baseline, skal være ~ -vig)")
    block(m[m["bet"] == True], "modellens SPILL-flagg")  # noqa: E712
    block(m[(m["ev"] > 0.02) & (m["bet"] == False)], "positiv EV under terskel")  # noqa: E712
    if len(m) < MIN_MATCHED:
        L.append("")
        L.append(f"**For lite data ennå** ({len(m)} koblede sider, trenger >{MIN_MATCHED} "
                 "— og helst hundrevis). La snapshots samle seg noen uker.")
    return "\n".join(L)


def main() -> int:
    snap = load_snapshots()
    if snap.empty:
        print("Ingen snapshots i data/odds_history/ ennå — publish-workflowen "
              "logger 4x/dag; kom tilbake om noen dager.")
        return 0
    sides = earliest_per_side(snap)
    print(f"{len(snap)} snapshot-rader, {len(sides)} unike (kamp, side).")
    m = join_closing(sides)
    print(f"{len(m)} sider koblet mot closing-odds.\n")
    txt = report(m)
    print(txt)
    out = config.REPORTS_DIR / "clv_report.md"
    out.write_text(txt + "\n", encoding="utf-8")
    print(f"\nSkrevet til {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
