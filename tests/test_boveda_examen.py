import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from lab.boveda import Boveda
from lab.boveda_examen_modelos import MotorExamen, HORIZONTES, variables, etiquetas
from lab.boveda_examen import sortear, revelar, pesos_pasados, rondas, score, ejecutar
from lab.boveda_compat21 import firma_compatible
from lab.boveda_ejecutar import ROOT


def datos(n=3800):
    dates = pd.bdate_range('2003-01-01', periods=n)
    rng = np.random.default_rng(21)
    c = 100*np.exp(np.cumsum(rng.normal(.0005, .01, n)))
    d = pd.DataFrame({'open': c, 'high': c*1.015, 'low': c*.985,
                      'close': c, 'volume': rng.uniform(1e5, 2e5, n)}, index=dates)
    return {s: d.copy() for s in ('SPY', '^VIX', 'DX-Y.NYB', 'HYG', 'LQD', 'GLD', 'HG=F')}


class ExamenTest(unittest.TestCase):
    def test_future_poison_all_horizons_byte_identical_new_methods(self):
        frames = datos(4300); t = pd.Timestamp('2016-06-15')
        weights = {'ingenuo': 1., 'logistica': 2., 'analogos': 3., 'boosting': 2.}
        expected = {h: MotorExamen('SPY', h).pronosticar(Boveda(frames).ver(t), weights) for h in HORIZONTES}
        for factor in (10., np.nan):
            poison = {s: d.copy() for s, d in frames.items()}
            for d in poison.values(): d.loc[d.index > t] *= factor
            vault = Boveda(poison)
            for h in HORIZONTES:
                actual = MotorExamen('SPY', h).pronosticar(vault.ver(t), weights)
                if h < 1000: self.assertIn('boosting', actual)
                self.assertIn('analogos', actual); self.assertIn('ponderado', actual)
                self.assertEqual(json.dumps(expected[h], sort_keys=True, allow_nan=False), json.dumps(actual, sort_keys=True, allow_nan=False))
                for p in actual.values():
                    self.assertLess(p['etiquetas_hasta'], '2019-01-01')
                    self.assertLessEqual(p['etiquetas_hasta'], t.date().isoformat())
                    self.assertLessEqual(p['minimo_esperado'], p['maximo_esperado'])

    def test_validation_does_not_train_and_missing_external_is_abstention(self):
        data = datos(5600); vault = Boveda(data); model = MotorExamen('SPY', 30)
        p = model.pronosticar(vault.ver('2022-06-15'))
        self.assertLess(p['boosting']['ajuste_hasta'], '2019-01-01')
        altered = {s: d.copy() for s, d in data.items()}
        for d in altered.values(): d.loc[(d.index >= '2019-01-01') & (d.index < '2022-06-15')] *= 2
        q = MotorExamen('SPY', 30).pronosticar(Boveda(altered).ver('2022-06-15'))
        self.assertEqual(p['ingenuo'], q['ingenuo'])
        self.assertNotIn('entre_activos', MotorExamen('SPY', 30).pronosticar(Boveda({'SPY': data['SPY']}).ver('2022-06-15')))

    def test_calendar_targets_extremes_and_missing_path(self):
        d = datos(5600)['SPY']; date = '2020-01-03'
        result, error = revelar(d, date, 30, {'x': {'p10': -1., 'p90': 10.}})
        self.assertIsNone(error); self.assertEqual(result['objetivo'], '2020-02-03')
        future = d.loc['2020-01-06':'2020-02-03']
        self.assertAlmostEqual(result['maximo_real'], future.high.max()/d.loc[date, 'close']-1)
        d.loc['2020-01-10', 'close'] = np.nan
        self.assertIn('hueco', revelar(d, date, 30, {})[1])
        self.assertIn('reserva', revelar(d, '2023-12-01', 90, {})[1])

    def test_random_reproducible_no_duplicates_no_future_eligibility(self):
        data = datos(5600)
        a = sortear(data, 100, 7); self.assertEqual(a, sortear(data, 100, 7))
        self.assertNotEqual(a, sortear(data, 100, 8)); self.assertEqual(len(set(a)), 100)
        self.assertTrue(all('2005-01-01' <= t < '2024-01-01' and pd.Timestamp(t).weekday() < 5 for _, t in a))
        with self.assertRaises(ValueError): sortear(data, 0, 0)

    def test_external_prefix_equal_and_not_current_close(self):
        frames = datos(); t = frames['SPY'].index[800]
        full = variables(Boveda(frames).ver(t), 'SPY')
        frames['DX-Y.NYB'].loc[t, 'close'] *= 10
        altered = variables(Boveda(frames).ver(t), 'SPY')
        pd.testing.assert_series_equal(full['externa_DX-Y.NYB'], altered['externa_DX-Y.NYB'])
        for h in HORIZONTES:
            ret, peak, trough, targets = etiquetas(frames['SPY'].loc[:t], h)
            self.assertTrue(all(targets[i] < len(full) for i in np.flatnonzero(np.isfinite(ret))))

    def test_weights_use_only_mature_training_oos(self):
        rows = [{'objetivo': '2018-01-01', 'y': 1, 'pronosticos': {'boosting': {'p_sube': .8}}}]*30
        bad = [{'objetivo': '2020-01-01', 'y': 0, 'pronosticos': {'boosting': {'p_sube': .99}}}]*200
        self.assertEqual(pesos_pasados(rows, '2018-01-01'), {})
        self.assertEqual(pesos_pasados(rows, '2023-01-01'), pesos_pasados(rows+bad, '2023-01-01'))

    def test_stop_count_search_and_no_selection_in_validation(self):
        rows = []
        for year in range(2006, 2024):
            for month in range(1, 13):
                rows.append({'fecha': f'{year}-{month:02}-01', 'objetivo': f'{year}-{month:02}-28',
                    'sim': 'SPY', 'horizonte': 30, 'y': month % 2,
                    'pronosticos': {'ingenuo': {'p_sube': .5}, 'boosting': {'p_sube': .99}}})
        out = rondas(rows)
        self.assertEqual(len(out['rondas']), 3); self.assertEqual(out['ganador_congelado'], 'ingenuo')
        self.assertGreater(out['familia_ajuste_busqueda'], out['contrastes_calculados']+976)
        self.assertFalse(out['reserva']['evaluacion_final_nueva'])
        self.assertEqual(score(rows, 'ausente')['pronosticos_disponibles'], 0)

    def test_signed21_unchanged_and_exclusive_receipt_blocks_repeat_before_io(self):
        protocol = json.loads((ROOT/'resultados/boveda_protocolo_v2.json').read_text(encoding='utf8'))
        self.assertEqual(firma_compatible(), protocol['firma'])
        from lab import boveda_examen as exam
        with tempfile.TemporaryDirectory() as td, patch.object(exam, 'OUT', Path(td)), patch.object(exam, 'descargar') as fetch:
            (Path(td)/'boveda_protocolo_v2.json').write_text(json.dumps(protocol), encoding='utf8')
            (Path(td)/'boveda_examen_recibo_1_1000.json').write_text('{}')
            with self.assertRaises(FileExistsError): ejecutar(1000, 1)
            fetch.assert_not_called()


if __name__ == '__main__': unittest.main()
