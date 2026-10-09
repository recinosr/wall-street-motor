# Tarea 14, punto 1

Vita usa frases deterministas del diario, primera persona y ejemplos sin inventar
mediciones semanales. Distingue 0 patrones que cumplen todos los criterios de
los contrastes individuales significativos. No cambia políticas ni ledgers.

Contexto resumido en caché del Worker por 600 segundos, historial acotado y
universo completo solo ante una ficha identificada por índice de nombres.
Cada cerebro tiene límite de 12 segundos. Fallos sanitizados quedan en logs y
`respaldos`; `/api/vita/estado` prueba en paralelo los cerebros configurados,
con candado y reserva del límite diario. Ajustes → Laboratorio incluye el botón.

El Worker consulta `models` con la clave en cabecera, comprueba `generateContent`
y sustituye un modelo inexistente por Flash disponible. El modelo por defecto
figura en la [documentación oficial de Gemini](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash).
La meta de 6 segundos requiere medir el servicio publicado; no es una promesa.
Workflow manual `vita-estado.yml`: una consulta protegida, sin mostrar secretos.

Pruebas dirigidas: 11 Node de Vita y 3 Python del diario, correctas.
