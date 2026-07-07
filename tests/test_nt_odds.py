"""Tester for Modul 5 (nt_odds): spilleroppslag, lagring, underlag-inferens og
NT-WebSocket-parsing (mot ekte fangede rammer som fixture)."""
from __future__ import annotations

import json

from datetime import date

import pytest

from src import nt_odds
from src.nt_odds import (
    PlayerIndex,
    infer_surface,
    load_slip,
    make_entry,
    nt_name_to_query,
    parse_ws_frames,
    save_slip,
)


@pytest.fixture(scope="module")
def index() -> PlayerIndex:
    from src.ingest import load_matches

    return PlayerIndex.from_matches(load_matches())


def test_resolve_kjent_spiller(index: PlayerIndex) -> None:
    res = index.resolve_one("Djokovic")
    assert res is not None and "Djokovic" in res[1]


def test_resolve_label_varianter(index: PlayerIndex) -> None:
    # Kambi-stil 'Etternavn X.' og 'Fornavn Etternavn' skal begge løse.
    for label in ("Djokovic N.", "Novak Djokovic", "Sinner J."):
        pid, name = index.resolve_label(label)
        assert pid is not None


def test_search_ukjent_gir_tomt(index: PlayerIndex) -> None:
    assert len(index.search("zzzznotaplayer")) == 0


def test_make_entry_struktur() -> None:
    e = make_entry(tour="atp", surface="Hard", player_a_id=1, player_a_name="A",
                   nt_odds_a=1.8, player_b_id=2, player_b_name="B", nt_odds_b=2.1)
    assert e["tour"] == "atp" and e["nt_odds_a"] == 1.8 and "timestamp" in e


def test_save_load_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(nt_odds.config, "ODDS_DIR", tmp_path)
    day = date(2026, 6, 18)
    e = make_entry(tour="atp", surface="Clay", player_a_id=10, player_a_name="X",
                   nt_odds_a=1.5, player_b_id=20, player_b_name="Y", nt_odds_b=2.7)
    save_slip([e], day)
    assert len(load_slip(day)) == 1
    save_slip([e], day)
    assert len(load_slip(day)) == 2  # append, ikke overskriv


def test_infer_surface_lookup_og_fallback() -> None:
    lookup = {"wimbledon": "Grass", "rolandgarros": "Clay"}
    assert infer_surface("Wimbledon", date(2026, 7, 1), lookup) == "Grass"
    assert infer_surface("Roland Garros", date(2026, 6, 1), lookup) == "Clay"
    # Ukjent turnering -> årstid-fallback (juli -> grass).
    assert infer_surface("Ukjent Cup", date(2026, 7, 1), lookup) == "Grass"
    # Ukjent + vinter -> hard.
    assert infer_surface("Ukjent Cup", date(2026, 1, 15), lookup) == "Hard"


# --- NT WebSocket-parsing (SockJS-ramme som fixture) ------------------------
def _ws_frame() -> str:
    """Én SockJS-ramme (a[...]) med et tennis-event og Vinner-marked, slik NT
    faktisk sender det (fraksjonsodds i currentpriceup/-down)."""
    inner = {
        "version": 1,
        "data": [{
            "contentId": {"type": "eventGroup", "id": "104607.1"},
            "changeType": "refreshed",
            "change": {"events": [{
                "idfoevent": "8501223.1",
                "sporttypename": "Tennis",
                "name": "Auger-Aliassime, Felix - Djokovic, Novak",
                "tournamentname": "Wimbledon Men Singles - ATP",
                "tsstart": "2026-07-07T18:00:00.000+02:00",
                "markets": [{
                    "name": "Vinner ",
                    "selections": [
                        {"competitornumber": "1", "name": "Auger-Aliassime, Felix",
                         "currentpriceup": "13", "currentpricedown": "10"},
                        {"competitornumber": "2", "name": "Djokovic, Novak",
                         "currentpriceup": "13", "currentpricedown": "25"},
                    ],
                }],
            }]},
        }],
    }
    return "a[" + json.dumps(json.dumps(inner)) + "]"


def test_nt_name_to_query() -> None:
    assert nt_name_to_query("Djokovic, Novak") == "Novak Djokovic"
    assert nt_name_to_query("Sinner, Jannik") == "Jannik Sinner"
    assert nt_name_to_query("Cobolli Flavio") == "Cobolli Flavio"  # uten komma: uendret


def test_parse_ws_frames() -> None:
    ms = parse_ws_frames([_ws_frame(), "o", 'a["ping"]'])  # tåler støy-rammer
    assert len(ms) == 1
    m = ms[0]
    assert m["home"] == "Auger-Aliassime, Felix" and m["away"] == "Djokovic, Novak"
    assert m["odds_home"] == pytest.approx(1 + 13 / 10)   # 2.3
    assert m["odds_away"] == pytest.approx(1 + 13 / 25)   # 1.52
    assert m["tour"] == "atp"
    assert m["tournament"].startswith("Wimbledon")


def test_parse_ws_frames_merker_double() -> None:
    inner = {"version": 1, "data": [{"change": {"events": [{
        "idfoevent": "9.1", "sporttypename": "Tennis",
        "name": "Krawietz K / Puetz T - Doumbia S / Reboul F",
        "tournamentname": "Wimbledon Men Doubles - ATP",
        "markets": [{"name": "Vinner ", "selections": [
            {"competitornumber": "1", "name": "Krawietz K / Puetz T", "currentpriceup": "1", "currentpricedown": "2"},
            {"competitornumber": "2", "name": "Doumbia S / Reboul F", "currentpriceup": "3", "currentpricedown": "2"},
        ]}],
    }]}}]}
    frame = "a[" + json.dumps(json.dumps(inner)) + "]"
    ms = parse_ws_frames([frame])
    assert len(ms) == 1 and ms[0]["kind"] == "double"  # med, men merket


def test_fetch_nt_odds_med_mocket_harvest(index, tmp_path, monkeypatch) -> None:
    # Mock nettleser-hentingen med en ekte-formet WS-ramme; verifiser slip.
    monkeypatch.setattr(nt_odds.config, "ODDS_DIR", tmp_path)
    monkeypatch.setattr(nt_odds, "harvest_nt_odds", lambda **k: [_ws_frame()])
    from src.ingest import load_matches

    entries = nt_odds.fetch_nt_odds(date(2026, 7, 7), matches=load_matches(), index=index)
    assert len(entries) == 1
    e = entries[0]
    # Djokovic skal kobles til en gyldig spiller-id, underlag = Grass (Wimbledon).
    assert e["player_b_id"] is not None and "Djokovic" in e["player_b_name"]
    assert e["surface"] == "Grass"
    assert e["nt_odds_b"] == pytest.approx(1.52)
    assert len(load_slip(date(2026, 7, 7))) == 1
