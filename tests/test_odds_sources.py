"""Tester for odds_sources (Pinnacle-parsing og amerikansk-odds-konvertering)."""
from __future__ import annotations

import pytest

from src.odds_sources import _tour_from_league, american_to_decimal, parse_pinnacle


def test_american_to_decimal() -> None:
    assert american_to_decimal(138) == pytest.approx(2.38)
    assert american_to_decimal(-165) == pytest.approx(1.606)
    assert american_to_decimal(100) == pytest.approx(2.0)
    assert american_to_decimal(-100) == pytest.approx(2.0)


def test_tour_from_league_filtrerer_lavere_nivaa() -> None:
    assert _tour_from_league("ATP Wimbledon - QF") == "atp"
    assert _tour_from_league("WTA Wimbledon") == "wta"
    assert _tour_from_league("ATP Challenger Liege - R1") is None
    assert _tour_from_league("ITF Men Bastia-Lucciana - R1") is None
    assert _tour_from_league("ATP Wimbledon Doubles") is None
    assert _tour_from_league("UTR Pro Waco") is None


def _matchup(mid: int, league: str, home: str, away: str, **kw) -> dict:
    return {
        "id": mid, "type": "matchup", "parent": None, "isLive": kw.get("is_live", False),
        "league": {"name": league},
        "startTime": kw.get("start", "2030-01-01T12:00:00Z"),
        "participants": [
            {"alignment": "home", "name": home},
            {"alignment": "away", "name": away},
        ],
    }


def _market(mid: int, home_price: int, away_price: int, **kw) -> dict:
    return {
        "matchupId": mid, "type": "moneyline", "period": kw.get("period", 0),
        "status": kw.get("status", "open"),
        "prices": [
            {"designation": "home", "price": home_price},
            {"designation": "away", "price": away_price},
        ],
    }


def test_parse_pinnacle() -> None:
    matchups = [
        _matchup(1, "ATP Wimbledon - QF", "Jannik Sinner", "Novak Djokovic"),
        _matchup(2, "ATP Challenger Liege - R1", "A", "B"),          # lavere nivå -> bort
        _matchup(3, "WTA Wimbledon", "X", "Y", is_live=True),        # live -> bort
        _matchup(4, "WTA Wimbledon", "P", "Q", start="2020-01-01T12:00:00Z"),  # startet -> bort
        _matchup(5, "ATP Wimbledon - QF", "C", "D"),                 # mangler marked -> bort
    ]
    markets = [
        _market(1, -300, 250),
        _market(2, 100, -120),
        _market(3, 100, -120),
        _market(4, 100, -120),
    ]
    evs = parse_pinnacle(matchups, markets)
    assert len(evs) == 1
    ev = evs[0]
    assert ev["home"] == "Jannik Sinner" and ev["away"] == "Novak Djokovic"
    assert ev["tour"] == "atp"
    assert ev["odds_home"] == pytest.approx(1.333, abs=1e-3)
    assert ev["odds_away"] == pytest.approx(3.5)


def test_parse_pinnacle_hopper_over_stengt_marked() -> None:
    matchups = [_matchup(1, "ATP Wimbledon", "A", "B")]
    markets = [_market(1, 100, -120, status="suspended")]
    assert parse_pinnacle(matchups, markets) == []
