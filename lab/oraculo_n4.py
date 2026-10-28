"""Oraculo nivel 4: ¿las noticias GDELT (tema y tono) aportan a la dirección o al tamaño de SPY?

Ejecuta EXACTAMENTE lab/oraculo_n4_prereg.json. Verifica su sha256, lee el corpus congelado de
datos/gdelt_n4/ y evalua validacion (ajuste en entrenamiento) y luego la prueba sellada (reajuste
en entrenamiento + validacion). La prueba se abre una sola vez; --sintetico usa datos falsos.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from lab import oraculo_n4_datos as datos  # noqa: E402

PRECIOS = RAIZ / "datos" / "pit" / "precios" / "SPY.csv.gz"
SALIDA = RAIZ / "resultados" / "oraculo_n4.json"
CORTE_UTC = pd.Timestamp("2026-10-27T23:59:59Z")
HORIZONTES = (1, 5)
VENTANA_Z = 60           # alineacion: "60 ventanas anteriores"
MINIMO_Z = 20            # "mínimo 20 observaciones"
CLIP_Z = 5.0             # "recortado a [-5, 5]"
MIN_FILAS = 750
COBERTURA_MIN = 0.90
PRIMER_DIA_TODOS = pd.Timestamp("2017-06-30")
BLOQUE = 20              # estadistica.bootstrap: "bloques de 20 días"
C_LOGIT = 1.0
ALFA = 0.05
PRUEBAS = [("direccion", 1), ("direccion", 5), ("tamano", 1), ("tamano", 5)]

LIMITES = [
    "GDELT fecha cada artículo por su hora de indexación (seendate), no por su publicación; "
    "la disponibilidad usada es conservadora pero no exacta.",
    "GDELT puede haber reprocesado su histórico; no es verificable desde aquí y no se controla.",
    "El tono usa el clasificador léxico fijo de GDELT; no mide sentimiento contextual.",
    "El volumen es porcentaje de la cobertura monitoreada por GDELT, no número de noticias.",
    "Solo SPY, con precios sin ajustar; no se modelan costos ni ejecución.",
    "Una sola prueba sellada: un resultado positivo solo puede entrar a la bóveda y no cambia el plan 80/20.",
]


def noticias_de(prereg: dict) -> list[str]:
    return [f"{t}_{k}" for t in prereg["fuente_noticias"]["temas"] for k in ("vol", "tono")]


def cargar_spy() -> pd.DataFrame:
    return pd.read_csv(PRECIOS, usecols=["date", "open", "close", "available_at"], compression="gzip")


def preparar_spy(df: pd.DataFrame) -> pd.DataFrame:
    """Filas de SPY con available_at <= corte, ordenadas; el índice de fila es el índice de sesión."""
    df = df.assign(date=pd.to_datetime(df["date"]),
                   available_at=pd.to_datetime(df["available_at"], utc=True))
    df = df[df["available_at"] <= CORTE_UTC].dropna(subset=["open", "close"])
    df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    return df[["date", "open", "close"]]


def ventanas_noticias(fechas: pd.DatetimeIndex, diario: pd.DataFrame, noticias: list[str]) -> np.ndarray:
    """Media diaria de cada variable en los días UTC [T_prev, T-1]. Fila 0 sin T_prev."""
    d = diario.copy()
    d.index = pd.DatetimeIndex(pd.to_datetime(d.index))
    cal = pd.date_range(fechas[0], fechas[-1], freq="D")
    M = d.reindex(cal)[noticias].to_numpy(float)
    pos = np.asarray((fechas - cal[0]).days)
    A = np.full((len(fechas), len(noticias)), np.nan)
    for i in range(1, len(fechas)):
        W = M[pos[i - 1]:pos[i]]
        ok = ~np.isnan(W)
        n = ok.sum(0)
        s = np.where(ok, W, 0.0).sum(0)
        A[i] = np.where(n > 0, s / np.maximum(n, 1), np.nan)
    return A


def zscore_pasado(A: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Z-score contra las 60 filas anteriores (estrictamente pasado). Devuelve (Z, válida)."""
    n, k = A.shape
    Z = np.zeros((n, k))
    valida = np.zeros(n, bool)
    for i in range(n):
        H = A[max(0, i - VENTANA_Z):i]
        if len(H) == 0 or (~np.isnan(H)).sum(0).min() < MINIMO_Z:
            continue
        mu = np.nanmean(H, 0)
        sd = np.nanstd(H, 0)
        x = A[i]
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(sd > 0, (x - mu) / sd, 0.0)
        z = np.where(np.isnan(x), 0.0, z)  # ausente = 0 tras el z-score
        Z[i] = np.clip(z, -CLIP_Z, CLIP_Z)
        valida[i] = True
    return Z, valida


def har(close: np.ndarray) -> np.ndarray:
    """Columnas rv1, rv5, rv22 en T usando solo cierres hasta T_prev."""
    r = np.full(len(close), np.nan)
    r[1:] = np.abs(np.log(close[1:] / close[:-1]))
    s = pd.Series(r)
    return np.c_[s.shift(1).to_numpy(),
                 s.rolling(5).mean().shift(1).to_numpy(),
                 s.rolling(22).mean().shift(1).to_numpy()]


def objetivos(close: np.ndarray, open_: np.ndarray) -> dict:
    s = pd.Series(close)
    tg = {}
    for h in HORIZONTES:
        c_h = s.shift(-(h - 1)).to_numpy()  # close(T+h-1)
        tg[h] = {"sube": np.where(np.isnan(c_h), np.nan, (c_h > open_).astype(float)),
                 "abs": np.abs(np.log(c_h / open_))}
    return tg


def construir(spy: pd.DataFrame, diario: pd.DataFrame, noticias: list[str]) -> dict:
    fechas = pd.DatetimeIndex(spy["date"])
    close = spy["close"].to_numpy(float)
    open_ = spy["open"].to_numpy(float)
    A = ventanas_noticias(fechas, diario, noticias)
    Z, valida_z = zscore_pasado(A)
    RV = har(close)
    return {"fechas": fechas, "A": A, "Z": Z, "RV": RV, "hay": ~np.isnan(A).all(axis=1),
            "valida": valida_z & ~np.isnan(RV).any(axis=1), "tg": objetivos(close, open_)}


def rango(fechas: pd.DatetimeIndex, ini: str, fin: str) -> tuple[int, int]:
    m = np.flatnonzero((fechas >= pd.Timestamp(ini)) & (fechas <= pd.Timestamp(fin)))
    return (int(m[0]), int(m[-1])) if len(m) else (0, -1)


def conjunto(c: dict, a: int, b: int, h: int) -> np.ndarray:
    """Filas válidas en [a, b] cuyo objetivo T+h-1 cae también dentro de [a, b] (embargo)."""
    if b < a:
        return np.array([], dtype=int)
    i = np.arange(a, b + 1)
    ok = c["valida"][a:b + 1] & ~np.isnan(c["tg"][h]["abs"][a:b + 1]) & (i + h - 1 <= b)
    return i[ok]


def _iso(x):
    return None if x is None else pd.Timestamp(x).date().isoformat()


def _pct(hay: np.ndarray, a: int, b: int):
    return round(float(hay[a:b + 1].mean()), 4) if b >= a else None


def _primeras_ultimas(diario: pd.DataFrame, temas: list[str]):
    primera, ultima = {}, {}
    for t in temas:
        con = diario.index[diario[[f"{t}_vol", f"{t}_tono"]].notna().any(axis=1).to_numpy()]
        primera[t] = con.min() if len(con) else None
        ultima[t] = con.max() if len(con) else None
    return primera, ultima


def particion(c: dict, rangos_fecha: dict, primera_todos) -> tuple[str, list[str], dict]:
    """Partición por fechas del prereg; si falla un chequeo, respaldo 60/15/25 por filas válidas."""
    motivos = []
    if primera_todos is None or primera_todos > PRIMER_DIA_TODOS:
        motivos.append(f"primera fecha con datos de todos los temas: {_iso(primera_todos)}")
    for n, (a, b) in rangos_fecha.items():
        cov = _pct(c["hay"], a, b)
        if cov is None or cov < COBERTURA_MIN:
            motivos.append(f"tramo {n} con {cov} de días con noticias")
    if not motivos:
        return "fechas", motivos, rangos_fecha
    R = np.flatnonzero(c["valida"])
    n = len(R)
    n1 = int(0.60 * n)
    n2 = n1 + int(0.15 * n)
    rangos = {"entrenamiento": (int(R[0]), int(R[n1 - 1])),
              "validacion": (int(R[n1 - 1]) + 1, int(R[n2 - 1])),
              "prueba": (int(R[n2 - 1]) + 1, int(R[-1]))}
    return "cronologica_60_15_25", motivos, rangos


def _particion_info(c: dict, usada: str, motivos: list[str], rangos: dict) -> dict:
    f = c["fechas"]
    return {"usada": usada, "respaldo_usado": usada != "fechas",
            "motivo_respaldo": "; ".join(motivos) or None,
            "tramos": {n: {"inicio": _iso(f[a]), "fin": _iso(f[b]), "dias_habiles": b - a + 1,
                           "filas_validas": int(c["valida"][a:b + 1].sum()),
                           "pct_dias_con_noticias": _pct(c["hay"], a, b)}
                       for n, (a, b) in rangos.items()}}


def _cobertura(c: dict, rangos: dict, primeras: dict, ultimas: dict, temas: list[str]) -> dict:
    return {"primera_noticia_por_tema": {t: _iso(primeras[t]) for t in temas},
            "ultima_noticia_por_tema": {t: _iso(ultimas[t]) for t in temas},
            "pct_dias_con_noticias": {n: _pct(c["hay"], a, b) for n, (a, b) in rangos.items()}}


def sigmoide(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -500, 500)))


def logistica_l2(X: np.ndarray, y: np.ndarray, C: float = C_LOGIT, iteraciones: int = 100) -> np.ndarray:
    """Logística con penalización 1/(2C)*||w||^2 sin intercepto (primera columna), por Newton."""
    k = X.shape[1]
    pen = np.ones(k)
    pen[0] = 0.0
    lam = 1.0 / C

    def obj(w):
        z = X @ w
        return np.sum(np.logaddexp(0.0, z) - y * z) + 0.5 * lam * np.sum(pen * w * w)

    w = np.zeros(k)
    for _ in range(iteraciones):
        p = sigmoide(X @ w)
        g = X.T @ (p - y) + lam * pen * w
        H = (X * (p * (1 - p))[:, None]).T @ X + np.diag(lam * pen)
        paso = np.linalg.solve(H, g)
        t = 1.0
        f0 = obj(w)
        while t > 1e-6 and obj(w - t * paso) > f0:
            t /= 2
        w = w - t * paso
        if np.max(np.abs(t * paso)) < 1e-10:
            break
    return w


def ajustar_evaluar(c: dict, tipo: str, h: int, fit: np.ndarray, ev: np.ndarray) -> dict:
    """Ajusta en fit y devuelve la pérdida diaria de la base y del modelo en ev."""
    if tipo == "direccion":
        y = c["tg"][h]["sube"]
        Zf = c["Z"][fit]
        mu = Zf.mean(0)
        sd = Zf.std(0)
        sd = np.where(sd > 0, sd, 1.0)
        Xf = np.c_[np.ones(len(fit)), (Zf - mu) / sd]
        Xe = np.c_[np.ones(len(ev)), (c["Z"][ev] - mu) / sd]
        w = logistica_l2(Xf, y[fit])
        p = sigmoide(Xe @ w)
        ye = y[ev]
        return {"pb": (y[fit].mean() - ye) ** 2, "pm": (p - ye) ** 2,
                "exact": {"exactitud_modelo": float(np.mean((p > 0.5) == (ye == 1))),
                          "exactitud_siempre_sube": float(np.mean(ye == 1))}}
    a = c["tg"][h]["abs"]
    N = len(c["fechas"])
    X0 = np.c_[np.ones(N), c["RV"]]
    X1 = np.c_[X0, c["Z"]]
    b0 = np.linalg.lstsq(X0[fit], a[fit], rcond=None)[0]
    b1 = np.linalg.lstsq(X1[fit], a[fit], rcond=None)[0]
    return {"pb": (a[ev] - X0[ev] @ b0) ** 2, "pm": (a[ev] - X1[ev] @ b1) ** 2, "exact": {}}


def _resumen(pb: np.ndarray, pm: np.ndarray) -> dict:
    return {"perdida_base": float(pb.mean()), "perdida_modelo": float(pm.mean()),
            "mejora_media": float((pb - pm).mean())}


def bootstrap(x: np.ndarray, rng: np.random.Generator, rondas: int) -> tuple[float, list[float]]:
    """Bloques circulares de 20 días. Devuelve (p unilateral, IC95 percentil de medias)."""
    n = len(x)
    nb = -(-n // BLOQUE)
    inicios = rng.integers(0, n, size=(rondas, nb))
    idx = (inicios[:, :, None] + np.arange(BLOQUE)[None, None, :]) % n
    idx = idx.reshape(rondas, -1)[:, :n]
    medias = x[idx].mean(axis=1)
    p = (1 + np.count_nonzero(medias <= 0)) / (rondas + 1)
    lo, hi = np.percentile(medias, [2.5, 97.5])
    return float(p), [float(lo), float(hi)]


def bh(p) -> np.ndarray:
    p = np.asarray(p, float)
    m = len(p)
    orden = np.argsort(p)
    q = p[orden] * m / np.arange(1, m + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(m)
    out[orden] = np.minimum(q, 1.0)
    return out


def _limpio(x):
    if isinstance(x, dict):
        return {str(k): _limpio(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_limpio(v) for v in x]
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    return x


def _escribir(ruta, datos_: dict) -> dict:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(_limpio(datos_), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(ruta)
    return datos_


def _sin_evaluacion(base: dict, motivo: str, cobertura: dict, particion_info=None) -> dict:
    return {**base, "particion": particion_info, "cobertura": cobertura, "estado": "sin_evaluacion",
            "veredicto": "sin_evaluacion", "resumen": f"Sin evaluación: {motivo}.",
            "prueba_abierta": False, "pruebas": {}}


def ejecutar(prereg: dict, sha: str, spy_crudo: pd.DataFrame, diario: pd.DataFrame,
             manifiesto_sha, salida, sintetico: bool = False) -> dict:
    temas = list(prereg["fuente_noticias"]["temas"])
    diario = diario.copy()
    diario.index = pd.DatetimeIndex(pd.to_datetime(diario.index))
    c = construir(preparar_spy(spy_crudo), diario, noticias_de(prereg))
    fechas = c["fechas"]
    pa = prereg["particion"]
    tramos_fecha = {"entrenamiento": pa["entrenamiento"], "validacion": pa["validacion"],
                    "prueba": pa["prueba_sellada"]}
    rangos_fecha = {n: rango(fechas, *f) for n, f in tramos_fecha.items()}
    primeras, ultimas = _primeras_ultimas(diario, temas)
    primera_todos = None if any(v is None for v in primeras.values()) else max(primeras.values())
    n_valid = int(c["valida"].sum())
    base = {"prereg_sha256": sha, "prereg_version": prereg["version"],
            "ejecutado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sintetico": sintetico, "manifiesto_datos_sha256": manifiesto_sha,
            "n_filas_validas": n_valid, "limites": LIMITES}
    if n_valid < MIN_FILAS:
        cob = _cobertura(c, rangos_fecha, primeras, ultimas, temas)
        return _escribir(salida, _sin_evaluacion(base, f"{n_valid} filas válidas (mínimo {MIN_FILAS})", cob))

    usada, motivos, rangos = particion(c, rangos_fecha, primera_todos)
    base["particion"] = _particion_info(c, usada, motivos, rangos)
    base["cobertura"] = _cobertura(c, rangos, primeras, ultimas, temas)
    (a_tr, b_tr), (a_va, b_va), (a_te, b_te) = (rangos[k] for k in ("entrenamiento", "validacion", "prueba"))

    sets = {}
    for tipo, h in PRUEBAS:
        nombre = f"{tipo}_h{h}"
        sets[nombre] = {"val": (conjunto(c, a_tr, b_tr, h), conjunto(c, a_va, b_va, h)),
                        "pru": (conjunto(c, a_tr, b_va, h), conjunto(c, a_te, b_te, h))}
    if min(len(x) for s in sets.values() for par in s.values() for x in par) == 0:
        return _escribir(salida, _sin_evaluacion(base, "tramo sin filas evaluables tras embargo",
                                                 base["cobertura"], base["particion"]))

    # Validacion: ajuste en entrenamiento, medida en validacion.
    pruebas = {}
    for tipo, h in PRUEBAS:
        nombre = f"{tipo}_h{h}"
        fit, ev = sets[nombre]["val"]
        r = ajustar_evaluar(c, tipo, h, fit, ev)
        pruebas[nombre] = {"tipo": tipo, "horizonte": h,
                           "metrica": "brier" if tipo == "direccion" else "error_cuadratico",
                           "n_validacion": len(ev), "validacion": _resumen(r["pb"], r["pm"])}

    # Se abre la prueba sellada: queda anotado aunque la corrida falle después.
    _escribir(salida, {**base, "estado": "interrumpido", "veredicto": "interrumpido",
                       "resumen": "Corrida interrumpida después de abrir la prueba sellada; cuenta como intento.",
                       "prueba_abierta": True, "pruebas": pruebas})

    # Prueba: reajuste en entrenamiento + validacion, medida en la prueba sellada.
    rng = np.random.default_rng(int(prereg["estadistica"]["semilla"]))
    rondas = int(prereg["estadistica"]["bootstrap_rondas"])
    for tipo, h in PRUEBAS:
        nombre = f"{tipo}_h{h}"
        fit, ev = sets[nombre]["pru"]
        r = ajustar_evaluar(c, tipo, h, fit, ev)
        dif = r["pb"] - r["pm"]
        p, ic = bootstrap(dif, rng, rondas)
        prueba = {"n": len(ev), **_resumen(r["pb"], r["pm"]), "ic95": ic, "p": p}
        prueba.update(r["exact"])
        pruebas[nombre]["prueba"] = prueba

    nombres = [f"{t}_h{h}" for t, h in PRUEBAS]
    for nombre, q in zip(nombres, bh([pruebas[k]["prueba"]["p"] for k in nombres])):
        pr = pruebas[nombre]["prueba"]
        pr["q_BH"] = float(q)
        pr["aprobada"] = bool(q < ALFA and pr["mejora_media"] > 0 and pruebas[nombre]["validacion"]["mejora_media"] > 0)

    nivel_dir = any(pruebas[k]["prueba"]["aprobada"] for k in nombres if k.startswith("direccion"))
    nivel_tam = any(pruebas[k]["prueba"]["aprobada"] for k in nombres if k.startswith("tamano"))
    if nivel_dir:
        veredicto = "direccion_aprobada"
        resumen = "Nivel 4 aprobado: las noticias GDELT superan la tasa base de dirección de SPY en la prueba sellada."
    elif nivel_tam:
        veredicto = "tamano_si_direccion_no"
        resumen = ("Tamaño sí, dirección no: las noticias mejoran el tamaño del movimiento de SPY sobre HAR, "
                   "pero no la dirección; no da ventaja para comprar ni vender.")
    else:
        veredicto = "ninguna"
        resumen = "No aprobado: ninguna prueba del nivel 4 supera su base en la prueba sellada con los criterios del prereg."
    return _escribir(salida, {**base, "pruebas": pruebas, "nivel_direccion_aprobado": nivel_dir,
                              "nivel_tamano_aprobado": nivel_tam,
                              "estado": "aprobado" if nivel_dir else "no_aprobado",
                              "veredicto": veredicto, "resumen": resumen, "prueba_abierta": True})


def _sintetico(prereg: dict, seed: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Datos falsos con el mismo formato que los reales (solo para pruebas)."""
    rng = np.random.default_rng(seed)
    fechas = pd.bdate_range("2015-01-01", "2026-10-27")
    cierre = 200 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(fechas))))
    apertura = np.r_[cierre[0], cierre[:-1]] * np.exp(rng.normal(0, 0.003, len(fechas)))
    spy = pd.DataFrame({"date": [f"{d:%Y-%m-%d}" for d in fechas], "open": apertura, "close": cierre,
                        "available_at": [f"{d:%Y-%m-%d}T20:00:00Z" for d in fechas]})
    cal = pd.date_range("2015-01-01", "2026-10-27", freq="D")
    cols = {}
    for nombre in noticias_de(prereg):
        v = rng.normal(0, 1, len(cal))
        v[rng.random(len(cal)) < 0.05] = np.nan
        cols[nombre] = v
    diario = pd.DataFrame(cols, index=[d.date() for d in cal])
    return spy, diario


def _prueba_abierta(ruta) -> bool:
    if not Path(ruta).exists():
        return False
    try:
        previo = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True  # ilegible: no se arriesga la prueba sellada
    return bool(previo.get("prueba_abierta")) if isinstance(previo, dict) else True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Oraculo nivel 4 (prereg sellado).")
    ap.add_argument("--sintetico", action="store_true",
                    help="datos falsos, salida temporal, ignora la guarda (solo pruebas)")
    args = ap.parse_args(argv)
    prereg, sha = datos.verificar_prereg()
    if args.sintetico:
        spy, diario = _sintetico(prereg)
        manifiesto_sha = None
        salida = Path(tempfile.gettempdir()) / "oraculo_n4_sintetico.json"
    else:
        if _prueba_abierta(SALIDA):
            print(f"La prueba sellada ya se abrió en {SALIDA}; no se vuelve a correr.")
            return 1
        spy = cargar_spy()
        diario = datos.cargar_diario()
        manifiesto_sha = hashlib.sha256(datos.MANIFIESTO.read_bytes()).hexdigest()
        salida = SALIDA
    res = ejecutar(prereg, sha, spy, diario, manifiesto_sha, salida, sintetico=args.sintetico)
    print(f"{res['estado']}: {res['resumen']}")
    print(f"resultado en {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
