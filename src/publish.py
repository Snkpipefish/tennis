"""Statisk publisering av dashbordet — kjøres av GitHub Actions.

Hele pipelinen kjører i skyen, helt uavhengig av Leif: bygg data (Sackmann +
tennis-data + ESPN-resultater), tren Elo, hent Pinnacle-odds, regn tips og EV,
og render ett statisk HTML-dokument til site/index.html som deployes til
GitHub Pages. Ingen NT, ingen nettleser, ingen hemmeligheter.

Kjør lokalt for test:  python -m src.publish
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import config, elo, ev_engine, ingest, odds_sources
from .ui import build_overview

SITE_DIR = config.ROOT / "site"
HISTORY_DIR = config.DATA_DIR / "odds_history"

_PAGE = """<!doctype html><html lang="no"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tennis +EV — tips</title>
<style>
  :root{{--bg:#0f1419;--card:#1a2230;--line:#2b3648;--ink:#e6edf3;--muted:#8b98a9;
        --pos:#3fb950;--neg:#f85149;}}
  *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
  .wrap{{max-width:1000px;margin:0 auto;padding:24px}}
  h1{{font-size:22px;margin:0 0 4px}} .sub{{color:var(--muted);margin:0 0 20px;font-size:13px}}
  .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:18px}}
  .card h2{{font-size:15px;margin:0 0 12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}}
  h3{{font-size:15px;margin:18px 0 6px}}
  table{{width:100%;border-collapse:collapse;font-size:14px}}
  th,td{{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}}
  th{{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase}}
  td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
  .pos{{color:var(--pos)}} .muted{{color:var(--muted)}} .empty{{color:var(--muted);padding:8px 0}}
  .pill{{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;background:#22304a;color:#9fc1ff;margin-left:6px}}
  .pill.d{{background:#3a2b4a;color:#d2a8ff}}
  .tp{{color:#9fc1ff;font-weight:600;font-size:13px;white-space:nowrap}}
  .od{{white-space:nowrap}}
  .betline{{background:#15281a;border:1px solid #2ea04355;border-radius:8px;padding:2px 8px;color:#7ee787;font-size:13px;white-space:nowrap}}
  details{{margin:4px 0 10px}} summary{{cursor:pointer;font-weight:600;padding:6px 0;font-size:14px}}
  /* Mobil: tabeller blir flytende tekstlinjer per kamp i stedet for brede kolonner. */
  @media (max-width:640px){{
    .wrap{{padding:12px}} body{{font-size:14px}}
    table,tbody,tr{{display:block;width:100%}}
    tr{{padding:7px 0;border-bottom:1px solid var(--line)}}
    tr:last-child{{border-bottom:none}}
    tr.h{{display:none}}
    td,td.num{{display:inline;border:none;padding:0 8px 0 0;text-align:left;white-space:normal}}
    td.od{{white-space:nowrap}}
    .betline{{white-space:normal;display:inline-block;margin-top:3px}}
  }}
</style></head><body><div class="wrap">
<h1>🎾 Tennis +EV — dagens tips</h1>
<p class="sub">Oppdatert {updated} · P = marked (Pinnacle, de-vigget) + kalibrert Elo trent på {n_matches_total:,} kamper t.o.m. {last_result} · ~ = anslag fra markedet · innsats i kr per 1000 kr bankroll</p>
{bets_html}
{overview_html}
<p class="sub">Automatisk generert. Tips er sannsynligheter, ikke garantier — spill ansvarlig.</p>
</div></body></html>"""


def _bets_html(bets: list[dict]) -> str:
    L = ['<div class="card"><h2>Anbefalte spill (%d)</h2>' % len(bets)]
    if not bets:
        L.append('<p class="empty">Ingen kanter akkurat nå — ingen odds slår markedets '
                 'fair pris med margin. Tipsene står under.</p>')
    else:
        L.append('<table><tr class="h"><th>Turnering</th><th>Kamp</th><th>Spill på</th>'
                 '<th class="num">P</th><th class="num">Odds</th><th class="num">EV%</th>'
                 '<th class="num">kr / 1000</th></tr>')
        for b in bets:
            L.append(f'<tr><td class="muted">{b["tournament"]}</td><td>{b["match"]}</td>'
                     f'<td><b>{b["bet_on"]}</b></td><td class="num">{b["model_p"]*100:.1f}%</td>'
                     f'<td class="num">{b["nt_odds"]:.2f}</td>'
                     f'<td class="num pos">+{b["ev"]*100:.1f}</td>'
                     f'<td class="num"><b>{b["stake_kr"]:.0f}</b></td></tr>')
        L.append("</table>")
    L.append("</div>")
    return "\n".join(L)


def _overview_html(sections: list[dict]) -> str:
    n = sum(s["n"] for s in sections)
    L = [f'<div class="card"><h2>Kamper og tips ({n})</h2>']
    if not sections:
        L.append('<p class="empty">Ingen kamper ute akkurat nå.</p>')
    for sec in sections:
        L.append(f'<details {"open" if sec["open"] else ""}><summary>{sec["title"]} '
                 f'<span class="muted">({sec["n"]} kamper)</span></summary>')
        for t in sec["tournaments"]:
            L.append(f'<h3>{t["name"]} <span class="pill">{t["tour"]}</span>'
                     f'<span class="pill">{t["surface"]}</span></h3>')
            L.append('<table><tr class="h"><th>Tid</th><th>Kamp (favoritt uthevet)</th>'
                     '<th class="num">Odds</th><th>Verdi</th></tr>')
            for m in t["matches"]:
                # Favoritten nevnes ÉN gang: uthevet, med prosenten limt på.
                if m["tip_side"] == "a":
                    kamp = (f'<b>{m["name_a"]}</b> <span class="tp">{m["tip_p"]}</span> '
                            f'<span class="muted">– {m["name_b"]}</span>')
                else:
                    kamp = (f'<span class="muted">{m["name_a"]} –</span> '
                            f'<b>{m["name_b"]}</b> <span class="tp">{m["tip_p"]}</span>')
                if m["kind"] == "double":
                    kamp += '<span class="pill d">Double</span>'
                verdi = (f'<span class="betline">✔ {m["bet_str"]}</span>' if m["bet_str"]
                         else (f'<span class="pos">{m["value_str"]}</span>' if m["value_str"] else ""))
                L.append(f'<tr><td class="muted num">{m["time"]}</td><td>{kamp}</td>'
                         f'<td class="num od">{m["odds_main"]}</td><td>{verdi}</td></tr>')
            L.append("</table>")
        L.append("</details>")
    L.append("</div>")
    return "\n".join(L)


def render_site(entries: list[dict], df: pd.DataFrame, matches: pd.DataFrame) -> str:
    bets = df[df["bet"]].to_dict("records") if not df.empty else []
    sections = build_overview(entries, df) if entries else []
    return _PAGE.format(
        updated=datetime.now(ZoneInfo("Europe/Oslo")).strftime("%d.%m.%Y %H:%M"),
        n_matches_total=len(matches),
        last_result=matches["date"].max().date().isoformat(),
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
