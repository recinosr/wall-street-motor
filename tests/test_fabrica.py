import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from lab import fabrica


class FabricaTests(unittest.TestCase):
    def test_bh_cuenta_toda_la_familia(self):
        self.assertEqual(fabrica.benjamini_hochberg({"a": .001, "b": .02, "c": .06}), {"a", "b"})
        self.assertEqual(fabrica.benjamini_hochberg({"a": .02, "b": .04, "c": .06}), set())

    def test_senal_usa_pasado_y_entrada_futura_con_costos(self):
        idx = pd.date_range("2024-01-01", periods=90, freq="min", tz="UTC")
        px = [100 + i * .1 for i in range(90)]
        frame = pd.DataFrame({"open": px, "high": px, "low": px, "close": px,
                              "volume": [1]*90}, index=idx)
        regla = {"id": "abc", "entrada": "momentum", "activo": "BTC",
                 "lookback_minutos": 5, "horizonte_minutos": 15, "umbral": .001}
        resultado = fabrica.dia(regla, frame, 1)
        esperado = (px[20] / px[6]) * .999**2 - 1
        self.assertAlmostEqual(resultado[0], esperado)
        roto = frame.drop(idx[4])
        self.assertFalse(fabrica.senal(regla, roto, 5))

    def test_reserva_no_se_lee_antes_de_medidas_todas_las_variantes(self):
        reglas = [{"id": str(i), "activo": "BTC", "familia": "ejemplo",
                   "entrada": "momentum", "lookback_minutos": 5,
                   "horizonte_minutos": 15, "umbral": .001} for i in range(2)]
        with tempfile.TemporaryDirectory() as tmp:
            llamadas = []
            def leer(activo, desde, hasta):
                llamadas.append((desde, hasta))
                raise LookupError("sin velas")
            with patch.object(fabrica, "ROOT", Path(tmp)), \
                 patch.object(fabrica, "variantes", side_effect=lambda: iter(reglas)), \
                 patch.object(fabrica.archivo, "leer", side_effect=leer):
                out = fabrica.ejecutar(limite=1)
            self.assertEqual(out["probadas"], 1)
            self.assertEqual(out["con_correccion"], 0)
            self.assertEqual(llamadas, [(fabrica.PANTALLA_DESDE, fabrica.PANTALLA_HASTA)])
            self.assertEqual(json.loads((Path(tmp)/"resultados/fabrica.json").read_text())["registro"]["0"]["motivo"], "sin_datos")

    def test_reserva_solo_tras_bh_de_la_familia_completa(self):
        reglas = [{"id": str(i), "activo": "BTC", "familia": "ejemplo"} for i in range(2)]
        muestra = {"dias": 30, "operaciones": 30, "neto": 1., "azar": 0.,
                   "mantener": 0., "ventaja": [.01]*30, "fechas": [], "mensual": []}
        with tempfile.TemporaryDirectory() as tmp:
            llamadas = []
            def leer(activo, desde, hasta):
                llamadas.append((desde, hasta))
                return object()
            with patch.object(fabrica, "ROOT", Path(tmp)), \
                 patch.object(fabrica, "variantes", side_effect=lambda: iter(reglas)), \
                 patch.object(fabrica.archivo, "leer", side_effect=leer), \
                 patch.object(fabrica, "evaluar", return_value=muestra), \
                 patch.object(fabrica, "p_bootstrap", return_value=.001):
                out = fabrica.ejecutar(limite=2)
            self.assertEqual(out["con_correccion"], 2)
            self.assertEqual(sum(1 for a, b in llamadas if a == fabrica.RESERVA_DESDE), 1)
            self.assertTrue(all("final" in r for r in out["registro"].values()))


if __name__ == "__main__":
    unittest.main()
