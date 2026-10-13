# Diario de meses · tarea22

El diario compara nueve métodos sobre100 ETFs y BTC/ETH. No utiliza acciones individuales ni ejecuta operaciones. Los100 ETFs son fondos que existen hoy: eliminar acciones individuales **no elimina el sesgo de supervivencia de los ETFs**. Se usa cada serie desde su primera observación, sin inventar historia anterior ni completar huecos. Cripto es elegible desde2015, sujeto al calentamiento de300 cierres; ETH no existía al principio de2015.

Hay cuatro juegos: A pronostica de una vez los días restantes; B actualiza con el cierre anterior. Cada uno empieza en la primera sesión o en una sesión sorteada mediante una semilla fija que no consulta resultados futuros. El objetivo diario es cierre/cierre anterior, no retorno desde el inicio. En cripto se pronostican lunes–viernes; los fines de semana siguen disponibles como contexto. El rango final cripto incorpora la duración natural del período.

En A, momentum, tendencia, volatilidad y los clasificadores mantienen los rasgos deT; es una hipótesis de persistencia de rasgos, no un modelo entrenado distinto para cada distancia futura. Calendario conoce la fecha objetivo. En B las probabilidades usan rasgos disponibles antes de cada objetivo. Los rangosP10–P90 se fijan al inicio en ambos modos: remuestreo de bloques de cinco log-retornos pasados, con desplazamiento de deriva por la probabilidad del método. Son aproximaciones compartidas, no modelos independientes de colas por método ni precios garantizados. No contienen dividendos, costos o impuestos.

La moneda usa la frecuencia de subidas de los últimos1826 días naturales **disponibles**; un ETF joven puede tener menos de cinco años. Azar es una apuesta direccional independiente de0/1: su Brier castiga su confianza extrema; no debe interpretarse como una probabilidad calibrada de50%. Logística y boosting conservan los parámetros de21B (C=.1;30 árboles, profundidad2, hoja60, learning_rate=.05). Se ajustan al principio del año con etiquetas ya maduras, hasta2018 como máximo. Ausencia de modelo/rasgo vuelve explícitamente a moneda. El ensamble es el promedio fijo de momentum, tendencia, volatilidad, logística, boosting y calendario; no hay optimización de pesos ni selección por validación.

2006–2018 es diseño causal expansivo;2019–2023 comparación con coeficientes congelados;2024–septiembre2026 es **exploración de una reserva ya consumida en21**. La tarea22 no puede volver a crear una prueba final independiente sobre esos mismos años. No abre el archivo reservado del aprendiz2025–2026. No modifica cuentas, ledgers, políticas de bots ni rutinas existentes.

El núcleo recibe vistas copiadas del pasado. El compilador prepara rasgos causales y vectoriza las mañanas deB; las pruebas verifican igualdad con las llamadas de cada mañana y con prefijos separados. Envenenar todo el futuro no cambiaA; enB no cambia los pronósticos publicados antes del dato envenenado.

El ganador mensual se define por menor Brier, con desempate por orden registrado. Acierto y cobertura son descriptivos. El clima usaSPY: retorno mensual, proporción de subidas, volatilidad frente a la mediana **anterior** y posición respecto a diez cierres mensuales terminados. Crisis/pandemia son etiquetas retrospectivas de contexto, nunca entradas. El texto “por qué” es una plantilla numérica de asociaciones, no causalidad ni reflexión LLM.

La inferencia agrupa activos antes de remuestrear meses: no trata100 ETFs correlacionados como100 muestras independientes. Bootstrap circular de seis observaciones mensuales,9999 réplicas para diferencias y persistencia;1999 para regresiones simples. Los efectosFOMC solo tienen observaciones en meses con reuniones; sus bloques de seis observaciones pueden abarcar más de seis meses naturales. Se reporta persistencia frente a1/9 y, para evitar confundir dominancia de un método con habilidad, frente al azar ajustado a las frecuencias de ganadores. No se cambia el método por esos resultados. BH incluye todas las pruebas calculadas, la familia de búsqueda de21B y36 variantes del intento22 interrumpido antes de métricas. La resolución finita y el ajuste conservador limitan la potencia; no sobrevivir no prueba que el efecto sea exactamente cero.

Los precios proceden deYahooChart, con OHLC exclusivamente en caché ignorado. Son series retrospectivas que el proveedor puede corregir, sin archivo de vintages ni corroboración completa de todas las series. Primeras fuentesSPY/QQQ/VT reutilizan el caché público de21 y se cortan estrictamente en septiembre; las demás se descargaron hasta el mismo corte. Las fuentes/hash/cobertura y los huecos están en el resultado. Los resultados diarios públicos son retornos relativos y signos, sin nivelesOHLC.

## Calendario y publicaciones

Reglas predefinidas: día de la semana; último y tres primeros días del mes; víspera de feriadoXNYS; FOMC programado y sesión anterior; tercer viernes; cuarto miércoles; primer día; mayo–octubre y noviembre–abril. El calendarioXNYS y la lista oficialFOMC actual no garantizan el calendario publicado en cadaT. Se excluyen reuniones de emergencia; las reuniones que cruzan de mes usan su último día. Esta prueba diaria **no reproduce** la ventana intradía de la deriva preFOMC.

Los cortes son por año de publicación, no por día exacto; el diario empieza en2006 y deja explícito n=0 cuando no hay período anterior:

- [Ariel1987, A monthly effect in stock returns](https://www.sciencedirect.com/science/article/abs/pii/0304405X87900663): marzo1987. La regla último+3 es una adaptación, no réplica de su primera mitad del mes.
- Lakonishok y Smidt1988, Are Seasonal Anomalies Real? A Ninety-Year Perspective: cambio de mes; antes de1988 no hay observaciones de este diario.
- [McConnell y Xu2008, Equity Returns at the Turn of the Month](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1135217): corte2008, con2006–2007 antes.
- [Lucca y Moench2015](https://doi.org/10.1111/jofi.12196): corte2015; existen versiones de trabajo anteriores, por lo que “antes de2015” no implica que el efecto fuera desconocido.
- Efecto lunes: corte1980 deFrench, no atribuido erróneamente aBouman/Jacobsen.
- [Bouman y Jacobsen2002, Halloween/Sell in May](https://swlb2.aeaweb.org/articles?id=10.1257%2F000282802762024683): diciembre2002; no hay tramo anterior en2006–2026.
- [Lista oficialFOMC](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) y archivos anuales2003–2020: `datos/fomc_calendario22.json` conserva fuentes/hash y correcciones verificadas.

## Ejecución y publicación

`python -m lab.boveda_meses_ejecutar congelar` requiere código/pruebas comprometidos; crea un protocolo exclusivo. `python -m lab.boveda_meses_ejecutar ejecutar` verifica la firma, exige las102 fuentes y se niega a repetir un resultado ya publicado. Cuatro procesosCPU trabajan por activo; no hay agentes LLM. Publica `resultados/boveda_meses.json` y21 fragmentos anuales. La app los transmite por rutas fijas sin caché; no expone archivos arbitrarios.

El marcador personal conserva probabilidad y bloqueo por activo/día, también entre modos y recargas; un día se cuenta una sola vez. B permite apostar solo con la información de la mañana visible. Revelar todoB bloquea apuestas sobre mañanas que todavía no se vieron. El JSON contiene respuestas: es práctica educativa, no examen ciego ni evaluación estadística del usuario.

## Vita prospectiva

`agente/vita_meses_prompt_v1.txt` y `agente/vita_meses.json` congelan el prompt, modelo y diez ETFs. No hay backtestLLM. Google declara corte de conocimiento **enero2025** para [Gemini2.5Flash](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash), y actualmente restringe ese modelo a proyectos que ya lo usaban. No se cambia de modelo silenciosamente.

Workflow `vita-meses.yml`: lunes–viernes12:00UTC, antes de la apertura deNY, con nueva verificación siActions se demora. Una petición estándar en lote para10 ETFs, hasta1800 tokens de salida, sin herramientas, búsqueda, reintentos ni fallback pagado. La reserva del intento se publica **antes** de llamar y pertenece a un run/attempt: una reejecución deActions no consume otra cuota ese día. Ausencia de clave, cuota agotada, fuente incompleta, JSON inválido o respuesta tardía deja abstención.

La clave se configura porJose únicamente como secreto `GEMINI_API_KEY` **del motor**. La variable `VITA_MESES_FREE_TIER_CONFIRMED=true` se establece solo después de verificar el nivel/cuota del proyecto enAIStudio: una llamada pequeña no demuestra que una clave pertenezca al [nivel gratuito](https://ai.google.dev/gemini-api/docs/pricing). Codex no copió claves entre repositorios ni habilitó facturación. Por ahora el piloto queda preparado, con cero pronósticosLLM y cero etiquetas; no se presenta como activo.

El calificador exige forecast inmutable, commit anterior a apertura, recibo exitoso deActions también completado antes de apertura y cierres exactos maduros. Publica un marcador separado deVita y los nueve comparadores sobre los mismos diez activos/días. No crea resultados atrasados ni rellena huecos. `resultados/vita_meses.json` y `/api/vita-meses` alimentan la tarjeta. La comparación es descriptiva hasta reunir observaciones prospectivas suficientes; no demuestra ganancias.
