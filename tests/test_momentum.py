import unittest
import numpy as np
import pandas as pd
from types import SimpleNamespace
from unittest.mock import patch
from lab.carteras import annual_relative,PORTFOLIOS
from lab.etfs import CATALOGO,TER_FICHA,ficha

class MomentumTests(unittest.TestCase):
    def test_issuer_overrides_stale_provider(self):
        fund=SimpleNamespace(fund_operations=pd.DataFrame({'value':{'Annual Report Expense Ratio':.003}}),
                             top_holdings=None,sector_weightings={},fund_overview={})
        ticker=SimpleNamespace(history=lambda **kwargs:pd.DataFrame({'Close':[]}),info={},funds_data=fund)
        with patch('lab.etfs.yf.Ticker',return_value=ticker):
            item=ficha('IWMO.L','Momentum','Momentum desarrollado','Irlanda','acumula',.72)
        self.assertEqual(item['gasto_proveedor_pct'],.3)
        self.assertEqual(item['gasto_anual_pct'],.25)
        self.assertIn('ishares.com',item['fuente_gasto'])
    def test_real_allocations_and_issuer_cost(self):
        self.assertEqual(PORTFOLIOS['80/20 mundo/momentum Irlanda'],{'VWRA.L':.8,'IWMO.L':.2})
        self.assertEqual(PORTFOLIOS['80/20 mundo/momentum EEUU'],{'VT':.8,'MTUM':.2})
        self.assertTrue({'IWMO.L','MTUM'} <= {r[0] for r in CATALOGO})
        self.assertEqual(TER_FICHA['IWMO.L'][0],.25)
    def test_partial_year_excluded_streak_and_same_dates(self):
        dates=pd.to_datetime(['2019-12-31','2020-12-31','2021-12-31','2022-12-30','2023-12-29','2024-06-28'])
        f=pd.DataFrame({'A':[1,.9,.8,1,.9,10.]},index=dates)
        b=pd.Series([1,1,1,1,1,1.],index=dates)
        result=annual_relative(f,[1],b)
        self.assertEqual([r['anio'] for r in result['anios']],[2020,2021,2022,2023])
        self.assertEqual(result['perdedores_seguidos'],2)
        self.assertEqual(result['negativos_seguidos'],2)
        self.assertLess(result['peor_anio_relativo_pp'],-10)
