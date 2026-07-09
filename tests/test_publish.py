"""Tester for skypubliseringens odds-snapshot-logg (CLV-grunnlag)."""
import json

import pandas as pd

from src import publish


def _df():
    return pd.DataFrame([{
        "book": "pinnacle", "tour": "atp", "surface": "Grass",
        "tournament": "Wimbledon", "start": "2026-07-10T12:00:00Z",
        "match": "Jannik Sinner – Novak Djokovic", "side": "A",
        "bet_on": "Jannik Sinner", "opponent": "Novak Djokovic",
        "model_p": 0.71, "elo_p": 0.68, "market_p": 0.72,
        "nt_odds": 1.45, "implied_p": 0.69, "ev": 0.03,
        "known": True, "stake_kr": 0.0, "bet": False,
    }])


def test_log_snapshot_appends_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "HISTORY_DIR", tmp_path)
    publish.log_snapshot(_df())
    publish.log_snapshot(_df())
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1  # én fil per måned
    lines = [json.loads(l) for l in files[0].read_text().splitlines()]
    assert len(lines) == 2
    r = lines[0]
    assert r["match"] == "Jannik Sinner – Novak Djokovic"
    assert r["nt_odds"] == 1.45
    assert "ts" in r and r["ts"][:2] == "20"
    # ingen bankroll-avhengige felter i loggen
    assert "stake_kr" not in r


def test_log_snapshot_empty_df_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "HISTORY_DIR", tmp_path)
    publish.log_snapshot(pd.DataFrame())
    assert list(tmp_path.glob("*")) == []
