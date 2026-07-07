"""Lokal web-UI for tennis-EV-maskinen.

Ett dashbord: full oversikt over ALLE turneringer og kamper (single og double,
herrer og damer, alle bøker) listet nedover, med modell-P, markeds-P og EV per
kamp — pluss anbefalte spill øverst når det finnes kanter.

Ingen bankroll-felt: innsatser vises PER 1000 KR bankroll, så skalerer man
selv (dobbel bankroll = dobbel innsats). Odds hentes uten synlig nettleser.

Start:  python main.py ui      (åpner http://127.0.0.1:5057)
"""
from __future__ import annotations

from datetime import date as date_cls

import pandas as pd
from flask import Flask, flash, redirect, render_template_string, request, url_for

from . import config, ev_engine, nt_odds, track
from .nt_odds import _norm

app = Flask(__name__)
app.secret_key = "tennis-ev-local"  # kun lokal bruk

_PORT = 5057


def _fmt_time(start) -> str:
    t = pd.to_datetime(start, errors="coerce", utc=True)
    if pd.isna(t):
        return ""
    t = t.tz_convert("Europe/Oslo")
    return t.strftime("%H:%M") if t.date() == date_cls.today() else t.strftime("%d.%m %H:%M")


def _fmt_pp(pa: float) -> str:
    return f"{pa*100:.0f}–{(1-pa)*100:.0f} %"


def _level_of(tournament: str) -> str:
    low = tournament.lower()
    if "challenger" in low:
        return "Challenger"
    if "itf" in low:
        return "ITF"
    return "Hovedtour"


def build_overview(entries: list[dict], df: pd.DataFrame) -> list[dict]:
    """Slip + EV-tabell -> nivåseksjoner (Hovedtour/Challenger/ITF) med
    turneringer og kamper, ferdig formatert. HVER kamp får maskinens tips
    (favoritt + prosent) — også når det ikke finnes noe å spille."""
    matches: dict[str, dict] = {}
    for e in entries:
        key = ev_engine.match_key_of(e)
        m = matches.setdefault(key, {
            "key": key, "name_a": e["player_a_name"], "name_b": e["player_b_name"],
            "a_id": e.get("player_a_id"), "kind": e.get("kind", "single"),
            "tour": e.get("tour", ""), "surface": e.get("surface", ""),
            "tournament": e.get("tournament", ""), "start": e.get("start"),
            "odds": {},
        })
        # Orienter oddsene til kampens visningsrekkefølge (a–b).
        same = (e.get("player_a_id") is not None and e.get("player_a_id") == m["a_id"]) or \
               _norm(e["player_a_name"]) == _norm(m["name_a"])
        oa, ob = (e["nt_odds_a"], e["nt_odds_b"]) if same else (e["nt_odds_b"], e["nt_odds_a"])
        m["odds"][e.get("book", "nt")] = (oa, ob)
        if e.get("book") == "nt":  # NTs norske turneringsnavn foretrekkes
            m["tournament"] = e.get("tournament", m["tournament"])
        if not m["start"] and e.get("start"):
            m["start"] = e["start"]

    by_key = df.groupby("match_key") if not df.empty else None
    rows: dict[str, dict] = {}
    for key, m in matches.items():
        # Maskinens tips: modellens blandede P når spillerne er kjent,
        # ellers markedets implisitte P fra oddsene (merket med ~).
        tip_pa, tip_approx = None, False
        value_str, value_cls, bet_str = "", "", ""
        if by_key is not None and key in by_key.groups:
            g = df.loc[by_key.groups[key]]
            ga = g[g["bet_on"] == m["name_a"]]
            if not ga.empty and bool(ga.iloc[0]["known"]):
                tip_pa = float(ga.iloc[0]["model_p"])
            best = g.sort_values("ev", ascending=False).iloc[0]
            if best["ev"] > 0:
                value_str = f"{best['ev']*100:+.1f} %"
                value_cls = "pos"
            b = g[g["bet"]]
            if not b.empty:
                bb = b.sort_values("ev", ascending=False).iloc[0]
                bet_str = (f"{bb['bet_on']} @ {bb['nt_odds']:.2f} hos "
                           f"{config.BOOK_LABELS.get(bb['book'], bb['book'])} — "
                           f"{bb['stake_kr']:.0f} kr/1000")
        if tip_pa is None:
            oa, ob = m["odds"].get("pinnacle") or next(iter(m["odds"].values()))
            tip_pa = (1.0 / oa) / (1.0 / oa + 1.0 / ob)
            tip_approx = True
        tip_side = "a" if tip_pa >= 0.5 else "b"
        rows[key] = {
            **m,
            "time": _fmt_time(m["start"]),
            "odds_str": {b: f"{o[0]:.2f} / {o[1]:.2f}" for b, o in m["odds"].items()},
            "tip_side": tip_side,
            "tip_name": m["name_a"] if tip_side == "a" else m["name_b"],
            "tip_p": f"{'~' if tip_approx else ''}{max(tip_pa, 1-tip_pa)*100:.0f} %",
            "value_str": value_str, "value_cls": value_cls, "bet_str": bet_str,
            "sort_start": str(m["start"] or "9999"),
        }

    tournaments: dict[str, list] = {}
    for r in rows.values():
        tournaments.setdefault(r["tournament"] or "(ukjent turnering)", []).append(r)
    levels: dict[str, list] = {"Hovedtour": [], "Challenger": [], "ITF": []}
    for name, ms in tournaments.items():
        ms.sort(key=lambda r: r["sort_start"])
        levels[_level_of(name)].append(
            {"name": name, "surface": ms[0]["surface"], "tour": ms[0]["tour"].upper(),
             "matches": ms, "sort": ms[0]["sort_start"]})
    out = []
    for title in ("Hovedtour", "Challenger", "ITF"):
        ts = sorted(levels[title], key=lambda t: (t["sort"], t["name"]))
        if ts:
            out.append({"title": title, "open": title == "Hovedtour",
                        "tournaments": ts, "n": sum(len(t["matches"]) for t in ts)})
    return out


TEMPLATE = """
<!doctype html><html lang="no"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tennis +EV</title>
<style>
  :root{--bg:#0f1419;--card:#1a2230;--line:#2b3648;--ink:#e6edf3;--muted:#8b98a9;
        --pos:#3fb950;--neg:#f85149;--accent:#388bfd;}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:1100px;margin:0 auto;padding:24px}
  h1{font-size:22px;margin:0 0 4px} .sub{color:var(--muted);margin:0 0 20px;font-size:13px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:18px}
  .card h2{font-size:15px;margin:0 0 12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
  h3{font-size:15px;margin:18px 0 6px} h3:first-of-type{margin-top:0}
  table{width:100%;border-collapse:collapse;font-size:14px}
  th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}
  th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
  .pos{color:var(--pos)} .neg{color:var(--neg)}
  .pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;background:#22304a;color:#9fc1ff;margin-left:6px}
  .pill.d{background:#3a2b4a;color:#d2a8ff}
  .btn{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:9px 14px;font-size:14px;cursor:pointer}
  .btn.sec{background:#26324a} .btn.win{background:var(--pos)} .btn.loss{background:var(--neg)}
  .btn:hover{filter:brightness(1.1)}
  form.inline{display:inline} .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .flash{background:#1d2b1d;border:1px solid #2ea04366;color:#7ee787;padding:10px 14px;border-radius:8px;margin-bottom:14px}
  .flash.err{background:#2b1d1d;border-color:#f8514966;color:#ff9a93}
  .stat{display:inline-block;margin-right:28px} .stat b{font-size:20px;display:block}
  .muted{color:var(--muted)} .empty{color:var(--muted);padding:8px 0}
  .betline{background:#15281a;border:1px solid #2ea04355;border-radius:8px;padding:2px 8px;color:#7ee787;font-size:13px;white-space:nowrap}
  details{margin:4px 0 10px} summary{cursor:pointer;font-weight:600;padding:6px 0;font-size:14px}
  summary:hover{color:#9fc1ff}
</style></head><body><div class="wrap">

<h1>🎾 Tennis +EV</h1>
<p class="sub">{{ today }} · P = marked (Pinnacle, de-vigget) + kalibrert Elo · spill kun når oddsen slår markedets fair pris og EV &gt; 5 % · innsats i kr per 1000 kr bankroll</p>

{% with msgs = get_flashed_messages(with_categories=true) %}
  {% for cat,msg in msgs %}<div class="flash {{ 'err' if cat=='err' else '' }}">{{ msg }}</div>{% endfor %}
{% endwith %}

<div class="card"><div class="row">
  <form method="post" action="{{ url_for('fetch') }}" class="inline">
    <button class="btn" type="submit">Hent odds &amp; regn</button></form>
  <form method="post" action="{{ url_for('refresh_model') }}" class="inline">
    <button class="btn sec" type="submit">Oppdater data &amp; modell</button></form>
  <form method="post" action="{{ url_for('log') }}" class="inline">
    <button class="btn sec" type="submit">Loggfør anbefalte</button></form>
  <span class="muted" style="font-size:13px">Henter Pinnacle + Norsk Tipping i bakgrunnen — ingen vinduer.</span>
</div></div>

<div class="card">
  <h2>Anbefalte spill ({{ bets|length }})</h2>
  {% if bets %}
  <table><tr>
    <th>Turnering</th><th>Kamp</th><th>Bok</th><th>Spill på</th><th class="num">P</th>
    <th class="num">Marked-P</th><th class="num">Odds</th><th class="num">EV%</th><th class="num">kr / 1000</th></tr>
  {% for b in bets %}<tr>
    <td class="muted">{{ b.tournament }}</td><td>{{ b.match }}</td>
    <td>{{ book_labels.get(b.book, b.book) }}</td><td><b>{{ b.bet_on }}</b></td>
    <td class="num">{{ '%.1f'|format(b.model_p*100) }}%</td>
    <td class="num">{{ '–' if b.market_p != b.market_p else '%.1f%%'|format(b.market_p*100) }}</td>
    <td class="num">{{ '%.2f'|format(b.nt_odds) }}</td>
    <td class="num pos">+{{ '%.1f'|format(b.ev*100) }}</td>
    <td class="num"><b>{{ '%.0f'|format(b.stake_kr) }}</b></td></tr>{% endfor %}
  </table>
  {% elif sections %}
  <p class="empty">Ingen kanter akkurat nå — ingen odds slår markedets fair pris med margin. Da er riktig svar å ikke spille. Tipsene står likevel under.</p>
  {% else %}
  <p class="empty">Ingen odds hentet ennå — trykk «Hent odds &amp; regn».</p>
  {% endif %}
</div>

<div class="card">
  <h2>Kamper og tips ({{ n_matches }})</h2>
  <p class="muted" style="margin:0 0 10px;font-size:13px">Tips = maskinens antagelse om vinner, uansett om oddsen er verdt å spille. ~ betyr anslag fra markedet (modellen kjenner ikke spillerne / double).</p>
  {% for sec in sections %}
    <details {{ 'open' if sec.open }}>
      <summary>{{ sec.title }} <span class="muted">({{ sec.n }} kamper)</span></summary>
      {% for t in sec.tournaments %}
      <h3>{{ t.name }} <span class="pill">{{ t.tour }}</span><span class="pill">{{ t.surface }}</span></h3>
      <table><tr><th>Tid</th><th>Kamp</th><th>Tips</th><th class="num">NT</th><th class="num">Pinnacle</th><th>Verdi</th></tr>
      {% for m in t.matches %}<tr>
        <td class="muted num">{{ m.time }}</td>
        <td>{% if m.tip_side == 'a' %}<b>{{ m.name_a }}</b> – <span class="muted">{{ m.name_b }}</span>
            {% else %}<span class="muted">{{ m.name_a }}</span> – <b>{{ m.name_b }}</b>{% endif %}
            {% if m.kind == 'double' %}<span class="pill d">Double</span>{% endif %}</td>
        <td class="num"><b>{{ m.tip_name }}</b> {{ m.tip_p }}</td>
        <td class="num">{{ m.odds_str.get('nt', '–') }}</td>
        <td class="num">{{ m.odds_str.get('pinnacle', '–') }}</td>
        <td>{% if m.bet_str %}<span class="betline">✔ {{ m.bet_str }}</span>
            {% elif m.value_str %}<span class="{{ m.value_cls }}">{{ m.value_str }}</span>
            {% else %}<span class="muted">–</span>{% endif %}</td>
      </tr>{% endfor %}
      </table>
      {% endfor %}
    </details>
  {% else %}
    <p class="empty">Ingen kamper i dag ennå — trykk «Hent odds &amp; regn».</p>
  {% endfor %}
</div>

<div class="card">
  <h2>Åpne veddemål ({{ open_bets|length }})</h2>
  {% if open_bets %}
  <table><tr><th>Dato</th><th>Bok</th><th>Kamp</th><th>Spill på</th><th class="num">Odds</th>
    <th class="num">kr / 1000</th><th>Utfall</th></tr>
  {% for o in open_bets %}<tr>
    <td class="muted">{{ o.placed_date }}</td>
    <td>{{ book_labels.get(o.get('book','nt'), o.get('book','nt')) }}</td>
    <td>{{ o.match }}</td><td>{{ o.bet_on }}</td>
    <td class="num">{{ '%.2f'|format(o.nt_odds) }}</td><td class="num">{{ '%.0f'|format(o.stake_kr) }}</td>
    <td>
      <form method="post" action="{{ url_for('settle') }}" class="inline">
        <input type="hidden" name="bet_id" value="{{ o.bet_id }}"><input type="hidden" name="won" value="1">
        <button class="btn win" type="submit">Vant</button></form>
      <form method="post" action="{{ url_for('settle') }}" class="inline">
        <input type="hidden" name="bet_id" value="{{ o.bet_id }}"><input type="hidden" name="won" value="0">
        <button class="btn loss" type="submit">Tapte</button></form>
    </td></tr>{% endfor %}
  </table>
  {% else %}<p class="empty">Ingen åpne veddemål. Trykk «Loggfør anbefalte» for å spore dagens.</p>{% endif %}
</div>

<div class="card">
  <h2>Track record</h2>
  {% if stats.n_settled %}
    <div class="stat"><span class="muted">Faktisk ROI</span>
      <b class="{{ 'pos' if stats.actual_roi>=0 else 'neg' }}">{{ '%+.1f'|format(stats.actual_roi*100) }}%</b></div>
    <div class="stat"><span class="muted">Forventet ROI</span><b>{{ '%+.1f'|format(stats.expected_roi*100) }}%</b></div>
    <div class="stat"><span class="muted">Resultat (per 1000)</span>
      <b class="{{ 'pos' if stats.total_profit>=0 else 'neg' }}">{{ '%+.0f'|format(stats.total_profit) }} kr</b></div>
    <div class="stat"><span class="muted">Treff</span><b>{{ stats.n_won }}/{{ stats.n_settled }}</b></div>
  {% else %}<p class="empty">Ingen avgjorte veddemål ennå.</p>{% endif %}
</div>

<p class="sub">Legg spillene manuelt hos boka. Maskinen anbefaler — du bestemmer.</p>
</div>
<script>
// Vis at det jobbes: odds-henting og modelloppdatering tar opptil et par minutter.
document.querySelectorAll("form").forEach(f => f.addEventListener("submit", () => {
  const b = f.querySelector("button[type=submit]");
  if (b) { b.disabled = true; b.textContent = "Jobber …"; }
}));
</script>
</body></html>
"""


def _dashboard_context():
    entries = nt_odds.load_slip()
    df = ev_engine.evaluate_slip(entries, config.DEFAULT_BANKROLL) if entries else pd.DataFrame()
    bets = df[df["bet"]].to_dict("records") if not df.empty else []
    sections = build_overview(entries, df) if entries else []
    log = track.load_log()
    return {
        "today": date_cls.today().isoformat(),
        "bets": bets,
        "sections": sections,
        "n_matches": sum(s["n"] for s in sections),
        "stats": track.compute_stats(log),
        "open_bets": [r for r in log if r["status"] == "pending"],
        "book_labels": config.BOOK_LABELS,
    }


@app.route("/")
def index():
    return render_template_string(TEMPLATE, **_dashboard_context())


@app.route("/fetch", methods=["POST"])
def fetch():
    try:
        from . import odds_sources

        entries, warnings = odds_sources.fetch_all_odds()
        ev_engine.run(config.DEFAULT_BANKROLL, verbose=False)  # oppdater rapporten
        n_by_book: dict[str, int] = {}
        for e in entries:
            n_by_book[e.get("book", "nt")] = n_by_book.get(e.get("book", "nt"), 0) + 1
        summary = ", ".join(f"{n} fra {config.BOOK_LABELS.get(b, b)}" for b, n in n_by_book.items())
        flash(f"Hentet {summary}." + (f" ({'; '.join(warnings)})" if warnings else ""))
    except Exception as exc:
        flash(f"Kunne ikke hente odds: {exc}", "err")
    return redirect(url_for("index"))


@app.route("/refresh-model", methods=["POST"])
def refresh_model():
    try:
        from . import elo, ingest

        m = ingest.build_matches(verbose=False)
        elo.build_elo(m, verbose=False)
        flash("Data og Elo-modell oppdatert.")
    except Exception as exc:
        flash(f"Oppdatering feilet: {exc}", "err")
    return redirect(url_for("index"))


@app.route("/log", methods=["POST"])
def log():
    track.log_bets(bankroll=config.DEFAULT_BANKROLL)
    flash("Loggførte dagens anbefalte veddemål.")
    return redirect(url_for("index"))


@app.route("/settle", methods=["POST"])
def settle():
    try:
        bet_id = int(request.form["bet_id"])
        won = request.form.get("won") == "1"
        r = track.settle(bet_id, won)
        flash(f"Registrerte {'seier' if won else 'tap'} ({r['profit_kr']:+.0f} kr per 1000).")
    except (KeyError, ValueError) as exc:
        flash(f"Kunne ikke registrere utfall: {exc}", "err")
    return redirect(url_for("index"))


def run(host: str = "127.0.0.1", port: int = _PORT) -> None:
    print(f"Tennis +EV UI kjører på http://{host}:{port}  (Ctrl+C for å stoppe)")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    run()
