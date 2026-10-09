import tempfile
import unittest
import numpy as np
import pandas as pd
from lab.robots import signals,simulate,random_control

class RobotTests(unittest.TestCase):
    def data(self):
        c=np.full(120,100.)
        return pd.DataFrame({'open':c,'high':c+.1,'low':c-.1,'close':c,'volume':1000.},index=pd.date_range('2024-01-01',periods=120,freq='h',tz='UTC'))
    def test_no_trade_cash(self):
        d=self.data();v,tr,g=simulate(d,np.zeros(120,bool),np.zeros(120,bool),'BinHV45',3600)
        self.assertTrue((v==1000).all());self.assertEqual(tr,[])
    def test_entry_future_open_and_two_costs(self):
        d=self.data();entry=np.zeros(120,bool);entry[100]=True
        v,tr,_=simulate(d,entry,np.zeros(120,bool),'BinHV45',3600)
        self.assertEqual(tr[0]['inicio'],101)
        self.assertAlmostEqual(v[-1],1000*.999/1.001)
    def test_stop_first_on_ambiguous_bar(self):
        d=self.data();d.loc[d.index[101],['high','low']]=[110.,90.]
        entry=np.zeros(120,bool);entry[100]=True
        v,tr,_=simulate(d,entry,np.zeros(120,bool),'BinHV45',3600)
        self.assertAlmostEqual(tr[0]['neto'],-.05)
    def test_signals_only_use_past(self):
        d=self.data();a=signals(d);d.iloc[110:,d.columns.get_loc('close')]=1e6;b=signals(d)
        for key in a:
            for x,y in zip(a[key],b[key]):pd.testing.assert_series_equal(x.iloc[:110],y.iloc[:110])
    def test_random_equal_count_duration(self):
        d=self.data();tr=[{'inicio':101,'fin':103},{'inicio':105,'fin':109}]
        values=random_control(d,tr,trials=5)
        self.assertEqual(len(values),5)
        self.assertTrue(all(abs(x-((.999/1.001)**2-1))<1e-10 for x in values))
