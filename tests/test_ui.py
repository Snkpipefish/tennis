"""Tester for den lokale web-UI-en (Flask test client)."""
from __future__ import annotations

import pytest

from src import ui


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Isoler bankroll-state og track-logg til tmp.
    monkeypatch.setattr(ui, "_STATE", tmp_path / "ui_state.json")
    monkeypatch.setattr(ui.track.config, "TRACK_LOG", tmp_path / "track.json")
    ui.app.config.update(TESTING=True)
    return ui.app.test_client()


def test_index_rendrer(client) -> None:
    r = client.get("/")
    assert r.status_code == 200
    html = r.data.decode()
    assert "Tennis +EV" in html
    assert "Dagens anbefalte" in html
    assert "Track record" in html


def test_bankroll_lagres(client) -> None:
    r = client.post("/bankroll", data={"bankroll": "5000"}, follow_redirects=True)
    assert r.status_code == 200
    assert ui.get_bankroll() == 5000.0


def test_bankroll_ugyldig_flasher_feil(client) -> None:
    r = client.post("/bankroll", data={"bankroll": "tull"}, follow_redirects=True)
    assert "Ugyldig" in r.data.decode()


def test_fetch_haandterer_feil(client, monkeypatch) -> None:
    # Simuler at ALLE kilder feiler — UI skal vise feilmelding, ikke krasje.
    from src import odds_sources

    def boom(*a, **k):
        raise RuntimeError("blokkert")

    monkeypatch.setattr(odds_sources, "fetch_all_odds", boom)
    r = client.post("/fetch", follow_redirects=True)
    assert r.status_code == 200
    assert "Kunne ikke hente" in r.data.decode()


def test_settle_ukjent_id_flasher_feil(client) -> None:
    r = client.post("/settle", data={"bet_id": "999", "won": "1"}, follow_redirects=True)
    assert r.status_code == 200
    assert "Kunne ikke registrere" in r.data.decode()


def test_index_har_hent_knapp(client) -> None:
    html = client.get("/").data.decode()
    assert "Hent odds" in html                 # henteknappen finnes
    assert "/fetch" in html
