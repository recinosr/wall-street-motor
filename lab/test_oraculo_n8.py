"""Pruebas unitarias del oraculo nivel 8 con datos sinteticos (no toca la prueba sellada)."""
from __future__ import annotations

import json
import math
import random
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oraculo_n8 as n8  # noqa: E402


def serie_sintetica(n: int, seed: int = 1, sigma: float = 0.01) -> n8.Serie:
    rnd = random.Random(seed)
    cierres = [100.0]
    for _ in range(n - 1):
        cierres.append(cierres[-1] * math.exp(rnd.gauss(0.0, sigma)))
    inicio = datetime(2000, 1, 1, tzinfo=timezone.utc)
    fechas = [(inicio + timedelta(days=i)).date().isoformat() for i in range(n)]
    disp = [inicio + timedelta(days=i, hours=21) for i in range(n)]
    return n8.Serie("TEST", fechas, cierres, disp)


class TestQlike(unittest.TestCase):
    def test_cero_cuando_y_igual_f(self):
        for v in (0.01, 0.5, 3.0):
            self.assertEqual(n8.qlike(v, v), 0.0)

    def test_positivo_y_formula(self):
        self.assertGreater(n8.qlike(1.0, 2.0), 0)
        self.assertGreater(n8.qlike(2.0, 1.0), 0)
        self.assertAlmostEqual(n8.qlike(1.0, 2.0), 0.5 - math.log(0.5) - 1.0, places=12)


class TestEwma(unittest.TestCase):
    def test_recursion_y_semilla(self):
        s = serie_sintetica(400, seed=3)
        F = n8.caracteristicas(s)
        c = s.cierres
        sq = [0.0] + [math.log(c[k] / c[k - 1]) ** 2 for k in range(1, len(c))]
        s2 = sum(sq[1:253]) / 252  # semilla: primeras 252 sesiones de r
        self.assertAlmostEqual(F["m1"][252] / 21, s2, places=14)
        for k in range(253, 400):
            s2 = 0.94 * s2 + 0.06 * sq[k]
            self.assertAlmostEqual(F["m1"][k] / 21, s2, places=14)

    def test_b0_es_media_252(self):
        s = serie_sintetica(400, seed=4)
        F = n8.caracteristicas(s)
        c = s.cierres
        sq = [0.0] + [math.log(c[k] / c[k - 1]) ** 2 for k in range(1, len(c))]
        k = 300
        self.assertAlmostEqual(F["b0"][k], 21 * sum(sq[k - 251:k + 1]) / 252, places=14)


class TestHar(unittest.TestCase):
    def test_recupera_coeficientes_conocidos(self):
        rnd = random.Random(11)
        n = 300
        F = {"d": [None] * n, "w": [None] * n, "m": [None] * n, "rv21": [None] * n}
        for k in range(n):
            F["d"][k] = rnd.uniform(0, 0.1)
            F["w"][k] = rnd.uniform(0, 0.1)
            F["m"][k] = rnd.uniform(0, 0.1)
            F["rv21"][k] = 2.0 + 0.5 * F["d"][k] + 0.3 * F["w"][k] + 0.2 * F["m"][k]
        beta = n8.ajustar_har(F, list(range(n)))
        for got, exp in zip(beta, [2.0, 0.5, 0.3, 0.2]):
            self.assertAlmostEqual(got, exp, places=8)

    def test_fallback_a_b0_si_har_no_positivo(self):
        F = {"b0": [0.04], "b1": [0.03], "m1": [0.02], "d": [0.0], "w": [0.0], "m": [0.0]}
        pr, fb = n8.pronosticos_en(F, 0, [-1.0, 0.0, 0.0, 0.0])
        self.assertTrue(fb)
        self.assertEqual(pr["M2"], pr["B0"])


class TestBH(unittest.TestCase):
    def test_valores_conocidos(self):
        q = n8.bh([0.01, 0.04, 0.03, 0.005])
        for got, exp in zip(q, [0.02, 0.04, 0.04, 0.02]):
            self.assertAlmostEqual(got, exp, places=12)

    def test_tope_en_uno_y_monotono(self):
        q = n8.bh([0.9, 0.8])
        self.assertAlmostEqual(q[0], 0.9, places=12)
        self.assertAlmostEqual(q[1], 0.9, places=12)
        self.assertTrue(all(0 <= x <= 1 for x in n8.bh([0.2, 0.5, 0.9, 0.01])))


class TestBootstrap(unittest.TestCase):
    def test_extremos(self):
        rondas = 200
        self.assertAlmostEqual(n8.p_bootstrap([1.0] * 150, random.Random(1), rondas), 1 / (rondas + 1))
        self.assertAlmostEqual(n8.p_bootstrap([-1.0] * 150, random.Random(1), rondas), 1.0)


class TestReapertura(unittest.TestCase):
    def test_ya_abierto(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "oraculo_n8.json"
            self.assertFalse(n8.ya_abierto(ruta))
            ruta.write_text(json.dumps({"aperturas_prueba_sellada": 0}), encoding="utf-8")
            self.assertFalse(n8.ya_abierto(ruta))
            ruta.write_text(json.dumps({"aperturas_prueba_sellada": 1}), encoding="utf-8")
            self.assertTrue(n8.ya_abierto(ruta))
            ruta.write_text("no es json", encoding="utf-8")
            self.assertTrue(n8.ya_abierto(ruta))

    def test_main_se_niega_a_reabrir(self):
        original = n8.SALIDA
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "oraculo_n8.json"
            contenido = json.dumps({"aperturas_prueba_sellada": 1, "estado": "completa"})
            ruta.write_text(contenido, encoding="utf-8")
            n8.SALIDA = ruta
            try:
                self.assertEqual(n8.main(["--abrir-prueba"]), 2)
                self.assertEqual(ruta.read_text(encoding="utf-8"), contenido)
            finally:
                n8.SALIDA = original


class TestSinLookahead(unittest.TestCase):
    def test_pronostico_en_t_no_lee_filas_posteriores(self):
        n, t = 400, 300
        s = serie_sintetica(n, seed=5)
        F = n8.caracteristicas(s)
        beta = [1.0, 0.5, 0.3, 0.2]
        pr1, _ = n8.pronosticos_en(F, t, beta)

        # Mutar todas las filas posteriores a t (cierres distintos, mismos available_at).
        rnd = random.Random(99)
        cierres = list(s.cierres)
        for j in range(t + 1, n):
            cierres[j] *= math.exp(rnd.gauss(0.0, 0.5))
        s2 = n8.Serie(s.simbolo, s.fechas, cierres, s.disponible)
        F2 = n8.caracteristicas(s2)
        pr2, _ = n8.pronosticos_en(F2, t, beta)

        self.assertEqual(pr1, pr2)
        for nombre in ("b0", "b1", "m1", "d", "w", "m"):
            for k in range(t + 1):
                self.assertEqual(F[nombre][k], F2[nombre][k], f"{nombre}[{k}] lee el futuro")
        # Control: el objetivo si cambia (usa r posteriores), asi que la prueba no es vacua.
        self.assertNotEqual(F["rv21"][t], F2["rv21"][t])

    def test_origenes_respetan_tramo(self):
        s = serie_sintetica(600, seed=6)
        ks = n8.origenes(s, "2000-09-15", "2000-10-31")
        self.assertTrue(ks)
        for k in ks:
            self.assertGreaterEqual(s.fechas[k], "2000-09-15")
            self.assertLessEqual(s.fechas[k], "2000-10-31")
            self.assertGreaterEqual(k, n8.VENTANA_HIST)
            self.assertLessEqual(k + 21, len(s.fechas) - 1)


if __name__ == "__main__":
    unittest.main()
