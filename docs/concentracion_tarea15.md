# Concentrar o diversificar — tarea15

Una corrida nueva: 144,036 recorridos intentados en108 celdas; 2,000 por celda aleatoria,36 recorridos de momentum. Semilla20261009. 498 acciones descargadas,5 fallas, más SPY/VOO. Seis inicios(2000,2003,2006,2009,2012,2015),5/10años; corte exclusivo1abr2025. Datos públicos nuevos en memoria; solo métricas publicadas.

US$100 ficticios/mes,60/120aportes y liquidación en aniversario. $0.15/orden y0.1% por lado dentro del aporte. No cambia presupuesto personal50–100 ni ninguna cuenta. Dividendos brutos aproximados; faltan retenci?n y costos de fondeo/cambio.

**No demuestra que elegir acciones venza un ETF.** Se eligen miembros actuales: empresas desaparecidas faltan. En2000, sobrevivientes seleccionados en2026 pueden dominar al índice por ese sesgo. Las ausencias futuras invalidan recorridos, sin reemplazos retrospectivos; se publica cada exclusión.

Ejemplo2000→2010, $12,000 aportados; SPY como proxy de VOO aún inexistente:

| Acciones |P10 USD|Mediana USD|P90 USD|Vence SPY|Pierde aportes|×5|
|---|---:|---:|---:|---:|---:|---:|
|1|10751.72|18014.81|30325.21|80.10|14.90|1.95|
|3|13539.96|18883.33|29719.09|93.20|4.00|1.45|
|5|14922.07|19726.30|30344.32|97.55|1.05|1.95|
|10|16149.36|19826.42|27692.43|99.70|0.15|0.55|
|20|17005.84|20014.16|26050.45|100.00|0.00|0.00|
|50|17320.00|19466.28|25283.92|100.00|0.00|0.00|

Momentum12 anual usa12 meses terminados en el precio del mes anterior; ejecuta en fecha posterior y liquida/recompra anualmente. No mira rendimientos futuros para elegir. Su universo superviviente impide considerarlo evaluación causal limpia. El resumen entre seis ventanas muestra ratios sobre todos los aportes, y no confunde una trayectoria con miles de carteras aleatorias.

×5 = valor final >=5 veces TODOS los aportes, no retorno anual ni promesa. Bandas P10–P90 excluyen20% de resultados, no son límites.

Bessembinder(2018) encontr? que la mayoría de acciones de EEUU rindió menos que letras del Tesoro durante su vida y aproximadamente4% explica la creación neta de riqueza. No repetimos ese estudio: no tenemos bajas hist?ricas ni comparaci?n con letras. [Fuente acad?mica original](https://asu.elsevierpure.com/en/publications/do-stocks-outperform-treasury-bills/).

Yahoo Chart ajustado bruto, sin segunda fuente completa: la pantalla es exploratoria, no resultados corroborados de500activos. Ventanas y sorteos se solapan;108 comparaciones descriptivas,0tests de hipótesis/BH; no se escogió umbral tras ver ganancias.

C?digo motor: `python -m lab.concentracion`; workflow manual `concentracion.yml` para repetir. API `/api/concentracion`; tarjeta Aprender→Carteras. No cambia cron existente, pesos ni ledgers.
