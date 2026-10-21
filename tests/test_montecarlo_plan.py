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

    @classmethod
    def setUpClass(cls):
        cls.out = m.resumen()

    def test_datos_reales_publicables(self):
        h = self.out["escenarios"]["base"]["horizontes"]["10"]
        self.assertLess(h["final_usd"]["p5"], h["final_usd"]["p50"])
        self.assertLess(h["final_usd"]["p50"], h["final_usd"]["p95"])

    def test_costo_compra_resta_el_aporte(self):
        fin, aportado, _ = m.simular(np.zeros((24, 2)), 36, 50, 12, 1, 100.0, [0.8, 0.2], costo_compra=0.001)
        self.assertTrue(np.allclose(fin, 0.999 * 3600.0))
        self.assertEqual(aportado, 3600.0)

    def test_costos_bajan_la_mediana(self):
        r_con = m.retornos(m.PARAMS, True).to_numpy()
        r_sin = m.retornos(m.PARAMS, False).to_numpy()
        fin_con = m.simular(r_con, 120, 2000, 12, 1, 100.0, [0.8, 0.2], m.costo_compra())[0]
        fin_sin = m.simular(r_sin, 120, 2000, 12, 1, 100.0, [0.8, 0.2])[0]
        self.assertLess(np.percentile(fin_con, 50), np.percentile(fin_sin, 50))

    def test_historia_larga_desde_1950(self):
        self.assertTrue(self.out["escenarios"]["historia_larga"]["datos"]["desde"].startswith("1950"))

    def test_claves_de_horizonte_exactas(self):
        esperadas = {"aportado_usd", "referencia_7pct_usd", "final_usd", "prob_final_menor_aportado",
                     "prob_final_menor_referencia_7pct", "peor_caida_maxima", "prob_caida_peor_que_30pct",
                     "prob_caida_peor_que_50pct", "costo_mediana_usd", "caminos_historicos"}
        for nombre in ("base", "historia_larga", "conservador"):
            esc = self.out["escenarios"][nombre]
            self.assertEqual(set(esc["horizontes"]), {"5", "10", "20"})
            for h in esc["horizontes"].values():
                self.assertEqual(set(h), esperadas)
                self.assertEqual(set(h["final_usd"]), {"p1", "p5", "p25", "p50", "p75", "p95"})


if __name__ == "__main__":
    unittest.main()
