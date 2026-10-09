"""Enciclopedia causal, reglas v1 congeladas antes de medir.

OHLC diarios sin rellenar huecos. Tendencia previa: close[t-1] frente a
close[t-6] (cinco sesiones ANTERIORES a la primera vela del patrón).
Pequeño <=30% del rango, doji <=10%, largo >=60%; sombras según fórmulas.
Figuras: pivote de radio 3 conocido solo tres sesiones después; tolerancia
de niveles 2%, ruptura 0.5%; ventanas 60/20, volumen >1.5 media previa20.
Estas son definiciones operativas propias, no interpretaciones visuales.
No se abre ningún archivo histórico reservado. Fuente descargada en ejecución.
"""
import argparse
import hashlib
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy.stats import t as student

ROOT = Path(__file__).resolve().parents[1]
COST = .001
EXITS = ['fijo_1', 'fijo_5', 'fijo_10', 'fijo_20', 'ratio_1', 'ratio_2', 'ratio_3']
BEGIN, END = '2000-01-01', '2025-04-01'  # pantalla independiente; reserva intacta
SPLIT = '2016-01-01'
BOOTSTRAPS = 1999


def catalog():
    """Nombre, dibujo en palabras, dirección del libro y ventana del extremo."""
    candles = [
        ('doji', 'Cuerpo casi invisible con dos mechas.', 0, 1),
        ('doji_libelula', 'Cuerpo arriba y mecha larga abajo.', 1, 1),
        ('doji_lapida', 'Cuerpo abajo y mecha larga arriba.', -1, 1),
        ('doji_piernas_largas', 'Dos mechas largas y cuerpo diminuto al centro.', 0, 1),
        ('martillo', 'Cuerpo arriba, sombra inferior de al menos dos cuerpos tras caída.', 1, 1),
        ('martillo_invertido', 'Sombra superior larga tras caída.', 1, 1),
        ('hombre_colgado', 'Forma de martillo después de una subida.', -1, 1),
        ('estrella_fugaz', 'Cuerpo abajo y sombra superior larga tras subida.', -1, 1),
        ('marubozu_alcista', 'Vela verde casi sin sombras.', 1, 1),
        ('marubozu_bajista', 'Vela roja casi sin sombras.', -1, 1),
        ('peonza', 'Cuerpo pequeño entre dos sombras.', 0, 1),
        ('envolvente_alcista', 'Cuerpo verde cubre el cuerpo rojo anterior.', 1, 2),
        ('envolvente_bajista', 'Cuerpo rojo cubre el cuerpo verde anterior.', -1, 2),
        ('harami_alcista', 'Cuerpo verde pequeño dentro de uno rojo.', 1, 2),
        ('harami_bajista', 'Cuerpo rojo pequeño dentro de uno verde.', -1, 2),
        ('harami_cruz', 'Un doji queda dentro del cuerpo anterior.', 0, 2),
        ('linea_penetrante', 'Verde abre debajo del mínimo rojo y supera su mitad.', 1, 2),
        ('nube_oscura', 'Roja abre sobre máximo verde y cae bajo su mitad.', -1, 2),
        ('pinzas_inferior', 'Dos mínimos casi iguales tras caída.', 1, 2),
        ('pinzas_superior', 'Dos máximos casi iguales tras subida.', -1, 2),
        ('estrella_manana', 'Roja grande, cuerpo pequeño separado y verde de recuperación.', 1, 3),
        ('estrella_atardecer', 'Verde grande, cuerpo pequeño separado y roja de reversión.', -1, 3),
        ('estrella_manana_doji', 'Estrella de la mañana con doji central.', 1, 3),
        ('estrella_atardecer_doji', 'Estrella del atardecer con doji central.', -1, 3),
        ('bebe_abandonado_alcista', 'Doji aislado por dos brechas de rango tras caída.', 1, 3),
        ('bebe_abandonado_bajista', 'Doji aislado por dos brechas de rango tras subida.', -1, 3),
        ('tres_soldados_blancos', 'Tres verdes con cierres crecientes; regla B registrada.', 1, 3),
        ('tres_cuervos_negros', 'Tres rojas con cierres decrecientes.', -1, 3),
        ('tres_metodos_ascendentes', 'Verde larga, tres rojas contenidas, verde que supera el inicio.', 1, 5),
        ('tres_metodos_descendentes', 'Roja larga, tres verdes contenidas, roja que rompe abajo.', -1, 5),
        ('tres_dentro_arriba', 'Harami alcista seguido por cierre sobre el primer cuerpo.', 1, 3),
        ('tres_dentro_abajo', 'Harami bajista seguido por cierre bajo el primer cuerpo.', -1, 3),
        ('tres_fuera_arriba', 'Envolvente alcista seguida de otro cierre creciente.', 1, 3),
        ('tres_fuera_abajo', 'Envolvente bajista seguida de otro cierre decreciente.', -1, 3),
        ('kicker_alcista', 'Roja seguida por verde que abre sobre su apertura.', 1, 2),
        ('kicker_bajista', 'Verde seguida por roja que abre bajo su apertura.', -1, 2),
        ('tasuki_alcista', 'Dos verdes con brecha; roja entra parcialmente en la brecha.', 1, 3),
        ('tasuki_bajista', 'Dos rojas con brecha; verde entra parcialmente en la brecha.', -1, 3),
        ('separacion_alcista', 'Roja y verde abren al mismo nivel durante subida.', 1, 2),
        ('separacion_bajista', 'Verde y roja abren al mismo nivel durante caída.', -1, 2),
    ]
    graphs = [
        ('soporte', 'Precio toca y rebota sobre un mínimo confirmado previo.', 1),
        ('resistencia', 'Precio toca y retrocede bajo un máximo confirmado previo.', -1),
        ('ruptura_resistencia', 'Cierre supera un techo anterior por 0.5%.', 1),
        ('ruptura_soporte', 'Cierre pierde un piso anterior por 0.5%.', -1),
        ('ruptura_resistencia_volumen', 'Ruptura alcista con volumen >1.5 veces media previa20.', 1),
        ('ruptura_soporte_volumen', 'Ruptura bajista con volumen >1.5 veces media previa20.', -1),
        ('doble_techo', 'Dos cumbres parecidas; cierre rompe valle intermedio.', -1),
        ('doble_piso', 'Dos valles parecidos; cierre rompe cumbre intermedia.', 1),
        ('triple_techo', 'Tres cumbres parecidas y ruptura del piso intermedio.', -1),
        ('triple_piso', 'Tres valles parecidos y ruptura del techo intermedio.', 1),
        ('hombro_cabeza_hombro', 'Tres cumbres: central más alta, hombros parecidos, rompe cuello.', -1),
        ('hch_inverso', 'Tres valles: central más bajo, hombros parecidos, rompe cuello.', 1),
        ('triangulo_ascendente', 'Techo horizontal y mínimos ascendentes; rompe arriba.', 1),
        ('triangulo_descendente', 'Piso horizontal y máximos descendentes; rompe abajo.', -1),
        ('triangulo_simetrico_alcista', 'Techos bajan, pisos suben; rompe arriba.', 1),
        ('triangulo_simetrico_bajista', 'Techos bajan, pisos suben; rompe abajo.', -1),
        ('bandera_alcista', 'Impulso de 10% y canal corto descendente; rompe arriba.', 1),
        ('bandera_bajista', 'Caída de 10% y canal corto ascendente; rompe abajo.', -1),
        ('banderin_alcista', 'Impulso de 10% y consolidación convergente; rompe arriba.', 1),
        ('banderin_bajista', 'Caída de 10% y consolidación convergente; rompe abajo.', -1),
        ('canal_alcista', 'Techo y piso paralelos ascendentes; toca piso y rebota.', 1),
        ('canal_bajista', 'Techo y piso paralelos descendentes; toca techo y retrocede.', -1),
        ('cuna_ascendente', 'Dos bordes ascendentes convergen; rompe abajo.', -1),
        ('cuna_descendente', 'Dos bordes descendentes convergen; rompe arriba.', 1),
        ('taza_con_asa', 'Bordes similares, valle central profundo, asa corta; rompe borde.', 1),
        ('cruce_dorado', 'Media50 cruza por encima de media200.', 1),
        ('cruce_muerte', 'Media50 cruza por debajo de media200.', -1),
        ('rsi_sobrevendido', 'RSI14 cae bajo30 por primera vez.', 1),
        ('rsi_sobrecomprado', 'RSI14 supera70 por primera vez.', -1),
        ('macd_alcista', 'MACD12/26 cruza arriba de señal EMA9.', 1),
        ('macd_bajista', 'MACD12/26 cruza abajo de señal EMA9.', -1),
        ('bollinger_inferior', 'Cierre vuelve dentro desde debajo de media20 menos2 desviaciones.', 1),
        ('bollinger_superior', 'Cierre vuelve dentro desde sobre media20 más2 desviaciones.', -1),
        ('gap_alcista', 'Apertura supera máximo anterior por0.5%.', 1),
        ('gap_bajista', 'Apertura pierde mínimo anterior por0.5%.', -1),
    ]
    out = []
    for family, entries in [('vela', candles), ('figura', [(*x, 60) for x in graphs])]:
        for name, drawing, direction, length in entries:
            out.append(dict(id=name, nombre=name.replace('_', ' ').capitalize(), familia=family,
                            dibujo=drawing, direccion=direction, extremo_velas=length,
                            libro=('Se interpreta como posible subida.' if direction == 1 else
                                   'Se interpreta como posible caída.' if direction == -1 else
                                   'Se interpreta como indecisión; no tiene dirección única.'),
                            prueba='Entrada en apertura posterior, siete salidas, costos y dos controles; definición v1 fija.'))
    return out


def detect(df):
    """Solo operaciones rolling/shift hacia atrás y pivotes ya confirmados."""
    o,h,l,c,v = (df[k] for k in ['open','high','low','close','volume'])
    b=(c-o).abs(); r=(h-l).replace(0,np.nan)
    u=h-np.maximum(o,c); d=np.minimum(o,c)-l
    green=c>o; red=c<o; doji=b<=.1*r; small=b<=.3*r; large=b>=.6*r
    up=lambda k: c.shift(k)>c.shift(k+5)
    down=lambda k: c.shift(k)<c.shift(k+5)
    hammer=(d>=2*b)&(u<=.1*r)&(b>.1*r)
    inv=(u>=2*b)&(d<=.1*r)&(b>.1*r)
    inside=(np.maximum(o,c)<np.maximum(o.shift(),c.shift()))&(np.minimum(o,c)>np.minimum(o.shift(),c.shift()))
    engulf=(np.maximum(o,c)>=np.maximum(o.shift(),c.shift()))&(np.minimum(o,c)<=np.minimum(o.shift(),c.shift()))
    P={
        'doji':doji, 'doji_libelula':doji&(u<=.1*r)&(d>=.6*r)&down(1),
        'doji_lapida':doji&(d<=.1*r)&(u>=.6*r)&up(1),
        'doji_piernas_largas':doji&(u>=.35*r)&(d>=.35*r),
        'martillo':hammer&down(1), 'martillo_invertido':inv&down(1),
        'hombre_colgado':hammer&up(1), 'estrella_fugaz':inv&up(1),
        'marubozu_alcista':green&(b>=.9*r), 'marubozu_bajista':red&(b>=.9*r),
        'peonza':small&~doji&(u>=.2*r)&(d>=.2*r),
        'envolvente_alcista':engulf&green&red.shift()&down(2),
        'envolvente_bajista':engulf&red&green.shift()&up(2),
        'harami_alcista':inside&small&green&red.shift()&large.shift()&down(2),
        'harami_bajista':inside&small&red&green.shift()&large.shift()&up(2),
        'harami_cruz':inside&doji&large.shift(),
        'linea_penetrante':green&red.shift()&(o<l.shift())&(c>(o.shift()+c.shift())/2)&(c<o.shift())&down(2),
        'nube_oscura':red&green.shift()&(o>h.shift())&(c<(o.shift()+c.shift())/2)&(c>o.shift())&up(2),
        'pinzas_inferior':(abs(l-l.shift())<=.001*c)&green&red.shift()&down(2),
        'pinzas_superior':(abs(h-h.shift())<=.001*c)&red&green.shift()&up(2),
    }
    morning=red.shift(2)&large.shift(2)&small.shift()&green&(c>(o.shift(2)+c.shift(2))/2)&(np.maximum(o.shift(),c.shift())<c.shift(2))&down(3)
    evening=green.shift(2)&large.shift(2)&small.shift()&red&(c<(o.shift(2)+c.shift(2))/2)&(np.minimum(o.shift(),c.shift())>c.shift(2))&up(3)
    P.update(estrella_manana=morning, estrella_atardecer=evening,
             estrella_manana_doji=morning&doji.shift(), estrella_atardecer_doji=evening&doji.shift(),
             bebe_abandonado_alcista=morning&doji.shift()&(h.shift()<l.shift(2))&(l>h.shift()),
             bebe_abandonado_bajista=evening&doji.shift()&(l.shift()>h.shift(2))&(h<l.shift()),
             tres_soldados_blancos=green&green.shift()&green.shift(2)&(c>c.shift())&(c.shift()>c.shift(2)),
             tres_cuervos_negros=red&red.shift()&red.shift(2)&(c<c.shift())&(c.shift()<c.shift(2)))
    contained=pd.Series(True,index=df.index)
    for lag in (1,2,3):
        contained &= (h.shift(lag)<h.shift(4))&(l.shift(lag)>l.shift(4))
    P.update(tres_metodos_ascendentes=green.shift(4)&large.shift(4)&red.shift(3)&red.shift(2)&red.shift()&contained&green&(c>h.shift(4))&up(5),
             tres_metodos_descendentes=red.shift(4)&large.shift(4)&green.shift(3)&green.shift(2)&green.shift()&contained&red&(c<l.shift(4))&down(5),
             tres_dentro_arriba=P['harami_alcista'].shift()&green&(c>o.shift(2)),
             tres_dentro_abajo=P['harami_bajista'].shift()&red&(c<o.shift(2)),
             tres_fuera_arriba=P['envolvente_alcista'].shift()&green&(c>c.shift()),
             tres_fuera_abajo=P['envolvente_bajista'].shift()&red&(c<c.shift()),
             kicker_alcista=red.shift()&green&large&(o>o.shift()),
             kicker_bajista=green.shift()&red&large&(o<o.shift()),
             tasuki_alcista=green.shift(2)&green.shift()&(l.shift()>h.shift(2))&red&(o>o.shift())&(o<c.shift())&(c<h.shift(2))&(c>c.shift(2)),
             tasuki_bajista=red.shift(2)&red.shift()&(h.shift()<l.shift(2))&green&(o<c.shift())&(o>o.shift())&(c>l.shift(2))&(c<c.shift(2)),
             separacion_alcista=red.shift()&green&(abs(o-o.shift())<=.001*c)&up(2),
             separacion_bajista=green.shift()&red&(abs(o-o.shift())<=.001*c)&down(2))
    s50=c.rolling(50).mean(); s200=c.rolling(200).mean()
    delta=c.diff(); gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    loss=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    rsi=100-100/(1+gain/loss)
    macd=c.ewm(span=12,adjust=False,min_periods=26).mean()-c.ewm(span=26,adjust=False,min_periods=26).mean()
    msign=macd.ewm(span=9,adjust=False).mean()
    avg=c.rolling(20).mean(); std=c.rolling(20).std(ddof=0)
    lowband=avg-2*std; highband=avg+2*std
    P.update(cruce_dorado=(s50>s200)&(s50.shift()<=s200.shift()),
             cruce_muerte=(s50<s200)&(s50.shift()>=s200.shift()),
             rsi_sobrevendido=(rsi<30)&(rsi.shift()>=30), rsi_sobrecomprado=(rsi>70)&(rsi.shift()<=70),
             macd_alcista=(macd>msign)&(macd.shift()<=msign.shift()),
             macd_bajista=(macd<msign)&(macd.shift()>=msign.shift()),
             bollinger_inferior=(c>lowband)&(c.shift()<lowband.shift()),
             bollinger_superior=(c<highband)&(c.shift()>highband.shift()),
             gap_alcista=o>1.005*h.shift(),gap_bajista=o<.995*l.shift())
    graphs=[x['id'] for x in catalog() if x['familia']=='figura' and x['id'] not in P]
    arrays={name:np.zeros(len(df),dtype=bool) for name in graphs}
    highs,lows=[],[]
    hv,lv,cv=h.to_numpy(),l.to_numpy(),c.to_numpy()
    vol=(v>1.5*v.shift().rolling(20).mean()).fillna(False).to_numpy()
    for i in range(6,len(df)):
        j=i-3  # pivot j only confirmed at i; never trade at j
        if hv[j]>max(hv[j-3:j]) and hv[j]>=max(hv[j+1:i+1]): highs.append(j)
        if lv[j]<min(lv[j-3:j]) and lv[j]<=min(lv[j+1:i+1]): lows.append(j)
        highs=[x for x in highs if x>=i-60]; lows=[x for x in lows if x>=i-60]
        if not highs or not lows: continue
        resistance=hv[highs[-1]]; support=lv[lows[-1]]
        ru=cv[i]>resistance*1.005 and cv[i-1]<=resistance*1.005
        rd=cv[i]<support*.995 and cv[i-1]>=support*.995
        arrays['soporte'][i]=abs(lv[i]/support-1)<=.02 and cv[i]>support and cv[i]>cv[i-1]
        arrays['resistencia'][i]=abs(hv[i]/resistance-1)<=.02 and cv[i]<resistance and cv[i]<cv[i-1]
        for name,value in [('ruptura_resistencia',ru),('ruptura_soporte',rd),('ruptura_resistencia_volumen',ru and vol[i]),('ruptura_soporte_volumen',rd and vol[i])]: arrays[name][i]=value
        for top,pts,prices in [(True,highs,hv),(False,lows,lv)]:
            for n in [2,3]:
                if len(pts)<n: continue
                q=pts[-n:]; y=prices[q]
                if min(np.diff(q))<5: continue
                neck=min(lv[q[0]:q[-1]+1]) if top else max(hv[q[0]:q[-1]+1])
                broken=(cv[i]<neck*.995 and cv[i-1]>=neck*.995) if top else (cv[i]>neck*1.005 and cv[i-1]<=neck*1.005)
                similar=max(y)/min(y)<=1.02
                name=('doble_' if n==2 else 'triple_')+('techo' if top else 'piso')
                arrays[name][i]=similar and broken
                if n==3:
                    head=(y[1]>max(y[0],y[2])*1.03) if top else (y[1]<min(y[0],y[2])*.97)
                    arrays['hombro_cabeza_hombro' if top else 'hch_inverso'][i]=head and abs(y[0]/y[2]-1)<.02 and broken
        hh=[x for x in highs if x>=i-20]; ll=[x for x in lows if x>=i-20]
        if len(hh)<2 or len(ll)<2: continue
        # Two confirmed pivots per border, extrapolated only forward to today.
        ah=(hv[hh[-1]]-hv[hh[-2]])/(hh[-1]-hh[-2]); al=(lv[ll[-1]]-lv[ll[-2]])/(ll[-1]-ll[-2])
        roof=hv[hh[-1]]+ah*(i-hh[-1]); floor=lv[ll[-1]]+al*(i-ll[-1])
        if roof<=floor: continue
        eps=.001*cv[i]; flat_h=abs(ah)<eps; flat_l=abs(al)<eps
        bu=cv[i]>roof*1.005 and cv[i-1]<= (roof-ah)*1.005
        bd=cv[i]<floor*.995 and cv[i-1]>= (floor-al)*.995
        converges=ah<al; symmetric=ah<-eps and al>eps
        impulse=cv[max(0,i-20)]/cv[max(0,i-30)]-1
        parallel=abs(ah-al)<=eps
        vals={'triangulo_ascendente':flat_h and al>eps and bu,
              'triangulo_descendente':flat_l and ah<-eps and bd,
              'triangulo_simetrico_alcista':symmetric and bu,'triangulo_simetrico_bajista':symmetric and bd,
              'bandera_alcista':impulse>.1 and parallel and ah<0 and bu,
              'bandera_bajista':impulse<-.1 and parallel and al>0 and bd,
              'banderin_alcista':impulse>.1 and symmetric and bu,
              'banderin_bajista':impulse<-.1 and symmetric and bd,
              'canal_alcista':parallel and ah>eps and abs(lv[i]/floor-1)<.02 and cv[i]>cv[i-1],
              'canal_bajista':parallel and al<-eps and abs(hv[i]/roof-1)<.02 and cv[i]<cv[i-1],
              'cuna_ascendente':converges and ah>eps and al>eps and bd,
              'cuna_descendente':converges and ah<-eps and al<-eps and bu}
        for name,value in vals.items(): arrays[name][i]=value
        # Cup: confirmed rims separated20..50, bottom in middle third, depth10..40%, handle5..15.
        if len(highs)>=2:
            a,bp=highs[-2:]; width=bp-a; handle=i-bp
            if 20<=width<=50 and 5<=handle<=15 and abs(hv[a]/hv[bp]-1)<.02:
                bottom=a+int(np.argmin(lv[a:bp+1])); depth=1-lv[bottom]/min(hv[a],hv[bp])
                arrays['taza_con_asa'][i]=(.1<=depth<=.4 and a+width/3<=bottom<=a+2*width/3 and
                    min(lv[bp:i+1])>hv[bp]*(1-depth/2) and cv[i]>max(hv[a],hv[bp])*1.005 and cv[i-1]<=max(hv[a],hv[bp])*1.005)
    P.update({k:pd.Series(v,index=df.index) for k,v in arrays.items()})
    return {k:v.fillna(False).astype(bool) for k,v in P.items()}


def net_return(entry, exit_price, direction=1):
    """Short nocional sin préstamo: coste sobre ambos nocionales, sin apalancamiento."""
    ratio=exit_price/entry
    return direction*(ratio-1)-COST*(1+ratio)


def trade(df, i, mode, direction, stop=None, prices=None, split=None):
    """Señal al cierre i; compra/short en open i+1. Empate stop/objetivo: stop.
    Brecha de salida: open real, nunca precio del stop si fue atravesado.
    No etiqueta inmadura ni cruza corte2016. R neto dividido riesgo inicial.
    """
    if i+1>=len(df): return None
    prices=prices if prices is not None else df[['open','high','low','close']].to_numpy(float)
    entry=float(prices[i+1,0]); h=int(mode.split('_')[1]) if mode.startswith('fijo') else 20
    if i+h>=len(df): return None
    split=int(df.index.searchsorted(pd.Timestamp(SPLIT,tz='UTC'))) if split is None else split
    if i<split<=i+h: return None
    if mode.startswith('fijo'):
        return net_return(entry,float(prices[i+h,3]),direction),h,None
    risk=direction*(entry-stop)
    if risk<=0 or risk/entry>.5: return None
    target=entry+direction*int(mode.split('_')[1])*risk
    for j in range(i+1,i+21):
        opening,hi,lo,close=prices[j]
        if direction*(opening-stop)<=0: price=opening
        elif direction*(opening-target)>=0: price=opening
        elif (lo<=stop if direction==1 else hi>=stop): price=stop
        elif (hi>=target if direction==1 else lo<=target): price=target
        elif j==i+20: price=close
        else: continue
        value=net_return(entry,price,direction)
        return value,j-i,value/(risk/entry)
    return None


def fetch_daily(symbol):
    """Nuevos datos diarios en memoria; ajusta OHLC por splits/dividendos con adjclose.
    Yahoo no es una segunda fuente independiente. Cobertura y ese límite se publican.
    """
    start=int(pd.Timestamp(BEGIN,tz='UTC').timestamp()); end=int(pd.Timestamp(END,tz='UTC').timestamp())
    for attempt in range(3):
        r=requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol.replace(".","-")}',
                       params=dict(period1=start,period2=end,interval='1d'),headers={'User-Agent':'Mozilla/5.0'},timeout=40)
        if r.status_code==429: time.sleep(2**attempt); continue
        r.raise_for_status(); data=r.json()['chart']['result'][0]; break
    else: raise RuntimeError('Yahoo rate limit')
    q=data['indicators']['quote'][0]
    df=pd.DataFrame({k:q[k] for k in ['open','high','low','close','volume']},index=pd.to_datetime(data['timestamp'],unit='s',utc=True).normalize())
    adj=np.array(data['indicators'].get('adjclose',[{'adjclose':q['close']}])[0]['adjclose'],dtype=float)
    factor=adj/df.close.to_numpy(float)
    df[['open','high','low','close']]=df[['open','high','low','close']].mul(factor,axis=0)
    df=df.dropna().sort_index(); df=df[~df.index.duplicated()]
    # Yahoo may include a crypto candle at period2; enforce exclusivity locally.
    df=df[(df.index>=pd.Timestamp(BEGIN,tz='UTC'))&(df.index<pd.Timestamp(END,tz='UTC'))]
    df=df[(df[['open','high','low','close']]>0).all(axis=1)&(df.low<=df[['open','close']].min(axis=1))&(df.high>=df[['open','close']].max(axis=1))]
    if symbol.endswith('-USD') and (df.index.to_series().diff().dropna()!=pd.Timedelta(days=1)).any():
        raise ValueError('Huecos cripto: no se saltan sesiones')
    if len(df)<220: raise ValueError('Menos de220 sesiones')
    return df


def measure_asset(symbol,df):
    """Eventos no superpuestos por combinación. Azar estratificado antes/después2016,
    misma frecuencia sin reemplazo; conserva distribución de distancia del stop.
    Base: retorno normal neto direccional del activo y duración realmente observada.
    """
    patterns=detect(df); out={}; prices=df[['open','high','low','close']].to_numpy(float)
    split=int(df.index.searchsorted(pd.Timestamp(SPLIT,tz='UTC')))
    years=df.index.year.to_numpy();dates=[x.date().isoformat() for x in df.index]
    candidate_cache={}
    forward={}
    for direction in [-1,1]:
        for h in [1,5,10,20]:
            vals=pd.Series(net_return(df.open.shift(-1),df.close.shift(-h),direction),index=df.index)
            for period in ['antes2016','desde2016']:
                mask=(df.index<pd.Timestamp(SPLIT,tz='UTC')) if period=='antes2016' else (df.index>=pd.Timestamp(SPLIT,tz='UTC'))
                valid=mask & (df.index+pd.to_timedelta(h*2,unit='D')<pd.Timestamp(SPLIT,tz='UTC')) if period=='antes2016' else mask
                forward[(direction,h,period)]=float(vals[valid].mean())
    for p in catalog():
        direction=p['direccion'] or 1
        stop_series=(df.low.rolling(p['extremo_velas'],min_periods=1).min() if direction==1 else df.high.rolling(p['extremo_velas'],min_periods=1).max())
        indices=np.flatnonzero(patterns[p['id']].to_numpy()); stops=stop_series.to_numpy(float)
        for mode in EXITS:
            key=p['id']+'|'+mode; events=[]; last_exit=-1
            for i in indices:
                if i+1<=last_exit: continue
                stop=float(stops[i]); result=trade(df,i,mode,direction,stop,prices,split)
                if result is None: continue
                value,h,risk_r=result; last_exit=i+h
                period='antes2016' if years[i]<2016 else 'desde2016'
                # Exact normal return for every possible signal date of same duration/period.
                if (direction,h,period) not in forward:
                    vals=pd.Series(net_return(df.open.shift(-1),df.close.shift(-h),direction),index=df.index)
                    group=df.index.year<2016 if period=='antes2016' else df.index.year>=2016
                    if period=='antes2016': group=group & (np.arange(len(df))+h < np.searchsorted(df.index,pd.Timestamp(SPLIT,tz='UTC')))
                    forward[(direction,h,period)]=float(vals[group].mean())
                risk=direction*(prices[i+1,0]-stop)/prices[i+1,0]
                events.append(dict(date=dates[i],net=float(value),normal=forward[(direction,h,period)],
                                   period=period,r=float(risk_r) if risk_r is not None else None,risk=float(risk),h=int(h)))
            seed=int(hashlib.sha256((symbol+key).encode()).hexdigest()[:16],16)
            rng=np.random.default_rng(seed)
            for period in ['antes2016','desde2016']:
                group=[e for e in events if e['period']==period]
                if not group: continue
                horizon=int(mode.split('_')[1]) if mode.startswith('fijo') else 20
                if (horizon,period) not in candidate_cache:
                    candidate_cache[(horizon,period)]=[i for i in range(len(df)-horizon) if (years[i]<2016)==(period=='antes2016') and
                                                      (years[i+horizon]<2016)==(period=='antes2016')]
                candidates=candidate_cache[(horizon,period)]
                # Random control uses SAME nonoverlap convention and exactly n trades.
                available=list(rng.permutation(candidates)); chosen=[];occupied=np.zeros(len(df),dtype=bool)
                for j in available:
                    if not occupied[j:j+horizon].any():
                        chosen.append((j,j+horizon));occupied[j:j+horizon]=True
                    if len(chosen)==len(group): break
                if len(chosen)<len(group) and mode.startswith('fijo'):
                    # Exact random schedule via random gaps; avoids greedy packing failure.
                    slack=len(candidates)-1-(len(group)-1)*horizon
                    if slack>=0:
                        gaps=rng.multinomial(slack,np.full(len(group)+1,1/(len(group)+1)))
                        offsets=np.cumsum(gaps[:-1])+np.arange(len(group))*horizon
                        chosen=[(candidates[k],candidates[k]+horizon) for k in offsets]
                if len(chosen)<len(group):
                    # Variable stop duration: randomize dates, enforce actual exits, same n.
                    chosen=[];occupied[:]=False
                    rotation=int(rng.integers(0,len(candidates))) if candidates else 0
                    for j in np.roll(candidates,rotation):
                        if occupied[j]: continue
                        e=group[len(chosen)]; entry=float(prices[j+1,0])
                        trial=trade(df,j,mode,direction,entry*(1-direction*e['risk']),prices,split)
                        if trial and not occupied[j:j+trial[1]].any():
                            chosen.append((j,j+trial[1]));occupied[j:j+trial[1]]=True
                        if len(chosen)==len(group): break
                if len(chosen)<len(group):
                    for e in group: e['random']=None
                    continue
                for e,(j,_) in zip(group,chosen):
                    entry=float(prices[j+1,0]); stop=entry*(1-direction*e['risk'])
                    result=trade(df,j,mode,direction,stop,prices,split)
                    e['random']=float(result[0]) if result else None
            # Derived date-level metrics only, no raw OHLC.
            out[key]=[dict(e,symbol=symbol) for e in events if e.get('random') is not None]
    return out


def aggregate_dates(events):
    """Sufficient date-level statistics; no need to retain millions of trade dicts."""
    dates={}
    for e in events:
        row=dates.setdefault(e['date'],[0.,0.,0.,0.,0.,0.,0.])
        row[0]+=1;row[1]+=e['net']>0;row[2]+=e['net'];row[3]+=e['normal'];row[4]+=e['random']
        if e['r'] is not None: row[5]+=e['r'];row[6]+=1
    return dates


def merge_dates(target,source):
    for date,values in source.items():
        row=target.setdefault(date,[0.]*7)
        for i,value in enumerate(values): row[i]+=value


def summarize(events,seed=1):
    if not events: return dict(n=0,ganadoras=None,media_neta=None,p_normal=1.,p_azar=1.,t=None,ci_fecha=None,esperanza_R=None)
    dates=events if isinstance(events,dict) else aggregate_dates(events)
    rows=np.array([dates[k] for k in sorted(dates)],dtype=float)
    totals=rows.sum(axis=0);n=int(totals[0])
    # Cluster across assets by signal date. Moving20-date block bootstrap reduces overlap dependence.
    values=np.column_stack([(rows[:,2]-rows[:,3])/rows[:,0],(rows[:,2]-rows[:,4])/rows[:,0],rows[:,2]/rows[:,0]])
    m=len(values)
    mean=values.mean(axis=0); rng=np.random.default_rng(seed)
    if m<30 or n<30:
        p=[1.,1.]; t=None; ci=None
    else:
        block=min(20,m); chunks=math.ceil(m/block)
        # Precomputed circular block means:20x less memory/work than materializing dates.
        circular=np.concatenate([values,values[:block-1]],axis=0)
        cumul=np.vstack([np.zeros((1,3)),np.cumsum(circular,axis=0)])
        blocks=(cumul[block:]-cumul[:-block])/block
        draws=[]
        for batch in range(0,BOOTSTRAPS,100):
            starts=rng.integers(0,m,(min(100,BOOTSTRAPS-batch),chunks))
            draws.extend(blocks[starts].mean(axis=1))
        boot=np.array(draws); se=boot.std(axis=0,ddof=1)
        stats=np.divide(mean,se,out=np.zeros(3),where=se>0)
        p=[float(2*student.sf(abs(stats[i]),m-1)) if se[i]>0 else 1. for i in range(2)]
        t=float(stats[0]); ci=[float(x) for x in np.quantile(boot[:,2],[.025,.975])]
    return dict(n=n,fechas=m,ganadoras=float(totals[1]/n),media_neta=float(totals[2]/n),
                normal=float(totals[3]/n),azar=float(totals[4]/n),exceso_normal=float((totals[2]-totals[3])/n),
                exceso_azar=float((totals[2]-totals[4])/n),p_normal=p[0],p_azar=p[1],t=t,ci_fecha=ci,
                esperanza_R=float(totals[5]/totals[6]) if totals[6] else None,
                inferencia='t con error estándar bootstrap bloques20 fechas; activos agrupados por fecha; IC media de fechas')


def bh(values):
    ordered=sorted(values,key=values.get); m=len(ordered); q={}; previous=1.
    for rank in range(m,0,-1):
        key=ordered[rank-1]; previous=min(previous,values[key]*m/rank); q[key]=previous
    return q


def opposite_book(stats,direction):
    """Underperforming the baseline is not the same as moving opposite the book."""
    net=stats.get('media_neta')
    if not direction or net is None: return False
    gross=direction*((net+direction+COST)/(direction-COST)-1)
    return gross<0 and stats.get('exceso_normal',0)<0 and stats.get('exceso_azar',0)<0


def add_bh_counts(report):
    """Expose raw significance separately from positive, temporally stable rules."""
    contrasts=groups=pool=0;patterns=set()
    for pattern in report['items']:
        for exit in pattern['salidas']:
            for asset in ['universo','BTC-USD','ETH-USD']:
                for period in ['total','antes2016','desde2016']:
                    s=exit['grupos'][asset][period]
                    contrasts+=sum(s.get('q_'+c,1)<=.05 for c in ['normal','azar'])
                    groups+=bool(s.get('pasa_BH'))
                    if asset=='universo' and period=='total' and s.get('pasa_BH'):
                        pool+=1;patterns.add(pattern['id'])
    report.update(pruebas_pasan_BH=contrasts,grupos_ambos_controles_BH=groups,
                  combinaciones_universo_BH=pool,patrones_universo_BH=sorted(patterns))
    return report


def finalize(parts,output=ROOT/'resultados/enciclopedia.json'):
    combined={}; coverage={}; errors={}; minutes=0
    for part in parts:
        coverage.update(part['coverage']); errors.update(part['errors']); minutes+=part['minutes']
        if 'aggregates' in part:
            for key,groups in part['aggregates'].items():
                targets=combined.setdefault(key,{})
                for asset,dates in groups.items(): merge_dates(targets.setdefault(asset,{}),dates)
        else:
            for key,events in part['events'].items():
                groups=combined.setdefault(key,{})
                merge_dates(groups.setdefault('universo',{}),aggregate_dates(events))
                for asset in ['BTC-USD','ETH-USD']:
                    merge_dates(groups.setdefault(asset,{}),aggregate_dates(e for e in events if e['symbol']==asset))
    rows=[]; tests={}
    # Global correction includes FULL/pre/post x two contrasts x pool/BTC/ETH x all exits.
    for p in catalog():
        exits=[]
        for mode in EXITS:
            events=combined.get(p['id']+'|'+mode,{}); groups={}
            for asset in ['universo','BTC-USD','ETH-USD']:
                selected=events.get(asset,{})
                groups[asset]={}
                for period in ['total','antes2016','desde2016']:
                    subset=selected if period=='total' else {date:values for date,values in selected.items() if (date<SPLIT)==(period=='antes2016')}
                    key=p['id']+'|'+mode+'|'+asset+'|'+period
                    s=summarize(subset,int(hashlib.sha256(key.encode()).hexdigest()[:8],16))
                    groups[asset][period]=s
                    for control in ['normal','azar']: tests[key+'|'+control]=s['p_'+control]
            exits.append(dict(id=mode,grupos=groups))
        rows.append(dict(p,salidas=exits))
    adjusted=bh(tests); passed=0; contrary=0
    complete=len(coverage)+len(errors)>=len(json.loads((ROOT/'ideas/enciclopedia_universo.json').read_text())['symbols'])
    for p in rows:
        states=[]
        for mode in p['salidas']:
            for asset,groups in mode['grupos'].items():
                for period,s in groups.items():
                    key=p['id']+'|'+mode['id']+'|'+asset+'|'+period
                    s['q_normal']=adjusted[key+'|normal']; s['q_azar']=adjusted[key+'|azar']
                    s['pasa_BH']=complete and max(s['q_normal'],s['q_azar'])<=.05
                s=groups['total']; post=groups['desde2016']; pre=groups['antes2016']
                good=lambda a: a.get('exceso_normal',0)>0 and a.get('exceso_azar',0)>0 and a.get('media_neta',0)>0
                bad=lambda a: opposite_book(a,p['direccion'])
                status='sin_evidencia'
                if s['n']<30: status='insuficiente'
                elif p['direccion'] and s['pasa_BH'] and good(s) and post['pasa_BH'] and good(post) and pre['n']>=30 and good(pre): status='sirve_en_muestra'
                elif p['direccion'] and s['pasa_BH'] and bad(s) and post['pasa_BH'] and bad(post): status='contrario_al_libro'
                groups['estado']=status
                if asset=='universo': states.append(status); passed+=status=='sirve_en_muestra'; contrary+=status=='contrario_al_libro'
        p['estado']='sirve_en_muestra' if 'sirve_en_muestra' in states else 'contrario_al_libro' if 'contrario_al_libro' in states else 'sin_evidencia' if any(s!='insuficiente' for s in states) else 'insuficiente'
        p['conclusion']=dict(sirve_en_muestra='Efecto histórico que sobrevivió controles y corte temporal; falta evaluación prospectiva.',contrario_al_libro='El efecto significativo va contra la dirección descrita; no autoriza invertir la regla.',sin_evidencia='No demostró ventaja con estos datos, costos y comparaciones.',insuficiente='Faltan observaciones para evaluar.')[p['estado']]
    report=dict(version=1,as_of=datetime.now(timezone.utc).isoformat(),begin=BEGIN,end_exclusive=END,
                fuente='Yahoo Chart, OHLC ajustados; sin corroboración independiente completa',
                metodo='Definiciones operativas v1; entrada futura; eventos separados; bootstrap por bloques20 fechas; BH global bilateral; cortes2016; controles del mismo activo. Selección histórica, no prueba causal prospectiva.',
                limitaciones=['S&P500 actual: sesgo de supervivencia; no universo histórico.','No costos de préstamo en ventas hipotéticas; no trading real.','Los precios ajustados son reconstrucciones retrospectivas.','Sin evidencia no prueba efecto cero.','Calendario de bolsa de la fuente; sesiones ausentes no verificadas con segunda fuente.'],
                completo=complete,coverage=coverage,errors=errors,cost_per_side=COST,minutes_compute=minutes,
                patrones=len(rows),velas=sum(p['familia']=='vela' for p in rows),combinaciones=len(rows)*len(EXITS),pruebas_BH=len(tests),
                combinaciones_pasan=passed,combinaciones_contrarias=contrary,patrones_pasan=sum(p['estado']=='sirve_en_muestra' for p in rows),
                patrones_contrarios=[p['id'] for p in rows if p['estado']=='contrario_al_libro'],items=rows)
    add_bh_counts(report)
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n',encoding='utf8')
    return report


def batch(symbols,fetcher=fetch_daily):
    started=time.monotonic(); result=dict(aggregates={},coverage={},errors={},minutes=0)
    # Download concurrently, measure deterministically one asset at a time. No persistent raw data.
    with ThreadPoolExecutor(max_workers=4) as pool:
        def get(symbol):
            try: return symbol,fetcher(symbol),None
            except Exception as exc: return symbol,None,type(exc).__name__
        for symbol,df,error in pool.map(get,symbols):
            if error: result['errors'][symbol]=error; print(symbol,error,flush=True); continue
            result['coverage'][symbol]=dict(first=df.index[0].date().isoformat(),last=df.index[-1].date().isoformat(),sessions=len(df),ten_years=(df.index[-1]-df.index[0]).days>=3652)
            try:
                events=measure_asset(symbol,df)
                for key,values in events.items():
                    group=result['aggregates'].setdefault(key,{})
                    dates=aggregate_dates(values);merge_dates(group.setdefault('universo',{}),dates)
                    if symbol in ['BTC-USD','ETH-USD']: merge_dates(group.setdefault(symbol,{}),dates)
            except Exception as exc:
                result['coverage'].pop(symbol); result['errors'][symbol]='measure_'+type(exc).__name__
                raise
            print(symbol,len(df),flush=True)
    result['minutes']=(time.monotonic()-started)/60
    return result


def repair_crypto(directory):
    """Reuse already measured STOCK metrics; replace only the two crypto inputs.
    No new variants/thresholds. Original artifacts contain derived metrics, no OHLC.
    """
    paths=sorted(directory.rglob('parte-*.json'))
    if len(paths)!=8: raise ValueError('La reparación exige los ocho lotes originales')
    crypto=['BTC-USD','ETH-USD']
    def parts():
        for path in paths:
            part=json.loads(path.read_text(encoding='utf8'))
            for symbol,coverage in part['coverage'].items():
                if symbol not in crypto and coverage['last']>=END:
                    raise ValueError('Hay acciones fuera del corte: no reutilizar este lote')
            for symbol in crypto:
                part['coverage'].pop(symbol,None);part['errors'].pop(symbol,None)
            if 'events' in part:
                for key,events in part['events'].items():
                    part['events'][key]=[e for e in events if e['symbol'] not in crypto]
            else:
                for groups in part['aggregates'].values():
                    pool=groups.get('universo',{})
                    for symbol in crypto:
                        for date,values in groups.pop(symbol,{}).items():
                            for i,value in enumerate(values): pool[date][i]-=value
                            if pool[date][0]==0: pool.pop(date)
            yield part
        yield batch(crypto)
    return finalize(parts())


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--batch',type=int); parser.add_argument('--batches',type=int,default=8)
    parser.add_argument('--merge',type=Path); parser.add_argument('--output',type=Path); parser.add_argument('--symbols',nargs='+')
    parser.add_argument('--repair-crypto',type=Path)
    args=parser.parse_args()
    if args.repair_crypto:
        result=repair_crypto(args.repair_crypto)
        print('Corte reparado:',result['patrones_pasan'],'reglas estables; BH',result['pruebas_pasan_BH'])
    elif args.merge:
        paths=sorted(args.merge.rglob('parte-*.json'))
        if len(paths)!=args.batches: raise ValueError('Faltan lotes: no aplicar BH parcial')
        # Stream one batch at a time; do not load all large artifacts into RAM.
        parts=(json.loads(p.read_text(encoding='utf8')) for p in paths)
        result=finalize(parts,args.output or ROOT/'resultados/enciclopedia.json')
        print(json.dumps({k:result[k] for k in ['patrones','velas','pruebas_BH','patrones_pasan','patrones_contrarios','minutes_compute']}))
    else:
        symbols=args.symbols or json.loads((ROOT/'ideas/enciclopedia_universo.json').read_text())['symbols']
        if args.batch is not None: symbols=symbols[args.batch::args.batches]
        result=batch(symbols)
        if args.batch is not None:
            path=args.output or ROOT/f'resultados/parte-{args.batch}.json'; path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(result,allow_nan=False,separators=(',',':')),encoding='utf8')
        else: finalize([result],args.output or ROOT/'resultados/enciclopedia.json')
