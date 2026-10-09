import json
import tempfile
import unittest
from pathlib import Path
from lab.vita_diario import build


class DiaryTests(unittest.TestCase):
    def test_missing_and_stale_not_invented(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'marcador.json').write_text(json.dumps({'actualizado':'2026-10-08','etiquetas':0,'acumulado':[]}),encoding='utf8')
            d=build(folder,'2026-10-09')
            self.assertEqual(d['que_probo_hoy'],[])
            self.assertEqual(d['como_voy']['pronosticos'],[])
            self.assertEqual(d,build(folder,'2026-10-09'))
            self.assertIn('demo_cripto',d['fuentes_no_disponibles'])

    def test_only_measured_fields_no_account_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'demo_cripto.json').write_text(json.dumps({'observado_en':'2026-10-09','accounts':{'BTC':{'initial':1000,'net_liquidation':995,'hold_equity':1001,'vs_hold':-6,'correo':'privado','clave':'secreto'}}}),encoding='utf8')
            d=build(folder,'2026-10-09')
            self.assertEqual(len(d['que_probo_hoy']),1)
            self.assertEqual(d['como_voy']['demo_contra_mantener']['BTC']['vs_hold'],-6)
            self.assertNotIn('secreto',json.dumps(d))
            self.assertTrue(any('US$995.00 frente a US$1,001.00' in s for s in d['frases']))
            self.assertTrue(3<=len(d['frases'])<=5)

    def test_patterns_criteria_not_individual_significance(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'enciclopedia.json').write_text(json.dumps({'patrones':75,'patrones_pasan':0,'pruebas_pasan_BH':93,'begin':'2000-01-01','end_exclusive':'2025-04-01'}),encoding='utf8')
            Path(folder,'robots.json').write_text(json.dumps({'casos':[{'estrategia':'a','supera_ambos':False},{'estrategia':'b','supera_ambos':True}]}),encoding='utf8')
            d=build(folder,'2026-10-09')
            self.assertIn('75 patrones: 0 pasan',d['frases'][0])
            self.assertIn('2 robots en 2 casos históricos: 1 superan',d['frases'][1])
            self.assertNotIn('93 pasan',d['frases'][0])


if __name__=='__main__':unittest.main()
