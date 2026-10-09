# Wall Street Motor

Laboratorio público y autocontenido de simulación con velas de un minuto de BTC y ETH de Coinbase. No conecta brokers ni opera dinero real. Su código, archivo de velas, rutinas y resultados viven en este repositorio. La rama `datos` contiene exclusivamente `velas/1m/BTC` y `velas/1m/ETH`; `main` contiene el código y los resúmenes.

## Rutinas

La app privada consulta `resultados/enciclopedia.json` mediante `/api/enciclopedia`, con caché de una hora. Su catálogo documenta75 reglas y siete salidas; los colores describen evidencia retrospectiva corregida, no promesas. Los datos fuente se descargan en ejecución: el reporte contiene métricas y cobertura, nunca OHLC. `enciclopedia.yml` ejecuta ocho lotes semanales y una BH global antes de publicar.

| Rutina | Frecuencia | Método |
| --- | --- | --- |
| `archivar` | diaria | Descarga el día UTC anterior de Coinbase y fusiona sin duplicar. |
| `gimnasio` | diaria, BTC y ETH | Entrena con seis meses previos, elige en validación y mide en el mes siguiente. Cobra 0.1 % por lado. Compara azar de la misma frecuencia y comprar y mantener. Registra cuántos candidatos evaluó. |
| `escuela` | cada tres horas | Cinco reglas juegan 1,000 sesiones iguales por bot, con costos y control aleatorio. Son prácticas retrospectivas, no evidencia prospectiva. |
| `aprendiz` | cada hora | Modelo logístico incremental: un mes cronológico por lote, solo meses anteriores a abril de 2025. Cada sesión se predice antes de incorporar sus etiquetas. Abril a diciembre de 2025 y 2026 permanecen reservados para esta rutina. |
| `fabrica` | diaria | Cinco familias declarativas generan 324 variantes BTC/ETH. Mide como máximo 120 variantes nuevas por corrida y guarda todas las fallas. Abre su periodo final reservado solo tras medir la familia completa y pasar Benjamini–Hochberg. |
| `fabrica-diaria` | diaria | Cuatro familias de ideas diarias generan 102 variantes BTC/ETH con velas públicas de Coinbase. Evalúa por meses cronológicos con costo de 0.1 % por lado, azar y mantener. Aplica Benjamini–Hochberg a las 102 antes de abrir abril de 2025 en adelante. Publica solo métricas. |

`resultados/*.json` contiene vistas compactas de la última corrida. Los resultados negativos se publican igual que los positivos. Ningún resultado retrospectivo demuestra una ventaja futura. Entrenar y seleccionar muchas reglas exige contar todas las pruebas y corregir comparaciones múltiples; el gimnasio informa su número de candidatos y la fábrica aplica Benjamini–Hochberg a las 324 variantes definidas.

## Reproducir

Python 3.12:

```sh
python -m pip install -r requirements.txt
git fetch origin datos
git worktree add --detach /tmp/motor-datos origin/datos
ln -s /tmp/motor-datos/velas velas
python -m unittest discover -s tests
python -m scripts.motor gimnasio --activo BTC
python -m scripts.motor aprendiz --run-id manual-1
python -m scripts.motor escuela --sesiones 1000
python -m lab.fabrica
python -m lab.fabrica_diaria
```

La simulación de un día se ejecuta con `python -m lab.dia BTC 2026-09-23 --bots 1000` cuando esa fecha ya está archivada. Para añadir el día UTC anterior: `python -m lab.archivar diario --salida /tmp/motor-datos`. Las acciones de GitHub tienen un límite de 30 minutos por trabajo; una corrida vencida se registra como fallo y no equivale a evidencia positiva.

## Límites

Coinbase puede omitir minutos sin negociación. El archivo conserva esos huecos y las funciones que requieren intervalos exactos no los rellenan. Los costos son hipótesis de simulación, no tarifas de una cuenta personal. El bot ganador de entrenamiento puede sobreajustarse; se compara con azar y con mantener fuera de la selección. Los datos y modelos de este repo no contienen información personal.
