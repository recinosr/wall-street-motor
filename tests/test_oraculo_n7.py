import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from lab import oraculo_n7 as o


def df_de(fechas, cierre):
    fechas = pd.Series(pd.DatetimeIndex(fechas)).dt.as_unit("ns")
    avail = (fechas + pd.Timedelta(hours=20)).dt.tz_localize("UTC").dt.as_unit("ns")
    return pd.DataFrame({"date": fechas, "close": np.asarray(cierre, float), "available_at": avail})


def aleatorio(seed, desde="1994-01-03", hasta="2026-10-15", drift=0.0003, vol=0.01):
    fechas = pd.bdate_range(desde, hasta)
    rng = np.random.default_rng(seed)
    cierre = 100 * np.exp(np.cumsum(rng.normal(drift, vol, len(fechas))))
    return df_de(fechas, cierre)


DIV = {"SPY": 0.013, "VT": 0.019}
P = {"aporte": 100.0, "ventana": 60, "spread": 0.001}


class OraculoN7(unittest.TestCase):
    def test_hash_del_prereg_coincide(self):
        prereg, sha = o.verificar_prereg()
        self.assertEqual(prereg["version"], "oraculo-nivel7")
        esperado = (o.PREREG_SHA).read_text().split()[0]
        self.assertEqual(sha, esperado)

    def test_hash_incorrecto_aborta(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "p.json"
            ruta.write_text('{"version": "x"}', encoding="utf-8")
            sha = Path(d) / "p.sha256"
            sha.write_text("0" * 64 + "  p.json\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                o.verificar_prereg(ruta, sha)

    def test_siempre_arriba_r2_igual_r0(self):
        # Precio siempre creciente: cierre previo > SMA200 en todo mes con historial, y sin historial
        # R2 compra igual que el plan. Por tanto R2 debe coincidir con R0 exactamente.
        fechas = pd.bdate_range("1995-01-02", "2026-10-15")
        df = df_de(fechas, 100 * 1.001 ** np.arange(len(fechas)))
        cal = o.calendario({"_GSPC": df}, {"_GSPC": 0.03})
        senal = o.Senal(df)
        pesos = np.array([1.0])
        vs = o.ventanas(cal, pd.Timestamp("1996-01-01"), pd.Timestamp("2010-12-01"))[:12]
        self.assertTrue(len(vs) > 0)
        for m0, s, e in vs:
            r0 = o.simular(cal, senal, "R0", pesos, m0, s, e, P, False)
            r2 = o.simular(cal, senal, "R2", pesos, m0, s, e, P, False)
            self.assertAlmostEqual(r0["multiple"], r2["multiple"], places=12)
            self.assertEqual(r0["log"], r2["log"])

    def test_decisiones_no_usan_cierre_de_ejecucion(self):
        dfs = {"VT": aleatorio(2), "SPY": aleatorio(1)}
        cal = o.calendario(dfs, DIV)
        senal = o.Senal(dfs["SPY"])
        vs = o.ventanas(cal, pd.Timestamp("2012-01-01"), pd.Timestamp("2012-01-31"))
        m0, s, e = vs[0]
        t_exec = next(t for t in range(s, e) if cal.primer[t] and cal.mo[t] == m0 + 5)
        orden = cal.orden[t_exec]
        self.assertIsNotNone(senal.caida(orden))
        self.assertIsNotNone(senal.sobre_sma(orden))

        # Envenenar el dia de ejecucion y todo lo posterior (en ambos activos y en la senal).
        fecha_exec = cal.fechas[t_exec]
        sucio = {}
        for sym, df in dfs.items():
            x = df.copy()
            m = x["date"] >= fecha_exec
            x.loc[m, "close"] = x.loc[m, "close"] * np.linspace(0.01, 50, int(m.sum()))
            sucio[sym] = x
        cal2 = o.calendario(sucio, DIV)
        senal2 = o.Senal(sucio["SPY"])
        self.assertEqual(senal.caida(orden), senal2.caida(orden))
        self.assertEqual(senal.sobre_sma(orden), senal2.sobre_sma(orden))

        pesos = np.array([0.8, 0.2])
        for regla in ["R0", "R1", "R2", "R3", "R4"]:
            usar = regla == "R0"
            limpio = o.simular(cal, senal, regla, pesos, m0, s, e, P, usar)["log"]
            envenenado = o.simular(cal2, senal2, regla, pesos, m0, s, e, P, usar)["log"]
            antes = [x for x in limpio if x[0] <= t_exec]
            antes2 = [x for x in envenenado if x[0] <= t_exec]
            self.assertEqual(antes, antes2, regla)

    def test_banda_octubre_solo_al_pesar_fuera(self):
        # SPY salta x3 el 15-sep-2010: en octubre pesa ~43 % (fuera de 15-25 %), la banda manda
        # las compras a VT hasta que SPY vuelve a 20 %. Precios planos y sin dividendos.
        fechas = pd.bdate_range("2009-06-01", "2016-12-30")
        spy = np.where(fechas >= pd.Timestamp("2010-09-15"), 300.0, 100.0)
        dfs = {"VT": df_de(fechas, np.full(len(fechas), 100.0)), "SPY": df_de(fechas, spy)}
        cal = o.calendario(dfs, {"VT": 0.0, "SPY": 0.0})
        senal = o.Senal(dfs["SPY"])
        m0, s, e = o.ventanas(cal, pd.Timestamp("2010-01-01"), pd.Timestamp("2010-01-01"))[0]
        pesos = np.array([0.8, 0.2])  # activos ordenados ["VT", "SPY"]
        r0 = o.simular(cal, senal, "R0", pesos, m0, s, e, P, True)["log"]
        r4 = o.simular(cal, senal, "R4", pesos, m0, s, e, P, False)["log"]
        for t, comp in r4:
            self.assertAlmostEqual(comp[0], 80.0)
            self.assertAlmostEqual(comp[1], 20.0)
        sin_spy = [(cal.fechas[t].strftime("%Y-%m"), comp) for t, comp in r0 if comp[1] == 0.0]
        self.assertEqual(sin_spy[0][0], "2010-10")
        self.assertGreaterEqual(len(sin_spy), 10)
        for _, comp in sin_spy:
            self.assertAlmostEqual(comp[0], 100.0)
        siguiente = [comp for t, comp in r0 if cal.fechas[t] > pd.Timestamp(sin_spy[-1][0] + "-01")]
        self.assertAlmostEqual(siguiente[0][1], 20.0)
        self.assertAlmostEqual(siguiente[0][0], 80.0)

    def test_bh_valores_conocidos(self):
        q = o.bh([0.01, 0.03, 0.04, 0.2])
        self.assertTrue(np.allclose(q, [0.04, 0.16 / 3, 0.16 / 3, 0.2]))

    def test_bootstrap_extremos(self):
        rng = np.random.default_rng(0)
        self.assertAlmostEqual(o.p_bootstrap(np.full(50, 1.0), rng, 200), 1 / 201)
        self.assertAlmostEqual(o.p_bootstrap(np.full(50, -1.0), rng, 200), 1.0)

    def test_pipeline_sintetico_e_informe(self):
        with open(o.PREREG, encoding="utf-8") as f:
            prereg = json.load(f)
        prereg["datos"]["tramo_validacion"]["inicios"] = ["1996-01-01", "1997-12-01"]
        prereg["datos"]["tramo_prueba"]["inicios"] = ["2009-07-01", "2010-06-01"]
        precios = {"_GSPC": aleatorio(3), "SPY": aleatorio(1), "VT": aleatorio(2)}
        res = o.calcular(prereg, precios, rondas=200, sha="x" * 64)
        self.assertIn("level_approved", res)
        self.assertEqual(set(res["tramos"]["prueba"]["rules"]), {"R0", "R1", "R2", "R3", "R4"})
        self.assertEqual(set(res["tramos"]["validacion"]["rules"]), {"R0", "R1", "R2", "R3"})
        self.assertIsNone(res["tramos"]["prueba"]["rules"]["R0"]["approved"])
        texto = o.informe(res)
        lineas = texto.rstrip("\n").split("\n")
        self.assertTrue(8 <= len(lineas) <= 15, len(lineas))
        self.assertIn("El plan 80/20 no cambia por este resultado; una regla aprobada solo entra a la bóveda y espera 90 días.", texto)


if __name__ == "__main__":
    unittest.main()
