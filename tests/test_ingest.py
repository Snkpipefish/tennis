"""Tester for Modul 1 (ingest).

Bruker den allerede bygde parquet-tabellen (lastes ikke på nytt). Kjør
`python -m src.ingest` først hvis data/raw/matches.parquet mangler.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src import config
from src.ingest import normalize_surface


@pytest.fixture(scope="module")
def matches() -> pd.DataFrame:
    if not config.MATCHES_PARQUET.exists():
        pytest.skip("matches.parquet mangler — kjør `python -m src.ingest`")
    return pd.read_parquet(config.MATCHES_PARQUET)


def test_radantall_positivt(matches: pd.DataFrame) -> None:
    assert len(matches) > 0


def test_winner_er_en_av_to_spillere(matches: pd.DataFrame) -> None:
    # Vinner og taper må begge være satt, og være ulike spillere.
    assert matches["winner_id"].notna().all()
    assert matches["loser_id"].notna().all()
    assert (matches["winner_id"] != matches["loser_id"]).all()


def test_kun_gyldige_underlag(matches: pd.DataFrame) -> None:
    assert set(matches["surface"].unique()) <= set(config.SURFACES)


def test_dato_parset_og_kronologisk(matches: pd.DataFrame) -> None:
    assert matches["date"].notna().all()
    # Tabellen skal være sortert stigende på dato (kritisk for Elo).
    assert matches["date"].is_monotonic_increasing


def test_begge_tourer_tilstede(matches: pd.DataFrame) -> None:
    assert set(matches["tour"].unique()) == set(config.TOURS)


def test_normalize_surface() -> None:
    assert normalize_surface("Clay") == "Clay"
    assert normalize_surface("grass") == "Grass"
    assert normalize_surface("Hard") == "Hard"
    assert normalize_surface("Carpet") == "Hard"
    assert normalize_surface(None) == "Hard"
    assert normalize_surface("") == "Hard"
