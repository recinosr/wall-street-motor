import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from lab.pronostico import targets, save_once, digest, predict, wilson, features, summary
from lab.enciclopedia import detect

class ForecastTests(unittest.TestCase):
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
