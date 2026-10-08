"""Planifica trabajos de Actions y reúne sus resultados mensuales."""
import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path

import pandas as pd

from . import dia, gimnasio


def matriz(activo, desde, hasta, costo="", spread="0"):
    activos = gimnasio.ACTIVOS if activo.upper() == "TODOS" else (activo.upper(),)
    if any(a not in gimnasio.ACTIVOS for a in activos): raise ValueError("Activo no admitido")
    if costo:
        c = float(costo)
        if c < 0: raise ValueError("Costo negativo")
        perfiles = [("personalizado", c, 0.0, 1000)]
    else:
        perfiles = [("generico", .001, 0.0, 1000), ("exchange", .0002, 0.0, 1000),
                    ("hapi1000", 0.0, .10, 1000), ("hapi125", 0.0, .10, 125)]
    spread = float(spread or 0)
    if spread < 0: raise ValueError("Spread negativo")
    meses = [str(m) for m in pd.period_range(desde, hasta, freq="M")][6:]
    if not meses: meses = [hasta[:7]]
    return {"include": [{"activo": a, "perfil": p, "costo": c, "fijo": f, "capital": capital, "spread": spread, "mes": m}
                        for a in activos for p, c, f, capital in perfiles for m in meses]}


def velas_necesarias(activo, desde, hasta):
    if activo not in gimnasio.ACTIVOS: raise ValueError("Activo no admitido")
    inicio = pd.Timestamp(desde) - pd.Timedelta(days=5)
    fin = pd.Timestamp(hasta)
    if fin < inicio: raise ValueError("Fechas invertidas")
    return [f"velas/1m/{activo}/{mes}.csv.gz" for mes in pd.period_range(inicio, fin, freq="M")]


def entregar(ruta, activo, mes, desde, hasta):
    """Exporta el informe y solo los detalles producidos por este perfil/mes."""
    perfil = gimnasio.nombre_perfil()
    raiz = gimnasio.RAIZ / "datos" / "gimnasio"
    informe = raiz / f"{activo}_{desde}_{hasta}_{perfil}.json"
    v = json.loads(informe.read_text(encoding="utf-8"))
    destino = Path(ruta)
    destino.mkdir(parents=True, exist_ok=True)
    shutil.copy2(informe, destino / informe.name)
    for m in v["meses"]:
        if m["mes"] != mes: raise ValueError("Informe de otro mes")
        fechas = [d["fecha"] for d in m["serie_diaria"]] + m.get("dias_previos", [])
        for fecha in fechas:
            relativo = Path("dias") / activo / perfil / fecha[:7] / f"{fecha}.json"
            archivo = raiz / relativo
            if not archivo.is_file(): raise FileNotFoundError(f"Falta detalle de {activo} {fecha}")
            salida = destino / relativo
            salida.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archivo, salida)
    return destino


def reunir(ruta, desde, hasta):
    grupos = defaultdict(list)
    for archivo in Path(ruta).rglob("*.json"):
        if f"_{desde}_{hasta}_" not in archivo.name:
            continue
        try:
            v = json.loads(archivo.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if "meses" not in v or "sim" not in v: continue
        clave = (v["sim"], v["costo_por_lado"], v.get("spread", 0), v.get("costo_fijo_usd_por_orden", 0), v.get("capital_usd", 1000))
        grupos[clave].extend(v["meses"])
    lineas = ["# Gimnasio — resultados fuera de muestra", "", "Suma de retornos diarios; intervalos bootstrap por día. El mejor posible usa información futura y solo es referencia.", ""]
    for (sim, costo, spread, fijo, capital), meses in sorted(grupos.items()):
        if not meses: continue
        dia.COSTO, dia.SPREAD, dia.COSTO_FIJO, dia.CAPITAL = costo, spread, fijo, capital
        meses.sort(key=lambda m: m["mes"])
        if not meses[0].get("dias_previos"):
            carpeta = gimnasio.RAIZ / "datos" / "gimnasio" / "dias" / sim / gimnasio.nombre_perfil()
            meses[0]["dias_previos"] = sorted(p.stem for p in carpeta.rglob("*.json") if p.stem < meses[0]["prueba_desde"])
        _, informe = gimnasio.guardar(sim, desde, hasta, meses)
        perfil = f"USD {fijo:.2f} por orden, cuenta USD {capital:g}" if fijo else f"{costo:.3%} por lado"
        if spread: perfil += f", spread {spread:.3%}"
        lineas += [f"## {sim} · {perfil}", "", "| Mes | Campeón | Prueba | Sin entrenar | Mantener | Mejor posible | Operaciones |",
                   "|---|---|---:|---:|---:|---:|---:|"]
        for m in meses:
            lineas.append(f"| {m['mes']} | {m['campeon']} | {m['prueba_campeon']:+.2%} | {m['prueba_sin_entrenar']:+.2%} | {m['mantener_diario']:+.2%} | {m['mejor_posible']:+.2%} | {m['operaciones']} |")
        serie = [d["campeon"] for m in meses for d in m.get("serie_diaria", [])]
        ic = gimnasio.intervalo(serie)
        ventaja = informe["intervalo_ventaja_corregido"]
        n = sum(m["n_pruebas"] for m in meses)
        z = max(m["umbral_z_bonferroni"] for m in meses)
        brier = [m["brier"] for m in meses if m.get("brier")]
        lineas += ["", f"Intervalo 95 % del campeón: [{ic[0]:+.2%}, {ic[1]:+.2%}]. Ventaja frente a max(no operar, mantener), intervalo corregido para 32 configuraciones: [{ventaja[0]:+.2%}, {ventaja[1]:+.2%}].",
                   f"Reglas evaluadas: {n}; umbral |z| de Bonferroni mensual máximo: {z:.2f}."]
        if brier:
            total = sum(b["n"] for b in brier)
            bm = sum(b["brier"] * b["n"] for b in brier) / total
            bb = sum(b["brier_base"] * b["n"] for b in brier) / total
            lineas.append(f"Calibración del agente de contexto: Brier {bm:.4f} frente a base {bb:.4f}, {total} etiquetas solapadas de 15 minutos.")
        lineas += [informe["conclusion"], ""]
    if not grupos: lineas.append("No hubo meses con seis meses previos de datos suficientes.")
    destino = gimnasio.RAIZ / "datos" / "gimnasio" / "resumen.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return destino


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    sub = a.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("matriz")
    p.add_argument("activo"); p.add_argument("desde"); p.add_argument("hasta"); p.add_argument("--costo", default=""); p.add_argument("--spread", default="0")
    p = sub.add_parser("reunir")
    p.add_argument("ruta"); p.add_argument("desde"); p.add_argument("hasta")
    p = sub.add_parser("velas")
    p.add_argument("activo"); p.add_argument("desde"); p.add_argument("hasta")
    p = sub.add_parser("entregar")
    p.add_argument("ruta"); p.add_argument("activo"); p.add_argument("mes"); p.add_argument("desde"); p.add_argument("hasta")
    p.add_argument("--costo", type=float, default=.001); p.add_argument("--fijo", type=float, default=0)
    p.add_argument("--capital", type=float, default=1000); p.add_argument("--spread", type=float, default=0)
    x = a.parse_args()
    if x.comando == "matriz": print(json.dumps(matriz(x.activo, x.desde, x.hasta, x.costo, x.spread), separators=(",", ":")))
    elif x.comando == "velas": print("\n".join(velas_necesarias(x.activo, x.desde, x.hasta)))
    elif x.comando == "entregar":
        dia.COSTO, dia.COSTO_FIJO, dia.CAPITAL, dia.SPREAD = x.costo, x.fijo, x.capital, x.spread
        print(entregar(x.ruta, x.activo, x.mes, x.desde, x.hasta))
    else: print(reunir(x.ruta, x.desde, x.hasta))
