# Vita: diagnóstico del 9-oct-2026

Gemini 3.8 Flash admite como mínimo `low`, ya usado. Se redujo la salida
a 700 tokens. Una llamada real protegida: HTTP 200, 4,927 ms; Cloudflare
367 ms. Groq sin configurar. No se prueba Flash-Lite ni se cambia la prioridad
porque el primer humo funcionó. El timeout anterior no permite atribuir causa.

Estado ahora distingue `models` y `generateContent`; lista en caché 24 horas
por entorno/fetcher, sin secretos como claves de caché. No garantiza persistencia
entre isolates ni continuidad del servicio. Humo mínimo, no conversación larga.

Fuente: [niveles oficiales](https://ai.google.dev/gemini-api/docs/generate-content/thinking).
Evidencia: [humo](qa/tarea15/thinking.json).
