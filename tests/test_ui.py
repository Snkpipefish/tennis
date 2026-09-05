"""Tester for den lokale web-UI-en (Flask test client)."""
from __future__ import annotations

import pytest

from src import ui


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Isoler track-logg og slip til tmp.
    monkeypatch.setattr(ui.track.config, "TRACK_LOG", tmp_path / "track.json")
    monkeypatch.setattr(ui.nt_odds.config, "ODDS_DIR", tmp_path)
    ui.app.config.update(TESTING=True)
    return ui.app.test_client()


def test_index_rendrer(client) -> None:
    r = client.get("/")
    assert r.status_code == 200
    html = r.data.decode()
    assert "Tennis +EV" in html
    assert "Anbefalte spill" in html
    assert "Kamper og tips" in html
    assert "Track record" in html
    assert "bankroll" not in html.lower().replace("kr bankroll", "")  # ingen bankroll-felt


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


def test_oversikt_grupperer_og_viser_double(client, monkeypatch) -> None:
    from src.nt_odds import make_entry, save_slip

    single = make_entry(tour="atp", surface="Grass", book="nt", kind="single",
                        tournament="Wimbledon Men Singles - ATP",
                        start="2030-07-07T18:00:00Z",
                        player_a_id=1, player_a_name="Sterk", nt_odds_a=1.5,
                        player_b_id=2, player_b_name="Svak", nt_odds_b=2.6)
    double = make_entry(tour="atp", surface="Grass", book="nt", kind="double",
                        tournament="Wimbledon Men Doubles - ATP",
                        player_a_id=None, player_a_name="A / B", nt_odds_a=1.8,
                        player_b_id=None, player_b_name="C / D", nt_odds_b=2.0)
    save_slip([single, double], replace=True)
    html = client.get("/").data.decode()
    assert "Wimbledon Men Singles - ATP" in html
    assert "Wimbledon Men Doubles - ATP" in html
    assert "A / B" in html and "C / D" in html
    assert "Double" in html
    assert "Sterk" in html  # tips vises (modellens favoritt)


def test_build_overview_slaar_sammen_boeker() -> None:
    import pandas as pd

    from src.nt_odds import make_entry

    nt = make_entry(tour="atp", surface="Grass", book="nt",
                    tournament="Wimbledon", start="2030-07-07T18:00:00Z",
                    player_a_id=1, player_a_name="Sterk", nt_odds_a=1.5,
                    player_b_id=2, player_b_name="Svak", nt_odds_b=2.6)
    pinn = make_entry(tour="atp", surface="Grass", book="pinnacle",
                      tournament="ATP Wimbledon",
                      player_a_id=2, player_a_name="Svak", nt_odds_a=2.8,  # motsatt rekkefølge
                      player_b_id=1, player_b_name="Sterk", nt_odds_b=1.45)
    sections = ui.build_overview([nt, pinn], pd.DataFrame())
    assert len(sections) == 1 and sections[0]["title"] == "Hovedtour"
    ts = sections[0]["tournaments"]
    assert len(ts) == 1                       # samme kamp -> én rad
    m = ts[0]["matches"][0]
    assert m["odds_str"]["nt"] == "1.50 / 2.60"
    assert m["odds_str"]["pinnacle"] == "1.45 / 2.80"  # snudd riktig vei
    # Tips finnes selv uten modell-df: markedets implisitte favoritt (~).
    assert m["tip_name"] == "Sterk" and m["tip_p"].startswith("~")


def _sections_med_favoritter():
    from src.nt_odds import make_entry
    import pandas as pd

    def e(a, b, oa, ob, tourney, start, ida, idb):
        return make_entry(tour="atp", surface="Hard", book="pinnacle", kind="single",
                          tournament=tourney, start=start,
                          player_a_id=ida, player_a_name=a, nt_odds_a=oa,
                          player_b_id=idb, player_b_name=b, nt_odds_b=ob)
    entries = [
        e("Stor", "Liten", 1.08, 9.0, "ATP Test Open - R1", "2030-07-07T10:00:00Z", 1, 2),
        e("Midt", "Annen", 1.30, 3.6, "ATP Test Open - R1", "2030-07-07T12:00:00Z", 3, 4),
        e("Jevn", "Jevnere", 1.90, 1.95, "ATP Test Open - R1", "2030-07-07T14:00:00Z", 5, 6),
        e("Chall", "Enger", 1.05, 12.0, "ATP Challenger Bygda", "2030-07-07T09:00:00Z", 7, 8),
    ]
    # Tom EV-tabell -> tipset faller tilbake på markedets P (merket ~).
    return entries, pd.DataFrame()


def test_build_kupong_velger_hovedtourens_sterkeste() -> None:
    entries, df = _sections_med_favoritter()
    k = ui.build_kupong(ui.build_overview(entries, df))
    names = [p["name"] for p in k["picks"]]
    assert names[0] == "Stor"                      # sortert etter P
    assert "Chall" not in names                    # Challenger holdes utenfor
    assert len(k["picks"]) == 3                    # minst 3 rader vises
    assert k["picks"][0]["checked"] and k["n_checked"] == 1   # bare >= 85 % forhåndsvalgt
    assert k["picks"][0]["odds"] == 1.08 and k["picks"][0]["approx"] is True
    assert all(0.5 <= p["p"] <= 1.0 for p in k["picks"])


def test_render_site_har_kupong_og_oversikt() -> None:
    import pandas as pd
    from src import publish

    entries, df = _sections_med_favoritter()
    matches = pd.DataFrame({"date": pd.to_datetime(["2030-07-01"])})
    html = publish.render_site(entries, df, matches)
    assert "Dagens kupong" in html
    assert 'data-o="1.080"' in html and "Stor" in html
    assert "Alle kamper og tips" in html and "Challenger" in html
    assert "bankroll" not in html.lower().replace("kr bankroll", "")
