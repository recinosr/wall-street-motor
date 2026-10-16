"""Daily S&P 500 signal scan. Cross-sectional ranks are hypotheses, not advice."""
import datetime as dt
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from lab.sp500 import lista

ROOT=Path(__file__).resolve().parents[1]
SPARK='https://query1.finance.yahoo.com/v7/finance/spark'


def scan():
    companies=lista(); symbols=list(dict.fromkeys([x['sim'] for x in companies]+['SPY'])); info={x['sim']:x for x in companies};info.setdefault('SPY',{'nombre':'SPDR S&P 500 ETF Trust','sector':'Índice','industria':'Índice'}); rows=[]; failures=[]; history={}
    for offset in range(0,len(symbols),20):
        batch=symbols[offset:offset+20]
        try:
            response=requests.get(SPARK,params={'symbols':','.join(batch),'range':'2y','interval':'1d'},
                headers={'User-Agent':'Mozilla/5.0'},timeout=40);response.raise_for_status()
            for item in response.json().get('spark',{}).get('result',[]):
                try:
                    record=item['response'][0];quotes=record['indicators']['quote'][0];timestamps=record.get('timestamp',[])
                    close=pd.Series(quotes['close']).dropna().to_numpy(float)
                    if len(close)<253:continue
                    history[item['symbol']]={dt.datetime.fromtimestamp(ts,dt.timezone.utc).date().isoformat():float(v)
                        for ts,v in zip(timestamps,quotes['close']) if v is not None}
                    r21=close[-1]/close[-22]-1;r63=close[-1]/close[-64]-1;r12_1=close[-22]/close[-253]-1
                    sma200=close[-1]/np.mean(close[-200:])-1
                    rows.append({'sim':item['symbol'],'precio':float(close[-1]),'ret_1m_pct':100*r21,
                        'ret_3m_pct':100*r63,'momentum_12_1_pct':100*r12_1,'dist_sma200_pct':100*sma200,
                        **{k:info[item['symbol']].get(k) for k in ('nombre','sector','industria')}})
                except (KeyError,ValueError,IndexError,TypeError):continue
        except Exception as exc:failures.append({'lote':offset,'error':str(exc)[:120]})
        time.sleep(.25)
    frame=pd.DataFrame(rows)
    if not frame.empty:
        z={col:(frame[col]-frame[col].mean())/(frame[col].std(ddof=0) or 1) for col in ('ret_1m_pct','ret_3m_pct','momentum_12_1_pct')}
        frame['score_momentum']=.4*z['ret_1m_pct']+.3*z['ret_3m_pct']+.3*z['momentum_12_1_pct']
        frame['puesto']=frame['score_momentum'].rank(method='first',ascending=False).astype(int)
        frame['razon']=frame.apply(lambda x:f"Momentum transversal: 40% 1m ({x.ret_1m_pct:.1f}%), 30% 3m ({x.ret_3m_pct:.1f}%), 30% 12–1m ({x.momentum_12_1_pct:.1f}%); {'sobre' if x.dist_sma200_pct>=0 else 'bajo'} SMA200. Hipótesis sin ventaja demostrada.",axis=1)
        top=frame.sort_values(['score_momentum','sim'],ascending=[False,True]).head(20).replace({np.nan:None}).to_dict('records')
    else:top=[]
    out={'actualizado':dt.datetime.now(dt.timezone.utc).isoformat(),'fecha':dt.date.today().isoformat(),
        'activos_consultados':len(symbols),'cobertura':len(rows),'top20':top,'fallas':failures,
        'metodo':'Ranking z-score transversal: 40% retorno1m + 30% retorno3m + 30% momentum12-1; Yahoo Spark ajustado disponible.',
        'aviso':'Universo de componentes actuales, sesgo de supervivencia para cualquier análisis histórico. Ranking descriptivo; no es recomendación ni ventaja probada.'}
    target=ROOT/'resultados/escaner_sp500.json';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf8')
    archive_dir=ROOT/'datos/oraculo/escaner';archive_dir.mkdir(parents=True,exist_ok=True)
    archive_path=archive_dir/(out['fecha']+'.json')
    sealed={'fecha':out['fecha'],'ancla':max(history.get('SPY',{}),default=out['fecha']),'publicado':out['actualizado'],'top20':top,'metodo':out['metodo']}
    seal=hashlib.sha256(json.dumps(sealed,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    if not archive_path.exists():archive_path.write_text(json.dumps({**sealed,'sha256':seal,'calificaciones':{}},ensure_ascii=False,allow_nan=False),encoding='utf8')
    # Califica cada cohorte contra SPY usando las sesiones del benchmark y precios ajustados disponibles.
    spy_dates=sorted(history.get('SPY',{}))
    for saved in archive_dir.glob('*.json'):
        cohort=json.loads(saved.read_text(encoding='utf8'));base=cohort.get('ancla',cohort['fecha']);base_i=spy_dates.index(base) if base in spy_dates else -1
        if base_i<0:continue
        ratings=cohort.setdefault('calificaciones',{})
        for horizon in (5,21):
            if horizon in ratings or len(spy_dates)<=base_i+horizon:continue
            target_day=spy_dates[base_i+horizon];benchmark=history['SPY'].get(target_day)
            rows_out=[]
            for item in cohort['top20']:
                start=next((v for d,v in history.get(item['sim'],{}).items() if d==base),None)
                end=history.get(item['sim'],{}).get(target_day)
                if start and end and benchmark and history['SPY'].get(base):
                    asset_ret=end/start-1;sp_ret=benchmark/history['SPY'][base]-1
                    rows_out.append({'sim':item['sim'],'fecha_salida':target_day,'retorno_pct':100*asset_ret,
                        'sp500_pct':100*sp_ret,'exceso_pct':100*(asset_ret-sp_ret)})
            ratings[str(horizon)]={'n':len(rows_out),'resultados':rows_out,'fuente':'cierres ajustados Yahoo Spark; requiere cobertura exacta en ambas fechas'}
        saved.write_text(json.dumps(cohort,ensure_ascii=False,allow_nan=False),encoding='utf8')
    print('S&P500:',len(symbols),'historia:',len(rows),'top:',len(top),'fallas:',len(failures))
    return out


if __name__=='__main__':scan()
