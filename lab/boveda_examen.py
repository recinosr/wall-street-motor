"""Sorteo reproducible, revelación posterior y rondas predefinidas del examen 21B."""
import argparse
import datetime as dt
import hashlib
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
from lab.boveda import Boveda
from lab.boveda_ejecutar import ASSETS, descargar, write, sha
from lab.boveda_examen_modelos import MotorExamen, HORIZONTES, RONDAS, BASE, NUEVOS, EXOGENAS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'resultados'
CONFIG = {'version': 4, 'entrenamiento': ['2005-01-01', '2018-12-31'],
          'validacion': ['2019-01-01', '2023-12-31'], 'reserva_desde': '2024-01-01',
          'horizontes_dias_naturales': HORIZONTES, 'rondas_predefinidas': RONDAS,
          'seleccion': 'mínimo Brier OOS de entrenamiento; empate orden fijo; sin afinar en validación',
          'parada': 'dos rondas consecutivas cuyo límite inferior IC95 de mejora apareada no supera cero; máximo6',
          'abstencion': 'política de comparación vuelve explícitamente al ingenuo; pronóstico ausente no se inventa',
          'inferencia': 'bootstrap119999 de bloques de calendario max(60,2h); primaria30/60/90 bloque180 días; activos juntos',
          'busqueda': 'BH global y Bonferroni incluye todas las variantes diseñadas, celdas y976 contrastes previos',
          'reserva': 'ya abierta por21; NO se descarga ni evalúa otra vez; ganador requiere prueba prospectiva',
          'curva_tasas': 'abstención: no se dispone de vintages con publicación verificable; no retraso inventado'}
CONFIG['caminata'] = 'simetría de log-retornos, precios positivos; p=.5, sin deriva logarítmica'
CONFIG['intento_previo'] = 'v2 detenido antes de métricas; corrección de soporte físico y vectorización causal, misma semilla'
CONFIG['variantes_previas_generadas'] = 44


def firma():
    return sha({'config': CONFIG, 'codigo': {p: hashlib.sha256((ROOT/p).read_text(encoding='utf8').encode()).hexdigest()
        for p in ('lab/boveda_examen.py', 'lab/boveda_examen_modelos.py', 'lab/boveda_compat21.py',
                  'lab/boveda.py', 'lab/boveda_metricas.py', 'lab/boveda_ejecutar.py')}})


def sortear(frames, n, seed):
    if not isinstance(n, int) or not 1 <= n <= 10000: raise ValueError('n debe estar entre1 y10000')
    candidates = []
    for sim in ASSETS:
        if sim not in frames: continue
        d = frames[sim]
        for i, t in enumerate(d.index):
            if t < pd.Timestamp('2005-01-01') or t >= pd.Timestamp('2024-01-01') or t.weekday() >= 5: continue
            # Elegibilidad del sorteo usa SOLO pasado: nunca dirección ni huecos futuros.
            if i >= 420 and np.isfinite(d.close.iloc[i]) and np.isfinite(d.close.iloc[:i+1]).sum() >= 420:
                candidates.append((sim, t.date().isoformat()))
    if n > len(candidates): raise ValueError('Más preguntas que pares activo/fecha elegibles')
    rng = np.random.default_rng(seed)
    selected = [candidates[i] for i in rng.choice(len(candidates), n, replace=False)]
    return sorted(selected, key=lambda x: (x[1], x[0]))


def revelar(d, date, h, preds):
    i = d.index.get_loc(pd.Timestamp(date)); j = d.index.searchsorted(pd.Timestamp(date)+pd.Timedelta(days=h))
    if j >= len(d) or d.index[j] >= pd.Timestamp('2024-01-01'): return None, 'objetivo cruza reserva o falta madurez'
    future = d.iloc[i+1:j+1]
    if not np.isfinite(future[['close', 'high', 'low']].to_numpy()).all(): return None, 'hueco en trayectoria; sin rellenar'
    base = float(d.close.iloc[i]); ret = float(d.close.iloc[j]/base-1)
    outcome = {'objetivo': d.index[j].date().isoformat(), 'retorno': ret,
               'maximo_real': float(future.high.max()/base-1), 'minimo_real': float(future.low.min()/base-1),
               'dentro_rango': {m: bool(p['p10'] <= ret <= p['p90']) for m, p in preds.items()}}
    return outcome, None


def pesos_pasados(rows, date):
    losses = {}
    for row in rows:
        if row['objetivo'] >= date or row['objetivo'] >= '2019-01-01': continue
        for m, p in row['pronosticos'].items():
            if m not in (*BASE, *NUEVOS) or m in ('ponderado', 'ensamble'): continue
            losses.setdefault(m, []).append((p['p_sube']-row['y'])**2)
    # Inverso de Brier OOS maduro; no pérdidas in-sample del ajuste.
    return {m: 1/max(float(np.mean(v)), .01) for m, v in losses.items() if len(v) >= 30}


def bootstrap_calendario(rows, differences, block):
    if not rows: return {'p': 1., 'ic95': None, 'bloques': 0}
    dates = pd.to_datetime([r['fecha'] for r in rows])
    ids = ((dates-pd.Timestamp('2005-01-01')).days//block).to_numpy()
    groups = sorted(set(ids))
    # Misma muestra de bloques para todos los activos y métodos: preserva dependencia transversal.
    totals = np.array([np.asarray(differences)[ids == g].sum() for g in groups])
    counts = np.array([(ids == g).sum() for g in groups])
    if len(groups) < 3: return {'p': 1., 'ic95': None, 'bloques': len(groups)}
    rng = np.random.default_rng(20261010)
    if not np.any(differences): return {'p': 1., 'ic95': [0., 0.], 'bloques': len(groups)}
    sample = rng.integers(0, len(groups), (119999, len(groups)))
    draws = totals[sample].sum(axis=1)/counts[sample].sum(axis=1)
    mean = float(np.mean(differences))
    return {'p': float((1+np.count_nonzero(draws-mean >= mean))/120000),
            'ic95': np.quantile(draws, [.025, .975]).tolist(), 'bloques': len(groups)}


def loss(row, method):
    # Ausencias explícitas: compara la política de abstenerse al ingenuo.
    p = row['pronosticos'].get(method, row['pronosticos']['ingenuo'])['p_sube']
    return (p-row['y'])**2


def score(rows, method, h=None, inference=True):
    if not rows: return {'n': 0, 'brier': None, 'habilidad': None, 'p': 1., 'ic95': None}
    base = np.array([loss(r, 'ingenuo') for r in rows]); own = np.array([loss(r, method) for r in rows])
    delta = base-own
    out = {'n': len(rows), 'pronosticos_disponibles': sum(method in r['pronosticos'] for r in rows),
           'brier': float(own.mean()), 'brier_ingenuo': float(base.mean()),
           'habilidad': float(1-own.mean()/base.mean()) if base.mean() > 0 else None,
           **(bootstrap_calendario(rows, delta, max(60, 2*h) if h else 180) if inference else {'p': 1., 'ic95': None})}
    if out['ic95'] is not None: out['ic95_habilidad'] = [v/float(base.mean()) for v in out['ic95']]
    return out


def rondas(rows):
    train = [r for r in rows if r['objetivo'] < '2019-01-01' and r['horizonte'] != 1000]
    val = [r for r in rows if r['fecha'] >= '2019-01-01' and r['horizonte'] != 1000]
    if not train or not val: raise ValueError('Muestra sin entrenamiento/validación; aumentar n')
    evaluated = []; metrics = []; incumbent = 'ingenuo'; failures = 0; tried = []
    # Las seis familias de mezclas están diseñadas antes de conocer validación.
    for number, candidates in enumerate(RONDAS, 1):
        tried.extend(candidates)
        training = {m: score(train, m, inference=False) for m in candidates}
        choice = min(candidates, key=lambda m: (training[m]['brier'], candidates.index(m)))
        # Retiene campeón por habilidad de entrenamiento, nunca por ranking validación.
        if training[choice]['brier'] < score(train, incumbent, inference=False)['brier']: incumbent_next = choice
        else: incumbent_next = incumbent
        comparison = [loss(r, incumbent)-loss(r, incumbent_next) for r in val]
        change = bootstrap_calendario(val, comparison, 180)
        improves = change['ic95'] is not None and change['ic95'][0] > 0
        failures = 0 if improves else failures+1
        winner = score(val, incumbent_next)
        evaluated.append({'ronda': number, 'variantes': list(candidates), 'elegido_entrenamiento': choice,
            'campeon_entrenamiento': incumbent_next, 'entrenamiento': training,
            'validacion': winner, 'mejora_frente_ronda_anterior': change,
            'mejora_mayor_ic': improves, 'sin_mejora_consecutivas': failures})
        for sim in ASSETS:
            for h in HORIZONTES:
                subset = [r for r in rows if r['sim'] == sim and r['horizonte'] == h and r['fecha'] >= '2019-01-01']
                for m in candidates:
                    if subset: metrics.append({'ronda': number, 'sim': sim, 'horizonte': h, 'metodo': m, **score(subset, m, h)})
        incumbent = incumbent_next
        if number >= 3 and failures >= 2: break
    # Cuenta incluso variantes diseñadas pero no abiertas; ajuste de búsqueda conservador.
    designed = sum(map(len, RONDAS))+CONFIG['variantes_previas_generadas']
    family = 976+designed*len(ASSETS)*len(HORIZONTES)+designed
    ranked = sorted(metrics, key=lambda m: m['p']); q = 1.
    for rank in range(len(ranked), 0, -1):
        m = ranked[rank-1]; q = min(q, m['p']*family/rank)
        m['q_bh'] = q; m['p_busqueda'] = min(1., m['p']*family)
        m['ventaja'] = bool(m['habilidad'] is not None and m['habilidad'] > 0 and q < .05 and m['p_busqueda'] < .05)
    return {'rondas': evaluated, 'ganador_congelado': incumbent, 'metricas': metrics,
            'variantes_intentadas': len(tried)+CONFIG['variantes_previas_generadas'],
            'variantes_evaluadas_validacion': len(tried), 'variantes_diseno': designed,
            'contrastes_calculados': len(metrics), 'familia_ajuste_busqueda': family,
            'parada': '2 rondas sin mejora mayor que IC' if failures >= 2 else 'máximo6',
            'reserva': {'estado': 'no reabierta; consumida en tarea21', 'evaluacion_final_nueva': False,
                        'requisito': 'evaluación prospectiva desde publicación del ganador; no instalada como bot'}}


def ejecutar(n, seed):
    if not 1 <= n <= 10000: raise ValueError('n debe estar entre1 y10000')
    dest = OUT/f'boveda_examen_{seed}_{n}.json'
    if dest.exists(): raise ValueError('Este examen ya fue registrado: no sobrescribir/repetir silenciosamente')
    from lab.boveda_compat21 import firma_compatible
    old = json.loads((OUT/'boveda_protocolo_v2.json').read_text(encoding='utf8'))
    if firma_compatible() != old['firma']: raise ValueError('Núcleo21 alterado; examen bloqueado')
    started = time.monotonic(); design = OUT/'boveda_examen_diseno_v4.json'
    if not design.exists(): write(design, {'config': CONFIG, 'firma': firma(), 'fecha': dt.datetime.now(dt.timezone.utc).isoformat()}, once=True)
    protocol = json.loads(design.read_text(encoding='utf8'))
    if protocol['firma'] != firma(): raise ValueError('Diseño del examen alterado; registrar una nueva versión, sin sustituir recibo')
    # Recibo antes de descarga/sorteo: intentos fallidos también son auditables.
    receipt = OUT/f'boveda_examen_v4_recibo_{seed}_{n}.json'
    write(receipt, {'semilla': seed, 'n': n, 'firma': firma(), 'inicio': dt.datetime.now(dt.timezone.utc).isoformat()}, once=True)
    frames = {}; sources = []; errors = []
    for sim in dict.fromkeys((*ASSETS, '^VIX', *EXOGENAS)):
        try:
            d, source = descargar(sim, '2023-12-31'); frames[sim] = d; sources.append(source)
        except Exception as e: errors.append({'sim': sim, 'error': str(e)[:180]})
    if any(s not in frames for s in ASSETS): raise ValueError('Falta un activo del universo; no seleccionar solo supervivientes de descarga')
    anchors = sortear(frames, n, seed); vault = Boveda(frames)
    models = {(s, h): MotorExamen(s, h) for s in ASSETS for h in HORIZONTES}
    rows = []; questions = []; unavailable = []
    for index, (sim, date) in enumerate(anchors):
        view = vault.ver(date); preds_by_h = {}; weights = pesos_pasados(rows, date)
        # Primero TODOS los pronósticos, luego consultar cualquier resultado.
        for h in HORIZONTES:
            preds_by_h[h] = models[sim, h].pronosticar(view, weights)
        for h, preds in preds_by_h.items():
            if not preds:
                unavailable.append({'sim': sim, 'fecha': date, 'horizonte': h, 'motivo': 'menos120 etiquetas maduras/300 contexto'})
                continue
            outcome, error = revelar(frames[sim], date, h, preds)
            if error:
                unavailable.append({'sim': sim, 'fecha': date, 'horizonte': h, 'motivo': error}); continue
            record = {'sim': sim, 'fecha': date, 'horizonte': h, 'pronosticos': preds, **outcome, 'y': int(outcome['retorno'] > 0)}
            rows.append(record)
            # Solo ejemplos relativos, nunca OHLC; gráfico conocido60 sesiones antes deT.
            d = view[sim]; c = float(d.close.iloc[-1]); history = d.close.iloc[-60:]
            i = frames[sim].index.get_loc(pd.Timestamp(date)); j = frames[sim].index.get_loc(pd.Timestamp(outcome['objetivo']))
            questions.append({**record, 'contexto': [{'fecha': t.date().isoformat(), 'retorno': float(v/c-1)} for t, v in history.items() if np.isfinite(v)],
                'revelaciones': [{'fecha': t.date().isoformat(), 'retorno': float(v/c-1)} for t, v in frames[sim].close.iloc[i+1:j+1].items()]})
        if (index+1) % 100 == 0: print(index+1, '/', n, 'preguntas pronosticadas; sin inspeccionar puntuaciones', flush=True)
    educational = (OUT/'boveda_examen_ganador.json').exists()
    results = json.loads((OUT/'boveda_rondas.json').read_text(encoding='utf8')) if educational else rondas(rows)
    # Otra semilla genera práctica; nunca vuelve a seleccionar al campeón ni
    # convierte el mismo conjunto histórico en una validación independiente.
    if educational:
        results = {k: results[k] for k in ('rondas', 'ganador_congelado', 'metricas', 'variantes_intentadas',
                   'variantes_diseno', 'contrastes_calculados', 'familia_ajuste_busqueda', 'parada', 'reserva')}
    # Recibo exclusivo contiene pronósticos/revelación; no publica precios absolutos.
    result = {'version': 1, 'semilla': seed, 'n_sorteadas': n, 'pares_unicos': len(set(anchors)),
              'fecha': dt.datetime.now(dt.timezone.utc).isoformat(), 'firma': firma(), 'config': CONFIG,
              'fuentes': sources, 'fallas': errors, 'no_calificadas': unavailable, 'calificadas': len(rows),
              'anclas_sha256': sha(anchors), 'duracion_segundos': round(time.monotonic()-started, 2),
              'modo': 'práctica educativa adicional; métricas congeladas originales' if educational else 'rondas iniciales', **results}
    write(dest, result, once=True)
    if not educational: write(OUT/'boveda_rondas.json', result, once=True)
    # Banco pre-reserva educativo. El navegador contiene el futuro y lo oculta;
    # tampoco cuenta cada clic como una nueva evaluación estadística.
    allowed = set(m for round_ in results['rondas'] for m in round_['variantes'])
    for q in questions:
        q['pronosticos'] = {m: p for m, p in q['pronosticos'].items() if m in allowed}
        q['dentro_rango'] = {m: b for m, b in q['dentro_rango'].items() if m in allowed}
    write(OUT/'boveda_examenes.json', {'version': 1, 'semilla': seed, 'firma': firma(), 'ejemplos': questions,
          'aviso': 'Banco educativo público pre2024; futuras revelaciones están en JSON. No es examen ciego ni evaluación independiente.'})
    # Ganador y regla inmutables; no abre ni solicita la reserva.
    if not educational:
        write(OUT/'boveda_examen_ganador.json', {'firma': firma(), 'ganador': results['ganador_congelado'],
              'fecha': result['fecha'], 'reserva': results['reserva'], 'semilla': seed, 'config': CONFIG}, once=True)
    print('Terminado', result['duracion_segundos'], 's;', results['parada'], flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('modo', choices=['examen']); p.add_argument('--n', type=int, default=1000)
    p.add_argument('--semilla', type=int, required=True); args = p.parse_args()
    ejecutar(args.n, args.semilla)


if __name__ == '__main__': main()
