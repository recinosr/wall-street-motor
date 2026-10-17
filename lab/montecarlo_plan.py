"""Montecarlo del plan 80/20 (VWRA/VUAA) con aportes mensuales.

Proxies con historia: VT (mundo) para VWRA y SPY (S&P 500) para VUAA, precios de cierre
sin dividendos. Se suma un rendimiento por dividendos fijo y declarado (supuesto, no medido).
Bootstrap circular por bloques de 12 meses de los pares (VT, SPY) del mismo mes, para
conservar la correlación y las rachas. Semilla fija. No predice: acota rangos.
"""
from __future__ import annotations

import gzip
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
PRECIOS = RAIZ / "datos" / "pit" / "precios"
SALIDA = RAIZ / "resultados" / "montecarlo_plan.json"

PARAMS = {
    "semilla": 20261017,
    "rondas": 20000,
    "bloque_meses": 12,
    "aporte_mensual_usd": 100.0,
    "pesos": {"VT": 0.8, "SPY": 0.2},
    "dividendo_anual": {"VT": 0.019, "SPY": 0.013},
    "horizontes_anios": [5, 10, 20],
    "plan_esperado_anual": 0.07,
    "ajuste_conservador_anual": -0.04,
}


def mensuales(simbolo: str) -> pd.Series:
    with gzip.open(PRECIOS / f"{simbolo}.csv.gz", "rt") as f:
        df = pd.read_csv(io.StringIO(f.read()), usecols=["date", "close"], parse_dates=["date"])
    cierre = df.set_index("date")["close"].resample("ME").last().dropna()
    return cierre.pct_change().dropna()


def retornos_mensuales(p: dict = PARAMS) -> pd.DataFrame:
    df = pd.concat({s: mensuales(s) for s in p["pesos"]}, axis=1, sort=True).dropna()
    for s, d in p["dividendo_anual"].items():
        df[s] = df[s] + (1 + d) ** (1 / 12) - 1
    return df


def cartera(df: pd.DataFrame, p: dict = PARAMS) -> np.ndarray:
    # aportes nuevos se reparten 80/20 cada mes; sin vender, así que se compone cada pata
    return np.column_stack([df[s].to_numpy() for s in p["pesos"]])


def simular(r: np.ndarray, meses: int, rondas: int, bloque: int, semilla: int, aporte: float, pesos: list[float]):
    rng = np.random.default_rng(semilla)
    n = len(r)
    bloques = -(-meses // bloque)
    inicios = rng.integers(0, n, size=(rondas, bloques))
    idx = ((inicios[:, :, None] + np.arange(bloque)[None, None, :]) % n).reshape(rondas, -1)[:, :meses]
    patas = np.array(pesos) * aporte
    saldo = np.zeros((rondas, len(pesos)))
    pico = np.zeros(rondas)
    peor_caida = np.zeros(rondas)
    aportado = 0.0
    for t in range(meses):
        saldo = saldo * (1 + r[idx[:, t]]) + patas
        aportado += aporte
        total = saldo.sum(axis=1)
        pico = np.maximum(pico, total)
        peor_caida = np.minimum(peor_caida, total / pico - 1)
    return saldo.sum(axis=1), aportado, peor_caida


def caminos_historicos(r: np.ndarray, meses: int, aporte: float, pesos: list[float]):
    out = []
    for i in range(0, len(r) - meses + 1):
        saldo = np.zeros(len(pesos))
        for t in range(meses):
            saldo = saldo * (1 + r[i + t]) + np.array(pesos) * aporte
        out.append(saldo.sum())
    return np.array(out)


def referencia(meses: int, aporte: float, anual: float) -> float:
    m = (1 + anual) ** (1 / 12) - 1
    return float(sum(aporte * (1 + m) ** (meses - t) for t in range(1, meses + 1)))


def resumen(p: dict = PARAMS, ajuste_anual: float = 0.0) -> dict:
    df = retornos_mensuales(p)
    r = cartera(df, p) + ((1 + ajuste_anual) ** (1 / 12) - 1)
    pesos = list(p["pesos"].values())
    res = {
        "parametros": p,
        "ajuste_anual_aplicado": ajuste_anual,
        "datos": {"meses": int(len(df)), "desde": str(df.index[0].date()), "hasta": str(df.index[-1].date()),
                  "nota": "precio sin dividendos + dividendo anual supuesto; historia desde jun-2008 (incluye 2008, 2020, 2022)"},
        "horizontes": {},
    }
    for a in p["horizontes_anios"]:
        meses = a * 12
        fin, aportado, caida = simular(r, meses, p["rondas"], p["bloque_meses"], p["semilla"] + a, p["aporte_mensual_usd"], pesos)
        q = lambda x, v: float(np.percentile(x, v))
        hist = caminos_historicos(r, meses, p["aporte_mensual_usd"], pesos) if len(r) >= meses else np.array([])
        res["horizontes"][str(a)] = {
            "aportado_usd": aportado,
            "referencia_7pct_usd": round(referencia(meses, p["aporte_mensual_usd"], p["plan_esperado_anual"]), 2),
            "final_usd": {f"p{v}": round(q(fin, v), 2) for v in (5, 25, 50, 75, 95)},
            "prob_final_menor_aportado": round(float((fin < aportado).mean()), 4),
            "prob_final_menor_referencia_7pct": round(float((fin < referencia(meses, p["aporte_mensual_usd"], p["plan_esperado_anual"])).mean()), 4),
            "peor_caida_maxima": {f"p{v}": round(q(caida, v), 4) for v in (5, 50, 95)},
            "prob_caida_peor_que_30pct": round(float((caida < -0.30).mean()), 4),
            "prob_caida_peor_que_50pct": round(float((caida < -0.50).mean()), 4),
            "caminos_historicos": ({"n_ventanas_solapadas": int(len(hist)), "min_usd": round(float(hist.min()), 2), "max_usd": round(float(hist.max()), 2)} if len(hist) else None),
        }
    return res


if __name__ == "__main__":
    out = resumen()
    # la muestra (2008-2026) es alcista en su mayoría: se publica también un escenario conservador
    out["conservador"] = resumen(ajuste_anual=PARAMS["ajuste_conservador_anual"])["horizontes"]
    SALIDA.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    json.dump({"base": out["horizontes"], "conservador": out["conservador"]}, sys.stdout, indent=1, ensure_ascii=False)
