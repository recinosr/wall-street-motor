# Montecarlo del plan 80/20 (21-oct-2026)

Plan: 80 % VWRA (proxy VT) + 20 % VUAA (proxy SPY), US$100 al mes, sin vender. Versión `montecarlo-v2`. Bootstrap por bloques de 12 meses, 20,000 rondas, semilla fija. Script: `lab/montecarlo_plan.py` -> `resultados/montecarlo_plan.json` (corte de datos: 2026-10-19).

Costos incluidos en el escenario con costos: diferencial de TER frente a los proxies (VWRA 0.19 % vs VT 0.06 %; VUAA 0.07 % vs SPY 0.0945 %), dividendos netos de retención 15 % (supuestos, no medidos) y costo de compra de 0.10 % por aporte. Costo mediano = mediana sin costos menos mediana con costos, con la misma semilla.

## Base (pares VT/SPY, 2008-07 a 2026-10, 220 meses)

| Horizonte | Aportado | P1 | P5 | P50 | P95 | Prob. pérdida | Costo mediano |
|---|---|---|---|---|---|---|---|
| 5 años | 6,000 | 4,214 | 5,168 | 7,683 | 10,209 | 13.0 % | 62 |
| 10 años | 12,000 | 8,852 | 11,361 | 19,592 | 31,066 | 6.9 % | 318 |
| 20 años | 24,000 | 21,014 | 29,514 | 66,663 | 142,299 | 1.9 % | 2,300 |

## Historia larga (S&P 500 como proxy de toda la cartera, 1950-02 a 2026-10, solo EE. UU.)

| Horizonte | Aportado | P1 | P5 | P50 | P95 | Prob. pérdida | Costo mediano |
|---|---|---|---|---|---|---|---|
| 5 años | 6,000 | 4,583 | 5,483 | 7,863 | 10,534 | 10.1 % | 116 |
| 10 años | 12,000 | 9,630 | 12,201 | 20,740 | 33,448 | 4.6 % | 635 |
| 20 años | 24,000 | 25,265 | 34,834 | 76,578 | 164,098 | 0.8 % | 5,319 |

## Conservador (base con −4 %/año, 2008-07 a 2026-10)

| Horizonte | Aportado | P1 | P5 | P50 | P95 | Prob. pérdida | Costo mediano |
|---|---|---|---|---|---|---|---|
| 5 años | 6,000 | 3,832 | 4,686 | 6,915 | 9,129 | 24.2 % | 55 |
| 10 años | 12,000 | 7,337 | 9,292 | 15,659 | 24,287 | 19.1 % | 241 |
| 20 años | 24,000 | 14,161 | 19,370 | 40,808 | 82,777 | 11.9 % | 1,286 |

USD. "Prob. pérdida" = fracción de rondas con saldo final menor que lo aportado.

## Calibración contra VWRA.L (2019-08 a 2026-10, 87 meses)

- CAGR real de VWRA.L: 12.86 %/año.
- CAGR del modelo (pata VT con dividendo neto y diferencial de TER): 12.46 %/año.
- Diferencia: −0.40 pp/año (el modelo queda por debajo del fondo real en este período).

## Límites

- La base tiene solo 18 años de datos comunes y casi todos alcistas; no incluye 2000-2002 ni décadas perdidas. Por eso se publica el conservador.
- La historia larga es solo EE. UU. y usa dividendo neto fijo de 2.0 %/año y TER combinado de 0.166 %/año.
- Los dividendos (1.9 % VT, 1.3 % SPY brutos) son supuestos, no medidos.
- Cargo de la tarjeta o del banco al depositar: no modelado. Cambio de divisa 0 % asumido (cuenta y ETF en USD).
- Sin impuestos sobre ganancias. Retiro final 0 (XTB cobra US$30 solo en retiros menores de US$50).
- El último mes (oct-2026) es parcial: datos hasta el 19-oct.
- No predice: acota rangos bajo los supuestos declarados.

## Veredicto

A 20 años, la historia larga tiene P5 de US$34,834 y 0.8 % de probabilidad de terminar por debajo de lo aportado. En la base, P5 de US$29,514 y 1.9 % de probabilidad de pérdida. Son rangos bajo supuestos declarados, no una predicción.
