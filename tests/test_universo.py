import unittest
import pandas as pd
from lab.universo import listed, metrics, inverse
from lab.sp500 import CONCEPTOS

class UniverseTests(unittest.TestCase):
    def test_official_filter(self):
        text='Symbol|Security Name|Test Issue|ETF|Market Category\nA|Alpha|N|N|Q\nB|Beta ETF|N|Y|G\nC|Some Warrants|N|N|Q\nD|Test|Y|N|Q\nFile Creation Time: now||||\n'
        rows=listed(text,'test')
        self.assertEqual([r['sim'] for r in rows],['A','B'])
        self.assertEqual(rows[1]['tipo'],'ETF')
    def test_null_volume_and_momentum(self):
        d=pd.DataFrame({'close':[100.,90.,110.]},index=pd.date_range('2020-01-01',periods=3,tz='UTC'))
        m=metrics(d)
        self.assertIsNone(m['volumen_medio_usd'])
        self.assertIsNone(m['momentum_12m_pct'])
        self.assertAlmostEqual(m['peor_caida_pct'],-10)
        self.assertNotIn('precio',m)
    def test_inverse_partial(self):
        r=inverse({'etfs':[{'sim':'VT','top':[{'sim':'A','peso_pct':2}]}]})
        self.assertEqual(r['empresas']['A'][0]['peso_pct'],2)
        self.assertIn('top10',r['cobertura'])
    def test_xom_alternative(self):
        self.assertIn('RevenueFromContractWithCustomerIncludingAssessedTax',CONCEPTOS['ingresos'])
