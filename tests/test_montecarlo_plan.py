import unittest

import numpy as np

from lab import montecarlo_plan as m


class MontecarloPlan(unittest.TestCase):
    def test_retorno_cero_deja_lo_aportado(self):
        r = np.zeros((24, 2))
        fin, aportado, caida = m.simular(r, 36, 50, 12, 1, 100.0, [0.8, 0.2])
        self.assertTrue(np.allclose(fin, 3600.0))
        self.assertEqual(aportado, 3600.0)
        self.assertTrue(np.allclose(caida, 0))

    def test_determinista_con_semilla(self):
        r = np.random.default_rng(0).normal(0.005, 0.04, (60, 2))
        a = m.simular(r, 60, 100, 12, 7, 100.0, [0.8, 0.2])[0]
        b = m.simular(r, 60, 100, 12, 7, 100.0, [0.8, 0.2])[0]
        self.assertTrue(np.array_equal(a, b))

    def test_referencia_crece_mas_que_aportes(self):
        self.assertGreater(m.referencia(120, 100.0, 0.07), 12000.0)

    def test_datos_reales_publicables(self):
        out = m.resumen()
        h = out["horizontes"]["10"]
        self.assertLess(h["final_usd"]["p5"], h["final_usd"]["p50"])
        self.assertLess(h["final_usd"]["p50"], h["final_usd"]["p95"])


if __name__ == "__main__":
    unittest.main()
