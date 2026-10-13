"""Piloto22 LLM prospectivo: publicación previa, recibo, etiquetas maduras.

No se invoca sin confirmación de nivel gratuito. Un intento diario en lote,
incluso si da429/timeout/JSON inválido. Sin backtests ni edición de forecasts.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import numpy as np
import pandas as pd
import requests
from .boveda_meses import BovedaMes, MotorMes, METHODS
from .boveda_ejecutar import descargar
from .pronostico import CAL, digest, save_once, receipt

ROOT=Path(__file__).resolve().parents[1]
DIRECTORY=ROOT/'resultados/vita_meses'
CONFIG=json.loads((ROOT/'agente/vita_meses.json').read_text(encoding='utf8'))
PROMPT=(ROOT/CONFIG['prompt']).read_text(encoding='utf8')
SIGNATURE=digest(dict(config=CONFIG,prompt=PROMPT))
UTC=dt.timezone.utc


def validate(response):
    out=response.get('pronosticos') if isinstance(response,dict) else None
    if not isinstance(out,dict) or set(out)!=set(CONFIG['activos']):raise ValueError('Deben ser exactamente diez activos')
    for value in out.values():
        p=value.get('p_sube');reason=value.get('razon')
        if type(p) not in (int,float) or not np.isfinite(p) or not 0<=p<=1:raise ValueError('Probabilidad inválida')
        if not isinstance(reason,str) or len(reason)>240:raise ValueError('Razón inválida')
    return out


def before_open(now):
    day=pd.Timestamp(now.date())
    if not CAL.is_session(day):return None
    deadline=CAL.session_open(day)
    if pd.Timestamp(now)>=deadline:return None
    return day,deadline,CAL.previous_session(day)


def reserve(now=None):
    now=now or dt.datetime.now(UTC);window=before_open(now)
    if not window or str(now.date())<CONFIG['inicio_minimo']:return 'Fuera de ventana'
    if os.environ.get('VITA_MESES_FREE_TIER_CONFIRMED')!='true' or not os.environ.get('GEMINI_API_KEY'):
        return 'Preparado; sin llamada mientras falte confirmar gratuidad/clave'
    if not os.environ.get('GITHUB_RUN_ID'):return 'Solo ejecución registrada en Actions'
    path=DIRECTORY/'intentos'/(str(now.date())+'.json')
    if path.exists():return 'Ya reservado: no reintentar ni transferir a otra ejecución'
    save_once(path,dict(fecha=now.isoformat(),firma=SIGNATURE,modelo=CONFIG['modelo'],
        solicitudes_maximas=1,run_id=os.environ['GITHUB_RUN_ID'],
        run_attempt=os.environ.get('GITHUB_RUN_ATTEMPT','1')))
    return 'Reserva creada: debe publicarse antes de llamar'


def generate(now=None):
    now=now or dt.datetime.now(UTC);window=before_open(now)
    if not window:return 'Sin sesión o apertura ya ocurrió; ninguna llamada'
    if str(now.date())<CONFIG['inicio_minimo']:return 'Antes del inicio congelado'
    day,deadline,previous=window;path=DIRECTORY/(str(day.date())+'.json')
    attempt=DIRECTORY/'intentos'/(str(day.date())+'.json')
    if path.exists():return 'Día ya pronosticado; no duplicar llamada'
    if os.environ.get('VITA_MESES_FREE_TIER_CONFIRMED')!='true':return 'Preparado: falta verificar nivel gratuito en AI Studio'
    token=os.environ.get('GEMINI_API_KEY')
    if not token:return 'Preparado: GEMINI_API_KEY no configurada en este repositorio'
    if not attempt.exists():return 'Sin reserva publicada; ninguna llamada'
    reservation=json.loads(attempt.read_text(encoding='utf8'))
    if (reservation.get('run_id')!=os.environ.get('GITHUB_RUN_ID') or
        reservation.get('run_attempt')!=os.environ.get('GITHUB_RUN_ATTEMPT','1')):
        return 'Reserva de otra ejecución/otro intento; ninguna llamada'
    # Antes de red: la reserva debe estar en el remoto, no solo en el disco local.
    import subprocess
    rel=attempt.relative_to(ROOT).as_posix()
    commits=subprocess.check_output(['git','-c','safe.directory=*','log','--diff-filter=A','--format=%H','--',rel],cwd=ROOT,text=True).strip().splitlines()
    if len(commits)!=1:return 'Reserva no comprometida; ninguna llamada'
    if subprocess.run(['git','-c','safe.directory=*','merge-base','--is-ancestor',commits[0],'origin/main'],cwd=ROOT).returncode:
        return 'Reserva sin publicación verificada; ninguna llamada'
    contexts={};rows=[]
    for sim in CONFIG['activos']:
        d,source=descargar(sim,str(previous.date()))
        if d.index[-1]!=previous or not np.isfinite(d.close.iloc[-1]):raise ValueError('Contexto no fresco: '+sim)
        vault=BovedaMes(d);past=vault.ver(day)
        model=MotorMes(sim,vault.ver('2019-01-01'))
        p=model.pronosticar(past,[day],'A_primero')[0]
        feature=past.rasgos.iloc[-1]
        if not np.isfinite(feature[['r1','r5','mom','vol','dist']]).all():raise ValueError('Rasgos incompletos')
        contexts[sim]=dict(hasta=str(previous.date()),rasgos={k:round(float(feature[k]),6) for k in ('r1','r5','mom','vol','dist')},
                          comparadores=dict(zip(METHODS,p.tolist())))
        rows.append(dict(sim=sim,ancla=str(previous.date()),objetivo=str(day.date()),predicciones=dict(zip(METHODS,p.tolist())),fuente_sha256=source['sha256_respuesta']))
    if dt.datetime.now(UTC)>=deadline.to_pydatetime():return 'Se agotó ventana antes de llamar; abstención'
    # La reserva durable pertenece a un único run/attempt. El workflow contiene
    # un solo paso de generación: reejecutar Actions cambia run_attempt y se rechaza.
    # API key por cabecera, nunca URL ni log. Sin tools/grounding ni reintentos.
    schema={'type':'OBJECT','properties':{'pronosticos':{'type':'OBJECT','properties':{
        s:{'type':'OBJECT','properties':{'p_sube':{'type':'NUMBER'},'razon':{'type':'STRING'}},'required':['p_sube','razon']} for s in CONFIG['activos']},'required':CONFIG['activos']}},'required':['pronosticos']}
    context=json.dumps(dict(objetivo=str(day.date()),activos=contexts),ensure_ascii=False,allow_nan=False)
    response=requests.post('https://generativelanguage.googleapis.com/v1beta/models/'+CONFIG['modelo']+':generateContent',
        headers={'x-goog-api-key':token,'Content-Type':'application/json'},json={
            'systemInstruction':{'parts':[{'text':PROMPT}]},'contents':[{'role':'user','parts':[{'text':context}]}],
            'generationConfig':{'temperature':0,'maxOutputTokens':CONFIG['max_output_tokens'],
                'thinkingConfig':{'thinkingBudget':0},'responseMimeType':'application/json','responseSchema':schema}},timeout=50)
    # No imprimir cuerpo ni request si falla; puede incluir datos o credenciales.
    if response.status_code!=200:return 'Intento consumido: HTTP'+str(response.status_code)+'; sin reintento'
    body=response.json();parts=body.get('candidates',[{}])[0].get('content',{}).get('parts',[])
    result=validate(json.loads(''.join(p.get('text','') for p in parts if not p.get('thought'))))
    if pd.Timestamp(dt.datetime.now(UTC))>=deadline:return 'Respuesta tardía; no publicar pronóstico'
    for row in rows:
        row['predicciones']['vita']=float(result[row['sim']]['p_sube']);row['razon']=result[row['sim']]['razon']
    save_once(path,dict(version=1,publicado=dt.datetime.now(UTC).isoformat(),deadline=deadline.isoformat(),
        firma_prompt=SIGNATURE,modelo=CONFIG['modelo'],corte_entrenamiento=CONFIG['corte_entrenamiento_oficial'],
        run_id=os.environ.get('GITHUB_RUN_ID'),filas=rows,contexto_sha256=digest(contexts),
        aviso='Prospectivo, no backtest; contexto hasta cierre previo; sin OHLC público ni operaciones.'))
    return 'Diez pronósticos guardados; aún requieren publicación y recibo previo a apertura'


def proof(path,payload):
    result=receipt(path,payload)
    if not result:return None
    r=requests.get('https://api.github.com/repos/recinosr/wall-street-motor/actions/runs/'+str(payload['run_id']),
        headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'},timeout=25)
    r.raise_for_status();run=r.json()
    # El recibo servidor también debe preceder apertura, no solo el commit local.
    if run.get('status')!='completed' or run.get('conclusion')!='success' or pd.Timestamp(run['updated_at'])>=pd.Timestamp(payload['deadline']):return None
    if payload.get('firma_prompt')!=SIGNATURE:raise ValueError('Versión diferente; preservar separado, no mezclar')
    return {**result,'recibo_completado':run['updated_at']}


def score(now=None):
    now=now or dt.datetime.now(UTC);records=[];pending=[];errors=[]
    directory=DIRECTORY/'calificaciones';directory.mkdir(parents=True,exist_ok=True)
    for path in sorted(DIRECTORY.glob('????-??-??.json')):
        payload=json.loads(path.read_text(encoding='utf8'))
        try:verification=proof(path,payload)
        except Exception:errors.append(dict(archivo=path.name,error='No se verificó publicación/recibo'));continue
        if not verification:pending.append(dict(archivo=path.name,estado='sin recibo previo verificable'));continue
        for row in payload['filas']:
            dest=directory/(digest(dict(forecast=payload['sha256'],sim=row['sim']))+'.json')
            if dest.exists():continue
            target=pd.Timestamp(row['objetivo'])
            if pd.Timestamp(now)<CAL.session_close(target)+pd.Timedelta(minutes=15):continue
            try:
                d,_=descargar(row['sim'],str(now.date()))
                prices=d.close.reindex(pd.to_datetime([row['ancla'],row['objetivo']]))
                if not np.isfinite(prices).all() or (prices<=0).any():raise ValueError('Cierre exacto ausente')
                y=int(prices.iloc[1]>prices.iloc[0]);ret=float(prices.iloc[1]/prices.iloc[0]-1)
                save_once(dest,dict(sim=row['sim'],objetivo=row['objetivo'],y=y,retorno=ret,
                    predicciones=row['predicciones'],prueba=verification,medido=now.isoformat()))
            except Exception:errors.append(dict(sim=row['sim'],error='Fuente no disponible; etiqueta pendiente'))
    for path in directory.glob('*.json'):records.append(json.loads(path.read_text(encoding='utf8')))
    methods=(*METHODS,'vita');summary=[]
    for method in methods:
        rows=[r for r in records if method in r['predicciones']]
        summary.append(dict(metodo=method,n=len(rows),
            acierto=float(np.mean([(r['predicciones'][method]>=.5)==bool(r['y']) for r in rows])) if rows else None,
            brier=float(np.mean([(r['predicciones'][method]-r['y'])**2 for r in rows])) if rows else None))
    state=dict(version=1,actualizado=now.isoformat(),firma_prompt=SIGNATURE,config=CONFIG,
        estado='activo' if os.environ.get('GEMINI_API_KEY') and os.environ.get('VITA_MESES_FREE_TIER_CONFIRMED')=='true' else 'preparado; faltan clave en motor o confirmación de nivel gratuito',
        dias_calificados=len(set(r['objetivo'] for r in records)),marcador=summary,pendientes=pending,errores=errors,
        registrados=len(list(DIRECTORY.glob('????-??-??.json'))),
        aviso='Sin etiquetas no hay acierto; nunca se rellena pasado con LLM. Marcador descriptivo de10 activos correlacionados, sin habilidad ni retorno demostrados.')
    (ROOT/'resultados/vita_meses.json').write_text(json.dumps(state,ensure_ascii=False,allow_nan=False),encoding='utf8')
    return state


def main():
    p=argparse.ArgumentParser();p.add_argument('accion',choices=['reservar','registrar','calificar']);a=p.parse_args()
    if a.accion=='reservar':print(reserve());return
    if a.accion=='registrar':
        try:print(generate())
        except Exception:print('No se publicó: fuente/JSON inválido; no repetir intento LLM hoy')
    else:print('Días calificados:',score()['dias_calificados'])

if __name__=='__main__':main()
