import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lab.boveda_examen_auditar import auditar
from lab.boveda_examen_publicar import anotar_auditoria


class AuditTest(unittest.TestCase):
    def test_exact_block_signs_and_original_unchanged_with_exclusive_audit(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            original={'firma':'test','ganador_congelado':'ingenuo','familia_ajuste_busqueda':1000,
                      'metricas':[{'ventaja':True,'sim':'SPY','horizonte':60,'metodo':'extra','n':4,'p':.00001,'habilidad':.2}]}
            path=root/'boveda_rondas.json';path.write_text(json.dumps(original),encoding='utf8');before=path.read_bytes()
            rows=[{'fecha':t,'retorno':.1,'pronosticos':{'ingenuo':{'p_sube':.5},'extra':{'p_sube':.9}}}
                  for t in ('2019-01-01','2019-06-01','2019-09-01','2020-02-01')]
            (root/'boveda_examen_SPY_60.json').write_text(json.dumps({'firma':'test','ejemplos':rows}),encoding='utf8')
            with patch('lab.boveda_examen_auditar.OUT',root),patch('builtins.print'):
                auditar()
                with self.assertRaises(FileExistsError):auditar()
            a=json.loads((root/'boveda_examen_auditoria.json').read_text(encoding='utf8'))
            self.assertEqual(a['pruebas'][0]['p_signos_sensibilidad'],1/16)
            self.assertFalse(a['pruebas'][0]['supera_sensibilidad'])
            self.assertEqual(path.read_bytes(),before)
            (root/'boveda_examenes.json').write_text(json.dumps({'firma':'test','ejemplos':[]}),encoding='utf8')
            anotar_auditoria(root)
            self.assertEqual(json.loads((root/'boveda_examenes.json').read_text(encoding='utf8'))['auditoria'],a)
