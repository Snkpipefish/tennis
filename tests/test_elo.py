"""Tester for Modul 2 (elo)."""
from __future__ import annotations

import pandas as pd
import pytest

from src import config
from src.elo import DIMENSIONS, EloModel, expected_score, k_factor


def test_expected_score_grunnleggende() -> None:
    assert expected_score(1500, 1500) == pytest.approx(0.5)
    assert expected_score(1700, 1500) > 0.5
    assert expected_score(1300, 1500) < 0.5
    # Symmetri: P(A) + P(B) = 1.
    assert expected_score(1600, 1400) + expected_score(1400, 1600) == pytest.approx(1.0)
    # 200 poeng forsprang ~ 0.76 i Elo-skala.
    assert expected_score(1700, 1500) == pytest.approx(0.7597, abs=1e-3)


def test_k_factor_avtar() -> None:
    assert k_factor(0) > k_factor(10) > k_factor(100)
    assert k_factor(0) == pytest.approx(config.ELO_K_FACTOR / config.ELO_K_SHIFT ** config.ELO_K_DECAY)


def test_update_match_likt_utgangspunkt() -> None:
    m = EloModel()
    m.update_match(winner=1, loser=2, surface="Hard")
    rw = m.get("all", 1)
    rl = m.get("all", 2)
    assert rw > config.ELO_INIT          # vinner stiger
    assert rl < config.ELO_INIT          # taper synker
    # Likt utgangspunkt og lik kampteller => symmetrisk endring.
    assert (rw - config.ELO_INIT) == pytest.approx(config.ELO_INIT - rl)
    # Hard-underlaget oppdateres. Clay er ikke spilt ennå, så Clay-rating
    # SEEDES fra samlet rating (ikke flatt 1500).
    assert m.get("Hard", 1) > config.ELO_INIT
    assert m.get("Clay", 1) == pytest.approx(m.get("all", 1))
    assert m.count["all"][1] == 1 and m.count["Hard"][1] == 1
    assert m.count["Clay"].get(1, 0) == 0


def test_upset_gir_storre_utslag() -> None:
    m = EloModel()
    m.rating["all"][1] = 1800  # favoritt
    m.rating["all"][2] = 1400  # outsider
    # Outsider (2) slår favoritt (1): stort utslag.
    m.update_match(winner=2, loser=1, surface="Hard")
    assert m.get("all", 2) - 1400 > 50


def test_probabilities_innenfor_0_1() -> None:
    m = EloModel()
    m.rating["all"][1] = 1700
    m.rating["Clay"][1] = 1900
    probs = m.probabilities(1, 2, "Clay")
    for key in ("p_overall", "p_surface", "p_blend"):
        assert 0.0 < probs[key] < 1.0
    # Blend ligger mellom de to rene.
    lo, hi = sorted([probs["p_overall"], probs["p_surface"]])
    assert lo <= probs["p_blend"] <= hi


def test_save_load_roundtrip(tmp_path) -> None:
    m = EloModel()
    m.update_match(1, 2, "Hard")
    m.update_match(3, 1, "Clay")
    sp = tmp_path / "state.parquet"
    mp = tmp_path / "meta.json"
    m.save(sp, mp)
    loaded = EloModel.load(sp, mp)
    for dim in DIMENSIONS:
        for pid in (1, 2, 3):
            assert loaded.get(dim, pid) == pytest.approx(m.get(dim, pid))
    assert loaded.n_matches == m.n_matches


def test_process_collect_balansert_og_ordnet() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-01-02"]),
            "season": [2020, 2020],
            "tour": ["atp", "atp"],
            "surface": ["Hard", "Clay"],
            "winner_id": [10, 5],
            "loser_id": [5, 10],
        }
    )
    m = EloModel()
    out = m.process(df, collect=True)
    assert list(out.columns) >= ["a_id", "b_id", "label", "p_overall", "p_surface", "p_blend"]
    # Deterministisk ordning: a alltid lavest id.
    assert (out["a_id"] < out["b_id"]).all()
    # Første kamp: 10 vant mot 5 => a=5, label=0. Andre: 5 vant mot 10 => a=5, label=1.
    assert out.loc[0, "label"] == 0
    assert out.loc[1, "label"] == 1
