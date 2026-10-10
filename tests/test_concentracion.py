import unittest
import numpy as np
from lab.concentracion import random_portfolios,momentum_portfolio,buy,statistics,RATE,FEE

class ConcentrationTest(unittest.TestCase):
    def test_constant_prices_lose_exact_costs_inside_budget(self):
        p=np.ones((61,55))*100
        values,fan,eligible=random_portfolios(p,50,100,np.random.default_rng(3))
        expected=60*buy(100,50)*(1-RATE)-50*FEE
        np.testing.assert_allclose(values,expected);self.assertEqual(eligible,55)
        self.assertEqual(fan[-1]['aportes'],6000);self.assertTrue(fan[-1]['liquidacion'])
        self.assertEqual(statistics(values,6000,6000)['pierde_pct'],100)

    def test_missing_future_is_excluded_not_reranked(self):
        p=np.ones((26,2))*100;p[14,0]=np.nan
        values,_,_=random_portfolios(p,2,50,np.random.default_rng(1));self.assertTrue(np.isnan(values).all())
        value,history=momentum_portfolio(p,13,12,2);self.assertTrue(np.isnan(value));self.assertEqual(len(history),1)

    def test_momentum_ignores_execution_and_later_price_for_first_choice(self):
        p=np.ones((39,4))*100;p[12,1]=200
        _,first=momentum_portfolio(p,13,24,1)
        changed=p.copy();changed[13:,3]=10000
        _,other=momentum_portfolio(changed,13,24,1)
        self.assertEqual(first[0]['indices'],[1]);self.assertEqual(first[0],other[0])
        self.assertEqual(first[0]['momento_conocido'],12)
        missing=p.copy();missing[13,1]=np.nan
        value,choice=momentum_portfolio(missing,13,24,1)
        self.assertTrue(np.isnan(value));self.assertEqual(choice[0],first[0])

    def test_x5_is_total_contributions_and_nan_counted(self):
        d=statistics([499,500,np.nan,99],100,200)
        self.assertEqual(d['n'],3);self.assertAlmostEqual(d['x5_pct'],100/3)
