# Tarea21B: exámenes sorpresa y rondas

5 señales deEEM a60 días superan el bootstrap registrado, sobre33 preguntas y14 bloques; ninguna supera la sensibilidad adicional de signos por bloques tras ajustar por búsqueda. Son señales exploratorias en validación reutilizada, sin confirmación independiente. El campeón escogido en entrenamiento es **base_5a**. La habilidad primaria de validación pasó de **-0.09%** en ronda1 a **-0.09%** en ronda3; diferencia de **+0.00 puntos porcentuales**. Son probabilidades de retorno de precio, no ganancias de inversión ni dinero operado.

## Medición

Una única corrida completa, semilla**20261011**, con**1000 pares activo/fecha únicos** sorteados sin reposición desde2005 hasta2023. **3515 preguntas calificadas** entre30/60/90/1000 días naturales;**485** sin calificar. Horizonte: primera sesión desdeT+h; cripto días UTC. Se entregan probabilidad, retorno medio, P10–P90 del cierre y extremos high/low medios de trayectorias maduras; se revela después el cierre y los extremos reales. Clasificadores conservan los rangos/picos incondicionales; mezclas promedian cuantiles descriptivos. No son límites de la trayectoria ni garantías.

DiseñoV4 publicado antes de correr (V2:**617d107**, corregido antes de puntuaciones), firma**90b3b4f0c1b75f08958eaff963ec6e1d55a9ff67e9187ec10729a41f0f814fa7**. Recibo exclusivo anterior a descarga/sorteo, resultado por semilla/n y ganador exclusivos. El diseño previo se conserva sin ejecución: firma y resolución se ampliaron antes de medir. V2 se interrumpió tras400 preguntas antes de calcular/inspeccionar puntuaciones: se corrigió la referencia de caminata para impedir rangos inferiores a−100% a1000d y se vectorizó la forma60 con equivalencia byte por byte. Se conservó la misma semilla, diseños y recibos. No hubo selección por resultados de esa interrupción; se contabilizan un intento interrumpido y una corrida completa. El diseñoV3 se conservó sin ejecución; V4 incluye44 variantes previas en el ajuste conservador de88 variantes/versiones y119999 réplicas, definido antes de medir. Los reintentos de suites por permisos/sys.path/fixture no son experimentos de mercado.

Ajuste mensual solo con etiquetas maduras2005–2018; modelos y parámetros congelados al terminar2018. Selección por Brier OOS de entrenamiento en30/60/90;1000 días es diagnóstico separado. Ensamble ponderado por pérdidas OOS **ya maduras de entrenamiento**, nunca por validación. Ausencia de método se muestra como abstención; la política comparada usa explícitamente el ingenuo y reporta su disponibilidad. Regímenes por umbrales, boosting, señales entre activos, calendario/halving conocido, análogos y ensamble implementados. Curva de tasas/CAPE se abstienen sin vintages/publicación verificables.

## Rondas y activos

| Ronda | Elegido en entrenamiento | Campeón retenido por entrenamiento | Habilidad en validación | IC95 descriptivo de habilidad |
|---|---|---|---:|---|
| 1 | base_5a | base_5a | -0.09% | -1.64% a 1.50% |
| 2 | ponderado | base_5a | -0.09% | -1.64% a 1.50% |
| 3 | ponderado_mezcla25 | base_5a | -0.09% | -1.64% a 1.50% |

Parada: **2 rondas sin mejora mayor que IC**. **70 variantes intentadas**,**88 diseñadas**,**1014 contrastes calculados**; familia conservadora de**4584** que incluye variantes/celdas no abiertas y976 contrastes previos. Bootstrap119999 por bloques de calendario:180 días para habilidad primaria ymax(60,2h) por celda, activos remuestreados juntos. Menos de3 bloques: p=1, sinIC. Resolución mínima1/120000; Bonferroni de Brier como ajuste de búsqueda, sin inventar Sharpe de operaciones inexistentes. La parada es descriptiva, no confirmación de ventaja.

Habilidad del campeón en cada celda de validación; **estas cifras son descriptivas**:

| Activo | Horizonte (días) | Habilidad Brier | Pronósticos / preguntas | qBH | p ajustada por búsqueda |
|---|---:|---:|---:|---:|---:|
| BTC-USD | 30 | 0.00% | 42/42 | 1.0000 | 1.0000 |
| BTC-USD | 60 | 0.00% | 40/40 | 1.0000 | 1.0000 |
| BTC-USD | 90 | 0.00% | 37/37 | 1.0000 | 1.0000 |
| BTC-USD | 1000 | 0.00% | 20/20 | 1.0000 | 1.0000 |
| CSPX.L | 30 | 0.28% | 45/45 | 1.0000 | 1.0000 |
| CSPX.L | 60 | 0.28% | 45/45 | 1.0000 | 1.0000 |
| CSPX.L | 90 | 1.24% | 44/44 | 1.0000 | 1.0000 |
| CSPX.L | 1000 | 0.00% | 18/18 | 1.0000 | 1.0000 |
| EEM | 30 | -0.17% | 33/33 | 1.0000 | 1.0000 |
| EEM | 60 | 7.11% | 33/33 | 1.0000 | 1.0000 |
| EEM | 90 | 6.78% | 33/33 | 1.0000 | 1.0000 |
| EEM | 1000 | -11.26% | 14/14 | 1.0000 | 1.0000 |
| ETH-USD | 30 | 0.00% | 38/38 | 1.0000 | 1.0000 |
| ETH-USD | 60 | 0.00% | 38/38 | 1.0000 | 1.0000 |
| ETH-USD | 90 | 0.00% | 37/37 | 1.0000 | 1.0000 |
| GLD | 30 | -5.66% | 35/35 | 1.0000 | 1.0000 |
| GLD | 60 | -4.55% | 35/35 | 1.0000 | 1.0000 |
| GLD | 90 | -13.38% | 35/35 | 1.0000 | 1.0000 |
| GLD | 1000 | -14.69% | 11/11 | 1.0000 | 1.0000 |
| MTUM | 30 | 1.11% | 42/42 | 1.0000 | 1.0000 |
| MTUM | 60 | 1.00% | 42/42 | 1.0000 | 1.0000 |
| MTUM | 90 | 2.39% | 41/41 | 1.0000 | 1.0000 |
| MTUM | 1000 | 0.00% | 24/24 | 1.0000 | 1.0000 |
| QQQ | 30 | 2.36% | 36/36 | 1.0000 | 1.0000 |
| QQQ | 60 | 5.76% | 34/34 | 1.0000 | 1.0000 |
| QQQ | 90 | -1.78% | 34/34 | 1.0000 | 1.0000 |
| QQQ | 1000 | 100.00% | 18/18 | 1.0000 | 1.0000 |
| SPY | 30 | 0.00% | 27/27 | 1.0000 | 1.0000 |
| SPY | 60 | -1.89% | 27/27 | 1.0000 | 1.0000 |
| SPY | 90 | 11.36% | 27/27 | 1.0000 | 1.0000 |
| SPY | 1000 | 100.00% | 13/13 | 1.0000 | 1.0000 |
| TLT | 30 | -1.33% | 39/39 | 1.0000 | 1.0000 |
| TLT | 60 | -1.98% | 39/39 | 1.0000 | 1.0000 |
| TLT | 90 | -8.83% | 39/39 | 1.0000 | 1.0000 |
| TLT | 1000 | 39.09% | 21/21 | 1.0000 | 1.0000 |
| VT | 30 | -0.15% | 36/36 | 1.0000 | 1.0000 |
| VT | 60 | 1.11% | 35/35 | 1.0000 | 1.0000 |
| VT | 90 | 1.01% | 35/35 | 1.0000 | 1.0000 |
| VT | 1000 | -2.80% | 16/16 | 1.0000 | 1.0000 |

Señales que pasan el bootstrap original; contraste de sensibilidad **posterior, no preregistrado**:

| Método (EEM60 días) | Habilidad Brier | p bootstrap registrado | p signos por bloques | p sensibilidad ajustada |
|---|---:|---:|---:|---:|
| volatilidad | 9.00% | 0.00000833 | 0.014832 | 1.000 |
| estacionalidad | 16.21% | 0.00000833 | 0.005737 | 1.000 |
| ponderado | 6.80% | 0.00000833 | 0.009583 | 1.000 |
| estacionalidad_mezcla25 | 4.49% | 0.00000833 | 0.003662 | 1.000 |
| ponderado_mezcla25 | 1.76% | 0.00000833 | 0.009338 | 1.000 |

Se contabilizan **5 contrastes adicionales**, familia conservadora de**4589**. Se enumeran los16,384 cambios de signos de14 bloques: no se recalculan predicciones, no se cambia el campeón ni se sobrescribe el protocolo original. Este contraste supone simetría/independencia entre bloques y es una sensibilidad, no una evaluación nueva. Su desacuerdo con el bootstrap y la muestra pequeña impiden presentar EEM60 como ventaja robusta. Las119,999 réplicas no equivalen a119,999 observaciones independientes. La señal más fuerte, calendario+16.21% de habilidad, **no es+16.21% de rentabilidad**. Precisión con pocos grupos: [Cameron/Gelbach/Miller](https://www.nber.org/papers/t0344), [guía Cameron/Miller](https://cameron.econ.ucdavis.edu/research/Cameron_Miller_JHR_2015.pdf).

## Reserva y límites

**La reserva2024–2026 ya se abrió en tarea21. No se reabrió en21B.** La validación2019–2023 también se vio en21: estas rondas son desarrollo retrospectivo sobre validación reutilizada, no evidencia independiente nueva. El ganador quedó congelado para una futura prueba prospectiva desde publicación; esa evaluación nueva no se programó como bot ni se presentó como realizada. Una segunda apertura histórica no recuperaría independencia.

Hashes de reserva inicial, recibo de apertura y protocoloV2 iguales antes/después: **True**. Se conservó el núcleo original: solo despacho CLI agregado bajo`__main__`; el adaptador semanal comprueba la misma firmaV2 retirando exclusivamente ese sufijo. No cambian horarios, reglas ni predictores21. La reserva del aprendiz no se leyó. No se modificaron bots, políticas, ledgers ni presupuesto personal.

15 fuentes Yahoo públicas independientes hasta2023;**0 fallas**. Retrospectivas, con posibles revisiones/splits; no son vintages completos. Universo deETF actuales predefinido, con sesgo de selección/supervivencia; no se inventa historia de activos jóvenes. Sin dividendos, costos, impuestos ni rentabilidad negociable. Se conserva la corroboración parcial21 de cripto; no se atribuye una segunda fuente a toda esta historia ni a los extremos nuevos. Muestreo al azar no elimina dependencia entre activos, horizontes solapados o las decisiones de diseño anteriores.

## App y validación

Aprender→Marcador→Bóveda: **Examen sorpresa**, gráfico con60 cierres conocidos hastaT, pronósticos y apuestas probabilísticas propias antes de revelar. Animación y movimiento reducido; ejes calculados solo con pasado y parte ya revelada. Brier local contra cada método en las mismas preguntas, apuestas bloqueadas incluso tras recargar, preguntas repetidas no duplican el marcador. Sin datos personales ni envío de apuestas. El futuro viene enJSON: ejercicio educativo, no examen ciego. Banco:3515 casos, índice y39 fragmentos por activo/horizonte; ningunaOHLC absoluta. API protegida,no-store,stream y lista fija; memoria de3 fragmentos. Serviceworkerv80.

Pruebas completas: **149Python motor,245Python app con PyTorchCPU,170Node**, más23 focalizadas en entorno numérico fijado. Futuro×10/NaN byte idéntico en4 horizontes y todos los métodos disponibles; publicación/prefijos, madurez, congelación2018, pesos OOS, sorteo sin duplicados, huecos, extremos, reserva y recibos exclusivos. Empaque conserva todas las preguntas exactamente; auditoría exacta probada en fixture y original inmutable. QA real del banco a375/1280px, ocultar/revelar, marcador persistente, no duplicar, apuestas bloqueadas al recargar,1000 días y animación sin desbordamiento ni errores. Evidencia en`repo app:docs/qa/tarea21b/`.

Método y protocolo detallados: [motor público](https://github.com/recinosr/wall-street-motor/blob/main/docs/boveda_examen.md), [GradientBoostingClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.GradientBoostingClassifier.html), [validación cronológica](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html).


Cierre publicado: motor **efcaaa2**, código/app **589e4f27**. [Despliegue correcto](https://github.com/recinosr/proyecto-wall-street/actions/runs/38082793085); HTTP200 de index, ambos módulos y serviceworkerv80, contenido idéntico a publicado. API anónima401/no-store; sesión autenticada probada enQA local/unitarias, sin usar clave personal en producción. [Compatibilidad semanal en nube correcta](https://github.com/recinosr/wall-street-motor/actions/runs/38082953346):23 pruebas de bóveda más auditoría, adaptador firmado y publicación terminan correctamente; horarios intactos. Banco3515 casos/39 fragmentos disponible en motor. Los tres hashes remotos de reserva/apertura/protocolo siguen idénticos. Evidencia en `docs/qa/tarea21b/publicacion.json` y `despliegue.json`.
