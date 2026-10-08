"""Sesiones de Escuela persistidas entre invocaciones, sin guardar velas futuras."""
import argparse
import datetime as dt
import json
import os
import secrets
from pathlib import Path

from .escuela import RAIZ, Sesion
from .escuela import LISTA

ESTADO = RAIZ / "datos" / "escuela" / "sesion_activa.json"


def _guardar(estado):
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    temporal = ESTADO.with_suffix(".tmp")
    temporal.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporal, ESTADO)


def _cargar():
    if not ESTADO.exists():
        raise ValueError("No hay sesión activa; usa 'escuela nueva'")
    estado = json.loads(ESTADO.read_text(encoding="utf-8"))
    sesion = Sesion(estado["semilla"], activo=estado["activo"], inicio=estado["inicio"],
                    duracion=estado["duracion"], anonimo=estado["anonimo"],
                    particion=estado["particion"], guardar=True,
                    modo="cfd_x1")
    sesion.jugador = "agente"
    for paso in estado["pasos"]:
        sesion.paso(paso["accion"], **paso["argumentos"])
    return estado, sesion


def _mostrar(sesion):
    obs = sesion.observacion()
    print("Vela {vela}/{total} | restantes {restantes} | efectivo {efectivo:.2f} | "
          "posición {posicion:.2f} | equidad {equidad:.2f}".format(total=sesion.duracion, **obs))
    if not sesion.anonimo:
        print(obs["activo"], obs["instante"])
    print("Contexto:", json.dumps(obs["contexto"], ensure_ascii=False, default=str))
    print("Últimas velas cerradas (OHLCV):")
    print("#   apertura    máximo     mínimo     cierre     volumen")
    velas = obs["velas"][-60:]
    for i, b in enumerate(velas, start=len(obs["velas"]) - len(velas)):
        print(f"{i:>3} {b['open']:>10.4f} {b['high']:>10.4f} {b['low']:>10.4f} "
              f"{b['close']:>10.4f} {b['volume']:>11.0f}" +
              (f" {b['time']}" if "time" in b else ""))


def _precio_real(sesion, valor):
    if valor is None:
        return None
    base = float(sesion.velas.close.iloc[0])
    return float(valor) * base / 100 if sesion.anonimo else float(valor)


def ejecutar(args):
    p = argparse.ArgumentParser(prog="python lab.py escuela")
    sub = p.add_subparsers(dest="comando", required=True)
    nueva = sub.add_parser("nueva")
    nueva.add_argument("--anonimo", action="store_true")
    nueva.add_argument("--duracion", type=int, default=60)
    nueva.add_argument("--particion", choices=("practica", "entrenamiento", "validacion"), default="entrenamiento")
    sub.add_parser("ver")
    for nombre in ("comprar", "corto"):
        op = sub.add_parser(nombre)
        op.add_argument("tamano", type=float)
        op.add_argument("--stop", type=float, required=True)
        op.add_argument("--objetivo", type=float, required=True)
        op.add_argument("--prob", type=float, required=True)
        op.add_argument("--razon", required=True)
    avanzar = sub.add_parser("avanzar")
    avanzar.add_argument("k", type=int)
    cerrar = sub.add_parser("cerrar")
    cerrar.add_argument("--razon", required=True)
    cerrar.add_argument("--prob", type=float, default=0.5)
    sub.add_parser("terminar")
    a = p.parse_args(args)
    if a.comando == "nueva":
        if ESTADO.exists():
            raise ValueError("Ya hay una sesión activa; termínala antes de crear otra")
        if a.duracion < 2:
            raise ValueError("Duración mínima: 2 velas")
        semilla = secrets.randbits(48)
        # Algunos activos aún carecen de archivo 1m; probar los demás sin cambiar el corte.
        candidatos = list(LISTA)
        import random
        random.Random(semilla).shuffle(candidatos)
        sesion = None
        for activo in candidatos:
            try:
                sesion = Sesion(semilla, activo=activo, duracion=a.duracion,
                                anonimo=a.anonimo, particion=a.particion, modo="cfd_x1")
                break
            except LookupError:
                continue
        if sesion is None:
            raise LookupError("No hay velas archivadas suficientes en la partición solicitada")
        estado = {"version": 1, "semilla": semilla, "activo": sesion.activo,
                  "inicio": sesion.velas.index[0].isoformat(), "duracion": a.duracion,
                  "anonimo": a.anonimo, "particion": a.particion, "pasos": []}
        _guardar(estado)
        _mostrar(sesion)
        return
    estado, sesion = _cargar()
    if a.comando == "ver":
        _mostrar(sesion)
        return
    if a.comando == "terminar":
        resultado = sesion.terminar()
        ESTADO.unlink()
        print(json.dumps({"activo": sesion.activo, "inicio": estado["inicio"],
                          "resultado": resultado}, ensure_ascii=False, indent=2))
        return
    if a.comando == "avanzar":
        accion, kw = "esperar", {"k": a.k}
    elif a.comando == "cerrar":
        accion, kw = "cerrar", {"prob_sube": a.prob, "razon": a.razon}
    else:
        accion = "comprar" if a.comando == "comprar" else "vender_corto"
        kw = {"tamano": a.tamano, "stop": _precio_real(sesion, a.stop),
              "objetivo": _precio_real(sesion, a.objetivo),
              "prob_sube": a.prob, "razon": a.razon}
    sesion.paso(accion, **kw)
    estado["pasos"].append({"accion": accion, "argumentos": kw})
    _guardar(estado)
    _mostrar(sesion)
