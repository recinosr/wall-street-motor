# Factores con universo PIT

| Periodo | Rebalances | Media Top 5 | Media universo | Media peores 5 | Exceso Top 5 | IC 95% bootstrap mensual | Tickers sin serie | Fraccion sin serie | Fechas miembro sin precio/corte |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025-01-02–2026-09-30 | 20 | 5.98 % | 1.12 % | 1.26 % | 4.86 % | -1.08 % a 11.67 % | 10/537 | 1.86 % | 1.81 % |
| 2010–2024 | 170 | 1.48 % | 1.04 % | 2.21 % | 0.44 % | -0.51 % a 1.38 % | 179/782 | 22.89 % | 17.30 % |

Referencia anterior: Claude reporto +8.5% de exceso por horizonte de 21 dias con el universo elegido a posteriori. En esta medicion PIT, el exceso Top 5 frente al promedio de miembros elegibles es 4.86 %. Comparacion orientativa: la corrida anterior no dejo guardada su definicion de benchmark, asi que no es una replica exacta.

| Ano | Rebalances | Media Top 5 | Media universo | Media peores 5 | Exceso Top 5 |
|---|---:|---:|---:|---:|---:|
| 2010 | 3 | -2.15 % | 3.48 % | 2.02 % | -5.63 % |
| 2011 | 12 | -0.31 % | 0.15 % | 1.66 % | -0.46 % |
| 2012 | 12 | 2.17 % | 1.62 % | 3.49 % | 0.55 % |
| 2013 | 12 | 3.83 % | 2.31 % | 3.03 % | 1.52 % |
| 2014 | 12 | 2.07 % | 0.98 % | 0.00 % | 1.09 % |
| 2015 | 12 | 0.43 % | -0.21 % | -2.65 % | 0.64 % |
| 2016 | 12 | 1.92 % | 1.36 % | 6.92 % | 0.56 % |
| 2017 | 12 | 2.58 % | 1.40 % | 0.34 % | 1.18 % |
| 2018 | 12 | -2.90 % | -0.69 % | -0.99 % | -2.21 % |
| 2019 | 12 | 3.05 % | 1.92 % | 2.94 % | 1.13 % |
| 2020 | 12 | 1.72 % | 1.60 % | 9.18 % | 0.13 % |
| 2021 | 12 | 1.12 % | 1.93 % | 2.13 % | -0.80 % |
| 2022 | 12 | 0.43 % | -0.72 % | 1.71 % | 1.15 % |
| 2023 | 12 | 2.46 % | 0.81 % | 2.56 % | 1.64 % |
| 2024 | 11 | 3.23 % | 1.52 % | 0.60 % | 1.71 % |
| 2025 | 12 | 2.88 % | 0.96 % | 2.95 % | 1.92 % |
| 2026 | 8 | 10.62 % | 1.35 % | -1.26 % | 9.27 % |

Regla: momentum 12-1, volatilidad anualizada, distancia al maximo de 252 sesiones y penalizacion SMA200, equiponderada en cinco acciones. Rebalanceo cada 21 sesiones; horizonte de 21 sesiones sin solapamiento (salida en la sesion 21; el siguiente tramo entra desde el cierre previo). Cada fecha usa solo la membresia vigente y precios anteriores a la decision. El promedio usa miembros con historial suficiente para los factores y precio al cierre del horizonte. Las series Yahoo sin datos (HTTP 404 o sin grafico) aparecen en resumen.json; no se rellenaron ni inventaron. Los precios no incluyen dividendos. El JSON conserva los cortes anuales, intervalos bootstrap, tickers faltantes y cada rebalanceo.
