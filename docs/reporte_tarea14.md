# Tarea 14 — 9 de octubre de 2026

Ejecutada **1 → 2 → 3**, con pull/rebase, commit y push por punto en ambos repos.

| Punto | Privado | Motor público |
|---|---|---|
| 1. Vita | `1bd79bdf` | `45955c4` |
| 2. Comprar/Vender | `c383204e` | `c16c895` |
| 3. Calma visual | `49a1fc21` | `fbeef3c` |

- **Vita:** diario con frases deterministas y fechas; prompt en primera persona,
  ejemplos y prohibiciones; contexto en caché 10 minutos e historial acotado;
  universo completo solo al identificar una ficha. Timeout 12 s, fallos
  sanitizados en `respaldos` y Workers Logs. Botón Estado de Vita en Laboratorio.
  El Worker consulta `models` con la clave en cabecera y sustituye modelos
  inexistentes por Flash disponible. [Modelo oficial](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash),
  [persistencia de logs](https://developers.cloudflare.com/workers/observability/logs/workers-logs/).
- **Práctica:** cualquier activo de Mercado usa la misma cuenta local de
  US$1,000 de Simular. Precio fechado independiente del rango; botones bloqueados
  sin cotización. Todas las posiciones visibles, con precios guardados explícitos.
- **Pantallas:** inicio en Resumen, reporte exclusivo allí, tarjetas tocables,
  Portafolio con tres opciones; Este año/Trading en Laboratorio, Carteras en
  Aprender. Resumen sencillo y detalle técnico plegable; buscador y orden a 375 px.

## Única prueba real de `/api/vita/estado`

[Corrida correcta](https://github.com/recinosr/proyecto-wall-street/actions/runs/37975757098),
9-oct-2026, 12:48:06 GT. Una consulta protegida desde Actions al Worker publicado;
[JSON sanitizado](qa/tarea14/vita-estado.json):

| Cerebro | Resultado | Latencia |
|---|---|---|
| Gemini · gemini-3.8-flash | Timeout; sin respuesta HTTP | 12,000 ms |
| Cloudflare · llama-3.3-70b | Funciona; HTTP 200 | 371 ms |
| Groq / Anthropic / OpenAI | Sin configurar | — |

**Gemini sigue sin validación funcional.** No se comprobó si el bloqueo ocurre
en la consulta de modelos o en generación; el timeout no demuestra clave inválida.
La meta de menos de 6 s con Gemini/Groq queda **sin cumplir**. El respaldo
funciona, pero tras agotar Gemini una conversación puede superar 12 s. No se
hizo otra llamada real ni se verificó una conversación real con el prompt nuevo.
El diagnóstico no garantiza disponibilidad continua. Sin cookie, endpoint: 401.

## Verificación

- Python privado: **241**, motor: **98**, correctas. PyTorch **2.8.0+cpu**,
  SB3 **2.7.0**, Gymnasium **1.2.0**, TA-Lib **0.8.1**; red real sin omisiones.
- Node completa local: **123**, cero fallas/omisiones, **una sola ejecución**.
  35 ejecuciones de casos dirigidos durante los cambios; dos fallaron primero
  por configuración/assert del test y se corrigieron. Tras la suite completa
  se corrigió el clic dentro de un plegable y pasaron cinco casos dirigidos y UI.
- Diario: tres pruebas dirigidas correctas. Primeros intentos impedidos por
  permisos de Windows; motor completo primero con entorno sin cuatro dependencias,
  repetido con el entorno completo existente. No son ensayos financieros.
- Chromium **375×812**, datos ficticios: compra NVDA → cambio de rango →
  posiciones en Simular → venta, detalle del universo y Laboratorio; sin errores
  JS ni desbordamiento. [Resumen](qa/tarea14/resumen-375.png),
  [Mercado](qa/tarea14/mercado-375.png), [gráfica](qa/tarea14/grafica-375.png),
  [Simular](qa/tarea14/simular-375.png). Dos intentos UI sin servidor útil y dos
  recorridos correctos. CI conserva sus pruebas habituales por despliegue.

[Despliegue de los tres puntos correcto](https://github.com/recinosr/proyecto-wall-street/actions/runs/37975557461),
PWA `v69`. El despliegue del punto 1 falló preparando el namespace de Cloudflare;
sus pruebas pasaron y el despliegue del punto 2 publicó también ese código.
[Despliegue final de logs correcto](https://github.com/recinosr/proyecto-wall-street/actions/runs/37976094552)
(`b0085c49`), sin repetir la llamada real. Ajuste del cliente HTTP del humo:
`a2f983f1`. No requirió cambios en la app ni más corridas estadísticas.

**0 experimentos estadísticos nuevos.** Políticas, intención, ledgers, tareas
programadas y archivo histórico reservado preservados. Los archivos previos
sin seguimiento no se incluyeron. El motor solo recibe diario/índice y notas:
la app, Pages y Worker pertenecen al repo privado.
