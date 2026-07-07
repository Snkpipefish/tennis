# Kalibreringsrapport — Modul 3

_Generert automatisk av `src/calibrate.py`. Test-sesong: 2026 (out-of-sample)._

## Konklusjon

- **Kvalitet på endelig modell: GOD**
- Basis-variant valgt: **Blanding (50/50)** (`p_blend`)
- Kalibreringsmetode valgt: **platt**
- På urørt test-sesong 2026: Brier **0.2169**, log-loss **0.6221**, ECE **0.0215** (2,865 kamper).
- Kalibrering forbedret log-loss med +0.0108 og ECE med +0.0314 vs. rå Elo.

**Referansepunkt:** Brier 0,25 = ren myntkast (alltid 0,5). Lavere er bedre. ECE er vektet snitt-avvik mellom predikert og observert sannsynlighet; < 0,03 regnes som godt kalibrert.

## Metodikk

- Datasett: 121,467 kamper, sesongene 2005–2026 (ATP+WTA, Sackmann).
- Elo varmes opp på alt før de siste 2 sesongene.
- Walk-forward gjennom holdout (predikér før kamp, oppdater etter) — som i produksjon.
- **Fit-sett** (kalibrator trenes her): sesong 2025.
- **Test-sett** (urørt, endelig dom): sesong 2026.
- Spillere ordnes deterministisk (a = lavest id) før prediksjon for å unngå label-lekkasje; snitt-label i test = 0.501 (≈0,5 bekrefter balanse).

## 1. Rå Elo-varianter (out-of-sample test)

| Variant | Brier | Log-loss | ECE | n |
|---|---|---|---|---|
| Samlet Elo | 0.2232 | 0.6403 | 0.0622 | 2,865 |
| Underlags-Elo | 0.2267 | 0.6491 | 0.0669 | 2,865 |
| Blanding (50/50) ⬅ valgt | 0.2207 | 0.6329 | 0.0529 | 2,865 |

_Basis valgt etter log-loss på fit-sesong 2025 (ikke test), for å unngå å tilpasse seg testen._

## 2. Kalibrering av basis (Blanding (50/50)) — test-sesong 2026

| Metode | Brier | Log-loss | ECE | n |
|---|---|---|---|---|
| raw | 0.2207 | 0.6329 | 0.0529 | 2,865 |
| platt ⬅ valgt | 0.2169 | 0.6221 | 0.0215 | 2,865 |
| isotonic | 0.2175 | 0.6300 | 0.0143 | 2,865 |

## 3. Reliability-tabell (test-sesong)

| Bin | n | Rå snitt-pred | Rå observert | Kalibrert snitt-pred | Kalibrert observert |
|---|---|---|---|---|---|
| 0.0–0.1 | 66 | 0.064 | 0.030 | 0.067 | 0.000 |
| 0.1–0.2 | 161 | 0.156 | 0.161 | 0.158 | 0.122 |
| 0.2–0.3 | 274 | 0.250 | 0.277 | 0.259 | 0.208 |
| 0.3–0.4 | 314 | 0.352 | 0.373 | 0.353 | 0.344 |
| 0.4–0.5 | 394 | 0.450 | 0.457 | 0.451 | 0.476 |
| 0.5–0.6 | 413 | 0.551 | 0.516 | 0.551 | 0.543 |
| 0.6–0.7 | 432 | 0.650 | 0.558 | 0.649 | 0.665 |
| 0.7–0.8 | 390 | 0.749 | 0.674 | 0.744 | 0.710 |
| 0.8–0.9 | 302 | 0.846 | 0.712 | 0.833 | 0.861 |
| 0.9–1.0 | 119 | 0.933 | 0.866 | 0.924 | 0.889 |

## 4. Reliability-diagram

![Reliability diagram](reliability_diagram.png)

Kalibrator lagret til `models/calibrator.pkl` (basis `p_blend`, metode `platt`).
