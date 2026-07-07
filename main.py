"""main.py — orkestrering av hele tennis-EV-maskinen.

Daglig flyt (PLAN.md): oppdater data -> oppdater Elo -> les NT-odds -> today_bets.md

Leif gjør ingenting teknisk: odds hentes AUTOMATISK fra Norsk Tipping (Kambi).
Ingen manuell inntasting.

Kommandoer:
    python main.py ui                 Start lokal web-UI (http://127.0.0.1:5057)
    python main.py setup              Bygg/oppdater alt + valider (Modul 1-4)
    python main.py daily -b 5000      Hent odds, oppdater data/Elo, regn veddemål
    python main.py bets  -b 5000      Bare regn EV på dagens slip (Modul 6)
    python main.py log   -b 5000      Loggfør dagens anbefalte veddemål (Modul 7)
    python main.py settle <id> win    Registrer utfall (Modul 7)
    python main.py track              Skriv track_record.md (Modul 7)

-b/--bankroll i kroner (kreves for innsatsberegning).

Selv-oppstart: main.py bruker automatisk prosjektets .venv (og oppretter det med
avhengigheter ved første kjøring), slik at `python3 main.py ...` bare virker —
ingen manuell aktivering eller `pip install`.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_VENV = _ROOT / ".venv"
_VENV_PY = _VENV / "bin" / "python"


def _ensure_venv() -> None:
    """Sørg for at vi kjører i prosjektets .venv med avhengigheter installert."""
    # venv-ens python er en symlink til system-python, så sammenlign sys.prefix
    # (peker på .venv KUN når vi faktisk kjører i miljøet), ikke selve binæren.
    try:
        already = Path(sys.prefix).resolve() == _VENV.resolve()
    except OSError:
        already = False
    if already:
        return
    if not _VENV_PY.exists():
        print("Setter opp Python-miljø første gang (kan ta et minutt) ...", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(_ROOT / ".venv")], check=True)
        subprocess.run([str(_VENV_PY), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
        subprocess.run([str(_VENV_PY), "-m", "pip", "install", "-q", "-r", str(_ROOT / "requirements.txt")], check=True)
    # Start på nytt med riktig Python (erstatter denne prosessen).
    os.execv(str(_VENV_PY), [str(_VENV_PY), str(_ROOT / "main.py"), *sys.argv[1:]])


_ensure_venv()

from src import calibrate, elo, ev_engine, ingest, market_check, nt_odds, track  # noqa: E402


def _bankroll(argv: list[str], default: float = 1000.0) -> float:
    for i, a in enumerate(argv):
        if a in ("--bankroll", "-b") and i + 1 < len(argv):
            return float(argv[i + 1].replace(",", "."))
    return default


def cmd_setup() -> None:
    print("[1/4] Modul 1 — ingest");   matches = ingest.build_matches()
    print("[2/4] Modul 2 — elo");      elo.build_elo(matches)
    print("[3/4] Modul 3 — calibrate")
    result = calibrate.run_calibration(); calibrate.write_report(result)
    print("[4/4] Modul 4 — market_check")
    market_check.write_report(market_check.run_market_check())
    print("\nOppsett ferdig. Se reports/calibration.md og reports/market_validation.md.")


def cmd_daily(argv: list[str]) -> None:
    bankroll = _bankroll(argv)
    print("[1/4] Oppdaterer data ..."); matches = ingest.build_matches(verbose=False)
    print("[2/4] Oppdaterer Elo ...");  elo.build_elo(matches, verbose=False)
    print("[3/4] Henter NT-tennisodds i nettleser ...")
    try:
        nt_odds.fetch_nt_odds(matches=matches)
    except Exception as exc:
        print(f"  Klarte ikke hente odds: {exc}")
        print("  Bruker allerede lagret slip for i dag hvis den finnes.")
    print("[4/4] Regner dagens veddemål ...")
    ev_engine.run(bankroll)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else "daily"

    if cmd == "setup":
        cmd_setup()
    elif cmd == "fetch":          # hent odds uten å regne (diagnostikk)
        nt_odds.fetch_nt_odds()
    elif cmd == "manual":         # nødløsning hvis auto-henting svikter
        nt_odds.interactive()
    elif cmd == "daily":
        cmd_daily(argv[1:])
    elif cmd == "bets":
        ev_engine.run(_bankroll(argv[1:]))
    elif cmd == "ui":
        from src import ui
        ui.run()
    elif cmd in ("log", "settle", "track", "report"):
        track.main(argv if cmd != "track" else ["report"] + argv[1:])
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
