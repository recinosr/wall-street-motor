# Montecarlo del plan 80/20 (17-oct-2026)

Plan: 80 % VWRA (proxy VT) + 20 % VUAA (proxy SPY), US$100 al mes, sin vender. Bootstrap por bloques de 12 meses de pares (VT, SPY), 20,000 rondas, semilla fija. Script: `lab/montecarlo_plan.py` -> `resultados/montecarlo_plan.json`.

| Horizonte | Aportado | Mediana base | P5–P95 base | Mediana conservadora (−4 %/año) | P(final < aportado) base / conservador |
|---|---|---|---|---|---|
| 5 años | 6,000 | 7,750 | 5,224–10,300 | ver json | 12 % / ver json |
| 10 años | 12,000 | 19,940 | 11,596–31,649 | 15,924 | 6 % / 18 % |
| 20 años | 24,000 | 69,275 | 30,684–147,969 | 42,262 | 2 % / 10 % |

- La referencia del plan (7 % anual) en 10 años da US$17,105: cae cerca del percentil 30–35 del base, o sea es una meta razonable, no optimista.
- Caída máxima en 10 años: mediana −20 %, P5 −41 %. Probabilidad de ver −30 % o peor en algún momento: 28 %. De −50 %: 0.7 %. En 20 años: 61 % y 6 %.
- **Límites honestos:** solo hay 18 años de datos comunes (jun-2008 a hoy) y casi todos alcistas; por eso se publica el escenario conservador. Los dividendos (1.9 % y 1.3 %) son un supuesto, no medido. No incluye costos de XTB ni tipo de cambio. No predice: acota rangos.
- No cambia el plan: ninguna regla de salida se activó.
