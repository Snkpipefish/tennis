"""Statisk publisering av dashbordet — kjøres av GitHub Actions.

Hele pipelinen kjører i skyen, helt uavhengig av Leif: bygg data (Sackmann +
tennis-data + ESPN-resultater), tren Elo, hent Pinnacle-odds, regn tips og EV,
og render ett statisk HTML-dokument til site/index.html som deployes til
GitHub Pages. Ingen NT, ingen nettleser, ingen hemmeligheter.

Siden har tre deler: dagens KUPONG (hovedtourens sterkeste favoritter, som
kan hukes av/på med samlet odds og sannsynlighet regnet live), eventuelle
+EV-spill mot markedet, og full oversikt over alle kamper med tips.

Kjør lokalt for test:  python -m src.publish
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import config, elo, ev_engine, ingest, odds_sources
from .ui import build_kupong, build_overview

SITE_DIR = config.ROOT / "site"
HISTORY_DIR = config.DATA_DIR / "odds_history"

_PAGE = """<!doctype html><html lang="no"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tennis-tips</title>
<style>
  :root{{--bg:#0b1016;--card:#141b25;--card2:#182230;--line:#243041;--ink:#e8eef5;--muted:#8a97a8;
        --dim:#5f6b7a;--acc:#7cb8ff;--good:#3fd07a;--goodbg:#12301f;--warn:#f0b35a;--neg:#ff6b6b;
        --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased}}
  .wrap{{max-width:960px;margin:0 auto;padding:22px 20px 40px}}
  header{{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px;margin-bottom:16px}}
  h1{{font-size:24px;margin:0;letter-spacing:-.01em}}
  .meta{{color:var(--muted);font-size:13px;margin:0}}
  .card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:16px}}
  .card h2{{font-size:12px;margin:0 0 12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;font-weight:700}}
  .card h2 small{{font-weight:500;letter-spacing:0;text-transform:none;color:var(--dim);margin-left:6px}}
  .num{{font-variant-numeric:tabular-nums}}
  .mono{{font-family:var(--mono);font-size:13px}}
  .muted{{color:var(--muted)}} .dim{{color:var(--dim)}} .pos{{color:var(--good)}} .neg{{color:var(--neg)}}
  /* --- kupong --- */
  .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-bottom:14px}}
  .stat{{background:var(--card2);border:1px solid var(--line);border-radius:10px;padding:10px 12px}}
  .stat b{{display:block;font-size:22px;line-height:1.1;font-variant-numeric:tabular-nums}}
  .stat span{{font-size:12px;color:var(--muted)}}
  .picks{{list-style:none;margin:0;padding:0}}
  .pick{{display:grid;grid-template-columns:24px 92px 1fr auto auto;gap:10px;align-items:center;
    padding:9px 6px;border-top:1px solid var(--line)}}
  .pick:first-child{{border-top:none}}
  .pick input{{width:18px;height:18px;accent-color:var(--good);cursor:pointer;margin:0}}
  .pick .t{{color:var(--muted);font-size:13px;white-space:nowrap}}
  .pick .who b{{font-weight:650}} .pick .who .vs{{color:var(--dim)}}
  .pick .tour{{display:block;color:var(--dim);font-size:12px}}
  .pick.off .who{{opacity:.45}}
  .p{{display:inline-block;min-width:44px;text-align:center;padding:2px 7px;border-radius:999px;font-weight:700;font-size:12.5px;
      font-variant-numeric:tabular-nums;white-space:nowrap}}
  .p.hi{{background:var(--goodbg);color:var(--good)}} .p.mid{{background:#1c2b45;color:var(--acc)}} .p.lo{{background:#232a35;color:var(--muted)}}
  .odds{{font-family:var(--mono);font-size:13px;color:var(--ink);white-space:nowrap;text-align:right}}
  .note{{color:var(--muted);font-size:13px;margin:12px 0 0}}
  /* --- oversikt --- */
  details{{margin:2px 0 8px}}
  summary{{cursor:pointer;font-weight:650;padding:8px 0;font-size:15px;list-style:none;display:flex;align-items:center;gap:8px}}
  summary::-webkit-details-marker{{display:none}}
  summary::before{{content:"▸";color:var(--dim);font-size:13px;transition:transform .15s}}
  details[open]>summary::before{{transform:rotate(90deg)}}
  .tn{{display:flex;align-items:center;gap:8px;margin:14px 0 4px;font-size:14px;font-weight:650}}
  .pill{{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:600;background:#1c2b45;color:var(--acc)}}
  .pill.s{{background:#22303f;color:var(--muted)}} .pill.d{{background:#3a2b4a;color:#d2a8ff}}
  table{{width:100%;border-collapse:collapse;font-size:14px}}
  td{{padding:7px 8px;border-top:1px solid var(--line);vertical-align:middle}}
  tr:first-child td{{border-top:none}}
  td.t{{color:var(--muted);white-space:nowrap;width:1%;font-size:13px}}
  td.o{{text-align:right;white-space:nowrap;width:1%}}
  td.v{{white-space:nowrap;width:1%}}
  .vs{{color:var(--dim)}}
  .betline{{background:var(--goodbg);border:1px solid #2ea04366;border-radius:8px;padding:2px 8px;color:#7ee787;font-size:13px}}
  .legend{{color:var(--dim);font-size:12.5px;margin-top:6px}}
  @media (max-width:640px){{
    .wrap{{padding:12px 12px 32px}} body{{font-size:14px}} h1{{font-size:21px}}
    .card{{padding:12px 12px;border-radius:12px}}
    .stat b{{font-size:19px}}
    .pick{{grid-template-columns:22px 1fr auto;grid-template-areas:"c who p" "c t odds";row-gap:2px}}
    .pick input{{grid-area:c}} .pick .t{{grid-area:t}} .pick .who{{grid-area:who}} .pick .p{{grid-area:p}} .pick .odds{{grid-area:odds}}
    table,tbody,tr{{display:block;width:100%}}
    tr{{padding:7px 0;border-top:1px solid var(--line)}} tr:first-child{{border-top:none}}
    td,td.t,td.o,td.v{{display:inline;border:none;padding:0 8px 0 0;text-align:left;white-space:normal;width:auto}}
  }}
</style></head><body><div class="wrap">
<header><h1>🎾 Tennis-tips</h1><p class="meta">Oppdatert {updated} · Pinnacle-marked + Elo trent på {n_matches_total} kamper t.o.m. {last_result}</p></header>
{kupong_html}
{bets_html}
{overview_html}
<p class="legend">Tips = markedets pris (potens-de-vigget Pinnacle, 70 %) blandet med kalibrert Elo (30 %). ~ = kun markedets anslag (spiller ukjent for modellen).
Odds er Pinnacle. Innsats oppgis per 1000 kr. Tips er sannsynligheter, ikke garantier — spill ansvarlig.</p>
</div>
<script>
(function(){{
  var rows=[].slice.call(document.querySelectorAll('.pick'));
  if(!rows.length)return;
  function pct(x){{return (x*100).toFixed(x*100>=10?0:1)+' %';}}
  function upd(){{
    var n=0,po=1,pp=1,sum=0,dist=[1];
    rows.forEach(function(r){{
      var on=r.querySelector('input').checked; r.classList.toggle('off',!on); if(!on)return;
      var p=+r.dataset.p,o=+r.dataset.o; n++;po*=o;pp*=p;sum+=p;
      var d=new Array(dist.length+1).fill(0);
      for(var i=0;i<dist.length;i++){{d[i]+=dist[i]*(1-p);d[i+1]+=dist[i]*p;}} dist=d;
    }});
    var s=document.getElementById('ks');
    if(!n){{s.innerHTML='<div class="stat"><b>0</b><span>kamper valgt</span></div>';return;}}
    var ev=1000*(po*pp-1), max1=dist[n]+(n>1?dist[n-1]:0);
    s.innerHTML=
      '<div class="stat"><b>'+n+'</b><span>kamper</span></div>'+
      '<div class="stat"><b class="mono">'+po.toFixed(2)+'</b><span>samlet odds</span></div>'+
      '<div class="stat"><b>'+pct(pp)+'</b><span>alle går inn</span></div>'+
      '<div class="stat"><b>'+pct(max1)+'</b><span>høyst ett tap</span></div>'+
      '<div class="stat"><b>'+sum.toFixed(1).replace('.',',')+' av '+n+'</b><span>går vanligvis inn</span></div>'+
      '<div class="stat"><b class="'+(ev>=0?'pos':'neg')+'">'+(ev>=0?'+':'')+ev.toFixed(0)+' kr</b><span>forventet per 1000 kr</span></div>';
  }}
  rows.forEach(function(r){{r.querySelector('input').addEventListener('change',upd);}});
  upd();
}})();
</script>
</body></html>"""


def _esc(x: object) -> str:
    return html.escape(str(x), quote=False)


def _pclass(p: float) -> str:
    return "hi" if p >= 0.85 else ("mid" if p >= 0.70 else "lo")


def _kupong_html(k: dict) -> str:
    picks = k["picks"]
    L = ['<div class="card"><h2>Dagens kupong <small>hovedtourens sterkeste favoritter — '
         f'huk av selv, tallene regnes om</small></h2>']
    if not picks:
        L.append('<p class="muted">Ingen hovedtour-kamper priset akkurat nå.</p></div>')
        return "\n".join(L)
    L.append('<div class="stats" id="ks"></div><ul class="picks">')
    for p in picks:
        chk = " checked" if p["checked"] else ""
        L.append(
            f'<li class="pick" data-p="{p["p"]:.4f}" data-o="{p["odds"]:.3f}">'
            f'<input type="checkbox"{chk} aria-label="Ta med {_esc(p["name"])}">'
            f'<span class="t num">{_esc(p["time"])}</span>'
            f'<span class="who"><b>{_esc(p["name"])}</b> <span class="vs">– {_esc(p["opponent"])}</span>'
            f'<span class="tour">{_esc(p["tournament"])}</span></span>'
            f'<span class="p {_pclass(p["p"])}">{_esc(p["p_str"])}</span>'
            f'<span class="odds">{p["odds"]:.2f}</span></li>')
    L.append("</ul>")
    n85 = k["n_checked"]
    if n85:
        hvem = "den ene" if n85 == 1 else f"de {n85}"
        L.append(f'<p class="note">Forhåndsvalgt: {hvem} med tips over {k["pick_p"]*100:.0f} %. '
                 'Slike favoritter går historisk inn 92 av 100 ganger og er omtrent break-even hos Pinnacle; '
                 'hvert ledd under 85 % koster 1–3 %, og kupongen ganger opp tapet.</p>')
    else:
        L.append(f'<p class="note">Ingen favoritt over {k["pick_p"]*100:.0f} % akkurat nå — de sterkeste står '
                 'her, ingen er forhåndsvalgt. Ledd under 85 % koster 1–3 % hver, og kupongen ganger opp tapet.</p>')
    L.append("</div>")
    return "\n".join(L)


def _bets_html(bets: list[dict]) -> str:
    if not bets:
        return ('<p class="meta" style="margin:-6px 0 16px 4px">Anbefalte spill mot markedet: '
                'ingen akkurat nå — ingen odds slår Pinnacles fair pris med margin.</p>')
    L = ['<div class="card"><h2>Anbefalte spill <small>%d — oddsen slår markedets fair pris</small></h2>' % len(bets)]
    L.append('<table>')
    for b in bets:
        L.append(f'<tr><td class="t">{_esc(b["tournament"])}</td><td>{_esc(b["match"])} → <b>{_esc(b["bet_on"])}</b> '
                 f'<span class="p {_pclass(b["model_p"])}">{b["model_p"]*100:.0f} %</span></td>'
                 f'<td class="o mono">{b["nt_odds"]:.2f}</td>'
                 f'<td class="v"><span class="betline">EV +{b["ev"]*100:.1f} % · {b["stake_kr"]:.0f} kr/1000</span></td></tr>')
    L.append("</table></div>")
    return "\n".join(L)


def _overview_html(sections: list[dict]) -> str:
    n = sum(s["n"] for s in sections)
    L = [f'<div class="card"><h2>Alle kamper og tips <small>{n} kamper — favoritten uthevet med maskinens prosent</small></h2>']
    if not sections:
        L.append('<p class="muted">Ingen kamper ute akkurat nå.</p>')
    for sec in sections:
        L.append(f'<details {"open" if sec["open"] else ""}><summary>{_esc(sec["title"])} '
                 f'<span class="muted">({sec["n"]} kamper)</span></summary>')
        for t in sec["tournaments"]:
            L.append(f'<div class="tn">{_esc(t["name"])} <span class="pill">{_esc(t["tour"])}</span>'
                     f'<span class="pill s">{_esc(t["surface"])}</span></div>')
            L.append('<table>')
            for m in t["matches"]:
                badge = f'<span class="p {_pclass(m["tip_prob"])}">{_esc(m["tip_p"])}</span>'
                if m["tip_side"] == "a":
                    kamp = f'<b>{_esc(m["name_a"])}</b> {badge} <span class="vs">– {_esc(m["name_b"])}</span>'
                else:
                    kamp = f'<span class="vs">{_esc(m["name_a"])} –</span> <b>{_esc(m["name_b"])}</b> {badge}'
                if m["kind"] == "double":
                    kamp += ' <span class="pill d">Double</span>'
                verdi = (f'<span class="betline">✔ {_esc(m["bet_str"])}</span>' if m["bet_str"]
                         else (f'<span class="pos">{_esc(m["value_str"])}</span>' if m["value_str"] else ""))
                L.append(f'<tr><td class="t num">{_esc(m["time"])}</td><td>{kamp}</td>'
                         f'<td class="o mono">{_esc(m["odds_main"])}</td><td class="v">{verdi}</td></tr>')
            L.append("</table>")
        L.append("</details>")
    L.append("</div>")
    return "\n".join(L)


def render_site(entries: list[dict], df: pd.DataFrame, matches: pd.DataFrame) -> str:
    bets = df[df["bet"]].to_dict("records") if not df.empty else []
    sections = build_overview(entries, df) if entries else []
    kupong = build_kupong(sections)
    return _PAGE.format(
        updated=datetime.now(ZoneInfo("Europe/Oslo")).strftime("%d.%m.%Y %H:%M"),
        n_matches_total=f"{len(matches):,}".replace(",", " "),
        last_result=matches["date"].max().date().isoformat(),
        kupong_html=_kupong_html(kupong),
        bets_html=_bets_html(bets),
        overview_html=_overview_html(sections),
    )


def log_snapshot(df: pd.DataFrame) -> None:
    """Logg dagens evaluerte odds til data/odds_history/YYYY-MM.jsonl.

    Grunnlag for CLV-analyse (closing line value): eneste gjenværende
    kandidat-kant som ikke kan backtestes historisk. Snapshots fra de fire
    daglige kjøringene sammenlignes senere med tennis-datas closing-odds
    (tools/clv_report.py). Committes til repoet av workflowen.
    """
    if df.empty:
        return
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cols = ["book", "tour", "surface", "tournament", "start", "match",
            "side", "bet_on", "model_p", "elo_p", "market_p", "nt_odds",
            "ev", "known", "bet"]
    path = HISTORY_DIR / f"{ts[:7]}.jsonl"
    out = df[cols].astype(object).where(df[cols].notna(), None)  # NaN -> null
    with path.open("a", encoding="utf-8") as f:
        for r in out.to_dict("records"):
            r["ts"] = ts
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def main() -> int:
    print("[1/4] Bygger data (Sackmann + tennis-data + ESPN) ...")
    matches = ingest.build_matches(verbose=True)
    print("[2/4] Trener Elo ...")
    elo.build_elo(matches, verbose=False)
    print("[3/4] Henter Pinnacle-odds ...")
    entries, warnings = odds_sources.fetch_all_odds(matches=matches)
    for w in warnings:
        print(f"  ADVARSEL: {w}")
    print("[4/4] Regner tips og skriver site/index.html ...")
    df = ev_engine.evaluate_slip(entries, config.DEFAULT_BANKROLL)
    log_snapshot(df)
    SITE_DIR.mkdir(exist_ok=True)
    Path(SITE_DIR / "index.html").write_text(render_site(entries, df, matches))
    print(f"Ferdig: {SITE_DIR / 'index.html'} ({len(entries)} kamper)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
