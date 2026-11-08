# Arreglos de estabilidad para Máquina v2

Fecha: 2026-11-08

## Cambios

- Ollama: el instalador oficial se intenta hasta cinco veces con espera creciente. Si falla, se usa el artefacto de [GitHub Releases](https://github.com/ollama/ollama/releases/latest). La release consultada el 2026-11-08 publica `ollama-linux-amd64.tar.zst` (1.54 GB); no publica el `.tgz` mencionado en el pedido. Los modelos se conservan en `actions/cache` con una clave por sistema operativo y modelo. `ollama pull` tiene cinco intentos y espera creciente.
- SEC: `scripts/sec_prefetch.mjs` baja localmente el mapa de tickers y companyfacts para el universo y la unión de los miembros históricos S&P 500 en `datos/universo_pit/sp500_miembros.json`, limita solicitudes a ocho por segundo y guarda puntos trimestrales compactos con su fecha `filed`. Los campos incluyen ingresos, utilidad operativa, utilidad neta y BPA diluido. El gzip se actualiza cada 50 compañías. La variante de Actions carga ese archivo sin llamar a la SEC.
- Duración: las variantes con noticias o debate usan cinco llamadas diarias por defecto. La matriz pasa de 20 a 40 tramos con `max-parallel: 20`, que permite dos tandas de 20 sin exceder la concurrencia configurada. Cada tramo conserva `filas.jsonl` y `avance.jsonl`, y carga sus artefactos incluso si el paso falla.
- Resumen: reunir la caché de titulares es `continue-on-error`; el resumen espera 40 tramos y `resumir.mjs` combina los directorios parciales disponibles.

## Estado de la extracción SEC

Ejecuté `node scripts/sec_prefetch.mjs` en esta computadora. SEC respondió HTTP 403 tanto a `www.sec.gov/files/company_tickers.json` como a endpoints de `data.sec.gov`, incluso con el User-Agent requerido. No se generó `datos/sec/fundamentales.json.gz` y por eso no se añadió un archivo vacío o fabricado al repo. La descarga debe repetirse desde una conexión que SEC acepte antes de correr la variante `fundamentales`.

## Duración estimada

Para el período predeterminado 2025-01-02 a 2026-10-16, hay aproximadamente 450 sesiones hábiles: unos 11–12 días por tramo. Con dos tandas de 20, cinco llamadas al día para noticias/debate y el caché caliente de modelos, estimo 2–5 horas para una variante sin noticias/debate y 3–7 horas para noticias o debate. Las variantes se ejecutan en serie dentro de cada tramo, por lo que una corrida que incluya varias variantes puede acercarse a la suma de esos tiempos. Son estimaciones de planificación; el tiempo de generación del modelo y los servicios de red de cada runner varían. El prefetch SEC debería requerir aproximadamente 2–5 minutos a ocho solicitudes por segundo, más el tiempo variable de descarga, cuando SEC permita el acceso.

No se iniciaron corridas de GitHub Actions.
