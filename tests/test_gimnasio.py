"""Invariantes del gimnasio: causalidad, partición temporal y referencias."""
import unittest
import random
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from lab import dia, gimnasio
from lab.gimnasio_workflow import entregar, matriz, velas_necesarias


def sesion(seed, volatilidad=.0002):
    rng = np.random.default_rng(seed)
    cierre = 100 * np.exp(np.cumsum(rng.normal(0, volatilidad, 390)))
    apertura = np.r_[100, cierre[:-1]]
    indice = pd.date_range("2026-07-01 09:30", periods=390, freq="min", tz=dia.NY)
    df = pd.DataFrame({"open": apertura, "high": np.maximum(apertura, cierre),
                       "low": np.minimum(apertura, cierre), "close": cierre, "volume": 100}, index=indice)
    df.attrs["cierre_previo"] = 100.0
    df.attrs["media_dia"] = 100.0
    return df


class GimnasioTest(unittest.TestCase):
    def test_registro_no_cambia_operaciones_y_solo_usa_rasgos_conocidos(self):
        df = sesion(83)
        x = dia.rasgos(df)
        bot = {"id": 9, "familia": "azar", "p": .2, "mantener": 10,
               "stop": .005, "objetivo": .005, "salida": "tiempo"}
        registro = []
        original = dia.correr_bot(bot, df, x, 18)
        auditado = dia.correr_bot(bot, df, x, 18, registro=registro)
        self.assertEqual(original, auditado)
        self.assertEqual(len(registro), 2 * len(original[1]))
        for r in registro:
            self.assertLessEqual(r["senal_index"], r["index"])
            self.assertEqual(r["precio_observado"], float(df.close.iloc[r["senal_index"]]))
            self.assertTrue(r["motivos"])
            for k, v in r["rasgos"].items():
                self.assertEqual(v, float(x[k].iloc[r["senal_index"]]))
        changed = df.copy()
        changed.loc[changed.index[201]:, ["open", "high", "low", "close"]] *= 5
        later = []
        dia.correr_bot(bot, changed, dia.rasgos(changed), 18, registro=later)
        self.assertEqual([r for r in registro if r["index"] <= 200],
                         [r for r in later if r["index"] <= 200])

    def test_diagnostico_distingue_etapas_sin_cambiar_la_seleccion(self):
        fechas = [f"2026-{m:02}-01" for m in range(1, 8)]
        bots = [{"id": i, "familia": "azar"} for i in range(3)]
        def evaluar(bot, sim, dias, semilla):
            if bot["id"] in (-1, 0): return np.array([0.]), np.array([0])
            ret = -.01 if bot["id"] == 1 or dias == ["2026-06-01"] else .01
            return np.array([ret]), np.array([1])
        df = sesion(9)
        with patch.object(gimnasio, "preparar", return_value=fechas), \
             patch.object(gimnasio, "dividir_mes", return_value=([fechas[0]], [fechas[5]], [fechas[6]])), \
             patch.object(dia, "crear_bots", return_value=bots), \
             patch.object(gimnasio, "evaluar", side_effect=evaluar), \
             patch.object(gimnasio, "modelo_contexto", return_value=None), \
             patch.object(gimnasio, "datos_dia", return_value=(df, dia.rasgos(df))):
            fila = gimnasio.mes_a_mes("BTC", fechas[0], fechas[-1], pob=3, gens=1, mes="2026-07")[0]
        self.assertEqual(fila["campeon"], "no_operar")
        self.assertEqual(fila["n_pruebas"], 3)
        self.assertEqual(dict(fila["diagnostico"]["etapas"]), {
            "sin_entradas_train": 1, "margen_insuficiente_train": 1, "validacion_no_positiva": 1})
        json.dumps(fila)

    def setUp(self):
        self.costos = dia.COSTO, dia.SPREAD, dia.COSTO_FIJO, dia.CAPITAL
        dia.COSTO, dia.SPREAD, dia.COSTO_FIJO, dia.CAPITAL = 0, 0, 0, 1000

    def tearDown(self):
        dia.COSTO, dia.SPREAD, dia.COSTO_FIJO, dia.CAPITAL = self.costos

    def test_rasgos_y_senal_no_ven_velas_futuras(self):
        df = sesion(1)
        t = 200
        cambiado = df.copy()
        cambiado.loc[cambiado.index[t + 1]:, "close"] *= 20
        cambiado.loc[cambiado.index[t + 1]:, "high"] *= 20
        x, y = dia.rasgos(df), dia.rasgos(cambiado)
        pd.testing.assert_series_equal(x.iloc[t], y.iloc[t])
        bot = {"id": 1, "familia": "momentum", "k": 10, "umbral": 0,
               "tendencia": "1h", "min_vol_rel": 0, "gap_max": 1}
        self.assertEqual(dia.senal(bot, x, t, np.random.default_rng(1)),
                         dia.senal(bot, y, t, np.random.default_rng(1)))

    def test_campeon_solo_prueba_dias_posteriores(self):
        fechas = [d.date().isoformat() for d in pd.bdate_range("2026-01-05", "2026-08-31")]
        train, val, test = gimnasio.dividir_mes(fechas, "2026-07")
        self.assertGreaterEqual(len(train), 70)
        self.assertGreaterEqual(len(val), 10)
        self.assertEqual(train[0], "2026-01-05")
        self.assertTrue(max(train) < min(val) <= max(val) < min(test))
        self.assertTrue(all(d.startswith("2026-07") for d in test))
        self.assertEqual(gimnasio.dividir_mes(fechas, "2026-02"), ([], [], []))
        cripto = [d.date().isoformat() for d in pd.date_range("2026-01-05", "2026-07-31")]
        train_cripto, val_cripto, _ = gimnasio.dividir_mes(cripto, "2026-07")
        self.assertEqual(train_cripto[0], "2026-01-05")
        self.assertEqual(val_cripto[0], "2026-06-01")

    def test_azar_sin_costos_media_cercana_a_cero(self):
        bot = {"id": 0, "familia": "azar", "p": .05, "mantener": 15,
               "stop": 1, "objetivo": 1, "salida": "tiempo"}
        retornos = []
        for seed in range(20):
            df = sesion(seed)
            x = dia.rasgos(df)
            for i in range(20):
                bot["id"] = i
                retornos.append(dia.correr_bot(bot, df, x, semilla=seed)[0])
        self.assertLess(abs(float(np.mean(retornos))), .001)

    def test_mejor_posible_domina_mejor_bot_por_dia(self):
        bots = dia.crear_bots(20, 12)
        for seed in range(10):
            df = sesion(seed + 200, .0005)
            x = dia.rasgos(df)
            mejor = max(dia.correr_bot(b, df, x, semilla=seed)[0] for b in bots)
            self.assertGreaterEqual(dia.mejor_posible(df) + 1e-12, mejor)

    def test_costo_fijo_y_spread_se_cobran_en_ambos_lados(self):
        dia.COSTO, dia.SPREAD, dia.COSTO_FIJO, dia.CAPITAL = 0, .0002, .1, 125
        final = dia.vender(dia.comprar(1, 100), 100)
        self.assertAlmostEqual(final, (1 - .0001 - .1 / 125) * (1 - .0001) - .1 / 125)
        self.assertLess(final, 1)

    def test_mutacion_conserva_parametros_validos_de_familia(self):
        df = sesion(31)
        x = dia.rasgos(df)
        rng = random.Random(9)
        for i, bot in enumerate(dia.crear_bots(100, 9)):
            mutado = gimnasio.mutar(bot, rng, 1000 + i)
            self.assertEqual(mutado["familia"], bot["familia"])
            dia.correr_bot(mutado, df, x, semilla=3)

    def test_senales_en_bloque_equivalen_a_regla_minuto_a_minuto(self):
        x = dia.rasgos(sesion(41))
        for bot in dia.crear_bots(60, 41):
            if bot["familia"] == "azar": continue
            bloque = dia.senales_bot(bot, x)
            for t in range(60, len(x) - 1):
                self.assertEqual(bool(bloque[t]), dia.senal(bot, x, t, random.Random(1)))

    def test_detalle_diario_guarda_mil_bots_y_referencia(self):
        df = sesion(52)
        clave = ("BTC", "2026-07-01")
        anterior = gimnasio._cache.get(clave)
        gimnasio._cache[clave] = (df, dia.rasgos(df))
        try:
            v = gimnasio.detalle_dia("BTC", clave[1], {"id": -1, "familia": "no_operar"})
            self.assertEqual(len(v["retornos"]), 1000)
            self.assertGreaterEqual(v["mejor_posible"] + 1e-12, max(v["retornos"]))
            json.dumps(v)
        finally:
            if anterior is None: gimnasio._cache.pop(clave)
            else: gimnasio._cache[clave] = anterior

    def test_matriz_cubre_activos_costos_y_solo_meses_necesarios(self):
        trabajos = matriz("TODOS", "2026-01-05", "2026-10-03")["include"]
        self.assertEqual(len(trabajos), 2 * 4 * 4)
        self.assertEqual({t["mes"] for t in trabajos}, {"2026-07", "2026-08", "2026-09", "2026-10"})
        rutas = velas_necesarias("BTC", "2026-01-05", "2026-10-03")
        self.assertEqual(rutas[0], "velas/1m/BTC/2025-12.csv.gz")
        self.assertEqual(rutas[-1], "velas/1m/BTC/2026-10.csv.gz")

    def test_entrega_no_mezcla_archivos_de_otro_perfil_o_mes(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            base = raiz / 'datos' / 'gimnasio'
            base.mkdir(parents=True)
            informe = {'meses': [{'mes': '2026-07', 'serie_diaria': [{'fecha':'2026-07-01'}], 'dias_previos': ['2026-06-01']}]}
            (base / 'BTC_2026-01-05_2026-10-03_costo0.json').write_text(json.dumps(informe))
            for perfil, fecha in [('costo0','2026-07-01'), ('costo0','2026-06-01'), ('costo0','2026-08-01'), ('costo0.001','2026-07-01')]:
                f = base / 'dias' / 'BTC' / perfil / fecha[:7] / (fecha + '.json')
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text('{}')
            with patch.object(gimnasio, 'RAIZ', raiz):
                entregar(raiz / 'entrega', 'BTC', '2026-07', '2026-01-05', '2026-10-03')
            archivos = sorted(f.name for f in (raiz / 'entrega').rglob('*.json'))
            self.assertEqual(archivos, ['2026-06-01.json', '2026-07-01.json', 'BTC_2026-01-05_2026-10-03_costo0.json'])

    def test_huecos_no_convierten_quince_minutos_en_quince_filas(self):
        df = sesion(60)
        incompleto = df.drop(df.index[65:75])
        etiquetas = dict(gimnasio.etiquetas_contexto(incompleto))
        esperado = df['close'].iat[75] / df['open'].iat[61] - 1
        self.assertAlmostEqual(etiquetas[60], esperado)
        sin_objetivo = incompleto.drop(df.index[75])
        self.assertNotIn(60, dict(gimnasio.etiquetas_contexto(sin_objetivo)))

    def test_hora_y_ventana_usadas_son_minutos_reales(self):
        df = sesion(61)
        incompleto = df.drop(df.index[65:75])
        x = dia.rasgos(incompleto)
        fila = x.loc[df.index[80]]
        self.assertAlmostEqual(fila['hora'] * 389, 80)
        self.assertTrue(np.isnan(fila['tendencia_1h']))
        self.assertAlmostEqual(fila['ret5'], df['close'].iat[80] / df['close'].iat[75] - 1)

    def test_azar_optimizado_conserva_operaciones_y_semillas(self):
        df = sesion(71)
        x = dia.rasgos(df)
        for i in range(10):
            bot = {'id':i, 'familia':'azar', 'p':.05, 'mantener':15,
                   'stop':.001, 'objetivo':.002, 'tendencia':'1h',
                   'min_vol_rel':.75, 'gap_max':.05, 'salida':'volatilidad'}
            rapido = dia.correr_bot(bot, df, x, semilla=i)
            with patch.object(dia, 'senales_bot', return_value=None):
                referencia = dia.correr_bot(bot, df, x, semilla=i)
            self.assertEqual(rapido, referencia)

    def test_instrucciones_mal_formadas_usan_valores_predeterminados(self):
        with tempfile.TemporaryDirectory() as tmp:
            archivo = Path(tmp) / 'instrucciones.json'
            with patch.object(dia, 'INSTRUCCIONES', archivo):
                for cfg in [[], {'familias_activas':None}, {'rejillas':[]}, {'rejillas':{'k':[100]}}, {'rejillas':{'stop':['hola']}}, {'reglas_nuevas':[None]}, {'franjas':['09:30']}]:
                    archivo.write_text(json.dumps(cfg))
                    dia.configuracion.cache_clear()
                    self.assertEqual(dia.configuracion(), {})
                    self.assertEqual(len(dia.crear_bots(10)), 10)
            dia.configuracion.cache_clear()


if __name__ == "__main__":
    unittest.main()
