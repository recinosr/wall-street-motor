"""Carteras educativas con aportes, dividendos netos, rebalanceo y ventanas comunes.

Fuentes nuevas públicas descargadas al ejecutar; no abre archivos históricos reservados.
Las mezclas son aproximaciones con ETFs, no las cuentas de sus autores.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
import requests
import yfinance as yf
import exchange_calendars as xc

ROOT=Path(__file__).resolve().parents[1]
COST=.001
CAL=xc.get_calendar('XNYS',start='1990-01-01',end='2035-12-31')
# Versiones fijas: no optimizamos pesos después de ver resultados.
PORTFOLIOS={
 '100% mundo':{'VT':1},
 '100% mundo acumulación':{'VWRA.L':1},
 'Bogleheads 3 fondos (60/40)':{'VTI':.42,'VXUS':.18,'BND':.4},
 'Buffett 90/10':{'CSPX.L':.9,'SHY':.1},
 'All Weather (aproximación sin apalancamiento)':{'VTI':.3,'TLT':.4,'IEF':.15,'GLD':.075,'DBC':.075},
 'Golden Butterfly':{'VTI':.2,'IJS':.2,'TLT':.2,'SHY':.2,'GLD':.2},
 'Permanent Portfolio':{'VTI':.25,'TLT':.25,'BIL':.25,'GLD':.25},
 '60/40 mundo/bonos':{'VT':.6,'BND':.4},
 'Swensen (personal, no fondo Yale)':{'VTI':.3,'VEA':.15,'VWO':.05,'VNQ':.2,'IEF':.15,'TIP':.15},
 '80/20 mundo/bonos':{'VT':.8,'BND':.2},
 '100% S&P':{'CSPX.L':1},
 '100% Nasdaq':{'QQQ':1},
 'Núcleo y satélites':{'VWRA.L':.8,'QQQ':.1,'BTC-USD':.1},
 'Jose 5x20':{'VWRA.L':.2,'QQQ':.2,'SCHD':.2,'BTC-USD':.2,'GLD':.2},
 'Jose 60/40 mundo/Nasdaq':{'VWRA.L':.6,'QQQ':.4},
 'Jose 60/20/20 mundo/Nasdaq/dividendos':{'VWRA.L':.6,'QQQ':.2,'SCHD':.2},
 'Jose 65/35 mundo/oro':{'VWRA.L':.65,'GLD':.35},
 'Jose 65/20/15 mundo/Nasdaq/BTC':{'VWRA.L':.65,'QQQ':.2,'BTC-USD':.15},
}
# Contrastes de historia más larga, identificados como equivalentes estadounidenses.
PORTFOLIOS.update({'Buffett 90/10 historia EEUU':{'SPY':.9,'SHY':.1},
                   '100% S&P historia EEUU':{'SPY':1}})
PORTFOLIOS['100% Nasdaq acumulación Irlanda']={'CNDX.L':1}
for name,alloc in list(PORTFOLIOS.items()):
    if 'VWRA.L' in alloc and len(alloc)>1:
        PORTFOLIOS[name+' historia VT EEUU']={('VT' if s=='VWRA.L' else s):w for s,w in alloc.items()}


def net_index(hist,tax=.3):
    c=hist['Close'].astype(float);div=hist.get('Dividends',pd.Series(0.,index=c.index)).fillna(0)
    factors=(c+div*(1-tax))/c.shift()
    if (factors.dropna()<=0).any():raise ValueError('Factor de retorno inválido')
    return factors.fillna(1).cumprod()


def download(symbol):
    ticker=yf.Ticker(symbol)
    h=ticker.history(period='max',auto_adjust=False,actions=True)
    if symbol.endswith('.L') and ticker.get_history_metadata().get('currency')!='USD':
        raise ValueError('La clase de Londres no llegó cotizada en USD')
    if len(h)<30:raise ValueError('Menos de30 sesiones')
    h.index=pd.to_datetime(h.index.date)
    # Nunca el precio extra en vivo; solo días ya terminados UTC.
    h=h[h.index<pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()]
    h=h[~h.index.duplicated()].dropna(subset=['Close'])
    tax=0 if symbol.endswith('.L') or symbol in ('GLD','BTC-USD') else .3
    return net_index(h,tax),h


def rebalance(positions,weights,cost=COST):
    """Resolver NAV posterior a costos cobrando únicamente cambios de posición."""
    value=float(positions.sum());net=value
    for _ in range(30):net=value-cost*np.abs(weights*net-positions).sum()
    return weights*net


def calendar_flags(index):
    months=index.to_period('M');first=np.r_[True,months[1:]!=months[:-1]]
    month_ends={m:CAL.date_to_session(m.end_time.normalize(),direction='previous').date() for m in months.unique()}
    last=[date.date()==month_ends[m] for date,m in zip(index,months)]
    years=index.year.to_numpy();annual=np.r_[False,years[1:]!=years[:-1]]
    return first,np.asarray(last),annual


def schedule(frame,weights,rule,flags=None):
    first,last,_=flags or calendar_flags(frame.index)
    execute=first.copy() if rule=='inicio' else last.copy() if rule=='fin' else np.zeros(len(frame),dtype=bool)
    missing=0
    if rule=='caida':
        # Señal al cierre anterior; compra al cierre posterior. Umbral5%, sin optimizar.
        bench=(frame/frame.iloc[0]).to_numpy()@weights
        peak=pd.Series(bench).rolling(20,min_periods=1).max().to_numpy()
        dd=bench/peak-1;waiting=False;had_signal=False
        for i in range(len(frame)):
            if first[i]:waiting=True;had_signal=False
            if waiting and i>0 and dd[i-1]<=-.05:
                execute[i]=True;waiting=False;had_signal=True
            if last[i] and waiting:execute[i]=True;waiting=False
            if last[i] and not had_signal:missing+=1
    return execute,missing


def simulate(frame,weights,monthly=100,rule='inicio',flags=None):
    weights=np.asarray(weights,float)
    if not np.isclose(weights.sum(),1) or (weights<0).any():raise ValueError('Pesos inválidos')
    flags=flags or calendar_flags(frame.index);first,last,annual=flags
    orders,missing=schedule(frame,weights,rule,flags)
    growth=frame.pct_change().fillna(0).to_numpy()+1
    positions=np.zeros(len(weights));cash=0.;total_in=0.;values=[];unit=[];factor=1.;prior=0.
    for i,mult in enumerate(growth):
        positions*=mult;deposit=monthly if first[i] else 0.;cash+=deposit;total_in+=deposit
        if orders[i] and cash>0:positions+=cash/(1+COST)*weights;cash=0.
        if annual[i] and positions.sum()>0:positions=rebalance(positions,weights)
        value=positions.sum()+cash
        if prior>0:factor*=max(0,(value-deposit)/prior)
        elif value>0:factor=value/total_in
        values.append(value);unit.append(factor);prior=value
    return {'valor_final':float(values[-1]),'aportado':total_in,'serie':np.asarray(values),'posiciones_finales':positions,
            'unit':np.asarray(unit),'sin_senal':missing}


def performance(unit,index):
    peak=np.maximum.accumulate(unit);dd=unit/peak-1
    start=None;max_days=0
    for i,v in enumerate(dd):
        if v< -1e-10 and start is None:start=max(0,i-1)
        elif v>= -1e-10 and start is not None:
            max_days=max(max_days,(index[i]-index[start]).days);start=None
    if start is not None:max_days=max(max_days,(index[-1]-index[start]).days)
    years=(index[-1]-index[0]).days/365.25
    return {'ret_anual_pct':100*(unit[-1]**(1/years)-1) if years>0 else None,
            'peor_caida_pct':float(dd.min()*100),'recuperacion_dias':max_days,'sin_recuperar':start is not None}


def windows(frame,weights,benchmark):
    # El peor decenio usa toda la historia de la cartera, aunque VT aún no existiera.
    joint=frame.copy()
    starts=joint.groupby(joint.index.to_period('M')).head(1).index
    full_flags=calendar_flags(joint.index)
    results=[]
    for start in starts:
        end=start+pd.DateOffset(years=10)
        if end>joint.index[-1]:continue
        cut=joint.loc[start:end]
        idx=joint.index.get_indexer(cut.index)
        flags=tuple(f[idx] for f in full_flags)
        a=simulate(cut[frame.columns],weights,100,flags=flags)
        shared=cut.index.intersection(benchmark.index)
        b=matched=None
        if len(shared)>2000 and benchmark.index[0]<=cut.index[0] and benchmark.index[-1]>=cut.index[-1]:
            common_flags=calendar_flags(shared)
            matched=simulate(cut.loc[shared],weights,100,flags=common_flags)
            b=simulate(benchmark.loc[shared].to_frame('__world'),[1.],100,flags=common_flags)
        results.append({'desde':start.date().isoformat(),'hasta':cut.index[-1].date().isoformat(),
                        'ret_anual_pct':performance(a['unit'],cut.index)['ret_anual_pct'],
                        'valor':a['valor_final'],'valor_comparable':matched['valor_final'] if matched else None,
                        'mundo':b['valor_final'] if b else None})
    shared=frame.index.intersection(benchmark.index)
    return results,shared[0].date().isoformat() if len(shared) else None


def monthly_wins(frame,weights,rule,flags):
    first,last,_=flags;orders,_=schedule(frame,weights,rule,flags)
    starts=np.flatnonzero(first);wins=ties=n=0
    values=frame.to_numpy()
    for start in starts:
        ends=np.flatnonzero(last[start:])
        if not len(ends):continue
        end=start+ends[0]
        purchases=np.flatnonzero(orders[start:end+1]);entry=start+purchases[0] if len(purchases) else None
        base=float((values[end]/values[start])@weights)/(1+COST)
        other=float((values[end]/values[entry])@weights)/(1+COST) if entry is not None else 1.
        wins+=other>base+1e-10;ties+=abs(other-base)<=1e-10;n+=1
    return {'meses_gana_pct':wins/n*100 if n else None,'meses_empata':ties,'meses_completos':n}


def verify_quote(symbol,hist):
    """Segunda fuente independiente: Stooq, solo cierre comparable, nunca ajustar silenciosamente."""
    import html,re
    date=hist.index[-1].date().isoformat();price=float(hist.Close.iloc[-1])
    # Corroboración del cierre final de la simulación, además de cobertura histórica publicada.
    try:
        if symbol=='BTC-USD':
            start=dt.datetime.fromisoformat(date).replace(tzinfo=dt.timezone.utc)
            rows=requests.get('https://api.exchange.coinbase.com/products/BTC-USD/candles',params={
                'granularity':86400,'start':start.isoformat(),'end':(start+dt.timedelta(days=1)).isoformat()},timeout=25).json()
            refs=[float(r[4]) for r in rows if r[0]==int(start.timestamp())]
            ref=refs[0] if refs else None;url='Coinbase BTC-USD diario'
        else:
            url=('https://markets.ft.com/data/etfs/tearsheet/historical?s='+symbol[:-2]+':LSE:USD') if symbol.endswith('.L') else 'https://chartexchange.com/symbol/'+('nasdaq' if symbol=='QQQ' else 'nyse')+'-'+symbol.lower()+'/historical/'
            response=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=25);ref=None
            if not symbol.endswith('.L') and (not response.ok or date not in response.text):
                url=url.replace('/nyse-','/nasdaq-') if '/nyse-' in url else url.replace('/nasdaq-','/nyse-')
                response=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=25);response.raise_for_status()
            response.raise_for_status()
            for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',response.text,re.S):
                cells=[html.unescape(re.sub('<[^>]+>','',v)).strip() for v in re.findall(r'<td\b[^>]*>(.*?)</td>',row,re.S)]
                if len(cells)<5:continue
                rowdate=cells[0]
                if symbol.endswith('.L'):
                    match=re.search(r'(?:Monday|Tuesday|Wednesday|Thursday|Friday), ([A-Za-z]+ \d{2}, \d{4})',rowdate)
                    if not match:continue
                    rowdate=dt.datetime.strptime(match.group(1),'%B %d, %Y').date().isoformat()
                if rowdate==date:ref=float(cells[4].replace(',',''));break
        if ref is not None:
            diff=(ref/price-1)*100
            return {'estado':'coincide' if abs(diff)<=.05 else 'diverge','fuente':url,'fecha':date,
                    'diferencia_pct':diff,'alcance':'Cierre final a0.05%; no valida serie completa/dividendos. Coinbase es otro mercado y puede diferir.'}
    except Exception:pass
    if symbol.endswith('.L') or symbol=='BTC-USD':return {'estado':'pendiente','fuente':'Segundo proveedor Londres/BTC no corroboró el cierre'}
    try:
        import io
        r=requests.get('https://stooq.com/q/d/l/',params={'s':symbol.lower()+'.us','i':'d'},timeout=25)
        r.raise_for_status();table=pd.read_csv(io.StringIO(r.text))
        table['Date']=pd.to_datetime(table['Date']);date=hist.index[-1]
        same=table[table.Date==date]
        if len(same)!=1:return {'estado':'pendiente','fuente':'Stooq','fecha':date.date().isoformat()}
        delta=float(same.Close.iloc[0]-hist.Close.iloc[-1])
        return {'estado':'coincide' if abs(delta)<=.02 else 'diverge','fuente':'Stooq',
                'fecha':date.date().isoformat(),'diferencia_usd':round(delta,4),
                'alcance':'Solo cierre final; no valida todos los dividendos ni toda la serie.'}
    except Exception as e:return {'estado':'pendiente','fuente':'Stooq','error':str(e)[:80]}


def build():
    t=time.time();symbols=sorted({s for p in PORTFOLIOS.values() for s in p});prices={};verification={};failures=[]
    def one(sym):
        try:
            series,h=download(sym);return sym,series,verify_quote(sym,h),None
        except Exception as e:return sym,None,None,str(e)[:150]
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        for sym,series,proof,error in pool.map(one,symbols):
            if error:failures.append({'sim':sym,'error':error})
            else:prices[sym]=series;verification[sym]=proof
    portfolios=[]
    for name,alloc in PORTFOLIOS.items():
        if any(s not in prices for s in alloc):failures.append({'cartera':name,'error':'Componente sin datos; no sustituir silenciosamente'});continue
        f=pd.concat({s:prices[s] for s in alloc},axis=1,join='inner').dropna();weights=np.asarray(list(alloc.values()))
        if len(f)<30:continue
        flags=calendar_flags(f.index);sim=simulate(f,weights,flags=flags)
        win,common=windows(f,weights,prices['VT']) if 'VT' in prices else ([],None)
        timing=[]
        for rule in ('inicio','fin','caida'):
            result=simulate(f,weights,rule=rule,flags=flags)
            timing.append({'regla':rule,'valor_final':round(result['valor_final'],2),
                'sin_senal':result['sin_senal'],**monthly_wins(f,weights,rule,flags)})
        portfolios.append({'nombre':name,'pesos':alloc,'instrumentos':', '.join(f'{s} {v*100:g}%' for s,v in alloc.items()),
            'desde':f.index[0].date().isoformat(),'hasta':f.index[-1].date().isoformat(),**performance(sim['unit'],f.index),
            'aportes':[{'mensual':m,'aportado':sim['aportado']*m/100,'valor_final':round(sim['valor_final']*m/100,2)} for m in (50,100)],
            'ventanas_10a':len(win),'peor_10a_anual_pct':min((w['ret_anual_pct'] for w in win),default=None),
            'ventanas_comparables_mundo':sum(w['mundo'] is not None for w in win),
            'ventanas_gana_mundo_pct':sum(w['valor_comparable']>w['mundo'] for w in win if w['mundo'] is not None)/sum(w['mundo'] is not None for w in win)*100 if any(w['mundo'] is not None for w in win) else None,
            'comparacion_desde':common,'ventanas':win,'timing':timing,
            'verificacion':{s:verification[s] for s in alloc}})
        portfolios[-1]['sensibilidad_cierre_final_usd']=sum(sim['posiciones_finales'][i]*verification[s].get('diferencia_pct',0)/100 for i,s in enumerate(alloc) if verification[s]['estado']=='diverge')
    if not portfolios:raise RuntimeError('No hay carteras con datos: '+str(failures))
    return {'version':1,'actualizado':dt.datetime.now(dt.timezone.utc).isoformat(),'corte':max(x['hasta'] for x in portfolios),
        'carteras':portfolios,'fallas':failures,'segundos':round(time.time()-t,2),
        'comparaciones':len(PORTFOLIOS)*3,'carteras_declaradas':len(PORTFOLIOS),
        'aviso':'Estudio retrospectivo, no cartera personal ni promesa. US$100 ficticios por mes; costos 0.1% por lado dentro del aporte, rebalanceo anual solo cambios. Dividendos EEUU netos de30% reinvertidos al exdividendo como aproximación; acumulación irlandesa sin doble retención. Retorno anual ponderado por tiempo y caída sin aportes; ventanas10años inician mensualmente y comparan capital final con VT sobre mismas fechas. Historia variable: no comparar valores finales de períodos distintos. Esperar caída =5% desde máximo20 sesiones conocido, comprar cierre posterior o fin de mes; efectivo sin interés. Pesos Jose asignados provisionalmente a activos explícitos. Fuera: fondeo/cambio/retiros, impuestos locales. Segunda fuente de precios con cobertura parcial; cifras provisionales donde no está verificada.'}


def build_robots():
    """Banco separado de reglas públicas; no altera las cuentas prospectivas."""
    from .carteras_robots import build as robot_build
    return robot_build()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--salida',default=None);p.add_argument('--robots',action='store_true');a=p.parse_args();r=build_robots() if a.robots else build()
    a.salida=a.salida or ('salida/carteras_robots.json' if a.robots else 'salida/carteras.json')
    path=Path(a.salida);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(r,ensure_ascii=False,allow_nan=False),encoding='utf8')
    print('Carteras:',len(r.get('carteras',r.get('robots',[]))),'segundos:',r['segundos'],'fallas:',len(r['fallas']))
