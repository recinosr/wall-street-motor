# vita_local: modelo local sin cuota (3-nov-2026)

Para que los **exámenes y jueces** de Vita no gasten la cuota gratis de Gemini que usa Vita para contestarle a Jose.

- Workflow: `.github/workflows/vita-local.yml` (a mano). Instala Ollama, baja `qwen2.5:7b-instruct` (≈4.7 GB, Q4) y lo corre en la CPU del runner. Este repo es público, así que los minutos de Actions no tienen límite.
- Tareas: `prueba` (2 casos integrados para ver que funciona), `parafrasis` (3 versiones tipo chat de cada pregunta) y `juez` (CORRECTA/PARCIAL/INCORRECTA con criterios y errores graves).
- Entrada: un JSON en `vita_local/entrada/` (lista de hasta 200). Para `parafrasis`: `[{"id","pregunta"}]`. Para `juez`: `[{"id","pregunta","respuesta","criterios_obligatorios","errores_graves"}]`.
- Salida: `vita_local/salida/<tarea>-<fecha>.json`, con el modelo y los segundos por caso.

**Reglas:** solo preguntas públicas o escritas a mano. Nada del examen oculto, nada de la validación sellada, ningún secreto. Un modelo de 7B en CPU es lento (decenas de segundos por caso) y juzga peor que uno grande: úsalo como respaldo o para generar paráfrasis, y compara su acuerdo con el juez principal (GitHub Models) antes de confiar en él.

El proyecto principal lo usa desde `scripts/llm.mjs` (proveedor `ollama`, variable `OLLAMA_URL`).
