"""Recolector separado del núcleo; publica exclusivamente métricas y ejemplos relativos."""
import argparse
import datetime as dt
import hashlib
import json
import subprocess
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests
import exchange_calendars as xc
from lab.boveda import Boveda, Pronosticador, HORIZONTES, METODOS
from lab.boveda_metricas import resumir

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'resultados'
CACHE = ROOT/'.boveda-cache'
ASSETS = ('SPY', 'QQQ', 'VT', 'CSPX.L', 'MTUM', 'GLD', 'BTC-USD', 'ETH-USD', 'TLT', 'EEM')
EXAMPLES = ('2008-09-15', '2015-07-15', '2020-03-02', '2022-01-03', '2023-07-17',
            '2024-07-15', '2025-07-15', '2026-01-05', '2026-06-01', '2026-07-15')
CONFIG = {'version': 1, 'activos': ASSETS, 'horizontes': HORIZONTES, 'metodos': METODOS,
          'desde': '2005-01-01', 'reserva_desde': '2024-01-01', 'reentreno': 'mensual expansivo',
          'C': .1, 'minimo_ajuste': 300, 'minimo_condicional': 60, 'bootstrap': 999,
          'bloque': 'max(21,2*h)', 'semilla': 20261010, 'ejemplos': EXAMPLES,
          'objetivo': 'retorno de precio, no total ni rentabilidad negociable',
          'valuacion': 'abstención sin vintages de CAPE y spread con filed verificado'}


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def firma_codigo():
    paths = ('lab/boveda.py', 'lab/boveda_metricas.py', 'lab/boveda_ejecutar.py')
    return sha({'config': CONFIG, 'archivos': {p: hashlib.sha256((ROOT/p).read_text(encoding='utf8').encode()).hexdigest() for p in paths}})


def write(path, payload, once=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Creación exclusiva para el protocolo y evaluación final; jamás sobrescribirlos.
    if once:
        with path.open('x', encoding='utf8') as f: json.dump(payload, f, ensure_ascii=False, allow_nan=False)
    else:
        tmp = path.with_suffix('.tmp'); tmp.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf8')
        tmp.replace(path)


def congelar():
    commit = subprocess.check_output(['git', '-c', 'safe.directory=*', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    paths = ['lab/boveda.py', 'lab/boveda_metricas.py', 'lab/boveda_ejecutar.py', 'tests/test_boveda.py']
    for p in paths:
        original = subprocess.check_output(['git', '-c', 'safe.directory=*', 'show', commit+':'+p], cwd=ROOT)
        if original.decode('utf8').replace('\r\n', '\n') != (ROOT/p).read_text(encoding='utf8'):
            raise ValueError('Congelar requiere código y pruebas ya comprometidos')
    write(OUT/'boveda_protocolo_v2.json', {'config': CONFIG, 'firma': firma_codigo(), 'commit_diseno': commit,
           'congelado': dt.datetime.now(dt.timezone.utc).isoformat()}, once=True)


def descargar(sim, end):
    CACHE.mkdir(exist_ok=True)
    path = CACHE/(sim.replace('^', '')+'-'+end+'.json')
    if path.exists(): payload = json.loads(path.read_text(encoding='utf8'))
    else:
        # Descargar SOLO hasta el límite explícito: durante diseño no se solicita la reserva.
        params = {'period1': int(pd.Timestamp('2003-01-01', tz='UTC').timestamp()),
                  'period2': int((pd.Timestamp(end, tz='UTC')+pd.Timedelta(days=1)).timestamp()),
                  'interval': '1d', 'events': 'splits'}
        error = None
        for attempt in range(3):
            try:
                r = requests.get('https://query1.finance.yahoo.com/v8/finance/chart/'+sim,
                                 params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=40)
                r.raise_for_status(); payload = r.json()['chart']['result'][0]
                if not payload: raise ValueError('Sin datos')
                write(path, payload); break
            except Exception as e: error = e; time.sleep(attempt+1)
        else: raise ValueError('Descarga fallida: '+str(error)[:150])
    zone = payload.get('meta', {}).get('exchangeTimezoneName', 'UTC')
    index = pd.to_datetime(payload['timestamp'], unit='s', utc=True).tz_convert(zone).tz_localize(None).normalize()
    d = pd.DataFrame(payload['indicators']['quote'][0], index=index).sort_index()
    d = d.loc[(d.index <= end) & d.close.notna() & (d.close > 0)]
    if sim.endswith('-USD'):
        # Solo días UTC completos. Se conservan fines de semana en contexto y horizontes.
        cutoff = pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()
        d = d.loc[d.index < cutoff]
        d = d.reindex(pd.date_range(d.index.min(), d.index.max(), freq='D'))
    else:
        cal = xc.get_calendar('XLON' if sim.endswith('.L') else 'XNYS', start='2003-01-01')
        now = pd.Timestamp.now(tz='UTC')
        sessions = cal.sessions[(cal.sessions >= d.index.min()) & (cal.sessions <= d.index.max())]
        completed = [s for s in sessions if cal.session_close(s)+pd.Timedelta(minutes=15) <= now]
        d = d.reindex(completed)
    if d.index.has_duplicates: raise ValueError('Fechas duplicadas en fuente')
    return d, {'sim': sim, 'desde': str(d.index.min().date()), 'hasta': str(d.index.max().date()),
               'sesiones': len(d), 'fuente': 'Yahoo chart; OHLC solo caché local ignorado',
               'sesiones_sin_precio': int(d.close.isna().sum()),
               'sha256_respuesta': sha(payload), 'zona': zone,
               'nota': 'Precio retrospectivo del proveedor; sin adjclose ni dividendos. No es un archivo de vintages.'}


def evaluar(sim, d, exogenous, period, after=None):
    models = {h: Pronosticador(sim, h) for h in HORIZONTES}
    vault = Boveda({sim: d, **exogenous}); rows = []; examples = []; skipped = 0
    # El evaluador conserva resultados; nunca pasan a las estrategias.
    closes = d.close.to_numpy(); indices = d.index
    for i, t in enumerate(indices):
        date = t.date().isoformat()
        if date < '2005-01-01' or t.weekday() >= 5 or not np.isfinite(closes[i]): continue
        if period == 'desarrollo' and date >= '2024-01-01': continue
        if period != 'desarrollo' and date < '2024-01-01': continue
        horizons = [h for h in HORIZONTES if i+h < len(d) and np.isfinite(closes[i+h]) and
                    (period != 'desarrollo' or indices[i+h] < pd.Timestamp('2024-01-01')) and
                    (not after or date > after.get(str(h), '1900-01-01'))]
        if not horizons: continue
        view = vault.ver(date)
        for h in horizons:
            preds = models[h].pronosticar(view)
            if not preds: skipped += 1; continue
            target = indices[i+h].date().isoformat(); ret = float(closes[i+h]/closes[i]-1)
            for method, pred in preds.items():
                rows.append({'periodo': period, 'sim': sim, 'horizonte': h, 'metodo': method,
                             'fecha': date, 'objetivo': target, 'retorno': ret, 'y': int(ret > 0),
                             'base': preds['ingenuo']['p_sube'], **pred})
            if date in EXAMPLES and np.isfinite(closes[i+1:i+h+1]).all():
                examples.append({'sim': sim, 'horizonte': h, 'fecha': date, 'objetivo': target,
                                 'pronosticos': preds, 'revelaciones': [
                                     {'fecha': indices[j].date().isoformat(), 'retorno': float(closes[j]/closes[i]-1)}
                                     for j in range(i+1, i+h+1)]})
    last = {str(h): max((r['fecha'] for r in rows if r['horizonte'] == h), default=(after or {}).get(str(h))) for h in HORIZONTES}
    return {'metricas': resumir(rows), 'ejemplos': examples, 'hasta_ancla': last,
            'pronosticos': len(rows), 'sin_historia': skipped}


def ejecutar(mode, end):
    started = time.monotonic(); initial = OUT/'boveda_reserva_inicial.json'
    if mode != 'desarrollo':
        protocol = json.loads((OUT/'boveda_protocolo_v2.json').read_text(encoding='utf8'))
        if protocol['firma'] != firma_codigo(): raise ValueError('Código alterado tras congelación; reserva bloqueada')
        if mode == 'final' and initial.exists(): raise ValueError('La reserva inicial ya fue evaluada; usar extender')
        if mode == 'extender' and not initial.exists(): raise ValueError('Falta evaluación inicial')
        if mode == 'final':
            # Recibo de apertura ANTES de solicitar la reserva: incluso una falla
            # impide repetir silenciosamente la evaluación inicial.
            write(OUT/'boveda_reserva_apertura.json', {
                'firma': protocol['firma'], 'commit_diseno': protocol['commit_diseno'],
                'abierta': dt.datetime.now(dt.timezone.utc).isoformat(), 'hasta': end}, once=True)
    else:
        if (OUT/'boveda_protocolo_v2.json').exists(): raise ValueError('Diseño ya congelado')
        end = min(end, '2023-12-31')
    previous = json.loads((OUT/'boveda.json').read_text(encoding='utf8')) if (OUT/'boveda.json').exists() else {}
    frames = {}; sources = []; failures = []
    for sim in (*ASSETS, '^VIX'):
        try:
            d, source = descargar(sim, end)
            if len(d) < 2: raise ValueError('Sin sesiones completas')
            frames[sim] = d; sources.append(source)
        except Exception as e: failures.append({'sim': sim, 'error': str(e)[:180]})
    period = 'desarrollo' if mode == 'desarrollo' else 'reserva' if mode == 'final' else 'extension-'+end
    progress = previous.get('hasta_ancla', {}) if mode == 'extender' else {}
    results = {}
    def one(sim):
        result = evaluar(sim, frames[sim], {'^VIX': frames['^VIX']} if '^VIX' in frames and not sim.endswith('-USD') else {},
                         period, progress.get(sim))
        print(sim, result['pronosticos'], 'pronósticos', flush=True)
        return sim, result
    with ThreadPoolExecutor(max_workers=2) as pool:
        for sim, result in pool.map(one, [s for s in ASSETS if s in frames]): results[sim] = result
    metrics = [m for r in results.values() for m in r['metricas']]
    # BH global: resumir dentro del activo no basta; corregir todos los activos juntos.
    kept = previous.get('metricas', []) if mode != 'desarrollo' else []
    metrics = kept+metrics; ranked = sorted(metrics, key=lambda r: r['p']); q = 1.
    for rank in range(len(ranked), 0, -1):
        r = ranked[rank-1]; q = min(q, r['p']*len(ranked)/rank); r['q_bh'] = q
        r['ventaja'] = bool(r['habilidad'] is not None and r['habilidad'] > 0 and q < .05)
    anchors = previous.get('hasta_ancla', {}) if mode == 'extender' else {}
    anchors.update({s: r['hasta_ancla'] for s, r in results.items()})
    examples = previous.get('ejemplos', []) if mode != 'desarrollo' else []
    examples += [e for r in results.values() for e in r['ejemplos']]
    data = {'version': 1, 'actualizado': dt.datetime.now(dt.timezone.utc).isoformat(), 'corte_solicitado': end,
            'fase': mode, 'config': CONFIG, 'firma': firma_codigo(), 'metricas': metrics,
            'contrastes': len(metrics), 'ejemplos': examples, 'fuentes': sources, 'fallas': failures,
            'hasta_ancla': anchors, 'duracion_segundos': round(time.monotonic()-started, 2),
            'reserva': {'desde': '2024-01-01', 'evaluacion_inicial': 'única, archivo inmutable',
                        'extension': 'solo anclas nuevas por horizonte; no repite las evaluadas'},
            'sin_evaluar': {'valuacion': CONFIG['valuacion'],
                            'IBIT': 'Se eligió BTC-USD como alternativa explícita, sin inventar historia de IBIT.'},
            'aviso': 'Simulación de probabilidades, no dinero ganado. Horizonte en sesiones (cripto: días UTC); anclas lunes a viernes. Rangos de retorno de precio P10–P90, no garantías. Wilson y deciles descriptivos; inferencia Brier por bloques y BH global. ETFs actuales elegidos de antemano: no es un universo sin supervivencia. VIX contemporáneo descargado, sin archivo de vintages. CAPE se abstiene sin fecha de publicación. No se abrió el histórico reservado del agente.'}
    if mode == 'final':
        snapshot = dict(data); snapshot['metricas'] = [m for m in metrics if m['periodo'] == 'reserva']
        snapshot['sha256'] = sha(snapshot); write(initial, snapshot, once=True)
    write(OUT/'boveda.json', data)
    print('Terminado:', data['duracion_segundos'], 's;', len(metrics), 'contrastes;', len(failures), 'fallas')


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('modo', choices=['desarrollo', 'congelar', 'final', 'extender'])
    p.add_argument('--hasta', default=dt.date.today().isoformat()); a = p.parse_args()
    congelar() if a.modo == 'congelar' else ejecutar(a.modo, a.hasta)
