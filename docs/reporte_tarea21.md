# Tarea 21

Ningún método demostró mejorar el Brier del ingenuo expansivo tras BH global en esta medición. Eso no prueba que la ventaja sea imposible: las 999 réplicas tienen resolución mínima p=0.001 y poca potencia para efectos aislados en una familia grande.

976 contrastes; {"desarrollo": {"celdas": 488, "pronosticos": 1723231}, "reserva": {"celdas": 488, "pronosticos": 331363}}. Reserva inicial única separada, firmas previas, ejemplos relativos sin OHLC. Pruebas136, controles de futuro y caché byte por byte. CAPE/diferencial se abstienen sin publicaciones verificadas; datos Yahoo retrospectivos, sin vintages completos. La reserva del aprendiz no fue leída. Las extensiones incorporan solo anclas nuevas por horizonte. Ver [método y límites](boveda.md).
