import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from lab import enciclopedia as E
from lab.ict import correct

def fixture(n=300):
    rng=np.random.default_rng(19);c=100*np.exp(np.cumsum(rng.normal(0,.025,n)))
    return pd.DataFrame(dict(open=c*.999,high=c*1.005,low=c*.995,close=c,volume=1000),index=pd.date_range('2024-01-01',periods=n,tz='UTC'))

class ICTTest(unittest.TestCase):
    def test_all_ten_rules_preserve_prefix_when_future_changes(self):
        d=fixture();prefix=E.ict_signals(d.iloc[:200]);changed=d.copy();changed.iloc[200:,:4]*=5
        self.assertEqual(len(prefix),10)
        for name,series in E.ict_signals(changed).items():pd.testing.assert_series_equal(series.iloc[:200],prefix[name])

    def test_sweep_confirms_next_day_against_original_range(self):
        d=pd.DataFrame(dict(open=[100.]*25,high=[110.]*25,low=[90.]*25,close=[100.]*25,volume=1000),index=pd.date_range('2024-01-01',periods=25,tz='UTC'))
        d.iloc[20,:4]=[95,105,80,85];d.iloc[21,:4]=[85,105,84,95]
        p=E.ict_signals(d);self.assertFalse(p['barrido_minimo_mismo'].iat[20]);self.assertTrue(p['barrido_minimo_siguiente'].iat[21])
        self.assertFalse(p['barrido_minimo_siguiente'].iat[20])
        short=d.iloc[:21];self.assertFalse(E.ict_signals(short)['barrido_minimo_siguiente'].iat[-1])

    def test_bear_sweep_and_three_candle_gap(self):
        d=fixture(30);d.iloc[:,:4]=[100,110,90,100];d.iloc[20,:4]=[100,120,95,105]
        self.assertTrue(E.ict_signals(d)['barrido_maximo_mismo'].iat[20])
        d.iloc[22,:4]=[125,130,121,126]
        self.assertTrue(E.ict_signals(d)['brecha_valor_alcista'].iat[22])

    def test_custom_temporal_cut_is_used_by_events_and_controls(self):
        d=fixture();defs=[p for p in E.catalog() if p['id']=='brecha_valor_alcista']
        with patch.object(E,'SPLIT','2024-07-01'):
            measured=E.measure_asset('TEST',d,defs)
        events=measured['brecha_valor_alcista|fijo_1'];self.assertTrue(events)
        for e in events:self.assertEqual(e['period'],'antes2016' if e['date']<'2024-07-01' else 'desde2016')
        self.assertEqual({e['period'] for e in events},{'antes2016','desde2016'})

    def test_bh_includes_prior_and_new_rules_in_one_family(self):
        import copy
        sample={'n':31,'p_normal':1.,'p_azar':1.,'media_neta':.01,'exceso_normal':.01,'exceso_azar':.01}
        def item(name):
            return {'id':name,'direccion':1,'salidas':[{'id':'fijo_1','grupos':{asset:{p:copy.deepcopy(sample) for p in ('total','antes2016','desde2016')} for asset in ('universo','BTC-USD','ETH-USD')}}]}
        report={'items':[item('previa'),item('nueva')]}
        s=report['items'][1]['salidas'][0]['grupos']['universo']['total'];s['p_normal']=.001;s['p_azar']=.01
        correct(report);self.assertEqual(report['pruebas_BH'],36)
        self.assertAlmostEqual(s['q_normal'],.036);self.assertAlmostEqual(s['q_azar'],.18);self.assertFalse(s['pasa_BH'])
