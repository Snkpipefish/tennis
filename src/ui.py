"""Liten lokal web-UI for tennis-EV-maskinen.

Ett dashboard i nettleseren slik at Leif slipper terminalen. Viser dagens
anbefalte veddemål og track record, med knapper for å hente NT-odds, regne på
nytt, loggføre veddemål og registrere utfall. Bankroll settes i et felt.

Start:  python main.py ui      (åpner http://127.0.0.1:5057)

Alt input skjer ved klikk/valg — ingen kommandolinje, ingen manuell odds-tasting.
"""
from __future__ import annotations

import json
from datetime import date as date_cls

from flask import Flask, flash, redirect, render_template_string, request, url_for

from . import config
from . import ev_engine, nt_odds, track

app = Flask(__name__)
app.secret_key = "tennis-ev-local"  # kun lokal bruk

_STATE = config.ODDS_DIR / "ui_state.json"
_PORT = 5057


def get_bankroll() -> float:
    if _STATE.exists():
        try:
            return float(json.loads(_STATE.read_text()).get("bankroll", 1000.0))
        except (ValueError, json.JSONDecodeError):
            pass
    return 1000.0


def set_bankroll(value: float) -> None:
    _STATE.write_text(json.dumps({"bankroll": value}))


TEMPLATE = """
<!doctype html><html lang="no"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tennis +EV</title>
<style>
  :root{--bg:#0f1419;--card:#1a2230;--line:#2b3648;--ink:#e6edf3;--muted:#8b98a9;
        --pos:#3fb950;--neg:#f85149;--accent:#388bfd;}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:1000px;margin:0 auto;padding:24px}
  h1{font-size:22px;margin:0 0 4px} .sub{color:var(--muted);margin:0 0 20px;font-size:13px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:18px}
  .card h2{font-size:15px;margin:0 0 12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
  table{width:100%;border-collapse:collapse;font-size:14px}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
  th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
  .pos{color:var(--pos)} .neg{color:var(--neg)}
  .pill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;background:#22304a;color:#9fc1ff}
  .btn{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:9px 14px;font-size:14px;cursor:pointer}
  .btn.sec{background:#26324a} .btn.win{background:var(--pos)} .btn.loss{background:var(--neg)}
  .btn:hover{filter:brightness(1.1)}
  form.inline{display:inline} .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  input[type=number]{background:#0d1117;border:1px solid var(--line);color:var(--ink);
    border-radius:8px;padding:8px 10px;width:120px;font-size:14px}
  .flash{background:#1d2b1d;border:1px solid #2ea04366;color:#7ee787;padding:10px 14px;border-radius:8px;margin-bottom:14px}
  .flash.err{background:#2b1d1d;border-color:#f8514966;color:#ff9a93}
  .stat{display:inline-block;margin-right:28px} .stat b{font-size:20px;display:block}
  .muted{color:var(--muted)} .empty{color:var(--muted);padding:8px 0}
</style></head><body><div class="wrap">

<h1>🎾 Tennis +EV — Norsk Tipping</h1>
<p class="sub">{{ today }} · kalibrert modell · vedd kun ved EV &gt; 5 % · 1/4-Kelly</p>

{% with msgs = get_flashed_messages(with_categories=true) %}
  {% for cat,msg in msgs %}<div class="flash {{ 'err' if cat=='err' else '' }}">{{ msg }}</div>{% endfor %}
{% endwith %}

<div class="card"><div class="row">
  <form method="post" action="{{ url_for('bankroll') }}" class="row">
    <label class="muted">Bankroll (kr)</label>
    <input type="number" name="bankroll" value="{{ bankroll|int }}" min="0" step="100">
    <button class="btn sec" type="submit">Lagre</button>
  </form>
  <form method="post" action="{{ url_for('fetch') }}" class="inline">
    <button class="btn" type="submit">Hent NT-odds &amp; regn</button></form>
  <form method="post" action="{{ url_for('refresh_model') }}" class="inline">
    <button class="btn sec" type="submit">Oppdater data &amp; modell</button></form>
  <form method="post" action="{{ url_for('log') }}" class="inline">
    <button class="btn sec" type="submit">Loggfør anbefalte</button></form>
</div>
<p class="muted" style="margin:10px 0 0;font-size:13px">«Hent NT-odds» åpner en nettleser som henter dagens kamper fra Norsk Tipping automatisk (tar noen sekunder første gang).</p>
</div>

<div class="card">
  <h2>Dagens anbefalte veddemål ({{ bets|length }})</h2>
  {% if bets %}
  <table><tr>
    <th>Kamp</th><th>Spill på</th><th class="num">Modell-P</th><th class="num">NT-odds</th>
    <th class="num">Implisitt-P</th><th class="num">EV%</th><th class="num">Innsats kr</th></tr>
  {% for b in bets %}<tr>
    <td>{{ b.match }}</td><td><b>{{ b.bet_on }}</b> <span class="pill">{{ b.surface }}</span></td>
    <td class="num">{{ '%.1f'|format(b.model_p*100) }}%</td>
    <td class="num">{{ '%.2f'|format(b.nt_odds) }}</td>
    <td class="num">{{ '%.1f'|format(b.implied_p*100) }}%</td>
    <td class="num pos">+{{ '%.1f'|format(b.ev*100) }}</td>
    <td class="num"><b>{{ '%.0f'|format(b.stake_kr) }}</b></td></tr>{% endfor %}
  </table>
  <p class="muted" style="margin-top:10px">Samlet innsats: <b>{{ '%.0f'|format(total_stake) }} kr</b>
     av {{ n_matches }} vurderte kamper.</p>
  {% else %}
  {% if has_slip %}<p class="empty">Ingen kamper over EV-terskelen i dag.</p>
  {% else %}<p class="empty">Ingen odds hentet i dag ennå — trykk «Hent NT-odds &amp; regn» øverst.</p>{% endif %}
  {% endif %}
</div>

<div class="card">
  <h2>Track record</h2>
  {% if stats.n_settled %}
    <div class="stat"><span class="muted">Faktisk ROI</span>
      <b class="{{ 'pos' if stats.actual_roi>=0 else 'neg' }}">{{ '%+.1f'|format(stats.actual_roi*100) }}%</b></div>
    <div class="stat"><span class="muted">Forventet ROI</span><b>{{ '%+.1f'|format(stats.expected_roi*100) }}%</b></div>
    <div class="stat"><span class="muted">Resultat</span>
      <b class="{{ 'pos' if stats.total_profit>=0 else 'neg' }}">{{ '%+.0f'|format(stats.total_profit) }} kr</b></div>
    <div class="stat"><span class="muted">Treff</span><b>{{ stats.n_won }}/{{ stats.n_settled }}</b></div>
  {% else %}<p class="empty">Ingen avgjorte veddemål ennå.</p>{% endif %}
</div>

<div class="card">
  <h2>Åpne veddemål ({{ open_bets|length }})</h2>
  {% if open_bets %}
  <table><tr><th>Dato</th><th>Kamp</th><th>Spill på</th><th class="num">Odds</th>
    <th class="num">Innsats</th><th>Utfall</th></tr>
  {% for o in open_bets %}<tr>
    <td class="muted">{{ o.placed_date }}</td><td>{{ o.match }}</td><td>{{ o.bet_on }}</td>
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

<p class="sub">Legg veddemålene manuelt hos Norsk Tipping. Maskinen anbefaler — du bestemmer.</p>
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
    bankroll = get_bankroll()
    entries = nt_odds.load_slip()
    df = ev_engine.evaluate_slip(entries, bankroll) if entries else None
    bets = []
    total_stake = 0.0
    n_matches = 0
    if df is not None and not df.empty:
        b = df[df["bet"]]
        bets = b.to_dict("records")
        total_stake = float(b["stake_kr"].sum())
        n_matches = len(df) // 2
    log = track.load_log()
    return {
        "today": date_cls.today().isoformat(),
        "bankroll": bankroll,
        "bets": bets,
        "total_stake": total_stake,
        "n_matches": n_matches,
        "has_slip": bool(entries),
        "stats": track.compute_stats(log),
        "open_bets": [r for r in log if r["status"] == "pending"],
    }


@app.route("/")
def index():
    return render_template_string(TEMPLATE, **_dashboard_context())


@app.route("/bankroll", methods=["POST"])
def bankroll():
    try:
        set_bankroll(float(request.form.get("bankroll", "1000").replace(",", ".")))
        flash("Bankroll lagret.")
    except ValueError:
        flash("Ugyldig bankroll.", "err")
    return redirect(url_for("index"))


@app.route("/fetch", methods=["POST"])
def fetch():
    try:
        entries = nt_odds.fetch_nt_odds()
        flash(f"Hentet {len(entries)} kamper fra Norsk Tipping.")
    except Exception as exc:
        flash(f"Kunne ikke hente odds automatisk: {exc}", "err")
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
    track.log_bets(bankroll=get_bankroll())
    flash("Loggførte dagens anbefalte veddemål.")
    return redirect(url_for("index"))


@app.route("/settle", methods=["POST"])
def settle():
    try:
        bet_id = int(request.form["bet_id"])
        won = request.form.get("won") == "1"
        r = track.settle(bet_id, won)
        flash(f"Registrerte {'seier' if won else 'tap'} ({r['profit_kr']:+.0f} kr).")
    except (KeyError, ValueError) as exc:
        flash(f"Kunne ikke registrere utfall: {exc}", "err")
    return redirect(url_for("index"))


def run(host: str = "127.0.0.1", port: int = 5057) -> None:
    print(f"Tennis +EV UI kjører på http://{host}:{port}  (Ctrl+C for å stoppe)")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    run()
