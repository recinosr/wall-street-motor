"""Pantalla descriptiva pública: concentración, aportes y momentum causal.

Descarga nueva en memoria, corte anterior a abril2025; nunca lee reserva.
Universo actual: supervivencia. No inferencia causal ni elección personal.
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import requests

ROOT=Path(__file__).resolve().parents[1]
SIZES=(1,3,5,10,20,50)
STARTS=(2000,2003,2006,2009,2012,2015)
SEED=20261009
FEE=.15
RATE=.001

def fetch_daily(symbol):
    start=int(pd.Timestamp('1998-01-01',tz='UTC').timestamp());end=int(pd.Timestamp('2025-04-01',tz='UTC').timestamp())
    r=requests.get('https://query1.finance.yahoo.com/v8/finance/chart/'+symbol,
                   params={'period1':start,'period2':end,'interval':'1d'},headers={'User-Agent':'Mozilla/5.0'},timeout=40)
    r.raise_for_status();d=r.json()['chart']['result'][0]
    adjusted=d['indicators']['adjclose'][0]['adjclose']
    df=pd.DataFrame({'close':adjusted},index=pd.to_datetime(d['timestamp'],unit='s',utc=True).normalize()).dropna().sort_index()
    df=df[(df.index<pd.Timestamp('2025-04-01',tz='UTC'))&(df.close>0)]
    df=df[~df.index.duplicated()]
    if len(df)<220:raise ValueError('Menos de220 sesiones')
    return df

def buy(cash,n):
    return max(0.,cash-FEE*n)/(1+RATE)

def statistics(values,contributed,benchmark):
    valid=np.asarray(values,float);valid=valid[np.isfinite(valid)]
    if not len(valid):return {'n':0,'mediana':None,'p10':None,'p90':None,'vence_benchmark_pct':None,'pierde_pct':None,'x5_pct':None}
    return dict(n=len(valid),mediana=float(np.median(valid)),p10=float(np.quantile(valid,.1)),p90=float(np.quantile(valid,.9)),
                vence_benchmark_pct=float(100*np.mean(valid>benchmark)),pierde_pct=float(100*np.mean(valid<contributed)),x5_pct=float(100*np.mean(valid>=5*contributed)))

def momentum_summary(rows):
    result=[]
    for years in (5,10):
        for n in (1,3,5):
            group=[r for r in rows if r['regla']=='momentum12_anual' and r['horizonte_anios']==years and r['n_acciones']==n]
            valid=[r for r in group if r['estadisticas']['n']]
            values=[r['estadisticas']['mediana']/r['aportes'] for r in valid]
            stats=statistics(values,1,1)
            stats['vence_benchmark_pct']=float(100*np.mean([r['estadisticas']['mediana']>r['valor_benchmark'] for r in valid])) if valid else None
            result.append(dict(horizonte_anios=years,n_acciones=n,ventanas=len(group),excluidas=len(group)-len(valid),unidad='Valor final / total aportado',estadisticas=stats))
    return result

def random_portfolios(prices,n,count,rng,monthly=100):
    eligible=np.flatnonzero(np.isfinite(prices[0])&(prices[0]>0))
    if len(eligible)<n:return np.full(count,np.nan),[],0
    # Sin reemplazo dentro de cada cartera; carteras pueden coincidir entre sí.
    ids=np.array([rng.choice(eligible,n,replace=False) for _ in range(count)])
    selected=prices[:,ids];units=np.zeros((count,n));series=[]
    for row in selected[:-1]:
        units+=buy(monthly,n)/n/row
        value=(units*row).sum(axis=1);series.append(value)
    final=(units*selected[-1]).sum(axis=1)*(1-RATE)-FEE*n
    fan=[]
    for i,values in enumerate(series):
        values=values[np.isfinite(values)]
        fan.append(dict(mes=i+1,aportes=monthly*(i+1),p10=float(np.quantile(values,.1)) if len(values) else None,
                        mediana=float(np.median(values)) if len(values) else None,p90=float(np.quantile(values,.9)) if len(values) else None))
    terminal=final[np.isfinite(final)]
    fan.append(dict(mes=len(prices)-1,aportes=monthly*(len(prices)-1),liquidacion=True,
                    p10=float(np.quantile(terminal,.1)) if len(terminal) else None,mediana=float(np.median(terminal)) if len(terminal) else None,
                    p90=float(np.quantile(terminal,.9)) if len(terminal) else None))
    return final,fan,len(eligible)

def momentum_portfolio(prices,start,months,n,monthly=100):
    """Selección anual con 12 meses terminados ANTES del precio de ejecución.
    Ausencias futuras invalidan el recorrido, nunca cambian la selección anterior.
    """
    units=np.zeros(prices.shape[1]);selected=None;history=[]
    for i in range(start,start+months):
        row=prices[i]
        if np.any((units>0)&~np.isfinite(row)):return np.nan,history
        if selected is None or (i-start)%12==0:
            if i<13:return np.nan,history
            score=prices[i-1]/prices[i-13]-1
            known=np.isfinite(score)&np.isfinite(row)&(row>0)
            candidates=np.flatnonzero(known)
            if len(candidates)<n:return np.nan,history
            chosen=candidates[np.argsort(-score[candidates],kind='stable')[:n]]
            cash=float(np.where(units>0,units*row,0).sum())*(1-RATE)-FEE*np.count_nonzero(units)
            cash=max(0.,cash);units[:]=0;selected=chosen
            units[selected]=buy(cash+monthly,n)/n/row[selected]
            history.append({'mes':i-start+1,'indices':chosen.tolist(),'momento_conocido':i-1})
        else:
            if not np.isfinite(row[selected]).all():return np.nan,history
            units[selected]+=buy(monthly,n)/n/row[selected]
    row=prices[start+months]
    if np.any((units>0)&~np.isfinite(row)):return np.nan,history
    value=float(np.where(units>0,units*row,0).sum())*(1-RATE)-FEE*np.count_nonzero(units)
    return value,history

def run(symbols,count=2000,fetcher=fetch_daily):
    prices={};coverage={};errors={}
    def get(symbol):
        try:return symbol,fetcher(symbol),None
        except Exception as e:return symbol,None,type(e).__name__
    with ThreadPoolExecutor(max_workers=4) as pool:
        for symbol,df,error in pool.map(get,list(dict.fromkeys(symbols+['SPY','VOO']))):
            if error:errors[symbol]=error;continue
            prices[symbol]=df.close
            coverage[symbol]={'primera':str(df.index[0].date()),'ultima':str(df.index[-1].date()),'sesiones':len(df)}
            print(symbol,len(df),flush=True)
    if 'SPY' not in prices:raise ValueError('Falta referencia SPY')
    bench=prices['SPY'];dates=bench.groupby(bench.index.tz_localize(None).to_period('M')).head(1).index
    universe=[s for s in symbols if s in prices]
    matrix=np.column_stack([prices[s].reindex(dates).to_numpy(float) for s in universe])
    rng=np.random.default_rng(SEED);rows=[];attempted=0
    for year in STARTS:
        for years in (5,10):
            start=int(dates.searchsorted(pd.Timestamp(f'{year}-01-01',tz='UTC')));months=years*12
            if start+months>=len(dates):continue
            # Incluye liquidación en aniversario posterior, sin aporte extra.
            end=start+months;sample=matrix[start:end+1]
            name='VOO' if 'VOO' in prices and np.isfinite(prices['VOO'].reindex(dates[start:end+1])).all() else 'SPY (proxy anterior a VOO)'
            symbol='VOO' if name=='VOO' else 'SPY'
            bp=prices[symbol].reindex(dates[start:end+1]).to_numpy(float)
            benchmark=buy(100,1)*np.sum(1/bp[:-1])*bp[-1]*(1-RATE)-FEE
            for n in SIZES:
                values,fan,eligible=random_portfolios(sample,n,count,rng)
                attempted+=count
                rows.append(dict(inicio=str(dates[start].date()),fin=str(dates[end].date()),horizonte_anios=years,n_acciones=n,
                                 regla='azar',intentadas=count,excluidas=count-int(np.isfinite(values).sum()),elegibles_inicio=eligible,
                                 aportes=months*100,benchmark=name,valor_benchmark=float(benchmark),estadisticas=statistics(values,months*100,benchmark),abanico=fan))
            for n in (1,3,5):
                value,selection=momentum_portfolio(matrix,start,months,n);attempted+=1
                rows.append(dict(inicio=str(dates[start].date()),fin=str(dates[end].date()),horizonte_anios=years,n_acciones=n,regla='momentum12_anual',
                                 intentadas=1,excluidas=int(not np.isfinite(value)),aportes=months*100,benchmark=name,valor_benchmark=float(benchmark),
                                 estadisticas=statistics([value],months*100,benchmark),selecciones=[dict(x,simbolos=[universe[j] for j in x['indices']]) for x in selection]))
    return dict(version=1,fecha=datetime.now(timezone.utc).isoformat(),corte_exclusivo='2025-04-01',semilla=SEED,
                fuente='Yahoo Chart nuevo en memoria, ajustado bruto; sin corroboración completa independiente',coverage=coverage,errors=errors,
                costo_orden=FEE,costo_lado=RATE,aporte_mensual_ficticio=100,recorridos_intentados=attempted,comparaciones_descriptivas=len(rows),
                definicion_x5='Valor final liquidado >=5 veces TODOS los aportes; no quintuplicar una única inversión inicial.',
                momentum_resumen=momentum_summary(rows),limitaciones=['Lista actual S&P: supervivencia; las bajas históricas faltan.','Ausencias futuras invalidan trayectorias; exclusiones explícitas, sesgo adicional.',
                'VOO nace en2010: antes se usa SPY marcado como proxy.','60/120 aportes; liquidación en aniversario sin aporte extra.',
                'Dividendos brutos aproximados; sin retención,fondeo,cambio ni préstamo.','Ventanas superpuestas y carteras repetibles: no observaciones independientes ni p-valores.',
                'Momentum selecciona con precios conocidos pero el universo actual introduce supervivencia; no evaluación causal prospectiva.',
                'No es presupuesto ni cartera personal; costos incluidos en100 ficticios.'],items=rows)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--carteras',type=int,default=2000);p.add_argument('--output',type=Path,default=ROOT/'resultados/concentracion.json');a=p.parse_args()
    if a.carteras<1000:raise ValueError('Al menos1000 carteras por celda')
    symbols=json.loads((ROOT/'ideas/enciclopedia_universo.json').read_text())['symbols']
    symbols=[s for s in symbols if s not in ('BTC-USD','ETH-USD','SPY','VOO')]
    result=run(symbols,a.carteras);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,separators=(',',':')),encoding='utf8')
    print('Recorridos',result['recorridos_intentados'],'celdas',len(result['items']))
