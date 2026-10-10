# Vita: diagn?stico del 9-oct-2026

Tres llamadas reales de humo, una por variante; ninguna conversaci?n larga.

| Variante | Gemini | models | generateContent | Cloudflare |
|---|---|---|---|---|
| 3.8 Flash, low, salida700 | HTTP200 /4927ms | sin separaci?n | sin separaci?n |367ms |
| mismo modelo, etapas/cach?24h | timeout12000ms | HTTP200/113ms | sin HTTP/timeout |467ms |
| 3.5 Flash-Lite, minimal, salida700 | HTTP200/567ms | HTTP200/95ms | HTTP200/472ms |656ms |

El bloqueo observado est? en generaci?n, no en lista. No se puede atribuir
una causa interna al proveedor ni asegurar continuidad con un humo.
Flash-Lite queda primero; Cloudflare respaldo. Groq sin configurar.
Lista en cach?24h por entorno/fetcher; no persiste entre isolates.

Fuentes: [niveles oficiales](https://ai.google.dev/gemini-api/docs/generate-content/thinking),
[Flash-Lite vigente](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite).
Evidencias: [primero](qa/tarea15/thinking.json), [etapas](qa/tarea15/stages.json),
[Lite](qa/tarea15/lite.json). La instrumentaci?n se adelant? a Lite para identificar
la etapa; el primer ?xito seguido de timeout oblig? a continuar el punto1.
