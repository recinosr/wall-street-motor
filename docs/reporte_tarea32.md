# Tarea 32: resultados

## Bloque 1 — datos point-in-time (parcial, versión inicial)

- `lab/oraculo_pit.py` agrega filtro estricto por instante UTC `available_at`, caché de contenido con escritura atómica y lectores para Yahoo, EDGAR y GDELT.
- Yahoo conserva OHLC sin ajustar como base causal y etiqueta disponibilidad al cierre de Nueva York. Los cierres ajustados pueden cambiar retroactivamente y no se usan como dato histórico PIT estricto.
- EDGAR expone `acceptanceDateTime` para el bloque `recent`; el endpoint actual no cubre por sí solo todos los años desde los 90.
- GDELT conserva `seendate` como hora en que GDELT indexó el artículo (no siempre la publicación original), usa esa hora como disponibilidad conservadora y cachea por consulta. Su consulta no reconstruye todo el universo histórico y requiere paginar para ampliar cobertura.
- FOMC y CPI quedan explícitamente pendientes de un archivo de revisiones/publicaciones verificable. El lector no convierte la fecha del evento o del período mensual en fecha de disponibilidad.
- Verificación: 6 pruebas unitarias del filtro temporal, fechas de publicación FOMC/CPI (fixtures), rechazo de fechas sin zona/CIK inválido y bloqueo de reapertura; pasan. La descarga directa de fuentes falló por red bloqueada en este entorno (`WinError 10061`), así que no se pobló la caché ni se congeló corpus.
- Límite importante: Yahoo actual no ofrece vintages de cierres ni correcciones; la hora de cierre se aproxima a 16:00 ET y el OHLC puede reflejar ajustes de splits. Los ensayos siguientes son retrospectivos con precios actuales, no evidencia PIT completa.

## Bloque 2 — niveles 1–3

Ventana retrospectiva: 2025-10-08 a 2026-10-08; se abrió dos veces para cada uno de los niveles 1 y 2. La segunda ejecución corrigió la longitud del bootstrap después de ver la primera salida. Esto compromete ambas pruebas reservadas: todos los resultados son exploratorios y no pueden aprobar niveles. El registro muestra 2 aperturas por nivel y el script bloquea una tercera ejecución en la misma versión. Entrenamiento hasta 2024-10-07; validación 2024-10-08 a 2025-10-07. Activos disponibles de `datos/cache/y_*_1d.csv`, cierre actual de Yahoo; el manifiesto SHA-256 está en `web/nivel.json`. Yahoo no ofrece vintage de cierres ni historial de correcciones, así que no es PIT estricto. Sin dividendos. El conjunto local contiene 10 símbolos seleccionados, no un universo libre de sesgo de supervivencia. Regresión logística fija sobre momentum de cinco sesiones. Comparación de Brier contra tasa alcista de entrenamiento; bootstrap circular con bloques max(10, 2 × horizonte). Nivel 2 cuenta 30 comparaciones por corrida (60 análisis nominales al incluir las dos aperturas), con ajuste Benjamini–Hochberg en cada corrida. La pantalla muestra el mejor resultado y los detalles.

| Nivel | Resultado medido | Estado |
|---|---|---|
| 1 — SPY, dirección a 1 sesión | n=251; Brier modelo 0.25012 vs base 0.24956; mejora −0.00056 (IC95 de mejora −0.00140 a 0.00033; p=0.903). | No aprobado; 2 aperturas, exploratorio |
| 2 — 10 activos, 1/5/21 sesiones | 30 comparaciones por corrida. Mejor q ajustado=0.05498: Visa a 1 sesión mejora Brier 0.00191 (IC95 0.00059 a 0.00336; p=0.0030). Ninguna supera q<0.05; 2 aperturas invalidan lectura confirmatoria. | No aprobado; exploratorio |
| 3 — FOMC, CPI y resultados | Sin ensayo. El entorno bloqueó la descarga del calendario FOMC/BLS y EDGAR, por lo que no hay eventos cacheados que unir. La rama `origin/datos` sí tiene velas SPY de 1 minuto desde 2021-10 hasta 2026-10. | Sin evaluación |

Nivel actual: 1; no hay métodos sobrevivientes. Los CSV usados están en caché ignorada localmente y no se versionan; por ello la ejecución solo se reproduce si están presentes los ficheros con los hashes del manifiesto. La práctica histórica previa del agente pudo observar estos años. No presentar estos números como evaluación causal limpia de su aprendizaje ni como aprobación.

## Pantalla Nivel

Agregada a Oráculo → «Nivel y currículo». Muestra nivel actual, aprobados, valores Brier, mejor comparación nivel 2, ajuste por pruebas múltiples y explicación honesta. Solo hay una versión medida; por eso no hay una curva longitudinal entre versiones todavía.

## Bloque 4 — niveles 4–7

Pruebas reservadas sin abrir (0 aperturas). Se registran sin evaluación porque faltan entradas necesarias:

- Nivel 4: GDELT entrega hora de indexación, no siempre publicación original; falta corpus histórico clasificado y congelado.
- Nivel 5: faltan vintages de precios PIT y un detector fijado antes de reservar crisis completas de 2000–02, 2008, 2020 y 2022.
- Nivel 6: falta panel PIT común y sincronizado de tasas, dólar, oro y tecnología.
- Nivel 7: falta simulación completa de dividendos, conversión, spread, tarifas XTB y benchmark de aportes con una misma prueba.

No hay ventaja sobreviviente ni niveles aprobados. La pantalla muestra la razón por nivel y evita asignar un resultado numérico donde no hubo ensayo.

## Verificación de cierre

- Python acotado de Tarea 32: 6/6 pruebas pasan. `exchange_calendars` 4.13.2 ya estaba instalado.
- Node: 194/194 pruebas de Worker, Web y Android pasan.
- `python -m unittest discover -s tests` no terminó en el runner tras varios minutos y no produjo resumen final; no se declara verde la suite Python completa.
