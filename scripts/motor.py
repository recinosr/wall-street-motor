"""Corridas públicas con salida JSON compacta. Solo velas BTC/ETH de Coinbase."""
import argparse
import datetime as dt
import json
from pathlib import Path

import pandas as pd

from lab import aprendiz, dia, escuela_bots, gimnasio

ROOT = Path(__file__).resolve().parents[1]
RESULTADOS = ROOT / "resultados"


def publicar(nombre, valor):
    RESULTADOS.mkdir(exist_ok=True)
    payload = json.dumps(valor, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(payload.encode("utf-8")) > 1_000_000:
        raise ValueError(f"{nombre}: supera 1 MB")
    (RESULTADOS / nombre).write_text(payload + "\n", encoding="utf-8")


def escuela(n):
    if n != 1000:
        raise ValueError("El protocolo publicado usa 1,000 sesiones por bot")
    resumen = escuela_bots.correr(n, particion="entrenamiento")
    total = sum(v["sesiones"] for v in resumen.values())
    publicar("escuela.json", {
        "version": 1, "fuente": "Coinbase BTC/ETH 1m", "costo_por_lado": .001,
        "total": total, "bots": {k: {"total": v["sesiones"], "neto": v["neto_medio"],
                    "percentil_azar": v["percentil_medio"], "brier": v["brier_medio"],
                    "peor_caida": v["peor_caida_media"]} for k, v in resumen.items()},
        "curva": [], "mejores": [], "peores": [], "manual": "", "sesiones": [],
        "aviso": "Práctica retrospectiva. No demuestra ventaja fuera de muestra."})


def gimnasio_diario(activo):
    if activo not in gimnasio.ACTIVOS:
        raise ValueError("Solo BTC y ETH")
    fin = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    inicio = (pd.Timestamp(fin).to_period("M") - 6).start_time.date()
    dia.COSTO, dia.SPREAD, dia.COSTO_FIJO, dia.CAPITAL = .001, 0., 0., 1000.
    meses = gimnasio.mes_a_mes(activo, str(inicio), str(fin), pob=16, gens=2,
                               mes=fin.strftime("%Y-%m"), guardar_dias=False)
    if not meses:
        publicar(f"gimnasio_{activo}.json", {"sim": activo, "perfiles": [], "estado": "sin_muestra_suficiente"})
        return
    m = meses[-1]
    fila = {k: m[k] for k in (
        "mes", "train_desde", "train_hasta", "validacion_desde", "validacion_hasta",
        "prueba_desde", "prueba_hasta", "dias_prueba", "campeon", "prueba_campeon",
        "prueba_sin_entrenar", "mantener_diario", "operaciones", "n_pruebas",
        "intervalo_ventaja_95", "mejor_posible", "descripcion", "intervalo_95")}
    perfil = {"sim": activo, "perfil": "costo0.001", "costo_por_lado": .001, "meses": [fila],
        "conclusion": "Ventaja fuera de muestra no demostrada.",
        "aviso": "Mes de prueba posterior a entrenamiento y validación; costo 0.1 % por lado."}
    publicar(f"gimnasio_{activo}.json", {"sim": activo, "perfiles": [perfil]})


def aprender(run_id):
    resumen = aprendiz.ejecutar(ejecucion=run_id)
    if resumen.get("estado") in ("ya_procesado", "entrenamiento_completo"):
        return
    # El modelo/avance se mantiene en datos/aprendiz; la API recibe solo una vista pequeña.
    publicar("aprendiz.json", {k: resumen[k] for k in (
        "version", "actualizado", "activo", "ultimo_mes", "dias", "ejemplos",
        "consultas_llm", "pesos_sha", "pesos", "sesgo", "congelado_mes",
        "congelado_sha", "ultimo_lote", "estado")})
    recorrido = json.loads((ROOT / "datos/aprendiz/recorrido.json").read_text(encoding="utf-8"))
    publicar("aprendiz_recorrido.json", recorrido)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("modo", choices=("escuela", "gimnasio", "aprendiz"))
    p.add_argument("--activo", choices=("BTC", "ETH"), default="BTC")
    p.add_argument("--sesiones", type=int, default=1000)
    p.add_argument("--run-id", default="")
    a = p.parse_args()
    if a.modo == "escuela": escuela(a.sesiones)
    elif a.modo == "gimnasio": gimnasio_diario(a.activo)
    else: aprender(a.run_id)


if __name__ == "__main__":
    main()
