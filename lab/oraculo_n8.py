"""Oraculo nivel 8: pronostico de la volatilidad (riesgo) del mes siguiente.

Ejecuta EXACTAMENTE lab/oraculo_n8_prereg.json (pre-registro sellado) usando solo la biblioteca
estandar de Python. Al arrancar verifica el sha256 del prereg contra lab/oraculo_n8_prereg.sha256
y aborta si no coincide.

Uso:
  python3 lab/oraculo_n8.py --validacion    entrenamiento + validacion. No calcula metricas de la
                                            prueba sellada y no escribe resultados.
  python3 lab/oraculo_n8.py --abrir-prueba  apertura UNICA de la prueba sellada. Se niega (exit 2) si
                                            resultados/oraculo_n8.json ya registra una apertura.

Sin lookahead: el pronostico del origen t se calcula solo con r_1..r_t (cierres hasta t). El
objetivo rv21 usa r_{t+1}..r_{t+21}. Los coeficientes HAR se ajustan solo con origenes del tramo
de entrenamiento. Las filas con available_at <= el de t son exactamente las filas 0..t.
"""
from __future__ import annotations

import bisect
import csv
import gzip
import hashlib
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PRECIOS = RAIZ / "datos" / "pit" / "precios"
PREREG = RAIZ / "lab" / "oraculo_n8_prereg.json"
PREREG_SHA = RAIZ / "lab" / "oraculo_n8_prereg.sha256"
SALIDA = RAIZ / "resultados" / "oraculo_n8.json"

VERSION = "oraculo-nivel8"
ACTIVO = "_GSPC"
SECUNDARIOS = ["QQQ", "VT"]
VENTANA_HIST = 252             # sesiones de historia previa (B0 y semilla EWMA)
HORIZONTE = 21                 # sesiones del objetivo y del intervalo
ESCALA = 21                    # d_t, w_t, m_t y pronosticos en unidades de rv21
LAMBDA = 0.94                  # M1 EWMA (RiskMetrics)
Z95 = 1.96                     # intervalo 95 %
ALFA = 0.05                    # aprobacion: q_BH < 0.05
BLOQUE = 63                    # bootstrap circular por bloques
CORTE_ORIGEN = "2026-10-15"    # datos.corte: ultimo dia de origen
CORTE_OBJETIVO = "2026-11-13"  # datos.corte: cierres del objetivo <= este dia
INICIO = "0000-00-00"          # "inicio" del prereg
MODELOS = ["B0", "B1", "M1", "M2"]
COMPARADOS = ["B1", "M1", "M2"]  # frente a B0
PRINCIPALES = ["M1", "M2"]       # comparaciones principales en la prueba sellada
MARCAS_OPCION = {"--validacion", "--abrir-prueba"}


# ---------------------------------------------------------------- prereg

def verificar_prereg(ruta: Path = PREREG, ruta_sha: Path = PREREG_SHA) -> tuple[dict, str]:
    """Devuelve (prereg, sha256). Aborta si el sha256 de los bytes no coincide con el sidecar."""
    # Git en Windows puede convertir LF a CRLF; se hashea el texto canonico con LF.
    datos = Path(ruta).read_bytes().replace(b"\r\n", b"\n")
    esperado = Path(ruta_sha).read_text(encoding="utf-8").split()[0].lower()
    real = hashlib.sha256(datos).hexdigest()
    if real != esperado:
        raise RuntimeError(f"sha256 del prereg no coincide: esperado {esperado}, real {real}. Abortado.")
    prereg = json.loads(datos.decode("utf-8"))
    if prereg["datos"]["particion"]["prueba_sellada"][1] != CORTE_ORIGEN:
        raise RuntimeError("el prereg cambio el corte de origen; este codigo no lo implementa")
    return prereg, real


def tramos(prereg: dict) -> dict[str, tuple[str, str]]:
    """Tramos por fecha de origen: nombre -> (inicio, fin) como 'YYYY-MM-DD'."""
    out = {}
    for nombre, (ini, fin) in prereg["datos"]["particion"].items():
        out[nombre] = (INICIO if ini == "inicio" else ini, fin)
    return out


# ---------------------------------------------------------------- datos

class Serie:
    """Cierres diarios de un activo, ordenados por fecha. Indice k = sesion k."""

    def __init__(self, simbolo: str, fechas: list[str], cierres: list[float], disponible: list[datetime]):
        self.simbolo = simbolo
        self.fechas = fechas
        self.cierres = cierres
        self.disponible = disponible


def cargar(simbolo: str, carpeta: Path = PRECIOS) -> Serie:
    fechas, cierres, disp = [], [], []
    with gzip.open(carpeta / f"{simbolo}.csv.gz", "rt", newline="") as f:
        for fila in csv.DictReader(f):
            if not fila["close"]:
                continue
            c = float(fila["close"])
            if c <= 0:
                raise RuntimeError(f"{simbolo}: cierre no positivo en {fila['date']}")
            fechas.append(fila["date"])
            cierres.append(c)
            disp.append(datetime.fromisoformat(fila["available_at"].replace("Z", "+00:00")))
    if any(fechas[i] >= fechas[i + 1] for i in range(len(fechas) - 1)):
        raise RuntimeError(f"{simbolo}: fechas no estrictamente crecientes")
    if any(disp[i] >= disp[i + 1] for i in range(len(disp) - 1)):
        raise RuntimeError(f"{simbolo}: available_at no estrictamente creciente")
    return Serie(simbolo, fechas, cierres, disp)


# ---------------------------------------------------------------- caracteristicas causales

def caracteristicas(s: Serie) -> dict[str, list]:
    """Pronosticos y objetivos por indice k. F[nombre][k] depende de cierres 0..k (salvo rv21, R21)."""
    c = s.cierres
    n = len(c)
    sq = [0.0] * n                       # r_k^2, r_k = ln(c_k / c_{k-1})
    for k in range(1, n):
        r = math.log(c[k] / c[k - 1])
        sq[k] = r * r
    cs = [0.0] * (n + 1)                 # cs[k+1] = suma de sq[0..k]
    for k in range(n):
        cs[k + 1] = cs[k] + sq[k]

    def media(a: int, b: int) -> float:  # media de r^2 en las sesiones a..b (inclusive)
        return (cs[b + 1] - cs[a]) / (b - a + 1)

    F = {nombre: [None] * n for nombre in ("b0", "b1", "m1", "d", "w", "m", "rv21", "R21")}
    s2 = None
    for k in range(VENTANA_HIST, n):
        # Semilla EWMA = media de r^2 de las primeras 252 sesiones (r_1..r_252), asignada a k=252.
        s2 = media(1, k) if k == VENTANA_HIST else LAMBDA * s2 + (1 - LAMBDA) * sq[k]
        F["m1"][k] = ESCALA * s2
        F["b0"][k] = ESCALA * media(k - 251, k)
        F["b1"][k] = ESCALA * media(k - 20, k)
        F["d"][k] = ESCALA * sq[k]
        F["w"][k] = ESCALA * media(k - 4, k)
        F["m"][k] = ESCALA * media(k - 21, k)
        if k + HORIZONTE < n:
            F["rv21"][k] = cs[k + HORIZONTE + 1] - cs[k + 1]          # suma r^2 de k+1..k+21
            F["R21"][k] = math.log(c[k + HORIZONTE] / c[k])          # retorno log a 21 sesiones
    return F


def origenes(s: Serie, ini: str, fin: str) -> list[int]:
    """Origenes del tramo [ini, fin] (por fecha de origen) con 252 previas y 21 posteriores en el corte."""
    n = len(s.fechas)
    out = []
    for k in range(VENTANA_HIST, n - HORIZONTE):
        f = s.fechas[k]
        if not (ini <= f <= fin) or f > CORTE_ORIGEN:
            continue
        if s.fechas[k + HORIZONTE] > CORTE_OBJETIVO:
            continue
        # Regla de tiempo: las filas con available_at <= el de k son exactamente 0..k.
        if bisect.bisect_right(s.disponible, s.disponible[k]) != k + 1:
            raise RuntimeError(f"{s.simbolo}: available_at no permite separar el origen {f}")
        out.append(k)
    return out


# ---------------------------------------------------------------- HAR y pronosticos

def resolver(A: list[list[float]], b: list[float]) -> list[float]:
    """Resuelve A x = b por eliminacion gaussiana con pivoteo parcial."""
    n = len(b)
    M = [fila[:] + [b[i]] for i, fila in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-300:
            raise ValueError("sistema singular")
        M[col], M[piv] = M[piv], M[col]
        for r in range(col + 1, n):
            factor = M[r][col] / M[col][col]
            for j in range(col, n + 1):
                M[r][j] -= factor * M[col][j]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))) / M[i][i]
    return x


def ajustar_har(F: dict, ks: list[int]) -> list[float]:
    """MCO de rv21 sobre [1, d, w, m] con las ecuaciones normales (4x4)."""
    A = [[0.0] * 4 for _ in range(4)]
    b = [0.0] * 4
    for k in ks:
        x = [1.0, F["d"][k], F["w"][k], F["m"][k]]
        y = F["rv21"][k]
        for i in range(4):
            b[i] += x[i] * y
            for j in range(4):
                A[i][j] += x[i] * x[j]
    return resolver(A, b)


def pronosticos_en(F: dict, k: int, beta: list[float]) -> tuple[dict, bool]:
    """Pronosticos del origen k. Lee solo F[.][k], construido con cierres 0..k."""
    b0 = F["b0"][k]
    har = beta[0] + beta[1] * F["d"][k] + beta[2] * F["w"][k] + beta[3] * F["m"][k]
    fallback = har <= 0
    pr = {"B0": b0, "B1": F["b1"][k], "M1": F["m1"][k], "M2": b0 if fallback else har}
    return pr, fallback


# ---------------------------------------------------------------- metricas

def qlike(y: float, f: float) -> float:
    if y <= 0 or f <= 0:
        raise ValueError(f"QLIKE requiere y>0 y f>0 (y={y}, f={f})")
    u = y / f
    return u - math.log(u) - 1.0


def _media(xs: list[float]) -> float:
    return math.fsum(xs) / len(xs)


def evaluar(F: dict, ks: list[int], beta: list[float]) -> tuple[dict, dict[str, list[float]]]:
    """Metricas del tramo. Devuelve (resumen, serie de mejora por origen frente a B0)."""
    if not ks:
        raise RuntimeError("tramo sin origenes")
    L = {m: [] for m in MODELOS}
    mse = {m: [] for m in MODELOS}
    cub = {m: 0 for m in MODELOS}
    anc = {m: 0.0 for m in MODELOS}
    mej = {m: [] for m in COMPARADOS}
    fallbacks = 0
    for k in ks:
        pr, fb = pronosticos_en(F, k, beta)
        fallbacks += int(fb)
        y, R = F["rv21"][k], F["R21"][k]
        Lk = {m: qlike(y, pr[m]) for m in MODELOS}
        for m in MODELOS:
            L[m].append(Lk[m])
            mse[m].append((y - pr[m]) ** 2)
            h = Z95 * math.sqrt(pr[m])
            cub[m] += int(-h <= R <= h)
            anc[m] += 2 * h
        for m in COMPARADOS:
            mej[m].append(Lk["B0"] - Lk[m])
    n = len(ks)
    resumen = {
        "n_origenes": n,
        "primer_origen": None,  # se llena por el llamador con la fecha
        "fallbacks_M2_a_B0": fallbacks,
        "qlike_medio": {m: _media(L[m]) for m in MODELOS},
        "mejora_media_vs_B0": {m: _media(mej[m]) for m in COMPARADOS},
        "mse_medio": {m: _media(mse[m]) for m in MODELOS},
        "cobertura_95": {m: cub[m] / n for m in MODELOS},
        "ancho_medio_95": {m: anc[m] / n for m in MODELOS},
    }
    return resumen, mej


# ---------------------------------------------------------------- estadistica

def p_bootstrap(x: list[float], rng: random.Random, rondas: int) -> float:
    """p unilateral: (1 + #{media bootstrap <= 0}) / (rondas + 1), bloques circulares de 63."""
    n = len(x)
    nb = -(-n // BLOQUE)
    cuenta = 0
    for _ in range(rondas):
        muestra = []
        for _ in range(nb):
            ini = rng.randrange(n)
            muestra.extend(x[(ini + j) % n] for j in range(BLOQUE))
        if math.fsum(muestra[:n]) / n <= 0:
            cuenta += 1
    return (1 + cuenta) / (rondas + 1)


def bh(p: list[float]) -> list[float]:
    """Benjamini-Hochberg: q-valores en el orden de entrada."""
    p = [float(x) for x in p]
    m = len(p)
    orden = sorted(range(m), key=lambda i: p[i])
    q = [p[i] * m / (r + 1) for r, i in enumerate(orden)]
    for r in range(m - 2, -1, -1):
        q[r] = min(q[r], q[r + 1])
    out = [0.0] * m
    for r, i in enumerate(orden):
        out[i] = min(q[r], 1.0)
    return out


# ---------------------------------------------------------------- flujo

def preparar(prereg: dict, precios: dict[str, Serie]) -> dict:
    """Ajusta HAR por activo solo con origenes de entrenamiento. Solo toca entrenamiento y validacion."""
    tr = tramos(prereg)
    M = {}
    for sym, s in precios.items():
        F = caracteristicas(s)
        ks_ent = origenes(s, *tr["entrenamiento"])
        beta = ajustar_har(F, ks_ent)
        M[sym] = {
            "serie": s,
            "F": F,
            "beta": beta,
            "ks": {"entrenamiento": ks_ent, "validacion": origenes(s, *tr["validacion"])},
        }
    return M


def resumen_tramos(M: dict, nombres: list[str]) -> dict:
    out = {}
    for sym, d in M.items():
        out[sym] = {}
        for nombre in nombres:
            ks = d["ks"][nombre]
            res, _ = evaluar(d["F"], ks, d["beta"])
            res["primer_origen"] = d["serie"].fechas[ks[0]]
            res["ultimo_origen"] = d["serie"].fechas[ks[-1]]
            out[sym][nombre] = res
    return out


def prueba_sellada(prereg: dict, precios: dict[str, Serie], M: dict, sha: str) -> dict:
    """Solo se llama DESPUES de escribir la marca de apertura."""
    tr = tramos(prereg)
    rondas = int(prereg["estadistica"]["bootstrap_rondas"])
    semilla = int(prereg["estadistica"]["semilla"])
    rng = random.Random(semilla)
    series_principal = {}
    for sym in precios:
        d = M[sym]
        d["ks"]["prueba"] = origenes(d["serie"], *tr["prueba_sellada"])
        res, mej = evaluar(d["F"], d["ks"]["prueba"], d["beta"])
        res["primer_origen"] = d["serie"].fechas[d["ks"]["prueba"][0]]
        res["ultimo_origen"] = d["serie"].fechas[d["ks"]["prueba"][-1]]
        d["prueba"] = res
        if sym == ACTIVO:
            series_principal = mej
    # Comparaciones principales: solo en _GSPC, orden fijo M1 y luego M2.
    p = {m: p_bootstrap(series_principal[m], rng, rondas) for m in PRINCIPALES}
    q = dict(zip(PRINCIPALES, bh([p[m] for m in PRINCIPALES])))
    mej_val = M[ACTIVO]["validacion_resumen"]["mejora_media_vs_B0"]
    comparaciones = {}
    for m in PRINCIPALES:
        aprobado = bool(q[m] < ALFA and mej_val[m] > 0)
        comparaciones[m] = {
            "p_vs_B0": p[m],
            "q_BH": q[m],
            "mejora_media_prueba": M[ACTIVO]["prueba"]["mejora_media_vs_B0"][m],
            "mejora_media_validacion": mej_val[m],
            "aprobado": aprobado,
        }
    aprobados = [m for m in PRINCIPALES if comparaciones[m]["aprobado"]]
    return {"comparaciones": comparaciones, "aprobados": aprobados, "rondas": rondas, "semilla": semilla}


def ya_abierto(ruta: Path) -> bool:
    """True si el archivo ya registra una apertura, o si no se puede leer (por precaucion)."""
    if not ruta.exists():
        return False
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if not isinstance(datos, dict):
        return True
    return int(datos.get("aperturas_prueba_sellada", 0)) >= 1


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _har_dict(beta: list[float], n: int) -> dict:
    return {"b0": beta[0], "b1": beta[1], "b2": beta[2], "b3": beta[3], "origenes_entrenamiento": n}


def imprimir_validacion(sha: str, M: dict, resumen: dict) -> None:
    print("Oraculo nivel 8: entrenamiento + validacion (prueba sellada NO abierta)")
    print(f"prereg sha256 {sha}")
    print("Coeficientes HAR (MCO solo con origenes de entrenamiento, por activo):")
    for sym in [ACTIVO] + SECUNDARIOS:
        b = M[sym]["beta"]
        n = len(M[sym]["ks"]["entrenamiento"])
        print(f"  {sym}: n={n} b0={b[0]!r} b1={b[1]!r} b2={b[2]!r} b3={b[3]!r}")
    for nombre in ["entrenamiento", "validacion"]:
        for sym in [ACTIVO] + SECUNDARIOS:
            r = resumen[sym][nombre]
            print(f"[{nombre}] {sym}: n={r['n_origenes']} ({r['primer_origen']}..{r['ultimo_origen']}) "
                  f"fallbacks_M2={r['fallbacks_M2_a_B0']}")
            print("  QLIKE medio: " + " ".join(f"{m}={r['qlike_medio'][m]!r}" for m in MODELOS))
            print("  mejora media vs B0 (+ = mejor): " +
                  " ".join(f"{m}={r['mejora_media_vs_B0'][m]!r}" for m in COMPARADOS))
            print("  MSE medio: " + " ".join(f"{m}={r['mse_medio'][m]!r}" for m in MODELOS))
            print("  cobertura 95 %: " + " ".join(f"{m}={r['cobertura_95'][m]!r}" for m in MODELOS))
            print("  ancho medio 95 % (log-retorno 21 s): " +
                  " ".join(f"{m}={r['ancho_medio_95'][m]!r}" for m in MODELOS))
    print("p y q_BH de la prueba sellada: no se calculan en --validacion.")


def validar(prereg: dict, sha: str, precios: dict[str, Serie]) -> dict:
    M = preparar(prereg, precios)
    resumen = resumen_tramos(M, ["entrenamiento", "validacion"])
    return {"M": M, "resumen": resumen}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    validacion = "--validacion" in args
    abrir = "--abrir-prueba" in args
    if validacion == abrir or set(args) - MARCAS_OPCION:
        print("uso: python3 lab/oraculo_n8.py --validacion | --abrir-prueba", file=sys.stderr)
        return 2
    try:
        prereg, sha = verificar_prereg()
    except RuntimeError as err:
        print(err, file=sys.stderr)
        return 1
    if abrir and ya_abierto(SALIDA):
        print(f"negado: {SALIDA} ya registra una apertura de la prueba sellada. No se reabre.",
              file=sys.stderr)
        return 2
    precios = {s: cargar(s) for s in [ACTIVO] + SECUNDARIOS}
    if validacion:
        v = validar(prereg, sha, precios)
        imprimir_validacion(sha, v["M"], v["resumen"])
        return 0

    # Apertura: validacion primero, luego marca ANTES de tocar la prueba sellada.
    v = validar(prereg, sha, precios)
    M = v["M"]
    for sym in M:
        M[sym]["validacion_resumen"] = v["resumen"][sym]["validacion"]
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    marca = {
        "version": VERSION,
        "prereg_sha256": sha,
        "generado_utc": _ahora(),
        "aperturas_prueba_sellada": 1,
        "estado": "apertura_en_curso",
    }
    SALIDA.write_text(json.dumps(marca, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    sellada = prueba_sellada(prereg, precios, M, sha)
    nivel_aprobado = bool(sellada["aprobados"])
    tr = tramos(prereg)
    res = {
        "version": VERSION,
        "prereg_sha256": sha,
        "generado_utc": _ahora(),
        "aperturas_prueba_sellada": 1,
        "estado": "completa",
        "parametros": {
            "lambda": LAMBDA,
            "ventana_historia_sesiones": VENTANA_HIST,
            "horizonte_sesiones": HORIZONTE,
            "bloque_bootstrap": BLOQUE,
            "semilla": sellada["semilla"],
            "bootstrap_rondas": sellada["rondas"],
            "tramos": {k: list(v) for k, v in tr.items()},
            "corte_origen": CORTE_ORIGEN,
            "corte_objetivo": CORTE_OBJETIVO,
        },
        "coeficientes_har": {sym: _har_dict(M[sym]["beta"], len(M[sym]["ks"]["entrenamiento"]))
                             for sym in M},
        "tramos": {sym: {"entrenamiento": v["resumen"][sym]["entrenamiento"],
                         "validacion": v["resumen"][sym]["validacion"],
                         "prueba": M[sym]["prueba"]} for sym in M},
        "comparaciones_principales_GSPC": sellada["comparaciones"],
        "aprobados": sellada["aprobados"],
        "nivel8": {"estado": "aprobado" if nivel_aprobado else "no aprobado",
                   "aprobado": nivel_aprobado},
    }
    SALIDA.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"prueba sellada abierta; nivel8={res['nivel8']['estado']} escrito {SALIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
