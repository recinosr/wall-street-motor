# ICT y barridos de liquidez — tarea 15

Se añadieron diez reglas operativas a la enciclopedia: barridos alcistas/bajistas con recuperación el mismo día o el siguiente, brechas de valor justo de tres velas, bloques de órdenes y rupturas de estructura. Ninguna mostró ventaja neta estable entre los dos períodos contra ambos controles. Esto no prueba efecto cero ni valida las afirmaciones del video.

## Método y cobertura

- Diario: descarga pública nueva de Yahoo Chart desde 2000 hasta el 31-mar-2025; 498 acciones del S&P actual más BTC y ETH válidos, cinco símbolos fallidos explícitos. Corte de comparación 2016. No se abrió el archivo reservado.
- Horario: Coinbase BTC/ETH, año 2024 completo, 8,784 velas por activo, sin huecos ni relleno; corte 1-jul-2024. Aquí N=20 velas significa 20 horas, no 20 días.
- Todas las señales usan únicamente velas ya conocidas; entrada en apertura posterior. Los barridos del día siguiente requieren confirmación posterior y no permiten anticiparla. La brecha compara t con t−2. El bloque usa una vela contraria previa y un impulso de 1.5 ATR previo; estructura exige cruce inicial del extremo previo con margen 0.5%. Son definiciones reproducibles propias, no una definición universal de ICT.
- Siete salidas por regla, costo 0.1% por lado, controles de compra/mantener y entradas aleatorias del mismo activo; bootstrap por bloques de 20 fechas con eventos. Las ventas hipotéticas no incluyen préstamo de acciones.
- Se conservaron los valores p de las 75 reglas previas y se recalculó BH global incluyendo diario y horario: 11,550 contrastes, 2,100 nuevos. Los snapshots previos y nuevos tienen fechas diferentes.

## Resultado y número de intentos

163 contrastes individuales del conjunto completo pasan BH. Entre las reglas ICT, 60 contrastes individuales pasan BH y seis combinaciones activo/período pasan ambos controles; ninguna regla ICT reúne beneficio neto, ambos controles y estabilidad en ambos períodos. No confundir un hallazgo aislado con una estrategia estable.

Hubo una corrida completa y una parcial interrumpida tras 37 activos completos para adaptar el corte temporal horario: 2,590 mediciones regla/salida en esa parcial, descartadas del resultado final. No se cambiaron umbrales tras ver ganancias. Diez reglas, siete salidas y todos los contrastes nuevos entran en la corrección; no se seleccionó solo el ganador.

La lista actual del S&P tiene sesgo de supervivencia. Yahoo ajustado no recibió corroboración independiente completa de los 500 activos. Costos, impuestos y ejecución real incompletos: estudio exploratorio, sin recomendación personal ni dinero real.

## Qué significa lo de los mínimos

La explicación habitual se refiere a stops de venta colocados debajo de mínimos: al activarse pueden convertirse en órdenes de mercado. Una orden limitada de compra es distinta. Las velas OHLC no muestran cuántos stops hay, quién los colocó ni si una institución causó el movimiento; por eso no afirmamos haber medido esa acumulación ni “dinero inteligente”. [Investor.gov: tipos de órdenes](https://www.investor.gov/introduction-investing/investing-basics/how-stock-markets-work/types-orders).

[Coinbase: velas históricas](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles) permite granularidad de 3,600 segundos y hasta 300 velas por petición; advierte que la serie puede ser incompleta. Se paginó y comprobó continuidad en este año concreto.

## Uso

`python -m lab.ict` reproduce diario + horario y publica solo métricas. El workflow existente de enciclopedia ejecuta `python -m lab.ict --hourly-only` después de reconstruir el diario para preservar la extensión horaria sin una segunda descarga diaria completa; no se añadieron horarios programados. La web ofrece BTC/ETH de una hora, fechas claras y diagramas de las reglas. No modifica bots, modelos, políticas ni ledgers.
