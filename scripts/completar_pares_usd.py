"""Completar inventario USD inactivo sin repetir series ni cotizaciones."""
import datetime as dt
import json
from pathlib import Path
from lab.universo import get,DESCRIPTIONS

path=Path('resultados/universo.json');r=json.loads(path.read_text(encoding='utf8'))
existing={x['sim']:x for x in r['datos'] if x['tipo']=='cripto'}
products=get('https://api.exchange.coinbase.com/products').json()
for p in products:
    if p.get('quote_currency')!='USD':continue
    if p['id'] in existing:
        existing[p['id']]['coinbase_estado']=p.get('status')
        if p.get('trading_disabled'):existing[p['id']]['coinbase_inactivo']=True
        continue
    if not p.get('trading_disabled'):raise RuntimeError('Falta par activo; requiere datos actuales: '+p['id'])
    sym=p['base_currency']
    r['datos'].append({'sim':p['id'],'nombre':p.get('display_name',sym),'tipo':'cripto',
        'coinbase':p['id'],'coinbase_estado':p.get('status'),'coinbase_inactivo':True,
        'descripcion':DESCRIPTIONS.get(sym,'Criptoactivo con par USD inactivo en Coinbase; función específica pendiente de verificación.'),
        'error_cobertura':'Sin cotización actual verificable en Coinbase; no inventar cambios.',
        'fuente':'Coinbase directorio oficial'})
r['cripto']=sum(x['tipo']=='cripto' for x in r['datos'])
r['inventario_cripto_actualizado']=dt.datetime.now(dt.timezone.utc).isoformat()
path.write_text(json.dumps(r,ensure_ascii=False,allow_nan=False),encoding='utf8')
print('Cripto inventario:',r['cripto'],'USD Coinbase:',sum(x.get('quote_currency')=='USD' for x in products))
