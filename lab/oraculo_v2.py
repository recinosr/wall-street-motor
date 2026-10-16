"""Evaluación v2 del currículo del Oráculo (niveles 1, 2, 3 y 5).

Los parámetros viven en lab/oraculo_v2_prereg.json (pre-registrado, con hash).
Modos:
  --validacion      solo entrenamiento/validación; no abre la prueba sellada
  --abrir-prueba    abre la prueba sellada UNA vez; escribe el registro y bloquea reaperturas
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from lab import oraculo_datos as D

ROOT = Path(__file__).resolve().parents[1]
PREREG_PATH = ROOT / "lab" / "oraculo_v2_prereg.json"
HASH_PATH = ROOT / "lab" / "oraculo_v2_prereg.sha256"
REGISTRO = ROOT / "resultados" / "nivel_v2_registro.json"
SALIDA = ROOT / "resultados" / "nivel_v2.json"
SALIDA_VAL = ROOT / "resultados" / "nivel_v2_validacion.json"


def cargar_prereg():
    raw = PREREG_PATH.read_bytes()
    h = hashlib.sha256(raw).hexdigest()
    if h != HASH_PATH.read_text().strip():
        raise RuntimeError("El pre-registro cambió: su hash no coincide con oraculo_v2_prereg.sha256")
    return json.loads(raw), h


# ----------------------------------------------------------------- utilidades
def hash_serie(s):
    return hashlib.sha256(pd.util.hash_pandas_object(s, index=True).values.tobytes()).hexdigest()


def close_de(sym, corte):
    df = D.cargar_precios(sym)
    c = pd.to_numeric(df["close"], errors="coerce").dropna()
    c = c[(c > 0) & (c.index <= pd.Timestamp(corte))]
    return c[~c.index.duplicated(keep="last")]


def logit_fit(X, y, lam=10.0):
    mu, sd = X.mean(0), X.std(0)
    sd = np.where(sd < 1e-12, 1.0, sd)
    Z = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    k = Z.shape[1]
    pen = np.diag([0.0] + [lam] * (k - 1))
    ym = float(np.clip(y.mean(), 1e-4, 1 - 1e-4))
    beta = np.zeros(k)
    beta[0] = np.log(ym / (1 - ym))
    for _ in range(100):
        p = 1 / (1 + np.exp(-np.clip(Z @ beta, -30, 30)))
        w = np.maximum(p * (1 - p), 1e-7)
        grad = Z.T @ (p - y) + pen @ beta
        hess = (Z.T * w) @ Z + pen + np.eye(k) * 1e-9
        step = np.linalg.solve(hess, grad)
        beta -= step
        if np.max(np.abs(step)) < 1e-9:
            break
    return {"mu": mu, "sd": sd, "beta": beta}


def logit_pred(m, X):
    Z = np.column_stack([np.ones(len(X)), (X - m["mu"]) / m["sd"]])
    return 1 / (1 + np.exp(-np.clip(Z @ m["beta"], -30, 30)))


def bootstrap_mejora(d, bloque, rondas, semilla):
    """Media de d y p unilateral (H0: media <= 0) por bootstrap circular de bloques."""
    d = np.asarray(d, float)
    n = len(d)
    rng = np.random.default_rng(semilla + n)
    b = max(1, min(int(bloque), n))
    nb = int(np.ceil(n / b))
    starts = rng.integers(0, n, size=(rondas, nb))
    idx = (starts[:, :, None] + np.arange(b)[None, None, :]) % n
    medias = d[idx.reshape(rondas, -1)[:, :n]].mean(1)
    lo, hi = np.quantile(medias, [0.025, 0.975])
    p = (1 + np.count_nonzero(medias <= 0)) / (rondas + 1)
    return {"mejora": float(d.mean()), "ic95": [float(lo), float(hi)], "p": float(p)}


def bh(pvals):
    idx = [i for i, p in enumerate(pvals) if p is not None]
    m = len(idx)
    out = [None] * len(pvals)
    orden = sorted(idx, key=lambda i: pvals[i])
    q = 1.0
    for r in range(m, 0, -1):
        i = orden[r - 1]
        q = min(q, pvals[i] * m / r)
        out[i] = float(min(1.0, q))
    return out


def rasgos_precio(c):
    r = np.log(c).diff()
    f = pd.DataFrame({
        "r1": np.log(c / c.shift(1)),
        "r5": np.log(c / c.shift(5)),
        "r21": np.log(c / c.shift(21)),
        "lvol": np.log(r.rolling(21).std().clip(lower=1e-6)),
    })
    return f


# ------------------------------------------------------- niveles 1 y 2 (celdas)
def tramos(pr):
    p = pr["datos"]["particion"]
    return {k: (pd.Timestamp(v[0] if v[0] != "inicio" else "1900-01-01"), pd.Timestamp(v[1])) for k, v in p.items()}


def celda_direccion(c, h, pr, abrir):
    est = pr["estadistica"]
    T = tramos(pr)
    f = rasgos_precio(c)
    fut = c.shift(-h)
    y = (fut > c).astype(float)
    fecha_obj = pd.Series(c.index, index=c.index).shift(-h)
    df = f.copy()
    df["y"] = y
    df["fo"] = fecha_obj
    df = df[fut.notna() & f.notna().all(axis=1)]

    def seg(a, b):
        return df[(df.index >= a) & (df.index <= b) & (df["fo"] <= b)]

    tr, va = seg(*T["entrenamiento"]), seg(*T["validacion"])
    te = seg(*T["prueba_sellada"]) if abrir else None
    if len(tr) < pr["modelo_direccion"]["min_n_ajuste"] or len(va) < 100:
        return {"estado": "datos_insuficientes", "n_entrenamiento": int(len(tr)), "n_validacion": int(len(va))}
    cols = ["r1", "r5", "r21", "lvol"]
    out = {"horizonte": h, "n_entrenamiento": int(len(tr)), "n_validacion": int(len(va)),
           "inicio_datos": str(c.index.min().date())}

    def evaluar(modelo_df, ajuste_df, nombre):
        m = logit_fit(ajuste_df[cols].to_numpy(), ajuste_df["y"].to_numpy())
        yy = modelo_df["y"].to_numpy()
        p = logit_pred(m, modelo_df[cols].to_numpy())
        base = float(ajuste_df["y"].mean())
        d_brier = (yy - base) ** 2 - (yy - p) ** 2
        acc_m = ((p > 0.5) == (yy == 1)).astype(float)
        acc_up = (yy == 1).astype(float)
        d_acc = acc_m - acc_up
        bl = max(10, 2 * h)
        s = est["semilla"]
        res = {"n": int(len(yy)), "tasa_base_ajuste": base, "tasa_alza": float(yy.mean()),
               "brier_modelo": float(np.mean((yy - p) ** 2)), "brier_tasa_base": float(np.mean((yy - base) ** 2)),
               "exactitud_modelo": float(acc_m.mean()), "exactitud_siempre_sube": float(acc_up.mean()),
               "brier": bootstrap_mejora(d_brier, bl, est["bootstrap_rondas"], s),
               "exactitud": bootstrap_mejora(d_acc, bl, est["bootstrap_rondas"], s + 1)}
        return res

    out["validacion"] = evaluar(va, tr, "validacion")
    if abrir:
        if len(te) < 100:
            return {"estado": "datos_insuficientes", "n_prueba": int(len(te))}
        ajuste = pd.concat([tr, va])
        out["prueba"] = evaluar(te, ajuste, "prueba")
        out["n_prueba"] = int(len(te))
    out["estado"] = "evaluada"
    return out


def aprobar_celda(cel):
    """Aprobada si q de Brier y de exactitud < 0.05 y mejoras medias > 0 en prueba y validación."""
    if cel.get("estado") != "evaluada" or "prueba" not in cel:
        return False
    t, v = cel["prueba"], cel["validacion"]
    return bool(t["brier"]["q"] is not None and t["brier"]["q"] < 0.05 and t["exactitud"]["q"] < 0.05
                and t["brier"]["mejora"] > 0 and t["exactitud"]["mejora"] > 0
                and v["brier"]["mejora"] > 0)


def aplicar_bh(celdas, bloques=("validacion", "prueba")):
    """Una familia por bloque; BH sobre todas las pruebas (Brier y exactitud) del nivel."""
    for bloque in bloques:
        refs = []
        for cel in celdas:
            if cel.get("estado") == "evaluada" and bloque in cel:
                for k in ("brier", "exactitud") if "brier" in cel[bloque] else ("magnitud",):
                    if k in cel[bloque]:
                        refs.append(cel[bloque][k])
        qs = bh([r["p"] for r in refs])
        for r, q in zip(refs, qs):
            r["q"] = q


# ----------------------------------------------------------------- nivel 3
def sesion_reaccion(idx, fecha, available_at, es_resultado):
    d = pd.Timestamp(fecha)
    if es_resultado:
        ny = available_at.tz_convert("America/New_York")
        d = pd.Timestamp(ny.date())
        despues = ny.hour >= 16
    else:
        despues = False
    pos = idx.searchsorted(d)  # primera sesión >= d
    if pos >= len(idx):
        return None
    if despues and idx[pos] == d:
        pos += 1
    elif despues and idx[pos] > d:
        pass  # ya cae en una sesión posterior
    return pos if pos < len(idx) else None


def eventos_nivel3(pr):
    cfg = pr["nivel3"]
    ev = D.cargar_eventos()
    corte = pd.Timestamp(pr["datos"]["corte_datos"])
    salida = {}

    cfg_dias = pr["datos"]["evento_macro_min_dias"]

    def macro(tipo, activo, desde):
        e = ev[(ev.tipo == tipo) & (ev.fecha >= desde) & (ev.fecha <= corte)].sort_values("fecha")
        if tipo in ("CPI", "EMPLEO"):
            kept, last = [], None
            for _, r in e.iterrows():
                if last is None or (r.fecha - last).days >= cfg_dias:
                    kept.append(r)
                    last = r.fecha
            e = pd.DataFrame(kept)
        return [(r.fecha, r.available_at, False) for r in e.itertuples()]

    for tipo in ("FOMC", "CPI", "EMPLEO"):
        c = cfg["eventos"][tipo]
        salida[tipo] = (c["activo"], macro(tipo, c["activo"], pd.Timestamp(c["desde"])))
    for t in cfg["eventos"]["RESULTADOS"]["activos"]:
        e = ev[(ev.tipo == "8-K") & (ev.ticker == t) & ev.detalle.str.contains(r"(?:^|,)2\.02(?:,|$)") & (ev.fecha <= corte)]
        e = e.sort_values("available_at").drop_duplicates("fecha")
        salida["RES_" + t] = (t, [(r.fecha, r.available_at, True) for r in e.itertuples()])
    return salida


def tabla_eventos(c, eventos):
    idx = c.index
    f = rasgos_precio(c)
    filas, vistos = [], set()
    for fecha, disp, es_res in eventos:
        pos = sesion_reaccion(idx, fecha, disp, es_res)
        if pos is None or pos < 25 or pos in vistos:
            continue
        vistos.add(pos)
        R = float(np.log(c.iloc[pos] / c.iloc[pos - 1]))
        ft = f.iloc[pos - 1]  # rasgos con datos hasta t-1
        if ft.isna().any():
            continue
        filas.append({"fecha": idx[pos], "R": R, "y": float(R > 0), "s": float(np.log(max(abs(R), 1e-4))),
                      "r1": ft.r1, "r5": ft.r5, "r21": ft.r21, "lvol": ft.lvol})
    return pd.DataFrame(filas)


def celdas_evento(df, pr, abrir, rondas, semilla, nombre):
    T = tramos(pr)
    mins = pr["nivel3"]["minimos"]
    tr = df[(df.fecha <= T["entrenamiento"][1])]
    va = df[(df.fecha >= T["validacion"][0]) & (df.fecha <= T["validacion"][1])]
    te = df[(df.fecha >= T["prueba_sellada"][0]) & (df.fecha <= T["prueba_sellada"][1])] if abrir else None
    if len(tr) < mins["n_ajuste"] or len(va) < mins["n_validacion"] or (abrir and len(te) < mins["n_prueba"]):
        return [{"evento": nombre, "tipo": "ambas", "estado": "datos_insuficientes",
                 "n_ajuste": int(len(tr)), "n_validacion": int(len(va)), "n_prueba": None if te is None else int(len(te))}]
    cols = ["r1", "r5", "r21", "lvol"]
    d_cell = {"evento": nombre, "tipo": "direccion", "estado": "evaluada", "n_ajuste": int(len(tr)), "n_validacion": int(len(va))}
    s_cell = {"evento": nombre, "tipo": "tamano", "estado": "evaluada", "n_ajuste": int(len(tr)), "n_validacion": int(len(va))}

    def dir_eval(m_df, a_df):
        m = logit_fit(a_df[cols].to_numpy(), a_df["y"].to_numpy())
        yy, p = m_df["y"].to_numpy(), logit_pred(m, m_df[cols].to_numpy())
        base = float(a_df["y"].mean())
        d_b = (yy - base) ** 2 - (yy - p) ** 2
        acc_m = ((p > .5) == (yy == 1)).astype(float)
        acc_up = (yy == 1).astype(float)
        return {"n": int(len(yy)), "tasa_base_ajuste": base, "tasa_alza": float(yy.mean()),
                "brier_modelo": float(np.mean((yy - p) ** 2)), "brier_tasa_base": float(np.mean((yy - base) ** 2)),
                "exactitud_modelo": float(acc_m.mean()), "exactitud_siempre_sube": float(acc_up.mean()),
                "brier": bootstrap_mejora(d_b, 1, rondas, semilla), "exactitud": bootstrap_mejora(acc_m - acc_up, 1, rondas, semilla + 1)}

    def size_eval(m_df, a_df):
        x, s = a_df["lvol"].to_numpy(), a_df["s"].to_numpy()
        A = np.column_stack([np.ones(len(x)), x])
        coef = np.linalg.lstsq(A, s, rcond=None)[0]
        yy = m_df["s"].to_numpy()
        pred = coef[0] + coef[1] * m_df["lvol"].to_numpy()
        ref = float(s.mean())
        d = (yy - ref) ** 2 - (yy - pred) ** 2
        return {"n": int(len(yy)), "mse_modelo": float(np.mean((yy - pred) ** 2)), "mse_referencia_media": float(np.mean((yy - ref) ** 2)),
                "abs_retorno_medio": float(np.exp(yy).mean()), "pendiente_lvol": float(coef[1]),
                "magnitud": bootstrap_mejora(d, 1, rondas, semilla + 2)}

    d_cell["validacion"], s_cell["validacion"] = dir_eval(va, tr), size_eval(va, tr)
    if abrir:
        aj = pd.concat([tr, va])
        d_cell["prueba"], s_cell["prueba"] = dir_eval(te, aj), size_eval(te, aj)
        d_cell["n_prueba"] = s_cell["n_prueba"] = int(len(te))
    return [d_cell, s_cell]


def aprobar_evento(cel):
    if cel.get("estado") != "evaluada" or "prueba" not in cel:
        return False
    t, v = cel["prueba"], cel["validacion"]
    if cel["tipo"] == "direccion":
        return bool(t["brier"]["q"] < 0.05 and t["exactitud"]["q"] < 0.05 and t["brier"]["mejora"] > 0
                    and t["exactitud"]["mejora"] > 0 and v["brier"]["mejora"] > 0)
    return bool(t["magnitud"]["q"] < 0.05 and t["magnitud"]["mejora"] > 0 and v["magnitud"]["mejora"] > 0)


# ----------------------------------------------------------------- nivel 5
def _dd(equity):
    pico = np.maximum.accumulate(equity)
    return float(np.max(1 - equity / pico))


def posiciones(c, regla):
    r = np.log(c).diff()
    if regla == "tendencia":
        sma = c.rolling(200).mean()
        sig = (c > sma).astype(float).where(sma.notna())
    else:
        vol = r.rolling(21).std() * np.sqrt(252)
        sig = (~(vol > 0.25)).astype(float).where(vol.notna())
    return sig.shift(1)  # decidida al cierre t-1, vale para el retorno de t


def retornos_estrategia(ret, pos, costo):
    pos = pos.reindex(ret.index)
    cambio = pos.diff().abs().fillna(0)
    return ret * pos - costo * cambio


def metricas_ventana(r, a, b):
    seg = r[(r.index > pd.Timestamp(a)) & (r.index <= pd.Timestamp(b))].dropna()
    eq = (1 + seg).cumprod().to_numpy()
    return {"caida_max": _dd(np.concatenate([[1.0], eq])), "retorno_total": float(eq[-1] - 1), "sesiones": int(len(seg))}


def cagr(r):
    r = r.dropna()
    years = len(r) / 252
    return float((1 + r).prod() ** (1 / years) - 1)


def nivel5(pr, abrir):
    cfg = pr["nivel5"]
    c = close_de("^GSPC", pr["datos"]["corte_datos"])
    ret = c.pct_change()
    costo = cfg["costo_por_cambio_de_posicion"]
    ventanas = cfg["crisis_apartadas"]
    rng = np.random.default_rng(pr["estadistica"]["semilla"] + 5)
    n_rand = 2000
    res = {"reglas": {}}
    hold_w = {k: metricas_ventana(ret, *v) for k, v in ventanas.items()}
    for regla in ("tendencia", "volatilidad"):
        pos = posiciones(c, regla)
        st = retornos_estrategia(ret, pos, costo)
        valido = pos.notna()
        full_h, full_s = ret[valido], st[valido]
        w = {k: metricas_ventana(st, *v) for k, v in ventanas.items()}
        reduc = {k: (hold_w[k]["caida_max"] - w[k]["caida_max"]) / hold_w[k]["caida_max"] for k in ventanas}
        # Fracción invertida y duración media de rachas, para el calendario aleatorio.
        p = pos[valido].to_numpy()
        frac = float(p.mean())
        cambios = np.flatnonzero(np.diff(p) != 0)
        L1 = float(np.mean(np.diff(np.concatenate([[0], cambios, [len(p) - 1]]))[p[np.concatenate([[0], cambios + 1])] == 1])) if frac > 0 else 1
        L0 = float(np.mean(np.diff(np.concatenate([[0], cambios, [len(p) - 1]]))[p[np.concatenate([[0], cambios + 1])] == 0])) if frac < 1 else 1
        rand_stat = np.empty(n_rand)
        N = len(ret)
        for k in range(n_rand):
            largos, est, tot = [], int(rng.random() < frac), 0
            runs = []
            while tot < N + 5:
                ln = int(rng.geometric(1 / (L1 if est else L0)))
                runs.append(np.full(ln, float(est)))
                tot += ln
                est = 1 - est
            sched = pd.Series(np.concatenate(runs)[:N], index=ret.index)
            sr = retornos_estrategia(ret, sched, costo)
            red = []
            for kk, v in ventanas.items():
                m = metricas_ventana(sr, *v)
                red.append((hold_w[kk]["caida_max"] - m["caida_max"]) / hold_w[kk]["caida_max"])
            rand_stat[k] = np.mean(red)
        obs = float(np.mean(list(reduc.values())))
        pval = float((1 + np.count_nonzero(rand_stat >= obs)) / (n_rand + 1))
        res["reglas"][regla] = {
            "ventanas": {k: {"mantener": hold_w[k], "regla": w[k], "reduccion_caida_max": float(reduc[k])} for k in ventanas},
            "reduccion_media_obs": obs, "reduccion_media_aleatoria": float(rand_stat.mean()), "p_temporizacion_aleatoria": pval,
            "fraccion_invertida": frac, "racha_media_invertida": L1, "racha_media_efectivo": L0,
            "cagr_mantener_1950_2026": cagr(full_h), "cagr_regla_1950_2026": cagr(full_s),
            "caida_max_mantener_1950_2026": _dd((1 + full_h.dropna()).cumprod().to_numpy()),
            "caida_max_regla_1950_2026": _dd((1 + full_s.dropna()).cumprod().to_numpy()),
            "cambios_posicion": int(len(cambios)),
        }
    qs = bh([res["reglas"][r]["p_temporizacion_aleatoria"] for r in res["reglas"]])
    for r, q in zip(res["reglas"], qs):
        x = res["reglas"][r]
        x["q_bh"] = q
        n_ok = sum(1 for k in ventanas if x["ventanas"][k]["regla"]["caida_max"] <= 0.70 * x["ventanas"][k]["mantener"]["caida_max"])
        x["ventanas_con_reduccion_30pct"] = n_ok
        x["perdida_cagr_pp"] = (x["cagr_mantener_1950_2026"] - x["cagr_regla_1950_2026"]) * 100
        x["aprobada"] = bool(n_ok >= 3 and x["perdida_cagr_pp"] <= 1.5 and q < 0.05)
    res["aprobado"] = any(v["aprobada"] for v in res["reglas"].values())
    res["datos_sha256"] = hash_serie(c)
    return res



def resumen_web(r):
    """Registro compacto del currículo para la pantalla Nivel (solo resume, no recalcula)."""
    n1 = r["nivel1"]["celda"]["prueba"]
    c2 = [x for x in r["nivel2"]["celdas"] if x.get("estado") == "evaluada"]
    mejores = sorted(c2, key=lambda x: x["prueba"]["brier"]["p"])[:6]
    c3 = [x for x in r["nivel3"]["celdas"] if x.get("estado") == "evaluada"]
    n5 = r["nivel5"]["reglas"]
    tend, vol = n5["tendencia"], n5["volatilidad"]

    def fila(x):
        t = x["prueba"]
        return {"activo": x["activo"], "horizonte": x["horizonte"], "n": t["n"], "brier_modelo": t["brier_modelo"],
                "brier_base": t["brier_tasa_base"], "mejora": t["brier"]["mejora"], "p": t["brier"]["p"],
                "q": t["brier"]["q"], "mejora_validacion": x["validacion"]["brier"]["mejora"]}

    def fila3(x):
        t = x["prueba"]
        if x["tipo"] == "direccion":
            return {"evento": x["evento"], "tipo": "dirección", "n": t["n"], "mejora": t["brier"]["mejora"], "p": t["brier"]["p"],
                    "q": t["brier"]["q"], "mejora_validacion": x["validacion"]["brier"]["mejora"]}
        return {"evento": x["evento"], "tipo": "tamaño", "n": t["n"], "mejora": t["magnitud"]["mejora"], "p": t["magnitud"]["p"],
                "q": t["magnitud"]["q"], "mejora_validacion": x["validacion"]["magnitud"]["mejora"]}

    return {
        "version": r["version"], "corte_datos": r["corte_datos"], "particion": r["particion"],
        "prereg_sha256": r["prereg_sha256"], "prereg_commit": r["prereg_commit"],
        "aperturas_prueba_sellada": json.loads(REGISTRO.read_text(encoding="utf-8"))["aperturas"],
        "nivel_actual": 1, "aprobados": r["aprobados"],
        "nivel1": {"estado": r["nivel1"]["estado"], "activo": "^GSPC", "horizonte": 1, "n": n1["n"],
                   "brier_modelo": n1["brier_modelo"], "brier_base": n1["brier_tasa_base"], "mejora": n1["brier"]["mejora"],
                   "ic95": n1["brier"]["ic95"], "p": n1["brier"]["p"], "q": n1["brier"]["q"],
                   "exactitud_modelo": n1["exactitud_modelo"], "exactitud_siempre_sube": n1["exactitud_siempre_sube"]},
        "nivel2": {"estado": r["nivel2"]["estado"], "familia_n": r["nivel2"]["familia_n"], "celdas_aprobadas": r["nivel2"]["celdas_aprobadas"],
                   "celdas_con_mejora_positiva": sum(1 for x in c2 if x["prueba"]["brier"]["mejora"] > 0),
                   "mejores": [fila(x) for x in mejores]},
        "nivel3": {"estado": r["nivel3"]["estado"], "familia_n": r["nivel3"]["familia_n"], "celdas_aprobadas": r["nivel3"]["celdas_aprobadas"],
                   "celdas": [fila3(x) for x in c3],
                   "insuficientes": [x["evento"] for x in r["nivel3"]["celdas"] if x.get("estado") == "datos_insuficientes"]},
        "nivel4": {"estado": "sin_evaluacion", "motivo": "GDELT entrega hora de indexación, no de publicación, y no hay corpus histórico clasificado y congelado."},
        "nivel5": {"estado": "aprobado" if r["nivel5"]["aprobado"] else "no_aprobado",
                   "reglas": {k: {"aprobada": v["aprobada"], "ventanas_con_reduccion_30pct": v["ventanas_con_reduccion_30pct"],
                                  "perdida_cagr_pp": v["perdida_cagr_pp"], "q": v["q_bh"], "p": v["p_temporizacion_aleatoria"],
                                  "reduccion_media": v["reduccion_media_obs"], "reduccion_media_aleatoria": v["reduccion_media_aleatoria"],
                                  "cagr_mantener": v["cagr_mantener_1950_2026"], "cagr_regla": v["cagr_regla_1950_2026"],
                                  "ventanas": {w: {"dd_mantener": y["mantener"]["caida_max"], "dd_regla": y["regla"]["caida_max"],
                                                   "ret_mantener": y["mantener"]["retorno_total"], "ret_regla": y["regla"]["retorno_total"]}
                                               for w, y in v["ventanas"].items()}} for k, v in n5.items()}},
        "nivel6": {"estado": "sin_evaluacion", "motivo": "Falta un panel PIT sincronizado de tasas, dólar, oro y tecnología."},
        "nivel7": {"estado": "sin_evaluacion", "motivo": "Falta simulación completa con dividendos, spread, tarifas XTB y benchmark de aportes."},
    }

# ----------------------------------------------------------------- principal
def commit_prereg():
    try:
        return subprocess.run(["git", "log", "-1", "--format=%H", "--", str(PREREG_PATH)], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def ejecutar(abrir):
    pr, h = cargar_prereg()
    if abrir and REGISTRO.exists():
        reg = json.loads(REGISTRO.read_text(encoding="utf-8"))
        if any(int(v) > 0 for v in reg.get("aperturas", {}).values()):
            raise RuntimeError("La prueba sellada de oraculo-v2 ya se abrió; no se reabre")
    est = pr["estadistica"]
    corte = pr["datos"]["corte_datos"]
    rondas, semilla = est["bootstrap_rondas"], est["semilla"]
    series = {}

    def serie(sym):
        if sym not in series:
            series[sym] = close_de(sym, corte)
        return series[sym]

    # Nivel 1
    c1 = pr["nivel1"]
    cel1 = celda_direccion(serie(c1["activo"]), c1["horizonte"], pr, abrir)
    cel1["activo"] = c1["activo"]
    aplicar_bh([cel1])
    # Nivel 2
    celdas2 = []
    for a in pr["nivel2"]["activos"]:
        for hz in pr["nivel2"]["horizontes"]:
            cel = celda_direccion(serie(a), hz, pr, abrir)
            cel["activo"], cel["horizonte"] = a, hz
            celdas2.append(cel)
    aplicar_bh(celdas2)
    # Nivel 3
    evs = eventos_nivel3(pr)
    celdas3, pool = [], []
    for nombre, (activo, lista) in evs.items():
        df = tabla_eventos(serie(activo), lista)
        if nombre.startswith("RES_"):
            df = df.assign(ticker=activo)
            pool.append(df)
        celdas3 += celdas_evento(df, pr, abrir, rondas, semilla, nombre)
    if pool:
        celdas3 += celdas_evento(pd.concat(pool).sort_values("fecha").reset_index(drop=True), pr, abrir, rondas, semilla, "RESULTADOS_7_acciones")
    aplicar_bh(celdas3)
    # Nivel 5 solo cuando se abre la prueba (las crisis son la prueba apartada)
    n5 = nivel5(pr, abrir) if abrir else {"estado": "no_abierta"}

    ok1 = aprobar_celda(cel1)
    ok2 = sum(aprobar_celda(x) for x in celdas2)
    ok3 = sum(aprobar_evento(x) for x in celdas3)
    nivel_ok = {1: ok1, 2: ok2 >= 2, 3: ok3 >= 2, 5: bool(n5.get("aprobado"))}
    # BH global sobre niveles 1-3 (prueba): todas las pruebas
    glob = []
    if abrir:
        for cel in [cel1] + celdas2 + celdas3:
            if cel.get("estado") == "evaluada" and "prueba" in cel:
                for k in ("brier", "exactitud", "magnitud"):
                    if k in cel["prueba"]:
                        glob.append(cel["prueba"][k])
        for r, q in zip(glob, bh([g["p"] for g in glob])):
            r["q_global"] = q
    resultado = {
        "version": pr["version"], "prereg_sha256": h, "prereg_commit": commit_prereg(),
        "generado_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "modo": "prueba_abierta" if abrir else "solo_validacion",
        "corte_datos": corte, "particion": pr["datos"]["particion"],
        "manifiesto_datos_sha256": {k: hash_serie(v) for k, v in series.items()},
        "nivel1": {"estado": "aprobado" if ok1 else "no_aprobado", "celda": cel1},
        "nivel2": {"estado": "aprobado" if nivel_ok[2] else "no_aprobado", "celdas_aprobadas": ok2,
                   "celdas": celdas2, "familia_n": sum(1 for x in celdas2 if x.get("estado") == "evaluada")},
        "nivel3": {"estado": "aprobado" if nivel_ok[3] else "no_aprobado", "celdas_aprobadas": ok3, "celdas": celdas3,
                   "familia_n": sum(1 for x in celdas3 if x.get("estado") == "evaluada")},
        "nivel5": n5,
        "aprobados": [n for n, ok in nivel_ok.items() if ok] if abrir else [],
    }
    destino = SALIDA if abrir else SALIDA_VAL
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps(resultado, indent=1, ensure_ascii=False, default=float), encoding="utf-8")
    if abrir:
        REGISTRO.write_text(json.dumps({
            "version": pr["version"], "prereg_sha256": h, "prereg_commit": commit_prereg(),
            "aperturas": {"nivel1": 1, "nivel2": 1, "nivel3": 1, "nivel4": 0, "nivel5": 1, "nivel6": 0, "nivel7": 0},
            "abierta_utc": resultado["generado_utc"]}, indent=1), encoding="utf-8")
    return resultado


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    if modo == "--resumen":
        out = resumen_web(json.loads(SALIDA.read_text(encoding="utf-8")))
        (ROOT / "resultados" / "nivel_web.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        sys.exit(0)
    if modo not in ("--validacion", "--abrir-prueba"):
        sys.exit("uso: python -m lab.oraculo_v2 --validacion | --abrir-prueba")
    r = ejecutar(modo == "--abrir-prueba")
    print(json.dumps({k: r[k] for k in ("modo", "aprobados")}, ensure_ascii=False))
