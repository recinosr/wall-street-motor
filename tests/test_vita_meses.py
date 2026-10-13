import unittest
from unittest.mock import patch
from datetime import datetime,timezone
from lab.vita_meses import validate,CONFIG,before_open,generate,proof


class VitaMesTests(unittest.TestCase):
    def test_diez_probabilidades_exactas(self):
        data={'pronosticos':{s:{'p_sube':.55,'razon':'Hipótesis'} for s in CONFIG['activos']}}
        self.assertEqual(len(validate(data)),10)
        for invalid in (float('nan'),-1,2,True,'0.5'):
            data['pronosticos']['SPY']['p_sube']=invalid
            with self.assertRaises(ValueError):validate(data)

    def test_rechaza_activos_extras_y_faltantes(self):
        with self.assertRaises(ValueError):validate({'pronosticos':{}})
        with self.assertRaises(ValueError):validate({'pronosticos':{s:{'p_sube':.5,'razon':''} for s in CONFIG['activos']+['AAPL']}})

    def test_apertura_futura_y_feriado(self):
        self.assertIsNotNone(before_open(datetime(2026,10,13,12,tzinfo=timezone.utc)))
        self.assertIsNone(before_open(datetime(2026,10,13,15,tzinfo=timezone.utc)))
        self.assertIsNone(before_open(datetime(2026,10,11,12,tzinfo=timezone.utc)))

    def test_sin_gratuidad_no_llamada(self):
        with patch.dict('os.environ',{},clear=True),patch('lab.vita_meses.requests.post') as request:
            self.assertIn('gratuito',generate(datetime(2026,10,13,12,tzinfo=timezone.utc)))
            request.assert_not_called()

    def test_no_pasado_llm(self):
        self.assertIn('inicio',generate(datetime(2018,10,1,12,tzinfo=timezone.utc)))

    def test_recibo_tardio_no_cuenta(self):
        from types import SimpleNamespace
        payload={'run_id':'123','deadline':'2026-10-13T13:30:00Z'}
        response=SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'status':'completed','conclusion':'success','updated_at':'2026-10-13T13:31:00Z'})
        with patch('lab.vita_meses.receipt',return_value={'commit':'abc'}),patch('lab.vita_meses.requests.get',return_value=response),patch.dict('os.environ',{'GH_TOKEN':'prueba'}):
            self.assertIsNone(proof(None,payload))

    def test_sin_recibo_no_consulta_ni_califica(self):
        with patch('lab.vita_meses.receipt',return_value=None),patch('lab.vita_meses.requests.get') as request:
            self.assertIsNone(proof(None,{}));request.assert_not_called()


if __name__=='__main__':unittest.main()
