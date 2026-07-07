# Markedsvalidering — Modul 4

_Modellens kalibrerte sannsynligheter sammenlignet med Pinnacles closing odds (de-vigget). Pinnacle er referansen for et effektivt marked._

## Sammendrag

- Koblede kamper: **7,538** (sesongene 2023–2024, ATP+WTA).
- Korrelasjon modell vs Pinnacle: **0.790**.
- Pinnacles snittmargin (overround): **2.7 %**.
- Andel kamper med |modell − Pinnacle| > 5 %-poeng: **65.0 %**.

| Kilde | Brier | Log-loss | ECE | n |
|---|---|---|---|---|
| Modell (kalibrert) | 0.2167 | 0.6221 | 0.0105 | 7,538 |
| Pinnacle (de-vigget) | 0.1995 | 0.5809 | 0.0113 | 7,538 |

**Vurdering:** Modellen er merkbart bak Pinnacle. Vær varsom: store avvik er trolig modellfeil, ikke kant. Log-loss-gap modell − Pinnacle = +0.0412.

## Hva betyr dette for +EV mot Norsk Tipping?

Mot Pinnacle finnes nesten ingen kant. Reelle kanter oppstår der NTs odds avviker fra den skarpe konsensus. Bruk Pinnacle-avstanden som sanity-sjekk: er modellens P langt fra Pinnacle, stol mer på Pinnacle. Modul 6 leter etter NT-odds som er for høye relativt til den kalibrerte P-en som her er vist å ligge nær markedet.

## Avvik (modell − Pinnacle), persentiler

| Persentil | Avvik (%-poeng) |
|---|---|
| 1% | -34.0 |
| 5% | -22.4 |
| 25% | -10.0 |
| 50% | -3.0 |
| 75% | +4.2 |
| 95% | +16.8 |
| 99% | +27.7 |

## Plott

![Markedsvalidering](market_validation.png)

_Venstre: kalibreringskurver. Høyre: modell-P mot Pinnacle-P per kamp._
