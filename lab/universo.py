"""Universo oficial; publica métricas derivadas, nunca series OHLC licenciadas."""
import argparse
import concurrent.futures as cf
import datetime as dt
import io
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
UA = {'User-Agent': 'Mozilla/5.0'}
NASDAQ = 'https://www.nasdaqtrader.com/dynamic/SymDir/'


def get(url, **kwargs):
    r = requests.get(url, timeout=40, headers=kwargs.pop('headers', UA), **kwargs)
    r.raise_for_status()
    return r


def listed(text, source):
    out = []
    for r in pd.read_csv(io.StringIO(text), sep='|', dtype=str).fillna('').to_dict('records'):
        sim = r.get('Symbol') or r.get('ACT Symbol') or ''
        name = r.get('Security Name', '')
        if not sim or 'File Creation' in sim or r.get('Test Issue') != 'N':
            continue
        if any(x in name.lower() for x in ('warrant', ' rights', ' units')) or '$' in sim:
            continue
        out.append({'sim': sim.replace('.', '-'), 'nombre': name,
                    'tipo': 'ETF' if r.get('ETF') == 'Y' else 'acción',
                    'bolsa': r.get('Exchange') or {'Q': 'NASDAQ Global Select', 'G': 'NASDAQ Global', 'S': 'NASDAQ Capital'}.get(r.get('Market Category'), 'NASDAQ'),
                    'fuente_lista': source})
    return out


def history(sim, period='2y'):
    j = get('https://query1.finance.yahoo.com/v8/finance/chart/' + sim,
            params={'range': period, 'interval': '1d', 'events': 'div,splits'}).json()['chart']['result'][0]
    q = j['indicators']['quote'][0]
    d = pd.DataFrame(q, index=pd.to_datetime(j['timestamp'], unit='s', utc=True))
    # Solo velas de sesiones terminadas. No usar la vela intradía de Yahoo.
    d = d[d.index.normalize() + pd.Timedelta(hours=21, minutes=15) <= pd.Timestamp.now(tz='UTC')]
    return d.dropna(subset=['close'])


def metrics(d, annual=252):
    c = d['close']; r = c.pct_change().dropna()
    out = {'fecha': d.index[-1].date().isoformat(), 'observaciones': len(c),
           'cambio_dia_pct': float((c.iloc[-1]/c.iloc[-2]-1)*100) if len(c)>1 else None,
           'volatilidad_anual_pct': float(r.std()*np.sqrt(annual)*100),
           'peor_caida_pct': float((c/c.cummax()-1).min()*100),
           'caida_max_pct': float((c.iloc[-1]/c.max()-1)*100),
           'volumen_medio_usd': float((d['volume']*c).tail(20).mean()) if 'volume' in d else None}
    for n, k in ((21,'1'),(63,'3'),(252,'12')):
        out['momentum_'+k+'m_pct'] = float((c.iloc[-1]/c.iloc[-n-1]-1)*100) if len(c)>n else None
    out['momentum_12_1_pct'] = float((c.iloc[-22]/c.iloc[-253]-1)*100) if len(c)>252 else None
    return {k: (round(v,4) if isinstance(v,float) and np.isfinite(v) else None if isinstance(v,float) else v) for k,v in out.items()}


def spark(symbols):
    """Lotes20; spark no garantiza volumen: se mide aparte, nunca se inventa."""
    j = get('https://query1.finance.yahoo.com/v7/finance/spark', params={
        'symbols': ','.join(symbols), 'range': '2y', 'interval': '1d'}).json()
    out = {}
    for x in j.get('spark',{}).get('result',[]):
        a = x['response'][0]; q = a['indicators']['quote'][0]
        d = pd.DataFrame(q,index=pd.to_datetime(a['timestamp'],unit='s',utc=True))
        d = d[d.index.normalize()+pd.Timedelta(hours=21,minutes=15)<=pd.Timestamp.now(tz='UTC')].dropna(subset=['close'])
        if len(d)>1: out[x['symbol']] = metrics(d)
    return out


DESCRIPTIONS = {'BTC':'Bitcoin: red de transferencias y activo digital de oferta limitada.',
 'ETH':'Ethereum: red para contratos y aplicaciones programables.',
 'LINK':'Chainlink: conecta contratos con datos externos mediante oráculos.',
 'SOL':'Solana: red para contratos y aplicaciones con alta capacidad.',
 'USDC':'USDC: token que busca seguir el dólar mediante reservas del emisor.',
 'USDT':'Tether: token que busca seguir el dólar mediante reservas del emisor.',
 'XRP':'XRP: activo de una red para transferencias y liquidación.',
 'DOGE':'Dogecoin: moneda digital usada en transferencias y comunidades.'}


def crypto():
    failures=[]; assets={}
    try:
        rows=get('https://api.coingecko.com/api/v3/coins/markets',params={
            'vs_currency':'usd','order':'market_cap_desc','per_page':100,'page':1,
            'price_change_percentage':'7d,30d'}).json()
        for r in rows:
            key=r['id']; sym=r['symbol'].upper()
            assets[key]={'sim':sym+'-USD','id':key,'nombre':r['name'],'tipo':'cripto',
                'capitalizacion':r['market_cap'],'volumen_24h_usd':r['total_volume'],
                'cambio_dia_pct':r.get('price_change_percentage_24h'),
                'cambio_7d_pct':r.get('price_change_percentage_7d_in_currency'),
                'cambio_30d_pct':r.get('price_change_percentage_30d_in_currency'),
                'caida_ath_pct':r.get('ath_change_percentage'),
                'precio':r.get('current_price'), 'fecha':r.get('last_updated'),
                'descripcion':DESCRIPTIONS.get(sym, f"{r['name']}: criptoactivo; utilidad específica pendiente de verificación."),
                'fuente':'CoinGecko'}
    except Exception as e: failures.append('CoinGecko: '+str(e)[:120])
    products=get('https://api.exchange.coinbase.com/products').json()
    pairs=[p for p in products if p.get('quote_currency')=='USD' and not p.get('trading_disabled')]
    def one(p):
        sym=p['base_currency']; match=next((x for x in assets.values() if x['sim']==sym+'-USD'),None)
        row=dict(match or {'sim':p['id'],'nombre':p.get('display_name',sym),'tipo':'cripto',
            'descripcion':DESCRIPTIONS.get(sym,'Criptoactivo negociado en Coinbase; utilidad pendiente de verificación.')})
        row['coinbase']=p['id']
        try:
            s=get('https://api.exchange.coinbase.com/products/'+p['id']+'/stats').json()
            row.update(precio=float(s['last']), volumen_24h_usd=float(s['volume'])*float(s['last']),
                       cambio_dia_pct=(float(s['last'])/float(s['open'])-1)*100)
        except Exception as e: row['error']=str(e)[:100]
        time.sleep(.12)
        return row
    with cf.ThreadPoolExecutor(max_workers=3) as pool: extra=list(pool.map(one,pairs))
    seen={x['sim'] for x in extra}
    return extra+[x for x in assets.values() if x['sim'] not in seen], failures


def inverse(catalog):
    out={}
    for e in catalog.get('etfs',[]):
        for h in e.get('top',[]):
            out.setdefault(h['sim'],[]).append({'etf':e['sim'],'peso_pct':h['peso_pct']})
    return {'cobertura':'Solo posiciones disponibles en la fuente (normalmente top10); ausencia no significa peso cero.', 'empresas':out}


def build():
    started=time.time(); failures=[]
    stocks={x['sim']:x for f in ('nasdaqlisted.txt','otherlisted.txt') for x in listed(get(NASDAQ+f).text,f)}
    # Sector/industria conocidos del S&P, cobertura explícita fuera del índice.
    from lab import sp500
    try:
        for x in sp500.lista():
            if x['sim'] in stocks: stocks[x['sim']].update({k:x[k] for k in ('cik','sector','industria')})
    except Exception as e: failures.append('Sectores S&P: '+str(e)[:100])
    contact=os.environ.get('SEC_CONTACT')
    if contact:
        try:
            tickers=get('https://www.sec.gov/files/company_tickers.json',headers={'User-Agent':contact}).json()
            for t in tickers.values():
                if t['ticker'].replace('.','-') in stocks: stocks[t['ticker'].replace('.','-')]['cik']=t['cik_str']
            fund=sp500.fundamentales(sorted({x['cik'] for x in stocks.values() if x.get('cik')}),contact,dt.date.today().year-1)
            for x in stocks.values():
                if x.get('cik') in fund:
                    x['fundamentales']=sp500.metricas(fund[x['cik']],None)
                    x['fuentes_fundamentales']=fund[x['cik']]
        except Exception as e: failures.append('SEC: '+str(e)[:100])
    symbols=list(stocks)
    for i in range(0,len(symbols),20):
        batch=symbols[i:i+20]
        try:
            for sym,m in spark(batch).items(): stocks[sym].update(m)
        except Exception as e: failures.append('Spark '+','.join(batch)+': '+str(e)[:80])
        time.sleep(.3)
    # Chart tiene volumen; lotes concurrentes acotados, sin escribir precios fuente.
    def volume(sym):
        try: return sym,metrics(history(sym))
        except Exception: return sym,{'error_cobertura':'Sin historial/volumen verificable.'}
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        for sym,m in pool.map(volume,symbols): stocks[sym].update(m)
    coins,err=crypto(); failures+=err
    data=list(stocks.values())+coins
    result={'version':1,'actualizado':dt.datetime.now(dt.timezone.utc).isoformat(),
        'datos':data,'acciones_etfs':len(stocks),'cripto':len(coins),
        'con_metricas':sum(x.get('observaciones',0)>0 for x in data),
        'con_fundamentales':sum(bool(x.get('fundamentales')) for x in data),
        'sector_conocido':sum(bool(x.get('sector')) for x in data),
        'fallas':failures,'segundos':round(time.time()-started,2),
        'aviso':'Universo actual, no histórico sin supervivencia. Métricas descriptivas; no ventaja futura. Precios bursátiles y series OHLC no se publican.'}
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--salida',default='resultados/universo.json'); a=p.parse_args()
    r=build(); Path(a.salida).parent.mkdir(parents=True,exist_ok=True)
    Path(a.salida).write_text(json.dumps(r,ensure_ascii=False,allow_nan=False),encoding='utf8')
    print({k:r[k] for k in ('acciones_etfs','cripto','con_metricas','con_fundamentales','segundos')})
