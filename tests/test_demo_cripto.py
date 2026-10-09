import unittest
from datetime import datetime,timedelta,timezone
import pandas as pd
from lab.demo_cripto import initial,cycle,execute,new_account,eligible,digest,signal,corroborate
UTC=timezone.utc


def data(now):
    df=pd.DataFrame(dict(open=[100.]*400,high=[104.]*400,low=[95.]*400,close=[103.]*400,volume=[100.]*400),index=pd.date_range(now.date()-timedelta(days=400),periods=400,tz='UTC'))
    return dict(quote={'price':103.,'time':now.isoformat()},daily=df,coverage={'real_minutes':60})


class CryptoDemoTest(unittest.TestCase):
    def test_future_receipt_then_fill_and_fees(self):
        now=datetime(2026,10,9,0,10,tzinfo=UTC);d=data(now);d['daily'].loc[d['daily'].index[-3:],'close']=[101,102,103]
        state,events=cycle(initial(),{}, {'BTC':d},now,'1',{})
        pending=state['accounts']['BTC']['pending'];self.assertEqual(pending['rule'],'B');self.assertEqual(state['accounts']['BTC']['units'],0)
        later=now+timedelta(minutes=10);proof={'completed_at':(now+timedelta(minutes=1)).isoformat(),'run_id':'1'}
        d['quote']={'price':100,'time':later.isoformat()}
        state,events=cycle(state,{}, {'BTC':d},later,'2',{'1':proof})
        account=state['accounts']['BTC'];self.assertAlmostEqual(account['units'],1000/100/1.001)
        self.assertAlmostEqual(account['fees'],1000*.001/1.001);self.assertIsNone(account['pending'])
        self.assertEqual(account['position']['expires_at'],(later+timedelta(days=5)).isoformat())

    def test_no_backdated_fill_or_missing_receipt(self):
        now=datetime(2026,10,9,tzinfo=UTC);a=new_account();intent=dict(action='comprar',decided_at=now.isoformat())
        self.assertIsNone(execute(a,intent,dict(price=100,time=now.isoformat()),None,now))
        self.assertIsNone(execute(a,intent,dict(price=100,time=now.isoformat()),{'completed_at':now.isoformat()},now))
        self.assertEqual(a['cash'],1000)

    def test_idempotent_and_hash_chain(self):
        now=datetime(2026,10,9,4,tzinfo=UTC);state,events=cycle(initial(),{}, {},now,'1',{})
        same,new=cycle(state,{}, {},now,'1',{});self.assertEqual(state,same);self.assertEqual(new,[])
        self.assertEqual(events[1]['previous_hash'],events[0]['hash'])
        e=dict(events[0]);h=e.pop('hash');self.assertEqual(h,digest(e))

    def test_no_transfer_from_equity_pool_or_bearish(self):
        p=dict(id='martillo',direccion=1,extremo_velas=1,salidas=[dict(id='fijo_5',grupos={'universo':{'estado':'sirve_en_muestra'}})])
        self.assertEqual(eligible({'version':1,'completo':True,'items':[p]},'BTC'),[])

    def test_missed_daily_entry_not_replayed(self):
        now=datetime(2026,10,9,5,tzinfo=UTC);d=data(now);d['daily'].loc[d['daily'].index[-3:],'close']=[101,102,103]
        self.assertIsNone(signal('BTC',new_account(),d,{},now))

    def test_invalid_stop_reverts_account_and_no_charge(self):
        now=datetime(2026,10,9,tzinfo=UTC);later=now+timedelta(minutes=2);a=new_account()
        intent=dict(action='comprar',decided_at=now.isoformat(),exit='ratio_2',stop=110,id='x',rule='test')
        result=execute(a,intent,{'price':100,'time':later.isoformat()},{'completed_at':(now+timedelta(minutes=1)).isoformat()},later)
        self.assertEqual(result['action'],'cancelar');self.assertEqual(a['cash'],1000);self.assertEqual(a['fees'],0)

    def test_sale_cost_and_reference_same_budget(self):
        now=datetime(2026,10,9,4,tzinfo=UTC);d=data(now)
        state,events=cycle(initial(),{}, {'BTC':d},now,'1',{})
        a=state['accounts']['BTC'];self.assertAlmostEqual(a['hold_equity'],1000/1.001*.999)
        self.assertEqual(a['cash'],1000);self.assertGreater(a['vs_hold'],0)

    def test_rolling500_does_not_lose_counter(self):
        now=datetime(2026,10,9,4,tzinfo=UTC);state=initial();total=0
        for i in range(260):
            state,events=cycle(state,{}, {},now,str(i),{});total+=len(events)
        self.assertEqual(len(state['decisions']),500);self.assertEqual(state['total_decisions'],total)

    def test_second_exchange_freshness_and_disagreement(self):
        now=datetime(2026,10,9,4,tzinfo=UTC);quote=dict(price=100,time=now.isoformat())
        data={'error':[],'result':{'X':[['100.1','1',now.timestamp()]],'last':'cursor'}}
        self.assertLess(corroborate(quote,data,now)['relative_difference'],.005)
        data['result']['X'][0][0]='102'
        with self.assertRaises(ValueError):corroborate(quote,data,now)
        data['result']['X'][0]=['100','1',(now-timedelta(minutes=5)).timestamp()]
        with self.assertRaises(ValueError):corroborate(quote,data,now)

if __name__=='__main__': unittest.main()
