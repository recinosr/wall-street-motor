"""Aprendiz incremental v1: un mes cronológico por ejecución, sin LLM ni broker.

Predice y simula con pesos congelados durante cada sesión. Las etiquetas de
esa sesión solo se usan para actualizar al terminar. Nunca abre validación
(abril-diciembre 2025) ni prueba (2026). Estado portable en JSON, sin pickle.
"""
import argparse
import hashlib
import json
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import archivo

ROOT = Path(__file__).resolve().parents[1]
VERSION = "aprendiz-logistico-v1"
CORTE = "2025-04"
COSTO = .001
HORIZONTE = 15
UMBRAL = .60
NOMBRES = ["retorno_5m", "retorno_15m", "retorno_30m", "distancia_media_60m",
           "z_60m", "rango_60m", "volumen_relativo", "cuerpo_vela", "hora"]


def nuevo():
    return {"version": VERSION, "activo": "BTC", "pesos": [0.] * len(NOMBRES),
            "sesgo": 0., "ejemplos": 0, "positivos": 0, "dias": 0,
            "ultimo_mes": None, "ejecuciones": [], "lotes": []}


def huella(modelo):
    return hashlib.sha256(json.dumps({k: modelo[k] for k in
        ("version", "pesos", "sesgo")}, sort_keys=True).encode()).hexdigest()


def probabilidad(modelo, x):
    z = float(np.dot(modelo["pesos"], x) + modelo["sesgo"])
    return 1 / (1 + math.exp(-max(-40., min(40., z))))


def aprender(modelo, ejemplos):
    """SGD de pérdida logística; cada etiqueta se incorpora una sola vez."""
    w = np.asarray(modelo["pesos"], dtype=float)
    for e in ejemplos:
        x, y = np.asarray(e["x"]), e["y"]
        p = probabilidad({"pesos": w, "sesgo": modelo["sesgo"]}, x)
        paso = .05 / math.sqrt(1 + modelo["ejemplos"] / 1000)
        w -= paso * ((p - y) * x + .0001 * w)
        modelo["sesgo"] -= paso * (p - y)
        modelo["ejemplos"] += 1
        modelo["positivos"] += y
    modelo["pesos"] = w.tolist()


def rasgos_visibles(df, min_periods=60):
    """No construye etiquetas ni consulta velas posteriores."""
    c = df.close.astype(float)
    m = c.rolling("60min", min_periods=min_periods).mean()
    sd = c.rolling("60min", min_periods=min_periods).std()
    rango = (df.high / df.low - 1).rolling("60min", min_periods=min_periods).mean()
    vol = df.volume.rolling("60min", min_periods=min_periods).mean()
    ancho = df.high - df.low
    X = pd.DataFrame(index=df.index)
    for k in (5, 15, 30):
        X[f"retorno_{k}m"] = (c / c.reindex(c.index - pd.Timedelta(minutes=k)).to_numpy() - 1) / .01
    X["distancia_media_60m"] = (c / m - 1) / .01
    X["z_60m"] = ((c - m) / sd).where(sd > 0, 0) / 3
    X["rango_60m"] = rango / .01
    X["volumen_relativo"] = np.log1p(df.volume / vol.where(vol > 0)) / 3
    X["cuerpo_vela"] = ((c - df.open) / ancho).where(ancho > 0, 0)
    X["hora"] = (df.index.hour * 60 + df.index.minute - 570) / 389
    return X


def expedientes(df):
    """Rasgos causales con escala fija; horizonte por reloj, no por filas."""
    X = rasgos_visibles(df)
    # Cinco minutos entre pronósticos; las etiquetas de 15m se solapan.
    out = []
    indices = {t: i for i, t in enumerate(df.index)}
    for t in df.index[::5]:
        i = indices[t]
        if i < 60: continue
        x = X.loc[t, NOMBRES].to_numpy(dtype=float)
        if not np.isfinite(x).all(): continue
        ent, fin = t + pd.Timedelta(minutes=1), t + pd.Timedelta(minutes=HORIZONTE)
        if ent not in indices or fin not in indices: continue
        j, k = indices[ent], indices[fin]
        pe, ps = float(df.open.iloc[j]), float(df.close.iloc[k])
        neto = (ps / pe) * (1 - COSTO) ** 2 - 1
        out.append({"senal": i, "entrada": j, "salida": k, "x": np.clip(x, -3, 3).tolist(),
                    "y": int(neto > 0), "neto": neto, "pe": pe, "ps": ps})
    return out


def cartera(ejemplos, probabilidades):
    capital, ocupado, ops = 1., -1, []
    for e, p in zip(ejemplos, probabilidades):
        # La entrada necesita haberse decidido antes y la venta anterior estar cerrada.
        if e["senal"] <= ocupado or p < UMBRAL: continue
        capital *= 1 + e["neto"]
        ops.append([e["entrada"], e["salida"], e["pe"], e["ps"], capital])
        ocupado = e["salida"]
    return {"ret": capital - 1, "ops": ops}


def sesion(modelo, df, fecha, congelado=None):
    """Todas las predicciones de hoy anteceden a cualquier actualización de hoy."""
    E = expedientes(df)
    if not E: return None
    antes = huella(modelo)
    P = [probabilidad(modelo, e["x"]) for e in E]
    congelado = congelado if congelado is not None else nuevo()
    PF = [probabilidad(congelado, e["x"]) for e in E]
    base = (modelo["positivos"] + 1) / (modelo["ejemplos"] + 2)
    rng = np.random.default_rng(int(fecha.replace("-", "")))
    decisiones = []
    for e, p in zip(E, P):
        contrib = np.asarray(modelo["pesos"]) * e["x"]
        top = sorted(range(len(NOMBRES)), key=lambda j: abs(contrib[j]), reverse=True)[:3]
        motivos = "; ".join(f"{NOMBRES[j]}: {contrib[j]:+.4f}" for j in top)
        decisiones.append({"senal_index": e["senal"], "index": e["entrada"],
            "accion": "evaluar compra" if p >= UMBRAL else "esperar",
            "prob_sube": p, "fundamento": f"p(neto positivo en 15 min)={p:.3f}; umbral {UMBRAL}. "
                f"Contribuciones al logit: {motivos}. Son aportes matemáticos, no causas ni razonamiento verbal."})
    ia = cartera(E, P)
    # Registrar la acción efectiva, incluyendo el bloqueo de una posición aún abierta.
    entradas = {o[0] for o in ia["ops"]}
    for d in decisiones:
        d["accion"] = "comprar" if d["index"] in entradas else "esperar"
    pe, ps = E[0]["pe"], E[-1]["ps"]
    mantener = (ps / pe) * (1 - COSTO) ** 2 - 1
    participantes = {
        "ia": {"nombre": "Aprendiz incremental", **ia, "decisiones": decisiones},
        "congelado": {"nombre": "Checkpoint congelado: " + (congelado.get("ultimo_mes") or "inicial p=0.5"), **cartera(E, PF)},
        "azar": {"nombre": "Azar: entradas sorteadas (25 %)", **cartera(E, (rng.random(len(E)) < .25).astype(float))},
        "mantener": {"nombre": "Comprar y mantener esta sesión", "ret": mantener,
                     "ops": [[E[0]["entrada"], E[-1]["salida"], pe, ps, 1 + mantener]]},
        "efectivo": {"nombre": "Efectivo", "ret": 0., "ops": []}}
    brier = sum((p - e["y"]) ** 2 for p, e in zip(P, E)) / len(E)
    brier_base = sum((base - e["y"]) ** 2 for e in E) / len(E)
    pronosticos = [{"senal_index": e["senal"], "prob": p, "observado": e["y"],
                    "neto": e["neto"]} for p, e in zip(P, E)]
    aprender(modelo, E)
    modelo["dias"] += 1
    mezcla = bool(modelo.get("en_vivo_desde"))
    detalle = {"tipo": "aprendiz_incremental", "modelo": VERSION, "sim": "BTC", "fecha": fecha,
        "horizonte_minutos": HORIZONTE, "capital_usd": 1000, "costo_por_lado": COSTO,
        "spread": 0, "costo_fijo_usd": 0, "inicio_operable": E[0]["senal"],
        "precios": [[t.isoformat(), float(r.close), float(r.open), float(r.high), float(r.low)] for t, r in df.iterrows()],
        "participantes": participantes, "pronosticos": pronosticos, "brier": brier,
        "brier_base": brier_base, "pesos_antes_sha": antes, "pesos_despues_sha": huella(modelo),
        "congelado_sha": huella(congelado), "probabilidades_congelado": PF,
        "ejemplos": len(E), "consultas_llm": 0,
        "mezcla_experiencias_actuales": mezcla,
        "metodo": ("Práctica retrospectiva: el agente ya aprendió experiencias de fechas posteriores. "
                   "No es evaluación cronológica limpia. " if mezcla else
                   "Predicciones con pesos de días anteriores; actualización al cerrar el día. ") +
            "Entrenamiento histórico, no prueba sellada ni mercado en vivo."}
    return detalle


def procesar_mes(modelo, df, mes, congelado=None):
    if mes >= CORTE: raise ValueError("Validación y prueba están reservadas")
    if modelo["ultimo_mes"] and mes <= modelo["ultimo_mes"]: raise ValueError("Mes ya incorporado")
    antes, n0 = huella(modelo), modelo["ejemplos"]
    sesiones, ultimo = [], None
    datos = df.tz_convert("America/New_York").between_time("09:30", "15:59")
    for fecha, frame in datos.groupby(datos.index.strftime("%Y-%m-%d")):
        if not fecha.startswith(mes): continue
        ultimo_dia = sesion(modelo, frame, fecha, congelado)
        if not ultimo_dia: continue
        ultimo = ultimo_dia
        sesiones.append({"fecha": fecha, "ejemplos": ultimo["ejemplos"], "brier": ultimo["brier"],
            "brier_base": ultimo["brier_base"], "pesos_antes_sha": ultimo["pesos_antes_sha"],
            "pesos_despues_sha": ultimo["pesos_despues_sha"],
            "pronosticos": ultimo["pronosticos"],
            "senal_compra_n": sum(p["prob"] >= UMBRAL for p in ultimo["pronosticos"]),
            "participantes": {k: {"ret": v["ret"], "pares": len(v["ops"]), "ops": v["ops"]} for k, v in ultimo["participantes"].items()}})
    if not sesiones: raise LookupError("El mes no contiene sesiones utilizables")
    modelo["ultimo_mes"] = mes
    lote = {"version": VERSION, "mes": mes, "dias": len(sesiones), "ejemplos": modelo["ejemplos"] - n0,
        "mezcla_experiencias_actuales": bool(modelo.get("en_vivo_desde")),
        "pesos_antes_sha": antes, "pesos_despues_sha": huella(modelo), "sesiones": sesiones,
        "datos_sha": hashlib.sha256(df.to_csv().encode()).hexdigest()}
    lote["metricas"] = {"brier": sum(s["brier"] * s["ejemplos"] for s in sesiones) / lote["ejemplos"],
        "brier_base": sum(s["brier_base"] * s["ejemplos"] for s in sesiones) / lote["ejemplos"],
        "participantes": {k: {"neto_compuesto": math.prod(1 + s["participantes"][k]["ret"] for s in sesiones) - 1,
            "pares": sum(s["participantes"][k]["pares"] for s in sesiones)} for k in ultimo["participantes"]}}
    modelo["lotes"].append({k: v for k, v in lote.items() if k != "sesiones"})
    return lote, ultimo


def guardar(path, dato):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporal = path.with_suffix(".tmp")
    temporal.write_text(json.dumps(dato, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporal, path)


def ejecutar(directorio=None, ejecucion=None):
    directorio = Path(directorio) if directorio else ROOT / "datos" / "aprendiz"
    path = directorio / "modelo.json"
    modelo = json.loads(path.read_text(encoding="utf-8")) if path.exists() else nuevo()
    if modelo["version"] != VERSION: raise ValueError("Cambio de versión requiere otro historial de entrenamiento")
    if ejecucion and ejecucion in modelo["ejecuciones"]:
        return {"estado": "ya_procesado", "ejecucion": ejecucion}
    checkpoint = directorio / "congelado.json"
    congelado = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else nuevo()
    # Tras el primer mes, congelar su aprendizaje para comparar en meses NUEVOS.
    # No modifica los resultados iniciales ni usa el mes que se va a evaluar.
    if not checkpoint.exists() and modelo["ejemplos"]:
        congelado = {k: modelo[k] for k in ("version", "pesos", "sesgo", "ejemplos", "positivos", "ultimo_mes")}
        guardar(checkpoint, congelado)
    lista = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/datos", "velas/1m/BTC"],
                           cwd=ROOT, check=True, capture_output=True, text=True).stdout.splitlines()
    meses = sorted(Path(p).name[:7] for p in lista if p.endswith(".csv.gz")
                   and Path(p).name[:7] < CORTE and (not modelo["ultimo_mes"] or Path(p).name[:7] > modelo["ultimo_mes"]))
    if not meses: return {"estado": "entrenamiento_completo", "ultimo_mes": modelo["ultimo_mes"]}
    mes = meses[0]
    desde = pd.Timestamp(mes + "-01", tz="UTC")
    df = archivo.leer("BTC", desde, desde + pd.offsets.MonthBegin(1), rama="origin/datos")
    lote, ultimo = procesar_mes(modelo, df, mes, congelado)
    if ejecucion: modelo["ejecuciones"].append(ejecucion)
    ahora = datetime.now(timezone.utc).isoformat()
    resumen = {"version": VERSION, "actualizado": ahora, "activo": "BTC", "ultimo_mes": mes,
        "dias": modelo["dias"], "ejemplos": modelo["ejemplos"], "consultas_llm": 0,
        "pesos_sha": huella(modelo), "pesos": dict(zip(NOMBRES, modelo["pesos"])), "sesgo": modelo["sesgo"],
        "congelado_mes": congelado.get("ultimo_mes"), "congelado_sha": huella(congelado),
        "lotes": modelo["lotes"], "ultimo_lote": {k: v for k, v in lote.items() if k != "sesiones"},
        "ejemplos_en_vivo": modelo.get("ejemplos_en_vivo", 0),
        "run_id": ejecucion, "horario": "Práctica histórica cuatro veces al día, aproximadamente cada seis horas. Computadora apagada.",
        "informacion": "Velas BTC archivadas (precio OHLC y volumen). Sin noticias, balances ni acceso universal a internet.",
        "estado": "Práctica histórica incremental. No demuestra rentabilidad ni razonamiento de un LLM. "
            "Validación abril-diciembre 2025 y prueba 2026 permanecen reservadas."}
    guardar(directorio / "lotes" / f"{mes}.json", lote)
    guardar(directorio / "recorrido.json", ultimo)
    guardar(directorio / "resumen.json", resumen)
    # Estado/cursor al final: una reanudación desde el commit previo reproduce el mismo lote.
    guardar(path, modelo)
    return resumen


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directorio")
    p.add_argument("--ejecucion")
    args = p.parse_args()
    r = ejecutar(args.directorio, args.ejecucion)
    print(json.dumps({k: v for k, v in r.items() if k not in ("pesos", "lotes")}, ensure_ascii=False))
