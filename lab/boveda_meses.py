"""Diario causal de meses. Solo este núcleo pronostica; no importa recolectores.

Las probabilidades diarias son close/close anterior, incluso en modo A (no
retornos acumulados desde T). A congela los rasgos en T; B actualiza con ayer.
Los modelos estadísticos se ajustan anualmente con etiquetas maduras hasta
min(fin del año anterior, 2018). No se selecciona por validación ni por reserva.
"""
import hashlib
from functools import lru_cache
import numpy as np
import pandas as pd
import exchange_calendars as xc
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .boveda import indicadores

ETF = tuple(('SPY QQQ VT IWM EEM VTI VOO IVV DIA MDY IJH IJR VB VO VV '
 'VUG VTV IWF IWD IWO IWN IWP IWS VBR VBK VOT VOE RSP SDY DVY VIG '
 'SCHD DGRO QUAL MTUM USMV VLUE SPLV SPHQ DSI DBC USO SLV '
 'XLB XLE XLF XLI XLK XLP XLU XLV XLY XLRE IYT VGT VHT VFH VDE '
 'VIS VDC VCR VAW VOX VNQ IYR ICF ITB XHB XBI IBB SMH SOXX '
 'EFA VEA VWO EWJ EWG EWU EWC EWA EWH EWS EWT EWY EWM EWW EWZ '
 'EZA EWP EWI EWL EWD EWN TLT IEF SHY AGG TIP LQD GLD').split())
ASSETS = ETF + ('BTC-USD', 'ETH-USD')
METHODS = ('moneda', 'azar', 'momentum', 'tendencia', 'volatilidad',
           'logistica', 'boosting', 'ensamble', 'calendario')
MODES = ('A_primero', 'A_azar', 'B_primero', 'B_azar')
EFFECTS = ('lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'cambio_mes',
           'pre_feriado', 'fomc', 'pre_fomc', 'tercer_viernes',
           'cuarto_miercoles', 'primer_dia', 'sell_may', 'halloween')
COLS = ['r1', 'r5', 'mom', 'vol', 'dist']
CONFIG = dict(version=2, desde='2006-01', hasta='2026-09', semilla=20261012,
    metodos=METHODS, modos=MODES, etf=ETF, cripto_desde='2015-01-01',
    ajuste='anual expansivo, solo etiquetas maduras, techo2018',
    boosting='21B:30 árboles, profundidad2, hoja60, learning_rate.05',
    logistica='21B:C=.1, escalado solo entrenamiento',
    calendario='frecuencia condicional fija; mínimo60, vuelve a moneda si insuficiente',
    inferencia='bloques circulares de6 meses;9999 réplicas; activos juntos',
    reserva='consumida en21;2024–2026 exploratorio, NO nuevo examen independiente',
    universo='100 ETFs actuales; sesgo de selección de fondos supervivientes explícito; sin acciones',
    objetivo='precio sin dividendos/costos; subida estricta >0; cero cuenta como no sube',
    rango='bootstrap histórico de retornos log diarios: suma de bloques5, deriva por probabilidad; no OHLC',
    seleccion='ninguna selección de métodos por resultados; ganador mensual descriptivo por Brier',
    fuentes='precios retrospectivos Yahoo; calendario XNYS retrospectivo, sin vintages')


def seed(*parts):
    return int.from_bytes(hashlib.sha256('|'.join(map(str, parts)).encode()).digest()[:8], 'little')


@lru_cache(maxsize=4)
def _calendario(fomc):
    """Calendario independiente de precios y de elegibilidad futura del proveedor."""
    cal = xc.get_calendar('XNYS', start='2003-01-01', end='2027-12-31')
    sessions = cal.sessions
    idx = pd.date_range('2003-01-01', '2027-12-31')
    positions = sessions.to_series().groupby(sessions.to_period('M')).cumcount()
    reverse = sessions.to_series().groupby(sessions.to_period('M')).cumcount(ascending=False)
    p = positions.reindex(idx).to_numpy(); last = reverse.reindex(idx).to_numpy()
    f = pd.DatetimeIndex(pd.to_datetime(list(fomc)))
    pref = {sessions[sessions.searchsorted(t)-1] for t in f if t > sessions[0]}
    # Un feriado es día lunes–viernes cerrado; no confundir todo viernes con víspera.
    holidays = set(pd.bdate_range(sessions.min(), sessions.max()))-set(sessions)
    preholiday = {sessions[sessions.searchsorted(t)-1] for t in holidays if t > sessions[0]}
    flags = [(idx.weekday == k) for k in range(5)]
    flags += [(p < 3) | (last == 0), idx.isin(preholiday), idx.isin(f), idx.isin(pref),
              (idx.weekday == 4) & (idx.day >= 15) & (idx.day <= 21),
              (idx.weekday == 2) & (idx.day >= 22) & (idx.day <= 28), p == 0,
              (idx.month >= 5) & (idx.month <= 10), (idx.month >= 11) | (idx.month <= 4)]
    return pd.DataFrame(np.array(flags).T.astype(float), index=idx, columns=EFFECTS)


def calendario(index, fomc=()):
    return _calendario(tuple(fomc)).reindex(pd.DatetimeIndex(index)).copy()


class VistaMes(pd.DataFrame):
    _metadata = ['rasgos', 'bases']
    @property
    def _constructor(self):
        return VistaMes


class BovedaMes:
    def __init__(self, frame, crypto=False):
        self.__d = frame.copy(deep=True)
        self.__x = indicadores(self.__d, crypto)
        r = self.__d.close.pct_change(fill_method=None)
        self.__base = (r>0).astype(float).where(r.notna()).rolling('1826D', min_periods=60).mean()

    def ver(self, before):
        mask = self.__d.index < pd.Timestamp(before)
        out = VistaMes(self.__d.loc[mask].copy(deep=True))
        out.rasgos = self.__x.loc[mask].copy(deep=True)
        out.bases = self.__base.loc[mask].copy(deep=True)
        return out


def features(past):
    return past.rasgos if isinstance(past, VistaMes) else indicadores(past, False)


class MotorMes:
    """Recibe únicamente una copia de pasado para ajustar o pronosticar."""
    def __init__(self, sim, past, fomc=()):
        self.sim = sim
        self.crypto = sim.endswith('-USD')
        d = past.loc[:'2018-12-31'].copy()
        if len(d) < 300:
            raise ValueError('Sin300 cierres de contexto; abstención')
        x = past.rasgos.reindex(d.index) if isinstance(past, VistaMes) else indicadores(d, self.crypto)
        r = d.close.shift(-1)/d.close-1
        good = np.isfinite(r) & (d.close > 0) & (d.close.shift(-1) > 0)
        self.buckets = {}
        self.models = {}
        self.ajuste_hasta = d.index[-1].date().isoformat()
        self.etiquetas_hasta = d.index[np.flatnonzero(good)[-1]+1].date().isoformat()
        for col in ('momentum_12_1', 'media_10m', 'volatilidad'):
            self.buckets[col] = {float(v): float((r[good & (x[col] == v)] > 0).mean())
                for v in x[col].dropna().unique() if (good & (x[col] == v)).sum() >= 60}
        flags = calendario(d.index, fomc)
        self.calp = {c: float((r[good & (flags[c].shift(-1) == 1)] > 0).mean())
            for c in EFFECTS if (good & (flags[c].shift(-1) == 1)).sum() >= 60}
        valid = good & np.isfinite(x[COLS]).all(axis=1)
        if valid.sum() >= 120 and (r[valid] > 0).nunique() == 2:
            self.models = {
                'logistica': make_pipeline(StandardScaler(), LogisticRegression(C=.1, max_iter=500)),
                'boosting': GradientBoostingClassifier(n_estimators=30, max_depth=2,
                    min_samples_leaf=60, learning_rate=.05, random_state=21)}
            for model in self.models.values():
                model.fit(x.loc[valid, COLS].to_numpy(), (r[valid] > 0).astype(int))

    def pronosticar(self, past, targets, mode, fomc=()):
        if past.index[-1] >= pd.Timestamp(targets[0]) and mode.startswith('A'):
            raise ValueError('El contexto debe terminar antes del primer objetivo')
        xall = past.rasgos if isinstance(past, VistaMes) else indicadores(past, self.crypto)
        if isinstance(past, VistaMes):
            bases = past.bases
        else:
            r = past.close.pct_change(fill_method=None)
            bases = (r>0).astype(float).where(r.notna()).rolling('1826D', min_periods=60).mean()
        anchors = (np.repeat(len(past)-1, len(targets)) if mode.startswith('A') else
                   past.index.searchsorted(pd.DatetimeIndex(targets))-1)
        if (anchors<0).any():
            raise ValueError('Sin pasado')
        x = xall.iloc[anchors]
        base = bases.iloc[anchors].to_numpy()
        if not np.isfinite(base).all():
            raise ValueError('Sin60 etiquetas maduras')
        probabilities = np.repeat(base[:,None], len(METHODS), axis=1)
        for j, t in enumerate(targets):
            probabilities[j, 1] = float(np.random.default_rng(seed(self.sim, str(t), mode, 'azar')).integers(2))
        for m, col in (('momentum', 'momentum_12_1'), ('tendencia', 'media_10m'), ('volatilidad', 'volatilidad')):
            probabilities[:, METHODS.index(m)] = [self.buckets[col].get(float(v), float(b)) for v,b in zip(x[col],base)]
        available = np.isfinite(x[COLS]).all(axis=1).to_numpy()
        for m, model in self.models.items():
            if available.any():
                probabilities[available, METHODS.index(m)] = model.predict_proba(x.loc[available,COLS].to_numpy())[:,1]
        flags = calendario(targets, fomc).to_numpy()
        values=np.array([self.calp.get(c,0.) for c in EFFECTS])
        available=np.array([c in self.calp for c in EFFECTS],float)
        counts=flags@available
        probabilities[:, -1] = np.where(counts>0, (flags@values)/np.maximum(counts,1), base)
        probabilities[:, 7] = probabilities[:, [2,3,4,5,6,8]].mean(axis=1)
        return np.round(np.clip(probabilities, 0, 1), 5)

    def rango(self, past, h, probs):
        logs = np.log(past.close/past.close.shift(1)).dropna().tail(1260).to_numpy()
        rng = np.random.default_rng(seed(self.sim, str(past.index[-1]), h, 'rango'))
        samples = np.zeros(1999)
        for offset in range(0, h, 5):
            starts = rng.integers(0, len(logs), 1999)
            samples += sum(logs[(starts+k) % len(logs)] for k in range(min(5,h-offset)))
        q = float((logs > 0).mean())
        pos, neg = logs[logs > 0], logs[logs <= 0]
        spread = float(pos.mean()-neg.mean()) if len(pos) and len(neg) else 0.
        # Probabilidades promedio del resto del mes; no deriva basada en outcomes.
        return {m: np.round(np.expm1(np.quantile(samples, [.1,.9])+
                    h*(float(probs[:,i].mean())-q)*spread), 6).tolist()
                for i,m in enumerate(METHODS)}


def start_index(sim, month, targets):
    return int(np.random.default_rng(seed(sim, str(month), 'inicio')).integers(len(targets)))


def jugar(sim, frame, month, mode, model, fomc=(), vault=None):
    month = pd.Period(month, freq='M')
    if mode not in MODES:
        raise ValueError('Modo inválido')
    if sim.endswith('-USD'):
        targets = pd.bdate_range(month.start_time, month.end_time)
    else:
        cal = xc.get_calendar('XNYS', start='2003-01-01', end='2027-12-31')
        targets = cal.sessions_in_range(month.start_time.normalize(), month.end_time.normalize())
    if not len(targets):
        raise ValueError('Mes sin sesiones')
    if mode.endswith('azar'):
        targets = targets[start_index(sim, month, targets):]
    start = targets[0]
    past = vault.ver(start) if vault else frame.loc[frame.index < start].copy()
    if not len(past):
        raise ValueError('Sin historia anterior')
    if sim.endswith('-USD') and start < pd.Timestamp('2015-01-01'):
        raise ValueError('Cripto antes de2015')
    if mode.startswith('A'):
        probs = model.pronosticar(past, targets, mode, fomc)
    else:
        known = vault.ver(targets[-1]) if vault else frame.loc[frame.index < targets[-1]].copy()
        probs = model.pronosticar(known, targets, mode, fomc)
    # Rango fijado en T también para B, aunque las probabilidades diarias se actualicen.
    frozen = model.pronosticar(past, targets, 'A_'+mode.split('_')[1], fomc)
    horizon = (targets[-1]-past.index[-1]).days if sim.endswith('-USD') else len(targets)
    ranges = model.rango(past, horizon, frozen)
    # Revelación en función separada: ningún outcome entra en los pronosticadores.
    daily = frame.close.pct_change(fill_method=None).reindex(targets)
    y = [int(r > 0) if np.isfinite(r) else None for r in daily]
    end = frame.close.reindex([targets[-1]]).iloc[0]
    ret = float(end/past.close.iloc[-1]-1) if np.isfinite(end) else None
    prior = past.close.pct_change(fill_method=None).tail(20).dropna()
    last = (past.rasgos if isinstance(past,VistaMes) else indicadores(past,sim.endswith('-USD'))).iloc[-1]
    known = dict(hasta=str(past.index[-1].date()), subieron=float((prior > 0).mean()),
                 volatilidad=float(prior.std()) if len(prior)>1 else None,
                 tendencia=float(last.media_10m) if np.isfinite(last.media_10m) else None)
    return dict(sim=sim, mes=str(month), modo=mode, inicio=str(start.date()), contexto=known,
                fechas=[str(t.date()) for t in targets], probabilidades=probs.tolist(), y=y,
                retornos=[round(float(r),6) if np.isfinite(r) else None for r in daily],
                rango=ranges, retorno_mes=ret, ajuste_hasta=model.ajuste_hasta,
                etiquetas_hasta=model.etiquetas_hasta)


def calificar(game):
    y = np.array([v if v is not None else np.nan for v in game['y']])
    p = np.array(game['probabilidades']); good = np.isfinite(y)
    if not good.any():
        return None
    return {m: dict(n=int(good.sum()), acierto=float(((p[good,i]>=.5)==y[good]).mean()),
        brier=float(((p[good,i]-y[good])**2).mean()),
        cobertura=(game['rango'][m][0] <= game['retorno_mes'] <= game['rango'][m][1])
            if game['retorno_mes'] is not None else None)
        for i,m in enumerate(METHODS)}
