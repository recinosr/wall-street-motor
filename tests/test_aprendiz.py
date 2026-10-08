import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from lab import aprendiz as a


def velas():
    t = pd.date_range("2024-03-01 09:30", periods=390, freq="min", tz="America/New_York")
    c = 100 * np.exp(np.arange(390) * .0003 + np.sin(np.arange(390) / 9) * .003)
    return pd.DataFrame({"open": c * .9999, "close": c, "high": c * 1.001,
                         "low": c * .999, "volume": 100 + np.arange(390)}, index=t)


class AprendizTests(unittest.TestCase):
    def test_futuro_no_altera_rasgos_ni_predicciones_previas(self):
        df = velas()
        futuro = df.copy()
        futuro.loc[futuro.index[200]:, ["open", "close", "high", "low"]] *= .8
        antes = a.expedientes(df)
        despues = a.expedientes(futuro)
        for e, f in zip(antes, despues):
            if e["senal"] >= 200: break
            self.assertEqual(e["x"], f["x"])
            self.assertEqual(a.probabilidad(a.nuevo(), e["x"]), a.probabilidad(a.nuevo(), f["x"]))
        self.assertNotEqual(antes[27]["neto"], despues[27]["neto"])

    def test_predice_dia_completo_antes_de_aprender_y_reanuda_json(self):
        m = a.nuevo()
        r = a.sesion(m, velas(), "2024-03-01")
        self.assertTrue(all(p["prob"] == .5 for p in r["pronosticos"]))
        self.assertNotEqual(r["pesos_antes_sha"], r["pesos_despues_sha"])
        self.assertNotEqual(m["pesos"], [0.] * len(a.NOMBRES))
        restaurado = json.loads(json.dumps(m))
        dia2 = velas().copy()
        dia2.index += pd.Timedelta(days=1)
        self.assertEqual(a.sesion(m, dia2, "2024-03-02"), a.sesion(restaurado, dia2, "2024-03-02"))
        self.assertEqual(m, restaurado)

    def test_hueco_no_extiende_horizonte_y_costos_dos_lados(self):
        df = velas()
        normal = a.expedientes(df)
        roto = a.expedientes(df.drop(df.index[75]))
        self.assertNotIn(60, [e["senal"] for e in roto])
        e = normal[0]
        neto = (e["ps"] * .999) / (e["pe"] / .999) - 1
        self.assertAlmostEqual(e["neto"], neto, places=12)
        self.assertEqual(df.index[e["salida"]] - df.index[e["senal"]], pd.Timedelta(minutes=15))
        self.assertEqual(df.index[e["entrada"]] - df.index[e["senal"]], pd.Timedelta(minutes=1))

    def test_no_solapa_posiciones_ni_reentrena_mes_y_reserva_particiones(self):
        df = velas()
        E = a.expedientes(df)
        resultado = a.cartera(E, [1.] * len(E))
        capital = 1.
        for i, o in enumerate(resultado["ops"]):
            if i: self.assertGreater(o[0] - 1, resultado["ops"][i - 1][1])
            unidades = capital * (1 - a.COSTO) / o[2]
            capital = unidades * o[3] * (1 - a.COSTO)
            self.assertAlmostEqual(capital, o[4], places=12)
        self.assertAlmostEqual(capital - 1, resultado["ret"], places=12)
        m = a.nuevo()
        a.procesar_mes(m, df, "2024-03")
        previo = copy.deepcopy(m)
        with self.assertRaises(ValueError): a.procesar_mes(m, df, "2024-03")
        with self.assertRaises(ValueError): a.procesar_mes(m, df, "2025-04")
        with self.assertRaises(ValueError): a.procesar_mes(m, df, "2026-01")
        self.assertEqual(m, previo)

    def test_mismo_run_no_avanza_ni_entrena_dos_veces(self):
        lista = type('Listado', (), {'stdout': 'velas/1m/BTC/2024-03.csv.gz\nvelas/1m/BTC/2024-04.csv.gz\n'})()
        with tempfile.TemporaryDirectory() as tmp, patch.object(a.subprocess, 'run', return_value=lista), patch.object(a.archivo, 'leer', return_value=velas()) as lector:
            primero = a.ejecutar(tmp, '42')
            estado = (Path(tmp) / 'modelo.json').read_bytes()
            self.assertGreater(primero['ejemplos'], 0)
            self.assertEqual(a.ejecutar(tmp, '42')['estado'], 'ya_procesado')
            self.assertEqual((Path(tmp) / 'modelo.json').read_bytes(), estado)
            self.assertEqual(lector.call_count, 1)

    def test_checkpoint_entrenado_no_cambia_al_aprender_otro_dia(self):
        m = a.nuevo()
        a.sesion(m, velas(), '2024-03-01')
        fijo = copy.deepcopy(m)
        previo = copy.deepcopy(fijo)
        r = a.sesion(m, velas(), '2024-03-02', fijo)
        self.assertEqual(fijo, previo)
        self.assertEqual(r['congelado_sha'], a.huella(previo))
        self.assertTrue(any(p != .5 for p in r['probabilidades_congelado']))


if __name__ == "__main__": unittest.main()
