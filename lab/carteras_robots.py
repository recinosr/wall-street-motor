"""Seis reglas fijadas, precios públicos nuevos, señales previas y fechas comunes.

No usa velas reservadas ni reconstruye fondos antes de su lanzamiento.
"""
import concurrent.futures as cf
import datetime as dt
import time
import numpy as np
import pandas as pd
from .carteras import COST,CAL,download,verify_quote,performance

RULES={
 'DBMF':{'assets':['DBMF'],'source':'https://www.imgp.com/dbmf-etf/','description':'ETF que replica exposiciones agregadas de gestores de futuros; no es nuestro bot.'},
 'KMLM':{'assets':['KMLM'],'source':'https://kfafunds.com/kmlm/','description':'ETF sistemático de futuros de materias primas, monedas y bonos.'},
 'CTA':{'assets':['CTA'],'source':'https://www.simplify.us/etfs/cta-simplify-managed-futures-strategy-etf','description':'ETF de futuros con reglas sistemáticas long/short; su política puede cambiar.'},
 'Dual Momentum':{'assets':['SPY','VXUS','BND','BIL'],'source':'https://www.optimalmomentum.com/faq/','description':'SPY 12 meses > BIL: elegir mayor retorno SPY/VXUS; si no, BND. Revisión mensual; implementación ETF neta, no réplica del índice GEM.'},
 'Faber 10 meses':{'assets':['SPY','TLT','GLD','VNQ','EFA','BIL'],'source':'https://mebfaber.com/timing-model/','description':'Cinco partes de 20%: cada activo sobre su media de 10 cierres mensuales; si no, esa parte en BIL. Índices netos; aproximación con ETFs.'},
 'Permanent Portfolio':{'assets':['SPY','TLT','GLD','BIL'],'source':'https://www.harrybrowne.org/PermanentPortfolio.htm','description':'25% acciones, bonos largos, oro y letras. Rebalanceo anual; variante ETF, no regla original de bandas.'},
}


def monthly_target(history,name):
    """Solo recibe datos hasta el cierre de señal; nunca el cierre de ejecución."""
    rows=history.groupby(history.index.to_period('M')).tail(1)
    columns=list(history.columns);w=pd.Series(0.,index=columns)
    if name=='Dual Momentum':
        if len(rows)<13:return None
        ret=rows.iloc[-1]/rows.iloc[-13]-1
        asset=('SPY' if ret.SPY>=ret.VXUS else 'VXUS') if ret.SPY>ret.BIL else 'BND'
        w[asset]=1.
    elif name=='Faber 10 meses':
        if len(rows)<10:return None
        mean=rows.tail(10).mean();last=rows.iloc[-1]
        for asset in ('SPY','TLT','GLD','VNQ','EFA'):w[asset if last[asset]>mean[asset] else 'BIL']+=.2
    return w.to_numpy()


def targets(frame,name):
    if name in ('Dual Momentum','Faber 10 meses'):
        signals={}
        for i in range(1,len(frame)):
            prev=frame.index[i-1]
            if prev.to_period('M')==frame.index[i].to_period('M'):continue
            expected=CAL.date_to_session(prev.to_period('M').end_time.normalize(),direction='previous').tz_localize(None)
            if prev!=expected:continue # No sustituir un cierre faltante por el último que había.
            weight=monthly_target(frame.iloc[:i],name)
            if weight is not None:signals[i]=weight
        if not signals:raise ValueError('Sin warmup completo y cierre mensual verificable')
        return signals
    w=np.full(len(frame.columns),1/len(frame.columns))
    if name=='60/40':w=np.array([.6,.4])
    return {i:w for i in range(len(frame)) if i==0 or len(w)>1 and frame.index[i].year!=frame.index[i-1].year}


def run(frame,orders,monthly=0,cost=COST):
    """Rebalanceo al cierre posterior a señal, cobrado por cambios; aportes dentro del presupuesto."""
    start=min(orders);frame=frame.iloc[start:];orders={i-start:w for i,w in orders.items() if i>=start}
    growth=frame.pct_change().fillna(0).to_numpy()+1;positions=np.zeros(len(frame.columns));cash=1. if monthly==0 else 0.;values=[];total=0.;factor=1.;units=[];prior=0.;fees=0.;last_weights=None
    months=frame.index.to_period('M');deposits=np.r_[True,months[1:]!=months[:-1]]
    for i,mult in enumerate(growth):
        positions*=mult;deposit=monthly if deposits[i] else 0.;cash+=deposit;total+=deposit
        if i in orders:last_weights=np.asarray(orders[i],float)
        if deposit and i not in orders and last_weights is not None:
            fee=cash-cash/(1+cost);fees+=fee;positions+=cash/(1+cost)*last_weights;cash=0.
        if i in orders:
            weights=last_weights
            if weights is None or not np.isclose(weights.sum(),1) or (weights<0).any():raise ValueError('Pesos inválidos')
            nav=float(positions.sum()+cash);net=nav
            for _ in range(30):net=nav-cost*np.abs(weights*net-positions).sum()
            fee=cost*np.abs(weights*net-positions).sum();fees+=fee;positions=weights*net;cash=0.
        value=float(positions.sum()+cash)
        if monthly:
            if prior>0:factor*=(value-deposit)/prior
            elif total:factor=value/total
        else:factor=value
        values.append(value);units.append(factor);prior=value
    return {'serie':pd.Series(values,index=frame.index),'unit':pd.Series(units,index=frame.index),'fees':fees,'aportado':total}


def metric(series):return {**performance(series.to_numpy(),series.index),'ret_total_pct':float((series.iloc[-1]-1)*100)}


def crisis(strategy,market,year):
    common=strategy.index.intersection(market.index);common=common[common.year==year]
    if len(common)<40:return {'anio':year,'n':len(common),'estado':'Sin historia suficiente; no extrapolar','correlacion':None}
    # Retornos calculados antes del corte del año para incluir el primer día disponible.
    a=strategy.pct_change().loc[common];b=market.pct_change().loc[common];both=pd.concat([a,b],axis=1).dropna();down=both.iloc[:,1]<0
    return {'anio':year,'n':len(both),'desde':common[0].date().isoformat(),'hasta':common[-1].date().isoformat(),
            'cobertura':'Año parcial' if common[0].month!=1 or common[-1].month!=12 else 'Año completo por fechas; huecos posibles',
            'correlacion':float(both.iloc[:,0].corr(both.iloc[:,1])) if both.iloc[:,0].std()>0 and both.iloc[:,1].std()>0 else None,
            'correlacion_dias_acciones_caen':float(both.loc[down].iloc[:,0].corr(both.loc[down].iloc[:,1])) if down.sum()>=20 and both.loc[down].iloc[:,0].std()>0 and both.loc[down].iloc[:,1].std()>0 else None,
            'dias_acciones_caen':int(down.sum()),'media_robot_dias_caen_pct':float(both.loc[down].iloc[:,0].mean()*100),
            'ret_robot_pct':float((1+both.iloc[:,0]).prod()-1)*100,'ret_acciones_pct':float((1+both.iloc[:,1]).prod()-1)*100}


def decade_windows(strategy,world,balanced):
    starts=strategy.groupby(strategy.index.to_period('M')).head(1).index;out=[]
    for start in starts:
        end=start+pd.DateOffset(years=10)
        if end>strategy.index[-1]:continue
        cut=strategy.loc[start:end];last=cut.index[-1]
        result={'desde':start.date().isoformat(),'hasta':last.date().isoformat(),'ret_anual_pct':float((cut.iloc[-1]/cut.iloc[0])**(365.25/(last-start).days)-1)*100}
        for key,b in [('VT',world),('60/40',balanced)]:
            result['ret_'+key+'_pct']=float((b.loc[last]/b.loc[start]-1)*100) if start in b.index and last in b.index else None
        result['ret_robot_pct']=float((cut.iloc[-1]/cut.iloc[0]-1)*100);out.append(result)
    return out


def compare_rule(name,definition,prices,proofs):
    assets=definition['assets'];f=pd.concat({s:prices[s] for s in assets},axis=1,join='inner').dropna()
    orders=targets(f,name);result=run(f,orders);s=result['unit']
    common=s.index.intersection(prices['VT'].index).intersection(prices['BND'].index)
    if len(common)<40:raise ValueError('Sin fechas comunes suficientes con VT y BND')
    # Reejecutar con warmup anterior intacto y calendario común, sin rellenar precios.
    start=common[0];ff=f.loc[common];mapped={j:orders[f.index.get_loc(date)] for j,date in enumerate(common) if f.index.get_loc(date) in orders}
    active=max(k for k in orders if f.index[k]<=start);mapped[0]=orders[active]
    a=run(ff,mapped);world_frame=prices['VT'].loc[common].to_frame('VT');balanced_frame=pd.concat([prices['VT'].loc[common],prices['BND'].loc[common]],axis=1);balanced_frame.columns=['VT','BND']
    world=run(world_frame,targets(world_frame,'VT'));balanced=run(balanced_frame,targets(balanced_frame,'60/40'))
    win=decade_windows(a['unit'],world['unit'],balanced['unit'])
    # Crisis utiliza toda la cobertura propia y SPY: no restringir 2008 al lanzamiento posterior de VT.
    crises=[crisis(s,prices['SPY'],y) for y in (2008,2020,2022)]
    return {'nombre':name,'descripcion':definition['description'],'fuente_regla':definition['source'],
            'desde':s.index[0].date().isoformat(),'hasta':s.index[-1].date().isoformat(),'historia_propia':metric(s),
            'comparable_desde':common[0].date().isoformat(),'comparable_hasta':common[-1].date().isoformat(),'sesiones_comunes':len(common),
            'comparadores':{'robot':metric(a['unit']),'VT':metric(world['unit']),'60/40':metric(balanced['unit'])},
            'ventanas_10a':win,'n_ventanas_10a':len(win),'peor_10a_anual_pct':min((x['ret_anual_pct'] for x in win),default=None),
            'crisis':crises,'aportes':[{'mensual':m,'aportado':(v:=run(ff,mapped,m))['aportado'],'valor_final':round(v['serie'].iloc[-1],2),'costos':round(v['fees'],2)} for m in (50,100)],
            'verificacion':{s:proofs[s] for s in sorted(set(assets+['VT','BND','SPY']))},
            'cobertura':{'sesiones_propias':len(f),'sesiones_comparables':len(common),'sin_relleno':True,'regla_ultimo_cierre_mensual':True}}


def build():
    begin=time.time();symbols=sorted({s for x in RULES.values() for s in x['assets']}|{'VT','BND','SPY'});prices={};proofs={};failures=[]
    def one(s):
        try:
            price,hist=download(s);return s,price,verify_quote(s,hist),None
        except Exception as e:return s,None,None,str(e)[:180]
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        for s,price,proof,error in pool.map(one,symbols):
            if error:failures.append({'activo':s,'error':error})
            else:prices[s]=price;proofs[s]=proof
    results=[]
    for name,definition in RULES.items():
        try:results.append(compare_rule(name,definition,prices,proofs))
        except Exception as e:failures.append({'regla':name,'error':str(e)[:180]})
    if not results:raise RuntimeError('Ninguna regla con datos: '+str(failures))
    return {'version':1,'actualizado':dt.datetime.now(dt.timezone.utc).isoformat(),'robots':results,'fallas':failures,'segundos':round(time.time()-begin,2),
            'reglas_declaradas':6,'comparaciones_declaradas':12,'comparaciones_crisis_declaradas':18,'variantes_aporte':12,
            'sg_cta':{'estado':'Sin serie diaria gratuita verificable descargada; no se sustituye con ETF ni se inventa historia.',
                      'fuente':'https://content.sgmarkets.com/CTA_UPDATE_KEEPING_UP_WITH_THE_TRENDFOLLOWERS_2025'},
            'aviso':'Historia pública descargada de nuevo, retrospectiva elegida en 2026, sin ventaja causal demostrada. 6 reglas fijas, 12 comparaciones vs VT y 60/40 y 18 crisis, sin selección por resultado ni pruebas de significancia. Ventanas10años mensuales solapadas no son ensayos independientes. Señal en cierre mensual conocido, ejecución al siguiente cierre disponible, costos0.1% por cambios y primera entrada. 60/40=VT/BND, rebalanceo anual. ETF neto de gastos ya reflejados en precios; distribución EEUU con retención uniforme30% aproximada al exdividendo: algunos futuros tienen tratamiento distinto no verificado. US$50/100 incluyen costos de órdenes, fuera fondeo/cambio/retiro/impuestos locales. Correlación de crisis frente a SPY y solo cobertura propia; no medir fondos antes de lanzamiento. Corroboración solo del cierre final, no valida historia completa ni distribuciones. SG CTA sin serie descargada. Datos crudos quedan en memoria, no se publican.'}
