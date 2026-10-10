"""Despachos por reloj y latidos persistentes; aceptar no equivale a ejecutar."""
import base64
import datetime as dt
import json
import os
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

UTC = dt.timezone.utc
PATH = 'contents/resultados/vigilante.json'


def api(path, method='GET', data=None):
    req = Request('https://api.github.com/repos/'+os.environ['GITHUB_REPOSITORY']+'/'+path,
                  data=json.dumps(data).encode() if data is not None else None, method=method,
                  headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],
                           'Accept':'application/vnd.github+json','User-Agent':'motor-vigilante'})
    with urlopen(req, timeout=30) as r:
        raw=r.read()
        return json.loads(raw) if raw else None


def due(now):
    """Ventanas de diez minutos; reintenta fallos dentro del mismo bloque."""
    block=now.replace(minute=now.minute//10*10, second=0, microsecond=0)
    tasks=[]
    if now.minute % 10 >= 3: tasks.append(('demo-cripto.yml', block.isoformat()))
    if now.minute % 10 >= 5: tasks.append(('aprendiz.yml', block.isoformat()))
    if now.minute % 10 >= 7: tasks.append(('escuela.yml', block.isoformat()))
    if now.minute >= 8: tasks.append(('pronostico.yml', block.replace(minute=8).isoformat()))
    for minute, flow in [(33,'gimnasio.yml'),(43,'fabrica-diaria.yml')]:
        if now.minute >= minute: tasks.append((flow, block.replace(minute=0).isoformat()))
    daily=[(0,0,'pronostico.yml'),(10,0,'pronostico.yml'),(22,30,'universo.yml'),
           (22,30,'vita-diario.yml'),(2,20,'archivar.yml'),(5,10,'fabrica.yml')]
    if now.isoweekday()==7: daily.append((3,35,'enciclopedia.yml'))
    if now.day==1: daily.append((23,0,'carteras-robots.yml'))
    for hour,minute,flow in daily:
        if now.hour==hour and now.minute>=minute:
            tasks.append((flow,now.replace(hour=hour,minute=minute,second=0,microsecond=0).isoformat()))
    return list(dict.fromkeys(tasks))


def health(state, now):
    start=max(dt.datetime.fromisoformat(state['desde']),now-dt.timedelta(hours=24))
    first=int(start.timestamp()//600)*600+180
    if first<start.timestamp(): first+=600
    expected=list(range(first,int(now.timestamp())+1,600))
    seen={int(dt.datetime.fromisoformat(x['slot']).timestamp())+180 for x in state['despachos']
          if x['workflow']=='demo-cripto.yml' and x['aceptado']}
    return {'ciclos_esperados_24h':len(expected),'ciclos_perdidos_24h':sum(t not in seen for t in expected),
            'cobertura_desde':start.isoformat()}


def load():
    try:
        doc=api(PATH)
        return json.loads(base64.b64decode(doc['content'])),doc['sha']
    except HTTPError as e:
        if e.code!=404: raise
        now=dt.datetime.now(UTC).isoformat()
        return {'version':1,'desde':now,'latidos':[],'despachos':[]},None


def publish(state,sha):
    data={'message':'latido vigilante '+state['ultimo_latido'],'branch':'main',
          'content':base64.b64encode(json.dumps(state,ensure_ascii=False).encode()).decode()}
    if sha: data['sha']=sha
    return api(PATH,'PUT',data)['content']['sha']


def run(minutes=350):
    state,sha=load();start=time.monotonic();last=None;dirty=False
    while time.monotonic()-start<minutes*60:
        now=dt.datetime.now(UTC)
        for flow,slot in due(now):
            if any(x['workflow']==flow and x['slot']==slot and x['aceptado'] for x in state['despachos']):continue
            item={'workflow':flow,'slot':slot,'hora':now.isoformat(),'aceptado':False}
            try:
                payload={'ref':'main'}
                if flow=='pronostico.yml':
                    payload['inputs']={'modo':'completo' if dt.datetime.fromisoformat(slot).minute==0 else 'calificar'}
                api('actions/workflows/'+flow+'/dispatches','POST',payload)
                item['aceptado']=True
            except Exception as e:item['error']=type(e).__name__
            state['despachos'].append(item);dirty=True
            print(json.dumps(item),flush=True)
        block=int(now.timestamp()//600)
        if block!=last or dirty:
            state['ultimo_latido']=now.isoformat();state['run_id']=os.environ['GITHUB_RUN_ID']
            state['latidos'].append({'hora':now.isoformat(),'run_id':state['run_id']})
            state['latidos']=state['latidos'][-600:]
            cutoff=(now-dt.timedelta(hours=48)).isoformat()
            state['despachos']=[x for x in state['despachos'] if x['hora']>=cutoff]
            state.update(health(state,now))
            try:
                runs=api('actions/workflows/demo-cripto.yml/runs?per_page=30')['workflow_runs']
                state['corridas_demo']=[{k:r[k] for k in ('id','event','created_at','status','conclusion','html_url')} for r in runs]
                sha=publish(state,sha);last=block;dirty=False
            except Exception as e:
                print('Latido pendiente:',type(e).__name__,flush=True)
                # Solo este flujo escribe este archivo. Releer SHA tras conflicto/timeout.
                try:_,sha=load()
                except Exception:pass
        time.sleep(20)
    for attempt in range(3):
        try:
            api('actions/workflows/vigilante.yml/dispatches','POST',{'ref':'main'});return
        except Exception as e:print('Relevo pendiente:',type(e).__name__,flush=True);time.sleep(20)
    raise RuntimeError('No se pudo solicitar relevo; queda cron de respaldo')


if __name__=='__main__':run()
