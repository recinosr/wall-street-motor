"""Núcleo puro: vistas por cierre, etiquetas maduras y parámetros mensuales.

No importa archivos, red ni el recolector. Las estrategias solo reciben copias
del pasado. Los retornos objetivo se construyen por índices, fuera de indicadores.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

HORIZONTES = (1, 5, 21, 63)
INICIOS = {'VT': '2008-06-24', 'CSPX.L': '2010-05-19', 'MTUM': '2013-04-16',
           'IBIT': '2024-01-11', 'BTC-USD': '2014-09-17', 'ETH-USD': '2015-08-07'}
METODOS = ('ingenuo', 'caminata', 'base_5a', 'momentum_12_1', 'momentum_6m',
           'serie_tiempo', 'media_10m', 'supertrend', 'donchian', 'volatilidad',
           'vix', 'valuacion', 'volumen', 'logistica', 'ensamble')


class Vista(dict):
    def __init__(self):
        super().__init__()
        self.tablas = {}


class Boveda:
    def __init__(self, datos_completos):
        self.__datos = {}
        for sim, frame in datos_completos.items():
            d = frame.copy(deep=True)
            d.index = pd.DatetimeIndex(pd.to_datetime(d.index, utc=True)).tz_localize(None).normalize()
            if d.index.has_duplicates or not d.index.is_monotonic_increasing:
                raise ValueError('Fechas duplicadas o desordenadas')
            self.__datos[sim] = d

    def ver(self, hasta):
        t = pd.Timestamp(hasta).normalize()
        out = Vista()
        for sim, d in self.__datos.items():
            if t < pd.Timestamp(INICIOS.get(sim, '1900-01-01')):
                continue
            view = d.loc[d.index <= t].copy(deep=True)
            if 'filed' in view:
                # Sin hora de publicación, disponible desde el día SIGUIENTE.
                view = view.loc[pd.to_datetime(view.filed) < t].copy(deep=True)
            if len(view):
                out[sim] = view
        return out


def indicadores(d, cripto=False):
    c = d.close
    m, a = (30, 365) if cripto else (21, 252)
    r = c.pct_change(fill_method=None)
    x = pd.DataFrame({'r1': r, 'r5': c.pct_change(5, fill_method=None),
                      'mom': c.shift(m)/c.shift(a)-1,
                      'vol': r.rolling(20).std(), 'dist': c/c.rolling(200).mean()-1}, index=d.index)
    x['momentum_12_1'] = np.sign(x.mom)
    x['momentum_6m'] = np.sign(c/c.shift(6*m)-1)
    x['serie_tiempo'] = np.sign(c/c.shift(a)-1)
    # Faber: promedio de 10 cierres mensuales ya terminados; el mes actual no entra.
    monthly = c.resample('ME').last().rolling(10).mean()
    known = monthly.shift(1)
    month_keys = d.index.to_period('M')
    sma = pd.Series(known.to_numpy(), index=known.index.to_period('M'))
    x['media_10m'] = np.sign(c.to_numpy()/sma.reindex(month_keys).to_numpy()-1)
    volmedian = x.vol.expanding(min_periods=60).median()
    x['volatilidad'] = (x.vol > volmedian).astype(float).where(volmedian.notna())
    direction = np.sign(c-d.open)
    x['volumen'] = direction*d.volume/d.volume.rolling(20).mean().replace(0, np.nan)
    x['donchian'] = np.sign(c/(d.high.rolling(20).max().shift(1)+d.low.rolling(20).min().shift(1))*2-1)
    if cripto:
        prev = c.shift(1)
        tr = pd.concat([d.high-d.low, (d.high-prev).abs(), (d.low-prev).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=.1, adjust=False, min_periods=10).mean()
        mid = (d.high+d.low)/2
        upper = (mid+3*atr).to_numpy(copy=True); lower = (mid-3*atr).to_numpy(copy=True)
        prices = c.to_numpy(); trend = np.full(len(c), np.nan)
        for i in range(10, len(c)):
            if np.isfinite(upper[i-1]):
                if prices[i-1] <= upper[i-1]: upper[i] = min(upper[i], upper[i-1])
                if prices[i-1] >= lower[i-1]: lower[i] = max(lower[i], lower[i-1])
            old = trend[i-1] if np.isfinite(trend[i-1]) else 1
            trend[i] = 1 if prices[i] > upper[i-1] else -1 if prices[i] < lower[i-1] else old
        x['supertrend'] = trend
    return x


def tabla(vista, sim):
    if isinstance(vista, Vista) and sim in vista.tablas:
        return vista.tablas[sim]
    d = vista[sim]
    x = indicadores(d, sim.endswith('-USD'))
    # Series exógenas disponibles al cierre; nunca completar usando la siguiente fecha.
    if '^VIX' in vista:
        # Cierre VIX de AYER: también era conocido al cierre anterior de Londres.
        v = vista['^VIX'].close.shift(1).reindex(d.index, method='ffill')
        x['vix'] = (v > v.expanding(min_periods=60).median()).astype(float).where(v.notna())
    if 'CAPE' in vista:
        # CAPE y diferencial han de ser vintages con filed, filtrados por Boveda.
        f = vista['CAPE'].sort_values('filed')
        if {'filed', 'cape', 'spread'} <= set(f.columns):
            pub = pd.to_datetime(f.filed).dt.normalize()+pd.Timedelta(days=1)
            values = pd.Series(1/f.cape.to_numpy()-f.spread.to_numpy(), index=pub)
            values = values[~values.index.duplicated(keep='last')]
            x['valuacion'] = values.reindex(d.index, method='ffill')
    if isinstance(vista, Vista): vista.tablas[sim] = x
    return x


class Pronosticador:
    """Ajuste expansivo una vez por mes/horizonte, sin elegir hiperparámetros."""
    def __init__(self, sim, horizonte):
        if horizonte not in HORIZONTES: raise ValueError('Horizonte inválido')
        self.sim, self.h = sim, horizonte
        self.mes = None
        self.model = None
        self.buckets = {}

    def ajustar(self, vista):
        d = vista[self.sim]; x = tabla(vista, self.sim); h = self.h
        if len(d) < 300+h: return False
        # Solo etiquetas cuyo cierre final está en esta vista.
        ret = d.close.to_numpy()[h:]/d.close.to_numpy()[:-h]-1
        dates = d.index[:-h]; train = x.iloc[:-h]
        self.base = ret[np.isfinite(ret)]
        if len(self.base) < 120: return False
        self.base5 = ret[(dates >= d.index[-1]-pd.DateOffset(years=5)) & np.isfinite(ret)]
        self.buckets = {}
        for name in METODOS:
            if name not in x or (name == 'valuacion' and h < 63): continue
            if name in ('supertrend', 'donchian') and not self.sim.endswith('-USD'): continue
            vals = train[name].to_numpy()
            if name in ('volumen', 'valuacion'):
                valid = vals[np.isfinite(vals)]
                if len(valid) < 120: continue
                cuts = np.quantile(valid, [1/3, 2/3])
                groups = np.digitize(vals, cuts)
            else:
                cuts = None; groups = vals
            buckets = {float(g): ret[(groups == g) & np.isfinite(vals) & np.isfinite(ret)]
                       for g in np.unique(groups[np.isfinite(vals)])}
            self.buckets[name] = (cuts, buckets)
        cols = ['r1', 'r5', 'mom', 'vol', 'dist']
        tx = train[cols].to_numpy(); valid = np.isfinite(tx).all(axis=1) & np.isfinite(ret)
        y = ret[valid] > 0
        self.model = None
        if valid.sum() >= 120 and len(np.unique(y)) == 2:
            self.model = make_pipeline(StandardScaler(), LogisticRegression(C=.1, max_iter=300))
            self.model.fit(tx[valid], y.astype(int))
        self.fit_date = d.index[-1].date().isoformat()
        self.label_date = d.index[-1].date().isoformat()
        self.constantes = {'ingenuo': self.distribucion(self.base), 'base_5a': self.distribucion(self.base5),
                           'caminata': self.distribucion(np.r_[self.base, -self.base], .5)}
        self.condicionales = {name: {g: self.distribucion(r) for g, r in buckets.items() if len(r) >= 60}
                              for name, (_, buckets) in self.buckets.items()}
        self.mes = d.index[-1].strftime('%Y-%m')
        return True

    @staticmethod
    def distribucion(r, probability=None):
        return {'p_sube': float(np.clip(np.mean(r > 0) if probability is None else probability, .001, .999)),
                'p10': float(np.quantile(r, .1)), 'p90': float(np.quantile(r, .9)), 'n_ajuste': len(r)}

    def pronosticar(self, vista):
        if self.sim not in vista: return {}
        d = vista[self.sim]
        if not np.isfinite(d.close.iloc[-1]) or d.close.iloc[-1] <= 0: return {}
        if self.mes != d.index[-1].strftime('%Y-%m'):
            # La extensión semanal debe usar exactamente el mismo ajuste del mes
            # que una corrida continua, aunque empiece a mitad del mes.
            month = d.index[-1].to_period('M')
            candidates = d.index[(d.index.to_period('M') == month) & (d.index.weekday < 5) & d.close.notna()]
            if not len(candidates): return {}
            fit_view = Boveda(vista).ver(candidates[0])
            if not self.ajustar(fit_view): return {}
        last = tabla(vista, self.sim).iloc[-1]
        out = {k: dict(v) for k, v in self.constantes.items()}
        for name, (cuts, buckets) in self.buckets.items():
            value = last.get(name, np.nan)
            if not np.isfinite(value): continue
            group = float(np.digitize(value, cuts)) if cuts is not None else float(value)
            value = self.condicionales[name].get(group)
            if value is not None: out[name] = dict(value)
        cols = ['r1', 'r5', 'mom', 'vol', 'dist']
        if self.model is not None and np.isfinite(last[cols]).all():
            p = self.model.predict_proba(last[cols].to_numpy().reshape(1, -1))[0, 1]
            out['logistica'] = {**self.constantes['ingenuo'], 'p_sube': float(np.clip(p, .001, .999))}
        families = {'momentum': ['momentum_12_1', 'momentum_6m', 'serie_tiempo'],
                    'tendencia': ['media_10m', 'supertrend', 'donchian'],
                    'regimen': ['volatilidad', 'vix'], 'valuacion': ['valuacion'],
                    'volumen': ['volumen'], 'combinado': ['logistica']}
        used = {f: [k for k in keys if k in out] for f, keys in families.items()}
        used = {f: keys for f, keys in used.items() if keys}
        members = [{k: float(np.mean([out[name][k] for name in keys])) for k in ('p_sube', 'p10', 'p90')}
                   for keys in used.values()]
        if members:
            out['ensamble'] = {k: float(np.mean([v[k] for v in members])) for k in ('p_sube', 'p10', 'p90')}
            out['ensamble']['miembros'] = used
        for value in out.values():
            value['ajuste_hasta'] = self.fit_date
            value['etiquetas_hasta'] = self.label_date
        return out
