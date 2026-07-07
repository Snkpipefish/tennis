"""Tester for odds_sources (Pinnacle-parsing og amerikansk-odds-konvertering)."""
from __future__ import annotations

import pytest

from src.odds_sources import _classify_league, american_to_decimal, parse_pinnacle


def test_american_to_decimal() -> None:
    assert american_to_decimal(138) == pytest.approx(2.38)
    assert american_to_decimal(-165) == pytest.approx(1.606)
    assert american_to_decimal(100) == pytest.approx(2.0)
    assert american_to_decimal(-100) == pytest.approx(2.0)


def test_classify_league() -> None:
    assert _classify_league("ATP Wimbledon - QF") == ("atp", "single")
    assert _classify_league("WTA Wimbledon") == ("wta", "single")
    assert _classify_league("ATP Wimbledon Doubles") == ("atp", "double")
    assert _classify_league("WTA Wimbledon Doubles") == ("wta", "double")
    # Lavere nivåer VISES nå (vaktene hindrer anbefaling), men UTR/exhibition ikke.
    assert _classify_league("ATP Challenger Liege - R1") == ("atp", "single")
    assert _classify_league("ITF Women Bucharest - R1") == ("wta", "single")
    assert _classify_league("UTR Pro Waco") is None


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
        _matchup(2, "UTR Pro Waco", "A", "B"),                       # exhibition-nivå -> bort
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
    assert ev["kind"] == "single"


def test_parse_pinnacle_double_merkes() -> None:
    matchups = [_matchup(1, "ATP Wimbledon Doubles", "A / B", "C / D")]
    markets = [_market(1, -110, -110)]
    evs = parse_pinnacle(matchups, markets)
    assert len(evs) == 1 and evs[0]["kind"] == "double"


def test_parse_pinnacle_hopper_over_stengt_marked() -> None:
    matchups = [_matchup(1, "ATP Wimbledon", "A", "B")]
    markets = [_market(1, 100, -120, status="suspended")]
    assert parse_pinnacle(matchups, markets) == []


def test_fetch_all_beholder_gamle_odds_naar_kilde_feiler(tmp_path, monkeypatch) -> None:
    # NT-odds fra i morges ligger i slippen; ny henting der NT feiler skal
    # BEHOLDE dem og bare fornye Pinnacle-delen.
    import pandas as pd

    from src import nt_odds, odds_sources
    from src.nt_odds import make_entry, save_slip

    monkeypatch.setattr(nt_odds.config, "ODDS_DIR", tmp_path)
    old_nt = make_entry(tour="atp", surface="Grass", book="nt",
                        player_a_id=1, player_a_name="A", nt_odds_a=1.5,
                        player_b_id=2, player_b_name="B", nt_odds_b=2.6)
    save_slip([old_nt], replace=True)

    pinn = make_entry(tour="atp", surface="Grass", book="pinnacle",
                      player_a_id=1, player_a_name="A", nt_odds_a=1.4,
                      player_b_id=2, player_b_name="B", nt_odds_b=3.0)
    monkeypatch.setattr(odds_sources, "fetch_pinnacle", lambda *a, **k: [pinn])

    def boom(*a, **k):
        raise RuntimeError("NT nede")

    monkeypatch.setattr(nt_odds, "fetch_nt_odds", boom)
    monkeypatch.setattr(odds_sources, "PlayerIndex",
                        type("PI", (), {"from_matches": staticmethod(lambda *a, **k: None)}))
    monkeypatch.setattr(odds_sources, "load_slip", nt_odds.load_slip)

    entries, warnings = odds_sources.fetch_all_odds(
        matches=pd.DataFrame({"tourney": [], "surface": []}), include_nt=True)
    books = sorted(e["book"] for e in entries)
    assert books == ["nt", "pinnacle"]          # gammel NT beholdt + ny Pinnacle
    assert any("Norsk Tipping feilet" in w for w in warnings)
    assert len(nt_odds.load_slip()) == 2        # lagret flettet slip
