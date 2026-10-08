"""Fábrica de hipótesis: selección cronológica, bootstrap por día y FDR BH.

La pantalla termina el 31 de marzo de 2025. Solo un candidato aprobado abre el
periodo final reservado, una vez. Ese resultado final no ajusta parámetros.
"""
import hashlib
import itertools
import json
import random
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from . import archivo

ROOT = Path(__file__).resolve().parents[1]
PANTALLA_DESDE = "2024-01-01"
PANTALLA_HASTA = "2025-04-01"
RESERVA_DESDE = PANTALLA_HASTA
COSTO = .001


def variantes(raiz=None):
    raiz = Path(raiz or ROOT / "ideas")
    for ruta in sorted(raiz.glob("*.json")):
        plantilla = json.loads(ruta.read_text(encoding="utf-8"))
        for campo in ("fuente", "hipotesis", "entrada", "salida", "activo", "horizonte_minutos", "lookback_minutos", "umbral", "costo_por_lado"):
            if campo not in plantilla:
                raise ValueError(f"{ruta.name}: falta {campo}")
        if plantilla["costo_por_lado"] != COSTO or plantilla["entrada"] not in ("momentum", "reversion", "ruptura", "volatilidad", "horario"):
            raise ValueError(f"{ruta.name}: regla o costo no admitidos")
        if not plantilla["fuente"]["url"].startswith("https://"):
            raise ValueError(f"{ruta.name}: fuente sin enlace HTTPS")
        claves = [k for k in ("activo", "horizonte_minutos", "lookback_minutos", "umbral", "hora_utc") if k in plantilla]
        for valores in itertools.product(*(plantilla[k] for k in claves)):
            regla = dict(zip(claves, valores), familia=plantilla["id"], entrada=plantilla["entrada"],
                         salida=plantilla["salida"], costo_por_lado=COSTO, fuente=plantilla["fuente"]["url"])
            if regla["activo"] not in ("BTC", "ETH") or regla["horizonte_minutos"] < 1 or regla["lookback_minutos"] < 1:
                raise ValueError("Activo o plazo inválido")
            regla["id"] = hashlib.sha256(json.dumps(regla, sort_keys=True).encode()).hexdigest()[:16]
            yield regla


def senal(regla, df, i):
    lb = regla["lookback_minutos"]
    if i < lb or df.index[i]-df.index[i-lb] != pd.Timedelta(minutes=lb):
        return False
    anterior, ahora = float(df.close.iat[i-lb]), float(df.close.iat[i])
    ret = ahora / anterior - 1
    umbral = regla["umbral"]
    familia = regla["entrada"]
    if familia == "momentum": return ret > umbral
    if familia == "reversion": return ret < -umbral
    if familia == "ruptura": return ahora > float(df.high.iloc[i-lb:i].max()) * (1 + umbral)
    if familia == "volatilidad": return (float(df.high.iloc[i-lb:i+1].max()) / float(df.low.iloc[i-lb:i+1].min()) - 1 > umbral and ret > 0)
    return df.index[i].hour == regla["hora_utc"] and ret > umbral


def dia(regla, df, semilla):
    """Entrada en apertura futura; salida al cierre exacto del horizonte."""
    h = regla["horizonte_minutos"]
    lb = regla["lookback_minutos"]
    if len(df) < lb + h + 2:
        return None
    primero = None
    for i in range(lb, len(df)-h-1):
        if not senal(regla, df, i):
            continue
        entrada, salida = df.index[i+1], df.index[i+h]
        if entrada-df.index[i] != pd.Timedelta(minutes=1) or salida-df.index[i] != pd.Timedelta(minutes=h):
            continue
        primero = i
        break
    mantener = (float(df.close.iat[-1]) / float(df.open.iat[0])) * (1-COSTO)**2 - 1
    if primero is None:
        return 0., 0., mantener, False
    i = primero
    neto = (float(df.close.iat[i+h]) / float(df.open.iat[i+1])) * (1-COSTO)**2 - 1
    posibles = [j for j in range(lb, len(df)-h-1) if df.index[j]-df.index[j-lb] == pd.Timedelta(minutes=lb)
                and df.index[j+1]-df.index[j] == pd.Timedelta(minutes=1)
                and df.index[j+h]-df.index[j] == pd.Timedelta(minutes=h)]
    j = random.Random(semilla).choice(posibles)
    azar = (float(df.close.iat[j+h]) / float(df.open.iat[j+1])) * (1-COSTO)**2 - 1
    return neto, azar, mantener, True


def evaluar(regla, velas):
    filas = []
    for fecha, frame in velas.groupby(velas.index.strftime("%Y-%m-%d")):
        resultado = dia(regla, frame, int(hashlib.sha256((regla["id"]+fecha).encode()).hexdigest()[:12], 16))
        if resultado is not None:
            filas.append((fecha, *resultado))
    if not filas:
        return {"dias": 0, "operaciones": 0, "neto": 0., "azar": 0., "mantener": 0., "ventaja": [], "fechas": []}
    return {"dias": len(filas), "operaciones": sum(f[4] for f in filas),
            "neto": float(sum(f[1] for f in filas)), "azar": float(sum(f[2] for f in filas)),
            "mantener": float(sum(f[3] for f in filas)),
            "ventaja": [float(f[1]-max(f[2],f[3])) for f in filas], "fechas": [f[0] for f in filas]}


def p_bootstrap(ventaja, semilla, muestras=9999):
    x = np.asarray(ventaja, dtype=float)
    if len(x) < 30 or x.mean() <= 0:
        return 1.
    rng = np.random.default_rng(semilla)
    centrada = x-x.mean()
    observado = x.mean()
    supera = int(np.count_nonzero(centrada[rng.integers(0, len(x), (muestras, len(x)))].mean(axis=1) >= observado))
    return (supera+1)/(muestras+1)


def benjamini_hochberg(pvalores, q=.05):
    orden = sorted(pvalores, key=lambda k: pvalores[k])
    m = len(orden)
    kmax = max((i for i, k in enumerate(orden, 1) if pvalores[k] <= q*i/m), default=0)
    return set(orden[:kmax])


def ejecutar(limite=120, hasta=None):
    if limite < 1 or limite > 120:
        raise ValueError("Presupuesto máximo: 120 variantes por corrida")
    hasta = min(hasta or pd.Timestamp.now(tz="UTC").date().isoformat(), "2026-10-01")
    memoria = ROOT / "resultados" / "fabrica.json"
    estado = json.loads(memoria.read_text(encoding="utf-8")) if memoria.exists() else {"version": 1, "registro": {}}
    registro = estado["registro"]
    pendientes = [r for r in variantes() if r["id"] not in registro][:limite]
    cache = {}
    def cargar(activo, inicio, fin):
        key = (activo, inicio, fin)
        if key not in cache:
            cache[key] = archivo.leer(activo, inicio, fin)
        return cache[key]
    for regla in pendientes:
        try:
            v = evaluar(regla, cargar(regla["activo"], PANTALLA_DESDE, PANTALLA_HASTA))
            p = p_bootstrap(v["ventaja"], int(regla["id"], 16))
            registro[regla["id"]] = {"familia": regla["familia"], "activo": regla["activo"],
                "regla": regla, "dias": v["dias"], "operaciones": v["operaciones"],
                "neto": v["neto"], "azar": v["azar"], "mantener": v["mantener"],
                "p": p, "motivo": "sin_ventaja_estadistica" if p >= .05 else "esperando_familia"}
        except LookupError:
            registro[regla["id"]] = {"familia": regla["familia"], "activo": regla["activo"],
                                      "regla": regla, "p": 1., "motivo": "sin_datos"}
    total_plan = sum(1 for _ in variantes())
    # No se abre la reserva con un subconjunto favorable de la familia de pruebas.
    aprobados = (benjamini_hochberg({k: v["p"] for k, v in registro.items()})
                 if len(registro) == total_plan else set())
    for key, fila in registro.items():
        if key in aprobados and "final" not in fila:
            # Esta es la única ruta que lee la reserva. No se usa para volver a ajustar.
            v = evaluar(fila["regla"], cargar(fila["activo"], RESERVA_DESDE, hasta))
            fila["final"] = {k: v[k] for k in ("dias", "operaciones", "neto", "azar", "mantener")}
            fila["motivo"] = "final_sin_ventaja" if v["neto"] <= max(v["azar"], v["mantener"]) else "final_favorable_sin_promesa"
        elif len(registro) == total_plan and key not in aprobados and fila["motivo"] == "esperando_familia":
            fila["motivo"] = "rechazada_BH"
    motivos = Counter(v["motivo"] for v in registro.values())
    orden = sorted(registro, key=lambda k: registro[k]["p"])
    estado.update({"probadas": len(registro), "sin_correccion": sum(v["p"] < .05 for v in registro.values()),
                   "con_correccion": len(aprobados), "motivos": dict(motivos),
                   "ranking": orden[:20], "registro": registro, "total_plan": total_plan,
                   "metodo": "ventaja diaria neta contra máximo de azar y mantener; bootstrap unilateral por día (9999); BH q=0.05 tras medir todas las variantes",
                   "reserva_desde": RESERVA_DESDE})
    memoria.parent.mkdir(exist_ok=True)
    payload = json.dumps(estado, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(payload.encode()) > 1_000_000:
        raise ValueError("Memoria supera 1 MB; dividir registro antes de seguir")
    memoria.write_text(payload + "\n", encoding="utf-8")
    return estado


if __name__ == "__main__":
    ejecutar()
