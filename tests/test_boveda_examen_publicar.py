import tempfile
import unittest
from pathlib import Path
import json
from lab.boveda_examen_publicar import empacar


class EmpaqueTest(unittest.TestCase):
    def test_all_questions_preserved_exactly_and_idempotent_without_ohlc(self):
        questions = [{'sim': s, 'fecha': '2020-01-01', 'horizonte': h,
                      'pronosticos': {'ingenuo': {'p_sube': .6}}, 'retorno': .1,
                      'revelaciones': [{'retorno': .1}], 'contexto': [{'retorno': 0.}]}
                     for s in ('SPY', 'BTC-USD') for h in (30, 1000)]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'boveda_examenes.json'
            path.write_text(json.dumps({'firma': 'test', 'ejemplos': questions}), encoding='utf8')
            m = empacar(td); self.assertEqual(len(m['ejemplos']), 4)
            self.assertFalse(any('retorno' in q for q in m['ejemplos']))
            restored = []
            for fragment in m['fragmentos']:
                restored.extend(json.loads((Path(td)/fragment['archivo']).read_text(encoding='utf8'))['ejemplos'])
            self.assertEqual(sorted(restored,key=str), sorted(questions,key=str))
            self.assertEqual(empacar(td), m)
