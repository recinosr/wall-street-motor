# Tarea 13 — 9 de octubre de 2026

Ejecutada en orden **2 → 3 → 1 → 4 → 5**, con commit, rebase y push por punto
en los dos repositorios. App publicada; no se modificaron las políticas ni
los ledgers de cuentas existentes y no se abrió el archivo histórico reservado.

| Punto | Privado | Motor público |
|---|---|---|
| 2. Gráficas | `bd54e4d7` | `df8699d` |
| 3. Mercado | `69293f07` | `c4a7a99` |
| 1. Navegación | `1c5e2005` | `43c460f` |
| 4. Vita | `f1a12df5` | `0738b1c` |
| 5. Robots y revisión final | `6df68d16` | `c65800a` |

## Pantallas

- **Resumen:** tarjetas de S&P 500, Bitcoin y plan de largo plazo, una idea y
  un botón por tarjeta. La entrada de Portafolio también deja las cuatro guías
  sueltas en Aprender.
- **Mercado:** buscador arriba, palabras por nombre oficial y alias; Acciones
  (S&P 500 primero), ETFs, Cripto y Mis activos. Velas por defecto. El gráfico
  conserva zoom/desplazamiento, actualiza la serie, sigue el extremo derecho
  solo cuando se mira ahí y ofrece «→ Ahora». Reloj y cuenta regresiva en GT;
  sesión regular NYSE con feriados/cierres anticipados 2026, cripto 24 horas.
  El calendario futuro sin cobertura se identifica; el reloj no vuelve vivo
  un precio histórico. Replay y marcador de operaciones conservan la vista.
- **Portafolio:** plan, aportes y comparaciones existentes conservados. Base
  personal US$50/mes y máximo US$100, costos dentro; no se elige cartera real.
- **Simular:** práctica BTC/ETH en vivo, Comprar/Vender, efectivo, posición
  e historial local; al lado del seguimiento aparece la demo de Vita y mantener.
  Cuenta nueva independiente de US$1,000 (`wallstreet-live-practice-1000`);
  la anterior de US$10,000 sigue en Laboratorio. Sin migraciones silenciosas.
- **Aprender:** Enciclopedia, Carteras famosas, Pronósticos, Guías y Robots.
  Guías incluye empezar desde cero, Cinco personas y masterclass. Robots explica
  las tres reglas cripto anteriores y las seis reglas/fondos nuevos.
- **Vita:** chat corto, conversación local y «Nueva conversación». Cerebros
  Gemini → Groq → Workers AI, 20 segundos por intento; proveedor identificado.
  Anthropic/OpenAI opcionales con `VITA_CEREBRO`. Diario determinista, contexto
  acotado, ficha del activo cuando existe, precio fechado, SEC y ETFs disponibles.
  Candado, origen propio y contador persistente de 200 intentos diarios por
  candado (GT). No se envían perfiles, cookies ni cuentas personales; se rechazan
  identificadores detectados. No escribir datos personales: el filtro no es
  universal. Los niveles gratis pueden usar los textos para mejorar modelos.

**Ajustes → Laboratorio (técnico):** Escáner, Ideas, Plazos, Macro, Análisis,
Gimnasio, Escuela, Aprendiz, replay anterior, Neural Quant, DQN y Android.
Hashes antiguos técnicos llevan al Laboratorio. Rutinas existentes conservadas.
La demo cripto es determinista: el chat no decide sus compras ni aprende pesos.
PWA/candado conservados, service worker `wall-street-v66`.

## Mediciones y verificación

Una corrida de 6 reglas: DBMF, KMLM, CTA, Dual Momentum, Faber 10 meses y
Permanent Portfolio. **12 comparaciones** contra VT/60-40, **18 de crisis**,
12 escenarios de aporte; sin optimización ni selección. Todos rindieron menos
que VT en sus períodos comunes. DBMF/KMLM ayudaron en 2022; eso no demuestra
protección futura. ETFs de futuros sin diez años: se muestra cero ventanas.
SG CTA sin serie diaria descargable verificada; su [fuente oficial](https://wholesale.banking.societegenerale.com/en/prime-services-indices/)
remite a solicitar acceso a datos diarios completos. Fiscalidad aproximada y
corroboración solo del cierre final: [detalle y cifras](robots_tarea13.md).

- Python privado: **241 pruebas, OK**, con PyTorch `2.8.0+cpu`, SB3 `2.7.0`
  y Gymnasium `1.2.0`; no se omitió la red real.
- Python motor: **97 pruebas, OK**, incluyendo TA-Lib, diario y carteras.
- Node completa local: **114 pruebas, cero fallas/omisiones**, una sola ejecución
  final. Antes se usaron pruebas dirigidas; los despliegues ejecutaron sus propios
  checks existentes. Reintentos por permisos/dependencias no son nuevos ensayos
  estadísticos.
- Chromium 375×812: navegación, buscador, chat/guardado/borrado, Laboratorio,
  arrastre, pellizco y Ahora; sin desbordamiento ni errores JS. Capturas con
  **datos ficticios de prueba**: [Aprender](qa/tarea13/aprender-375.png),
  [Mercado](qa/tarea13/mercado-375.png), [Simular](qa/tarea13/simular-375.png),
  [Vita](qa/tarea13/vita-375.png).
- [Despliegue final exitoso](https://github.com/recinosr/proyecto-wall-street/actions/runs/37960160299).
  Recursos publicados verificados, `/api/vita` sin cookie: 401.
- [Diario en nube exitoso](https://github.com/recinosr/wall-street-motor/actions/runs/37960260265),
  diario automático 16:30 GT. Robots mensual/manual en el motor público.
  Ninguna prueba de chat invocó un proveedor real; Gemini sigue sin validación
  funcional de su clave/modelo en esta entrega.

La revisión automática rechazó inicialmente publicar Vita por autorización
insuficiente de proveedores/secretos. Se comprobó el texto explícito del punto 4
y aceptó la publicación; no queda un bloqueo ni se usó un rodeo.

## Clave de Gemini: pasos exactos

**Ya existe `GEMINI_API_KEY` en GitHub.** No leí su valor ni comprobé su validez.
El despliegue ya intenta cargarla al Worker. Estos pasos sirven para crearla o
reemplazarla; no hace falta crear otra solo por esta tarea.

1. Abrí [Google AI Studio → API Keys](https://aistudio.google.com/app/apikey),
   iniciá sesión y aceptá las condiciones si corresponde. Usá un proyecto en
   nivel gratis. AI Studio puede crear un proyecto predeterminado para usuarios
   nuevos; si no aparece el tuyo, Dashboard → Projects → Import projects.
2. En API Keys, **Create API key**, elegí el proyecto y copiá la clave. Las claves
   nuevas se crean como claves de autorización. [Instrucciones oficiales](https://ai.google.dev/gemini-api/docs/api-key).
   No actives facturación para seguir estos pasos.
3. En [el repositorio privado](https://github.com/recinosr/proyecto-wall-street),
   **Settings → Secrets and variables → Actions → Repository secrets**.
   Si existe `GEMINI_API_KEY`, abrí **Update**; si falta, **New repository secret**.
   Nombre exacto: `GEMINI_API_KEY`; valor: la clave; guardá el secreto.
4. **Actions → Publicar web y Worker → Run workflow → main → Run workflow**.
   Esperá la marca verde. Actions ejecuta `wrangler secret put` y la clave no
   aparece en el código, navegador ni informe. No se necesita pegarla en el
   motor público para el diario.
5. Abrí la app, recargá la nueva versión y entrá en **Vita**. Una respuesta
   indicará el proveedor. Si indica un respaldo, Gemini pudo fallar por clave,
   acceso, cuota o tiempo. No pegues la clave en la conversación.

Modelo verificado: `gemini-3.8-flash`, con [nivel gratis documentado](https://ai.google.dev/gemini-api/docs/pricing),
sujeto a cuota/disponibilidad de la cuenta. [Arquitectura y otros cerebros](vita_tarea13.md).
