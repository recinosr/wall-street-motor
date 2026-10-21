"""Montecarlo del plan 80/20 (VWRA/VUAA) con aportes mensuales. Versión montecarlo-v2.

Escenarios: "base" (pares VT/SPY desde 2008, con costos y dividendos netos), "historia_larga"
(^GSPC desde 1950 como proxy de toda la cartera; solo EE. UU.) y "conservador" (base con
-4 %/año). Bootstrap circular por bloques de 12 meses, semilla fija. Dividendos supuestos
(no medidos). Calibración medida contra VWRA.L. No predice: acota rangos.
"""
from __future__ import annotations

import gzip
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

VERSION = "montecarlo-v2"
RAIZ = Path(__file__).resolve().parents[1]
PRECIOS = RAIZ / "datos" / "pit" / "precios"
SALIDA = RAIZ / "resultados" / "montecarlo_plan.json"

PARAMS = {
    "semilla": 20261017,
    "rondas": 20000,
    "bloque_meses": 12,
    "aporte_mensual_usd": 100.0,
    "pesos": {"VT": 0.8, "SPY": 0.2},
    "horizontes_anios": [5, 10, 20],
    "plan_esperado_anual": 0.07,
    "ajuste_conservador_anual": -0.04,
    "costos": {
        "fondo": {"VT": "VWRA", "SPY": "VUAA"},  # fondo XTB que representa cada proxy
        "ter": {"VWRA": 0.0019, "VUAA": 0.0007, "VT": 0.0006, "SPY": 0.000945},  # VT y SPY ya lo descuentan
        "dividendo_bruto": {"VT": 0.019, "SPY": 0.013},  # supuesto, no medido
        "fraccion_eeuu": {"VT": 0.60, "SPY": 1.0},
        "retencion_eeuu": 0.15,
        "comision_xtb": 0.0,  # ETF, menos de EUR 100k al mes
        "cambio_divisa": 0.0,  # cuenta y ETF en USD
        "diferencial_y_orden": 0.001,  # diferencial compra-venta y orden limite
        "retiro_final": 0.0,  # XTB cobra US$30 solo en retiros menores de US$50
    },
    "historia_larga": {"dividendo_neto_anual": 0.02},  # supuesto
}


def _mens(anual: float) -> float:
    return (1 + anual) ** (1 / 12) - 1


def _csv(simbolo: str) -> pd.DataFrame:
    with gzip.open(PRECIOS / f"{simbolo}.csv.gz", "rt") as f:
        return pd.read_csv(io.StringIO(f.read()), usecols=["date", "close"], parse_dates=["date"])


def cargar(simbolo: str) -> pd.Series:
    return _csv(simbolo).set_index("date")["close"].resample("ME").last().dropna()


def mensuales(simbolo: str) -> pd.Series:
    return cargar(simbolo).pct_change().dropna()


def costo_compra(p: dict = PARAMS) -> float:
    c = p["costos"]
    return c["comision_xtb"] + c["cambio_divisa"] + c["diferencial_y_orden"]


def retornos(p: dict = PARAMS, costos: bool = True) -> pd.DataFrame:
    # costos=False es la referencia "sin costos": dividendos brutos y sin diferencial de TER
    c = p["costos"]
    df = pd.concat({s: mensuales(s) for s in p["pesos"]}, axis=1, sort=True).dropna()
    for s in p["pesos"]:
        if costos:
            neto = c["dividendo_bruto"][s] * (1 - c["fraccion_eeuu"][s] * c["retencion_eeuu"])
            df[s] += _mens(neto) + _mens(-(c["ter"][c["fondo"][s]] - c["ter"][s]))
        else:
            df[s] += _mens(c["dividendo_bruto"][s])
    return df


def retornos_larga(p: dict = PARAMS, costos: bool = True) -> pd.DataFrame:
    c, h = p["costos"], p["historia_larga"]
    df = mensuales("_GSPC").to_frame("GSPC")
    if costos:
        ter = sum(w * c["ter"][c["fondo"][s]] for s, w in p["pesos"].items())
        df["GSPC"] += _mens(h["dividendo_neto_anual"]) + _mens(-ter)
    else:
        df["GSPC"] += _mens(h["dividendo_neto_anual"] / (1 - c["retencion_eeuu"]))
    return df


def simular(r: np.ndarray, meses: int, rondas: int, bloque: int, semilla: int, aporte: float, pesos: list[float],
            costo_compra: float = 0.0):
    rng = np.random.default_rng(semilla)
    n = len(r)
    bloques = -(-meses // bloque)
    inicios = rng.integers(0, n, size=(rondas, bloques))
    idx = ((inicios[:, :, None] + np.arange(bloque)[None, None, :]) % n).reshape(rondas, -1)[:, :meses]
    patas = np.array(pesos) * aporte * (1 - costo_compra)
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


def caminos_historicos(r: np.ndarray, meses: int, aporte: float, pesos: list[float], costo_compra: float = 0.0):
    n = len(r) - meses + 1  # ventanas solapadas
    if n <= 0:
        return np.array([])
    patas = np.array(pesos) * aporte * (1 - costo_compra)
    saldo = np.zeros((n, len(pesos)))
    for t in range(meses):
        saldo = saldo * (1 + r[t:t + n]) + patas
    return saldo.sum(axis=1)


def referencia(meses: int, aporte: float, anual: float) -> float:
    m = (1 + anual) ** (1 / 12) - 1
    return float(sum(aporte * (1 + m) ** (meses - t) for t in range(1, meses + 1)))


def escenario(nombre: str, datos: dict, r_con: np.ndarray, r_sin: np.ndarray, pesos: list[float], p: dict = PARAMS) -> dict:
    aporte, cc = p["aporte_mensual_usd"], costo_compra(p)
    res = {"nombre": nombre, "datos": datos, "horizontes": {}}
    for a in p["horizontes_anios"]:
        meses, semilla = a * 12, p["semilla"] + a
        fin, aportado, caida = simular(r_con, meses, p["rondas"], p["bloque_meses"], semilla, aporte, pesos, cc)
        fin_sin = simular(r_sin, meses, p["rondas"], p["bloque_meses"], semilla, aporte, pesos)[0]
        hist = caminos_historicos(r_con, meses, aporte, pesos, cc)
        ref = referencia(meses, aporte, p["plan_esperado_anual"])
        q = lambda x, v: float(np.percentile(x, v))
        res["horizontes"][str(a)] = {
            "aportado_usd": round(aportado, 2),
            "referencia_7pct_usd": round(ref, 2),
            "final_usd": {f"p{v}": round(q(fin, v), 2) for v in (1, 5, 25, 50, 75, 95)},
            "prob_final_menor_aportado": round(float((fin < aportado).mean()), 4),
            "prob_final_menor_referencia_7pct": round(float((fin < ref).mean()), 4),
            "peor_caida_maxima": {f"p{v}": round(q(caida, v), 4) for v in (5, 50)},
            "prob_caida_peor_que_30pct": round(float((caida < -0.30).mean()), 4),
            "prob_caida_peor_que_50pct": round(float((caida < -0.50).mean()), 4),
            "costo_mediana_usd": round(float(np.median(fin_sin) - np.median(fin)), 2),
            "caminos_historicos": ({"n_ventanas": int(len(hist)), "min_usd": round(float(hist.min()), 2),
                                    "p50_usd": round(float(np.median(hist)), 2), "max_usd": round(float(hist.max()), 2),
                                    "prob_perdida": round(float((hist < aportado).mean()), 4)} if len(hist) else None),
        }
    return res


def _datos(df: pd.DataFrame) -> dict:
    return {"desde": df.index[0].strftime("%Y-%m"), "hasta": df.index[-1].strftime("%Y-%m"), "meses": int(len(df))}


def calibracion(p: dict = PARAMS) -> dict:
    # VWRA.L real (ya incluye dividendos y TER) contra la pata VT modelada, en su período común
    vwra = mensuales("VWRA.L")
    df = pd.concat({"VWRA": vwra, "MODELO": retornos(p, True)["VT"]}, axis=1, sort=True).dropna()
    cagr = lambda s: float((1 + s).prod() ** (12 / len(s)) - 1)
    real, mod = cagr(df["VWRA"]), cagr(df["MODELO"])
    return {**_datos(df), "cagr_vwra_real": round(real, 4), "cagr_modelo": round(mod, 4),
            "diferencia_pp": round((mod - real) * 100, 2)}


def resumen(p: dict = PARAMS) -> dict:
    c = p["costos"]
    pesos = list(p["pesos"].values())
    base_con, base_sin = retornos(p, True), retornos(p, False)
    larga_con, larga_sin = retornos_larga(p, True), retornos_larga(p, False)
    ajuste = _mens(p["ajuste_conservador_anual"])
    escenarios = {
        "base": escenario("Pares VT/SPY desde 2008, con costos y dividendos netos", _datos(base_con),
                          base_con.to_numpy(), base_sin.to_numpy(), pesos, p),
        "historia_larga": escenario("S&P 500 desde 1950 como proxy de toda la cartera (solo EE. UU.)",
                                    _datos(larga_con), larga_con.to_numpy(), larga_sin.to_numpy(), [1.0], p),
        "conservador": escenario("Base con -4 %/año", _datos(base_con),
                                 (base_con + ajuste).to_numpy(), (base_sin + ajuste).to_numpy(), pesos, p),
    }
    ter_larga = sum(w * c["ter"][c["fondo"][s]] for s, w in p["pesos"].items())
    dif_vt = (c["ter"]["VWRA"] - c["ter"]["VT"]) * 100
    dif_spy = (c["ter"]["VUAA"] - c["ter"]["SPY"]) * 100
    cal = calibracion(p)
    corte = _csv("VT")["date"].max().strftime("%Y-%m-%d")
    fuente = lambda s, uso: (f"datos/pit/precios/{s}.csv.gz: cierre mensual "
                             f"{cargar(s).index[0]:%Y-%m} a {cargar(s).index[-1]:%Y-%m} ({uso})")
    h5c, h5l = escenarios["conservador"]["horizontes"]["5"], escenarios["historia_larga"]["horizontes"]["5"]
    h20l, h20b = escenarios["historia_larga"]["horizontes"]["20"], escenarios["base"]["horizontes"]["20"]
    veredicto = (
        f"A 20 años, en historia_larga (S&P 500 desde 1950, solo EE. UU.) el P5 del saldo final es "
        f"US${h20l['final_usd']['p5']:,.0f} y {h20l['prob_final_menor_aportado'] * 100:.1f} % de las rondas "
        f"termina por debajo de lo aportado (US${h20l['aportado_usd']:,.0f}). "
        f"En base (muestra 2008-hoy, casi toda alcista) el P5 es US${h20b['final_usd']['p5']:,.0f} y la "
        f"probabilidad de pérdida es {h20b['prob_final_menor_aportado'] * 100:.1f} %. "
        f"El riesgo está en plazos cortos: a 5 años, en el conservador {h5c['prob_final_menor_aportado'] * 100:.0f} % "
        f"de las rondas pierde y el peor caso razonable (P5) es US${h5c['final_usd']['p5']:,.0f} de "
        f"US${h5c['aportado_usd']:,.0f} aportados; desde 1950 la peor ventana real de 5 años terminó en "
        f"US${h5l['caminos_historicos']['min_usd']:,.0f}. "
        f"Son rangos bajo supuestos declarados, no una predicción."
    )
    return {
        "version": VERSION,
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corte_datos": corte,
        "parametros": p,
        "fuente": [
            fuente("VT", "base, proxy de VWRA"),
            fuente("SPY", "base, proxy de VUAA"),
            fuente("_GSPC", "historia_larga, S&P 500"),
            fuente("VWRA.L", "calibración, USD, acumulación"),
            "Yahoo Finance vía datos/pit del motor",
            "lab/montecarlo_plan.py",
        ],
        "metodo": [
            f"Bootstrap circular por bloques de {p['bloque_meses']} meses sobre retornos mensuales reales: "
            f"{p['rondas']:,} rondas con semilla fija {p['semilla']}; cada ronda encadena bloques de meses "
            "históricos, lo que conserva correlaciones y rachas. Base usa pares VT/SPY del mismo mes.",
            f"Aportes: US${p['aporte_mensual_usd']:.0f} al mes durante 5, 10 y 20 años, sin vender; cada aporte "
            f"se reparte {p['pesos']['VT'] * 100:.0f}/{p['pesos']['SPY'] * 100:.0f} y compone desde su mes de entrada "
            "(historia_larga: 100 % en el S&P 500).",
            f"Costos: cada aporte entra multiplicado por (1 - {costo_compra(p)}) (comisión 0 %, cambio 0 %, "
            f"diferencial y orden límite 0.10 %). La pata VT resta {dif_vt:.2f} pp/año de TER frente a VT y la SPY "
            f"suma {-dif_spy:.4f} pp/año frente a SPY; ambos se mensualizan como (1+x)^(1/12)-1.",
            f"Dividendos netos: VT {c['dividendo_bruto']['VT'] * 100:.1f} % bruto con retención de "
            f"{c['retencion_eeuu'] * 100:.0f} % sobre {c['fraccion_eeuu']['VT'] * 100:.0f} % EE. UU.; SPY "
            f"{c['dividendo_bruto']['SPY'] * 100:.1f} % bruto con retención total; ambos supuestos, no medidos.",
            "Se reportan percentiles del saldo final y de la peor caída desde el máximo; costo_mediana_usd es la "
            "mediana sin costos (dividendos brutos, sin TER diferencial ni costo de compra) menos la mediana con costos, "
            "con la misma semilla.",
            "Caminos históricos: todas las ventanas reales de cada horizonte, con los mismos aportes y costos (null si "
            "no hay historia suficiente). Calibración: VWRA.L real frente a la pata VT modelada en su período común; "
            "conservador: base con -4 %/año.",
        ],
        "calibracion_vwra": cal,
        "escenarios": escenarios,
        "limites": [
            f"base: solo {escenarios['base']['datos']['meses']} meses comunes ({escenarios['base']['datos']['desde']} "
            f"a {escenarios['base']['datos']['hasta']}) y casi todos alcistas; no incluye 2000-2002 ni décadas perdidas. "
            "Por eso se publica el conservador.",
            f"historia_larga es solo EE. UU. (S&P 500 vía ^GSPC): no representa la cartera global ni el tipo de cambio. "
            f"Usa dividendo neto fijo de {p['historia_larga']['dividendo_neto_anual'] * 100:.1f} %/año y TER combinado "
            f"de {ter_larga * 100:.3f} %/año.",
            "Dividendos supuestos (1.9 % VT y 1.3 % SPY brutos; 2.0 % neto en historia_larga), no medidos.",
            "Cargo de la tarjeta o del banco al depositar: no modelado. Cambio de divisa 0 % asumido (cuenta y ETF en USD).",
            "Sin impuestos sobre ganancias ni costos de retiro (retiro final 0; XTB cobra US$30 solo en retiros menores de US$50).",
            f"Último mes parcial: los datos de VT llegan hasta {corte}.",
            "El bootstrap supone que el futuro se parece al pasado en bloques de 12 meses; no modela cambios de régimen "
            "de décadas ni cambios de correlación.",
            f"Calibración de VWRA.L: {cal['meses']} meses, diferencia de {cal['diferencia_pp']:+.2f} pp/año; "
            "el ajuste de TER del modelo es declarado, no medido.",
            "No predice: acota rangos bajo los supuestos declarados.",
        ],
        "veredicto": veredicto,
    }


if __name__ == "__main__":
    out = resumen()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    json.dump(out["escenarios"], sys.stdout, indent=1, ensure_ascii=False)
