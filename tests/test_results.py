"""Tester for results.py (ESPN-resultatgap)."""
from __future__ import annotations

import pandas as pd

from src import results


def _payload() -> dict:
    def comp(cid, date, n1, w1, n2, w2, status="STATUS_FINAL"):
        return {
            "id": cid, "date": date,
            "status": {"type": {"name": status}},
            "competitors": [
                {"athlete": {"displayName": n1}, "winner": w1},
                {"athlete": {"displayName": n2}, "winner": w2},
            ],
        }

    return {"events": [{
        "name": "Wimbledon",
        "groupings": [
            {"grouping": {"displayName": "Men's Singles"},
             "competitions": [
                 comp("c1", "2026-07-05T12:00Z", "Jannik Sinner", True, "Jan Struff", False),
                 comp("c2", "2026-07-05T13:00Z", "X", False, "Y", False),          # ingen vinner -> bort
                 comp("c3", "2026-07-05T14:00Z", "A", True, "B", False, "STATUS_IN_PROGRESS"),  # pågår -> bort
             ]},
            {"grouping": {"displayName": "Women's Singles"},
             "competitions": [comp("c4", "2026-07-06T12:00Z", "Iga Swiatek", True, "Coco Gauff", False)]},
            {"grouping": {"displayName": "Men's Doubles"},
             "competitions": [comp("c5", "2026-07-06T12:00Z", "P / Q", True, "R / S", False)]},
            {"grouping": {"displayName": "Men's Singles Qualifying"},
             "competitions": [comp("c6", "2026-07-01T12:00Z", "Kval A", True, "Kval B", False)]},
        ],
    }]}


def test_parse_scoreboard() -> None:
    rows = results.parse_scoreboard(_payload())
    assert len(rows) == 2  # kun ferdige hoveddraw-singler
    r1 = next(r for r in rows if r["tour"] == "atp")
    assert r1["winner_name"] == "Jannik Sinner" and r1["loser_name"] == "Jan Struff"
    assert r1["tournament"] == "Wimbledon"
    r2 = next(r for r in rows if r["tour"] == "wta")
    assert r2["winner_name"] == "Iga Swiatek"


def test_build_results_extension_kun_etter_cutoff(monkeypatch) -> None:
    # Base stopper 2026-07-05 for atp -> Sinner-kampen (05.07) er dekket,
    # Swiatek-kampen (06.07, wta-cutoff 01.07) skal med.
    base = pd.DataFrame({
        "date": [pd.Timestamp("2026-07-05"), pd.Timestamp("2026-07-01")] * 2,
        "tour": ["atp", "wta", "atp", "wta"],
        "season": [2026] * 4,
        "tourney": ["Wimbledon"] * 4,
        "surface": ["Grass"] * 4,
        "winner_id": [1, 3, 1, 3], "loser_id": [2, 4, 2, 4],
        "winner_name": ["Jannik Sinner", "Iga Swiatek", "Jannik Sinner", "Iga Swiatek"],
        "loser_name": ["Jan Struff", "Coco Gauff", "Jan Struff", "Coco Gauff"],
    })
    monkeypatch.setattr(results, "fetch_day", lambda tour, day, **k: _payload())
    ext = results.build_results_extension(base, verbose=False)
    assert len(ext) == 1
    r = ext.iloc[0]
    assert r["tour"] == "wta" and r["winner_id"] == 3 and r["loser_id"] == 4
    assert r["winner_name"] == "Iga Swiatek"       # løst til kjent id/navn
    assert r["surface"] == "Grass"                 # fra turneringsoppslaget
