"""Gimnasio del Oráculo: miles de repeticiones diarias con datos point-in-time.

Entrenamiento 1990-2014 (aprende), validación 2015-2019 (solo mide), 2020 en adelante sellado: no se toca.
Validación: conjunto fijo (mismas fechas y activos en cada sesión), t por bootstrap de bloques de fechas, tres referencias.
Cada método solo ve filas cuya hora de disponibilidad es <= la del cierre de la fecha de decisión.
"""
import argparse
import datetime as dt
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
PIT = ROOT / 'datos' / 'pit'
OUT = ROOT / 'resultados' / 'gimnasio_oraculo'
HORIZONTES = (1, 5, 21)
VENTANA_EVENTOS = {1: 3, 5: 7, 21: 30}  # días calendario hacia adelante (calendarios publicados de antemano)
TRAIN = ('1990-01-01', '2014-11-30')  # corte 30 nov: las etiquetas a 21 días maduran antes de la validación
VAL = ('2015-01-01', '2019-11-30')    # idem: ninguna etiqueta toca 2020 (prueba sellada)
PRIOR_N = 50
RETRAIN_CADA = 24
POOL_MAX = 10000
PASO_VAL = 5          # conjunto fijo de validación: fechas con ordinal múltiplo de 5 (igual en todas las sesiones)
BLOQUE = 10           # bootstrap por bloques de fechas (en pasos de 5 días: cubre el solapamiento de 21 sesiones)
N_BOOT = 1000
REF_PRINCIPAL = 'tasa_base_ventana'
REFS_SKILL = ['tasa_base_entrenamiento', 'tasa_base_ventana', 'siempre_sube_calibrado']
FEATURES = ['r1', 'r5', 'mom', 'vol', 'dist', 'rsi', 'volrel']
METODOS = ['tendencia_sma200', 'momentum_1m', 'momentum_3m', 'momentum_12m', 'reversion_caida', 'volumen_anomalo',
           'soporte_resist_20', 'soporte_resist_60', 'rsi', 'calendario', 'eventos', 'regimen_volatilidad']
ENSAMBLE_MIEMBROS = METODOS + ['logistica']
REFERENCIAS = ['tasa_base', 'siempre_sube']
TODOS = ENSAMBLE_MIEMBROS + REFERENCIAS


def cargar_activos(carpeta=PIT / 'precios'):
    out = {}
    for f in sorted(Path(carpeta).glob('*.csv.gz')):
        d = pd.read_csv(f, parse_dates=['date'])
        d['disp'] = pd.to_datetime(d['available_at'], utc=True)
        out[f.name[:-7].replace('_GSPC', '^GSPC')] = d.sort_values('disp').reset_index(drop=True)
    return out


def cargar_eventos(ruta=PIT / 'eventos.csv'):
    e = pd.read_csv(ruta)
    e = e[e.tipo.isin(['FOMC', 'CPI', 'EMPLEO'])]
    e['fecha'] = pd.to_datetime(e['fecha'])
    return {t: np.sort(g.fecha.values.astype('datetime64[D]')) for t, g in e.groupby('tipo')}


def _rsi(c, n=14):
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def _bucket(cond_list, labels, default='na'):
    out = np.full(len(cond_list[0]), default, dtype=object)
    for cond, label in reversed(list(zip(cond_list, labels))):
        out[np.asarray(cond)] = label
    return out


def _sr(c, n):
    hi = c.shift(1).rolling(n).max()
    lo = c.shift(1).rolling(n).min()
    pos = (c - lo) / (hi - lo).replace(0, np.nan)
    ok = hi.notna() & lo.notna()
    return _bucket([~ok, c > hi, c < lo, pos >= 2 / 3, pos <= 1 / 3], ['na', 'rotura_arriba', 'rotura_abajo', 'alto', 'bajo'], 'medio')


def construir(d, eventos, simbolo=''):
    """Todo vectorizado con operaciones hacia atrás: la fila i solo usa filas <= i (lo verifican los tests)."""
    c = d['close'].astype(float)
    cripto = simbolo.endswith('-USD')
    mes, trim, anio = (30, 90, 365) if cripto else (21, 63, 252)
    r1 = c.pct_change()
    vol = r1.rolling(20).std()
    vol_med = vol.rolling(252, min_periods=60).median()
    volu = d['volume'].astype(float).replace(0, np.nan)
    z = (volu - volu.rolling(20).mean().shift(1)) / volu.rolling(20).std().shift(1)
    ret5 = c / c.shift(5) - 1
    rsi = _rsi(c)
    fecha = d['date']
    n_mes = fecha.groupby([fecha.dt.year, fecha.dt.month]).cumcount() + 1
    b = {}
    sma = c.shift(1).rolling(200).mean()
    b['tendencia_sma200'] = _bucket([sma.isna(), c >= sma], ['na', 'sobre'], 'bajo')
    for nom, k in (('momentum_1m', mes), ('momentum_3m', trim), ('momentum_12m', anio)):
        s = c.shift(k)
        b[nom] = _bucket([s.isna(), c >= s], ['na', 'sube'], 'baja')
    b['reversion_caida'] = _bucket([ret5.isna(), ret5 <= -.10, ret5 <= -.05, ret5 <= -.02], ['na', 'caida10', 'caida5', 'caida2'], 'sin_caida')
    b['volumen_anomalo'] = _bucket([z.isna(), (z > 2) & (r1 >= 0), (z > 2) & (r1 < 0)], ['na', 'alto_sube', 'alto_baja'], 'normal')
    b['soporte_resist_20'] = _sr(c, 20)
    b['soporte_resist_60'] = _sr(c, 60)
    b['rsi'] = _bucket([rsi.isna(), rsi < 30, rsi < 50, rsi < 70], ['na', 'sobrevendido', 'bajo', 'medio'], 'sobrecomprado')
    fase = np.where(n_mes <= 3, 'inicio', np.where(fecha.dt.day >= 27, 'fin', 'medio'))
    b['calendario'] = (fecha.dt.day_of_week.astype(str) + '_' + pd.Series(fase)).to_numpy(dtype=object)
    ratio = vol / vol_med
    b['regimen_volatilidad'] = _bucket([ratio.isna(), ratio < .8, ratio > 1.25], ['na', 'baja', 'alta'], 'normal')
    # Eventos programados (FOMC/CPI/empleo) dentro del horizonte; el calendario se publica de antemano.
    dia = fecha.values.astype('datetime64[D]')
    ev = {}
    for h, w in VENTANA_EVENTOS.items():
        flags = []
        for t in ('FOMC', 'CPI', 'EMPLEO'):
            fe = eventos.get(t, np.array([], dtype='datetime64[D]'))
            flags.append(np.searchsorted(fe, dia + np.timedelta64(w, 'D'), side='right') - np.searchsorted(fe, dia, side='right') > 0)
        ev[h] = np.array([f'F{int(a)}C{int(b_)}E{int(e)}' for a, b_, e in zip(*flags)], dtype=object)
    feats = pd.DataFrame({'r1': r1, 'r5': ret5, 'mom': c.shift(mes) / c.shift(anio) - 1, 'vol': vol,
                          'dist': c / sma - 1, 'rsi': rsi / 100, 'volrel': ratio})
    base, up = {}, {}
    for h in HORIZONTES:
        # Solo pares (j, j+h) con j+h <= i: el último cierre ya observado en la fila i.
        madura = (c.shift(-h) / c > 1).astype(float).where(c.shift(-h).notna())
        acum = madura.fillna(0).cumsum().shift(h)
        cnt = madura.notna().astype(float).cumsum().shift(h)
        base[h] = (acum / cnt).fillna(.53).to_numpy()
        up[h] = (c.shift(-h) / c - 1 > 0).to_numpy()
    return {'sim': simbolo, 'n': len(d), 'bucket': b, 'eventos': ev, 'feats': feats, 'base': base, 'up': up,
            'fecha': fecha.to_numpy(), 'hecho': c.shift(-max(HORIZONTES)).notna().to_numpy()}


def estado_inicial():
    return {'sesiones': 0, 'repeticiones_train': 0, 'repeticiones_val': 0,
            'hedge': {str(h): {m: [0., 0] for m in ENSAMBLE_MIEMBROS} for h in HORIZONTES},
            'cal': {}, 'val_final': {}, 'logistica': {}}


def pesos_hedge(hedge_h):
    """Hedge clásico: w ∝ exp(-eta * pérdida acumulada), eta = sqrt(8 ln K / T); piso 1/(4K)."""
    k = len(hedge_h)
    t = max(v[1] for v in hedge_h.values())
    if t == 0:
        return {m: 1 / k for m in hedge_h}
    eta = math.sqrt(8 * math.log(max(k, 2)) / t)
    mn = min(v[0] for v in hedge_h.values())
    raw = {m: math.exp(-eta * (v[0] - mn)) for m, v in hedge_h.items()}
    tot = sum(raw.values())
    floor = 1 / (4 * k)
    return {m: floor + (1 - k * floor) * r / tot for m, r in raw.items()}


def _prob_logistica(modelo, x):
    if not modelo or np.isnan(x).any():
        return None
    z = float(((x - np.array(modelo['mean'])) / np.array(modelo['scale'])) @ np.array(modelo['coef']) + modelo['intercept'])
    return 1 / (1 + math.exp(-z))


def predecir(estado, S, i, h):
    """Probabilidad de subida a h sesiones para cada método, con datos <= fila i."""
    base = float(S['base'][h][i])
    out = {'tasa_base': base, 'siempre_sube': 1.0}
    for m in METODOS:
        bk = S['eventos'][h][i] if m == 'eventos' else S['bucket'][m][i]
        ups, n = estado['cal'].get(m, {}).get(f'{h}|{bk}', (0, 0))
        out[m] = min(.98, max(.02, (ups + PRIOR_N * base) / (n + PRIOR_N)))
    p = _prob_logistica(estado['logistica'].get(str(h)), S['feats'].iloc[i][FEATURES].to_numpy(dtype=float))
    out['logistica'] = base if p is None else min(.98, max(.02, p))
    return out


def ensamble(preds, pesos):
    return sum(pesos[m] * preds[m] for m in ENSAMBLE_MIEMBROS)


def _actualiza_cal(estado, S, i, h, y):
    for m in METODOS:
        bk = S['eventos'][h][i] if m == 'eventos' else S['bucket'][m][i]
        c = estado['cal'].setdefault(m, {}).setdefault(f'{h}|{bk}', [0, 0])
        c[0] += int(y)
        c[1] += 1


def elegibles(S, rango):
    f = S['fecha']
    ok = (f >= np.datetime64(rango[0])) & (f <= np.datetime64(rango[1])) & S['hecho']
    ok &= np.arange(S['n']) >= 260
    return np.flatnonzero(ok)


def validacion_fija(series):
    """Conjunto fijo y determinista (no depende de la semilla ni de la sesión): fechas con ordinal múltiplo de PASO_VAL."""
    out = {}
    for s_, S in series.items():
        idx = elegibles(S, VAL)
        ords = S['fecha'][idx].astype('datetime64[D]').astype(np.int64)
        idx = idx[ords % PASO_VAL == 0]
        if len(idx):
            out[s_] = idx
    return out


def _estadisticos(perd, ref, grupo, ng, rng):
    """skill = 1 - Brier/Brier_ref; t = dif media / error estándar de bootstrap por bloques de FECHAS (no de repeticiones)."""
    dif = ref - perd
    sd = np.bincount(grupo, weights=dif, minlength=ng)
    cn = np.bincount(grupo, minlength=ng).astype(float)
    nb = int(math.ceil(ng / BLOQUE))
    ini = rng.integers(0, max(ng - BLOQUE, 0) + 1, size=(N_BOOT, nb))
    pos = (ini[:, :, None] + np.arange(BLOQUE)).reshape(N_BOOT, -1)[:, :ng]
    medias = sd[pos].sum(1) / cn[pos].sum(1)
    media = float(dif.mean())
    se = float(medias.std(ddof=1))
    return {'skill': float(1 - perd.mean() / ref.mean()), 'brier': float(perd.mean()), 'brier_ref': float(ref.mean()),
            't': media / se if se > 0 else 0., 'n': int(len(perd))}


def evaluar(estado, series, fijo, pesos):
    """Mide todos los métodos con el estado congelado sobre el MISMO conjunto fijo; t agrupada por fecha."""
    filas = []
    for s_, idx in fijo.items():
        S = series[s_]
        for i in idx:
            f = int(S['fecha'][i].astype('datetime64[D]').astype(np.int64))
            for h in HORIZONTES:
                preds = predecir(estado, S, int(i), h)
                preds['ensamble'] = ensamble(preds, pesos[h])
                filas.append((s_, f, h, float(S['up'][h][i]), preds))
    ys = np.array([r[3] for r in filas])
    hs = np.array([r[2] for r in filas])
    sims = np.array([r[0] for r in filas])
    fechas = np.array([r[1] for r in filas])
    _, grupo = np.unique(fechas, return_inverse=True)
    ng = int(grupo.max()) + 1
    refs = {'tasa_base_entrenamiento': np.array([r[4]['tasa_base'] for r in filas])}
    v = np.zeros(len(ys))
    c = np.zeros(len(ys))
    for h in HORIZONTES:
        v[hs == h] = ys[hs == h].mean()
        for s_ in np.unique(sims):
            m = (hs == h) & (sims == s_)
            if m.any():
                c[m] = ys[m].mean()
    refs['tasa_base_ventana'] = v          # constante por horizonte con la frecuencia de subida de la propia ventana (en muestra)
    refs['siempre_sube_calibrado'] = c     # constante por activo y horizonte con su frecuencia de subida en la ventana (en muestra)
    perdidas = {m: (np.array([r[4][m] for r in filas]) - ys) ** 2 for m in TODOS + ['ensamble']}
    out = {'filas': len(filas), 'fechas': ng, 'activos': len(fijo), 'paso_dias': PASO_VAL, 'bloque_bootstrap': BLOQUE,
           'frecuencia_subida_ventana': {str(h): float(ys[hs == h].mean()) for h in HORIZONTES},
           'brier_ref': {}, 'metodos': {}}
    for rn, r in refs.items():
        rl = (r - ys) ** 2
        out['brier_ref'][rn] = float(rl.mean())
        rr = np.random.default_rng(12345)  # misma semilla de remuestreo en cada sesión y referencia
        out['metodos'][rn] = {m: _estadisticos(perdidas[m], rl, grupo, ng, rr) for m in perdidas}
    return out


def sesion(estado, activos, rng, n_train=500, n_val=None, ahora=None, quemar_rng_val=0):
    """Una sesión: entrena n_train repeticiones (aprende) y mide el conjunto fijo de validación (congelado).

    n_val se conserva por compatibilidad y se ignora: la validación ya no se muestrea.
    quemar_rng_val solo sirve a `rehacer_historia`: consume del rng lo que consumía el muestreo antiguo para reproducir el entrenamiento real."""
    series = {s: construir(d, activos['__eventos__'], s) for s, d in activos.items() if s != '__eventos__'}
    el_tr = {s: elegibles(S, TRAIN) for s, S in series.items()}
    el_tr = {s: v for s, v in el_tr.items() if len(v)}
    filas, etiquetas = [], []
    for _ in range(n_train):
        s = list(el_tr)[rng.integers(len(el_tr))]
        S = series[s]
        i = int(rng.choice(el_tr[s]))
        x = S['feats'].iloc[i][FEATURES].to_numpy(dtype=float)
        ys = []
        for h in HORIZONTES:
            y = bool(S['up'][h][i])
            preds = predecir(estado, S, i, h)
            for m in ENSAMBLE_MIEMBROS:
                lo = estado['hedge'][str(h)][m]
                lo[0] += (preds[m] - y) ** 2
                lo[1] += 1
            _actualiza_cal(estado, S, i, h, y)
            ys.append(int(y))
        if not np.isnan(x).any():
            filas.append(x)
            etiquetas.append(ys)
    estado['repeticiones_train'] += n_train
    if quemar_rng_val:
        el_va = {k: v for k, v in ((k, elegibles(S, VAL)) for k, S in series.items()) if len(v)}
        for _ in range(quemar_rng_val):
            rng.choice(el_va[list(el_va)[rng.integers(len(el_va))]])
    pesos = {h: pesos_hedge(estado['hedge'][str(h)]) for h in HORIZONTES}
    ev = evaluar(estado, series, validacion_fija(series), pesos)
    estado['val_final'] = ev
    estado['sesiones'] += 1
    return ev, np.array(filas, dtype=np.float32), np.array(etiquetas, dtype=np.int8)


def reentrenar(estado, X, Y):
    for k, h in enumerate(HORIZONTES):
        y = Y[:, k]
        if len(y) < 300 or len(set(y.tolist())) < 2:
            continue
        sc = StandardScaler().fit(X)
        lr = LogisticRegression(C=.1, max_iter=300).fit(sc.transform(X), y)
        estado['logistica'][str(h)] = {'mean': sc.mean_.tolist(), 'scale': sc.scale_.tolist(),
                                       'coef': lr.coef_[0].tolist(), 'intercept': float(lr.intercept_[0]), 'filas': int(len(y))}


def juntar_pool(out, X, Y, rng, consolidar):
    """Lotes por sesión (append-only); al reentrenar se consolidan en pool.npz con tope POOL_MAX."""
    lotes = out / 'lotes'
    lotes.mkdir(parents=True, exist_ok=True)
    if len(X):
        np.savez_compressed(lotes / f'{int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)}.npz', X=X, Y=Y)
    if not consolidar:
        return None
    xs, ys = [], []
    for f in [out / 'pool.npz'] + sorted(lotes.glob('*.npz')):
        if f.exists():
            with np.load(f) as z:
                xs.append(z['X'])
                ys.append(z['Y'])
    if not xs:
        return None
    X, Y = np.concatenate(xs), np.concatenate(ys)
    if len(X) > POOL_MAX:
        idx = np.sort(rng.choice(len(X), POOL_MAX, replace=False))
        X, Y = X[idx], Y[idx]
    np.savez_compressed(out / 'pool.npz', X=X, Y=Y)
    for f in lotes.glob('*.npz'):
        f.unlink()
    return X, Y


def resumen(estado, pesos):
    ev = estado.get('val_final') or {}
    if not ev:
        return {'actualizado': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'sesiones': estado['sesiones'],
                'pesos_hedge': pesos, 'frase': 'Sin datos de validación todavía.'}
    por_ref, mejores = {}, {}
    for rn in REFS_SKILL:
        mets = ev['metodos'][rn]
        cand = {m: v for m, v in mets.items() if m in METODOS + ['logistica']}
        top = sorted(cand.items(), key=lambda kv: -kv[1]['skill'])[:5]
        por_ref[rn] = {'brier_referencia': ev['brier_ref'][rn], 'top5': [{'metodo': m, **v} for m, v in top],
                       'ensamble': mets['ensamble']}
        mejores[rn] = top[0]
    mb, e = mejores[REF_PRINCIPAL], por_ref[REF_PRINCIPAL]['ensamble']
    umbral = 3.0  # el mejor de 13 métodos: t>2 aparece por azar; se exige t>3 y que valga en las tres referencias
    robusto = all(mejores[r][1]['skill'] > 0 and mejores[r][1]['t'] > umbral for r in REFS_SKILL)
    if mb[1]['skill'] <= 0:
        et = por_ref['tasa_base_entrenamiento']['ensamble']
        frase = (f"Sin ventaja demostrada: ningún método supera la tasa base de la propia ventana 2015-2019 (mejor {mb[0]}, skill {mb[1]['skill']:.4f}, t={mb[1]['t']:.1f}; "
                 f"ensamble skill {e['skill']:.4f}, t={e['t']:.1f}). La ganancia contra la tasa base de entrenamiento 1990-2014 (ensamble skill {et['skill']:.4f}, t={et['t']:.1f}) "
                 'es compatible con el sesgo alcista de 2015-2019 (frecuencia de subida mayor que la histórica) y no demuestra capacidad de predicción.')
    elif not robusto:
        frase = (f"Sin ventaja demostrada: contra la tasa base de la ventana 2015-2019 el mejor método ({mb[0]}) tiene skill {mb[1]['skill']:.4f} "
                 f"y t={mb[1]['t']:.1f} (bootstrap por bloques de fechas, no por repetición), y el ensamble skill {e['skill']:.4f}, t={e['t']:.1f}; "
                 f"el skill contra la tasa base de entrenamiento 1990-2014 ({mejores['tasa_base_entrenamiento'][1]['skill']:.4f}) refleja sobre todo que 2015-2019 fue más alcista.")
    else:
        frase = (f"{mb[0]} supera las tres referencias (skill {mb[1]['skill']:.4f}, t={mb[1]['t']:.1f} contra la tasa base de la ventana) con t por bloques de fechas; "
                 'falta confirmarlo en la prueba sellada y fuera de muestra.')
    return {'actualizado': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
            'repeticiones_entrenamiento': estado['repeticiones_train'], 'sesiones': estado['sesiones'],
            'validacion': {k: ev[k] for k in ('filas', 'fechas', 'activos', 'paso_dias', 'bloque_bootstrap', 'frecuencia_subida_ventana')},
            'metodo': 'conjunto fijo de validación idéntico en cada sesión; t = diferencia media de Brier / error estándar de bootstrap por bloques de fechas',
            'referencia_principal': REF_PRINCIPAL, 'umbral_t': umbral, 'por_referencia': por_ref,
            'pesos_hedge': pesos, 'frase': frase}


def fila_curva(estado, ev, fecha_hora=None):
    fila = {'fecha_hora': fecha_hora or dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'repeticiones_acumuladas': estado['repeticiones_train'], 'filas_validacion': ev['filas'], 'fechas_validacion': ev['fechas']}
    for rn in REFS_SKILL:
        fila['brier_ref_' + rn] = ev['brier_ref'][rn]
    for m in ['ensamble'] + TODOS:
        fila['brier_val_' + m] = ev['metodos'][REF_PRINCIPAL][m]['brier']
    for rn in REFS_SKILL:
        for m in ['ensamble'] + ENSAMBLE_MIEMBROS:
            v = ev['metodos'][rn][m]
            fila[f'skill_{rn}_{m}'] = v['skill']
            fila[f't_{rn}_{m}'] = v['t']
    return fila


def correr(out=OUT, n_train=500, n_val=None, semilla=0, carpeta_datos=PIT):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    pj = out / 'pesos.json'
    estado = json.loads(pj.read_text())['estado'] if pj.exists() else estado_inicial()
    estado.pop('val', None)  # acumulado antiguo (repeticiones muestreadas, t inflada): ya no se usa
    estado.setdefault('val_final', {})
    activos = cargar_activos(Path(carpeta_datos) / 'precios')
    activos['__eventos__'] = cargar_eventos(Path(carpeta_datos) / 'eventos.csv')
    rng = np.random.default_rng([semilla, estado['sesiones']])
    ev, X, Y = sesion(estado, activos, rng, n_train)
    consolidar = estado['sesiones'] % RETRAIN_CADA == 0 or not estado['logistica']
    pool = juntar_pool(out, X, Y, rng, consolidar)
    if pool is not None:
        reentrenar(estado, *pool)
    pesos = {str(h): pesos_hedge(estado['hedge'][str(h)]) for h in HORIZONTES}
    pj.write_text(json.dumps({'pesos': pesos, 'estado': estado}, sort_keys=True, separators=(',', ':')))
    res = resumen(estado, pesos)
    (out / 'resumen.json').write_text(json.dumps(res, indent=1, ensure_ascii=False, allow_nan=False))
    fila = fila_curva(estado, ev)
    curva = out / 'curva.csv'
    pd.DataFrame([fila]).to_csv(curva, mode='a', header=not curva.exists(), index=False)
    return fila


def rehacer_historia(destino, n_sesiones, semilla=0, n_train=500, carpeta_datos=PIT, horas=None):
    """Repite las sesiones 1..n con las mismas semillas y mide cada una con la validación corregida.

    Devuelve (estado final, filas de curva). `horas` conserva las marcas de tiempo originales."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    activos = cargar_activos(Path(carpeta_datos) / 'precios')
    activos['__eventos__'] = cargar_eventos(Path(carpeta_datos) / 'eventos.csv')
    estado, filas = estado_inicial(), []
    for k in range(n_sesiones):
        rng = np.random.default_rng([semilla, estado['sesiones']])
        ev, X, Y = sesion(estado, activos, rng, n_train, quemar_rng_val=200)
        consolidar = estado['sesiones'] % RETRAIN_CADA == 0 or not estado['logistica']
        pool = juntar_pool(destino, X, Y, rng, consolidar)
        if pool is not None:
            reentrenar(estado, *pool)
        filas.append(fila_curva(estado, ev, horas[k] if horas else None))
    return estado, filas


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--train', type=int, default=500)
    ap.add_argument('--val', type=int, default=None, help='obsoleto: la validación es un conjunto fijo')
    ap.add_argument('--semilla', type=int, default=0)
    ap.add_argument('--out', default=str(OUT))
    a = ap.parse_args()
    f = correr(a.out, a.train, a.val, a.semilla)
    print(json.dumps({k: (round(v, 5) if isinstance(v, float) else v) for k, v in f.items()
                      if k.startswith(('fecha', 'repet')) or (k.startswith(('skill_', 't_')) and k.endswith('_ensamble'))}, indent=1))
