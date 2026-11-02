import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from lab import gimnasio_oraculo as g

EV = {'FOMC': np.array(['2000-03-01', '2000-06-01'], dtype='datetime64[D]'),
      'CPI': np.array(['2000-02-15'], dtype='datetime64[D]'), 'EMPLEO': np.array([], dtype='datetime64[D]')}


def sintetico(n=700, seed=1):
    rng = np.random.default_rng(seed)
    fechas = pd.bdate_range('1999-01-04', periods=n)
    c = 100 * np.exp(np.cumsum(rng.normal(0, .01, n)))
    return pd.DataFrame({'date': fechas, 'open': c, 'high': c * 1.01, 'low': c * .99, 'close': c,
                         'volume': rng.integers(1000, 5000, n).astype(float),
                         'available_at': (fechas + pd.Timedelta(hours=21)).strftime('%Y-%m-%dT%H:%M:%SZ')}).assign(
        disp=lambda d: pd.to_datetime(d.available_at, utc=True))


def vista(S, i):
    out = {m: S['bucket'][m][i] for m in g.METODOS if m != 'eventos'}
    out.update({f'ev{h}': S['eventos'][h][i] for h in g.HORIZONTES})
    out.update({f'base{h}': S['base'][h][i] for h in g.HORIZONTES})
    out.update({f'f_{k}': v for k, v in S['feats'].iloc[i].items()})
    return out


class SinFuga(unittest.TestCase):
    def test_truncar_el_futuro_no_cambia_nada(self):
        d = sintetico()
        full = g.construir(d, EV)
        for i in (300, 450, 600):
            cortado = g.construir(d.iloc[:i + 1].reset_index(drop=True), EV)
            a, b = vista(full, i), vista(cortado, i)
            for k in a:
                if isinstance(a[k], float):
                    self.assertTrue(np.isclose(a[k], b[k], equal_nan=True), k)
                else:
                    self.assertEqual(a[k], b[k], k)

    def test_alterar_precios_posteriores_no_cambia_la_prediccion(self):
        d = sintetico()
        i = 400
        d2 = d.copy()
        d2.loc[i + 1:, ['close', 'high', 'low', 'open', 'volume']] *= 7.3
        est = g.estado_inicial()
        S1, S2 = g.construir(d, EV), g.construir(d2, EV)
        for h in g.HORIZONTES:
            self.assertEqual(g.predecir(est, S1, i, h), g.predecir(est, S2, i, h))

    def test_base_solo_usa_etiquetas_ya_maduras(self):
        d = sintetico()
        S = g.construir(d, EV)
        i, h = 500, 21
        c = d.close.to_numpy()
        esperado = np.mean([c[j + h] > c[j] for j in range(0, i - h + 1)])
        self.assertAlmostEqual(S['base'][h][i], esperado)

    def test_hecho_marca_filas_con_etiqueta_futura(self):
        S = g.construir(sintetico(), EV)
        self.assertFalse(S['hecho'][-1])
        self.assertTrue(S['hecho'][-22])

    def test_rangos_no_tocan_prueba_sellada(self):
        self.assertLess(pd.Timestamp(g.VAL[1]) + pd.Timedelta(days=31), pd.Timestamp('2020-01-01'))
        self.assertLess(pd.Timestamp(g.TRAIN[1]) + pd.Timedelta(days=31), pd.Timestamp(g.VAL[0]))


class Aprendizaje(unittest.TestCase):
    def test_hedge_favorece_menor_perdida(self):
        h = {'a': [10., 100], 'b': [30., 100], 'c': [20., 100]}
        w = g.pesos_hedge(h)
        self.assertAlmostEqual(sum(w.values()), 1)
        self.assertGreater(w['a'], w['c'])
        self.assertGreater(w['c'], w['b'])

    def _activos(self):
        d = sintetico(3300, 2)
        d['date'] = pd.bdate_range('2005-01-03', periods=3300)
        d['disp'] = d['date'] + pd.Timedelta(hours=21)
        return {'X': d, '__eventos__': EV}

    def test_sesion_valida_no_actualiza_estado_y_entrena_si(self):
        est = g.estado_inicial()
        ev, X, Y = g.sesion(est, self._activos(), np.random.default_rng(0), 60)
        self.assertEqual(est['repeticiones_train'], 60)
        self.assertEqual(est['hedge']['1']['tendencia_sma200'][1], 60)  # solo entrenamiento
        self.assertIn('ensamble', ev['metodos']['tasa_base_ventana'])

    def test_validacion_fija_no_depende_de_semilla_ni_sesion(self):
        act = self._activos()
        series = {'X': g.construir(act['X'], EV, 'X')}
        a = g.validacion_fija(series)
        e1, e2 = g.estado_inicial(), g.estado_inicial()
        ev1, _, _ = g.sesion(e1, act, np.random.default_rng(1), 40)
        ev2, _, _ = g.sesion(e2, act, np.random.default_rng(99), 90)
        self.assertEqual((ev1['filas'], ev1['fechas']), (ev2['filas'], ev2['fechas']))
        self.assertEqual(ev1['filas'], sum(len(v) for v in a.values()) * len(g.HORIZONTES))
        ords = series['X']['fecha'][a['X']].astype('datetime64[D]').astype(np.int64)
        self.assertTrue((ords % g.PASO_VAL == 0).all())
        fechas = series['X']['fecha'][a['X']]
        self.assertTrue(fechas.min() >= np.datetime64(g.VAL[0]) and fechas.max() <= np.datetime64(g.VAL[1]))  # no toca 2020+

    def test_referencia_de_ventana_es_la_frecuencia_de_la_propia_ventana(self):
        act = self._activos()
        ev, _, _ = g.sesion(g.estado_inicial(), act, np.random.default_rng(0), 30)
        S = g.construir(act['X'], EV, 'X')
        idx = g.validacion_fija({'X': S})['X']
        for h in g.HORIZONTES:
            self.assertAlmostEqual(ev['frecuencia_subida_ventana'][str(h)], float(S['up'][h][idx].mean()))
        # la tasa base de la ventana, como método, tiene skill 0 contra sí misma por horizonte constante (misma pérdida de referencia)
        self.assertAlmostEqual(ev['metodos']['tasa_base_ventana']['tasa_base']['brier_ref'], ev['brier_ref']['tasa_base_ventana'])

    def test_t_por_fechas_no_crece_con_repeticiones_duplicadas(self):
        rng = np.random.default_rng(3)
        ng, k = 120, 50
        grupo = np.repeat(np.arange(ng), 1)
        ref = rng.random(ng) * .1 + .25
        perd = ref - rng.normal(.002, .02, ng)
        t1 = g._estadisticos(perd, ref, grupo, ng, np.random.default_rng(0))['t']
        # cada fecha repetida k veces idéntica: 50x más filas pero la misma información
        t2 = g._estadisticos(np.tile(perd, k), np.tile(ref, k), np.tile(grupo, k), ng, np.random.default_rng(0))['t']
        self.assertAlmostEqual(t1, t2, delta=.05 * max(1, abs(t1)))

    def test_sesgo_alcista_no_da_skill_contra_la_tasa_base_de_la_ventana(self):
        # un predictor que solo sabe "sube 60 %" gana a una base de 53 % pero no a la frecuencia real de la ventana
        rng = np.random.default_rng(5)
        y = (rng.random(4000) < .6).astype(float)
        grupo = np.arange(4000) // 10
        ng = int(grupo.max()) + 1
        mod = (.6 - y) ** 2
        ent = (.53 - y) ** 2
        ven = (y.mean() - y) ** 2
        self.assertGreater(g._estadisticos(mod, ent, grupo, ng, np.random.default_rng(0))['t'], 2)
        self.assertLess(abs(g._estadisticos(mod, ven, grupo, ng, np.random.default_rng(0))['t']), 2)

    def test_dos_sesiones_en_disco(self):
        with tempfile.TemporaryDirectory() as t:
            f1 = g.correr(Path(t), 60, semilla=3)
            f2 = g.correr(Path(t), 60, semilla=3)
            self.assertEqual(f2['repeticiones_acumuladas'], 120)
            self.assertEqual(len(pd.read_csv(Path(t) / 'curva.csv')), 2)
            self.assertTrue((Path(t) / 'pesos.json').exists())
            res = __import__('json').loads((Path(t) / 'resumen.json').read_text())
            self.assertIn('frase', res)
            self.assertEqual(set(res['por_referencia']), set(g.REFS_SKILL))


if __name__ == '__main__':
    unittest.main()
