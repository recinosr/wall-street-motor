# Robots sistemáticos — seis reglas fijadas

Una corrida, 6 reglas, 12 comparaciones contra VT y 60/40, 18 mediciones de
crisis y 12 escenarios de aportes (US$50 y US$100). No hubo búsqueda de
parámetros ni selección del ganador. Las ventanas mensuales de diez años
se solapan; no son pruebas independientes. No se hicieron contrastes de
significancia ni se declara ventaja futura.

Descargas públicas nuevas en memoria, corte 8-oct-2026, sin abrir el archivo
reservado. Todos los cierres finales coincidieron con ChartExchange dentro
del umbral del verificador existente; esto no valida todas las velas ni los
dividendos. Los datos crudos no se publican. Resultados:
`salida/carteras_robots.json` y copia idéntica en el motor público.

| Regla | Período común | Anual robot / VT / 60-40 | Caída robot / VT / 60-40 |
|---|---|---|---|
| DBMF | may-2019–oct-2026 | 8.01 / 12.41 / 7.59 % | −22.15 / −34.31 / −22.80 % |
| KMLM | dic-2020–oct-2026 | 6.40 / 11.69 / 6.45 % | −32.55 / −26.87 / −22.80 % |
| CTA | mar-2022–oct-2026 | 7.46 / 13.71 / 7.94 % | −21.14 / −23.30 / −18.61 % |
| Dual Momentum | feb-2012–oct-2026 | 8.51 / 10.44 / 6.70 % | −33.82 / −34.31 / −22.80 % |
| Faber 10 meses | jun-2008–oct-2026 | 4.76 / 8.14 / 5.91 % | −12.96 / −50.36 / −31.52 % |
| Permanent Portfolio | jun-2008–oct-2026 | 6.24 / 8.14 / 5.91 % | −17.16 / −50.36 / −31.52 % |

Las seis rindieron menos que VT en sus propios períodos comunes. La menor
caída de Faber viene con menor retorno. No comparar valores finales de
fondos que empezaron en fechas distintas.

En 2022, DBMF: +18.92 %, correlación diaria con SPY −0.387; KMLM: +21.77 %,
correlación −0.329. SPY: −18.57 % en el año comparable. CTA: +7.53 % y
correlación −0.321, **solo desde marzo**; SPY −7.08 % en ese tramo. Esto
documenta diversificación observada en un período, no protección garantizada.
Dual Momentum −16.13 %, Faber −11.25 %, Permanent −12.47 % en 2022.

DBMF/KMLM/CTA no tienen ventanas de diez años. Dual tiene 57; Faber y
Permanent 101 sobre el intervalo común con VT. El JSON incluye retornos por
ventana, correlaciones de 2008/2020/2022 y media del robot en días en que
SPY cayó. Faltas de cobertura se muestran; no se fabrica un 2008 para ETFs
que nacieron después. La crisis usa toda la cobertura propia frente a SPY,
por lo que puede empezar antes que la comparación con VT.

Reglas y fuentes primarias revisadas:

- [DBMF](https://www.imgp.com/dbmf-etf/): exposición agregada de gestores de
  futuros mediante un ETF; no código de un bot nuestro.
- [KMLM](https://kfafunds.com/kmlm/): futuros sistemáticos.
- [CTA](https://www.simplify.us/etfs/cta-simplify-managed-futures-strategy-etf):
  futuros sistemáticos; su política puede cambiar con el tiempo.
- [Antonacci](https://www.optimalmomentum.com/faq/): revisión mensual;
  momentum absoluto de SPY contra letras (BIL), relativo SPY/VXUS; BND si
  falla el absoluto. Usamos índices netos y ETFs, no su índice GEM original.
- [Faber](https://mebfaber.com/timing-model/): 10 cierres mensuales; cinco
  partes de 20 % en SPY/TLT/GLD/VNQ/EFA, la parte fuera de tendencia va a BIL.
- [Permanent Portfolio](https://www.harrybrowne.org/PermanentPortfolio.htm):
  aproximación 25 % SPY/TLT/GLD/BIL con rebalanceo anual, distinta de bandas.
- [SG CTA](https://content.sgmarkets.com/CTA_UPDATE_KEEPING_UP_WITH_THE_TRENDFOLLOWERS_2025):
  se documenta, pero no se obtuvo una serie diaria gratuita verificable en
  esta corrida; no se sustituye con un ETF ni con rendimientos reconstruidos.

Señales después del cierre mensual completo y ejecución al **cierre de la
siguiente sesión**; no se compra al precio que generó la señal. Sin rellenar
huecos. Costos 0.1 % en cambios y primera compra; rebalanceo anual para
Permanent y 60/40 (VT/BND). Aportes iniciales de mes de US$50/100 con costos
dentro; aportar reparte dinero nuevo sin vender para rebalancear cada mes.
Retornos ponderados por tiempo, caída sin distorsión por aportes.

Gastos del ETF ya están reflejados en precios. Retención uniforme estimada
de 30 % sobre distribuciones de EE. UU., reinvertidas al exdividendo como
aproximación. El carácter fiscal de distribuciones de futuros puede diferir
y no fue verificado individualmente: **no son cifras personales netas de
todos los impuestos**. Fondeo, cambio, retiros e impuestos locales fuera.
Historia escogida en 2026, no evaluación causal ni cartera personal elegida.

Comando: `python -m lab.carteras --robots`. Motor: mismo código, salida
`resultados/carteras_robots.json`; workflow mensual y manual
`carteras-robots.yml`. No cambia rutinas, políticas ni ledgers existentes.
