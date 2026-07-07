"""Engangs fangst-økt mot Norsk Tipping.

Åpner NT-sport i en ekte (headful) nettleser som et vanlig besøk, klikker seg
til tennis, og lagrer ALLE JSON-svar siden sender (uansett adresse) til
data/odds/capture/. Ingen direkte API-kall — kun det siden selv gjør, så
trafikken ser ut som et normalt besøk.

Kjøres av Claude, ikke av Leif.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402

CAPTURE_DIR = config.ODDS_DIR / "capture"
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import sync_playwright

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_jsonl = CAPTURE_DIR / f"responses_{stamp}.jsonl"
    out_meta = CAPTURE_DIR / f"meta_{stamp}.json"
    requests_seen: list[str] = []
    n_saved = 0

    with sync_playwright() as p, out_jsonl.open("w") as fh:
        ctx = p.chromium.launch_persistent_context(
            str(config.ODDS_DIR / "browser_profile"), headless=False,
            locale="nb-NO", viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )

        def on_request(req):
            requests_seen.append(req.url)
            # Lagre POST-kropper til NTs egne tjenester — trengs for å kunne
            # gjenskape kallene (content/get styres av POST-parametre).
            if req.method == "POST" and "norsk-tipping.no" in req.url:
                try:
                    fh.write(json.dumps({"type": "request", "url": req.url, "post": req.post_data or ""}) + "\n")
                    fh.flush()
                except Exception:
                    pass

        def on_websocket(ws):
            def frame(payload):
                nonlocal n_saved
                try:
                    if isinstance(payload, (bytes, bytearray)):
                        payload = payload.decode("utf-8", "replace")
                    if len(payload) < 2_000_000:
                        fh.write(json.dumps({"type": "ws", "url": ws.url, "body": payload}) + "\n")
                        fh.flush()
                        n_saved += 1
                except Exception:
                    pass
            ws.on("framereceived", frame)

        def on_response(resp):
            nonlocal n_saved
            try:
                ct = resp.headers.get("content-type", "")
                if "json" not in ct and "javascript" not in ct:
                    return
                body = resp.text()
                if not body or len(body) > 3_000_000:
                    return
                if "json" not in ct:
                    s = body.lstrip()
                    if not (s.startswith("{") or s.startswith("[")):
                        return
                fh.write(json.dumps({"url": resp.url, "status": resp.status, "body": body}) + "\n")
                fh.flush()
                n_saved += 1
            except Exception:
                pass

        ctx.on("request", on_request)
        ctx.on("response", on_response)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("websocket", on_websocket)

        try:
            page.goto("https://www.norsk-tipping.no/sport/oddsen", wait_until="domcontentloaded", timeout=60000)
        except PWError as exc:
            print(f"goto feilet: {exc}")
            ctx.close()
            return 1

        # Godta samtykke hvis banner.
        for lab in ("Godta alle", "Godta", "Aksepter alle", "Aksepter", "Tillat alle", "Jeg godtar", "OK"):
            try:
                el = page.get_by_role("button", name=lab, exact=False)
                if el.count() > 0:
                    el.first.click(timeout=2000)
                    page.wait_for_timeout(800)
                    break
            except Exception:
                continue

        page.wait_for_timeout(8000)

        # Lukk ev. dialog/modal som ligger over innholdet.
        for closer in ("Lukk", "Close"):
            try:
                el = page.get_by_role("button", name=closer, exact=False)
                if el.count() > 0 and el.first.is_visible():
                    el.first.click(timeout=2000)
                    page.wait_for_timeout(800)
                    break
            except Exception:
                continue

        # Sportsboken ligger i en IFRAME (sport2.norsk-tipping.no). Klikk og
        # lesing må skje i riktig frame — søk i alle frames etter Tennis i
        # sportslista til venstre, og velg synlig treff lengst til venstre.
        clicked = False
        target_frame = None
        for _attempt in range(3):
            for fr in page.frames:
                try:
                    cands = fr.locator("xpath=//*[normalize-space(text())='Tennis']")
                    n = min(cands.count(), 12)
                    best, best_x = None, 10**9
                    for i in range(n):
                        el = cands.nth(i)
                        try:
                            if not el.is_visible():
                                continue
                            box = el.bounding_box()
                            if box and box["x"] < best_x:
                                best_x, best = box["x"], el
                        except Exception:
                            continue
                    if best is not None:
                        best.scroll_into_view_if_needed(timeout=3000)
                        page.wait_for_timeout(400)
                        best.click(timeout=5000)
                        clicked = True
                        target_frame = fr
                        break
                except Exception:
                    continue
            if clicked:
                break
            page.wait_for_timeout(4000)  # frame kan fortsatt holde på å laste

        page.wait_for_timeout(8000)

        # Klikk videre inn på turneringene i tennislista (som en bruker) for å
        # tvinge kamp-/odds-dataene til å lastes. Prøv flere rader i tennis-framen.
        def _click_in_frame(fr, patterns, n_max=4):
            done = 0
            for pat in patterns:
                try:
                    loc = fr.get_by_text(re.compile(pat, re.I))
                    cnt = min(loc.count(), n_max)
                    for i in range(cnt):
                        el = loc.nth(i)
                        try:
                            if not el.is_visible():
                                continue
                            el.scroll_into_view_if_needed(timeout=2000)
                            el.click(timeout=3500)
                            done += 1
                            page.wait_for_timeout(3500)
                        except Exception:
                            continue
                    if done:
                        return done
                except Exception:
                    continue
            return done

        fr = target_frame or page
        # 1) åpne en turnering (Wimbledon / Open / Cup / Challenger / navn m/ tall)
        _click_in_frame(fr, [r"wimbledon", r"open", r"\bcup\b", r"masters", r"challenger", r"\d{4}"])
        page.wait_for_timeout(4000)
        # 2) prøv å åpne en enkeltkamp (rad med spillernavn skilt med '-')
        try:
            rows = fr.get_by_text(re.compile(r".+\s[-–]\s.+"))
            if rows.count() > 0:
                rows.first.scroll_into_view_if_needed(timeout=2000)
                rows.first.click(timeout=3500)
                page.wait_for_timeout(4000)
        except Exception:
            pass
        page.wait_for_timeout(4000)
        try:
            title = page.title()
            url_now = page.url
        except PWError:
            title, url_now = "?", "?"
        # Dump synlig tekst fra ALLE frames — kampene kan leses rett fra DOM.
        try:
            parts = []
            for fr in page.frames:
                try:
                    parts.append(f"===== FRAME {fr.url[:120]} =====\n" + fr.evaluate("() => document.body ? document.body.innerText : ''"))
                except Exception:
                    continue
            (CAPTURE_DIR / f"dom_{stamp}.txt").write_text("\n\n".join(parts))
        except PWError:
            pass
        ctx.close()

    out_meta.write_text(json.dumps({
        "clicked_tennis": clicked, "final_url": url_now, "title": title,
        "n_json_saved": n_saved, "n_requests": len(requests_seen),
        "request_urls": sorted(set(requests_seen)),
    }, indent=2, ensure_ascii=False))
    print(f"FERDIG: {n_saved} JSON-svar -> {out_jsonl}")
    print(f"meta -> {out_meta}")
    return 0 if n_saved else 2


if __name__ == "__main__":
    raise SystemExit(main())
