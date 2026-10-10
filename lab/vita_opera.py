"""Tres políticas prospectivas de papel; sin brokers ni historia reservada."""
import argparse
import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .demo_cripto import digest, stamp, receipt, corroborate, eligible
from .enciclopedia import detect, catalog
from .pronostico import coin_history, features, CAL
from .universo import history
from .carteras import verify_quote
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
CRYPTO = ('BTC', 'ETH', 'LINK')
STOCKS = ('VT', 'QQQ', 'NFLX', 'MCD')
COST = .001
UTC = timezone.utc
POLICY = 'vita-opera-v1-mensual10-vol15-mom12_1-brier30dias'


def wallet():
    return dict(cash=1000., units=0., fees=0.)


def initial():
    return dict(version=1, policy=POLICY, simulacion=True, cost_per_side=COST,
                accounts={s:{k:dict(**wallet(), random=wallet(), hold=wallet(), pending=None,
                                     last_day=None, curve=[], last_operation=None)
                             for k in ('prudente','tendencia','activa')} for s in CRYPTO+STOCKS},
                ledger_hash='0'*64, total_events=0, events=[], errors=[], observado_en=None,
                comparaciones_descriptivas=42,
                aviso='US$1,000 por cuenta y activo. 21 cuentas, 42 comparaciones descriptivas contra mantener/azar, sin contraste de ventaja. Costos 0.1% por lado; sin spread, fondeo, impuestos ni dividendos. No ventaja demostrada. Azar: mismas oportunidades diarias, no igual número de operaciones. Prudente exige BH por activo y estabilidad; la demo anterior permanece separada.')


def trend(d, now, crypto):
    # Excluir TODO el mes en curso, incluso si hay un cierre diario disponible.
    closed=d[d.index.strftime('%Y-%m') < now.strftime('%Y-%m')].close.resample('ME').last().dropna()
    if len(closed)<10: raise ValueError('Faltan diez meses cerrados')
    above=float(closed.iloc[-1])>float(closed.tail(10).mean())
    weight=1.
    if crypto:
        vol=float(d.close.pct_change().tail(20).std()*np.sqrt(365))
        if not np.isfinite(vol) or vol<=0: raise ValueError('Volatilidad no disponible')
        weight=min(1., .15/vol)
    return weight if above else 0., f'Cierre mensual {closed.iloc[-1]:.4f}, media10 {closed.tail(10).mean():.4f}; peso objetivo {weight if above else 0.:.4f}.'


def probabilities(d, crypto, symbol='', patterns=False):
    x=features(d,crypto); y=d.close.shift(-1)>d.close
    valid=x.notna().all(axis=1)&d.close.shift(-1).notna()
    out={'sube_siempre':1., 'momentum_12_1':float(x.iloc[-1]['mom']>=0),
         'reversion_5d':float(x.iloc[-1]['r5']<=0),
         'azar':float(int(digest({'asset':symbol,'anchor':d.index[-1].isoformat()})[:8],16)%2)}
    if valid.sum()>=120 and y[valid].nunique()==2 and x.iloc[-1].notna().all():
        model=make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=300))
        model.fit(x[valid],y[valid].astype(int))
        out['logistica']=float(model.predict_proba(x.tail(1))[0,1])
    if patterns:
        signals=detect(d.tail(300),last_only=True)
        for rule in catalog():
            if rule['direccion'] and signals[rule['id']].iloc[-1]:out['patron:'+rule['id']]=float(rule['direccion']>0)
    return out


def active(preds, marker, crypto, current, asset_type=None):
    candidates=[r for r in marker.get('acumulado',[]) if r.get('sector')=='Todos' and
                r.get('tipo')==(asset_type or ('cripto' if crypto else 'acción')) and r.get('horizonte')==1 and
                r.get('dias',0)>=30 and r.get('predictor') in preds and np.isfinite(r.get('brier',np.nan))]
    name=min(candidates,key=lambda r:(r['brier'],r['predictor']))['predictor'] if candidates else 'logistica'
    p=preds.get(name)
    if p is None: return current, 'Logística no disponible; conservar posición, sin probabilidad inventada.'
    target=1. if p>.55 else 0. if p<.45 else current
    return target, f'{name}: p(subida)={p:.6f}; umbrales >0.55 comprar / <0.45 vender; selección Brier con mínimo30 días maduros, si no logística.'


def prudent(symbol,a,d,report,now,price):
    position=a.get('prudent_position')
    if position:
        expired=now>=stamp(position['expires_at'])
        stopped=position.get('stop') is not None and (price<=position['stop'] or price>=position['target'])
        return (0. if expired or stopped else 1.), ('Salida por plazo/stop/objetivo observado; precio futuro.' if expired or stopped else 'Mantener regla BH vigente.'),None
    candidates=eligible(report,symbol)
    if not candidates:return 0.,'Sin reglas compatibles que pasen BH y estabilidad; conservar efectivo. Demo original intacta.',None
    signals=detect(d.tail(300),last_only=True)
    for r in candidates:
        if not signals[r['id']].iloc[-1]:continue
        mode=r['salida'];stop=float(d.low.tail(r['extremo_velas']).min()) if mode.startswith('ratio_') else None
        if stop is not None and stop>=price:continue
        return 1.,f"Patrón {r['id']}, salida {mode}; BH activo y subperiodo estable, revisión {r['revision']}.",dict(rule=r['id'],exit=mode,stop=stop,revision=r['revision'])
    return 0.,'Reglas BH disponibles, sin señal alcista causal hoy.',None


def rebalance(a, target, price):
    value=a['cash']+a['units']*price
    delta=target*value-a['units']*price
    if abs(delta)<.01:return None
    if delta>0:
        gross=min(delta,a['cash']/(1+COST)); fee=gross*COST
        a['cash']-=gross+fee; a['units']+=gross/price; action='comprar'
    else:
        gross=min(-delta,a['units']*price); fee=gross*COST
        a['cash']+=gross-fee; a['units']-=gross/price; action='vender'
    a['fees']+=fee
    return dict(action=action, price=price, notional=gross, fee=fee)


def equity(a,p):return a['cash']+a['units']*p*(1-COST)


def cycle(state, markets, marker, now, run_id, proofs, report=None):
    state=copy.deepcopy(state)
    if state['version']!=1 or state['policy']!=POLICY:raise ValueError('Política incompatible: no migrar ledger')
    events=[]
    def log(symbol, policy, action, **fields):
        e=dict(seq=state['total_events']+1,asset=symbol,account=policy,action=action,
               observed_at=now.isoformat(),run_id=str(run_id),previous_hash=state['ledger_hash'],**fields)
        e['hash']=digest(e);state['ledger_hash']=e['hash'];state['total_events']+=1
        events.append(e);state['events'].append(e)
    momenta={s:float(m['daily'].close.iloc[-22]/m['daily'].close.iloc[-253]-1)
             for s,m in markets.items() if s in STOCKS and len(m['daily'])>252}
    winner=max(momenta,key=lambda s:(momenta[s],s)) if len(momenta)==len(STOCKS) else None
    for s,m in markets.items():
        p=float(m['quote']['price']); qt=stamp(m['quote']['time']); crypto=s in CRYPTO
        age=(now-qt).total_seconds()
        if not np.isfinite(p) or p<=0 or age<0 or age>(180 if crypto else 86400):continue
        d=m['daily'];day=now.date().isoformat() if crypto else qt.date().isoformat()
        for policy,a in state['accounts'][s].items():
            pending=a['pending']
            proof=proofs.get(str(pending['run_id'])) if pending else None
            if (pending and proof and qt>max(stamp(proof['completed_at']),stamp(pending['decided_at']))
                    and not (policy=='activa' and a.get('execution_day')==day)):
                setup=pending.get('prudent_setup')
                if setup and setup.get('stop') is not None and setup['stop']>=p:
                    log(s,policy,'cancelar',reason='Precio futuro fuera del stop; sin compra ni costo.',intent_id=pending['id'])
                    a['pending']=None;continue
                # Una bolsa no ejecuta una intención vieja en un cierre previo.
                result=rebalance(a,pending['target'],p)
                if result:
                    log(s,policy,result.pop('action'),**result,quote_time=m['quote']['time'],
                        reason=pending['reason'],intent_id=pending['id'],receipt=proof,corroboration=m['quote'].get('corroboration'))
                    a['last_operation']=events[-1]
                    a['execution_day']=day
                    if policy=='prudente':
                        if events[-1]['action']=='vender':a['prudent_position']=None
                        elif setup:
                            mode=setup['exit'];h=int(mode.split('_')[1]) if mode.startswith('fijo_') else 20
                            a['prudent_position']=dict(**setup,expires_at=(qt+timedelta(days=h)).isoformat(),
                                target=p+int(mode.split('_')[1])*(p-setup['stop']) if mode.startswith('ratio_') else None)
                if not a.get('hold_started'):
                    rebalance(a['hold'],1.,p);a['hold_started']=m['quote']['time']
                rebalance(a['random'],pending['random_target'],p)
                log(s,policy,'evaluacion',reason=pending['reason'],intent_id=pending['id'],receipt=proof,
                    quote_time=m['quote']['time'],random_target=pending['random_target'])
                a['pending']=None
            if not a['pending'] and a['last_day']!=day:
                current=a['units']*p/(a['cash']+a['units']*p)
                setup=None
                if policy=='prudente': target,reason,setup=prudent(s,a,d,report or {},now,p)
                elif policy=='tendencia':
                    target,reason=trend(d,now,crypto)
                    if not crypto:
                        if winner is None:continue
                        target=target if s==winner else 0.
                        reason+=f' Momentum12-1 ganador {winner}; cuenta separada sin transferir capital.'
                else:target,reason=active(m['predictions'],marker,crypto,current,'ETF' if s in ('VT','QQQ') else None)
                random_target=float(int(digest({'policy':policy,'asset':s,'day':day})[:8],16)%2)
                log(s,policy,'intencion',target=target,random_target=random_target,reason=reason,
                    signal_until=d.index[-1].isoformat())
                a['pending']=dict(id=events[-1]['hash'],run_id=str(run_id),decided_at=now.isoformat(),
                                  target=target,random_target=random_target,reason=reason,prudent_setup=setup)
                a['last_day']=day
            a['equity']=equity(a,p);a['hold_equity']=equity(a['hold'],p);a['random_equity']=equity(a['random'],p)
            a['quote_time']=m['quote']['time'];a['position']='efectivo' if a['units']<1e-10 else f"{a['units']:.8f} {s}"
            point=dict(time=m['quote']['time'],equity=a['equity'],hold=a['hold_equity'],random=a['random_equity'])
            if not a['curve'] or a['curve'][-1]['time']!=point['time']:
                a['curve'].append(point)
                log(s,policy,'saldo',reason='Valor neto de liquidación a precio observado, mismos costos en comparadores.',
                    quote_time=m['quote']['time'],price=p,equity=a['equity'],hold_equity=a['hold_equity'],random_equity=a['random_equity'])
    state['events']=state['events'][-300:];state['observado_en']=now.isoformat()
    return state,events


def market(s, now):
    crypto=s in CRYPTO
    d=coin_history(s+'-USD') if crypto else history(s,'5y')
    if crypto:
        r=requests.get(f'https://api.exchange.coinbase.com/products/{s}-USD/ticker',timeout=20);r.raise_for_status();v=r.json()
        q=dict(price=float(v['price']),time=v['time'],source='Coinbase public ticker')
        r=requests.get('https://api.kraken.com/0/public/Trades',params={'pair':'XBTUSD' if s=='BTC' else s+'USD'},timeout=20);r.raise_for_status()
        q['corroboration']=corroborate(q,r.json(),datetime.now(UTC))
        if d.index[-1].date()!=now.date()-timedelta(days=1):raise ValueError('Ancla diaria cripto obsoleta')
        if not (d.index[-21:].to_series().diff().dropna()==pd.Timedelta(days=1)).all():raise ValueError('Huecos diarios cripto; no rellenar')
    else:
        session=CAL.date_to_session(pd.Timestamp(now.date()),direction='previous')
        if session.date()!=now.date() or pd.Timestamp(now)<CAL.session_close(session)+pd.Timedelta(minutes=15):raise ValueError('Fuera de sesión cerrada')
        if d.index[-1].date()!=session.date():raise ValueError('Cierre bolsa obsoleto')
        # Fecha real del cierre de sesión, nunca timestamp de apertura de vela diaria.
        q=dict(price=float(d.close.iloc[-1]),time=CAL.session_close(session).isoformat(),source='Yahoo cierre diario')
        proof=verify_quote(s,d.rename(columns={'close':'Close'}).set_axis(d.index.tz_localize(None).normalize()))
        if proof['estado']!='coincide':raise ValueError('Segundo proveedor no corroboró cierre: '+json.dumps(proof))
        q['corroboration']=proof
    return dict(daily=d,quote=q)


def audit(state,directory):
    previous='0'*64;seq=0
    for path in sorted(directory.glob('*.jsonl')):
        for line in path.read_text(encoding='utf8').splitlines():
            e=json.loads(line);h=e.pop('hash');seq+=1
            if e['seq']!=seq or e['previous_hash']!=previous or digest(e)!=h:
                raise ValueError('Cadena de ledger alterada; detener sin migración')
            previous=h
    if previous!=state['ledger_hash'] or seq!=state['total_events']:
        raise ValueError('Ledger y resumen no coinciden')


def run(kind,root=ROOT):
    path=root/'resultados/vita_opera.json';state=json.loads(path.read_text(encoding='utf8')) if path.exists() else initial()
    directory=root/'resultados/vita_opera_ledger';audit(state,directory)
    markerpath=root/'resultados/marcador.json';marker=json.loads(markerpath.read_text(encoding='utf8')) if markerpath.exists() else {}
    reportpath=root/'resultados/enciclopedia.json';report=json.loads(reportpath.read_text(encoding='utf8')) if reportpath.exists() else {}
    now=datetime.now(UTC);run_id=os.environ.get('GITHUB_RUN_ID','local-'+now.isoformat());markets={};errors=[];proofs={}
    for s in CRYPTO if kind=='cripto' else STOCKS:
        try:
            m=market(s,now)
            patterns=any(r.get('predictor','').startswith('patron:') and r.get('dias',0)>=30 for r in marker.get('acumulado',[]))
            m['predictions']=probabilities(m['daily'],s in CRYPTO,s,patterns)
            markets[s]=m
        except Exception as exc:errors.append(dict(asset=s,error=str(exc)[:180]))
    for accounts in state['accounts'].values():
        for a in accounts.values():
            if a['pending']:
                rid=str(a['pending']['run_id'])
                if rid not in proofs:proofs[rid]=receipt(rid,datetime.now(UTC))
    state,events=cycle(state,markets,marker,datetime.now(UTC),run_id,proofs,report);state['errors']=errors
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/(now.strftime('%Y-%m')+'.jsonl')).open('a',encoding='utf8') as f:
        for e in events:f.write(json.dumps(e,ensure_ascii=False,allow_nan=False)+'\n')
    path.write_text(json.dumps(state,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(events=len(events),errors=errors),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--tipo',choices=['cripto','bolsa'],required=True)
    run(parser.parse_args().tipo)
