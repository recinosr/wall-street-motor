"""Entorno de práctica con velas históricas, sin acceso al futuro en la observación."""
import datetime as dt
import json
import random
import subprocess
from pathlib import Path

import pandas as pd
import numpy as np

from . import archivo

LISTA = ("BTC", "ETH")
NY = "America/New_York"


def contexto_previo(activo, historia):
    """Contexto calculado solo con velas previas del archivo Coinbase."""
    return {"cierre_previo": float(historia.close.iloc[-1])} if not historia.empty else {}

RAIZ = Path(__file__).resolve().parents[1]
REGISTRO = RAIZ / "datos" / "escuela" / "sesiones.jsonl"
PRECIO_INICIAL = 100.0
PARTICIONES = {
    "entrenamiento": (None, "2025-04-01"),
    "validacion": ("2025-04-01", "2026-01-01"),
    "prueba": ("2026-01-01", None),
}


def dias_particion(dias, particion):
    """Cortes fijos; no cambian cuando se agregan velas al archivo."""
    if particion == "practica":
        return list(dias)
    desde, hasta = PARTICIONES[particion]
    return [dia for dia in dias if (desde is None or dia >= desde)
            and (hasta is None or dia < hasta)]


def _dias_disponibles(activo):
    rutas = set()
    for ref in ("datos", "origin/datos"):
        p = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref,
                            f"velas/1m/{activo}"], cwd=RAIZ, capture_output=True, text=True)
        if p.returncode == 0:
            rutas.update(p.stdout.splitlines())
    for ruta in (RAIZ / "velas" / "1m" / activo).glob("*.csv.gz"):
        rutas.add(f"velas/1m/{activo}/{ruta.name}")
    dias = set()
    for ruta in rutas:
        mes = Path(ruta).name[:7]
        try:
            df = archivo.leer(activo, mes + "-01", str(pd.Period(mes).end_time.date() + dt.timedelta(days=1)))
            dias.update(df.index.tz_convert(NY).strftime("%Y-%m-%d"))
        except (LookupError, ValueError):
            pass
    return sorted(dias)


class ArchivoMemoria:
    """Carga una vez los meses de cada activo y reutiliza las velas en la corrida."""
    def __init__(self, meses_desde=None, meses_hasta=None):
        self.frames = {}
        self.dias = {}
        self.meses_desde, self.meses_hasta = meses_desde, meses_hasta

    def _cargar(self, activo):
        if activo in self.dias:
            return
        meses = set()
        for ref in ("datos", "origin/datos"):
            p = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref,
                                f"velas/1m/{activo}"], cwd=RAIZ, capture_output=True, text=True)
            if p.returncode == 0:
                meses.update(Path(r).name[:7] for r in p.stdout.splitlines() if r.endswith(".csv.gz"))
        meses.update(p.name[:7] for p in (RAIZ / "velas" / "1m" / activo).glob("*.csv.gz"))
        partes = []
        for mes in sorted(m for m in meses if (self.meses_desde is None or m >= self.meses_desde)
                          and (self.meses_hasta is None or m < self.meses_hasta)):
            try:
                partes.append(archivo.leer(activo, mes + "-01", str(pd.Period(mes).end_time.date() + dt.timedelta(days=1))))
            except (LookupError, ValueError):
                continue
        frame = pd.concat(partes).sort_index() if partes else pd.DataFrame()
        self.frames[activo] = frame
        self.dias[activo] = sorted(set(frame.index.tz_convert(NY).strftime("%Y-%m-%d"))) if not frame.empty else []

    def dias_disponibles(self, activo):
        self._cargar(activo)
        return self.dias[activo]

    def leer(self, activo, desde, hasta):
        self._cargar(activo)
        a, b = pd.Timestamp(desde), pd.Timestamp(hasta)
        a = a.tz_localize("UTC") if a.tzinfo is None else a.tz_convert("UTC")
        b = b.tz_localize("UTC") if b.tzinfo is None else b.tz_convert("UTC")
        frame = self.frames[activo]
        if frame.empty:
            raise LookupError(f"Sin velas archivadas para {activo}")
        out = frame[(frame.index >= a) & (frame.index < b)]
        if out.empty:
            raise LookupError(f"Sin velas archivadas para {activo} entre {a} y {b}")
        return out


class Sesion:
    def __init__(self, semilla, modo="contado", activo=None, inicio=None, duracion=60,
                 intervalo="1m", anonimo=True, costo=0.001, guardar=True, velas=None,
                 particion="practica", evaluacion_programada=False, archivo_cache=None,
                 resumido=False):
        if intervalo != "1m":
            raise ValueError("La escuela usa velas archivadas de 1 minuto")
        if modo not in ("contado", "cfd_x1", "apalancado"):
            raise ValueError("Modo desconocido")
        if not 0 <= costo < 1:
            raise ValueError("Costo inválido")
        self.rng = random.Random(semilla)
        self.semilla, self.modo, self.anonimo, self.costo = semilla, modo, anonimo, costo
        self.activo = activo or self.rng.choice(LISTA)
        self.duracion = int(duracion)
        if self.duracion < 2:
            raise ValueError("Duración mínima: 2 velas")
        self.guardar = guardar
        self.resumido = resumido
        if particion not in ("practica", "entrenamiento", "validacion", "prueba"):
            raise ValueError("Partición desconocida")
        if particion == "prueba" and not evaluacion_programada:
            raise PermissionError("La prueba sellada solo se usa en evaluación programada")
        self.particion = particion
        if velas is None:
            dias = archivo_cache.dias_disponibles(self.activo) if archivo_cache else _dias_disponibles(self.activo)
            if not dias:
                raise LookupError(f"No hay velas archivadas para {self.activo}")
            dias = dias_particion(dias, particion)
            if inicio is None:
                if not dias:
                    raise LookupError(f"No hay velas en la partición {particion} para {self.activo}")
                dia = self.rng.choice(dias)
                df = (archivo_cache.leer if archivo_cache else archivo.leer)(self.activo, dia, str(pd.Timestamp(dia) + pd.Timedelta(days=2)))
                df = df[df.index.tz_convert(NY).strftime("%Y-%m-%d") == dia]
                if len(df) <= self.duracion:
                    raise LookupError("Día archivado demasiado corto")
                inicio = df.index[self.rng.randrange(0, len(df) - self.duracion)]
            elif particion != "practica" and (pd.Timestamp(inicio).tz_localize(NY)
                  if pd.Timestamp(inicio).tzinfo is None else pd.Timestamp(inicio).tz_convert(NY)).strftime("%Y-%m-%d") not in dias:
                raise ValueError("La fecha no corresponde a la partición elegida")
            t = pd.Timestamp(inicio)
            if t.tzinfo is None:
                t = t.tz_localize(NY)
            t = t.tz_convert("UTC")
            df = (archivo_cache.leer if archivo_cache else archivo.leer)(self.activo, t - pd.Timedelta(days=1),
                              t + pd.Timedelta(minutes=self.duracion + 1))
            self.historia = df[df.index < t].tail(390).copy()
            velas = df[df.index >= t].head(self.duracion + 1).copy()
        else:
            velas = velas.copy()
            if velas.index.tz is None:
                raise ValueError("Las velas deben tener zona horaria")
        if not hasattr(self, 'historia'):
            self.historia = velas.iloc[:0].copy()
        if len(velas) < self.duracion + 1:
            raise LookupError("Faltan velas para completar la sesión")
        self.velas = velas.iloc[:self.duracion + 1].copy()
        if self.resumido:
            self._bot_closes = np.concatenate((self.historia.close.to_numpy(dtype=float), self.velas.close.to_numpy(dtype=float)))
            self._bot_historia = len(self.historia)
            self._closes = self.velas.close.to_numpy(dtype=float)
            self._highs = self.velas.high.to_numpy(dtype=float)
            self._lows = self.velas.low.to_numpy(dtype=float)
            self._volumes = self.velas.volume.to_numpy(dtype=float)
            self._apertura = float(self.velas.open.iloc[0])
        self._base_ctx = {}
        if not self.historia.empty and not self.resumido:
            self._base_ctx = contexto_previo(self.activo, self.historia)
        self.i = 0
        self.cash = 10000.0
        self.units = 0.0
        self.stop = self.objetivo = None
        self.registros = []
        self.operaciones = []
        self.curva = [10000.0]
        self.terminada = False
        self._registrar("inicio", {})

    def _precio(self):
        return float(self._closes[self.i]) if self.resumido else float(self.velas.iloc[self.i]["close"])

    def _equidad(self):
        return self.cash + self.units * self._precio()

    def _contexto(self):
        visibles = self.velas.iloc[:self.i + 1]
        px = self._precio()
        apertura = float(visibles.open.iloc[0])
        alto, bajo = float(visibles.high.max()), float(visibles.low.min())
        volumen = visibles.volume.sum()
        vwap = float((visibles.close * visibles.volume).sum() / volumen) if volumen else None
        ctx = dict(self._base_ctx)
        ctx.update({"precio": px, "apertura": apertura,
                    "desde_apertura_%": round((px / apertura - 1) * 100, 2),
                    "max_hoy": alto, "min_hoy": bajo,
                    "pos_en_rango_hoy": round((px - bajo) / max(alto - bajo, 1e-9), 2),
                    "vs_vwap_%": round((px / vwap - 1) * 100, 2) if vwap else None,
                    "ultimos_30m_%": round((px / float(visibles.close.iloc[max(0, len(visibles) - 31)]) - 1) * 100, 2)})
        if "cierre_previo" in ctx:
            ctx["cambio_hoy_%"] = round((px / ctx["cierre_previo"] - 1) * 100, 2)
        if self.anonimo:
            ctx.pop("sim", None)
            ctx.pop("instante_NY", None)
            if "patrones_recientes" in ctx:
                ctx["patrones_recientes"] = [{"tipo": p["tipo"], "direccion": p["direccion"]}
                                            for p in ctx["patrones_recientes"]]
            base = float(self.velas.close.iloc[0])
            for clave in ("precio", "cierre_previo", "apertura", "max_hoy", "min_hoy"):
                if isinstance(ctx.get(clave), (int, float)):
                    ctx[clave] = round(ctx[clave] / base * 100, 4)
        return ctx

    def observacion(self):
        if self.resumido:
            # Los bots solo consumen los últimos seis cierres y estas dos señales.
            # El corte de la matriz impide entregarles velas futuras.
            px = self._precio()
            vistos = self._bot_closes[max(0, self._bot_historia + self.i - 5):self._bot_historia + self.i + 1]
            base = self._closes[0]
            volumen = self._volumes[:self.i + 1]
            total = float(np.sum(volumen))
            vwap = float(np.sum(self._closes[:self.i + 1] * volumen) / total) if total else None
            return {"velas": [{"close": round(float(c) / base * 100, 5) if self.anonimo else float(c)} for c in vistos],
                    "contexto": {"desde_apertura_%": round((px / self._apertura - 1) * 100, 2),
                                 "vs_vwap_%": round((px / vwap - 1) * 100, 2) if vwap else None}}
        visibles = pd.concat([self.historia, self.velas.iloc[:self.i + 1]]).tail(120)
        base = float(self.velas.close.iloc[0])
        barras = []
        for t, row in visibles.iterrows():
            barra = {k: round(float(row[k]) / base * 100, 5) if self.anonimo and k != "volume"
                     else float(row[k]) for k in ("open", "high", "low", "close", "volume")}
            if not self.anonimo:
                barra["time"] = t.isoformat()
            barras.append(barra)
        t = (self.velas.index[self.i] + pd.Timedelta(minutes=1)).tz_convert(NY)
        obs = {"vela": self.i, "restantes": self.duracion - self.i,
               "dia_semana": t.weekday(), "minutos_desde_apertura": t.hour * 60 + t.minute - 570,
               "velas": barras, "contexto": self._contexto(),
               "efectivo": round(self.cash, 2), "posicion": round(self.units * self._precio(), 2),
               "equidad": round(self._equidad(), 2)}
        if not self.anonimo:
            obs.update({"activo": self.activo, "instante": t.isoformat()})
        return obs

    def _registrar(self, accion, argumentos):
        if not self.resumido:
            self.registros.append({"observacion": self.observacion(), "accion": accion,
                                   "argumentos": argumentos})

    def _operar(self, delta, prob_sube, razon, stop=None, objetivo=None):
        if not isinstance(razon, str) or not razon.strip() or len(razon) > 280:
            raise ValueError("Cada operación exige una razón breve")
        if prob_sube is None or not 0 <= float(prob_sube) <= 1:
            raise ValueError("Cada operación exige prob_sube entre 0 y 1")
        px = self._precio()
        fraccion = abs(delta) * px / self._equidad()
        fee = abs(delta) * px * self.costo
        self.cash -= delta * px + fee
        self.units += delta
        self.stop, self.objetivo = stop, objetivo
        visibles = self.velas.close.iloc[:self.i + 1]
        base = float((visibles.diff().dropna() > 0).mean()) if len(visibles) > 2 else 0.5
        self.operaciones.append({"i": self.i, "lado": "compra" if delta > 0 else "venta",
                                 "precio": px, "unidades": abs(delta), "costo": fee,
                                 "fraccion": fraccion,
                                 "prob_sube": float(prob_sube), "tasa_base": base,
                                 "razon": razon.strip(), "mfe": 0.0, "mae": 0.0})

    def _cerrar_automatico(self, razon):
        delta = -self.units
        px = self._precio()
        fee = abs(delta) * px * self.costo
        self.cash -= delta * px + fee
        self.units = 0
        self.stop = self.objetivo = None
        self.operaciones.append({"i": self.i, "lado": "compra" if delta > 0 else "venta",
                                 "precio": px, "unidades": abs(delta), "costo": fee,
                                 "razon": razon, "automatica": True, "mfe": 0.0, "mae": 0.0})

    def paso(self, accion, **kw):
        if self.terminada:
            raise RuntimeError("Sesión terminada")
        if isinstance(accion, dict):
            kw = {**accion, **kw}
            accion = kw.pop("tipo")
        previa = None if self.resumido else self.observacion()
        previo = self._equidad()
        if accion == "esperar":
            k = int(kw.get("k", 1))
            if k < 1:
                raise ValueError("k debe ser positivo")
        elif accion in ("comprar", "vender_corto"):
            if self.units:
                raise ValueError("Cierra antes de abrir otra posición")
            if accion == "vender_corto" and self.modo == "contado":
                raise ValueError("El modo contado no admite cortos")
            tam = float(kw.get("tamaño", kw.get("tamano", 0)))
            if not 0 < tam <= (10 if self.modo == "apalancado" else 1):
                raise ValueError("Tamaño fuera del límite del modo")
            delta = self._equidad() * tam / self._precio() * (1 if accion == "comprar" else -1)
            if self.modo == "contado":
                delta = min(self._equidad() * tam, self.cash) / (self._precio() * (1 + self.costo))
            self._operar(delta, kw.get("prob_sube"), kw.get("razon"), kw.get("stop"), kw.get("objetivo"))
            k = 1
        elif accion == "cerrar":
            if not self.units:
                raise ValueError("No hay posición abierta")
            self._operar(-self.units, kw.get("prob_sube"), kw.get("razon"))
            k = 1
        else:
            raise ValueError("Acción desconocida")
        if not self.resumido:
            self.registros.append({"observacion": previa, "accion": accion, "argumentos": kw})
        for _ in range(min(k, self.duracion - self.i)):
            self.i += 1
            if self.units:
                px = self._precio()
                entrada = next((o["precio"] for o in reversed(self.operaciones) if o["lado"] == ("compra" if self.units > 0 else "venta")), px)
                alto = self._highs[self.i] if self.resumido else float(self.velas.iloc[self.i].high)
                bajo = self._lows[self.i] if self.resumido else float(self.velas.iloc[self.i].low)
                mejor = (alto / entrada - 1) if self.units > 0 else (1 - bajo / entrada)
                peor = (bajo / entrada - 1) if self.units > 0 else (1 - alto / entrada)
                o = self.operaciones[-1]
                o["mfe"] = max(o["mfe"], mejor)
                o["mae"] = min(o["mae"], peor)
                if ((self.stop is not None and ((self.units > 0 and px <= self.stop) or (self.units < 0 and px >= self.stop)))
                    or (self.objetivo is not None and ((self.units > 0 and px >= self.objetivo) or (self.units < 0 and px <= self.objetivo)))):
                    self._cerrar_automatico("stop u objetivo")
            self.curva.append(self._equidad())
        return (None if self.resumido else self.observacion()), round(self._equidad() - previo, 2)

    def terminar(self):
        if self.terminada:
            raise RuntimeError("Sesión ya terminada")
        while self.i < self.duracion:
            self.paso("esperar", k=self.duracion - self.i)
        if self.units:
            self._cerrar_automatico("fin de sesión")
            self.curva[-1] = self.cash
        self.terminada = True
        precios = self.velas.close.astype(float).to_numpy()
        mantener = (precios[-1] / precios[0]) * (1 - self.costo) / (1 + self.costo) - 1
        # Mismas operaciones y duraciones, desplazadas al azar dentro de la sesión.
        pares = []
        abiertos = []
        for o in self.operaciones:
            if o["lado"] == "compra" and not abiertos:
                abiertos.append(o)
            elif o["lado"] == "venta" and self.modo != "contado" and not abiertos:
                abiertos.append(o)
            elif abiertos:
                x = abiertos.pop()
                pares.append((x["i"], o["i"], 1 if x["lado"] == "compra" else -1))
        for x in abiertos:
            pares.append((x["i"], self.duracion, 1 if x["lado"] == "compra" else -1))
        # random.Random mantiene exactamente la secuencia previa de semillas.
        # Los 1,000 recorridos y la aritmética se calculan en arrays NumPy.
        plazos = [max(1, fin - ini) for ini, fin, _ in pares]
        sorteos = np.fromiter((self.rng.randrange(0, self.duracion - plazo + 1)
                              for _ in range(1000) for plazo in plazos), dtype=np.int64,
                             count=1000 * len(pares)).reshape(1000, len(pares))
        muestras = np.ones(1000, dtype=np.float64)
        for columna, (ini, _fin, lado) in enumerate(pares):
            j = sorteos[:, columna]
            ratio = precios[j + plazos[columna]] / precios[j]
            apertura = next(o for o in self.operaciones if o["i"] == ini and
                            o["lado"] == ("compra" if lado > 0 else "venta"))
            muestras *= 1 + apertura["fraccion"] * ((ratio - 1) * lado - self.costo * (1 + ratio))
        muestras -= 1
        neto = self.cash / 10000 - 1
        percentil = 100 * (sum(x < neto - 1e-10 for x in muestras) +
                           0.5 * sum(abs(x - neto) <= 1e-10 for x in muestras)) / 1000
        curva = pd.Series(self.curva)
        decisiones = []
        for o in self.operaciones:
            if o.get("automatica"):
                continue
            fin = next((x["i"] for x in self.operaciones if x["i"] > o["i"]), self.duracion)
            y = float(precios[fin] > precios[o["i"]])
            decisiones.append((o["prob_sube"], o["tasa_base"], y))
        brier = sum((p - y) ** 2 for p, _, y in decisiones) / len(decisiones) if decisiones else None
        brier_base = sum((b - y) ** 2 for _, b, y in decisiones) / len(decisiones) if decisiones else None
        resultado = {"neto": round(neto, 6), "peor_caida": round(float((curva / curva.cummax() - 1).min()), 6),
                     "no_operar": 0.0, "comprar_mantener": round(mantener, 6),
                     "percentil_azar": round(percentil, 2), "corridas_azar": 1000,
                     "mfe": max((o["mfe"] for o in self.operaciones), default=None),
                     "mae": min((o["mae"] for o in self.operaciones), default=None),
                     "brier": brier, "brier_base": brier_base,
                     "operaciones": len(self.operaciones)}
        if self.guardar:
            REGISTRO.parent.mkdir(parents=True, exist_ok=True)
            with REGISTRO.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"semilla": self.semilla, "modo": self.modo, "anonimo": self.anonimo,
                                    "particion": self.particion,
                                    "activo": self.activo, "inicio": self.velas.index[0].isoformat(),
                                    "jugador": getattr(self, "jugador", None),
                                    # Las velas no se guardan: se reconstruyen con semilla + archivo. Sin esto
                                    # cada sesion pesaba ~1 MB y el registro superaba el limite de GitHub.
                                    "resultado": resultado,
                                    # Bots: solo el resumen. Agente interactivo: pasos y operaciones.
                                    **({} if getattr(self, "resumido", False) else
                                       {"pasos": [_compacto(r) for r in self.registros],
                                        "operaciones": self.operaciones})}, ensure_ascii=False) + "\n")
        return resultado


def _compacto(r):
    out = {k: v for k, v in r.items() if k != "observacion"}
    obs = r.get("observacion") or {}
    if isinstance(obs, dict):
        out["vela"] = obs.get("vela")
    return out


_sesion = None


def nueva_sesion(semilla, modo="contado", activo=None, inicio=None, duracion=60,
                 intervalo="1m", anonimo=True, **kw):
    global _sesion
    _sesion = Sesion(semilla, modo, activo, inicio, duracion, intervalo, anonimo, **kw)
    return _sesion.observacion()


def paso(accion, **kw):
    if _sesion is None:
        raise RuntimeError("Primero llama nueva_sesion")
    return _sesion.paso(accion, **kw)


def terminar():
    if _sesion is None:
        raise RuntimeError("Primero llama nueva_sesion")
    return _sesion.terminar()
