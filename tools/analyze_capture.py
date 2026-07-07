"""Oppsummer en fangst-økt: hva slags JSON sendte NT-siden, og hvor er tennis?

Leser data/odds/capture/responses_*.jsonl og skriver en kompakt oversikt:
url, status, toppnøkler, størrelse, og om innholdet ser tennis-/odds-aktig ut.
Ingen antakelser om endepunkt — ren observasjon.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAPTURE_DIR = ROOT / "data" / "odds" / "capture"

TENNIS_RE = re.compile(r"tennis|atp|wta", re.I)
ODDS_HINTS = ("odds", "outcome", "betOffer", "market", "selection", "price")


def summarize(path: Path) -> None:
    print(f"== {path.name} ==")
    with path.open() as fh:
        for i, line in enumerate(fh):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            body = rec.get("body", "")
            try:
                j = json.loads(body)
            except Exception:
                continue
            keys = list(j.keys())[:8] if isinstance(j, dict) else f"list[{len(j)}]"
            tennis = bool(TENNIS_RE.search(body))
            oddsy = sum(1 for h in ODDS_HINTS if h in body)
            print(f"[{i}] {rec.get('status')} {len(body):>8}b tennis={int(tennis)} odds_hints={oddsy} keys={keys}")
            print(f"     {rec.get('url', '')[:160]}")


def main() -> int:
    files = sorted(CAPTURE_DIR.glob("responses_*.jsonl"))
    if not files:
        print("Ingen fangstfiler ennå.")
        return 1
    for f in files[-2:]:
        summarize(f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
