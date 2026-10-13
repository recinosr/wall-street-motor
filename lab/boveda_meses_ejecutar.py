"""Recolector y publicación separada del núcleo22. Nunca publica OHLC."""
import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import numpy as np
import pandas as pd
import requests
from .boveda_ejecutar import descargar, sha
from .boveda_meses import (ASSETS, METHODS, MODES, EFFECTS, CONFIG, BovedaMes,
                           MotorMes, jugar, calificar, calendario, seed)
from .boveda_meses_lote import activo_job

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'resultados'
PROTOCOL = OUT/'boveda_meses_diseno.json'
FILES = ('lab/boveda_meses.py','lab/boveda_meses_ejecutar.py','lab/boveda_meses_lote.py','tests/test_boveda_meses.py')


def write(path, data, once=False):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x' if once else 'w',encoding='utf8') as f:
        json.dump(data,f,ensure_ascii=False,allow_nan=False,separators=(',',':'))


def fingerprint():
    return sha(dict(config=CONFIG, archivos={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in FILES}))


def congelar():
    commit = subprocess.check_output(['git','-c','safe.directory='+str(ROOT),'rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    for file in FILES:
        original = subprocess.check_output(['git','-c','safe.directory='+str(ROOT),'show',commit+':'+file],cwd=ROOT)
        if original.decode('utf8').replace('\r\n','\n') != (ROOT/file).read_text(encoding='utf8'):
            raise ValueError('Código y pruebas deben estar comprometidos antes de medir')
    write(PROTOCOL,dict(config=CONFIG,firma=fingerprint(),commit=commit,
        fecha=dt.datetime.now(dt.timezone.utc).isoformat(),aperturas_previas=976,
        intento_anterior='v1 detenido sin métricas tras3 activos: faltaban6 fuentes y corrección de calendario; misma semilla,36variantes previas contadas',
        aviso='Reserva21 consumida. Todo22 exploratorio; no reescribe reserva inicial.'),once=True)


def fomc():
    file = ROOT/'datos/fomc_calendario22.json'
    if file.exists():
        return json.loads(file.read_text(encoding='utf8'))
    dates=set();sources=[]
    for year in range(2003,2027):
        url = ('https://www.federalreserve.gov/monetarypolicy/fomchistorical'+str(year)+'.htm'
               if year<=2020 else 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm')
        response=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=40)
        response.raise_for_status();html=response.text
        if year<=2020:
            # Fechas solo de reuniones programadas, no llamadas de emergencia.
            headings=re.findall(r'<h[45][^>]*>(.*?)</h[45]>',html,re.S|re.I)
            for h in headings:
                text=re.sub('<[^>]*>','',h)
                if 'Meeting' not in text or any(w in text.lower() for w in ('unscheduled','conference')):continue
                cross=re.search(r'([A-Z][a-z]{2})/([A-Z][a-z]{2})\s+\d+\s*[-–]\s*(\d+)',text)
                if cross:
                    dates.add(str(pd.to_datetime(f'{cross[2]} {cross[3]} {year}').date()))
                    continue
                found=re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d+)(?:\s*[-–]\s*(\d+))?',text)
                if found:
                    value=pd.to_datetime(f'{found[1]} {found[3] or found[2]} {year}')
                    dates.add(str(value.date()))
        else:
            # Statement monetario (a), no notas de implementación(b) ni minutas.
            dates.update(f'{v[:4]}-{v[4:6]}-{v[6:]}' for v in
                re.findall(r'Statement:.*?pressreleases/monetary('+str(year)+r'\d{4})a\.htm',html,re.S))
        sources.append(dict(año=year,url=url,sha256=hashlib.sha256(html.encode()).hexdigest()))
    # Emergency2020 no se incluyó por encabezados "Conference Call".
    if any(sum(d.startswith(str(y)) for d in dates)!=8 for y in range(2006,2026)):
        raise ValueError('Calendario FOMC incompleto: revisar fuente antes de medir')
    data=dict(fechas=sorted(dates),fuentes=sources,
        advertencia='Lista oficial actual, no archivo de calendarios publicados en T. Programadas solamente; sin garantizar vintage.')
    write(file,data);return data


def blocks(values, test='positive', replicas=9999):
    v=np.asarray(values,float);v=v[np.isfinite(v)];n=len(v)
    if n<18:return dict(p=1.,ic95=None,n=n,bloque=6)
    rng=np.random.default_rng(20261012);length=6
    starts=rng.integers(0,n,(replicas,int(np.ceil(n/length))))
    indices=(starts[:,:,None]+np.arange(length))%n
    draws=v[indices.reshape(replicas,-1)[:,:n]].mean(axis=1)
    mean=float(v.mean());z=draws-mean
    p=(1+np.count_nonzero(z>=mean))/(replicas+1) if test=='positive' else (1+np.count_nonzero(abs(z)>=abs(mean)))/(replicas+1)
    return dict(p=float(p),ic95=np.quantile(draws,[.025,.975]).tolist(),n=n,bloque=6,replicas=replicas)


def bh(rows, family):
    q=1.
    ordered=sorted(rows,key=lambda r:r['p'])
    for rank in range(len(ordered),0,-1):
        r=ordered[rank-1];q=min(q,r['p']*family/rank);r['q_bh']=min(1.,q)
        r['p_bonferroni']=min(1.,r['p']*family)


def climate(d,month,dates):
    sel=d.loc[d.index.to_period('M')==month];r=d.close.pct_change(fill_method=None)
    prev=d.loc[d.index<month.start_time]
    if not len(sel) or not len(prev):return None
    local=r.reindex(sel.index).dropna();historic=r.loc[r.index<month.start_time].rolling(20).std().dropna()
    monthly=prev.close.resample('ME').last().dropna()
    vol=float(local.std()) if len(local)>1 else 0.
    events=[f'FOMC {v}' for v in dates if v.startswith(str(month))]
    # Etiquetas descriptivas retrospectivas; nunca son rasgos de pronóstico.
    if str(month) in ('2008-09','2008-10'):events.append('crisis financiera (etiqueta retrospectiva)')
    if str(month)=='2020-03':events.append('pandemia (etiqueta retrospectiva)')
    return dict(retorno=float(sel.close.iloc[-1]/prev.close.iloc[-1]-1),
        subieron=float((local>0).mean()),volatilidad=vol,
        vol_relativa=vol/float(historic.median()) if len(historic) and historic.median()>0 else None,
        tendencia=int(monthly.iloc[-1]>=monthly.tail(10).mean()) if len(monthly)>=10 else None,eventos=events)


def explain(row):
    scores=row['metodos'];winner=min(METHODS,key=lambda m:(scores[m]['brier'],METHODS.index(m)))
    base=scores['moneda'];own=scores[winner];margin=base['brier']-own['brier'];c=row['clima']
    first=f"Ganó {winner} por menor Brier ({own['brier']:.4f}, moneda {base['brier']:.4f}); acierto {own['acierto']:.1%}."
    second=(f"SPY tuvo {c['subieron']:.1%} de días de subida y retorno {c['retorno']:.1%}; "
        f"volatilidad {c['vol_relativa']:.2f} veces su mediana previa. " if c and c['vol_relativa'] is not None else 'Clima SPY no disponible. ')
    third=f"Calendario: Brier {scores['calendario']['brier']:.4f}. Es asociación descriptiva: un mes ganado no demuestra habilidad ni explica causalidad."
    return winner,margin,first+' '+second+third


def inference(months, effects):
    rows=[];persist=[];histograms=[];attrib=[]
    for mode in MODES:
        for period,lo,hi in (('diseño','2006','2018-12'),('comparacion','2019','2023-12'),('exploratorio','2024','2026-09')):
            subset=[r for r in months if r['modo']==mode and lo<=r['mes']<=hi]
            if not subset:continue
            winners=[r['ganador'] for r in subset]
            contiguous=[i for i in range(1,len(subset)) if pd.Period(subset[i]['mes'],'M')-1==pd.Period(subset[i-1]['mes'],'M')]
            same=np.array([winners[i]==winners[i-1] for i in contiguous],float)
            # Además de1/n, control por frecuencias marginales: métodos no equiprobables.
            freq=np.array([winners.count(m)/len(winners) for m in METHODS]);null=float(np.sum(freq**2))
            item=dict(tipo='persistencia',modo=mode,periodo=period,observada=float(same.mean()) if len(same) else None,
                azar_uniforme=1/len(METHODS),azar_frecuencias=null,**blocks(same-null))
            rows.append(item);persist.append(item)
            uniform=dict(tipo='persistencia_uniforme',modo=mode,periodo=period,**blocks(same-1/len(METHODS)))
            rows.append(uniform)
            for m in METHODS:
                advantages=[r['metodos']['moneda']['brier']-r['metodos'][m]['brier'] for r in subset]
                own=dict(tipo='ventaja_brier',modo=mode,periodo=period,metodo=m,delta=float(np.mean(advantages)),**blocks(advantages))
                rows.append(own)
                accuracy=[r['metodos'][m]['acierto'] for r in subset]
                counts,edges=np.histogram(accuracy,bins=np.linspace(0,1,21))
                histograms.append(dict(modo=mode,periodo=period,metodo=m,n=len(accuracy),min=min(accuracy),max=max(accuracy),
                    bordes=edges.tolist(),frecuencias=counts.tolist()))
                for feature in ('retorno','subieron','vol_relativa','tendencia'):
                    pairs=[(r['clima'][feature],a) for r,a in zip(subset,advantages) if r['clima'] and r['clima'][feature] is not None]
                    x,y=np.array(pairs,float).T if pairs else (np.array([]),np.array([]))
                    if len(x)<18 or x.std()==0:continue
                    x=(x-x.mean())/x.std();beta=float(np.mean(x*(y-y.mean())))
                    # IC bootstrap apareado por bloques de meses para regresión simple.
                    rng=np.random.default_rng(20261012);n=len(x)
                    ix=(rng.integers(0,n,(1999,int(np.ceil(n/6)),1))+np.arange(6))%n;ix=ix.reshape(1999,-1)[:,:n]
                    xx=x[ix];yy=y[ix];xc_=xx-xx.mean(axis=1)[:,None];yc_=yy-yy.mean(axis=1)[:,None]
                    draws=(xc_*yc_).sum(axis=1)/np.maximum((xc_**2).sum(axis=1),1e-12)
                    p=float((1+np.count_nonzero(abs(draws-beta)>=abs(beta)))/2000) if abs(beta)>1e-14 else 1.
                    item=dict(tipo='atribucion',modo=mode,periodo=period,metodo=m,rasgo=feature,
                        beta_por_desviacion=beta,ic95=np.quantile(draws,[.025,.975]).tolist(),p=p,n=n,bloque=6)
                    attrib.append(item);rows.append(item)
    pubs={'cambio_mes':(1987,1988,2008),'pre_fomc':(2015,), 'lunes':(1980,),
          'sell_may':(2002,),'halloween':(2002,)}
    calendar_rows=[]
    for effect in EFFECTS:
        for cutoff in pubs.get(effect,(None,)):
            for segment in ('antes','despues') if cutoff else ('todo',):
                select=[v for v in effects if v['efecto']==effect and
                    (cutoff is None or (int(v['mes'][:4])<cutoff)==(segment=='antes'))]
                item=dict(tipo='efecto_calendario',efecto=effect,publicacion=cutoff,segmento=segment,
                    media_retorno=float(np.mean([v['retorno'] for v in select])) if select else None,
                    acierto=float(np.mean([v['acierto'] for v in select])) if select else None,
                    acierto_resto=float(np.mean([v['acierto_resto'] for v in select])) if select else None,
                    delta_retorno=float(np.mean([v['delta'] for v in select])) if select else None,
                    **blocks([v['delta'] for v in select],test='two-sided'))
                calendar_rows.append(item);rows.append(item)
    # Toda la familia:9métodos*4modos*3periodos + persistencias + atribución + calendario;
    # más976 contrastes previos21 y búsqueda21B declarada, aunque no se usan para seleccionar.
    previous=976
    old=OUT/'boveda_rondas.json'
    if old.exists():previous=max(previous,json.loads(old.read_text(encoding='utf8')).get('familia_ajuste_busqueda',976))
    # 36 variantes del intento22 interrumpido también se cuentan conservadoramente.
    family=len(rows)+previous+36
    bh(rows,family)
    return dict(contrastes_nuevos=len(rows),familia_bh=family,contrastres_previos=previous,
        variantes_previas22=36,persistencia=persist,histogramas=histograms,atribucion=attrib,
        calendario=calendar_rows,ventajas=[r for r in rows if r['tipo']=='ventaja_brier'],
        efectos_superan_bh=[r for r in calendar_rows if r['q_bh']<.05 and r['n']>=18])


def ejecutar(limit=None):
    if not PROTOCOL.exists():raise ValueError('Congelar y comprometer diseño primero')
    protocol=json.loads(PROTOCOL.read_text(encoding='utf8'))
    if protocol['firma']!=fingerprint():raise ValueError('Cambió diseño congelado')
    if (OUT/'boveda_meses.json').exists() and limit is None:raise ValueError('Medición ya publicada; no repetir silenciosamente')
    begin=time.time();fc=fomc();dates=fc['fechas'];sources=[];failures=[];frames={}
    assets=ASSETS[:limit] if limit else ASSETS
    def fetch(sim):
        try:return sim,descargar(sim,'2026-09-30'),None
        except Exception as exc:return sim,None,str(exc)[:200]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for sim,result,error in pool.map(fetch,assets):
            if error:failures.append(dict(sim=sim,error=error))
            else:frames[sim]=result[0];sources.append(result[1])
    print('Fuentes',len(frames),'fallas',len(failures),flush=True)
    if failures or len(frames)!=len(assets):
        write(ROOT/'.boveda-cache/fallas22.json',failures)
        raise ValueError('Faltan fuentes: no se publica un universo incompleto. Ver caché/fallas22.json')
    byyear={y:[] for y in range(2006,2027)};groups={};coverage=[];effects=[]
    spy=frames.get('SPY');months=list(pd.period_range('2006-01','2026-09',freq='M'))
    climates={str(m):climate(spy,m,dates) for m in months} if spy is not None else {}
    with ProcessPoolExecutor(max_workers=4) as pool:
        for no,(sim,games,summaries,cov) in enumerate(pool.map(activo_job,[(s,d,dates) for s,d in frames.items()]),1):
            for game in games:byyear[int(game['mes'][:4])].append(game)
            for month,mode,stats in summaries:groups.setdefault((month,mode),[]).append(stats)
            coverage.append(cov)
            print(no,sim,'juegos',cov['meses_modos'],'segundos',round(time.time()-begin),flush=True)
    # Calendario contrastado sobre SPY únicamente: no102 copias correlacionadas.
    if spy is not None:
            frame=spy;r=frame.close.pct_change(fill_method=None);flags=calendario(frame.index,dates)
            for month in months:
                mask=(frame.index.to_period('M')==month)&r.notna()
                for effect in EFFECTS:
                    own=r[mask&(flags[effect]==1)];other=r[mask&(flags[effect]==0)]
                    if effect in ('sell_may','halloween'):
                        other=r[(frame.index.year==month.year)&(flags[effect]==0)].dropna()
                    if len(own) and len(other):effects.append(dict(mes=str(month),efecto=effect,
                        retorno=float(own.mean()),acierto=float((own>0).mean()),
                        acierto_resto=float((other>0).mean()),delta_acierto=float((own>0).mean()-(other>0).mean()),
                        delta=float(own.mean()-other.mean())))
    summary=[]
    for (month,mode),stats in sorted(groups.items()):
        methods={}
        for method in METHODS:
            total=sum(s[method]['n'] for s in stats)
            methods[method]=dict(n=total,acierto=sum(s[method]['acierto']*s[method]['n'] for s in stats)/total,
                brier=sum(s[method]['brier']*s[method]['n'] for s in stats)/total,
                cobertura=float(np.mean([s[method]['cobertura'] for s in stats if s[method]['cobertura'] is not None])))
        row=dict(mes=month,modo=mode,activos=len(stats),metodos=methods,clima=climates.get(month))
        row['ganador'],row['margen_brier'],row['por_que']=explain(row);summary.append(row)
    stats=inference(summary,effects);fragments=[]
    for year,games in byyear.items():
        if games:
            path=OUT/f'boveda_meses_{year}.json';write(path,dict(firma=protocol['firma'],metodos=METHODS,juegos=games))
            fragments.append(dict(año=year,archivo=path.name,bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    data=dict(version=1,firma=protocol['firma'],config=CONFIG,actualizado=dt.datetime.now(dt.timezone.utc).isoformat(),
        metodos=METHODS,modos=MODES,activos=list(frames),meses=summary,fragmentos=fragments,fuentes=sources,
        cobertura=coverage,fallas=failures,inferencia=stats,pronosticos=sum(r['metodos']['moneda']['n'] for r in summary)*len(METHODS),
        aviso='Diario retrospectivo educativo;2024–2026 ya conocido. Ninguna prueba final nueva ni habilidad futura demostrada.',
        duracion_segundos=round(time.time()-begin,2),piloto_vita='prospectivo separado; sin backtest LLM',
        fomc=fc,reglas_calendario='días de FOMC completos y día previo: no réplica intradía de Lucca/Moench')
    write(OUT/('boveda_meses_smoke.json' if limit else 'boveda_meses.json'),data)
    print('Terminado',len(summary),'meses/modos',data['pronosticos'],'pronósticos',flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('accion',choices=['congelar','ejecutar']);p.add_argument('--limite',type=int)
    a=p.parse_args();congelar() if a.accion=='congelar' else ejecutar(a.limite)

if __name__=='__main__':main()
