"""Tester for Modul 3 (calibrate)."""
from __future__ import annotations

import numpy as np
import pytest

from src.calibrate import (
    IdentityCalibrator,
    IsotonicCalibrator,
    PlattCalibrator,
    expected_calibration_error,
    generate_oos_predictions,
    metrics,
    reliability_table,
)
from src.ingest import load_matches


def test_metrics_perfekt_vs_mynt() -> None:
    rng = np.random.default_rng(0)
    # Perfekt sikre og korrekte prediksjoner -> Brier ~0, log-loss ~0.
    y = rng.integers(0, 2, 2000)
    p_perfect = np.where(y == 1, 1 - 1e-9, 1e-9)
    m_perfect = metrics(y, p_perfect)
    assert m_perfect["brier"] < 1e-3
    # Myntkast (0.5) -> Brier = 0.25.
    m_coin = metrics(y, np.full_like(y, 0.5, dtype=float))
    assert m_coin["brier"] == pytest.approx(0.25, abs=1e-6)


def test_ece_perfekt_kalibrert_er_lav() -> None:
    # Konstruer data der observert frekvens = predikert pr. bin.
    rng = np.random.default_rng(1)
    p = rng.uniform(0, 1, 20000)
    y = (rng.uniform(0, 1, 20000) < p).astype(int)
    assert expected_calibration_error(y, p) < 0.02


def test_reliability_table_struktur() -> None:
    y = np.array([0, 1, 0, 1, 1])
    p = np.array([0.1, 0.9, 0.2, 0.8, 0.95])
    tbl = reliability_table(y, p, bins=10)
    assert len(tbl) == 10
    assert int(tbl["n"].sum()) == 5


def test_platt_forbedrer_skjev_modell() -> None:
    # Lag overkonfidente prediksjoner; Platt skal redusere log-loss.
    rng = np.random.default_rng(2)
    true_p = rng.uniform(0.1, 0.9, 8000)
    y = (rng.uniform(0, 1, 8000) < true_p).astype(int)
    # Overkonfident: skyv mot 0/1.
    skewed = np.clip((true_p - 0.5) * 1.8 + 0.5, 1e-3, 1 - 1e-3)
    raw_ll = metrics(y, skewed)["logloss"]
    cal = PlattCalibrator().fit(skewed, y)
    cal_ll = metrics(y, cal.predict(skewed))["logloss"]
    assert cal_ll < raw_ll


def test_isotonic_og_identity_returnerer_gyldige_p() -> None:
    rng = np.random.default_rng(3)
    p = rng.uniform(0, 1, 1000)
    y = (rng.uniform(0, 1, 1000) < p).astype(int)
    for cal in (IsotonicCalibrator().fit(p, y), IdentityCalibrator().fit(p, y)):
        out = cal.predict(p)
        assert out.min() >= 0.0 and out.max() <= 1.0
        assert len(out) == len(p)


def test_walk_forward_splitt_og_balanse() -> None:
    matches = load_matches()
    preds, hold = generate_oos_predictions(matches, holdout_seasons=2)
    assert set(preds["season"].unique()) == set(hold)
    # Deterministisk ordning og balanserte labels (~0.5).
    assert (preds["a_id"] < preds["b_id"]).all()
    assert 0.45 < preds["label"].mean() < 0.55
    for col in ("p_overall", "p_surface", "p_blend"):
        assert preds[col].between(0, 1).all()
