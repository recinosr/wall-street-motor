"""Oraculo nivel 7: reglas de aporte mensual contra el plan 80/20 de compra fija.

Ejecuta EXACTAMENTE lab/oraculo_n7_prereg.json (pre-registro sellado). Al arrancar verifica el
sha256 del prereg contra lab/oraculo_n7_prereg.sha256 y aborta si no coincide.

Sin lookahead: la decision del primer dia habil del mes solo usa filas con available_at <= inicio
de ese dia (es decir, el cierre de la sesion previa). La orden se ejecuta al close del mismo dia,
con spread de compra. Los dividendos se acumulan diario como yield/252 sobre las unidades
invertidas, reinvertidos al close del dia sin spread. El efectivo rinde 0.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
PRECIOS = RAIZ / "datos" / "pit" / "precios"
PREREG = RAIZ / "lab" / "oraculo_n7_prereg.json"
PREREG_SHA = RAIZ / "lab" / "oraculo_n7_prereg.sha256"
SALIDA = RAIZ / "resultados" / "oraculo_n7.json"
INFORME = RAIZ / "docs" / "oraculo_nivel7.md"

# Numeros literales del texto de las reglas del prereg (seccion "reglas").
UMBRAL_CAIDA = 0.05            # R1_caida: "al menos 5 % por debajo de su maximo"
VENTANA_MAX_SESIONES = 252     # R1_caida: "maximo de 252 sesiones"
MESES_SIN_CAIDA = 12           # R1_caida: "si se acumulan 12 meses sin caida, compra todo"
SMA_SESIONES = 200             # R2_sma200 y R3: "media de 200 sesiones"
FRAC_R3 = 0.5                  # R3_doble_en_caida: "compra 50 %"
BANDA_MIN, BANDA_MAX = 0.15, 0.25  # R4_sin_banda: "SPY pesa fuera de 15-25 %"
PESO_SPY_OBJETIVO = 0.20       # R4_sin_banda: "hasta volver a 20 %"
MES_BANDA = 10                 # R4_sin_banda: "cada octubre"
SESIONES_ANIO = 252            # dividendos: "dividendo_anual/252" por sesion
BLOQUE_VENTANAS = 24           # estadistica.bootstrap: "bloques de 24 ventanas consecutivas"
CORTE_DATOS = pd.Timestamp("2026-10-15")  # datos.nota_ventanas: "antes del 2026-10-15"
ALFA = 0.05                    # estadistica.aprobada: "q_BH < 0.05"

# Reglas por tramo (prereg: validacion R0-R3, R4 se omite; prueba R0-R4).
REGLAS_VALIDACION = ["R0", "R1", "R2", "R3"]
REGLAS_PRUEBA = ["R0", "R1", "R2", "R3", "R4"]


def verificar_prereg(ruta: Path = PREREG, ruta_sha: Path = PREREG_SHA) -> tuple[dict, str]:
    """Devuelve (prereg, sha256). Aborta si el sha256 de los bytes no coincide con el sidecar."""
    datos = Path(ruta).read_bytes()
    esperado = Path(ruta_sha).read_text(encoding="utf-8").split()[0].lower()
    real = hashlib.sha256(datos).hexdigest()
    if real != esperado:
        raise RuntimeError(f"sha256 del prereg no coincide: esperado {esperado}, real {real}. Abortado.")
    return json.loads(datos.decode("utf-8")), real


def cargar(simbolo: str) -> pd.DataFrame:
    with gzip.open(PRECIOS / f"{simbolo}.csv.gz", "rt") as f:
        df = pd.read_csv(io.StringIO(f.read()), usecols=["date", "close", "available_at"])
    df["date"] = pd.to_datetime(df["date"]).dt.as_unit("ns")
    df["available_at"] = pd.to_datetime(df["available_at"], utc=True).dt.as_unit("ns")
    df = df.dropna(subset=["close"]).sort_values("date").drop_duplicates("date")
    if not df["available_at"].is_monotonic_increasing:
        raise RuntimeError(f"{simbolo}: available_at no es monotono con la fecha")
    return df.reset_index(drop=True)


def _ns_utc(serie: pd.Series) -> np.ndarray:
    return serie.dt.tz_convert(None).to_numpy(dtype="datetime64[ns]").astype(np.int64)


class Senal:
    """Indicadores sobre la serie de cierres. Solo lee filas con available_at <= momento de la orden."""

    def __init__(self, df: pd.DataFrame):
        self.disponible = _ns_utc(df["available_at"])
        self.cierre = df["close"].to_numpy(float)
        s = pd.Series(self.cierre)
        self.caida_pct = (s / s.rolling(VENTANA_MAX_SESIONES).max() - 1).to_numpy()
        self.sma = s.rolling(SMA_SESIONES).mean().to_numpy()

    def _indice(self, orden_ns: int) -> int:
        return int(np.searchsorted(self.disponible, orden_ns, side="right")) - 1

    def caida(self, orden_ns: int):
        i = self._indice(orden_ns)
        if i < 0 or np.isnan(self.caida_pct[i]):
            return None
        return bool(self.caida_pct[i] <= -UMBRAL_CAIDA)

    def sobre_sma(self, orden_ns: int):
        i = self._indice(orden_ns)
        if i < 0 or np.isnan(self.sma[i]):
            return None
        return bool(self.cierre[i] > self.sma[i])


class Calendario:
    def __init__(self, fechas, C, activos: list[str], dividendos: dict[str, float]):
        fechas = pd.DatetimeIndex(fechas)
        self.fechas = fechas
        self.C = np.asarray(C, float)
        self.activos = activos
        self.mo = np.asarray(fechas.year * 12 + fechas.month)
        self.mes = np.asarray(fechas.month)
        self.primer = np.r_[True, self.mo[1:] != self.mo[:-1]]
        self.orden = np.asarray(fechas.values, dtype="datetime64[ns]").astype(np.int64)
        self.fac = np.array([1 + dividendos[a] / SESIONES_ANIO for a in activos], float)


def calendario(dfs: dict[str, pd.DataFrame], dividendos: dict[str, float]) -> Calendario:
    m = None
    for sym, df in dfs.items():
        x = df[["date", "close"]].rename(columns={"close": sym})
        m = x if m is None else m.merge(x, on="date", how="inner")
    return Calendario(m["date"], m[list(dfs)].to_numpy(float), list(dfs), dividendos)


def ventanas(cal: Calendario, inicio: pd.Timestamp, fin: pd.Timestamp) -> list[tuple[int, int, int]]:
    """(mes_ordinal, indice_inicio, indice_valoracion). Una por primer dia habil del mes en [inicio, fin]."""
    primero, ultimo = {}, {}
    for t, m in enumerate(cal.mo):
        m = int(m)
        primero.setdefault(m, t)
        ultimo[m] = t
    out = []
    for m in sorted(primero):
        s = primero[m]
        if not (inicio <= cal.fechas[s] <= fin):
            continue
        if not all(k in primero for k in range(m, m + 60)):
            continue
        e = ultimo[m + 59]
        if cal.fechas[e] > CORTE_DATOS:
            continue
        out.append((m, s, e))
    return out


def simular(cal: Calendario, senal: Senal, regla: str, pesos: np.ndarray, m0: int, s: int, e: int,
            P: dict, usar_banda: bool) -> dict:
    """Simula una ventana diaria. Decisiones solo en el primer dia habil de cada mes de la ventana."""
    A = len(cal.activos)
    C, mo, mes, primer, orden, fac = cal.C, cal.mo, cal.mes, cal.primer, cal.orden, cal.fac
    aporte, ventana, spread = P["aporte"], P["ventana"], P["spread"]
    iS = cal.activos.index("SPY") if usar_banda else -1
    units = np.zeros(A)
    pot = 0.0          # efectivo sin invertir (nominal, sin interes)
    meses_pot = 0      # meses de aporte acumulados en el efectivo (R1)
    banda_on = False
    lado = 0           # -1: SPY bajo peso; +1: SPY sobre peso
    pico = 0.0
    mdd = 0.0
    log = []
    sin_historial = 0
    for t in range(s, e + 1):
        decide = bool(primer[t]) and m0 <= mo[t] < m0 + ventana
        if decide and usar_banda:
            # Pesos al cierre de la sesion previa, antes de la accion de hoy.
            w = None
            if units.any():
                valor = units * C[t - 1]
                w = valor[iS] / valor.sum()
            if banda_on and w is not None and ((lado < 0 and w >= PESO_SPY_OBJETIVO) or
                                               (lado > 0 and w <= PESO_SPY_OBJETIVO)):
                banda_on = False
            if (not banda_on) and mes[t] == MES_BANDA and w is not None and not (BANDA_MIN <= w <= BANDA_MAX):
                banda_on = True
                lado = -1 if w < PESO_SPY_OBJETIVO else 1
        if t > s:
            units = units * fac
        if decide:
            pot += aporte
            meses_pot += 1
            comp = np.zeros(A)
            if regla in ("R0", "R4"):
                if banda_on:
                    comp[iS if lado < 0 else 1 - iS] = pot
                else:
                    comp = pesos * pot
                pot = 0.0
            elif regla == "R1":
                caida = senal.caida(orden[t])
                if caida is None:
                    sin_historial += 1
                if caida is None or caida or meses_pot >= MESES_SIN_CAIDA:
                    comp = pesos * pot
                    pot = 0.0
                    meses_pot = 0
            elif regla == "R2":
                sobre = senal.sobre_sma(orden[t])
                if sobre is None:
                    sin_historial += 1
                if sobre is None or sobre:
                    comp = pesos * pot
                    pot = 0.0
            elif regla == "R3":
                sobre = senal.sobre_sma(orden[t])
                if sobre is None:
                    sin_historial += 1
                if sobre is None or not sobre:
                    comp = pesos * pot
                    pot = 0.0
                else:
                    comp = pesos * (FRAC_R3 * aporte)
                    pot -= FRAC_R3 * aporte
            else:
                raise ValueError(f"regla desconocida: {regla}")
            for a in range(A):
                if comp[a] > 0:
                    units[a] += comp[a] / (C[t, a] * (1 + spread))
            log.append((int(t), [round(float(x), 6) for x in comp]))
        valor_cuenta = float(units @ C[t]) + pot
        pico = max(pico, valor_cuenta)
        if pico > 0:
            mdd = min(mdd, valor_cuenta / pico - 1)
    final = float(units @ C[e]) + pot
    return {"multiple": final / (ventana * aporte), "mdd": mdd, "log": log, "sin_historial": sin_historial}


def p_bootstrap(x: np.ndarray, rng: np.random.Generator, rondas: int) -> float:
    n = len(x)
    nb = -(-n // BLOQUE_VENTANAS)
    inicios = rng.integers(0, n, size=(rondas, nb))
    idx = (inicios[:, :, None] + np.arange(BLOQUE_VENTANAS)[None, None, :]) % n
    idx = idx.reshape(rondas, -1)[:, :n]
    medias = x[idx].mean(axis=1)
    return float((1 + np.count_nonzero(medias <= 0)) / (rondas + 1))


def bh(p) -> np.ndarray:
    p = np.asarray(p, float)
    m = len(p)
    orden = np.argsort(p)
    q = p[orden] * m / np.arange(1, m + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(m)
    out[orden] = np.minimum(q, 1.0)
    return out


def evaluar(nombre: str, tcfg: dict, precios: dict, senal_sym: str, reglas: list[str], usar_banda: bool,
            rng: np.random.Generator, rondas: int, P: dict) -> dict:
    cartera = tcfg["cartera"]
    activos = list(cartera)
    cal = calendario({a: precios[a] for a in activos}, tcfg["dividendo_anual"])
    senal = Senal(precios[senal_sym])
    pesos = np.array([cartera[a] for a in activos], float)
    ini, fin = pd.Timestamp(tcfg["inicios"][0]), pd.Timestamp(tcfg["inicios"][1])
    vs = ventanas(cal, ini, fin)
    if not vs:
        raise RuntimeError(f"{nombre}: sin ventanas completas")
    sims = {r: [simular(cal, senal, r, pesos, m0, s, e, P, usar_banda and r == "R0") for m0, s, e in vs]
            for r in reglas}
    base = np.array([x["multiple"] for x in sims["R0"]])
    reglas_out = {}
    for r in reglas:
        mult = np.array([x["multiple"] for x in sims[r]])
        mej = mult - base
        mdd = np.array([x["mdd"] for x in sims[r]])
        d = {
            "n_windows": len(vs),
            "mean_multiple": float(mult.mean()),
            "mean_mejora": float(mej.mean()),
            "p": None,
            "q_BH": None,
            "median_max_drawdown": float(np.median(mdd)),
            "decisiones_sin_historial": int(sum(x["sin_historial"] for x in sims[r])),
            "approved": None,
        }
        if r != "R0":
            d["p"] = p_bootstrap(mej, rng, rondas)
        reglas_out[r] = d
    if usar_banda:
        rs = [r for r in reglas if r != "R0"]
        for r, q in zip(rs, bh([reglas_out[r]["p"] for r in rs])):
            reglas_out[r]["q_BH"] = float(q)
    return {
        "n_windows": len(vs),
        "primer_inicio": str(cal.fechas[vs[0][1]].date()),
        "ultima_valoracion": str(cal.fechas[vs[-1][2]].date()),
        "rules": reglas_out,
    }


def calcular(prereg: dict, precios: dict, rondas: int | None = None, sha: str | None = None) -> dict:
    d = prereg["datos"]
    costos = prereg["costos_xtb"]
    est = prereg["estadistica"]
    if costos["comision"] != 0 or costos["conversion"] != 0 or costos["efectivo_en_espera_anual"] != 0:
        raise RuntimeError("el prereg cambio costos que este codigo no implementa")
    P = {"aporte": float(prereg["aporte_mensual_usd"]), "ventana": int(d["ventana_meses"]),
         "spread": float(costos["spread_por_compra"])}
    rondas = int(est["bootstrap_rondas"]) if rondas is None else rondas
    rng = np.random.default_rng(int(est["semilla"]))
    # Orden fijo de bootstrap: validacion R1-R3, luego prueba R1-R4.
    val = evaluar("validacion", d["tramo_validacion"], precios, "_GSPC", REGLAS_VALIDACION, False, rng, rondas, P)
    pru = evaluar("prueba", d["tramo_prueba"], precios, "SPY", REGLAS_PRUEBA, True, rng, rondas, P)
    for r in ["R1", "R2", "R3", "R4"]:
        dp = pru["rules"][r]
        cond_val = None if r == "R4" else bool(val["rules"][r]["mean_mejora"] > 0)
        dp["pasa_validacion"] = cond_val
        dp["approved"] = bool(dp["q_BH"] < ALFA and dp["mean_mejora"] > 0 and cond_val is not False)
    nivel = any(pru["rules"][r]["approved"] for r in ["R1", "R2", "R3", "R4"])
    return {
        "prereg_sha256": sha,
        "prereg_version": prereg["version"],
        "ejecutado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "parametros": {
            "aporte_mensual_usd": P["aporte"], "ventana_meses": P["ventana"], "spread_por_compra": P["spread"],
            "semilla": est["semilla"], "bootstrap_rondas": rondas, "bloque_ventanas": BLOQUE_VENTANAS,
            "dividendos_validacion": d["tramo_validacion"]["dividendo_anual"],
            "dividendos_prueba": d["tramo_prueba"]["dividendo_anual"],
            "pesos_prueba": d["tramo_prueba"]["cartera"], "inicios_validacion": d["tramo_validacion"]["inicios"],
            "inicios_prueba": d["tramo_prueba"]["inicios"], "corte_datos": str(CORTE_DATOS.date()),
        },
        "tramos": {"validacion": val, "prueba": pru},
        "level_approved": bool(nivel),
    }


def informe(res: dict) -> str:
    val = res["tramos"]["validacion"]
    pru = res["tramos"]["prueba"]

    def n(x, k=4):
        return "-" if x is None else f"{x:.{k}f}".replace(".", ",")

    def pct(x):
        return "-" if x is None else f"{100 * x:.1f} %".replace(".", ",")

    filas = []
    for nombre, tr in (("validación", val), ("prueba", pru)):
        for r, dd in tr["rules"].items():
            if r == "R0":
                continue
            apro = "-" if dd["approved"] is None else ("si" if dd["approved"] else "no")
            filas.append(f"| {nombre} | {r} | {n(dd['mean_multiple'], 3)} | {n(dd['mean_mejora'], 4)} | "
                         f"{n(dd['p'])} | {n(dd['q_BH'])} | {pct(dd['median_max_drawdown'])} | {apro} |")
    aprobadas = [r for r, dd in pru["rules"].items() if dd.get("approved")]
    if res["level_approved"]:
        veredicto = f"**Veredicto:** nivel 7 aprobado ({', '.join(aprobadas)}), con q BH < 0,05 y mejora media positiva en prueba y validación."
    else:
        veredicto = ("**Veredicto:** nivel 7 no aprobado: ninguna regla de prueba cumple q BH < 0,05 "
                     "con mejora media positiva en prueba y, cuando aplica, en validación.")
    lineas = [
        "# Oráculo nivel 7: reglas de aporte contra el plan 80/20",
        f"Pre-registro `lab/oraculo_n7_prereg.json`, sha256 `{res['prereg_sha256']}`, verificado al arrancar. Ejecutado {res['ejecutado_utc']} UTC.",
        f"Ventanas de 60 aportes de 100 USD: validación {val['n_windows']} (_GSPC), prueba {pru['n_windows']} (VT 80 / SPY 20). "
        f"Plan R0, múltiplo medio: validación {n(val['rules']['R0']['mean_multiple'], 3)}, prueba {n(pru['rules']['R0']['mean_multiple'], 3)}.",
        "",
        "| Tramo | Regla | Múltiplo medio | Mejora media vs R0 | p | q BH | Peor caída mediana | Aprobada |",
        "|---|---|---|---|---|---|---|---|",
        *filas,
        "",
        f"{veredicto} El plan 80/20 no cambia por este resultado; una regla aprobada solo entra a la bóveda y espera 90 días.",
    ]
    return "\n".join(lineas) + "\n"


def main() -> None:
    try:
        prereg, sha = verificar_prereg()
    except RuntimeError as err:
        print(err, file=sys.stderr)
        sys.exit(1)
    precios = {s: cargar(s) for s in ["_GSPC", "SPY", "VT"]}
    res = calcular(prereg, precios, sha=sha)
    SALIDA.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    INFORME.write_text(informe(res), encoding="utf-8")
    print(f"nivel_aprobado={res['level_approved']} escrito {SALIDA} y {INFORME}")


if __name__ == "__main__":
    main()
