# VITA v2: estado de implementación

Fecha del reporte: 2026-11-06.

La implementación v2 está lista en `maquina_v2/` y `.github/workflows/maquina-v2.yml`. Reutiliza las series, los cálculos temporales y el cliente Ollama de `maquina_ilimitada/` sin modificar esa carpeta ni el workflow v1. Incluye inputs de período y modelo, variantes combinables, prueba de memoria, matriz de 20 tramos, artefactos, resúmenes y caché GDELT comprimida por mes.

Se confirmó por la API pública de Actions que el run `42343659179` seguía **en cola** y `42318399718` seguía **en ejecución** al preparar este reporte. Por esa condición, no se despachó la corrida v2. El workflow queda configurado con `solo_compra,factores`, `qwen2.5:7b`, 20 llamadas por día y rango predeterminado 2024-01-02 a 2024-12-31 para lanzarlo cuando deje de estar en cola.

Verificación local solicitada: `node --test maquina_v2/maquina.test.mjs` (4 pruebas aprobadas); `node --check` para ambos módulos ejecutables. Las métricas finales quedan pendientes de la corrida, no se han fabricado resultados.

## Alcance estadístico

Cada decisión usa cierres fechados antes del día de decisión. Las noticias se acotan a las 72 horas anteriores y se registran los días sin titulares. `solo_compra` restringe a señales de subida; `calibrada` calcula tasa base histórica hasta la fecha; `factores` añade momentum 12-1, volatilidad, cercanía a máximo y SMA200; `debate` y `conjunto` añaden llamadas de modelo. Los resultados son exploratorios y están sujetos a sesgo del universo actual y a la limitación de que los modelos se entrenaron después del período histórico.
