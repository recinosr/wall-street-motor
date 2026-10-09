import unittest
import json
import numpy as np
import pandas as pd
from lab.enciclopedia import catalog,detect,trade,bh,summarize,net_return,measure_asset,aggregate_dates,merge_dates


def fixture(n=260):
    rng=np.random.default_rng(11); c=100*np.exp(np.cumsum(rng.normal(0,.01,n)))
    return pd.DataFrame(dict(open=c*.997,high=c*1.02,low=c*.98,close=c,volume=np.full(n,1000)),
                        index=pd.date_range('2017-01-01',periods=n,tz='UTC'))


class EncyclopediaTest(unittest.TestCase):
    def test_catalog_and_every_detector_is_causal(self):
        d=fixture(); all_signals=detect(d); prefix=detect(d.iloc[:220])
        self.assertEqual(set(all_signals),{p['id'] for p in catalog()})
        self.assertGreaterEqual(sum(p['familia']=='vela' for p in catalog()),30)
        for key in all_signals:
            pd.testing.assert_series_equal(all_signals[key].iloc[:220],prefix[key],check_names=False)
        changed=d.copy(); changed.iloc[220:,:4]*=5
        for key,values in detect(changed).items():
            pd.testing.assert_series_equal(values.iloc[:220],prefix[key],check_names=False)

    def test_stop_gap_and_same_bar_pessimism(self):
        d=fixture(30); d.iloc[1,:4]=[100,120,80,100]
        net,h,r=trade(d,0,'ratio_2',1,90)
        self.assertEqual(h,1); self.assertAlmostEqual(net,net_return(100,90)); self.assertLess(r,-1)
        d.iloc[1,:4]=[100,105,95,100];d.iloc[2,:4]=[80,85,75,82]
        net,h,r=trade(d,0,'ratio_2',1,90)
        self.assertEqual(h,2); self.assertAlmostEqual(net,net_return(100,80))

    def test_next_open_and_unmatured(self):
        d=fixture(30);d.iloc[1,0]=50;d.iloc[1,3]=100
        self.assertAlmostEqual(trade(d,0,'fijo_1',1)[0],net_return(50,100))
        self.assertIsNone(trade(d,29,'fijo_1',1))
        self.assertIsNone(trade(d,0,'ratio_1',1,60))

    def test_batch_prices_equal_reference(self):
        d=fixture(70);prices=d[['open','high','low','close']].to_numpy(float)
        for i in range(0,50,7):
            for mode in ['fijo_1','fijo_5','ratio_1','ratio_3']:
                for direction in [-1,1]:
                    stop=float(d.close.iat[i])*(.97 if direction==1 else 1.03)
                    self.assertEqual(trade(d,i,mode,direction,stop),trade(d,i,mode,direction,stop,prices))

    def test_occupied_schedule_equals_pairwise_reference(self):
        rng=np.random.default_rng(17)
        for h in [1,5,10,20]:
            chosen=[];fast=[];occupied=np.zeros(300,dtype=bool)
            for j in rng.permutation(np.arange(280)):
                if all(j>=end or j+h<=start for start,end in chosen): chosen.append((j,j+h))
                if not occupied[j:j+h].any(): fast.append((j,j+h));occupied[j:j+h]=True
            self.assertEqual(chosen,fast)

    def test_derived_batch_is_json_serializable(self):
        events=measure_asset('fixture',fixture(260))
        restored=json.loads(json.dumps(events,allow_nan=False))
        self.assertEqual(set(restored),set(events))
        self.assertTrue(any(restored.values()))

    def test_split_prevents_leakage(self):
        d=fixture(30); d.index=pd.date_range('2015-12-25',periods=30,tz='UTC')
        self.assertIsNone(trade(d,0,'fijo_10',1))

    def test_bh_counts_nulls_and_small_sample(self):
        self.assertAlmostEqual(bh({'a':.001,'b':.02,'c':1})['b'],.03)
        self.assertEqual(summarize([])['p_normal'],1)

    def test_date_clusters_and_r(self):
        events=[dict(date=f'2020-01-{i:02}',net=.01,normal=0,random=0,r=1) for i in range(1,25)]*4
        s=summarize(events);self.assertEqual(s['n'],96);self.assertEqual(s['fechas'],24)
        self.assertEqual(s['p_normal'],1);self.assertEqual(s['esperanza_R'],1)

    def test_sufficient_statistics_preserve_measurement(self):
        events=[dict(date=f'2020-02-{i:02}',net=.01*i,normal=.002,random=-.003,r=i/2) for i in range(1,25)]*4
        a=aggregate_dates(events[:40]);merge_dates(a,aggregate_dates(events[40:]))
        self.assertEqual(summarize(events),summarize(a))

if __name__=='__main__': unittest.main()
