"""Pronósticos puros del examen: reciben exclusivamente una Vista de la bóveda.

Horizontes en días naturales, objetivo en la primera sesión >= T+h. Ajustes
solo con objetivos conocidos y anteriores a 2019. Sin selección en validación.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from lab.boveda import tabla

HORIZONTES = (30, 60, 90, 1000)
BASE = ('ingenuo', 'caminata', 'base_5a', 'momentum_12_1', 'momentum_6m',
        'serie_tiempo', 'media_10m', 'supertrend', 'donchian', 'volatilidad',
        'vix', 'volumen', 'logistica', 'ensamble')
NUEVOS = ('boosting', 'regimen', 'entre_activos', 'estacionalidad', 'analogos', 'ponderado')
FACTORES = (1., .25, .5, .1, .05)
RONDAS = (BASE, NUEVOS, *(tuple(m+'_mezcla'+str(int(f*100)) for m in NUEVOS) for f in FACTORES[1:]))
EXOGENAS = ('DX-Y.NYB', 'HYG', 'LQD', 'GLD', 'HG=F')
COLS = ['r1', 'r5', 'mom', 'vol', 'dist']


def variables(vista, sim):
    d = vista[sim]; x = tabla(vista, sim).copy()
    # Cierres del día anterior, incluso cuando el mercado destino cierra antes.
    for s in EXOGENAS:
        if s in vista:
            c = vista[s].close
            r = (c/c.shift(21)-1)
            r.index = r.index+pd.Timedelta(days=1)
            x['externa_'+s] = r.reindex(d.index, method='ffill')
    if 'externa_HYG' in x and 'externa_LQD' in x:
        x['credito'] = x['externa_HYG']-x['externa_LQD']
    if 'externa_GLD' in x and 'externa_HG=F' in x:
        x['oro_cobre'] = x['externa_GLD']-x['externa_HG=F']
    x['mes'] = d.index.month.astype(float)
    x['electoral'] = (d.index.year % 4).astype(float)
    # Calendario conocido: nada de fechar hoy halvings futuros de aquella fecha.
    halvings = pd.to_datetime(['2012-11-28', '2016-07-09', '2020-05-11'])
    phase = np.full(len(d), np.nan)
    if sim.endswith('-USD'):
        for t in halvings:
            mask = d.index >= t
            phase[mask] = np.minimum((d.index[mask]-t).days/365., 4.)
    x['halving'] = phase
    return x


def etiquetas(d, h):
    """Etiquetas de trayectorias completas en ESTA vista; no se llena un hueco."""
    c, high, low = (d[k].to_numpy(float) for k in ('close', 'high', 'low'))
    targets = d.index.searchsorted(d.index+pd.Timedelta(days=h))
    ret = np.full(len(d), np.nan); peak = ret.copy(); trough = ret.copy()
    for i, j in enumerate(targets):
        if j >= len(d) or d.index[j] >= pd.Timestamp('2019-01-01'): continue
        # T también está dentro del período de entrenamiento (2005–2018).
        if d.index[i] < pd.Timestamp('2005-01-01'): continue
        if not np.isfinite(c[i:j+1]).all() or not np.isfinite(high[i+1:j+1]).all() or not np.isfinite(low[i+1:j+1]).all(): continue
        if c[i] <= 0: continue
        ret[i] = c[j]/c[i]-1
        peak[i] = np.max(high[i+1:j+1])/c[i]-1
        trough[i] = np.min(low[i+1:j+1])/c[i]-1
    return ret, peak, trough, targets


def distribucion(r, peak, trough, p=None):
    return {'p_sube': float(np.clip(np.mean(r > 0) if p is None else p, .001, .999)),
            'retorno_esperado': float(np.mean(r)), 'p10': float(np.quantile(r, .1)),
            'p90': float(np.quantile(r, .9)), 'maximo_esperado': float(np.mean(peak)),
            'minimo_esperado': float(np.mean(trough)), 'n_ajuste': len(r)}


class MotorExamen:
    def __init__(self, sim, h):
        if h not in HORIZONTES: raise ValueError('Horizonte inválido')
        self.sim, self.h = sim, h; self.cache = None

    def ajustar(self, vista):
        d = vista[self.sim].loc[:'2018-12-31']
        if len(d) < 300: return False
        x = variables(vista, self.sim).reindex(d.index)
        ret, peak, trough, target = etiquetas(d, self.h)
        valid = np.isfinite(ret)
        if valid.sum() < 120: return False
        self.d, self.x, self.ret, self.peak, self.trough = d, x, ret, peak, trough
        self.valid = valid
        self.constants = {'ingenuo': self.dist(valid)}
        recent = valid & (d.index >= d.index[-1]-pd.DateOffset(years=5))
        if recent.sum() >= 60: self.constants['base_5a'] = self.dist(recent)
        # Caminata simétrica también en extremos: reflejar trayectoria intercambia picos.
        self.constants['caminata'] = distribucion(np.r_[ret[valid], -ret[valid]],
            np.r_[peak[valid], -trough[valid]], np.r_[trough[valid], -peak[valid]], .5)
        self.buckets = {}
        for name in BASE:
            if name not in x: continue
            if name in ('supertrend', 'donchian') and not self.sim.endswith('-USD'): continue
            values = x[name].to_numpy(); mask = valid & np.isfinite(values)
            if mask.sum() < 120: continue
            cuts = np.quantile(values[mask], [1/3, 2/3]) if name == 'volumen' else None
            groups = np.digitize(values, cuts) if cuts is not None else values
            self.buckets[name] = (cuts, {float(g): self.dist(mask & (groups == g))
                for g in np.unique(groups[mask]) if (mask & (groups == g)).sum() >= 60})
        self.models = {}; self.modelcols = {}
        external = [c for c in ('externa_DX-Y.NYB', 'credito', 'oro_cobre') if c in x]
        sets = {'logistica': COLS, 'boosting': COLS,
                'entre_activos': COLS+external if external else [],
                'estacionalidad': COLS+['mes', 'electoral']+(['halving'] if self.sim.endswith('-USD') else [])}
        for name, cols in sets.items():
            if not cols: continue
            mask = valid & np.isfinite(x[cols].to_numpy()).all(axis=1)
            if mask.sum() < 120 or len(np.unique(ret[mask] > 0)) < 2: continue
            if name == 'boosting':
                model = GradientBoostingClassifier(n_estimators=30, max_depth=2,
                    min_samples_leaf=60, learning_rate=.05, random_state=21)
            else: model = make_pipeline(StandardScaler(), LogisticRegression(C=.1, max_iter=500))
            model.fit(x.loc[mask, cols].to_numpy(), (ret[mask] > 0).astype(int))
            self.models[name], self.modelcols[name] = model, cols
        # Umbrales exclusivamente del ajuste maduro.
        self.volcut = float(np.nanmedian(x.loc[valid, 'vol']))
        self.regimes = {}
        groups = (x.vol.to_numpy() > self.volcut).astype(int)*2+(x.dist.to_numpy() > 0)
        mask = valid & np.isfinite(x[['vol', 'dist']]).all(axis=1).to_numpy()
        for g in range(4):
            use = mask & (groups == g)
            if use.sum() >= 60: self.regimes[g] = self.dist(use)
        self.shapes = self.formas(d.close)
        self.shapevalid = valid & np.isfinite(self.shapes).all(axis=1)
        self.ajuste_hasta = d.index[-1].date().isoformat()
        self.etiquetas_hasta = d.index[target[valid].max()].date().isoformat()
        self.cache = self.ajuste_hasta
        return True

    def dist(self, mask):
        return distribucion(self.ret[mask], self.peak[mask], self.trough[mask])

    @staticmethod
    def formas(close):
        # Forma acumulada de los últimos 60 días/sesiones, escala por vol local.
        c = close.to_numpy(float); out = np.full((len(c), 60), np.nan)
        for i in range(59, len(c)):
            path = c[i-59:i+1]
            if np.isfinite(path).all() and (path > 0).all():
                logpath = np.log(path/path[0]); scale = max(np.std(np.diff(logpath)), .00001)
                out[i] = logpath/scale
        return out

    def pronosticar(self, vista, pesos=None):
        if self.sim not in vista: return {}
        d = vista[self.sim]
        cutoff = min(d.index[-1], pd.Timestamp('2018-12-31'))
        # Ajuste mensual desde la primera sesión ya observada del mes.
        fit = d.index[d.index.to_period('M') == cutoff.to_period('M')][0] if cutoff.year < 2019 and d.index[-1].year < 2019 else pd.Timestamp('2018-12-31')
        t = fit.date().isoformat()
        # En diciembre2018 puede no haber sesión el31; clave efectiva, no fecha ficticia.
        t = d.loc[:fit].index[-1].date().isoformat()
        if self.cache != t:
            trainview = {s: frame.loc[:fit].copy() for s, frame in vista.items()}
            if not self.ajustar(trainview): return {}
        last = variables(vista, self.sim).iloc[-1]
        if not np.isfinite(d.close.iloc[-1]) or d.close.iloc[-1] <= 0: return {}
        out = {k: dict(v) for k, v in self.constants.items()}
        for name, (cuts, groups) in self.buckets.items():
            v = last.get(name, np.nan)
            if np.isfinite(v):
                g = float(np.digitize(v, cuts)) if cuts is not None else float(v)
                if g in groups: out[name] = dict(groups[g])
        for name, model in self.models.items():
            cols = self.modelcols[name]
            if np.isfinite(last[cols]).all():
                p = model.predict_proba(last[cols].to_numpy().reshape(1, -1))[0, 1]
                out[name] = {**self.constants['ingenuo'], 'p_sube': float(np.clip(p, .001, .999))}
        if np.isfinite(last[['vol', 'dist']]).all():
            group = int(last.vol > self.volcut)*2+int(last.dist > 0)
            if group in self.regimes: out['regimen'] = dict(self.regimes[group])
        shape = self.formas(d.close.iloc[-60:])[-1]
        if self.shapevalid.sum() >= 60 and np.isfinite(shape).all():
            indices = np.flatnonzero(self.shapevalid)
            # 60 vecinos fijados de antemano; jamás trayectorias inmaduras.
            nearest = indices[np.argsort(np.mean((self.shapes[indices]-shape)**2, axis=1), kind='stable')[:60]]
            mask = np.zeros(len(self.ret), bool); mask[nearest] = True
            out['analogos'] = self.dist(mask)
        families = (('momentum_12_1', 'momentum_6m', 'serie_tiempo'),
                    ('media_10m', 'supertrend', 'donchian'), ('volatilidad', 'vix'), ('volumen',), ('logistica',))
        available = [[m for m in f if m in out] for f in families]
        available = [f for f in available if f]
        if available:
            out['ensamble'] = self.mix(out, {m: 1/len(f) for f in available for m in f})
        if pesos:
            members = {m: w for m, w in pesos.items() if m in out and w > 0 and m != 'ponderado'}
            if members: out['ponderado'] = self.mix(out, members)
        for name in NUEVOS:
            if name in out:
                for f in FACTORES[1:]:
                    out[name+'_mezcla'+str(int(f*100))] = self.mix(out, {name: f, 'ingenuo': 1-f})
        for value in out.values():
            value['ajuste_hasta'] = self.ajuste_hasta
            value['etiquetas_hasta'] = self.etiquetas_hasta
        return out

    @staticmethod
    def mix(out, weights):
        keys = ('p_sube', 'retorno_esperado', 'p10', 'p90', 'maximo_esperado', 'minimo_esperado')
        total = sum(weights.values())
        return {**{k: float(sum(out[m][k]*w for m, w in weights.items())/total) for k in keys},
                'miembros': {m: w/total for m, w in weights.items()}}
