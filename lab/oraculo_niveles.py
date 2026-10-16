"""Ensayos cronolÃ³gicos de precio para niveles 1 y 2 del OrÃ¡culo.

El Ãºltimo aÃ±o de datos es una prueba sellada: el cÃ³digo nunca ajusta pesos,
escalas ni probabilidades con observaciones posteriores al inicio de prueba.
"""
from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datos" / "cache"
OUTPUT = ROOT / "resultados" / "nivel.json"
VERSION = "oraculo-pit-v1"
ACTIVOS = ["SPY", "NVDA", "TSLA", "META", "NFLX", "KO", "MA", "MCD", "V", "VWRA.L"]
CORTE_TEST = pd.Timestamp("2025-10-08")
HORIZONTES = (1, 5, 21)
SEMILLA = 32026


def _serie(simbolo):
    paths = sorted(DATA.glob(f"y_{simbolo}_*_1d.csv"))
    if not paths:
        return None
    frames = []
    for path in paths:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if "close" not in df:
            continue
        close = pd.to_numeric(df["close"], errors="coerce")
        # Niveles 1â€“2 son de direcciÃ³n; se usa cierre crudo, sin ajuste futuro.
        frames.append(close.rename("close"))
    if not frames:
        return None
    out = pd.concat(frames).sort_index()
    return out[~out.index.duplicated(keep="last")].dropna()


def _manifest():
    rows = []
    for simbolo in ACTIVOS:
        for path in sorted(DATA.glob(f"y_{simbolo}_*_1d.csv")):
            close = _serie(simbolo)
            if close is None:
                continue
            rows.append({"archivo": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "primera_fecha": str(close.index.min().date()), "Ãºltima_fecha": str(close.index.max().date()),
                         "filas": int(len(close))})
    return rows


def _fit_logit(x, y):
    """LogÃ­stica univariada con Newton y penalizaciÃ³n L2 fija."""
    mu, sd = float(np.mean(x)), float(np.std(x))
    if not np.isfinite(sd) or sd < 1e-12:
        sd = 1.
    z = np.column_stack([np.ones(len(x)), (x - mu) / sd])
    beta = np.array([math.log((y.mean() + 1e-4) / (1 - y.mean() + 1e-4)), 0.])
    penalty = np.diag([0., 1.])
    for _ in range(60):
        p = 1 / (1 + np.exp(-np.clip(z @ beta, -30, 30)))
        w = np.maximum(p * (1 - p), 1e-7)
        grad = z.T @ (p - y) + penalty @ beta
        hess = (z.T * w) @ z + penalty + np.eye(2) * 1e-9
        step = np.linalg.solve(hess, grad)
        beta -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return {"mu": mu, "sd": sd, "beta": beta.tolist()}


def _predict(model, x):
    z = np.column_stack([np.ones(len(x)), (x - model["mu"]) / model["sd"]])
    return 1 / (1 + np.exp(-np.clip(z @ np.asarray(model["beta"]), -30, 30)))


def _bootstrap_improvement(y, p, base, block_size=10, rounds=3000):
    """IC y p de mejora Brier por bootstrap circular, respetando horizonte."""
    d = (y - base) ** 2 - (y - p) ** 2
    n = len(d)
    if n < 30:
        return {"mejora_brier": float(np.mean(d)), "ic95": [None, None], "p": None}
    rng = np.random.default_rng(SEMILLA + n)
    block = min(max(2, n // 2), max(10, int(block_size)))
    samples = np.empty(rounds)
    starts = np.arange(n)
    for b in range(rounds):
        ix = []
        while len(ix) < n:
            s = int(rng.choice(starts))
            ix.extend((s + np.arange(block)) % n)
        samples[b] = d[np.asarray(ix[:n])].mean()
    low, high = np.quantile(samples, [.025, .975])
    pval = (1 + np.count_nonzero(samples <= 0)) / (rounds + 1)
    return {"mejora_brier": float(d.mean()), "ic95": [float(low), float(high)], "p": float(pval)}


def _bh(pvals):
    valid = [(i, p) for i, p in enumerate(pvals) if p is not None]
    m = len(valid)
    out = [None] * len(pvals)
    ordered = sorted(valid, key=lambda x: x[1])
    q_next = 1.
    for rank in range(m, 0, -1):
        i, p = ordered[rank - 1]
        q_next = min(q_next, p * m / rank)
        out[i] = min(1., q_next)
    return out


def _ensayo(simbolo, h):
    close = _serie(simbolo)
    if close is None or len(close) < 500:
        return None
    feature = np.log(close / close.shift(5))
    target = (np.log(close.shift(-h) / close) > 0).astype(float)
    frame = pd.DataFrame({"x": feature, "y": target, "close_date": close.index,
                          "target_date": close.index.to_series().shift(-h).values}, index=close.index)
    frame = frame.dropna(subset=["x", "y"])
    # Train and validation precede the reserved one-year test window.
    test = frame[(frame.index >= CORTE_TEST) & (frame["target_date"] <= close.index.max())]
    train = frame[(frame.index < CORTE_TEST - pd.Timedelta(days=365))]
    valid = frame[(frame.index >= CORTE_TEST - pd.Timedelta(days=365)) & (frame.index < CORTE_TEST)]
    if len(train) < 250 or len(valid) < 100 or len(test) < 100:
        return None
    model = _fit_logit(train.x.to_numpy(), train.y.to_numpy())
    # Calibration is assessed on validation only; no test refit or threshold search.
    valp = _predict(model, valid.x.to_numpy())
    val_brier = float(np.mean((valid.y.to_numpy() - valp) ** 2))
    y, p = test.y.to_numpy(), _predict(model, test.x.to_numpy())
    base_p = float(train.y.mean())
    base = np.full(len(y), base_p)
    stats = _bootstrap_improvement(y, p, base, block_size=2 * h)
    return {
        "activo": simbolo, "horizonte_sesiones": h,
        "entrenamiento": [str(train.index.min().date()), str(train.index.max().date())],
        "validacion": [str(valid.index.min().date()), str(valid.index.max().date())],
        "prueba_sellada": [str(test.index.min().date()), str(test.index.max().date())],
        "n_train": len(train), "n_valid": len(valid), "n_test": len(test),
        "brier_modelo_validacion": val_brier,
        "brier_modelo_prueba": float(np.mean((y - p) ** 2)),
        "brier_referencia_base_prueba": float(np.mean((y - base) ** 2)),
        "tasa_alza_prueba": float(y.mean()), "tasa_base_entrenamiento": base_p,
        **stats,
    }


def ejecutar():
    # El artefacto publicado registra las aperturas. Una versiÃ³n no puede
    # volver a consultar su ventana despuÃ©s de mostrarla al investigador.
    if OUTPUT.exists():
        try:
            prior = json.loads(OUTPUT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prior = {}
        if prior.get("version") == VERSION and any(
                int(v) > 0 for v in (prior.get("aperturas_prueba_sellada") or {}).values()):
            raise RuntimeError("La prueba de esta versiÃ³n ya se abriÃ³; fija una versiÃ³n nueva y una ventana nueva")
    res1 = _ensayo("SPY", 1)
    res2 = [_ensayo(s, h) for s in ACTIVOS for h in HORIZONTES]
    res2 = [x for x in res2 if x is not None]
    qs = _bh([x["p"] for x in res2])
    for row, q in zip(res2, qs):
        row["p_ajustado_bh"] = q
    level1_pass = bool(res1 and res1["ic95"][0] > 0)
    level2_pass = bool(res2 and any(x["p_ajustado_bh"] is not None and x["ic95"][0] > 0 and x["p_ajustado_bh"] < .05 for x in res2))
    result = {
        "version": VERSION, "generado_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fuente": "datos/cache/y_*_1d.csv local (Yahoo Finance, cierre OHLC crudo; precios sin dividendos)",
        "manifiesto_datos": _manifest(),
        "corte_datos": "2026-10-09", "inicio_prueba_sellada": str(CORTE_TEST.date()),
        "aperturas_prueba_sellada": {"nivel1": 1, "nivel2": 1, "nivel3": 0, "nivel4": 0, "nivel5": 0, "nivel6": 0, "nivel7": 0},
        "familias_de_comparaciones_nivel2": len(res2),
        "nivel_actual": 3 if level2_pass else 2 if level1_pass else 1,
        "aprobados": [n for n, ok in [(1, level1_pass), (2, level2_pass)] if ok],
        "nivel1": {"estado": "aprobado" if level1_pass else "no_aprobado", "resultado": res1,
                   "metodo": "regresiÃ³n logÃ­stica de retorno logarÃ­tmico de 5 sesiones, ajustada antes de prueba; base: tasa alcista de entrenamiento"},
        "nivel2": {"estado": "aprobado" if level2_pass else "no_aprobado", "resultados": res2,
                   "metodo": "misma regla fija para 10 activos locales y horizontes 1/5/21; Brier contra prevalencia de entrenamiento; IC bootstrap circular con bloques max(10, 2 Ã— horizonte) y ajuste BH de 30 comparaciones"},
        "nivel3": {"estado": "sin_evaluacion", "motivo": "El entorno bloqueÃ³ la descarga del calendario FOMC/BLS y de EDGAR (WinError 10061), asÃ­ que no hay eventos PIT cacheados para unir. La rama datos sÃ­ contiene velas SPY de 1 minuto desde 2021-10 hasta 2026-10."},
        "nivel4": {"estado": "sin_evaluacion", "motivo": "GDELT DOC ofrece hora de indexaciÃ³n (no publicaciÃ³n original) y no existe un corpus histÃ³rico clasificado y congelado para los activos de la prueba."},
        "nivel5": {"estado": "sin_evaluacion", "motivo": "No hay vintages de precios PIT ni detector de rÃ©gimen fijado antes de reservar crisis completas de 2000â€“02, 2008, 2020 y 2022."},
        "nivel6": {"estado": "sin_evaluacion", "motivo": "Falta un panel PIT comÃºn y sincronizado de tasas, dÃ³lar, oro y tecnologÃ­a para separar seÃ±al de correlaciÃ³n contemporÃ¡nea."},
        "nivel7": {"estado": "sin_evaluacion", "motivo": "No hay simulaciÃ³n completa con dividendos, conversiÃ³n, spread, tarifas XTB y benchmark de aportes mensuales para esa misma prueba."},
        "nota": "Solo precios locales con cierre hasta 2026-10-09. La ventana 2025-10-08 a 2026-10-08 se considera reservada para esta versiÃ³n. El artefacto publicado bloquea su reapertura.",
    }
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(ejecutar(), indent=2, ensure_ascii=False))
