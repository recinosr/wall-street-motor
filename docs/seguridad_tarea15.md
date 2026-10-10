# Seguridad — tarea15

Solo análisis/simulación; no brokers ni claves nuevas. No se reescribió historia.

| Control | Resultado y corrección |
|---|---|
| Secretos | Motor: gitleaks8.30.1, todos los refs,69 commits/78.71MB,0 hallazgos. Privado: gitleaks interrumpido por consumo; reemplazo de blobs únicos en curso, se completará antes de entrega. |
| Autenticación | Pages verifica APP_CLAVE en servidor para todas las rutas API; entrar/salir son bootstrap/cierre. Worker solo service binding, workers_dev=false, sin rutas públicas configuradas. No confiar en un header del cliente como autenticación pública. |
| Límites | Candado:10 intentos/IP por ventana15min, Durable Object atómico/persistente; hash de IP sin guardarla. Fallo del límite cierra acceso. Vita:200 reservas/candado/día GT, incluido diagnóstico. |
| Cookies | HttpOnly,Secure,SameSite=Strict; cookie malformada devuelve401. Se retira del reenvío general al Worker; no logs de claves. Cookie actual es credencial compartida y debe protegerse. |
| Headers | CSP con script-src self, sin scripts inline; estilos inline permitidos por UI existente. HSTS,nosniff,no-referrer y frame-ancestors none. API no-store, también errores. |
| Entradas | Clave tipo/longitud/cuerpo, origen, métodos, símbolos acotados; Vita pregunta3000/historial acotado. Mensajes renderizados mediante textContent; payload con img/onerror probado como texto. |
| Datos | Rutas de lectura explícitas y campos limitados; sin secretos. Métricas públicas del motor pueden cachearse internamente; Pages fuerza no-store. |
| Dependencias | npm audit:0,Worker sin dependencias runtime. pip-audit resolviendo privado34 y motor35 paquetes:0 avisos. El entorno compartido tenía37 avisos en6 paquetes; urllib3/soupsieve usados por descargadores actualizados y mínimos seguros en ambos requirements. Quedan32 avisos en4 paquetes ajenos al proyecto: cryptography,pip,pyjwt,setuptools; no se modifican herramientas compartidas indiscriminadamente. |

Evidencia en docs/qa/tarea15: pip-private.json,pip-motor.json,npm.json.
[Scanner PyPA](https://github.com/pypa/pip-audit),
[gitleaks](https://github.com/gitleaks/gitleaks).
No garantiza ausencia de vulnerabilidades, objetos Git inalcanzables ni servicios externos.
Los JS/APK y estudios estáticos son públicos; el candado protege datos/API privada.
