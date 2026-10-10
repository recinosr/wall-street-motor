# Reporte tarea 15

Completada en el orden **1 → 4 → 2 → 3**, con pull/rebase, commits y push por punto en ambos repositorios. Solo análisis y simulación.

| Punto | Entrega y conclusión |
|---|---|
| 1 | Gemini con 700 tokens y pensamiento mínimo; tres llamadas reales de humo, una por cambio. Flash Lite respondió HTTP 200 en 567 ms (lista 95 ms, generación 472 ms). Flash anterior presentó timeout en generación, no en la lista. Gemini Lite queda primero y Cloudflare de respaldo; lista cacheada 24 h por proceso. Groq sin configurar. No garantiza disponibilidad futura. |
| 4 | Candado con límite persistente, validación de entrada/origen, cabeceras CSP/HSTS, autenticación y cookies comprobadas, Vita como texto. Historia de ambos repos escaneada sin secretos reales detectados; un falso positivo clasificado. Dependencias de ambos proyectos sin avisos en auditoría; quedan avisos de paquetes ajenos del entorno compartido, documentados. |
| 2 | Abanico y tablas en Aprender → Carteras: seis tamaños, doce ventanas, momentum anual causal. Dos corridas completas: 288,072 recorridos; 108 celdas únicas descriptivas. No demuestra ventaja causal por el universo superviviente. US$100 ficticios es el experimento; presupuesto personal sigue US$50 base/100 máximo. |
| 3 | Diez reglas ICT añadidas a 75 previas, diario y BTC/ETH horario 2024. BH global de 11,550 contrastes, 2,100 nuevos. Algunos contrastes aislados pasan BH, pero ninguna regla ICT muestra ventaja neta estable contra ambos controles. |

## Validación

- Suite Node completa local **una sola vez: 130/130**, sin omisiones. Pruebas dirigidas antes y después para los cambios concretos; no se repitió la suite completa.
- Python completo: privado **242/242**, motor **107/107**, con PyTorch CPU, Stable-Baselines3, Gymnasium y TA-Lib disponibles.
- Pruebas dirigidas Python: 59 casos ejecutados, 58 aprobados y un fallo en fixture ICT corregido y vuelto a comprobar. Node: 98 casos dirigidos aprobados; un intento inicial bloqueado por permisos no llegó a ejecutar casos.
- Cuatro recorridos de interfaz móvil local: tres aprobados y un fixture de API corregido. Capturas a 375 px, sin errores JS ni desbordamiento general, tabla desplazable legible y respuesta maliciosa de Vita mostrada como texto. No son pruebas de mercado adicionales.
- Tres lecturas públicas de API desplegada sin cookie dieron 401 y las cabeceras previstas. Las tres llamadas de humo Gemini constan en sus recibos; no se hicieron llamadas extra para mejorar la cifra.
- Concentración: dos ejecuciones de los mismos parámetros, sin nuevas hipótesis; máxima revisión de mediana US$0.0331. ICT: una completa y una parcial de 37 activos descartada. Los detalles de todas las comparaciones están en los informes y métricas.

## Evidencia y límites

[Trazas Gemini](tarea15_punto1.md), [seguridad](seguridad_tarea15.md), [concentración](concentracion_tarea15.md), [ICT](ict_tarea15.md) y `docs/qa/tarea15/`. En el motor: `resultados/concentracion.json` y `resultados/enciclopedia.json`; solo métricas, sin publicar series descargadas.

Sesgo de supervivencia, falta de corroboración independiente completa y costos/impuestos parciales limitan los estudios. No se eligió cartera personal, no se operó dinero real y no se alteraron cuentas ficticias, modelos, archivos reservados ni horarios de bots. Los archivos de otros encargos permanecen fuera de estos commits.

## Publicación verificada

| Punto | Privado | Motor público |
|---|---|---|
| 1 | `51f2bebe`, informe `8fa78232` | `4a73c73` |
| 4 | `21406522`, escaneo `3452679b` | `5243d75`, escaneo `2b7bf86` |
| 2 | `a6f53657`, revisión `9012578c` | `f632c1a`, revisión `d950cc1` |
| 3 | `ed0c0db0` | `bf64bb9` |

[Despliegue final de Worker y Pages aprobado](https://github.com/recinosr/proyecto-wall-street/actions/runs/38013133375). Tres archivos publicados comprobados por SHA-256 normalizando CRLF local a LF de Git: `sw.js` (v71), `enciclopedia.js` y `concentracion-ui.js`, contenido idéntico y con CSP/HSTS. Primer acceso urllib sin User-Agent: 403; con User-Agent de navegador: 200. La comparación binaria inicial difería solamente por finales de línea. Evidencia: `docs/qa/tarea15/despliegue-final.json`. El commit posterior solo registra esta verificación y no requiere otro despliegue.
