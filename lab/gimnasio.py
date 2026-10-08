"""Gimnasio walk-forward: seis meses de historia, validación posterior y prueba mensual sellada."""
import argparse
from collections import Counter
import json
import math
import random
import statistics
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import archivo, dia

RAIZ = Path(__file__).resolve().parents[1]
ACTIVOS = ("BTC", "ETH")
VARIABLES = ("tendencia_1h", "tendencia_1d", "hora", "volatilidad_relativa", "gap")
VERSION_METODO = "6m-reloj-v2"
_cache = {}


def preparar(sim, desde, hasta):
    """Lee cada mes una vez y conserva el contexto anterior a cada sesión."""
    ini = pd.Timestamp(desde, tz=dia.NY)
    fin = pd.Timestamp(hasta, tz=dia.NY) + pd.Timedelta(days=1)
    try:
        df = archivo.leer(sim, (ini - pd.Timedelta(days=5)).tz_convert("UTC"), fin.tz_convert("UTC")).tz_convert(dia.NY)
    except LookupError:
        return []
    sesiones = df.between_time("09:30", "15:59")
    fechas = []
    for fecha, hoy in sesiones.groupby(sesiones.index.date):
        d = fecha.isoformat()
        if d < desde or d > hasta or len(hoy) < 200: continue
        prev = sesiones[sesiones.index < hoy.index[0]].tail(390)
        hoy = hoy.copy()
        if len(prev):
            hoy.attrs["cierre_previo"] = float(prev["close"].iat[-1])
            hoy.attrs["media_dia"] = float(prev["close"].mean())
        _cache[sim, d] = (hoy, dia.rasgos(hoy))
        fechas.append(d)
    return fechas


def datos_dia(sim, fecha):
    if (sim, fecha) not in _cache:
        try:
            df = dia.cargar(sim, fecha)
            _cache[sim, fecha] = (df, dia.rasgos(df)) if len(df) >= 200 else None
        except LookupError:
            _cache[sim, fecha] = None
    return _cache[sim, fecha]


def evaluar(bot, sim, fechas, semilla=11):
    retornos, operaciones = [], []
    for fecha in fechas:
        datos = datos_dia(sim, fecha)
        if datos is None: continue
        r, ops = dia.correr_bot(bot, *datos, semilla)
        retornos.append(float(r)); operaciones.append(len(ops))
    return np.asarray(retornos), np.asarray(operaciones)


def costo_vuelta():
    return 2 * (dia.costo_variable() + dia.COSTO_FIJO / dia.CAPITAL)


def puntaje(retornos, operaciones):
    if not len(retornos): return -math.inf
    n = int(np.sum(operaciones))
    if n == 0: return 0.0
    bruto_por_operacion = (float(sum(retornos)) + n * costo_vuelta()) / n
    if bruto_por_operacion <= 3 * costo_vuelta(): return -math.inf
    return float(np.mean(retornos) - .5 * np.std(retornos) - .5 * costo_vuelta() * np.mean(operaciones))


def mutar(bot, rng, nuevo_id):
    b = dict(bot, id=nuevo_id)
    otro = None
    for _ in range(100):
        candidato = dia.crear_bots(1, rng.randrange(10**9))[0]
        if candidato["familia"] == b["familia"]:
            otro = candidato
            break
    if otro is None: return b
    claves = [k for k in b if k in otro and k not in ("id", "familia")]
    if claves:
        k = rng.choice(claves); b[k] = otro[k]
    return b


def modelo_contexto(sim, train):
    """Ajusta solo con etiquetas cuyo horizonte de 15 min termina en train."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    xx, yy = [], []
    for fecha in train:
        df, x = datos_dia(sim, fecha)
        for t, futuro in etiquetas_contexto(df):
            v = x.iloc[t][list(VARIABLES)].to_numpy(dtype=float)
            if not np.all(np.isfinite(v)): continue
            xx.append(v); yy.append(int(futuro > 3 * costo_vuelta()))
    if len(yy) < 100 or len(set(yy)) < 2: return None
    modelo = make_pipeline(StandardScaler(), LogisticRegression(max_iter=200))
    modelo.fit(xx, yy)
    return modelo, float(np.mean(yy)), len(yy)


def etiquetas_contexto(df):
    """Horizonte de 15 minutos de reloj, sin extenderlo por velas faltantes."""
    entradas = df.index.get_indexer(df.index + pd.Timedelta(minutes=1))
    finales = df.index.get_indexer(df.index + pd.Timedelta(minutes=15))
    for t in range(60, len(df), 5):
        if entradas[t] < 0 or finales[t] < 0: continue
        yield t, float(df["close"].iat[finales[t]] / df["open"].iat[entradas[t]] - 1)


def probabilidad_dia(modelo, x):
    xx = x[list(VARIABLES)].to_numpy(dtype=float)
    validos = np.all(np.isfinite(xx), axis=1)
    p = np.zeros(len(x))
    p[validos] = modelo.predict_proba(xx[validos])[:, 1]
    x["prob_modelo"] = p


def calibracion(modelo, base, sim, fechas):
    pred, real = [], []
    for fecha in fechas:
        df, x = datos_dia(sim, fecha)
        probabilidad_dia(modelo, x)
        for t, futuro in etiquetas_contexto(df):
            p = float(x["prob_modelo"].iat[t])
            if p == 0: continue
            pred.append(p)
            real.append(int(futuro > 3 * costo_vuelta()))
    if not real: return None
    y = np.asarray(real)
    return {"n": len(real), "frecuencia_prueba": float(np.mean(y)), "frecuencia_train": base,
            "brier": float(np.mean((np.asarray(pred) - y) ** 2)), "brier_base": float(np.mean((base - y) ** 2))}


def intervalo(retornos, semilla=17, alpha=.05):
    retornos = np.asarray(retornos, dtype=float)
    if not len(retornos): return [0.0, 0.0]
    if np.all(retornos == retornos[0]):
        total = float(retornos[0] * len(retornos))
        return [total, total]
    rng = np.random.default_rng(semilla)
    n_boot = 50000 if alpha < .01 else 1000
    muestras = rng.choice(retornos, size=(n_boot, len(retornos)), replace=True).sum(axis=1)
    return [float(v) for v in np.quantile(muestras, [alpha / 2, 1 - alpha / 2])]


def detalle_dia(sim, fecha, campeon, semilla=11):
    df, x = datos_dia(sim, fecha)
    bots = dia.crear_bots(999, semilla + int(fecha.replace('-', ''))) + [campeon]
    resultados = []
    for bot in bots:
        r, ops = dia.correr_bot(bot, df, x, semilla)
        resultados.append({"bot": bot, "ret": float(r), "ops": ops})
    mejor = max(resultados, key=lambda v: v["ret"])
    peor = min(resultados, key=lambda v: v["ret"])
    campeon_dia = resultados[-1]
    for resultado in (mejor, peor, campeon_dia):
        registro = []
        dia.correr_bot(resultado["bot"], df, x, semilla, registro=registro)
        resultado["decisiones"] = registro
    return {"fecha": fecha, "sim": sim,
            "precios": [[str(t), float(c)] for t, c in df["close"].items()],
            "retornos": [v["ret"] for v in resultados],
            "mejor": mejor, "peor": peor, "campeon": campeon_dia, "version_registro": 1,
            "mejor_posible": dia.mejor_posible(df),
            "mantener": dia.vender(dia.comprar(1, float(df["open"].iat[0])), float(df["close"].iat[-1])) - 1}


def nombre_perfil():
    base = f"fijo{dia.COSTO_FIJO:g}_cuenta{dia.CAPITAL:g}" if dia.COSTO_FIJO else f"costo{dia.COSTO:g}"
    return base + (f"_spread{dia.SPREAD:g}" if dia.SPREAD else "")


def guardar_detalles(sim, fechas, campeon=None):
    bot = campeon or {"id": -1, "familia": "no_operar"}
    for fecha in fechas:
        destino = RAIZ / "datos" / "gimnasio" / "dias" / sim / nombre_perfil() / fecha[:7]
        destino.mkdir(parents=True, exist_ok=True)
        (destino / f"{fecha}.json").write_text(
            json.dumps(detalle_dia(sim, fecha, bot), ensure_ascii=False), encoding="utf-8")


def dividir_mes(dias, mes, dias_train=100):
    """Devuelve entrenamiento, validación y prueba en orden cronológico estricto."""
    anteriores = [d for d in dias if d[:7] < mes]
    test = [d for d in dias if d[:7] == mes]
    primer_mes = str(pd.Period(mes, freq="M") - 6)
    ventana = [d for d in anteriores if d[:7] >= primer_mes]
    if len({d[:7] for d in ventana}) < 6 or len(ventana) < max(100, dias_train) or not test:
        return [], [], []
    val = [d for d in ventana if d[:7] == ventana[-1][:7]]
    train = [d for d in ventana if d < val[0]]
    if len(train) < 70 or len(val) < 10: return [], [], []
    return train, val, test


def mes_a_mes(sim, desde, hasta, pob=150, gens=3, dias_train=100, semilla=11, mes=None, guardar_dias=False):
    dias = preparar(sim, desde, hasta)
    meses = sorted({d[:7] for d in dias})
    salida = []
    rng = random.Random(semilla)
    for m in meses:
        if mes and m != mes: continue
        train, val, test = dividir_mes(dias, m, dias_train)
        if not test: continue
        if guardar_dias and m == meses[6]:
            guardar_detalles(sim, [d for d in dias if d < test[0]])
        t0 = time.time()
        poblacion = dia.crear_bots(pob, rng.randrange(10**9))
        candidatos = []
        evaluaciones = []
        for g in range(gens):
            print(f"{sim} {m}: generación {g + 1}/{gens}, {len(train)} días de entrenamiento", flush=True)
            puntajes = []
            for b in poblacion:
                rt, ot = evaluar(b, sim, train, semilla)
                score = puntaje(rt, ot)
                puntajes.append(score)
                evaluaciones.append((b, rt, ot, score))
            candidatos += poblacion
            if g + 1 < gens:
                orden = np.argsort(puntajes)[::-1]
                elite = [poblacion[i] for i in orden[:max(2, pob // 5)]]
                nuevos = [mutar(rng.choice(elite), rng, 100000 + g * pob + i) for i in range(int(pob * .7))]
                poblacion = (elite + nuevos + dia.crear_bots(pob, rng.randrange(10**9)))[:pob]
        validables = []
        diagnostico = {"etapas": Counter(), "familias": {}}
        def anotar(bot, etapa):
            diagnostico["etapas"][etapa] += 1
            diagnostico["familias"].setdefault(bot["familia"], Counter())[etapa] += 1
        for bot, rt, ot, score in evaluaciones:
            if not sum(ot): anotar(bot, "sin_entradas_train"); continue
            if score == -math.inf: anotar(bot, "margen_insuficiente_train"); continue
            rv, ov = evaluar(bot, sim, val, semilla)
            if not sum(ov): anotar(bot, "sin_entradas_validacion"); continue
            sv = puntaje(rv, ov)
            anotar(bot, "validacion_positiva" if sv > 0 else "validacion_no_positiva")
            validables.append((sv, bot, float(np.mean(rt))))
        contexto = modelo_contexto(sim, train)
        brier = None
        n_pruebas = len(candidatos)
        if contexto:
            modelo, frecuencia, _ = contexto
            for d in train + val + test:
                probabilidad_dia(modelo, datos_dia(sim, d)[1])
            brier = calibracion(modelo, frecuencia, sim, test)
            for umbral in (.55, .65, .75):
                bot = {"id": 200000 + int(umbral * 100), "familia": "agente_contexto", "prob_min": umbral,
                       "mantener": 15, "stop": .01, "objetivo": .03, "salida": "tiempo"}
                rt, ot = evaluar(bot, sim, train, semilla)
                rv, ov = evaluar(bot, sim, val, semilla)
                if not sum(ot): anotar(bot, "sin_entradas_train")
                elif puntaje(rt, ot) == -math.inf: anotar(bot, "margen_insuficiente_train")
                elif not sum(ov): anotar(bot, "sin_entradas_validacion")
                else:
                    sv = puntaje(rv, ov)
                    anotar(bot, "validacion_positiva" if sv > 0 else "validacion_no_positiva")
                    validables.append((sv, bot, float(np.mean(rt))))
                n_pruebas += 1
        validables.insert(0, (0.0, {"id": -1, "familia": "no_operar"}, 0.0))
        validables.sort(key=lambda v: v[0], reverse=True)
        _, campeon, train_media = validables[0]
        diagnostico["criterio"] = "Cada evaluación recibe una etapa final; candidatos repetidos cuentan como evaluaciones, no reglas independientes."
        diagnostico["seleccion"] = ("Ningún candidato obtuvo puntaje positivo en validación; efectivo obtuvo 0."
                                    if campeon["familia"] == "no_operar" else "Se eligió el mayor puntaje en validación antes de abrir la prueba.")
        rc, oc = evaluar(campeon, sim, test, semilla)
        base = dia.crear_bots(60, rng.randrange(10**9))
        rb = np.mean([evaluar(b, sim, test, semilla)[0] for b in base], axis=0)
        mantener, posible = [], []
        for fecha in test:
            df, _ = datos_dia(sim, fecha)
            mantener.append(dia.vender(dia.comprar(1, float(df["open"].iat[0])), float(df["close"].iat[-1])) - 1)
            posible.append(dia.mejor_posible(df))
        ventaja = rc - np.maximum(0, mantener)
        fila = {"mes": m, "version_metodo": VERSION_METODO, "poblacion": pob, "generaciones": gens, "semilla": semilla,
                "train_desde": train[0], "train_hasta": train[-1],
                "validacion_desde": val[0], "validacion_hasta": val[-1],
                "prueba_desde": test[0], "prueba_hasta": test[-1], "dias_prueba": len(test),
                "campeon": campeon["familia"], "bot": campeon, "descripcion": dia.describir(campeon),
                "train_campeon": train_media, "validacion_puntaje": validables[0][0],
                "prueba_campeon": float(sum(rc)), "prueba_sin_entrenar": float(sum(rb)),
                "mantener_diario": float(sum(mantener)), "mejor_posible": float(sum(posible)),
                "dias_campeon_gana": float(np.mean(rc > 0)), "operaciones": int(sum(oc)),
                "intervalo_95": intervalo(rc), "intervalo_ventaja_95": intervalo(ventaja),
                "n_pruebas": n_pruebas,
                "diagnostico": diagnostico,
                "familias_descartadas": sorted(set(b["familia"] for b in candidatos) - {campeon["familia"]}),
                "umbral_z_bonferroni": statistics.NormalDist().inv_cdf(1 - .05 / (2 * n_pruebas)),
                "brier": brier,
                "dias_previos": [d for d in dias if d < test[0]] if m == meses[6] else [],
                "serie_diaria": [{"fecha": d, "campeon": float(r), "sin_entrenar": float(b),
                                  "mantener": float(h), "mejor_posible": float(p)}
                                 for d, r, b, h, p in zip(test, rc, rb, mantener, posible)],
                "seg": round(time.time() - t0)}
        salida.append(fila)
        if guardar_dias:
            guardar_detalles(sim, test, campeon)
        print(f"{sim} {m}: {campeon['familia']} prueba {sum(rc):+.2%}, mantener {sum(mantener):+.2%}", flush=True)
    return salida


def guardar(sim, desde, hasta, meses):
    destino = RAIZ / "datos" / "gimnasio"
    destino.mkdir(parents=True, exist_ok=True)
    perfil = nombre_perfil()
    nombre = destino / f"{sim}_{desde}_{hasta}_{perfil}.json"
    ventaja = np.asarray([d["campeon"] - max(0, d["mantener"]) for m in meses for d in m["serie_diaria"]])
    # El motor público compara BTC y ETH con un solo perfil de costo.
    superior = bool(len(ventaja) and intervalo(ventaja, alpha=.05 / 2)[0] > 0)
    informe = {"sim": sim, "version_metodo": VERSION_METODO, "costo_por_lado": dia.COSTO, "spread": dia.SPREAD,
               "costo_fijo_usd_por_orden": dia.COSTO_FIJO, "capital_usd": dia.CAPITAL,
               "criterio": "ventaja sobre max(no operar, comprar y mantener), bootstrap por días",
               "pruebas_configuraciones": 32, "intervalo_ventaja_corregido": intervalo(ventaja, alpha=.05 / 32),
               "ventaja_demostrada": superior, "meses": meses,
               "conclusion": ("Ventaja fuera de muestra no demostrada; hacen falta mejores datos de spread, profundidad y ejecución o señales adicionales."
                              if not superior else "Ventaja estadística observada en esta muestra; requiere réplica independiente.")}
    nombre.write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    escribir_lecciones(destino)
    return nombre, informe


def escribir_lecciones(destino):
    """Reúne campeones y descartes observados; no atribuye causalidad a una sola corrida."""
    filas = []
    for archivo in Path(destino).glob("*.json"):
        try: v = json.loads(archivo.read_text(encoding="utf-8"))
        except (OSError, ValueError): continue
        if not isinstance(v, dict) or "meses" not in v: continue
        for m in v["meses"]:
            if "bot" in m: filas.append((v.get("sim", "?"), v.get("costo_por_lado", 0), m))
    ganadores = Counter(m["campeon"] for _, _, m in filas if m["prueba_campeon"] > 0)
    descartes = Counter(f for _, _, m in filas for f in m.get("familias_descartadas", []))
    texto = ["# Lecciones del gimnasio", "", "Resultados de meses de prueba posteriores a entrenamiento y validación. Un mes positivo no demuestra ventaja estable.", "",
             "## Familias y parámetros que ganaron en prueba", ""]
    if not ganadores: texto.append("Ninguna familia obtuvo retorno positivo en las pruebas disponibles.")
    for sim, costo, m in filas:
        if m["prueba_campeon"] > 0:
            texto.append(f"- {sim} {m['mes']}, costo {costo:.3%}: {m['campeon']} {m['prueba_campeon']:+.2%}; parámetros `{json.dumps(m['bot'], ensure_ascii=False, sort_keys=True)}`.")
    texto += ["", "## Familias descartadas al seleccionar campeón", ""]
    texto += [f"- {f}: {n} meses/corridas sin ser seleccionada." for f, n in descartes.most_common()] or ["Sin descartes registrados."]
    texto += ["", "## Preguntas para el agente", "",
              "1. ¿Se mantiene alguna ventaja después de incluir spread y deslizamiento medidos por activo y hora?",
              "2. ¿Qué variable nueva, conocida antes de la orden, podría distinguir señales rentables de falsas rupturas o caídas?",
              "3. ¿La misma regla supera no operar y comprar y mantener en otros activos y meses posteriores, con el umbral corregido?", ""]
    (Path(destino) / "lecciones.md").write_text("\n".join(texto), encoding="utf-8")


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("sim", choices=ACTIVOS + ("TODOS",)); a.add_argument("desde"); a.add_argument("hasta")
    a.add_argument("--costo", type=float, default=.001); a.add_argument("--spread", type=float, default=0)
    a.add_argument("--fijo", type=float, default=0); a.add_argument("--capital", type=float, default=1000)
    a.add_argument("--pob", type=int, default=150); a.add_argument("--gens", type=int, default=3)
    a.add_argument("--dias-train", type=int, default=100, help="mínimo de días en los seis meses previos"); a.add_argument("--mes")
    a.add_argument("--guardar-dias", action="store_true")
    a.add_argument("--solo-dias-previos", action="store_true", help="genera días anteriores al primer mes de prueba sin reentrenar")
    x = a.parse_args()
    if min(x.costo, x.spread, x.fijo) < 0 or x.capital <= 0: a.error("Costos no válidos")
    dia.COSTO, dia.SPREAD, dia.COSTO_FIJO, dia.CAPITAL = x.costo, x.spread, x.fijo, x.capital
    for sim in ACTIVOS if x.sim == "TODOS" else (x.sim,):
        if x.solo_dias_previos:
            fechas = preparar(sim, x.desde, x.hasta)
            meses = sorted({d[:7] for d in fechas})
            if len(meses) > 6: guardar_detalles(sim, [d for d in fechas if d[:7] < meses[6]])
            continue
        res = mes_a_mes(sim, x.desde, x.hasta, x.pob, x.gens, x.dias_train, mes=x.mes, guardar_dias=x.guardar_dias)
        nombre, informe = guardar(sim, x.desde, x.hasta, res)
        print(informe["conclusion"], "guardado:", nombre)
