# Vita: conversación y diario

Vita conversa; las reglas de la demo cripto siguen siendo deterministas. El chat
no cambia pesos, políticas, cuentas ni workflows de investigación. El diario
resume resultados publicados con fecha y hash; no inventa pruebas de hoy ni
atribuye al chat el trabajo del motor.

`POST /api/vita` pasa por el candado de Pages y exige el mismo origen. Pages
retira la cookie y fabrica una identidad hash interna. Un Durable Object SQLite
reserva de forma atómica hasta 200 solicitudes diarias por candado, incluso
desde distintos dispositivos. Día de Guatemala; los intentos fallidos también
consumen una reserva. No se guarda allí el texto de la conversación.

Gemini, Groq y Workers AI se intentan en ese orden, con máximo 20 segundos por
proveedor, incluyendo lectura de respuesta. Los proveedores opcionales se
activan con la variable GitHub `VITA_CEREBRO=anthropic` o `openai`. Fallar vuelve
a la cadena automática. Un cerebro distinto conserva diario, personalidad y
conversación local. Los modelos pueden cambiar con `VITA_MODELO_<PROVEEDOR>` en
el Worker; no se aceptan endpoints del solicitante.

Modelos verificados el 9 de octubre de 2026:

- [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models),
  `gemini-3.8-flash`. Su [tabla de precios](https://ai.google.dev/gemini-api/docs/pricing)
  muestra entrada/salida gratuitas en el nivel gratis y uso del contenido para
  mejorar productos. La cuota depende de la cuenta: no se promete uso ilimitado.
- [Groq](https://console.groq.com/docs/models): `openai/gpt-oss-120b` en producción;
  la clave opcional permite el segundo respaldo, sujeto a la cuota del proyecto.
- [Workers AI](https://developers.cloudflare.com/workers-ai/models/llama-3.3-70b-instruct-fp8-fast/):
  `@cf/meta/llama-3.3-70b-instruct-fp8-fast`, binding `AI`, sin clave externa.
  [Cuota gratuita diaria](https://developers.cloudflare.com/workers-ai/platform/pricing/)
  limitada; agotar cuota produce un mensaje de indisponibilidad, no habilita
  facturación ni crea una cuenta.
- Opcionales con costo según cuenta: [Claude Sonnet 5](https://www.anthropic.com/news/claude-sonnet-5)
  y [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra),
  usando Messages y Responses respectivamente. OpenAI recibe `store:false`.

El contexto incluye diario, marcador, patrones resumidos, carteras, demo,
robots, tesis y la ficha de hasta tres activos mencionados (si existe en el
universo), con fundamentales SEC y ETFs disponibles. No se leen perfiles,
correos, nombres completos, libros personales ni cuentas de brokers. Preguntas
con correo, identificadores largos, claves o frases de identificación se
rechazan antes del proveedor; nombres de varias palabras con mayúsculas se
omiten. No es un detector universal de información personal: no escribirla.
Los textos externos se delimitan como datos, sin herramientas ni ejecución.

La conversación se guarda solo en localStorage (hasta 100 mensajes; se envían
seis recientes con tamaño acotado). «Nueva conversación» la elimina. Proveedores
gratis pueden usar los textos recibidos para mejorar sus modelos. La memoria
común de Vita es el diario del proyecto; no hay memoria personal en el servidor.

Sin clave Gemini, la app muestra «Todavía no tengo llave» con los pasos para
configurarla; Workers AI puede contestar mientras tanto. Sin ningún cerebro
disponible se devuelve esa explicación local. Las pruebas sustituyen fetch y
AI.run; no se invoca una API real en CI.

El workflow público `vita-diario.yml` corre a las 22:30 UTC (16:30 GT), además
de ejecución manual. «Mañana» significa continuar las reglas existentes y
esperar etiquetas, no un nuevo experimento inventado. Los acumulados se
identifican como acumulados y el resultado negativo se conserva.
