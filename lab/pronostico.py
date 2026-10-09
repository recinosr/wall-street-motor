"""Pronósticos prospectivos inmutables. No publica OHLC ni evalúa el archivo reservado."""
import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import math
import os
import subprocess
import time
from pathlib import Path

import exchange_calendars as xc
import numpy as np
import pandas as pd
import requests
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from scipy.stats import norm
from lab.universo import history, get
from lab.enciclopedia import catalog, detect

ROOT=Path(__file__).resolve().parents[1]
CAL=xc.get_calendar('XNYS')
UTC=dt.timezone.utc


def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def targets(now,kind):
    day=pd.Timestamp(now.date())
    if kind=='cripto':
        return [day.date().isoformat(),(day+pd.Timedelta(days=4)).date().isoformat()], day+pd.Timedelta(days=1)
    session=CAL.date_to_session(day,direction='next')
    dates=[session.date().isoformat(),CAL.session_offset(session,4).date().isoformat()]
    return dates,CAL.session_open(session)


def coin_history(product):
    end=dt.datetime.now(UTC).replace(hour=0,minute=0,second=0,microsecond=0)
    rows=[]
    for _ in range(3):
        start=end-dt.timedelta(days=290)
        rows+=get('https://api.exchange.coinbase.com/products/'+product+'/candles',params={
            'granularity':86400,'start':start.isoformat(),'end':end.isoformat()}).json()
        end=start; time.sleep(.15)
    d=pd.DataFrame(rows,columns=['timestamp','low','high','open','close','volume'])
    d=d.drop_duplicates('timestamp').sort_values('timestamp')
    d.index=pd.to_datetime(d.pop('timestamp'),unit='s',utc=True)
    cutoff=pd.Timestamp.now(tz='UTC').normalize()
    return d[d.index<cutoff]


def fetch(asset):
    return coin_history(asset['coinbase']) if asset['tipo']=='cripto' and asset.get('coinbase') else history(asset['sim'],'5y')


def features(d):
    c=d.close
    return pd.DataFrame({'r1':c.pct_change(),'r5':c.pct_change(5),
        'mom':c.shift(21)/c.shift(252)-1,'vol':c.pct_change().rolling(20).std(),
        'dist':c/c.rolling(200).mean()-1},index=d.index)


def predict(d,sim,horizon,patterns=None):
    x=features(d); last=x.iloc[-1]
    out={'sube_siempre':1.,'azar':float(int(hashlib.sha256((sim+str(d.index[-1])+str(horizon)).encode()).hexdigest()[:8],16)%2)}
    if pd.notna(last['mom']):out['momentum_12_1']=float(last['mom']>=0)
    if pd.notna(last['r5']):out['reversion_5d']=float(last['r5']<=0)
    # Se entrena con etiquetas ya maduras; validación cronológica final sin selección de hiperparámetros.
    future=d.close.shift(-horizon)/d.close-1
    valid=x.notna().all(axis=1)&future.notna()
    train=x[valid]; y=(future[valid]>0).astype(int)
    if len(train)>=120 and last.notna().all() and y.nunique()==2:
        model=make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=300));errors=[]
        boundaries=[int(len(train)*f) for f in (.5,.65,.8,1.)]
        for split,end in zip(boundaries[:-1],boundaries[1:]):
            if y.iloc[:split-horizon].nunique()<2:continue
            model.fit(train.iloc[:split-horizon],y.iloc[:split-horizon])
            p=model.predict_proba(train.iloc[split:end])[:,1]
            errors.extend((p-y.iloc[split:end].to_numpy())**2)
        brier=float(np.mean(errors)) if errors else None
        model.fit(train,y)
        out['logistica']=float(model.predict_proba(x.tail(1))[0,1])
    else:brier=None
    # Incluye cada patrón activo; patrones neutros y ausencias se abstienen.
    signals=patterns if patterns is not None else detect(d.tail(300),last_only=True)
    for rule in catalog():
        if rule['direccion'] and signals[rule['id']].iloc[-1]:out['patron:'+rule['id']]=float(rule['direccion']>0)
    return out,brier


def save_once(path,payload):
    payload['sha256']=digest(payload)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8') as f:json.dump(payload,f,ensure_ascii=False,allow_nan=False)


def generate(kind,now=None):
    now=now or dt.datetime.now(UTC)
    dates,deadline=targets(now,kind)
    path=ROOT/'resultados/pronosticos'/f'{dates[0]}-{kind}.json'
    if path.exists():print('Pronóstico existente preservado:',path.name);return
    if kind=='cripto' and now.hour>0:
        print('Fuera de la ventana 00:00–00:59 UTC; no crear pronóstico tardío.');return
    if pd.Timestamp(now)>=deadline:
        print('Apertura ya ocurrió; no crear pronóstico tardío.');return
    universe=json.loads((ROOT/'resultados/universo.json').read_text(encoding='utf8'))
    assets=[a for a in universe['datos'] if (a['tipo']=='cripto')==(kind=='cripto') and
            (a.get('volumen_medio_usd') or a.get('volumen_24h_usd') or 0)>5e6]
    failures=[]; rows=[]
    def one(a):
        try:
            d=fetch(a)
            if len(d)<30:raise ValueError('historia insuficiente')
            liquidity=float((d.close*d.volume).tail(20).mean())
            if liquidity<=5e6:raise ValueError('volumen medio20 días no supera USD5M')
            # Ancla inmediatamente anterior al objetivo; rechazar huecos/fecha obsoleta.
            anchor=(pd.Timestamp(dates[0])-pd.Timedelta(days=1)).date() if kind=='cripto' else CAL.previous_session(pd.Timestamp(dates[0])).date()
            if d.index[-1].date()!=anchor:raise ValueError('ancla no fresca')
            if kind=='cripto' and len(d)>5 and not (d.index[-6:].to_series().diff().dropna()==pd.Timedelta(days=1)).all():raise ValueError('huecos recientes')
            result=[];patterns=detect(d.tail(300),last_only=True)
            for h,target in zip((1,5),dates):
                preds,brier=predict(d,a['sim'],h,patterns)
                result.append({'sim':a['sim'],'coinbase':a.get('coinbase'),'tipo':a['tipo'],
                    'sector':a.get('sector','Desconocido'),'horizonte':h,'objetivo':target,
                    'ancla':d.index[-1].date().isoformat(),'predicciones':preds,
                    'validacion_brier':brier,'entrenamiento_hasta':d.index[-h-1].date().isoformat(),
                    'volumen_filtro_usd':liquidity})
            return result,None
        except Exception as e:return [],{'sim':a['sim'],'error':str(e)[:150]}
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        for result,err in pool.map(one,assets):
            rows+=result
            if err:failures.append(err)
    # Comprobar nuevamente después de descargar todo.
    published=dt.datetime.now(UTC)
    if pd.Timestamp(published)>=deadline:raise RuntimeError('Terminó después de apertura; no publicar')
    save_once(path,{'version':2,'publicado':published.isoformat(),'deadline':deadline.isoformat(),
        'run_id':os.environ.get('GITHUB_RUN_ID'),'tipo':kind,'filas':rows,'fallas':failures,
        'activos_elegibles':len(assets),'algoritmo':'logistica C=.1 fija, walk-forward3 bloques expansivos, purga horizonte, sin ajuste por resultado',
        'predictores_registrados':5+sum(bool(r['direccion']) for r in catalog()),
        'aviso':'Dirección entre cierre anterior y cierre objetivo. Patrones se abstienen sin señal. No es simulación de ejecución.'})


def receipt(path,payload):
    if not payload.get('run_id'):return None
    body={k:v for k,v in payload.items() if k!='sha256'}
    if digest(body)!=payload['sha256']:raise ValueError('Hash alterado')
    rel=path.relative_to(ROOT).as_posix()
    commit=subprocess.check_output(['git','log','--diff-filter=A','--format=%H','--',rel],cwd=ROOT,text=True).strip().splitlines()
    if len(commit)!=1:return None
    sha=commit[0]
    original=json.loads(subprocess.check_output(['git','show',sha+':'+rel],cwd=ROOT,text=True,encoding='utf8'))
    if original!=payload:raise ValueError('Pronóstico modificado después del commit inicial')
    date=subprocess.check_output(['git','show','-s','--format=%cI',sha],cwd=ROOT,text=True).strip()
    if pd.Timestamp(date)>=pd.Timestamp(payload['deadline']):return None
    token=os.environ.get('GH_TOKEN')
    if not token:return None
    r=requests.get('https://api.github.com/repos/recinosr/wall-street-motor/actions/runs/'+payload['run_id'],
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'},timeout=30)
    r.raise_for_status();run=r.json()
    if run.get('conclusion')!='success':return None
    return {'commit':sha,'run_id':run['id'],'url':run['html_url'],'sha256':payload['sha256']}


def wilson(w,n):
    if not n:return None
    p=w/n;z=1.96;den=1+z*z/n;delta=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))
    return [(p+z*z/(2*n)-delta)/den,(p+z*z/(2*n)+delta)/den]


def summary(rows):
    out=[]
    keys={(r['predictor'],r['tipo'],r['sector'],r['horizonte']) for r in rows}|{(r['predictor'],r['tipo'],'Todos',r['horizonte']) for r in rows}
    for key in sorted(keys):
        group=[r for r in rows if r['predictor']==key[0] and r['tipo']==key[1] and (key[2]=='Todos' or r['sector']==key[2]) and r['horizonte']==key[3]]
        daily={}
        for r in group:daily.setdefault(r['objetivo'],[]).append(r)
        differences=[np.mean([r['acierto']-r['siempre_acierto'] for r in g]) for g in daily.values()]
        mean=float(np.mean(differences)); ci=None
        if len(differences)>1:
            delta=1.96*np.std(differences,ddof=1)/np.sqrt(len(differences));ci=[mean-delta,mean+delta]
        wins=sum(r['acierto'] for r in group);n=len(group)
        out.append(dict(zip(('predictor','tipo','sector','horizonte'),key),n=n,dias=len(daily),
            acierto_pct=100*wins/n,brier=float(np.mean([(r['p']-r['y'])**2 for r in group])),
            ic95_descriptivo=wilson(wins,n),diferencia_sube_siempre=mean,ic95_por_dia=ci,
            azar_pct=100*np.mean([r['azar_acierto'] for r in group])))
        for control,field in (('siempre','siempre_acierto'),('azar','azar_acierto')):
            diffs=np.array([np.mean([r['acierto']-r[field] for r in g]) for g in daily.values()])
            mean=float(diffs.mean());z=diffs-mean;n_days=len(z)
            variance=float(z@z/n_days)
            for lag in range(1,min(6,n_days)):
                variance+=2*(1-lag/6)*float(z[lag:]@z[:-lag]/n_days)
            se=math.sqrt(max(0,variance)/n_days)
            out[-1]['p_'+control]=float(norm.sf(mean/se)) if n_days>=30 and se>0 else 1.
    return out


def score(now=None):
    now=now or dt.datetime.now(UTC);directory=ROOT/'resultados/pronosticos';evaluations=ROOT/'resultados/calificaciones'
    evaluations.mkdir(parents=True,exist_ok=True); failures=[]
    for path in sorted(directory.glob('*.json')):
        payload=json.loads(path.read_text(encoding='utf8'));proof=receipt(path,payload)
        if not proof:continue
        cache={}
        for row in payload['filas']:
            target=pd.Timestamp(row['objetivo'])
            close=target.tz_localize('UTC')+pd.Timedelta(days=1) if row['tipo']=='cripto' else CAL.session_close(target)+pd.Timedelta(minutes=15)
            if pd.Timestamp(now)<close:continue
            key=digest({'forecast':payload['sha256'],'sim':row['sim'],'h':row['horizonte']})
            dest=evaluations/(key+'.json')
            if dest.exists():continue
            try:
                if row['sim'] not in cache:cache[row['sim']]=fetch(row)
                d=cache[row['sim']];dates=d.index.strftime('%Y-%m-%d')
                a=d[dates==row['ancla']];b=d[dates==row['objetivo']]
                if len(a)!=1 or len(b)!=1:raise ValueError('Falta cierre exacto; pendiente')
                ret=float(b.close.iloc[0]/a.close.iloc[0]-1); y=int(ret>0)
                # Empates no son subida; convención fijada antes de observar resultados.
                preds=row['predicciones']; always=int(y==1);random=int((preds['azar']>=.5)==bool(y))
                rows=[{**{k:row[k] for k in ('sim','tipo','sector','horizonte','objetivo')},
                    'predictor':name,'p':p,'y':y,'acierto':int((p>=.5)==bool(y)),
                    'siempre_acierto':always,'azar_acierto':random,'retorno_pct':ret*100,
                    'brecha_pct':float(b.open.iloc[0]/a.close.iloc[0]-1)*100,
                    'prueba':proof} for name,p in preds.items()]
                save_once(dest,{'filas':rows,'medido':now.isoformat()})
            except Exception as e:failures.append({'sim':row['sim'],'error':str(e)[:120]})
    allrows=[r for p in evaluations.glob('*.json') for r in json.loads(p.read_text(encoding='utf8'))['filas']]
    last=max((r['objetivo'] for r in allrows),default=None)
    today=[r for r in allrows if r['objetivo']==last];window=[r for r in allrows if pd.Timestamp(r['objetivo'])>=pd.Timestamp(now.date())-pd.Timedelta(days=30)]
    unique={r['sim']:r for r in today if r['horizonte']==1}
    surprises=[]
    for row in sorted(unique.values(),key=lambda r:abs(r['retorno_pct']),reverse=True)[:10]:
        market=[r['retorno_pct'] for r in unique.values() if r['tipo']==row['tipo']]
        sector=[r['retorno_pct'] for r in unique.values() if r['sector']==row['sector']]
        model=next((r for r in today if r['sim']==row['sim'] and r['horizonte']==1 and r['predictor']=='logistica'),None)
        surprises.append({'sim':row['sim'],'retorno_pct':row['retorno_pct'],
            'texto':f"Movimiento {row['retorno_pct']:.2f}%; promedio equiponderado observado {np.mean(market):.2f}%, sector {np.mean(sector):.2f}%; brecha {row['brecha_pct']:.2f}%. "+
            ('La logística acertó. ' if model and model['acierto'] else 'La logística falló. ' if model else 'Sin pronóstico logístico. ')+
            'Resultados empresariales: fecha no disponible. Este contexto no demuestra la causa.'})
    r={'version':1,'actualizado':now.isoformat(),'ultimo_dia':last,'acumulado':summary(allrows),
        'diario':summary(today),'ventana_30d':summary(window),'sorpresas':surprises,'fallas':failures,
        'pronosticos_registrados':len(list(directory.glob('*.json'))),'etiquetas':len(allrows),
        'aviso':'Sin etiquetas maduras no hay aciertos. IC Wilson descriptivo supone independencia; IC de diferencias agrupa por día. No afirmar ventaja tras selección de miles de contrastes; dirección no es rentabilidad neta (costos 0.1% por lado).'}
    from lab.enciclopedia import bh
    tests={f'{window}:{i}:{control}':s['p_'+control] for window in ('acumulado','diario','ventana_30d') for i,s in enumerate(r[window]) for control in ('siempre','azar')}
    adjusted=bh(tests)
    for window in ('acumulado','diario','ventana_30d'):
        for i,s in enumerate(r[window]):
            for control in ('siempre','azar'):s['q_'+control]=adjusted[f'{window}:{i}:{control}']
    r['contrastes_calculados']=len(tests)
    r['inferencia']='BH global sobre todos los contrastes calculados de3 ventanas, tipos/sectores/horizontes. Pruebas por diferencias de aciertos agrupadas por día, Newey-West5lags, mínimo30días; de lo contrario p=1. No demuestra rendimiento neto.'
    (ROOT/'resultados/marcador.json').write_text(json.dumps(r,ensure_ascii=False,allow_nan=False),encoding='utf8')
    print('Etiquetas:',len(allrows),'Pronósticos:',r['pronosticos_registrados'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('accion',choices=['registrar','calificar']);p.add_argument('--tipo',choices=['acción','cripto'],default='acción');a=p.parse_args()
    generate(a.tipo) if a.accion=='registrar' else score()
