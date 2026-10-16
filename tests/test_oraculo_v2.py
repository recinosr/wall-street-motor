import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from lab import oraculo_v2 as v


class OraculoV2Tests(unittest.TestCase):
    def test_prereg_hash_coincide(self):
        pr, h = v.cargar_prereg()
        self.assertEqual(pr["version"], "oraculo-v2")
        self.assertEqual(pr["datos"]["particion"]["prueba_sellada"][0], "2020-01-01")

    def test_rasgos_no_miran_el_futuro(self):
        idx = pd.bdate_range("2020-01-01", periods=120)
        c = pd.Series(np.exp(np.cumsum(np.random.default_rng(1).normal(0, .01, 120))), index=idx)
        a = v.rasgos_precio(c)
        c2 = c.copy()
        c2.iloc[80:] *= 3.0
        b = v.rasgos_precio(c2)
        pd.testing.assert_frame_equal(a.iloc[:80], b.iloc[:80])

    def test_posicion_de_regla_usa_solo_cierres_previos(self):
        idx = pd.bdate_range("2019-01-01", periods=400)
        c = pd.Series(np.exp(np.cumsum(np.random.default_rng(2).normal(0, .01, 400))), index=idx)
        c2 = c.copy()
        c2.iloc[300:] *= 0.2
        for regla in ("tendencia", "volatilidad"):
            a, b = v.posiciones(c, regla), v.posiciones(c2, regla)
            pd.testing.assert_series_equal(a.iloc[:301], b.iloc[:301])

    def test_bh_monotono_y_acotado(self):
        q = v.bh([0.001, 0.04, 0.03, None, 0.5])
        self.assertIsNone(q[3])
        self.assertAlmostEqual(q[0], 0.004)
        self.assertTrue(all(0 <= x <= 1 for x in q if x is not None))

    def test_resultados_despues_de_cierre_reaccionan_al_dia_siguiente(self):
        idx = pd.bdate_range("2024-01-02", periods=10)
        antes = pd.Timestamp("2024-01-04 13:00", tz="UTC")   # 08:00 ET
        despues = pd.Timestamp("2024-01-04 21:30", tz="UTC")  # 16:30 ET
        self.assertEqual(idx[v.sesion_reaccion(idx, "2024-01-04", antes, True)], pd.Timestamp("2024-01-04"))
        self.assertEqual(idx[v.sesion_reaccion(idx, "2024-01-04", despues, True)], pd.Timestamp("2024-01-05"))

    def test_apertura_no_se_repite(self):
        with tempfile.TemporaryDirectory() as d:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps({"aperturas": {"nivel1": 1}}))
            with patch.object(v, "REGISTRO", reg):
                with self.assertRaises(RuntimeError):
                    v.ejecutar(True)

    def test_disponibilidad_de_precios_es_el_cierre(self):
        from lab import oraculo_datos as d
        p = d.cargar_precios("SPY")
        self.assertTrue(((p.available_at - p.index.tz_localize("UTC")) >= pd.Timedelta(hours=20)).all())


if __name__ == "__main__":
    unittest.main()
