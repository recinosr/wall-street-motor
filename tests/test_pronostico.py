import datetime as dt
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
import pandas as pd
from lab.pronostico import targets, save_once, digest, predict, wilson, features, summary, score
from lab.enciclopedia import detect

class ForecastTests(unittest.TestCase):
    def test_score_mature_only_and_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'resultados/pronosticos').mkdir(parents=True)
            rows=[dict(sim='A',tipo='acción',sector='prueba',horizonte=h,objetivo=day,
                       ancla='2026-10-08',predicciones={'logistica':.6,'azar':.4})
                  for h,day in [(1,'2026-10-09'),(5,'2026-10-15')]]
            save_once(root/'resultados/pronosticos/f.json',dict(filas=rows,publicado='2026-10-09T06:00:00Z',tipo='acción'))
            data=pd.DataFrame({'close':[100.,102.],'open':[100.,101.]},index=pd.to_datetime(['2026-10-08','2026-10-09']))
            with patch('lab.pronostico.ROOT',root),patch('lab.pronostico.receipt',return_value={'commit':'previo'}),patch('lab.pronostico.fetch',return_value=data) as fetch:
                now=dt.datetime(2026,10,10,1,tzinfo=dt.timezone.utc)
                score(now);first=json.loads((root/'resultados/marcador.json').read_text())
                self.assertEqual(first['etiquetas'],2)
                self.assertEqual(first['acumulado'][0]['horizonte'],1)
                score(now);self.assertEqual(fetch.call_count,1)
                self.assertEqual(json.loads((root/'resultados/marcador.json').read_text())['etiquetas'],2)
    def test_holiday_and_weekend(self):
        dates,deadline=targets(dt.datetime(2026,7,3,tzinfo=dt.timezone.utc),'acción')
        self.assertEqual(dates[0],'2026-07-06')
        self.assertEqual(dates[1],'2026-07-10')
    def test_crypto_horizon(self):
        dates,_=targets(dt.datetime(2026,10,9,tzinfo=dt.timezone.utc),'cripto')
        self.assertEqual(dates,['2026-10-09','2026-10-13'])
    def test_write_once_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'f.json';save_once(p,{'filas':[1]})
            r=json.loads(p.read_text());self.assertEqual(r['sha256'],digest({'filas':[1]}))
            with self.assertRaises(FileExistsError):save_once(p,{'filas':[2]})
            self.assertEqual(json.loads(p.read_text())['filas'],[1])
    def test_features_causal(self):
        d=pd.DataFrame({'close':np.arange(1,501,dtype=float)})
        a=features(d);d.iloc[400:]=1e8;b=features(d)
        pd.testing.assert_frame_equal(a.iloc[:400],b.iloc[:400])
    def test_crypto_year_month_are_calendar_days(self):
        d=pd.DataFrame({'close':np.arange(1,501,dtype=float)})
        self.assertAlmostEqual(features(d,crypto=True).mom.iloc[-1],470/135-1)
        self.assertAlmostEqual(features(d).mom.iloc[-1],479/248-1)
    def test_predict_probability(self):
        rng=np.random.default_rng(5);c=100*np.exp(np.cumsum(rng.normal(0,.01,600)))
        d=pd.DataFrame({'close':c,'open':c*.999,'high':c*1.01,'low':c*.99,'volume':1e6},index=pd.date_range('2020-01-01',periods=600,tz='UTC'))
        p,b=predict(d,'A',5);self.assertIn('logistica',p)
        self.assertTrue(all(0<=x<=1 for x in p.values()));self.assertGreaterEqual(b,0)
    def test_no_fake_score(self):
        self.assertEqual(summary([]),[]);self.assertIsNone(wilson(0,0))
        self.assertLess(wilson(5,10)[0],.5)
    def test_last_pattern_optimization_identical(self):
        rng=np.random.default_rng(55);c=100*np.exp(np.cumsum(rng.normal(0,.03,300)))
        d=pd.DataFrame({'close':c,'open':c*.99,'high':c*1.02,'low':c*.98,'volume':rng.uniform(1e5,1e6,300)})
        full=detect(d);last=detect(d,last_only=True)
        self.assertEqual({k:bool(v.iloc[-1]) for k,v in full.items()},{k:bool(v.iloc[-1]) for k,v in last.items()})
