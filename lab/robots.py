"""Tres estrategias públicas fijadas, adaptadas a1h/diario; medición retrospectiva."""
import argparse
import datetime as dt
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
import talib
from scipy import stats
from lab.universo import get
from lab.enciclopedia import bh

ROOT=Path(__file__).resolve().parents[1]
REV='f3340ce11f5bdf62f598522e64d1f5638eaa13f5'
STRATEGIES=['Strategy002','BinHV45','CombinedBinHAndCluc']
SOURCES={s:'https://github.com/freqtrade/freqtrade-strategies/blob/'+REV+'/user_data/strategies/'+('' if s=='Strategy002' else 'berlinguyinca/')+s+'.py' for s in STRATEGIES}
COST=.001


def candles(symbol,seconds):
    start=dt.datetime(2023,1,1,tzinfo=dt.timezone.utc);end=dt.datetime(2025,4,1,tzinfo=dt.timezone.utc);rows=[]
    while start<end:
        stop=min(end,start+dt.timedelta(seconds=seconds*290))
        for attempt in range(4):
            try:
                rows+=get('https://api.exchange.coinbase.com/products/'+symbol+'-USD/candles',params={
                    'start':start.isoformat(),'end':stop.isoformat(),'granularity':seconds}).json();break
            except Exception:
                if attempt==3:raise
                time.sleep(2**attempt)
        start=stop;time.sleep(.15)
    d=pd.DataFrame(rows,columns=['timestamp','low','high','open','close','volume']).drop_duplicates('timestamp').sort_values('timestamp')
    d.index=pd.to_datetime(d.pop('timestamp'),unit='s',utc=True)
    return d[(d.index>=pd.Timestamp('2023-01-01',tz='UTC'))&(d.index<pd.Timestamp('2025-04-01',tz='UTC'))]


def signals(d):
    c=d.close;o=d.open;low=d.low;high=d.high;typical=(c+low+high)/3
    middle=c.rolling(40).mean();lower=middle-2*c.rolling(40).std()
    delta=(middle-lower).abs();move=c.diff().abs();tail=(c-low).abs()
    oversold=lambda width,speed,shadow:((lower.shift()>0)&(delta>c*width)&(move>c*speed)&(tail<delta*shadow)&(c<lower.shift())&(c<=c.shift())).fillna(False)
    mean=typical.rolling(20).mean();band=mean-2*typical.rolling(20).std()
    a=lambda s:np.asarray(s,float)
    rsi=pd.Series(talib.RSI(a(c),timeperiod=14),index=d.index)
    slowk,_=talib.STOCH(a(high),a(low),a(c))
    hammer=talib.CDLHAMMER(a(o),a(high),a(low),a(c))
    sar=talib.SAR(a(high),a(low));fisher=np.tanh(.1*(rsi-50))
    ema=pd.Series(talib.EMA(a(c),timeperiod=50),index=d.index)
    return {
        'Strategy002':(((rsi<30)&(slowk<20)&(band>c)&(hammer==100)).fillna(False),((sar>c)&(fisher>.3)).fillna(False)),
        'BinHV45':(oversold(.007,.017,.025),pd.Series(False,index=d.index)),
        'CombinedBinHAndCluc':(oversold(.008,.0175,.25)|((c<ema)&(c<.985*band)&(d.volume<d.volume.rolling(30).mean().shift()*20)).fillna(False),(c>mean).fillna(False))}


def simulate(d,entry,exit_signal,strategy,seconds):
    cash=1000.;qty=0.;entryprice=0.;opened=None;curve=[];trades=[];gap_exits=0
    o,h,l,c=(d[k].to_numpy() for k in ('open','high','low','close'))
    buy=np.asarray(entry,bool);sell=np.asarray(exit_signal,bool)
    def roi(age):
        if strategy=='BinHV45':return .0125
        if strategy!='Strategy002':return .05
        return .01 if age>=60 else .03 if age>=30 else .04 if age>=20 else .05
    stop=-.1 if strategy=='Strategy002' else -.05
    for i in range(100,len(d)):
        gap=(d.index[i]-d.index[i-1]).total_seconds()!=seconds
        if qty:
            # Gaps: no inventar trayectorias; salir al siguiente precio observado.
            age=(d.index[i]-d.index[opened]).total_seconds()/60
            floor=entryprice*(1+stop)*(1+COST)/(1-COST)
            ceiling=entryprice*(1+roi(age))*(1+COST)/(1-COST)
            price=None;reason=None
            if gap:price=o[i];reason='hueco';gap_exits+=1
            elif o[i]<=floor:price=o[i];reason='stop_gap'
            elif sell[i-1] and c[i-1]>entryprice*(1+COST)/(1-COST):price=o[i];reason='senal'
            elif l[i]<=floor:price=floor;reason='stop'  # peor orden si toca también ROI
            elif o[i]>=ceiling:price=o[i];reason='roi_gap'
            elif h[i]>=ceiling:price=ceiling;reason='roi'
            if price is not None:
                cash=qty*price*(1-COST);trades.append({'inicio':opened,'fin':i,'neto':price/entryprice*(1-COST)/(1+COST)-1,'salida':reason});qty=0.
        # Evitar reentrada en vela de salida y señales opuestas simultáneas.
        exited=bool(trades and trades[-1]['fin']==i)
        if not qty and not gap and not exited and buy[i-1] and not sell[i-1]:
            entryprice=o[i];opened=i;qty=cash/(1+COST)/entryprice;cash=0.
            # Stop/ROI pueden ejecutarse en la misma vela de entrada; resolución conservadora.
            floor=entryprice*(1+stop)*(1+COST)/(1-COST);ceil=entryprice*(1+roi(0))*(1+COST)/(1-COST)
            price=floor if l[i]<=floor else ceil if h[i]>=ceil else None
            if price is not None:
                cash=qty*price*(1-COST);trades.append({'inicio':i,'fin':i,'neto':price/entryprice*(1-COST)/(1+COST)-1,'salida':'misma_vela'});qty=0.
        curve.append(cash+qty*c[i])
    if qty:
        cash=qty*c[-1]*(1-COST);trades.append({'inicio':opened,'fin':len(d)-1,'neto':c[-1]/entryprice*(1-COST)/(1+COST)-1,'salida':'corte'});curve[-1]=cash
    return np.asarray(curve),trades,gap_exits


def random_control(d,trades,seed=12,trials=200):
    """Mismo número de operaciones y mismas duraciones, sin solapamiento."""
    rng=np.random.default_rng(seed);out=[];lengths=[max(1,t['fin']-t['inicio']) for t in trades]
    available=len(d)-101-sum(lengths)-len(lengths)
    if available<0:return []
    for _ in range(trials):
        rng.shuffle(lengths)
        spaces=rng.multinomial(available,np.ones(len(lengths)+1)/(len(lengths)+1))
        at=100+spaces[0];value=1000.
        for k,length in enumerate(lengths):
            end=at+length;value*=float(d.close.iloc[end]/d.open.iloc[at])*(1-COST)/(1+COST)
            at=end+1+spaces[k+1]
        out.append(value/1000-1)
    return out


def measure(symbol):
    rows=[];failures=[];started=time.time()
    for seconds,label in ((86400,'diario'),(3600,'1h')):
        try:
            d=candles(symbol,seconds);sig=signals(d)
            expected=int((pd.Timestamp('2025-04-01',tz='UTC')-pd.Timestamp('2023-01-01',tz='UTC')).total_seconds()/seconds)
            for strategy in STRATEGIES:
                curve,trades,gaps=simulate(d,*sig[strategy],strategy,seconds)
                baseline=1000*d.close.iloc[100:].to_numpy()/d.open.iloc[100]*(1-COST)/(1+COST)
                random=random_control(d,trades)
                ret=float(curve[-1]/1000-1);bhret=float(baseline[-1]/1000-1)
                daily=pd.DataFrame({'a':curve,'b':baseline},index=d.index[100:]).resample('1D').last().dropna().pct_change().dropna()
                difference=daily.a-daily.b
                # Retornos diarios emparejados, error Newey-West7lags para no contar horas independientes.
                z=difference.to_numpy();mean=float(z.mean()) if len(z) else 0.;center=z-mean;n=len(z)
                var=float(np.dot(center,center)/n) if n else 0.
                for lag in range(1,min(8,n)):
                    var+=2*(1-lag/8)*float(np.dot(center[lag:],center[:-lag])/n)
                se=np.sqrt(max(0,var)/n) if n else 0.;p=float(stats.norm.sf(mean/se)) if se>0 else 1.
                rows.append({'activo':symbol,'frecuencia':label,'estrategia':strategy,'fuente':SOURCES[strategy],
                    'desde':d.index[100].isoformat(),'hasta':d.index[-1].isoformat(),'velas':len(d),'esperadas':expected,
                    'cobertura_pct':len(d)/expected*100,'operaciones':len(trades),'salidas_por_hueco':gaps,
                    'neto_pct':ret*100,'mantener_pct':bhret*100,'azar_mediana_pct':float(np.median(random))*100 if random else None,
                    'p_azar':(1+sum(r>=ret for r in random))/(1+len(random)) if random else 1.,
                    'p_mantener':p,'diferencia_diaria_ic95_pct':[(mean-1.96*se)*100,(mean+1.96*se)*100],
                    'peor_caida_pct':float((curve/np.maximum.accumulate(curve)-1).min()*100),
                    'segmentos':[{'anio':int(y),'retorno_pct':float(g.a.iloc[-1]/g.a.iloc[0]-1)*100} for y,g in pd.DataFrame({'a':curve},index=d.index[100:]).groupby(d.index[100:].year)]})
        except Exception as e:failures.append({'activo':symbol,'frecuencia':label,'error':str(e)[:200]})
    return {'resultados':rows,'fallas':failures,'segundos':round(time.time()-started,2)}


def finalize(directory):
    parts=[json.loads(p.read_text(encoding='utf8')) for p in Path(directory).glob('*.json')]
    rows=[r for p in parts for r in p['resultados']];pvalues=[]
    for r in rows:pvalues.extend([r['p_azar'],r['p_mantener']])
    # Familia fijada24casos ×2controles; fallas cuentan como p=1, no reducen la penalización.
    adjusted=bh(dict(enumerate(pvalues+[1.]*(48-len(pvalues)))))
    for i,r in enumerate(rows):
        r['q_azar']=adjusted[2*i];r['q_mantener']=adjusted[2*i+1]
        r['supera_ambos']=r['q_azar']<.05 and r['q_mantener']<.05 and r['neto_pct']>r['mantener_pct']
    result={'version':1,'actualizado':dt.datetime.now(dt.timezone.utc).isoformat(),'revision_fuente':REV,
        'pruebas_declaradas':48,'casos':rows,'fallas':[e for p in parts for e in p['fallas']],
        'segundos_sumados':sum(p['segundos'] for p in parts),
        'aviso':'Adaptaciones a1h/diario de reglas originalmente1m/5m, no réplica del motor freqtrade. TA-Lib para indicadores, entradas apertura posterior, costos0.1%por lado, stop primero ante ambigüedad, ROI en minutos original. BinHV45 usa buy_params7/17/25 del código fijado, sin optimización. Un activo/posición100% por ensayo, no brokers. Coinbase nuevo2023–mar2025; archivo reservado intacto. Warmup100velas, huecos no rellenados. Azar200permutaciones conserva frecuencia y duración (mínimo1vela para salida en misma vela); BH48contrastes. Selección pública retrospectiva: no prueba causal fuera de muestra; robustez temporal por año descriptiva.'}
    (ROOT/'resultados/robots.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf8')
    print('Casos:',len(rows),'superan ambos:',sum(r['supera_ambos'] for r in rows))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--activo');p.add_argument('--partes',default='resultados/robots_partes');p.add_argument('--finalizar',action='store_true');a=p.parse_args()
    if a.finalizar:finalize(a.partes)
    else:
        result=measure(a.activo);directory=Path(a.partes);directory.mkdir(parents=True,exist_ok=True)
        (directory/(a.activo+'.json')).write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf8')
        print(a.activo,len(result['resultados']),result['fallas'],result['segundos'])
