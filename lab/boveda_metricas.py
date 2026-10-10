"""Calificación apareada; bootstrap circular de bloques, familia BH global."""
import math
import numpy as np


def wilson(w, n):
    if not n: return None
    p = w/n; z = 1.96; den = 1+z*z/n
    delta = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))
    return [(p+z*z/(2*n)-delta)/den, (p+z*z/(2*n)+delta)/den]


def bootstrap(d, h, repetitions=999):
    """H0 centrada de diferencia Brier base − método; prueba unilateral fijada."""
    d = np.asarray(d, float); n = len(d); length = max(21, 2*h)
    if n < 3*length: return {'p': 1., 'ic95': None, 'bloque': length, 'replicas': repetitions}
    rng = np.random.default_rng(20261010)
    ext = np.r_[d, d[:length-1]]
    sums = np.convolve(ext, np.ones(length), 'valid')[:n]
    k, rem = divmod(n, length)
    starts = rng.integers(0, n, (repetitions, k))
    totals = sums[starts].sum(axis=1)
    if rem:
        tail = np.convolve(np.r_[d, d[:rem-1]], np.ones(rem), 'valid')[:n]
        totals += tail[rng.integers(0, n, repetitions)]
    draws = totals/n
    # Sin asumir días independientes ni comparar bootstrap sin centrar con cero.
    p = (1+np.count_nonzero(draws-d.mean() >= d.mean()))/(repetitions+1)
    return {'p': float(p), 'ic95': np.quantile(draws, [.025, .975]).tolist(),
            'bloque': length, 'replicas': repetitions}


def metricas(rows, h, inference=True):
    if not rows: return None
    p = np.array([r['p_sube'] for r in rows]); y = np.array([r['y'] for r in rows])
    b = np.array([r['base'] for r in rows]); ret = np.array([r['retorno'] for r in rows])
    loss = (p-y)**2; bl = (b-y)**2
    wins = ((p >= .5) == y).sum(); basewins = ((b >= .5) == y).mean()
    bins = []
    for i in range(10):
        mask = (p >= i/10) & (p < (i+1)/10)
        bins.append({'decil': i, 'n': int(mask.sum()),
                     'probabilidad': float(p[mask].mean()) if mask.any() else None,
                     'frecuencia': float(y[mask].mean()) if mask.any() else None,
                     'ic95': wilson(int(y[mask].sum()), int(mask.sum())) if mask.any() else None})
    low = np.array([r['p10'] for r in rows]); high = np.array([r['p90'] for r in rows])
    out = {'n': len(rows), 'brier': float(loss.mean()), 'brier_ingenuo': float(bl.mean()),
           'habilidad': float(1-loss.mean()/bl.mean()) if bl.mean() > 0 else None,
           'log_loss': float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p))),
           'log_loss_ingenuo': float(-np.mean(y*np.log(b)+(1-y)*np.log1p(-b))),
           'acierto': float(wins/len(rows)), 'acierto_ingenuo': float(basewins),
           'diferencia_acierto_pp': float(100*(wins/len(rows)-basewins)),
           'ic95_wilson_descriptivo': wilson(int(wins), len(rows)),
           'cobertura': float(np.mean((ret >= low) & (ret <= high))), 'calibracion': bins}
    if inference: out.update(bootstrap(bl-loss, h))
    return out


def resumir(records):
    result = []; groups = {}
    for r in records:
        groups.setdefault((r['periodo'], r['sim'], r['horizonte'], r['metodo']), []).append(r)
    for (period, sim, h, method), rows in sorted(groups.items()):
        m = metricas(rows, h); stability = {}
        for label, condition in [('2000s', lambda y: y < 2010), ('2010s', lambda y: 2010 <= y < 2020),
                                 ('2020s', lambda y: y >= 2020), ('2008', lambda y: y == 2008),
                                 ('2020', lambda y: y == 2020), ('2022', lambda y: y == 2022)]:
            subset = [r for r in rows if condition(int(r['fecha'][:4]))]
            if subset: stability[label] = metricas(subset, h, False)
        positive = [s['habilidad'] > 0 for s in stability.values() if s['habilidad'] is not None]
        result.append(dict(periodo=period, sim=sim, horizonte=h, metodo=method, **m,
                           estabilidad=stability, inestable=bool(positive and any(positive) and not all(positive))))
    # Incluye controles y ambos períodos: una sola familia de TODAS las celdas evaluadas.
    ranked = sorted(enumerate(result), key=lambda v: v[1]['p']); q = 1.; total = len(ranked)
    for rank in range(total, 0, -1):
        _, row = ranked[rank-1]; q = min(q, row['p']*total/rank); row['q_bh'] = q
        row['ventaja'] = bool(row['habilidad'] is not None and row['habilidad'] > 0 and q < .05)
    return result
