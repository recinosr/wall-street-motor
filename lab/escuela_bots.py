"""Referencias mecánicas de la escuela; ninguna regla aprende de datos futuros."""
import json
import random
import statistics
from pathlib import Path

from .escuela import ArchivoMemoria, Sesion, RAIZ

BOTS = ("azar", "mantener", "caida_apertura", "momentum_intradia", "reversion_vwap")


def jugar(sesion, bot, semilla):
    rng = random.Random(semilla)
    while sesion.i < sesion.duracion:
        obs = sesion.observacion()
        if sesion.units:
            if bot == "azar" and rng.random() < 0.08:
                sesion.paso("cerrar", prob_sube=0.5, razon="salida aleatoria")
            else:
                sesion.paso("esperar")
            continue
        vela = obs["velas"][-1]
        precio = vela["close"]
        ctx = obs["contexto"]
        comprar = False
        if bot == "azar":
            comprar = rng.random() < 0.08
        elif bot == "mantener":
            comprar = sesion.i == 0
        elif bot == "caida_apertura":
            comprar = sesion.i <= 30 and ctx.get("desde_apertura_%", 0) < -0.5
        elif bot == "momentum_intradia":
            comprar = len(obs["velas"]) >= 6 and precio > obs["velas"][-6]["close"] * 1.002
        elif bot == "reversion_vwap":
            comprar = ctx.get("vs_vwap_%") is not None and ctx["vs_vwap_%"] < -0.3
        if comprar:
            sesion.paso("comprar", tamaño=0.5, prob_sube=0.5,
                         razon=f"regla fija: {bot}")
        else:
            sesion.paso("esperar")
    return sesion.terminar()


def semillas_validas(n, activo=None, duracion=60, base=None, intentos=25, archivo_cache=None,
                    particion="entrenamiento"):
    """Semillas que producen sesiones completas. Cambian cada dia (base = fecha) para no repetir simulacros;
    las sesiones con velas insuficientes (por ejemplo cerca del cierre) se reemplazan por otras."""
    import datetime as dt
    base = base if base is not None else int(dt.date.today().strftime("%Y%m%d")) * 1000
    out, k = [], 0
    while len(out) < n and k < n * intentos:
        s = base + k
        k += 1
        try:
            Sesion(s, activo=activo, duracion=duracion, archivo_cache=archivo_cache,
                   particion=particion,
                   guardar=False, resumido=True)
            out.append(s)
        except LookupError:
            continue
    if not out:
        raise LookupError("No se encontraron sesiones completas en el archivo de velas")
    return out


def correr(n, activo=None, duracion=60, base=None, particion="entrenamiento"):
    if n < 1:
        raise ValueError("N debe ser positivo")
    cortes = {"entrenamiento": ("2024-04", "2025-04"),
              "validacion": ("2025-04", "2026-01")}
    cache = ArchivoMemoria(*cortes.get(particion, (None, None)))
    semillas = semillas_validas(n, activo, duracion, base, archivo_cache=cache,
                               particion=particion)
    salida = {}
    dias_usados = set()
    for bot in BOTS:
        resultados = []
        for j, s in enumerate(semillas):  # todos los bots juegan exactamente las mismas sesiones
            ses = Sesion(s, activo=activo, duracion=duracion, archivo_cache=cache,
                         particion=particion,
                         resumido=True)
            ses.jugador = bot
            dias_usados.add(ses.velas.index[0].tz_convert("America/New_York").date().isoformat())
            resultados.append(jugar(ses, bot, s + 7))
        salida[bot] = {"sesiones": len(resultados),
                       "neto_medio": statistics.mean(x["neto"] for x in resultados),
                       "percentil_medio": statistics.mean(x["percentil_azar"] for x in resultados),
                       "peor_caida_media": statistics.mean(x["peor_caida"] for x in resultados),
                       "brier_medio": statistics.mean(x["brier"] for x in resultados if x["brier"] is not None)
                       if any(x["brier"] is not None for x in resultados) else None}
    ruta = RAIZ / "datos" / "escuela" / "bots_resumen.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    import datetime as dt
    with open(RAIZ / "datos" / "escuela" / "bots_historial.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"fecha": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                            "semillas": [semillas[0], semillas[-1]], "duracion": duracion,
                            "dias_distintos_usados": len(dias_usados),
                            "particiones_usadas": {particion: len(dias_usados)},
                            "bots": salida},
                           ensure_ascii=False) + chr(10))
    return salida
