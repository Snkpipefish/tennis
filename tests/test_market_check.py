"""Tester for Modul 4 (market_check). Fokus på navnematching og de-vig (rene
funksjoner). Nettverk unngås."""
from __future__ import annotations

import pytest

from src.market_check import (
    devig_two_way,
    sackmann_surname_key,
    tennis_data_surname_key,
)


@pytest.mark.parametrize(
    "sackmann, td",
    [
        ("Marcos Giron", "Giron M."),
        ("Felix Auger Aliassime", "Auger-Aliassime F."),
        ("Christopher O'Connell", "O Connell C."),
        ("Alejandro Davidovich Fokina", "Davidovich Fokina A."),
        ("Iga Swiatek", "Swiatek I."),
        ("Stefanos Tsitsipas", "Tsitsipas S."),
    ],
)
def test_navnenokler_matcher(sackmann: str, td: str) -> None:
    assert sackmann_surname_key(sackmann) == tennis_data_surname_key(td)
    assert sackmann_surname_key(sackmann) != ""


def test_devig_balansert() -> None:
    # Symmetrisk marked -> 0.5.
    assert devig_two_way(2.0, 2.0) == pytest.approx(0.5)


def test_devig_favoritt() -> None:
    # PSW=1.5, PSL=3.0 -> implisitt 0.667/0.333, normalisert -> 0.667.
    assert devig_two_way(1.5, 3.0) == pytest.approx(2 / 3, abs=1e-6)
    # Summen av de to de-viggede skal være 1.
    assert devig_two_way(1.5, 3.0) + devig_two_way(3.0, 1.5) == pytest.approx(1.0)


def test_devig_fjerner_margin() -> None:
    # Marked med margin: begge 1.90 (overround ~5.3%). De-vigget skal bli 0.5.
    assert devig_two_way(1.90, 1.90) == pytest.approx(0.5)
