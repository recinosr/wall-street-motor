import unittest
import json,os,tempfile
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from lab.universo import listed, metrics, inverse,refresh_sec
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
    def test_common_partnership_units_are_equity_not_warrants(self):
        text='Symbol|Security Name|Test Issue|ETF|Market Category\nET|Energy Transfer Common Units|N|N|Q\nW|Units with Warrants|N|N|Q\n'
        self.assertEqual([r['sim'] for r in listed(text,'test')],['ET'])
    def test_xom_redomiciliation_even_if_wiki_updated(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'u.json';p.write_text(json.dumps({'datos':[{'sim':'XOM','tipo':'acción','cik':2115436,'fecha':'2026-10-08'}]}))
            fund={34088:{'ingresos':{'valor':100,'periodo':'CY2025','presentado':None}},2115436:{'patrimonio':{'valor':9}}}
            with patch.dict(os.environ,{'SEC_CONTACT':'solo prueba'}),patch('lab.sp500.lista',return_value=[{'sim':'XOM','cik':2115436}]),patch('lab.sp500.fundamentales',return_value=fund) as f:
                refresh_sec(p)
                self.assertIn(34088,f.call_args.args[0])
            r=json.loads(p.read_text(encoding='utf8'))['datos'][0]
            self.assertEqual(r['fundamentales']['ingresos'],100)
            self.assertEqual(r['cik_fundamentales_anuales'],34088)
            self.assertEqual(r['cik'],2115436)
            self.assertEqual(r['fecha'],'2026-10-08')
