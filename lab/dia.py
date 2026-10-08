"""Dia completo con muchos bots: cada bot recorre la sesion minuto a minuto y puede comprar y vender varias veces.

Uso:  python -m lab.dia BTC 2026-09-23 [--bots 1000] [--png salida.png]
Ventana: 09:30-16:00 Nueva York.
Sin mirar al futuro: la senal se calcula con el cierre de la vela t y la orden se ejecuta en la apertura de t+1.
Costo: 0.1 % por lado. Solo contado (comprar y vender)."""
import argparse
import json
import random
from functools import lru_cache
from pathlib import Path
import numpy as np
import pandas as pd

from . import archivo

NY = "America/New_York"
COSTO = 0.001
SPREAD = 0.0
COSTO_FIJO = 0.0
CAPITAL = 1000.0
INSTRUCCIONES = Path(__file__).resolve().parents[1] / "agente" / "instrucciones_bots.json"


@lru_cache(maxsize=1)
def configuracion():
    try:
        cfg = json.loads(INSTRUCCIONES.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict): return {}
        if not isinstance(cfg.get("rejillas", {}), dict): return {}
        if any(not isinstance(v, list) or not v for v in cfg.get("rejillas", {}).values()): return {}
        textos = {"salida": ("tiempo", "volatilidad"), "tendencia": ("cualquiera", "1h", "1d")}
        periodos = {"k": (5, 10, 15, 30), "w_reversion": (20, 60), "w_ruptura": (15, 30, 60)}
        for k, valores in cfg.get("rejillas", {}).items():
            if k in textos:
                if any(v not in textos[k] for v in valores): return {}
            elif any(not isinstance(v, (int, float)) or isinstance(v, bool) or not np.isfinite(v) or v < 0 for v in valores): return {}
            if k in periodos and any(v not in periodos[k] for v in valores): return {}
        if not isinstance(cfg.get("familias_activas", []), list) or any(not isinstance(f, str) for f in cfg.get("familias_activas", [])): return {}
        reglas = cfg.get("reglas_nuevas", [])
        if not isinstance(reglas, list): return {}
        for r in reglas:
            if not isinstance(r, dict) or not isinstance(r.get("nombre"), str) or r["nombre"] in FAMILIAS: return {}
            if not isinstance(r.get("condiciones", []), list) or any(not isinstance(c, dict) for c in r.get("condiciones", [])): return {}
            for c in r.get("condiciones", []):
                if not isinstance(c.get("rasgo"), str) or c.get("operador") not in (">", "<", "==") or not isinstance(c.get("valor"), (int, float, bool)) or not np.isfinite(c["valor"]): return {}
        for franjas in [cfg.get("franjas", [[60, 389]])] + [r.get("franjas", [[60, 389]]) for r in reglas]:
            if not isinstance(franjas, list) or any(not isinstance(f, list) or len(f) != 2 or
                not all(isinstance(v, int) for v in f) or not 0 <= f[0] <= f[1] <= 389 for f in franjas): return {}
        return cfg
    except (OSError, ValueError):
        return {}


def costo_variable():
    return COSTO + SPREAD / 2


def comprar(efectivo, precio):
    return max(0.0, efectivo * (1 - costo_variable()) - COSTO_FIJO / CAPITAL) / precio


def vender(unidades, precio):
    return max(0.0, unidades * precio * (1 - costo_variable()) - COSTO_FIJO / CAPITAL)


def cargar(sim, dia, ventana=("09:30", "15:59")):
    ini = pd.Timestamp(dia, tz=NY)
    df = archivo.leer(sim, (ini - pd.Timedelta(days=4)).tz_convert("UTC"), (ini + pd.Timedelta(days=1)).tz_convert("UTC")).tz_convert(NY)
    anteriores = df[df.index < ini].between_time(*ventana)
    hoy = df[(df.index >= ini) & (df.index < ini + pd.Timedelta(days=1))].between_time(*ventana).copy()
    if len(anteriores):
        hoy.attrs["cierre_previo"] = float(anteriores["close"].iat[-1])
        hoy.attrs["media_dia"] = float(anteriores["close"].tail(390).mean())
    return hoy


def rasgos(df):
    c = df["close"].astype(float)
    r = {}
    for k in (5, 10, 15, 30):
        previo = c.reindex(c.index - pd.Timedelta(minutes=k)).to_numpy()
        r[f"ret{k}"] = c / previo - 1
    for w in (20, 60):
        m, s = c.rolling(f"{w}min", min_periods=w).mean(), c.rolling(f"{w}min", min_periods=w).std()
        r[f"z{w}"] = (c - m) / s
    for w in (15, 30, 60):
        r[f"max{w}"] = c >= c.rolling(f"{w}min", min_periods=w).max().shift(1)
        r[f"min{w}"] = c <= c.rolling(f"{w}min", min_periods=w).min().shift(1)
    previo = df.attrs.get("cierre_previo", float(df["open"].iat[0]))
    media_dia = df.attrs.get("media_dia", previo)
    rango = (df["high"].astype(float) / df["low"].astype(float) - 1).rolling("60min", min_periods=60).mean()
    r["tendencia_1h"] = c / c.rolling("60min", min_periods=60).mean() - 1
    r["tendencia_1d"] = c / media_dia - 1
    r["volatilidad_60"] = rango
    r["volatilidad_relativa"] = rango / rango.expanding(min_periods=60).median()
    r["gap"] = float(df["open"].iat[0]) / previo - 1
    r["hora"] = (df.index.hour * 60 + df.index.minute - 570) / 389.0
    return pd.DataFrame(r, index=df.index)


FAMILIAS = ("azar", "momentum", "reversion", "ruptura", "reversion_tendencia", "horario")


def crear_bots(n, semilla=1):
    rng = random.Random(semilla)
    cfg = configuracion()
    nuevas = {r.get("nombre") for r in cfg.get("reglas_nuevas", []) if isinstance(r, dict)}
    familias = [f for f in cfg.get("familias_activas", FAMILIAS) if f in FAMILIAS or f in nuevas]
    if not familias:
        familias = list(FAMILIAS)
    rejilla = cfg.get("rejillas", {})
    def elegir(k, pred):
        opciones = rejilla.get(k, pred)
        return rng.choice(opciones if opciones else pred)
    bots = []
    for i in range(n):
        f = rng.choice(familias)
        b = {"id": i, "familia": f, "mantener": elegir("mantener", [5, 10, 15, 30, 60]),
             "stop": elegir("stop", [0.001, 0.002, 0.003, 0.005]), "objetivo": elegir("objetivo", [0.002, 0.003, 0.005, 0.008]),
             "salida": elegir("salida", ["tiempo", "volatilidad"]), "multiplo_vol": elegir("multiplo_vol", [2, 3, 4]),
             "min_vol_rel": elegir("min_vol_rel", [0, 0.75, 1]), "tendencia": elegir("tendencia", ["cualquiera", "1h", "1d"]),
             "gap_max": elegir("gap_max", [0.02, 0.05])}
        if f == "azar":
            b["p"] = elegir("p", [0.005, 0.01, 0.02, 0.05])
        elif f == "momentum":
            b["k"] = elegir("k", [5, 10, 15, 30]); b["umbral"] = elegir("umbral", [0.0005, 0.001, 0.002])
        elif f in ("reversion", "reversion_tendencia"):
            b["w"] = elegir("w_reversion", [20, 60]); b["z"] = elegir("z", [1.5, 2.0, 2.5])
            if f == "reversion_tendencia": b["tendencia"] = "1d"
        elif f == "horario":
            b["inicio"] = elegir("inicio", [60, 120, 180]); b["fin"] = elegir("fin", [240, 300, 360])
            b["w"] = elegir("w_reversion", [20, 60]); b["z"] = elegir("z", [1.5, 2.0, 2.5])
        elif f == "ruptura":
            b["w"] = elegir("w_ruptura", [15, 30, 60])
        bots.append(b)
    return bots


def senal(b, X, t, rng):
    if b["familia"] == "no_operar": return False
    if b["familia"] == "agente_contexto":
        return bool(X["prob_modelo"].iat[t] >= b.get("prob_min", 0.65))
    minuto = round(float(X["hora"].iat[t] * 389))
    regla = next((r for r in configuracion().get("reglas_nuevas", []) if r.get("nombre") == b["familia"]), None)
    if regla:
        if not any(a <= minuto <= z for a, z in regla.get("franjas", [[60, 389]])): return False
        for cond in regla.get("condiciones", []):
            rasgo = cond.get("rasgo")
            if rasgo not in X: return False
            valor = X[rasgo].iat[t]
            op, umbral = cond.get("operador"), cond.get("valor")
            if op == ">" and not valor > umbral: return False
            if op == "<" and not valor < umbral: return False
            if op == "==" and not valor == umbral: return False
            if op not in (">", "<", "=="): return False
        return bool(regla.get("condiciones"))
    cfg = configuracion()
    franjas = cfg.get("franjas", [[60, 389]])
    if not any(a <= minuto <= z for a, z in franjas): return False
    if b.get("tendencia") in ("1h", "1d") and not X[f"tendencia_{b['tendencia']}"].iat[t] > 0: return False
    if b.get("filtrar_vol_rel", True) and not X["volatilidad_relativa"].iat[t] >= b.get("min_vol_rel", 0): return False
    if abs(X["gap"].iat[t]) > b.get("gap_max", 1): return False
    if b["familia"] == "horario" and not b["inicio"] <= minuto <= b["fin"]: return False
    if b["familia"] == "azar":
        return rng.random() < b["p"]
    if b["familia"] == "momentum":
        v = X[f"ret{b['k']}"].iat[t]
        return bool(v == v and v > b["umbral"])
    if b["familia"] in ("reversion", "reversion_tendencia", "horario"):
        v = X[f"z{b['w']}"].iat[t]
        return bool(v == v and v < -b["z"])
    return bool(X[f"max{b['w']}"].iat[t])


def senales_bot(b, X):
    """Calcula señales deterministas en bloque; cada fila de X solo usa historia hasta esa fila."""
    f = b["familia"]
    n = len(X)
    t = np.rint(X["hora"].to_numpy() * 389)
    if f == "no_operar": return np.zeros(n, dtype=bool)
    if f == "agente_contexto": return X["prob_modelo"].to_numpy() >= b.get("prob_min", .65)
    cfg = configuracion()
    regla = next((r for r in cfg.get("reglas_nuevas", []) if r.get("nombre") == f), None)
    if regla:
        out = np.zeros(n, dtype=bool)
        for a, z in regla.get("franjas", [[60, 389]]): out |= (t >= a) & (t <= z)
        condiciones = regla.get("condiciones", [])
        if not condiciones: return np.zeros(n, dtype=bool)
        for cond in condiciones:
            if cond.get("rasgo") not in X: return np.zeros(n, dtype=bool)
            v, op, umbral = X[cond["rasgo"]].to_numpy(), cond.get("operador"), cond.get("valor")
            if op == ">": out &= v > umbral
            elif op == "<": out &= v < umbral
            elif op == "==": out &= v == umbral
            else: return np.zeros(n, dtype=bool)
        return out
    out = np.zeros(n, dtype=bool)
    for a, z in cfg.get("franjas", [[60, 389]]): out |= (t >= a) & (t <= z)
    if b.get("tendencia") in ("1h", "1d"):
        out &= X[f"tendencia_{b['tendencia']}"].to_numpy() > 0
    if b.get("filtrar_vol_rel", True):
        out &= X["volatilidad_relativa"].to_numpy() >= b.get("min_vol_rel", 0)
    out &= np.abs(X["gap"].to_numpy()) <= b.get("gap_max", 1)
    if f == "azar": return out
    if f == "momentum": base = X[f"ret{b['k']}"].to_numpy() > b["umbral"]
    elif f in ("reversion", "reversion_tendencia", "horario"):
        base = X[f"z{b['w']}"].to_numpy() < -b["z"]
        if f == "horario": out &= (t >= b["inicio"]) & (t <= b["fin"])
    else: base = X[f"max{b['w']}"].to_numpy(dtype=bool)
    return out & base


def correr_bot(b, df, X, semilla=0, registro=None):
    rng = random.Random(semilla * 100003 + b["id"])
    senales = senales_bot(b, X)
    o, c = df["open"].astype(float).to_numpy(), df["close"].astype(float).to_numpy()
    volatilidades = X["volatilidad_60"].to_numpy() if "volatilidad_60" in X else np.zeros(len(df))
    minutos = (df.index - df.index[0]).total_seconds().to_numpy() / 60
    n = len(df)
    efectivo, unidades, ent, t_ent = 1.0, 0.0, 0.0, -1
    ops = []
    maximo = 0.0
    def registrar(tipo, observado, ejecutado, precio, motivos):
        if registro is None: return
        rasgos = {k: float(X[k].iat[observado]) for k in X.columns
                  if np.isfinite(X[k].iat[observado])}
        registro.append({"tipo": tipo, "index": int(ejecutado), "senal_index": int(observado),
                         "precio": float(precio), "precio_observado": float(c[observado]),
                         "motivos": motivos, "rasgos": rasgos})
    for t in range(60, n - 1):
        if unidades == 0.0:
            entrar = (bool(senales[t]) and (b["familia"] != "azar" or rng.random() < b["p"])) if senales is not None else senal(b, X, t, rng)
            if entrar:
                px = o[t + 1]
                unidades = comprar(efectivo, px)
                efectivo, ent, t_ent = 0.0, px, t + 1
                maximo = px
                registrar("compra", t, t + 1, px, ["Se cumplió la regla de entrada: " + describir(b)])
        else:
            ret = c[t] / ent - 1
            maximo = max(maximo, c[t])
            volatilidad = volatilidades[t]
            trailing = b.get("salida") == "volatilidad" and np.isfinite(volatilidad) and c[t] < maximo * (1 - b.get("multiplo_vol", 3) * volatilidad)
            tiempo = (minutos[t] - minutos[t_ent] + 1) >= b["mantener"]
            salir = tiempo if b.get("salida") == "tiempo" else trailing or tiempo
            if ret <= -b["stop"] or ret >= b["objetivo"] or salir:
                px = o[t + 1]
                efectivo = vender(unidades, px)
                ops.append((t_ent, t + 1, ent, px, efectivo - 0.0))
                motivos = []
                if ret <= -b["stop"]: motivos.append("Stop de pérdida")
                if ret >= b["objetivo"]: motivos.append("Objetivo de ganancia")
                if tiempo: motivos.append("Tiempo máximo de posición")
                if b.get("salida") != "tiempo" and trailing: motivos.append("Stop móvil por volatilidad")
                registrar("venta", t, t + 1, px, motivos)
                unidades = 0.0
    if unidades > 0:  # cierre forzado al final de la sesion
        px = c[-1]
        efectivo = vender(unidades, px)
        ops.append((t_ent, n - 1, ent, px, efectivo))
        registrar("venta", n - 1, n - 1, px, ["Cierre forzado al terminar la sesión"])
    return efectivo - 1, ops


def mejor_posible(df):
    """Referencia a toro pasado: programacion dinamica exacta (compras y ventas perfectas, cualquier cantidad,
    con costo por lado). No es operable; sirve para saber cuanto habia en la mesa."""
    c = np.column_stack((df["open"].astype(float), df["close"].astype(float))).ravel()
    efectivo, tengo = 1.0, -1e9
    for px in c:
        anterior = efectivo
        efectivo = max(efectivo, vender(tengo, px))
        tengo = max(tengo, comprar(anterior, px))
    return efectivo - 1


def resumen_dia(sim, dia, n=1000, semilla=1):
    df = cargar(sim, dia)
    if len(df) < 200:
        return None
    X = rasgos(df)
    bots = crear_bots(n, semilla)
    res = []
    for b in bots:
        r, ops = correr_bot(b, df, X, semilla)
        res.append({**b, "ret": r, "ops": ops})
    mantener = vender(comprar(1.0, float(df["open"].iat[0])), float(df["close"].iat[-1])) - 1
    return df, res, mantener


def texto(sim, dia, df, res, mantener):
    r = np.array([x["ret"] for x in res])
    out = [f"{sim} {dia}  {df.index[0].strftime('%H:%M')}-{df.index[-1].strftime('%H:%M')} NY  "
           f"abre {df['open'].iat[0]:,.2f} cierra {df['close'].iat[-1]:,.2f}  rango del dia {(df['high'].max() / df['low'].min() - 1) * 100:.2f}%",
           f"Comprar y mantener todo el dia: {mantener * 100:+.2f}%   |   mejor posible a toro pasado: {mejor_posible(df) * 100:+.2f}%",
           f"{len(res)} bots: ganan {np.mean(r > 0) * 100:.0f}% | mediana {np.median(r) * 100:+.2f}% | mejor {r.max() * 100:+.2f}% | peor {r.min() * 100:+.2f}% | "
           f"operaciones por bot (mediana) {np.median([len(x['ops']) for x in res]):.0f}"]
    for f in FAMILIAS:
        s = [x for x in res if x["familia"] == f]
        v = np.array([x["ret"] for x in s])
        out.append(f"  {f:10s} n={len(s):3d}  media {v.mean() * 100:+.3f}%  gana {np.mean(v > 0) * 100:3.0f}%  mejor {v.max() * 100:+.2f}%  peor {v.min() * 100:+.2f}%")
    return "\n".join(out)


def describir(b):
    if b["familia"] == "no_operar": return "No opera: efectivo durante toda la sesión"
    if b["familia"] == "agente_contexto": return f"Regresión logística de contexto, probabilidad ≥{b.get('prob_min', 0.65):.0%}; sale a {b['mantener']} min"
    regla = next((r for r in configuracion().get("reglas_nuevas", []) if r.get("nombre") == b["familia"]), None)
    if regla: return f"{regla.get('descripcion', b['familia'])}; sale a {b['mantener']} min"
    base = {"azar": "entra al azar (prob. %s por minuto)" % b.get("p"),
            "momentum": "compra si subió más de %.2f%% en %s min" % (b.get("umbral", 0) * 100, b.get("k")),
            "reversion": "compra si cae %s desviaciones bajo su media de %s min" % (b.get("z"), b.get("w")),
            "reversion_tendencia": "compra caída de %s desviaciones sobre tendencia diaria" % b.get("z"),
            "horario": "compra caída solo entre minutos %s y %s" % (b.get("inicio"), b.get("fin")),
            "ruptura": "compra si rompe el máximo de %s min" % b.get("w")}[b["familia"]]
    return f"{base}; salida {b.get('salida', 'tiempo')} hasta {b['mantener']} min, stop -{b['stop'] * 100:.1f}% u objetivo +{b['objetivo'] * 100:.1f}%"


def grafica(sim, dia, df, res, ruta):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    mejor = max(res, key=lambda x: x["ret"]); peor = min(res, key=lambda x: x["ret"])
    fig, ax = plt.subplots(3, 1, figsize=(11, 10), dpi=100, gridspec_kw={"height_ratios": [2.2, 2.2, 1.2]})
    for a, bot, titulo in ((ax[0], mejor, "MEJOR bot"), (ax[1], peor, "PEOR bot")):
        a.plot(df.index, df["close"], color="#555", linewidth=0.9)
        for (ti, tf, pi, pf, _) in bot["ops"]:
            ok = pf > pi
            a.axvspan(df.index[ti], df.index[min(tf, len(df) - 1)], color="#0a7d32" if ok else "#b3261e", alpha=0.18)
            a.scatter(df.index[ti], pi, marker="^", color="#0a7d32", s=40, zorder=3)
            a.scatter(df.index[min(tf, len(df) - 1)], pf, marker="v", color="#b3261e", s=40, zorder=3)
        a.set_title(f"{titulo}: {bot['ret'] * 100:+.2f}% con {len(bot['ops'])} operaciones | {describir(bot)}", fontsize=9)
        a.grid(alpha=0.25)
    ax[2].hist([x["ret"] * 100 for x in res], bins=40, color="#1a56db")
    ax[2].axvline(0, color="k", linewidth=0.8)
    ax[2].set_title("Resultado de los %d bots (%% del dia)" % len(res), fontsize=9)
    ax[2].grid(alpha=0.25)
    fig.suptitle(f"{sim} {dia} (verde = compra y venta con ganancia, rojo = con pérdida)", fontsize=11)
    fig.tight_layout()
    fig.savefig(ruta)
    plt.close(fig)


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("sim"); a.add_argument("dia"); a.add_argument("--bots", type=int, default=1000); a.add_argument("--png")
    x = a.parse_args()
    r = resumen_dia(x.sim.upper(), x.dia, x.bots)
    if r is None:
        raise SystemExit("Sin velas suficientes")
    df, res, mant = r
    print(texto(x.sim.upper(), x.dia, df, res, mant))
    if x.png:
        grafica(x.sim.upper(), x.dia, df, res, x.png)
        print("grafica:", x.png)
