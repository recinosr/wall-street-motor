"""Daily S&P 500 signal scan. Cross-sectional ranks are hypotheses, not advice."""
import datetime as dt
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
    companies=lista(); symbols=[x['sim'] for x in companies]; info={x['sim']:x for x in companies}; rows=[]; failures=[]
    for offset in range(0,len(symbols),20):
        batch=symbols[offset:offset+20]
        try:
            response=requests.get(SPARK,params={'symbols':','.join(batch),'range':'2y','interval':'1d'},
                headers={'User-Agent':'Mozilla/5.0'},timeout=40);response.raise_for_status()
            for item in response.json().get('spark',{}).get('result',[]):
                try:
                    record=item['response'][0];close=pd.Series(record['indicators']['quote'][0]['close']).dropna().to_numpy(float)
                    if len(close)<253:continue
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
    print('S&P500:',len(symbols),'historia:',len(rows),'top:',len(top),'fallas:',len(failures))
    return out


if __name__=='__main__':scan()
