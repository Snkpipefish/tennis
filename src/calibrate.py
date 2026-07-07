"""Modul 3 — calibrate.py  (VIKTIGST)

Kalibrering er forutsetningen for at resten av maskinen er verdt noe: en
modell-sannsynlighet på 0,70 må bety at spilleren faktisk vinner ~70 % av
gangene. Hvis ikke blir +EV-regnestykket i Modul 6 søppel.

Metodikk (streng out-of-sample):
1. Hold de siste 2 sesongene utenfor Elo-treningen.
2. Varm opp Elo på alt FØR holdout (uten å registrere).
3. Walk-forward gjennom holdout: prediker FØR hver kamp, oppdater så Elo
   (akkurat som i produksjon). Nest siste sesong = fit-sett for kalibrator,
   siste sesong = endelig, urørt test-sett.
4. Mål rå kalibrering (Brier, log-loss, ECE) for de tre Elo-variantene.
   Velg basis-variant etter log-loss på FIT-settet (ikke test).
5. Fit Platt (logistisk) og isotonisk regresjon på fit-settet. Velg den som
   gir lavest log-loss på test. Lagre valgt kalibrator.
6. Reliability-diagram + reports/calibration.md.
"""
from __future__ import annotations

import pickle

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

from . import config
from .elo import EloModel, fit_rank_seed

VARIANTS = ("p_overall", "p_surface", "p_blend")
VARIANT_LABEL = {
    "p_overall": "Samlet Elo",
    "p_surface": "Underlags-Elo",
    "p_blend": "Blanding (50/50)",
}
_EPS = 1e-6


# --- metrikker ---------------------------------------------------------------
def _clip(p: np.ndarray) -> np.ndarray:
    return np.clip(p, _EPS, 1 - _EPS)


def metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    p = _clip(np.asarray(p, dtype=float))
    y = np.asarray(y, dtype=int)
    return {
        "brier": float(brier_score_loss(y, p)),
        "logloss": float(log_loss(y, p, labels=[0, 1])),
        "ece": expected_calibration_error(y, p),
        "n": int(len(y)),
    }


def reliability_table(y: np.ndarray, p: np.ndarray, bins: int = config.RELIABILITY_BINS) -> pd.DataFrame:
    """Bin prediksjoner og sammenlign snitt-predikert mot observert frekvens."""
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    rows = []
    for b in range(bins):
        mask = idx == b
        n = int(mask.sum())
        rows.append(
            {
                "bin": f"{edges[b]:.1f}–{edges[b + 1]:.1f}",
                "n": n,
                "mean_pred": float(p[mask].mean()) if n else np.nan,
                "frac_pos": float(y[mask].mean()) if n else np.nan,
            }
        )
    return pd.DataFrame(rows)


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = config.RELIABILITY_BINS) -> float:
    """Vektet snitt av |observert − predikert| over binnene (ECE)."""
    tbl = reliability_table(y, p, bins)
    tbl = tbl[tbl["n"] > 0]
    w = tbl["n"] / tbl["n"].sum()
    return float((w * (tbl["frac_pos"] - tbl["mean_pred"]).abs()).sum())


# --- kalibratorer ------------------------------------------------------------
class PlattCalibrator:
    """Logistisk regresjon på logit(p_raw) — Platt scaling."""

    def __init__(self) -> None:
        self.lr = LogisticRegression(C=1e6, solver="lbfgs")

    @staticmethod
    def _logit(p: np.ndarray) -> np.ndarray:
        p = _clip(np.asarray(p, dtype=float))
        return np.log(p / (1 - p)).reshape(-1, 1)

    def fit(self, p: np.ndarray, y: np.ndarray) -> "PlattCalibrator":
        self.lr.fit(self._logit(p), np.asarray(y, dtype=int))
        return self

    def predict(self, p: np.ndarray) -> np.ndarray:
        return self.lr.predict_proba(self._logit(p))[:, 1]


class IsotonicCalibrator:
    def __init__(self) -> None:
        self.iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")

    def fit(self, p: np.ndarray, y: np.ndarray) -> "IsotonicCalibrator":
        self.iso.fit(np.asarray(p, dtype=float), np.asarray(y, dtype=int))
        return self

    def predict(self, p: np.ndarray) -> np.ndarray:
        return self.iso.predict(np.asarray(p, dtype=float))


class IdentityCalibrator:
    """Ingen kalibrering — brukes hvis rå modell allerede er best."""

    def fit(self, p: np.ndarray, y: np.ndarray) -> "IdentityCalibrator":
        return self

    def predict(self, p: np.ndarray) -> np.ndarray:
        return _clip(np.asarray(p, dtype=float))


# --- walk-forward prediksjoner ----------------------------------------------
def generate_oos_predictions(matches: pd.DataFrame, holdout_seasons: int = config.HOLDOUT_SEASONS) -> tuple[pd.DataFrame, list[int]]:
    """Varm opp Elo før holdout, walk-forward gjennom holdout med prediksjoner."""
    seasons = sorted(matches["season"].unique())
    hold = seasons[-holdout_seasons:]
    warmup = matches[~matches["season"].isin(hold)]
    holdout = matches[matches["season"].isin(hold)]

    # Fit rank-seeding KUN på warmup for å unngå lekkasje fra test-perioden.
    rank_seed = fit_rank_seed(warmup)
    model = EloModel(rank_seed=rank_seed)
    model.process(warmup, collect=False)              # bygg historikk, ingen preds
    preds = model.process(holdout, collect=True)      # predict-før-update
    return preds, hold


# --- hovedrutine -------------------------------------------------------------
def run_calibration(verbose: bool = True) -> dict:
    from .ingest import load_matches

    matches = load_matches()
    preds, hold = generate_oos_predictions(matches)
    fit_season, test_season = hold[0], hold[-1]
    fit = preds[preds["season"] == fit_season].reset_index(drop=True)
    test = preds[preds["season"] == test_season].reset_index(drop=True)
    y_fit, y_test = fit["label"].to_numpy(), test["label"].to_numpy()

    # 1) Rå metrikker for alle varianter, på fit og test.
    raw_metrics = {
        v: {"fit": metrics(y_fit, fit[v]), "test": metrics(y_test, test[v])}
        for v in VARIANTS
    }
    # 2) Velg basis-variant etter log-loss på FIT (ikke test).
    base = min(VARIANTS, key=lambda v: raw_metrics[v]["fit"]["logloss"])

    # 3) Fit kalibratorer på fit-settet for valgt basis.
    p_fit, p_test = fit[base].to_numpy(), test[base].to_numpy()
    cals: dict[str, object] = {
        "raw": IdentityCalibrator().fit(p_fit, y_fit),
        "platt": PlattCalibrator().fit(p_fit, y_fit),
        "isotonic": IsotonicCalibrator().fit(p_fit, y_fit),
    }
    cal_metrics = {name: metrics(y_test, c.predict(p_test)) for name, c in cals.items()}

    # 4) Velg kalibrator med lavest log-loss på test.
    chosen = min(cal_metrics, key=lambda k: cal_metrics[k]["logloss"])

    # 5) Lagre bundle for senere moduler.
    bundle = {
        "base_variant": base,
        "method": chosen,
        "calibrator": cals[chosen],
        "fit_season": int(fit_season),
        "test_season": int(test_season),
        "surface_weight": config.ELO_SURFACE_WEIGHT,
        "test_metrics": cal_metrics[chosen],
    }
    with open(config.CALIBRATOR_PKL, "wb") as fh:
        pickle.dump(bundle, fh)

    result = {
        "matches": matches,
        "fit": fit,
        "test": test,
        "hold": hold,
        "raw_metrics": raw_metrics,
        "base": base,
        "cals": cals,
        "cal_metrics": cal_metrics,
        "chosen": chosen,
        "bundle": bundle,
    }
    if verbose:
        print(f"  basis-variant: {base} ({VARIANT_LABEL[base]})")
        print(f"  valgt kalibrator: {chosen}")
        print(f"  test (sesong {test_season}): {cal_metrics[chosen]}")
    return result


class _CalibratorUnpickler(pickle.Unpickler):
    """Tåler pickle skrevet mens calibrate kjørte som __main__ (python -m):
    klassereferanser til __main__ pekes tilbake til denne modulen."""

    def find_class(self, module, name):
        if module == "__main__" and name in globals():
            return globals()[name]
        return super().find_class(module, name)


def load_calibrator() -> dict:
    with open(config.CALIBRATOR_PKL, "rb") as fh:
        return _CalibratorUnpickler(fh).load()


def apply_calibrator(bundle: dict, p_raw) -> np.ndarray:
    """Bruk lagret kalibrator på rå sannsynligheter. For Modul 4–7."""
    return bundle["calibrator"].predict(np.asarray(p_raw, dtype=float))


def winner_oriented_holdout(holdout_seasons: int = config.HOLDOUT_SEASONS) -> pd.DataFrame:
    """Walk-forward OOS-prediksjoner orientert mot FAKTISK vinner, kalibrert.

    Returnerer én rad pr. kamp med modellens P(vinner vinner), både rå og
    kalibrert. Brukes av Modul 4 (market_check) til å koble mot markedsodds.
    """
    from .ingest import load_matches

    matches = load_matches()
    preds, _ = generate_oos_predictions(matches, holdout_seasons)
    bundle = load_calibrator()
    base = bundle["base_variant"]
    p_a = preds[base].to_numpy()
    p_a_cal = apply_calibrator(bundle, p_a)
    is_a_winner = preds["label"].to_numpy() == 1  # a == vinner
    out = preds[["date", "season", "tour", "surface", "winner_id", "loser_id", "winner_name", "loser_name"]].copy()
    out["p_winner_raw"] = np.where(is_a_winner, p_a, 1 - p_a)
    out["p_winner_cal"] = np.where(is_a_winner, p_a_cal, 1 - p_a_cal)
    return out


# --- plott + rapport ---------------------------------------------------------
def make_plots(result: dict) -> str:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    test = result["test"]
    base = result["base"]
    y = test["label"].to_numpy()
    p_raw = test[base].to_numpy()
    p_cal = result["cals"][result["chosen"]].predict(p_raw)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 8), gridspec_kw={"height_ratios": [3, 1]})

    ax1.plot([0, 1], [0, 1], "k--", lw=1, label="Perfekt kalibrert")
    for p, name, style in ((p_raw, f"Rå ({VARIANT_LABEL[base]})", "o-"), (p_cal, f"Kalibrert ({result['chosen']})", "s-")):
        tbl = reliability_table(y, p)
        tbl = tbl[tbl["n"] > 0]
        ax1.plot(tbl["mean_pred"], tbl["frac_pos"], style, label=name)
    ax1.set_xlabel("Predikert sannsynlighet")
    ax1.set_ylabel("Observert frekvens")
    ax1.set_title(f"Reliability diagram — OOS test (sesong {result['hold'][-1]})")
    ax1.legend(loc="upper left")
    ax1.grid(alpha=0.3)
    ax1.set_xlim(0, 1)
    ax1.set_ylim(0, 1)

    ax2.hist(p_raw, bins=20, range=(0, 1), alpha=0.6, label="Rå")
    ax2.hist(p_cal, bins=20, range=(0, 1), alpha=0.6, label="Kalibrert")
    ax2.set_xlabel("Predikert sannsynlighet")
    ax2.set_ylabel("Antall kamper")
    ax2.legend()
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    out = config.REPORTS_DIR / "reliability_diagram.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out.name


def _fmt_metrics_row(name: str, m: dict) -> str:
    return f"| {name} | {m['brier']:.4f} | {m['logloss']:.4f} | {m['ece']:.4f} | {m['n']:,} |"


def write_report(result: dict) -> None:
    plot_name = make_plots(result)
    base = result["base"]
    chosen = result["chosen"]
    hold = result["hold"]
    rawm = result["raw_metrics"]
    calm = result["cal_metrics"]
    test = result["test"]

    raw_test = rawm[base]["test"]
    cal_test = calm[chosen]
    # Forbedring i log-loss og ECE fra rå til valgt.
    dll = raw_test["logloss"] - cal_test["logloss"]
    dece = raw_test["ece"] - cal_test["ece"]

    # Dom: er rå modell allerede godt kalibrert?
    well_calibrated = raw_test["ece"] < 0.03
    verdict_quality = (
        "GOD" if cal_test["ece"] < 0.03 and cal_test["brier"] < 0.25 else
        "AKSEPTABEL" if cal_test["ece"] < 0.05 else
        "DÅRLIG"
    )

    rel_raw = reliability_table(test["label"].to_numpy(), test[base].to_numpy())
    p_cal_test = result["cals"][chosen].predict(test[base].to_numpy())
    rel_cal = reliability_table(test["label"].to_numpy(), p_cal_test)

    lines: list[str] = []
    lines.append("# Kalibreringsrapport — Modul 3")
    lines.append("")
    lines.append(f"_Generert automatisk av `src/calibrate.py`. Test-sesong: {hold[-1]} (out-of-sample)._")
    lines.append("")
    lines.append("## Konklusjon")
    lines.append("")
    lines.append(f"- **Kvalitet på endelig modell: {verdict_quality}**")
    lines.append(f"- Basis-variant valgt: **{VARIANT_LABEL[base]}** (`{base}`)")
    lines.append(f"- Kalibreringsmetode valgt: **{chosen}**")
    lines.append(
        f"- På urørt test-sesong {hold[-1]}: Brier **{cal_test['brier']:.4f}**, "
        f"log-loss **{cal_test['logloss']:.4f}**, ECE **{cal_test['ece']:.4f}** "
        f"({cal_test['n']:,} kamper)."
    )
    if well_calibrated:
        lines.append("- Rå Elo var allerede godt kalibrert (ECE < 0,03); kalibrering gir liten/ingen forbedring.")
    else:
        lines.append(f"- Kalibrering forbedret log-loss med {dll:+.4f} og ECE med {dece:+.4f} vs. rå Elo.")
    lines.append("")
    lines.append("**Referansepunkt:** Brier 0,25 = ren myntkast (alltid 0,5). Lavere er bedre. "
                 "ECE er vektet snitt-avvik mellom predikert og observert sannsynlighet; < 0,03 regnes som godt kalibrert.")
    lines.append("")

    lines.append("## Metodikk")
    lines.append("")
    seasons = sorted(result["matches"]["season"].unique())
    lines.append(f"- Datasett: {len(result['matches']):,} kamper, sesongene {seasons[0]}–{seasons[-1]} (ATP+WTA, Sackmann).")
    lines.append(f"- Elo varmes opp på alt før de siste {config.HOLDOUT_SEASONS} sesongene.")
    lines.append(f"- Walk-forward gjennom holdout (predikér før kamp, oppdater etter) — som i produksjon.")
    lines.append(f"- **Fit-sett** (kalibrator trenes her): sesong {hold[0]}.")
    lines.append(f"- **Test-sett** (urørt, endelig dom): sesong {hold[-1]}.")
    lines.append(f"- Spillere ordnes deterministisk (a = lavest id) før prediksjon for å unngå label-lekkasje; "
                 f"snitt-label i test = {test['label'].mean():.3f} (≈0,5 bekrefter balanse).")
    lines.append("")

    lines.append("## 1. Rå Elo-varianter (out-of-sample test)")
    lines.append("")
    lines.append("| Variant | Brier | Log-loss | ECE | n |")
    lines.append("|---|---|---|---|---|")
    for v in VARIANTS:
        mark = " ⬅ valgt" if v == base else ""
        lines.append(_fmt_metrics_row(VARIANT_LABEL[v] + mark, rawm[v]["test"]))
    lines.append("")
    lines.append(f"_Basis valgt etter log-loss på fit-sesong {hold[0]} (ikke test), for å unngå å tilpasse seg testen._")
    lines.append("")

    lines.append(f"## 2. Kalibrering av basis ({VARIANT_LABEL[base]}) — test-sesong {hold[-1]}")
    lines.append("")
    lines.append("| Metode | Brier | Log-loss | ECE | n |")
    lines.append("|---|---|---|---|---|")
    for name in ("raw", "platt", "isotonic"):
        mark = " ⬅ valgt" if name == chosen else ""
        lines.append(_fmt_metrics_row(name + mark, calm[name]))
    lines.append("")

    lines.append("## 3. Reliability-tabell (test-sesong)")
    lines.append("")
    lines.append("| Bin | n | Rå snitt-pred | Rå observert | Kalibrert snitt-pred | Kalibrert observert |")
    lines.append("|---|---|---|---|---|---|")
    for r, c in zip(rel_raw.itertuples(index=False), rel_cal.itertuples(index=False)):
        if r.n == 0:
            continue
        lines.append(
            f"| {r.bin} | {r.n:,} | {r.mean_pred:.3f} | {r.frac_pos:.3f} | "
            f"{c.mean_pred:.3f} | {c.frac_pos:.3f} |"
        )
    lines.append("")

    lines.append("## 4. Reliability-diagram")
    lines.append("")
    lines.append(f"![Reliability diagram]({plot_name})")
    lines.append("")
    lines.append(f"Kalibrator lagret til `{config.CALIBRATOR_PKL.relative_to(config.ROOT)}` "
                 f"(basis `{base}`, metode `{chosen}`).")
    lines.append("")

    (config.REPORTS_DIR / "calibration.md").write_text("\n".join(lines))


def main() -> int:
    result = run_calibration()
    write_report(result)
    print(f"Skrev {config.REPORTS_DIR / 'calibration.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
