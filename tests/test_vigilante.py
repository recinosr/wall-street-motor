import datetime as dt
import unittest
from unittest.mock import patch
from scripts.vigilante import due,health

class VigilanteTests(unittest.TestCase):
    def test_boveda_weekly_only_after_fast_verified_trial_and_same_slot(self):
        at=dt.datetime(2026,10,11,4,40,tzinfo=dt.timezone.utc)
        only=lambda t:[x for x in due(t) if x[0]=='boveda.yml']
        self.assertEqual(only(at.replace(minute=39)),[])
        self.assertEqual(only(at),only(at.replace(minute=55)))
        self.assertEqual(only(at),[('boveda.yml',at.isoformat())])
        self.assertEqual(only(at+dt.timedelta(days=1)),[])
        with patch('scripts.vigilante.BOVEDA_VERIFICADA_SEGUNDOS',1200):
            self.assertEqual(only(at),[])
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
