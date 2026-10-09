"""Demo de reglas registradas, dinero ficticio, nunca brokers.

A y B conservan su señal diaria/mensual BTC. No se convierten en reglas1min.
Una intención guardada espera otra corrida EXITOSA y una cotización posterior
al recibo Actions antes de ejecutarse. Las demoras se registran: no se compra
retrospectivamente en una apertura perdida. Stops observados cada~10min,
ejecución diferida con cotización fresca, distinta del ensayo diario ideal.
"""
import copy
import hashlib
import json
import os
from datetime import datetime,timedelta,timezone
from pathlib import Path

import pandas as pd
import requests

from .enciclopedia import catalog,detect
from .fabrica_diaria import fetch_daily

ROOT=Path(__file__).resolve().parents[1]
COST=.001
UTC=timezone.utc


def stamp(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(UTC)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def fresh(now,quote):
    try: return float(quote['price'])>0 and 0<=(now-stamp(quote['time'])).total_seconds()<=180
    except (KeyError,ValueError,TypeError): return False


def market(asset,now):
    # Coinbase latest300 one-minute candles, plus public ticker timestamp.
    base=f'https://api.exchange.coinbase.com/products/{asset}-USD'
    response=requests.get(base+'/candles',params={'granularity':60},timeout=20);response.raise_for_status()
    rows=response.json()
    minute=pd.DataFrame(rows,columns=['time','low','high','open','close','volume'])
    minute.index=pd.to_datetime(minute.pop('time'),unit='s',utc=True);minute=minute.sort_index()
    minute=minute[minute.index+pd.Timedelta(minutes=1)<=pd.Timestamp(now)]
    if len(minute)<60: raise ValueError('Faltan60 velas cerradas')
    recent=minute.iloc[-60:]
    if (recent.index.to_series().diff().dropna()!=pd.Timedelta(minutes=1)).any(): raise ValueError('Huecos1min, no rellenar')
    if (now-recent.index[-1].to_pydatetime()).total_seconds()>180: raise ValueError('Velas1min desactualizadas')
    r=requests.get(base+'/ticker',timeout=20);r.raise_for_status();q=r.json()
    quote=dict(price=float(q['price']),time=q['time'])
    if not fresh(datetime.now(UTC),quote): raise ValueError('Ticker desactualizado')
    daily=fetch_daily(asset,(now.date()-timedelta(days=400)).isoformat(),now.date().isoformat())
    if daily.index[-1].date()!=now.date()-timedelta(days=1): raise ValueError('Falta último día cerrado')
    return dict(quote=quote,daily=daily,minute=recent,coverage=dict(real_minutes=len(recent),last_minute=recent.index[-1].isoformat(),daily_last=daily.index[-1].isoformat()))


def receipt(run_id,now):
    """Verifica éxito Actions, no considera un despacho como ejecución."""
    token=os.environ.get('GH_TOKEN');repo=os.environ.get('GITHUB_REPOSITORY','recinosr/wall-street-motor')
    if not token or not str(run_id).isdigit(): return None
    r=requests.get(f'https://api.github.com/repos/{repo}/actions/runs/{run_id}',
                   headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'},timeout=20)
    r.raise_for_status();data=r.json()
    if data.get('status')!='completed' or data.get('conclusion')!='success': return None
    complete=stamp(data['updated_at'])
    if complete>now: return None
    return dict(run_id=str(run_id),completed_at=data['updated_at'],url=data['html_url'])


def new_account():
    return dict(initial=1000.,cash=1000.,units=0.,fees=0.,hold_units=None,hold_started=None,
                position=None,pending=None,seen=[],equity=1000.,net_liquidation=1000.,hold_equity=1000.,gain=0.,vs_hold=0.)


def initial():
    return dict(version=1,simulacion=True,cost_per_side=COST,accounts={a:new_account() for a in ['BTC','ETH']},
                decisions=[],total_decisions=0,ledger_hash='0'*64,last_run_id=None,observado_en=None,
                metodo='Reglas A/B diarias BTC + reglas cripto BH; intención publicada, recibo Actions exitoso y cotización futura. Cron aproximado10min, con posibles demoras.',
                limitaciones=['No LLM ni pesos aprendidos; reglas registradas y selección histórica.','Esta demo no valida transferencia a velas1min.','Señales diarias, seguimiento10min y fills diferidos: no replica salidas ideales del ensayo.','Costos0.1% por lado; no incluye spread, impuestos ni fondeo.'])


def eligible(report,asset):
    """Solo signo alcista, BH específico del activo y definición compatible v1."""
    if report.get('version')!=1 or not report.get('completo'): return []
    candidates=[]
    for p in report.get('items',[]):
        if p.get('direccion')!=1: continue
        for exit in p.get('salidas',[]):
            g=exit.get('grupos',{}).get(asset+'-USD',{})
            total,post=g.get('total',{}),g.get('desde2016',{})
            if g.get('estado')!='sirve_en_muestra': continue
            if not total.get('pasa_BH') or not post.get('pasa_BH'): continue
            if max(total.get('q_normal',1),total.get('q_azar',1),post.get('q_normal',1),post.get('q_azar',1))>.05: continue
            candidates.append(dict(id=p['id'],salida=exit['id'],extremo_velas=p['extremo_velas'],revision=digest(report)))
    # Fixed alphabetical arbitration; never optimize after observing live returns.
    return sorted(candidates,key=lambda p:(p['id'],p['salida']))


def signal(asset,account,data,report,now):
    df=data['daily'];last=df.index[-1];key=last.date().isoformat()
    # A: last-day monthly signal, known only after the UTC month closes.
    if asset=='BTC' and now.day==1 and (now-datetime(now.year,now.month,1,tzinfo=UTC)).total_seconds()<=1800:
        month_key='A:'+last.strftime('%Y-%m')
        months=df.close.resample('ME').last()
        if len(months)>=10 and month_key not in account['seen']:
            account['seen'].append(month_key);invested=float(months.iloc[-1])>float(months.iloc[-10:].mean())
            if invested and account['units']==0: return dict(action='comprar',rule='A',key=month_key,exit=None,reason='A: cierre mensual BTC supera media10 cierres; regla fija registrada.',signal_at=(last+pd.Timedelta(days=1)).isoformat())
            if not invested and account['units']>0: return dict(action='vender',rule='A',key=month_key,reason='A: cierre mensual ya no supera media10 cierres.',signal_at=(last+pd.Timedelta(days=1)).isoformat())
    position=account['position']
    if position:
        q=float(data['quote']['price'])
        if position.get('expires_at') and now>=stamp(position['expires_at']):
            return dict(action='vender',rule=position['rule'],reason='Venció el plazo registrado; vender con precio futuro al recibo.',key='exit:'+position['id'],signal_at=now.isoformat())
        if position.get('stop') is not None and (q<=position['stop'] or q>=position['target']):
            return dict(action='vender',rule=position['rule'],reason='Stop/objetivo observado en esta revisión; ejecución diferida, sin rellenar a precio pasado.',key='exit:'+position['id'],signal_at=now.isoformat())
        return None
    if now.hour!=0 or now.minute>30:
        # Opening window lost: do not replay earlier daily entry at an old price.
        return None
    if asset=='BTC':
        bkey='B:'+key
        if bkey not in account['seen']:
            account['seen'].append(bkey);three=df.iloc[-3:]
            if len(three)==3 and (three.close>three.open).all() and (three.close.diff().dropna()>0).all():
                return dict(action='comprar',rule='B',key=bkey,exit='fijo_5',reason='B: tres verdes diarias BTC y cierres crecientes; salida5 días; no se reinterpretan como minutos.',signal_at=(last+pd.Timedelta(days=1)).isoformat())
    signals=None
    for p in eligible(report,asset):
        ekey=p['id']+':'+p['salida']+':'+key
        if ekey in account['seen']: continue
        account['seen'].append(ekey)
        if signals is None: signals=detect(df)
        if p['id'] not in signals or not signals[p['id']].iloc[-1]: continue
        return dict(action='comprar',rule='enciclopedia:'+p['id'],key=ekey,exit=p['salida'],extremo_velas=p['extremo_velas'],
                    revision=p['revision'],reason='Patrón diario '+p['id']+' con BH específico '+asset+'; salida '+p['salida']+'; selección histórica, no ventaja futura.',signal_at=(last+pd.Timedelta(days=1)).isoformat())
    return None


def execute(account,intent,quote,proof,now):
    """Fill exclusivamente con un ticker fresco posterior al recibo de la intención."""
    if not proof or not fresh(now,quote): return None
    if stamp(proof['completed_at'])<stamp(intent['decided_at']): return None
    if stamp(quote['time'])<=max(stamp(proof['completed_at']),stamp(intent['decided_at'])): return None
    price=float(quote['price']);fee=0.
    if intent['action']=='comprar' and account['units']==0:
        budget=account['cash'];fee=budget*COST/(1+COST);account['units']=budget/(price*(1+COST));account['cash']=0.
        mode=intent.get('exit');h=int(mode.split('_')[1]) if mode and mode.startswith('fijo') else 20 if mode else None
        stop=intent.get('stop');target=price+int(mode.split('_')[1])*(price-stop) if mode and mode.startswith('ratio') and stop and stop<price else None
        if mode and mode.startswith('ratio') and target is None:
            # Invalid gap stop: reject before any account mutation.
            account['cash']=budget;account['units']=0.;return dict(action='cancelar',reason='Apertura fuera del stop; intención inválida, sin compra ni costos.')
        account['position']=dict(id=intent['id'],rule=intent['rule'],entry_price=price,entry_time=quote['time'],
                                 expires_at=(stamp(quote['time'])+timedelta(days=h)).isoformat() if h else None,
                                 stop=stop,target=target,revision=intent.get('revision'))
    elif intent['action']=='vender' and account['units']>0:
        gross=account['units']*price;fee=gross*COST;account['cash']+=gross-fee;account['units']=0.;account['position']=None
    else: return dict(action='cancelar',reason='Cuenta no coincide con la intención; no duplicar operación.')
    account['fees']+=fee
    return dict(action=intent['action'],price=price,quote_time=quote['time'],fee=fee,receipt=proof,reason=intent['reason'],intent_id=intent['id'],rule=intent['rule'])


def cycle(state,report,markets,now,run_id,receipts):
    state=copy.deepcopy(state)
    if state['version']!=1: raise ValueError('No migrar ledger/política silenciosamente')
    if state['last_run_id']==str(run_id): return state,[]
    emitted=[]
    def log(asset,action,reason,**fields):
        event=dict(seq=state['total_decisions']+1,asset=asset,action=action,reason=reason,observed_at=now.isoformat(),run_id=str(run_id),**fields)
        event['previous_hash']=state['ledger_hash'];event['hash']=digest(event)
        state['ledger_hash']=event['hash'];state['total_decisions']+=1;state['decisions'].append(event);emitted.append(event)
    for asset,account in state['accounts'].items():
        data=markets.get(asset)
        if not data or not fresh(now,data.get('quote',{})):
            log(asset,'esperar','Datos faltantes, huecos o cotización desactualizada; cuenta sin operaciones.');continue
        q=data['quote'];price=q['price'];pending=account['pending'];filled=False
        if account['hold_units'] is None:
            # Reference starts at first observed quote, same1000 budget and purchase fee.
            account['hold_units']=1000/(price*(1+COST));account['hold_started']=q['time']
        if pending:
            proof=receipts.get(str(pending['run_id']));result=execute(account,pending,q,proof,now)
            if result:
                log(asset,result.pop('action'),result.pop('reason'),**result);account['pending']=None;filled=True
            elif now-stamp(pending['decided_at'])>timedelta(days=1) and pending['action']=='comprar':
                log(asset,'cancelar','Intención de compra expiró tras24h sin recibo/precio futuro.');account['pending']=None
            else: log(asset,'esperar','Intención pendiente: requiere corrida anterior exitosa y precio posterior al recibo.',intent_id=pending['id'])
        if not account['pending'] and not filled:
            idea=signal(asset,account,data,report,now)
            if idea:
                idea.update(id=digest(dict(asset=asset,key=idea['key'],run=str(run_id)))[:24],decided_at=now.isoformat(),run_id=str(run_id))
                if (idea.get('exit') or '').startswith('ratio'):
                    idea['stop']=float(data['daily'].low.iloc[-idea['extremo_velas']:].min())
                account['pending']=idea;log(asset,'intencion_'+idea['action'],idea['reason'],intent=idea)
            else: log(asset,'mantener','Sin señal nueva dentro de la ventana diaria/mensual; conserva efectivo o posición.',coverage=data.get('coverage',{}))
        account['seen']=account['seen'][-1000:]
        account['equity']=account['cash']+account['units']*price
        account['net_liquidation']=account['cash']+account['units']*price*(1-COST)
        account['hold_equity']=account['hold_units']*price*(1-COST)
        account['gain']=account['net_liquidation']-account['initial'];account['vs_hold']=account['net_liquidation']-account['hold_equity']
        account['quote_time']=q['time'];account['last_price']=price
    state['decisions']=state['decisions'][-500:];state['observado_en']=now.isoformat();state['last_run_id']=str(run_id)
    state['approved_crypto_rules']={a:len(eligible(report,a)) for a in ['BTC','ETH']}
    return state,emitted


def run(root=ROOT,now=None,run_id=None):
    now=now or datetime.now(UTC);run_id=run_id or os.environ.get('GITHUB_RUN_ID')
    if not run_id: raise ValueError('Se requiere identificador único de corrida; usar workflow')
    path=root/'resultados/demo_cripto.json';state=json.loads(path.read_text(encoding='utf8')) if path.exists() else initial()
    if state['last_run_id']==str(run_id): return state
    report_path=root/'resultados/enciclopedia.json';report=json.loads(report_path.read_text(encoding='utf8')) if report_path.exists() else {}
    data={};proofs={}
    for asset,account in state['accounts'].items():
        try: data[asset]=market(asset,now)
        except Exception as exc: print(asset,'sin datos:',type(exc).__name__,flush=True)
        pending=account['pending']
        if pending:
            try: proofs[str(pending['run_id'])]=receipt(pending['run_id'],now)
            except Exception as exc: print(asset,'sin recibo:',type(exc).__name__,flush=True)
    observed=datetime.now(UTC)
    updated,events=cycle(state,report,data,observed,run_id,proofs)
    ledger=root/'resultados/demo_cripto_ledger'/('decisiones-'+now.strftime('%Y-%m')+'.jsonl')
    ledger.parent.mkdir(parents=True,exist_ok=True)
    with ledger.open('a',encoding='utf8') as f:
        for event in events: f.write(json.dumps(event,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
    path.write_text(json.dumps(updated,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n',encoding='utf8')
    print('Decisiones permanentes:',updated['total_decisions'],'Nuevas:',len(events))
    return updated


if __name__=='__main__': run()
