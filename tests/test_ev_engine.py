"""Tester for Modul 6 (ev_engine)."""
from __future__ import annotations

import pytest

from src.calibrate import IdentityCalibrator
from src.elo import EloModel
from src.ev_engine import EV_THRESHOLD, MAX_STAKE_FRACTION, evaluate_slip, quarter_kelly_stake
from src.nt_odds import make_entry


def test_quarter_kelly_kjent_verdi() -> None:
    # p=0.6, odds=2.0 -> full Kelly 0.2, 1/4 = 0.05, av 1000 kr = 50.
    assert quarter_kelly_stake(0.6, 2.0, 1000) == pytest.approx(50.0)


def test_quarter_kelly_takes_maks_andel() -> None:
    # Ekstrem kant (p=0.9, odds=2.0 -> full Kelly 0.8, 1/4 = 0.2) skal
    # kappes til MAX_STAKE_FRACTION av bankroll.
    assert quarter_kelly_stake(0.9, 2.0, 1000) == pytest.approx(1000 * MAX_STAKE_FRACTION)


def test_quarter_kelly_ingen_kant_gir_null() -> None:
    assert quarter_kelly_stake(0.4, 2.0, 1000) == 0.0
    assert quarter_kelly_stake(0.5, 1.5, 1000) == 0.0  # negativ EV


def _fake_model() -> EloModel:
    m = EloModel(rank_seed=None)
    m.rating["all"][1] = 1700.0
    m.rating["all"][2] = 1500.0
    return m


def _identity_bundle() -> dict:
    return {"base_variant": "p_overall", "calibrator": IdentityCalibrator()}


def test_evaluate_slip_finner_ev() -> None:
    # P(1 slår 2) = ~0.76. Odds 1.5 på A -> EV = 0.76*1.5-1 = 0.14 > terskel.
    entries = [make_entry(
        tour="atp", surface="Hard",
        player_a_id=1, player_a_name="Sterk", nt_odds_a=1.5,
        player_b_id=2, player_b_name="Svak", nt_odds_b=2.6,
    )]
    df = evaluate_slip(entries, bankroll=1000, model=_fake_model(), bundle=_identity_bundle())
    a = df[df["side"] == "A"].iloc[0]
    assert a["model_p"] == pytest.approx(0.7597, abs=1e-3)
    assert a["ev"] == pytest.approx(0.7597 * 1.5 - 1, abs=1e-3)
    assert bool(a["bet"]) is True
    assert a["stake_kr"] > 0
    # Svak side skal ikke anbefales.
    b = df[df["side"] == "B"].iloc[0]
    assert bool(b["bet"]) is False
    assert b["stake_kr"] == 0.0


def test_evaluate_slip_ingen_kant() -> None:
    # Fair odds som speiler modellen -> ingen EV over terskel.
    entries = [make_entry(
        tour="atp", surface="Hard",
        player_a_id=1, player_a_name="Sterk", nt_odds_a=1.0 / 0.76,
        player_b_id=2, player_b_name="Svak", nt_odds_b=1.0 / 0.24,
    )]
    df = evaluate_slip(entries, bankroll=1000, model=_fake_model(), bundle=_identity_bundle())
    assert not df["bet"].any()


def test_ukjent_spiller_gir_aldri_veddemaal() -> None:
    # Uten spiller-id blir P ≈ 0.5 (default-rating); høye odds ville gitt en
    # FALSK kant (0.5*3.0-1 = +50 %). Slike kamper skal aldri anbefales.
    entries = [make_entry(
        tour="atp", surface="Hard",
        player_a_id=None, player_a_name="Ukjent A", nt_odds_a=3.0,
        player_b_id=2, player_b_name="Svak", nt_odds_b=1.4,
    )]
    df = evaluate_slip(entries, bankroll=1000, model=_fake_model(), bundle=_identity_bundle())
    assert (df["ev"] > EV_THRESHOLD).any()      # kanten finnes på papiret ...
    assert not df["bet"].any()                  # ... men anbefales ikke
    assert (df["stake_kr"] == 0.0).all()
    assert not df["known"].any()


def test_threshold_konstant() -> None:
    assert EV_THRESHOLD == 0.05
