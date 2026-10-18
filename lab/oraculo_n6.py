"""Oráculo nivel 6: señales intermercado. Sigue lab/oraculo_n6_prereg.json (sha256 verificado)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
PREREG = RAIZ / "lab" / "oraculo_n6_prereg.json"
PREREG_SHA = RAIZ / "lab" / "oraculo_n6_prereg.sha256"
SALIDA = RAIZ / "resultados" / "oraculo_n6.json"
PRECIOS = RAIZ / "datos" / "pit" / "precios"


def cargar_prereg():
    datos = PREREG.read_bytes()
    real = hashlib.sha256(datos).hexdigest()
    esperado = PREREG_SHA.read_text().split()[0]
    if real != esperado:
        raise RuntimeError(f"sha256 del prereg no coincide: {esperado} vs {real}. Abortado.")
    return json.loads(datos), real


def cierre(simbolo):
    df = pd.read_csv(PRECIOS / f"{simbolo}.csv.gz", parse_dates=["date"])
    return df.set_index("date")["close"].astype(float)


def filas_mensuales(px, ventanas):
    """Una fila por mes: decisión el primer día hábil con el cierre previo."""
    spy = px["SPY"]
    dias = spy.index
    primeros = pd.Series(dias, index=dias).groupby([dias.year, dias.month]).first().tolist()
    cierres_previos = []
    for d in primeros:
        i = dias.get_loc(d)
        if i > 0:
            cierres_previos.append(i - 1)
    filas = []
    for k in range(len(cierres_previos) - 1):
        i, j = cierres_previos[k], cierres_previos[k + 1]
        if i < 126:
            continue
        mes = dias[i + 1].strftime("%Y-%m")
        fila = {"mes": mes, "ret": spy.iloc[j] / spy.iloc[i] - 1}
        f = {}
        for nombre, otro, v in (("S1", "TLT", 63), ("S2", "GLD", 126), ("S3", "QQQ", 63)):
            serie = px[otro].reindex(dias).ffill()
            if np.isnan(serie.iloc[i - v]) or np.isnan(serie.iloc[i]):
                f[nombre] = None
                continue
            r_o = serie.iloc[i] / serie.iloc[i - v] - 1
            r_s = spy.iloc[i] / spy.iloc[i - v] - 1
            mayor = r_o > r_s
            f[nombre] = (not mayor) if nombre in ("S1", "S2") else mayor  # True = 'sube'
        fila.update(f)
        filas.append(fila)
    return pd.DataFrame(filas)


def diferencia(df, s):
    sub = df[df[s].notna()]
    sube = sub[sub[s].astype(bool)]["ret"]
    baja = sub[~sub[s].astype(bool)]["ret"]
    if len(sube) == 0 or len(baja) == 0:
        return None
    return float(sube.mean() - baja.mean())


def bh(ps):
    m = len(ps)
    orden = sorted(range(m), key=lambda k: ps[k])
    q = [0.0] * m
    previo = 1.0
    for rango in range(m, 0, -1):
        k = orden[rango - 1]
        previo = min(previo, ps[k] * m / rango)
        q[k] = previo
    return q


def tasa(df, s):
    sub = df[df[s].notna()]
    acierto = ((sub[s].astype(bool)) == (sub["ret"] > 0)).mean()
    return float(acierto), float((sub["ret"] > 0).mean())


def main():
    pre, sha = cargar_prereg()
    px = {s: cierre(s) for s in ("SPY", "TLT", "GLD", "QQQ")}
    df = filas_mensuales(px, pre["datos"]["ventanas_retorno_sesiones"])
    val = df[(df.mes >= "2005-01") & (df.mes <= "2014-12")]
    pru = df[(df.mes >= "2015-01") & (df.mes <= "2026-08")]
    rng = np.random.default_rng(pre["estadistica"]["semilla"])
    rondas = pre["estadistica"]["bootstrap_rondas"]
    senales = ["S1", "S2", "S3"]
    res = {}
    for s in senales:
        d_val, d_pru = diferencia(val, s), diferencia(pru, s)
        res[s] = {"dif_validacion": d_val, "dif_prueba": d_pru,
                  "n_validacion": int(val[s].notna().sum()), "n_prueba": int(pru[s].notna().sum()),
                  "acierto_prueba_vs_base": tasa(pru, s)}
    ps = [p_unilateral(pru, s, rondas, rng) for s in senales]
    qs = bh(ps)
    aprobadas = []
    for s, p, q in zip(senales, ps, qs):
        res[s].update({"p": p, "q_BH": q})
        ok = q < 0.05 and (res[s]["dif_prueba"] or 0) > 0 and (res[s]["dif_validacion"] or 0) > 0
        res[s]["aprobada"] = bool(ok)
        if ok:
            aprobadas.append(s)
    out = {"prereg_sha256": sha, "ejecutado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "senales": res, "nivel6_aprobado": bool(aprobadas)}
    SALIDA.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


def p_unilateral(df, s, rondas, rng, bloque=3):
    """p = (1 + #{dif remuestreada centrada <= 0 ... }) : H0 de diferencia nula por bootstrap centrado."""
    sub = df[df[s].notna()].reset_index(drop=True)
    n = len(sub)
    ret, sen = sub["ret"].to_numpy(), sub[s].astype(bool).to_numpy()
    obs = ret[sen].mean() - ret[~sen].mean()
    cuenta, validas = 0, 0
    for _ in range(rondas):
        idx = []
        while len(idx) < n:
            ini = rng.integers(0, n)
            idx.extend((ini + np.arange(bloque)) % n)
        idx = np.array(idx[:n])
        r, g = ret[idx], sen[idx]
        if g.all() or (~g).all():
            continue
        validas += 1
        d = r[g].mean() - r[~g].mean()
        if d - obs >= obs:  # diferencia centrada >= obs: contraparte unilateral bajo H0
            cuenta += 1
    return (1 + cuenta) / (validas + 1)


if __name__ == "__main__":
    main()
