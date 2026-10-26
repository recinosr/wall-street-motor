"""Gimnasio del Oráculo: miles de repeticiones diarias con datos point-in-time.

Entrenamiento 1990-2014 (aprende), validación 2015-2019 (solo mide), 2020 en adelante sellado: no se toca.
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
            'cal': {}, 'val': {}, 'logistica': {}}


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


def sesion(estado, activos, rng, n_train=500, n_val=200, ahora=None):
    """Una sesión: entrena n_train repeticiones (aprende) y mide n_val en validación (congelado)."""
    series = {s: construir(d, activos['__eventos__'], s) for s, d in activos.items() if s != '__eventos__'}
    el_tr = {s: elegibles(S, TRAIN) for s, S in series.items()}
    el_va = {s: elegibles(S, VAL) for s, S in series.items()}
    el_tr = {s: v for s, v in el_tr.items() if len(v)}
    el_va = {s: v for s, v in el_va.items() if len(v)}
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
    # Validación honesta: pesos y calibraciones congelados; nada se actualiza.
    pesos = {h: pesos_hedge(estado['hedge'][str(h)]) for h in HORIZONTES}
    perd = {m: [] for m in TODOS + ['ensamble']}
    for _ in range(n_val):
        s = list(el_va)[rng.integers(len(el_va))]
        S = series[s]
        i = int(rng.choice(el_va[s]))
        for h in HORIZONTES:
            y = bool(S['up'][h][i])
            preds = predecir(estado, S, i, h)
            preds['ensamble'] = ensamble(preds, pesos[h])
            for m, p in preds.items():
                perd[m].append((p - y) ** 2)
                v = estado['val'].setdefault(m, {}).setdefault(str(h), [0, 0., 0., 0.])
                dif = (preds['tasa_base'] - y) ** 2 - (p - y) ** 2
                v[0] += 1
                v[1] += (p - y) ** 2
                v[2] += dif
                v[3] += dif * dif
    estado['repeticiones_val'] += n_val
    estado['sesiones'] += 1
    brier = {m: float(np.mean(v)) if v else float('nan') for m, v in perd.items()}
    return brier, np.array(filas, dtype=np.float32), np.array(etiquetas, dtype=np.int8)


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
            z = np.load(f)
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
    filas = {}
    for m in TODOS + ['ensamble']:
        vs = estado['val'].get(m, {})
        n = sum(v[0] for v in vs.values())
        if not n:
            continue
        mb = sum(v[1] for v in vs.values()) / n
        vb = estado['val']['tasa_base']
        bb = sum(v[1] for v in vb.values()) / sum(v[0] for v in vb.values())
        dif = sum(v[2] for v in vs.values()) / n
        var = max(sum(v[3] for v in vs.values()) / n - dif * dif, 1e-12)
        filas[m] = {'skill': 1 - mb / bb, 'brier': mb, 't': dif / math.sqrt(var / n), 'n': n}
    cand = {m: v for m, v in filas.items() if m not in REFERENCIAS + ['ensamble']}
    top = sorted(cand.items(), key=lambda kv: -kv[1]['skill'])[:5]
    mejor = top[0] if top else None
    if mejor is None:
        frase = 'Sin datos de validación todavía.'
    elif mejor[1]['skill'] <= 0:
        frase = 'Ningún método supera la tasa base en validación 2015-2019: por ahora no hay ventaja demostrada.'
    elif mejor[1]['t'] < 2:
        frase = (f"El mejor método ({mejor[0]}) supera la tasa base por {mejor[1]['skill']:.4f} de skill, pero t={mejor[1]['t']:.1f}<2: "
                 'indistinguible de ruido (las repeticiones se solapan, la t es optimista).')
    else:
        frase = (f"{mejor[0]} supera la tasa base en validación (skill {mejor[1]['skill']:.4f}, t={mejor[1]['t']:.1f}); "
                 'falta confirmarlo en la prueba sellada y fuera de muestra, la t es optimista por solapamiento.')
    return {'actualizado': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
            'repeticiones_entrenamiento': estado['repeticiones_train'], 'repeticiones_validacion': estado['repeticiones_val'],
            'sesiones': estado['sesiones'],
            'top5_skill_validacion': [{'metodo': m, **v} for m, v in top],
            'ensamble_validacion': filas.get('ensamble'), 'tasa_base_brier_validacion': filas.get('tasa_base', {}).get('brier'),
            'pesos_hedge': pesos, 'frase': frase}


def correr(out=OUT, n_train=500, n_val=200, semilla=0, carpeta_datos=PIT):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    pj = out / 'pesos.json'
    estado = json.loads(pj.read_text())['estado'] if pj.exists() else estado_inicial()
    activos = cargar_activos(Path(carpeta_datos) / 'precios')
    activos['__eventos__'] = cargar_eventos(Path(carpeta_datos) / 'eventos.csv')
    rng = np.random.default_rng([semilla, estado['sesiones']])
    brier, X, Y = sesion(estado, activos, rng, n_train, n_val)
    consolidar = estado['sesiones'] % RETRAIN_CADA == 0 or not estado['logistica']
    pool = juntar_pool(out, X, Y, rng, consolidar)
    if pool is not None:
        reentrenar(estado, *pool)
    pesos = {str(h): pesos_hedge(estado['hedge'][str(h)]) for h in HORIZONTES}
    pj.write_text(json.dumps({'pesos': pesos, 'estado': estado}, sort_keys=True, separators=(',', ':')))
    res = resumen(estado, pesos)
    (out / 'resumen.json').write_text(json.dumps(res, indent=1, ensure_ascii=False, allow_nan=False))
    bb = brier['tasa_base']
    fila = {'fecha_hora': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'repeticiones_acumuladas': estado['repeticiones_train'], 'brier_val_tasa_base': bb}
    for m in ['ensamble'] + TODOS:
        fila['brier_val_' + m] = brier[m]
    for m in ['ensamble'] + TODOS:
        fila['skill_val_' + m] = 1 - brier[m] / bb
    curva = out / 'curva.csv'
    pd.DataFrame([fila]).to_csv(curva, mode='a', header=not curva.exists(), index=False)
    return fila


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--train', type=int, default=500)
    ap.add_argument('--val', type=int, default=200)
    ap.add_argument('--semilla', type=int, default=0)
    ap.add_argument('--out', default=str(OUT))
    a = ap.parse_args()
    f = correr(a.out, a.train, a.val, a.semilla)
    print(json.dumps({k: (round(v, 5) if isinstance(v, float) else v) for k, v in f.items() if k.startswith(('fecha', 'repet', 'skill'))}, indent=1))
