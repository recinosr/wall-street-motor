import ast
import builtins
import json
import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path
import numpy as np
import pandas as pd
from lab.boveda import Boveda, Pronosticador, HORIZONTES, tabla
from lab.boveda_metricas import metricas, bootstrap, resumir


def prices(n=850, sim='SPY'):
    index = pd.bdate_range('2020-01-01', periods=n)
    rng = np.random.default_rng(21); c = 100*np.exp(np.cumsum(rng.normal(.0003, .012, n)))
    d = pd.DataFrame({'close': c, 'open': c*(1+rng.normal(0,.004,n)),
                      'high': c*1.02, 'low': c*.98, 'volume': rng.uniform(1e5,2e5,n)}, index=index)
    return {sim:d, '^VIX':d.assign(close=20+np.sin(np.arange(n)/20)*10)}


class VaultTest(unittest.TestCase):
    def test_poison_future_byte_identical_all_horizons_methods_and_retraining(self):
        for sim in ('SPY', 'BTC-USD'):
            data = prices(sim=sim); t = data[sim].index[650]
            cape = pd.DataFrame({'filed':['2020-01-10','2022-06-30','2023-02-10'],
                                 'cape':[20.,25.,99.], 'spread':[.02,.03,.8]},
                                index=pd.to_datetime(['2019-12-31','2021-12-31','2022-12-31']))
            data['CAPE'] = cape
            normal = Boveda(data)
            for poison in (10., np.nan):
                altered = {s:d.copy(deep=True) for s,d in data.items()}
                for s,d in altered.items():
                    mask = (pd.to_datetime(d.filed) > t) if 'filed' in d else d.index > t
                    cols = d.select_dtypes('number').columns
                    d.loc[mask, cols] = d.loc[mask, cols]*poison
                poisoned = Boveda(altered)
                for h in HORIZONTES:
                    a, b = Pronosticador(sim,h), Pronosticador(sim,h)
                    for date in (data[sim].index[620], t):
                        # Archivos bloqueados durante predicción: núcleo sin I/O.
                        with patch.object(builtins, 'open', side_effect=AssertionError('I/O prohibido')):
                            p = a.pronosticar(normal.ver(date)); q = b.pronosticar(poisoned.ver(date))
                        self.assertIn('logistica', p)
                        self.assertEqual(json.dumps(p,sort_keys=True,allow_nan=False).encode(),
                                         json.dumps(q,sort_keys=True,allow_nan=False).encode())

    def test_copies_inception_and_publication(self):
        data = prices(); data['IBIT'] = data['SPY'].copy()
        data['CAPE'] = pd.DataFrame({'filed':['2022-01-10'],'cape':[30.],'spread':[.02]},
                                   index=pd.to_datetime(['2021-12-31']))
        vault = Boveda(data); view = vault.ver('2022-01-10')
        self.assertNotIn('IBIT', view); self.assertNotIn('CAPE', view)
        self.assertIn('CAPE', vault.ver('2022-01-11'))
        original = vault.ver('2022-01-11')['SPY'].close.iloc[0]
        data['SPY'].iloc[0,0] = 0; view['SPY'].iloc[0,0] = -1
        self.assertEqual(vault.ver('2022-01-11')['SPY'].close.iloc[0], original)

    def test_indicators_causal_and_no_io_imports(self):
        import lab.boveda as module
        code = Path(module.__file__).read_text(encoding='utf8'); tree = ast.parse(code)
        allowed = {'numpy','pandas','sklearn'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): self.assertTrue(all(a.name.split('.')[0] in allowed for a in node.names))
            if isinstance(node, ast.ImportFrom): self.assertIn(node.module.split('.')[0], allowed)
            if isinstance(node, ast.Call):
                self.assertFalse(any(k.arg=='center' and isinstance(k.value,ast.Constant) and k.value.value for k in node.keywords))
                if isinstance(node.func,ast.Attribute) and node.func.attr=='shift':
                    self.assertFalse(any(isinstance(a,ast.UnaryOp) and isinstance(a.op,ast.USub) for a in node.args))
        data=prices(sim='BTC-USD'); t=data['BTC-USD'].index[600]
        full=tabla(data,'BTC-USD')
        past=tabla({s:d.loc[:t].copy() for s,d in data.items()},'BTC-USD')
        pd.testing.assert_frame_equal(past,full.loc[:t])
        pd.testing.assert_frame_equal(past,tabla(Boveda(data).ver(t),'BTC-USD'))

    def test_cached_forecasts_identical_to_indicators_recomputed_only_on_past(self):
        data=prices(sim='BTC-USD');vault=Boveda(data)
        for h in HORIZONTES:
            a,b=Pronosticador('BTC-USD',h),Pronosticador('BTC-USD',h)
            for i in (620,650,651):
                view=vault.ver(data['BTC-USD'].index[i])
                p=a.pronosticar(view);q=b.pronosticar(dict(view))
                self.assertEqual(json.dumps(p,sort_keys=True),json.dumps(q,sort_keys=True))

    def test_mature_labels_monthly_scaler_past_only(self):
        data=prices(); dates=data['SPY'].index; model=Pronosticador('SPY',63); vault=Boveda(data)
        first=dates[650]; p=model.pronosticar(vault.ver(first)); scaler=model.model.named_steps['standardscaler']
        fit=p['logistica']['ajuste_hasta']
        x=tabla(vault.ver(fit),'SPY')[['r1','r5','mom','vol','dist']].iloc[:-63].dropna()
        np.testing.assert_allclose(scaler.mean_,x.mean().to_numpy())
        second=dates[651]
        if first.month==second.month:
            q=model.pronosticar(vault.ver(second));self.assertEqual(p['logistica']['ajuste_hasta'],q['logistica']['ajuste_hasta'])
        for pred in p.values():
            self.assertLessEqual(pred['etiquetas_hasta'],first.date().isoformat())
            self.assertTrue(0 < pred['p_sube'] < 1);self.assertLessEqual(pred['p10'],pred['p90'])

    def test_weekly_resume_same_month_parameters(self):
        data=prices(); dates=data['SPY'].index; vault=Boveda(data)
        a,b=Pronosticador('SPY',21),Pronosticador('SPY',21)
        date=dates[650];month=dates[(dates.month==date.month)&(dates.year==date.year)][0]
        a.pronosticar(vault.ver(month))
        self.assertEqual(a.pronosticar(vault.ver(date)),b.pronosticar(vault.ver(date)))

    def test_ensemble_equal_weight_families(self):
        data=prices(sim='BTC-USD');p=Pronosticador('BTC-USD',63).pronosticar(Boveda(data).ver(data['BTC-USD'].index[650]))
        members=p['ensamble']['miembros']
        for k in ('p_sube','p10','p90'):
            expected=np.mean([np.mean([p[name][k] for name in names]) for names in members.values()])
            self.assertAlmostEqual(p['ensamble'][k],expected)


class RunnerTest(unittest.TestCase):
    def test_reserved_download_blocked_before_protocol_and_after_first_open(self):
        from lab import boveda_ejecutar as runner
        with tempfile.TemporaryDirectory() as td, patch.object(runner,'OUT',Path(td)), patch.object(runner,'descargar') as fetch:
            with self.assertRaises(FileNotFoundError):runner.ejecutar('final','2026-10-10')
            runner.write(Path(td)/'boveda_protocolo_v2.json',{'firma':runner.firma_codigo(),'commit_diseno':'test'})
            runner.write(Path(td)/'boveda_reserva_apertura.json',{'abierta':'ya'})
            with self.assertRaises(FileExistsError):runner.ejecutar('final','2026-10-10')
            fetch.assert_not_called()
            with patch.object(runner,'firma_codigo',return_value='otro'):
                with self.assertRaisesRegex(ValueError,'Código alterado'):runner.ejecutar('extender','2026-10-10')

    def test_targets_do_not_cross_reserve_and_extension_does_not_rescore(self):
        from lab.boveda_ejecutar import evaluar
        data=prices();d=data['SPY'];after={str(h):'2022-12-20' for h in HORIZONTES}
        first=evaluar('SPY',d,{},'desarrollo',after)
        self.assertTrue(first['metricas'])
        self.assertTrue(all(e['objetivo']<'2024-01-01' for e in first['ejemplos']))
        second=evaluar('SPY',d,{},'desarrollo',first['hasta_ancla'])
        self.assertEqual(second['pronosticos'],0)


class MetricsTest(unittest.TestCase):
    def test_metrics_pairing_and_calibration(self):
        rows=[{'p_sube':.6,'base':.6,'y':y,'retorno':.02 if y else -.02,'p10':-.03,'p90':.03} for y in [1,0]*100]
        m=metricas(rows,21)
        self.assertAlmostEqual(m['brier'],.26);self.assertEqual(m['habilidad'],0.)
        self.assertEqual(m['cobertura'],1.);self.assertEqual(sum(b['n'] for b in m['calibracion']),200)
        self.assertEqual(m['p'],1.)
    def test_block_null_and_short_history(self):
        self.assertEqual(bootstrap([1.,2.],63)['p'],1.)
        self.assertEqual(bootstrap(np.zeros(400),21)['p'],1.)
        self.assertEqual(bootstrap(np.ones(400),21)['p'],.001)
    def test_bh_counts_all_periods_assets_methods(self):
        rows=[dict(periodo=period,sim=sim,horizonte=1,metodo='x',fecha='2020-01-01',
                   p_sube=.5,base=.5,y=1,retorno=.02,p10=-.1,p90=.1) for period in ('desarrollo','reserva') for sim in ('SPY','QQQ')]
        result=resumir(rows);self.assertEqual(len(result),4)
        self.assertTrue(all(r['q_bh']==1. and not r['ventaja'] for r in result))


if __name__=='__main__': unittest.main()
