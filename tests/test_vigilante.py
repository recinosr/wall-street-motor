import datetime as dt
import unittest
from scripts.vigilante import due,health

class VigilanteTests(unittest.TestCase):
    def test_clock_and_retry(self):
        at=dt.datetime(2026,10,10,1,13,tzinfo=dt.timezone.utc)
        demo=[x for x in due(at) if x[0]=='demo-cripto.yml']
        self.assertEqual(demo,[x for x in due(at.replace(minute=14)) if x[0]=='demo-cripto.yml'])
        self.assertFalse(any(x[0]=='demo-cripto.yml' for x in due(at.replace(minute=12))))
        self.assertEqual(len(due(at)),len(set(due(at))))
    def test_partial_coverage_and_failed_dispatch(self):
        at=dt.datetime(2026,10,10,1,24,tzinfo=dt.timezone.utc)
        state={'desde':'2026-10-10T01:12:00+00:00','despachos':[
            {'workflow':'demo-cripto.yml','slot':'2026-10-10T01:10:00+00:00','aceptado':True}]}
        self.assertEqual(health(state,at)['ciclos_esperados_24h'],2)
        self.assertEqual(health(state,at)['ciclos_perdidos_24h'],1)
        state['despachos'][0]['aceptado']=False
        self.assertEqual(health(state,at)['ciclos_perdidos_24h'],2)
