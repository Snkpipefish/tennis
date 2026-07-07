"""Tester for Modul 7 (track)."""
from __future__ import annotations

from datetime import date

import pytest

from src import track


@pytest.fixture(autouse=True)
def _tmp_log(tmp_path, monkeypatch):
    monkeypatch.setattr(track.config, "TRACK_LOG", tmp_path / "track.json")
    yield


def _pending(bet_id, stake, odds, model_p, ev, status="pending"):
    return {
        "bet_id": bet_id, "placed_date": "2026-06-19", "tour": "atp", "surface": "Hard",
        "match": f"P{bet_id} – Q{bet_id}", "bet_on": f"P{bet_id}", "model_p": model_p,
        "nt_odds": odds, "implied_p": 1 / odds, "ev": ev, "stake_kr": stake,
        "status": status, "profit_kr": 0.0,
    }


def test_settle_gevinst_og_tap() -> None:
    track.save_log([_pending(1, 100, 2.5, 0.5, 0.25), _pending(2, 100, 2.0, 0.6, 0.2)])
    r1 = track.settle(1, won=True)
    assert r1["status"] == "won"
    assert r1["profit_kr"] == pytest.approx(150.0)  # 100*(2.5-1)
    r2 = track.settle(2, won=False)
    assert r2["status"] == "lost"
    assert r2["profit_kr"] == pytest.approx(-100.0)


def test_settle_ukjent_id() -> None:
    track.save_log([_pending(1, 100, 2.0, 0.6, 0.2)])
    with pytest.raises(KeyError):
        track.settle(99, won=True)


def test_compute_stats_roi() -> None:
    recs = [_pending(1, 100, 2.5, 0.5, 0.25), _pending(2, 100, 2.0, 0.6, 0.2)]
    track.save_log(recs)
    track.settle(1, won=True)   # +150
    track.settle(2, won=False)  # -100
    s = track.compute_stats(track.load_log())
    assert s["n_settled"] == 2 and s["n_won"] == 1
    assert s["total_stake"] == pytest.approx(200.0)
    assert s["total_profit"] == pytest.approx(50.0)
    assert s["actual_roi"] == pytest.approx(0.25)
    # forventet profit = 100*0.25 + 100*0.20 = 45
    assert s["expected_profit"] == pytest.approx(45.0)


def test_settle_match_hjelper() -> None:
    track.save_log([_pending(1, 100, 2.0, 0.6, 0.2)])
    r = track.settle_match("P1", "P1", won=True)
    assert r["status"] == "won"


def test_log_idempotent(tmp_path, monkeypatch) -> None:
    # Bruk en ekte sterk matchup for å garantere et anbefalt veddemål.
    from src import nt_odds
    from src.nt_odds import PlayerIndex, make_entry, save_slip

    monkeypatch.setattr(nt_odds.config, "ODDS_DIR", tmp_path)
    day = date(2026, 6, 19)
    dj = PlayerIndex.from_matches().resolve_one("Djokovic")
    # Motstander = ukjent id (rating ~1500) til sjenerøs odds -> klar EV på Djokovic.
    save_slip([make_entry(
        tour="atp", surface="Hard",
        player_a_id=dj[0], player_a_name=dj[1], nt_odds_a=2.5,
        player_b_id=999999, player_b_name="Ukjent Spiller", nt_odds_b=1.5,
    )], day)

    track.log_bets(day, bankroll=1000)
    n1 = len(track.load_log())
    track.log_bets(day, bankroll=1000)  # samme dag igjen
    n2 = len(track.load_log())
    assert n1 >= 1 and n1 == n2  # ingen dobbeltloggføring
