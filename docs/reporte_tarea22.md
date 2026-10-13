# Tarea22 · diario de meses

Instalado en **Aprender → Marcador**: elegir mes/activo, pronosticar todo el mes o día a día, inicio primero o al azar, apuesta personal fija, revelar, calificar, explicar y explorar calendario de calor/persistencia. Examen sorpresa añade “Mes completo”.

**102 fuentes completas, 100 ETFs y BTC/ETH; 249 meses, enero de 2006–septiembre de 2026; 13,694,868 probabilidades diarias**. Se solapan activos/días/modos: no son 13.7 millones de pruebas independientes. En enero de 2006 eran elegibles 75 activos; los demás entran cuando tienen historia suficiente. La fuente de ETH comienza el 9 de noviembre de 2017: no cubre 2015–2017; sus juegos comienzan en enero de 2019 tras el calentamiento y ajuste anual. Los juegos de BTC comienzan en enero de 2016. No se inventó cobertura anterior. Ningún OHLC público; 21 fragmentos anuales. Transporte gzip: 200.1 MB a 20.7 MB, sin modificar cifras.

## Tres meses más fáciles y tres más difíciles

“Fácil” significa mayor acierto de la **moneda en A con inicio primero**, sobre el universo disponible; no se seleccionó el mejor método para definir facilidad. El ganador sí se elige por menor Brier. Esta selección de extremos es retrospectiva y descriptiva.

| Mes | Acierto moneda | Ganador por Brier | SPY: retorno / días de subida | Volatilidad vs mediana previa |
|---|---:|---|---:|---:|
| 2014-02 | 67.6% | boosting | 4.6% / 73.7% | 0.93 veces |
| 2019-01 | 63.7% | calendario | 8.0% / 76.2% | 1.50 veces |
| 2023-12 | 63.1% | calendario | 4.1% / 70.0% | 0.75 veces |

| Mes | Acierto moneda | Ganador por Brier | SPY: retorno / días de subida | Volatilidad vs mediana previa |
|---|---:|---|---:|---:|
| 2010-05 | 37.9% | volatilidad | -7.9% / 35.0% | 2.38 veces |
| 2012-05 | 38.0% | momentum | -6.0% / 36.4% | 0.93 veces |
| 2008-10 | 38.5% | moneda | -16.5% / 34.8% | 7.54 veces |

Los fáciles favorecieron el sesgo de subida: en SPY hubo más días positivos que negativos. Los difíciles castigaron ese sesgo. Mayo de 2010 y octubre de 2008 tuvieron mucha más volatilidad; mayo de 2012 tuvo muchos días de caída sin superar la mediana previa de volatilidad. Ganar el Brier no exige ganar el acierto: octubre de 2008 lo ganó la moneda pese a acertar menos del 40 % en el universo. Las explicaciones mensuales usan plantillas y números; describen asociaciones, no causas ni razonamiento de un LLM.

## ¿Suerte o habilidad?

**No hay persistencia demostrada.** En 2019–2023, A/primero repite ganador 20.3%; azar por frecuencias 21.6%, referencia uniforme de 11.1 %. q BH=1.00. Los otros modos tampoco pasan el ajuste. Comparar únicamente con 1/9 confundiría la dominancia de ciertos métodos con habilidad.

**Ningún efecto de calendario sobrevive BH; ningún método muestra mejora Brier ajustada contra moneda.** Se calcularon 587 contrastes nuevos; familia conservadora de 5,207, incluida búsqueda de 21B y 36 variantes del intento22 interrumpido antes de métricas. No significante no significa efecto exactamente cero. Hay histogramas mensuales, regresiones de clima con intervalos y cortes por año de publicación; los tramos anteriores a publicaciones anteriores a 2006 quedan con n=0.

## Límites y entrega

2024–2026 ya se abrió en 21: se muestra como exploración, **sin otra prueba final independiente**. No se abrió el archivo reservado del aprendiz ni se cambiaron bots, ledgers o rutinas existentes. ETFs supervivientes y precios retrospectivos conservan sesgos; calendario FOMC sin vintage verificable. A congela rasgos diarios, los rangos son aproximados y azar es apuesta direccional 0/1, sin calibración. Las definiciones completas y fuentes están en [diario_meses.md](https://github.com/recinosr/wall-street-motor/blob/main/docs/diario_meses.md).

Vita/Gemini quedó **preparado**, sin backtest ni llamadas: diez ETFs, prompt/modelo versionados, reserva publicada antes de consumir cuota, máximo una llamada por día, recibo anterior a apertura y etiquetas maduras. Marcador separado junto a los nueve controles, actualmente n=0. Para activarlo falta la clave del motor y confirmar el nivel gratuito en AI Studio; no se copiaron secretos ni se habilitó facturación. Google declara enero de 2025 como corte de Gemini 2.5 Flash y restringe acceso a proyectos que ya lo usaban; no hay fallback silencioso.

Verificación: suites completas una vez, **245 Python app con PyTorch CPU,165 Python motor,173 Node** correctas. Después,7 pruebas focales deVita (incluido recibo tardío) y 3 de transporte/meses correctas. Futuro envenenado, igualdad deB con mañanas individuales, huecos, apuestas irreversibles y deduplicación comprobados. QA real a 375/1280 px, sin errores de JavaScript ni desbordamiento; [evidencia](qa/tarea22/interaccion.json).
