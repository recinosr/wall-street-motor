"""Extensión ICT fija; reutiliza métricas75 previas y reaplica BH GLOBAL.
Datos nuevos públicos en memoria. Nunca abre OHLC reservados.
"""
import hashlib
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd
import requests
from . import enciclopedia as E

ROOT=Path(__file__).resolve().parents[1]
HOURLY_BEGIN='2024-01-01'
HOURLY_END='2025-01-01'
HOURLY_SPLIT='2024-07-01'

def hourly(symbol):
    begin=pd.Timestamp(HOURLY_BEGIN,tz='UTC');end=pd.Timestamp(HOURLY_END,tz='UTC');rows=[]
    for start in pd.date_range(begin,end,freq='290h',inclusive='left'):
        stop=min(end,start+pd.Timedelta(hours=290))
        r=requests.get(f'https://api.exchange.coinbase.com/products/{symbol}/candles',
                       params={'start':start.isoformat(),'end':stop.isoformat(),'granularity':3600},timeout=30)
        r.raise_for_status();rows.extend(r.json());time.sleep(.12)
    if not rows:raise ValueError('Sin velas')
    df=pd.DataFrame(rows,columns=['time','low','high','open','close','volume']);df.index=pd.to_datetime(df.pop('time'),unit='s',utc=True)
    df=df.sort_index();df=df[~df.index.duplicated()];df=df[(df.index>=begin)&(df.index<end)]
    if df.isna().any().any() or (df[['open','high','low','close']]<=0).any().any():raise ValueError('Velas inválidas')
    return df

def correct(report):
    """Corrige valores p previos y nuevos juntos, sin recalcular viejos ensayos."""
    tests={}
    for p in report['items']:
        for exit in p['salidas']:
            for asset,periods in exit['grupos'].items():
                for period,s in periods.items():
                    if not isinstance(s,dict):continue
                    key='|'.join((p['id'],exit['id'],asset,period))
                    for control in ('normal','azar'):tests[key+'|'+control]=s['p_'+control]
    q=E.bh(tests)
    for p in report['items']:
        states=[]
        for exit in p['salidas']:
            for asset,periods in exit['grupos'].items():
                for period,s in periods.items():
                    if not isinstance(s,dict):continue
                    key='|'.join((p['id'],exit['id'],asset,period))
                    for control in ('normal','azar'):s['q_'+control]=q[key+'|'+control]
                    s['pasa_BH']=max(s['q_normal'],s['q_azar'])<=.05 and s['n']>=30
                total,pre,post=(periods[k] for k in ('total','antes2016','desde2016'))
                good=lambda s:s.get('media_neta',0)>0 and s.get('exceso_normal',0)>0 and s.get('exceso_azar',0)>0
                state='insuficiente' if total['n']<30 else 'sin_evidencia'
                if p['direccion'] and total['pasa_BH'] and post['pasa_BH'] and good(total) and good(post) and pre['n']>=30 and good(pre):state='sirve_en_muestra'
                elif p['direccion'] and total['pasa_BH'] and post['pasa_BH'] and E.opposite_book(total,p['direccion']) and E.opposite_book(post,p['direccion']):state='contrario_al_libro'
                periods['estado']=state
                if asset=='universo':states.append(state)
        p['estado']='sirve_en_muestra' if 'sirve_en_muestra' in states else 'contrario_al_libro' if 'contrario_al_libro' in states else 'sin_evidencia' if any(s!='insuficiente' for s in states) else 'insuficiente'
        p['conclusion']={'sirve_en_muestra':'Efecto histórico en esta muestra; falta prueba prospectiva.','contrario_al_libro':'Efecto contrario a la hipótesis; no autoriza invertir la regla.','sin_evidencia':'No demostró ventaja después de costos y controles.','insuficiente':'Faltan observaciones.'}[p['estado']]
    report['pruebas_BH']=len(tests);report['patrones']=len(report['items']);report['combinaciones']=sum(len(p['salidas']) for p in report['items'])
    report['patrones_pasan']=sum(p['estado']=='sirve_en_muestra' for p in report['items'])
    report['patrones_contrarios']=[p['id'] for p in report['items'] if p['estado']=='contrario_al_libro']
    report['combinaciones_pasan']=sum(e['grupos']['universo']['estado']=='sirve_en_muestra' for p in report['items'] for e in p['salidas'])
    report['combinaciones_contrarias']=sum(e['grupos']['universo']['estado']=='contrario_al_libro' for p in report['items'] for e in p['salidas'])
    E.add_bh_counts(report)
    return report

def statistics(groups,asset,split):
    dates=groups.get(asset,{})
    result={}
    for period in ('total','antes2016','desde2016'):
        selected=dates if period=='total' else {k:v for k,v in dates.items() if (k<split)==(period=='antes2016')}
        seed=int(hashlib.sha256((asset+period+str(len(dates))).encode()).hexdigest()[:8],16)
        result[period]=E.summarize(selected,seed)
    return result

def run(hourly_only=False):
    started=time.monotonic();path=ROOT/'resultados/enciclopedia.json';previous=json.loads(path.read_text(encoding='utf8'))
    # Reejecuciones sustituyen únicamente ICT; conservan75 valores p del estudio base.
    saved={p['id']:p for p in previous['items'] if p.get('familia')=='ict'}
    if hourly_only and len(saved)!=10:raise ValueError('Faltan las10 reglas ICT diarias')
    previous['items']=[p for p in previous['items'] if p.get('familia')!='ict']
    definitions=[p for p in E.catalog() if p['familia']=='ict'];aggregates={};coverage={};errors={}
    symbols=json.loads((ROOT/'ideas/enciclopedia_universo.json').read_text())['symbols']
    def get(symbol):
        try:return symbol,E.fetch_daily(symbol),None
        except Exception as e:return symbol,None,type(e).__name__
    with ThreadPoolExecutor(max_workers=4) as pool:
        for symbol,df,error in pool.map(get,[] if hourly_only else symbols):
            if error:errors[symbol]=error;continue
            measured=E.measure_asset(symbol,df,definitions)
            for key,events in measured.items():
                groups=aggregates.setdefault(key,{})
                dates=E.aggregate_dates(events);E.merge_dates(groups.setdefault('universo',{}),dates)
                if symbol in ('BTC-USD','ETH-USD'):E.merge_dates(groups.setdefault(symbol,{}),dates)
            coverage[symbol]={'first':str(df.index[0].date()),'last':str(df.index[-1].date()),'sessions':len(df)}
            print('diario',symbol,len(df),flush=True)
    hourly_coverage={};hourly_errors={};original_split=E.SPLIT
    try:
        E.SPLIT=HOURLY_SPLIT
        for symbol in ('BTC-USD','ETH-USD'):
            try:
                df=hourly(symbol);parts=df.groupby((df.index.to_series().diff()!=pd.Timedelta(hours=1)).cumsum())
                kept=0;segments=0
                for _,segment in parts:
                    if len(segment)<220:continue
                    segments+=1;kept+=len(segment)
                    for key,events in E.measure_asset(symbol,segment,definitions).items():
                        groups=aggregates.setdefault(key,{})
                        E.merge_dates(groups.setdefault(symbol+'-1h',{}),E.aggregate_dates(events))
                hourly_coverage[symbol]={'first':str(df.index[0]),'last':str(df.index[-1]),'received':len(df),'expected':8784,'measured':kept,'segments':segments,'discarded':len(df)-kept}
                print('horario',symbol,hourly_coverage[symbol],flush=True)
            except Exception as e:hourly_errors[symbol]=type(e).__name__
    finally:E.SPLIT=original_split
    for p in definitions:
        exits=[]
        for mode in E.EXITS:
            groups=aggregates.get(p['id']+'|'+mode,{})
            if hourly_only:
                prior=next(e for e in saved[p['id']]['salidas'] if e['id']==mode)
                stats={asset:prior['grupos'][asset] for asset in ('universo','BTC-USD','ETH-USD')}
            else:stats={asset:statistics(groups,asset,E.SPLIT) for asset in ('universo','BTC-USD','ETH-USD')}
            stats.update({asset:statistics(groups,asset,HOURLY_SPLIT) for asset in ('BTC-USD-1h','ETH-USD-1h')})
            exits.append({'id':mode,'grupos':stats})
        previous['items'].append(dict(p,salidas=exits))
    previous.update(version=2,as_of=datetime.now(timezone.utc).isoformat(),ict_fecha_base=previous.get('ict_fecha_base',previous['as_of']),ict_coverage=coverage or previous.get('ict_coverage',{}),ict_errors=errors if not hourly_only else previous.get('ict_errors',{}),
                    ict_horaria={'begin':HOURLY_BEGIN,'end_exclusive':HOURLY_END,'split':HOURLY_SPLIT,'coverage':hourly_coverage,'errors':hourly_errors},
                    ict_minutes=(time.monotonic()-started)/60,combinaciones_horarias=140,pruebas_nuevas=2100,
                    periodos_horarios={'antes2016':'enero–junio2024','desde2016':'julio–diciembre2024','total':'todo2024'})
    previous['metodo']+=' Extensión ICT v1:10 reglas, mismos controles/salidas; conserva métricas75 previas y recalcula BH global con todas las pruebas diarias y horarias. Horario2024 Coinbase, segmentos continuos, sin rellenar huecos; agrupación de inferencia por fecha UTC y bloques20fechas con eventos.'
    previous['limitaciones']+=['ICT: reglas operativas propias; OHLC no observa stops ni identifica participantes institucionales.','Horarios: reglas/salidas en velas de1hora, N20horas; no equivalentes a días.','Snapshots de métricas base e ICT tienen fechas distintas; sin corroboración independiente completa.']
    correct(previous);path.write_text(json.dumps(previous,ensure_ascii=False,allow_nan=False,separators=(',',':')),encoding='utf8')
    print('BH',previous['pruebas_BH'],'ICT',len(definitions),'minutes',previous['ict_minutes'])
    return previous

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--hourly-only',action='store_true');args=parser.parse_args();run(args.hourly_only)
