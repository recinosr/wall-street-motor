"""Reparar inventario oficial conservando unidades comunes de sociedades; no son warrants."""
import concurrent.futures as cf
import datetime as dt
import json
from pathlib import Path
from lab.universo import get,listed,NASDAQ,history,metrics

path=Path('resultados/universo.json');r=json.loads(path.read_text(encoding='utf8'))
known={x['sim'] for x in r['datos'] if x['tipo']!='cripto'}
fresh={x['sim']:x for f in ('nasdaqlisted.txt','otherlisted.txt') for x in listed(get(NASDAQ+f).text,f)}
missing=[x for x in fresh.values() if x['sim'] not in known]
def fill(x):
    try:x.update(metrics(history(x['sim'])))
    except Exception as e:x['error_cobertura']=str(e)[:120]
    return x
with cf.ThreadPoolExecutor(max_workers=8) as pool:r['datos']+=list(pool.map(fill,missing))
r['acciones_etfs']=sum(x['tipo']!='cripto' for x in r['datos'])
r['con_metricas']=sum(x.get('observaciones',0)>0 for x in r['datos'])
r['inventario_listados_actualizado']=dt.datetime.now(dt.timezone.utc).isoformat()
path.write_text(json.dumps(r,ensure_ascii=False,allow_nan=False),encoding='utf8')
print('Añadidos:',len(missing),'acciones/ETFs:',r['acciones_etfs'])
