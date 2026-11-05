# vita_local: modelo local sin cuota (3-nov-2026; ciclo horario desde el 5-nov-2026)

Para que la **práctica, los exámenes y los jueces** de Vita no gasten la cuota gratis de Gemini (que queda para contestarle a Jose) ni los minutos del repo privado.

- Workflow: `.github/workflows/vita-local.yml`. **Cada hora (minuto 23)** corre `vita_local/ciclo.mjs`; a mano se puede elegir otra tarea. Instala Ollama, baja `qwen2.5:7b-instruct` (≈4.7 GB, Q4, en caché) y lo corre en la CPU del runner. Este repo es público, así que los minutos de Actions no tienen límite.
- **Ciclo horario** (`ciclo.mjs`, hasta 40 min):
  1. **Juez**: casos en `entrada/juzgar/*.json` sin veredicto → `resultados/vita_local/juez/<archivo>`. Mismo criterio que el juez v4 del examen fresco del repo privado, un caso por llamada.
  2. **Examinador**: 6 grupos nuevos (la misma duda en forma formal, informal e indirecta) a partir de `entrada/hechos_publicos.json` → `resultados/vita_local/examen_pool.json`. La clave (cita y dato) se copia del hecho, no la inventa el modelo; el repo privado vuelve a verificarla contra su fuente y descarta lo que Vita ya vio.
  3. **Paráfrasis**: hasta 80 preguntas de `entrada/publicas.json` por ciclo, en orden rotativo, 3 versiones cada una → `resultados/vita_local/parafrasis/AAAA-MM-DD.jsonl` y la ventana `resultados/vita_local/practica.json` (últimas 1,500). `revisar: true` marca paráfrasis que meten una cifra o sigla que no estaba en la original.
  4. Una línea por ciclo en `resultados/vita_local/ciclos.jsonl`; diagnóstico de GitHub Models en `resultados/vita_local/github_models.json`.
- Tareas a mano: `prueba`, `parafrasis`, `juez` (criterios libres) y `juez-examen` (criterio del examen fresco).
- Entradas: `publicas.json` y `hechos_publicos.json` las genera el repo privado (`scripts/paquete_motor_vita.mjs`). `publicas.json` trae solo entrenamiento/desarrollo: realista_v3 sin validación, prueba congelada v2 sin su 20 % de prueba y reglas_trampas sin validación.
- **Estado 5-nov-2026:** el código y el horario están instalados, pero las entradas (`publicas.json`, `hechos_publicos.json`, `juzgar/`) **todavía no se copiaron**: salen del repo privado y copiarlas a este repo público necesita la autorización explícita de Jose. Sin entradas el ciclo solo corre el diagnóstico de GitHub Models y no instala Ollama.
- Comunicación: el repo privado lee `resultados/vita_local/*` por `raw.githubusercontent.com`. Este repo no puede leer el privado.

**Reglas:** solo preguntas públicas o escritas a mano. Nada del examen oculto, nada de validación, ningún secreto. Un modelo de 7B en CPU es lento (decenas de segundos por caso) y juzga peor que uno grande: su acuerdo con el juez Gemini se mide en `entrada/juzgar/acuerdo_juez_30.json` antes de confiar en él.

El proyecto principal también lo puede usar desde `scripts/llm.mjs` (proveedor `ollama`, variable `OLLAMA_URL`).
