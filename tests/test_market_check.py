"""Tester for Modul 4 (market_check). Fokus på navnematching og de-vig (rene
funksjoner). Nettverk unngås."""
from __future__ import annotations

import pytest

from src.market_check import (
    devig_power,
    devig_power_array,
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
        ("Karolina Pliskova", "Pliskova Ka."),
    ],
)
def test_navnenokler_matcher(sackmann: str, td: str) -> None:
    assert sackmann_surname_key(sackmann) == tennis_data_surname_key(td)
    assert sackmann_surname_key(sackmann) != ""


@pytest.mark.parametrize(
    "td, key",
    [
        # Initialer med flere bokstaver/punktum strippes (feilet før 2026-09-06)
        ("Tirante T.A.", "tirante"),
        ("Cerundolo J.M.", "cerundolo"),
        ("Struff J.L.", "struff"),
        ("Wang Xiy.", "wang"),
        ("Van De Zandschulp B.", "vandezandschulp"),
    ],
)
def test_tennis_data_nokkel_stripper_initialer(td: str, key: str) -> None:
    assert tennis_data_surname_key(td) == key


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


def test_devig_power_symmetrisk_og_sum() -> None:
    assert devig_power(1.9, 1.9) == pytest.approx(0.5)
    assert devig_power(1.25, 4.0) + devig_power(4.0, 1.25) == pytest.approx(1.0, abs=1e-9)


def test_devig_power_legger_margin_paa_underdog() -> None:
    # Potens-de-vig gir favoritten HØYERE P enn proporsjonal, og ligger
    # mellom proporsjonal P og rå 1/odds.
    for a, b in ((1.25, 4.0), (1.08, 9.72), (1.5, 2.6)):
        prop, pw = devig_two_way(a, b), devig_power(a, b)
        assert prop < pw < 1.0 / a
    assert devig_power(1.25, 4.0) == pytest.approx(0.7824, abs=1e-4)


def test_devig_power_uten_margin_er_raa_odds() -> None:
    assert devig_power(4.0, 4.0 / 3.0) == pytest.approx(0.25, abs=1e-6)


def test_devig_power_array_matcher_skalar() -> None:
    import numpy as np

    arr = devig_power_array([1.25, 1.08, 1.5, float("nan")], [4.0, 9.72, 2.6, 3.0])
    assert arr[0] == pytest.approx(devig_power(1.25, 4.0), abs=1e-6)
    assert arr[1] == pytest.approx(devig_power(1.08, 9.72), abs=1e-6)
    assert arr[2] == pytest.approx(devig_power(1.5, 2.6), abs=1e-6)
    assert np.isnan(arr[3])
