import unittest
import numpy as np
import pandas as pd
from lab.carteras_robots import monthly_target,targets,run,crisis,decade_windows


class RobotsTests(unittest.TestCase):
    def test_dual_relative_and_absolute_use_only_completed_months(self):
        dates=pd.date_range('2020-01-31',periods=13,freq='ME')
        f=pd.DataFrame({'SPY':np.linspace(1,1.2,13),'VXUS':np.linspace(1,1.3,13),'BND':1.,'BIL':np.linspace(1,1.01,13)},index=dates)
        np.testing.assert_array_equal(monthly_target(f,'Dual Momentum'),[0,1,0,0])
        f['SPY']=np.linspace(1,.9,13);np.testing.assert_array_equal(monthly_target(f,'Dual Momentum'),[0,0,1,0])
        self.assertIsNone(monthly_target(f.iloc[:-1],'Dual Momentum'))

    def test_next_session_causality_and_missing_month_close(self):
        dates=pd.bdate_range('2020-01-02','2021-04-05')
        f=pd.DataFrame({s:np.arange(len(dates))+100. for s in ('SPY','VXUS','BND','BIL')},index=dates)
        t=targets(f,'Dual Momentum');first=min(t);self.assertEqual(dates[first],pd.Timestamp('2021-02-01'))
        altered=f.copy();altered.iloc[first:]=1e8
        np.testing.assert_array_equal(t[first],targets(altered,'Dual Momentum')[first])
        missing=f.drop(pd.Timestamp('2021-01-29'));self.assertNotIn(pd.Timestamp('2021-02-01'),[missing.index[i] for i in targets(missing,'Dual Momentum')])

    def test_cost_and_contributions_no_monthly_sales(self):
        dates=pd.to_datetime(['2020-01-02','2020-01-31','2020-02-03'])
        f=pd.DataFrame({'SPY':[1,2,2],'TLT':[1,1,1]},index=dates)
        a=run(f,{0:np.array([.5,.5])},monthly=50)
        b=run(f,{0:np.array([.5,.5])},monthly=100)
        self.assertAlmostEqual(a['fees'],100-100/1.001)
        self.assertAlmostEqual(b['serie'].iloc[-1],a['serie'].iloc[-1]*2)
        flat=run(pd.DataFrame({'A':[1.,1.,1.]},index=dates),{0:np.array([1.])})
        self.assertAlmostEqual(flat['unit'].iloc[-1],1/1.001)

    def test_faber_and_no_synthetic_2008_or_ten_years(self):
        dates=pd.date_range('2020-01-31',periods=10,freq='ME')
        f=pd.DataFrame({s:np.linspace(1,2,10) for s in ('SPY','TLT','GLD','VNQ','EFA','BIL')},index=dates)
        w=monthly_target(f,'Faber 10 meses');self.assertAlmostEqual(w.sum(),1);self.assertEqual(w[-1],0)
        f.iloc[-1,:5]=.1;self.assertEqual(monthly_target(f,'Faber 10 meses')[-1],1)
        s=pd.Series(np.linspace(1,2,10),index=dates)
        self.assertIsNone(crisis(s,s,2008)['correlacion']);self.assertEqual(decade_windows(s,s,s),[])


if __name__=='__main__':unittest.main()
