import unittest
import tempfile
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pandas as pd
from lab.vita_opera import initial, cycle, trend, active, rebalance, wallet, digest, audit, prudent
from scripts.vigilante import due


class VitaOperaTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,10,12,tzinfo=timezone.utc)
        d=pd.DataFrame({'close':range(100,900)},index=pd.date_range('2024-08-01',periods=800,tz='UTC'))
        self.market={'BTC':dict(daily=d,quote=dict(price=900.,time=self.now.isoformat()),predictions={'logistica':.6})}

    def test_receipt_future_price_and_idempotence(self):
        s,e=cycle(initial(),self.market,{},self.now,'123',{})
        self.assertFalse(any(x['action']=='comprar' for x in e))
        proof={'123':dict(completed_at=(self.now+timedelta(seconds=30)).isoformat())}
        stale,_=cycle(s,self.market,{},self.now+timedelta(minutes=1),'124',proof)
        self.assertEqual(stale['accounts']['BTC']['activa']['units'],0)
        later=self.now+timedelta(minutes=2);self.market['BTC']['quote']['time']=later.isoformat()
        s,e=cycle(s,self.market,{},later,'124',proof)
        buys=[x for x in e if x['action']=='comprar'];self.assertEqual(len(buys),2)
        self.assertGreater(s['accounts']['BTC']['activa']['units'],0)
        again,events=cycle(s,self.market,{},later,'124',proof)
        self.assertEqual(events,[]);self.assertEqual(s,again)
        self.assertEqual(s['accounts']['BTC']['prudente']['cash'],1000)

    def test_hash_chain(self):
        s,events=cycle(initial(),self.market,{},self.now,'123',{})
        prev='0'*64
        for e in events:
            self.assertEqual(e['previous_hash'],prev)
            self.assertEqual(e['hash'],digest({k:v for k,v in e.items() if k!='hash'}));prev=e['hash']
        self.assertEqual(prev,s['ledger_hash'])
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'2026-10.jsonl';path.write_text('\n'.join(json.dumps(e) for e in events),encoding='utf8')
            audit(s,Path(td))
            path.write_text(path.read_text(encoding='utf8').replace('intencion','comprar'),encoding='utf8')
            with self.assertRaises(ValueError):audit(s,Path(td))

    def test_month_current_excluded_and_target_vol(self):
        d=self.market['BTC']['daily'];a=trend(d,self.now,True)
        d=d.copy();d.loc[pd.Timestamp('2026-10-09',tz='UTC'),'close']=1e9
        # Un mes en curso jamás cambia la señal mensual (sí puede cambiar vol).
        self.assertEqual(trend(d,self.now,False),trend(self.market['BTC']['daily'],self.now,False))
        self.assertGreater(a[0],0);self.assertLessEqual(a[0],1)

    def test_brier_selection_thresholds(self):
        m={'acumulado':[dict(sector='Todos',tipo='cripto',horizonte=1,dias=30,predictor='momentum_12_1',brier=.1)]}
        self.assertEqual(active({'logistica':.6,'momentum_12_1':0},m,True,1)[0],0)
        m['acumulado'][0]['dias']=29
        self.assertEqual(active({'logistica':.55},m,True,.3)[0],.3)
        self.assertEqual(active({},m,True,0)[0],0)

    def test_costs_and_random_hold_same_costs(self):
        a=wallet();rebalance(a,1,100);self.assertAlmostEqual(a['cash'],0)
        self.assertAlmostEqual(a['units'],1000/100.1)
        rebalance(a,0,100);self.assertAlmostEqual(a['cash'],1000*(1-.001)/(1+.001))

    def test_active_max_one_execution_daily(self):
        s,_=cycle(initial(),self.market,{},self.now,'123',{})
        later=self.now+timedelta(minutes=2);self.market['BTC']['quote']['time']=later.isoformat()
        s,_=cycle(s,self.market,{},later,'124',{'123':dict(completed_at=self.now.isoformat())})
        self.assertIsNone(s['accounts']['BTC']['activa']['pending'])

    def test_old_frequencies_unchanged(self):
        for minute in (9,19,29,39,49,59):
            tasks=due(self.now.replace(minute=minute))
            for name in ('demo-cripto.yml','aprendiz.yml','escuela.yml','vita-opera.yml'):
                self.assertEqual(sum(n==name for n,_ in tasks),1)

    def test_stock_rotation_requires_whole_universe_and_one_winner(self):
        market={s:self.market['BTC'] for s in ('VT','QQQ','NFLX','MCD')}
        state,events=cycle(initial(),market,{},self.now,'123',{})
        intents=[e for e in events if e['action']=='intencion' and e['account']=='tendencia']
        self.assertEqual(sum(e['target']>0 for e in intents),1)
        del market['MCD']
        _,events=cycle(initial(),market,{},self.now,'123',{})
        self.assertFalse(any(e['action']=='intencion' and e['account']=='tendencia' for e in events))

    def test_active_stock_daily_signal_after_previous_fill(self):
        yesterday=self.now-timedelta(days=1);self.market['BTC']['quote']['time']=yesterday.isoformat()
        s,_=cycle(initial(),self.market,{},yesterday,'123',{})
        self.market['BTC']['quote']['time']=self.now.isoformat()
        s,events=cycle(s,self.market,{},self.now,'124',{'123':dict(completed_at=(yesterday+timedelta(minutes=1)).isoformat())})
        self.assertEqual(sum(e['action']=='comprar' and e['account']=='activa' for e in events),1)
        self.assertIsNotNone(s['accounts']['BTC']['activa']['pending'])
        later=self.now+timedelta(minutes=1);self.market['BTC']['quote']['time']=later.isoformat()
        self.market['BTC']['quote']['price']=950.
        updated,events=cycle(s,self.market,{},later,'125',{'124':dict(completed_at=self.now.isoformat())})
        self.assertFalse(any(e['action'] in ('comprar','vender') and e['account']=='activa' for e in events))
        self.assertEqual(updated['accounts']['BTC']['activa']['quote_time'],later.isoformat())
        self.assertGreater(updated['accounts']['BTC']['activa']['equity'],s['accounts']['BTC']['activa']['equity'])

    def test_prudente_requires_asset_BH_and_stability(self):
        report={'version':1,'completo':True,'items':[{'direccion':1,'salidas':[{'id':'fijo_5','grupos':{'universo':{'estado':'sirve_en_muestra'}}}]}]}
        self.assertEqual(prudent('BTC',wallet(),self.market['BTC']['daily'],report,self.now,900)[0],0)

    def test_bolsa_daily_dispatch_weekdays_only(self):
        for day in (9,10):
            tasks=due(self.now.replace(day=day,hour=22,minute=49))
            self.assertEqual(sum(flow=='vita-opera-bolsa.yml' for flow,slot in tasks),int(day==9))
