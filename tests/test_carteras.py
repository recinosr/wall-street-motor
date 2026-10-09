import unittest
import numpy as np
import pandas as pd
from unittest.mock import patch
from lab.carteras import net_index,simulate,rebalance,performance,PORTFOLIOS,calendar_flags,schedule,monthly_wins,windows

class PortfolioTests(unittest.TestCase):
    def test_tax_not_double_adjusted(self):
        h=pd.DataFrame({'Close':[100,95],'Dividends':[0,5]})
        self.assertAlmostEqual(net_index(h,.3).iloc[-1],.985)
        self.assertAlmostEqual(net_index(h,0).iloc[-1],1)
    def test_cost_inside_budget(self):
        f=pd.DataFrame({'A':[1.,1.,1.]},index=pd.to_datetime(['2026-01-02','2026-01-05','2026-01-06']))
        s=simulate(f,[1.],100)
        self.assertEqual(s['aportado'],100)
        self.assertAlmostEqual(s['valor_final'],100/1.001)
        self.assertAlmostEqual(simulate(f,[1.],50)['valor_final'],s['valor_final']/2)
    def test_rebalance_only_changes(self):
        p=np.array([80.,20.]);r=rebalance(p,np.array([.5,.5]))
        self.assertAlmostEqual(r.sum()+.001*np.abs(r-p).sum(),100)
        np.testing.assert_array_equal(rebalance(np.array([50.,50.]),np.array([.5,.5])),[50,50])
    def test_partial_month_end_stays_cash(self):
        f=pd.DataFrame({'A':[1.,2.]},index=pd.to_datetime(['2026-10-01','2026-10-08']))
        self.assertAlmostEqual(simulate(f,[1.],rule='fin')['valor_final'],100)
        self.assertEqual(monthly_wins(f,np.array([1.]),'fin',calendar_flags(f.index))['meses_completos'],0)
    def test_drop_signal_executes_after_known_close(self):
        f=pd.DataFrame({'A':[1.,.94,.90]},index=pd.to_datetime(['2026-10-01','2026-10-02','2026-10-05']))
        orders,_=schedule(f,np.array([1.]),'caida')
        self.assertFalse(orders[1]);self.assertTrue(orders[2])
    def test_drawdown_ignores_contributions(self):
        p=performance(np.array([1.,.7,1.]),pd.to_datetime(['2020-01-01','2020-02-01','2020-03-01']))
        self.assertAlmostEqual(p['peor_caida_pct'],-30)
        self.assertFalse(p['sin_recuperar'])
    def test_declared_weights(self):
        self.assertEqual(len(PORTFOLIOS),27)
        for alloc in PORTFOLIOS.values():self.assertAlmostEqual(sum(alloc.values()),1)
    def test_worst_window_not_truncated_by_benchmark_launch(self):
        idx=pd.bdate_range('1999-01-04','2020-01-06');f=pd.DataFrame({'A':1.},index=idx)
        benchmark=pd.Series(1.,index=idx[idx>='2008-01-02'])
        def fake(frame,weights,monthly,**kwargs):return {'unit':np.ones(len(frame)),'valor_final':100.}
        with patch('lab.carteras.simulate',side_effect=fake):result,common=windows(f,[1.],benchmark)
        self.assertEqual(result[0]['desde'],'1999-01-04')
        self.assertIsNone(result[0]['mundo'])
        self.assertTrue(any(r['mundo'] is not None for r in result))
    def test_comparison_uses_common_sessions_without_filling(self):
        idx=pd.bdate_range('2009-01-02','2020-01-06');f=pd.DataFrame({'A':1.},index=idx)
        benchmark=pd.Series(1.,index=idx.delete(100))
        def fake(frame,weights,monthly,**kwargs):
            self.assertFalse(frame.isna().any().any())
            return {'unit':np.ones(len(frame)),'valor_final':float(len(frame))}
        with patch('lab.carteras.simulate',side_effect=fake):result,_=windows(f,[1.],benchmark)
        self.assertEqual(result[0]['mundo'],result[0]['valor_comparable'])
        self.assertEqual(result[0]['valor']-result[0]['valor_comparable'],1)
