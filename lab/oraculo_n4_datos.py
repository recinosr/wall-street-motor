"""Corpus GDELT congelado para el Oraculo nivel 4 (lab/oraculo_n4_prereg.json).

Descarga una respuesta cruda por tema, modo y año, la guarda en datos/gdelt_n4/ y escribe un
manifiesto sha256. Un archivo válido ya descargado no se vuelve a pedir.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

RAIZ = Path(__file__).resolve().parents[1]
PREREG = RAIZ / "lab" / "oraculo_n4_prereg.json"
PREREG_SHA = RAIZ / "lab" / "oraculo_n4_prereg.sha256"
CARPETA = RAIZ / "datos" / "gdelt_n4"
MANIFIESTO = CARPETA / "manifiesto.json"
API = "https://api.gdeltproject.org/api/v2/doc/doc"
UA = "ProyectoWallStreet-investigacion/oraculo-n4"
ANIOS = list(range(2017, 2027))
MODOS = ["timelinevol", "timelinetone"]
PAUSA_S = 8          # pausa entre peticiones
REINTENTOS = 8       # reintentos con espera creciente (15 s, 30 s, ... tope 300 s)
PRESUPUESTO_S = 5 * 3600  # tiempo máximo de descarga por corrida; lo que falte se reanuda en otra
CORTE = pd.Timestamp("2026-10-27").date()
FIN_CORPUS = "20261027235959"


def verificar_prereg() -> tuple[dict, str]:
    """Devuelve (prereg, sha256). Aborta si el sha256 no coincide con el sidecar."""
    datos = PREREG.read_bytes()
    esperado = PREREG_SHA.read_text(encoding="utf-8").split()[0].lower()
    real = hashlib.sha256(datos).hexdigest()
    if real != esperado:
        raise RuntimeError(f"sha256 del prereg no coincide: esperado {esperado}, real {real}. Abortado.")
    return json.loads(datos.decode("utf-8")), real


def consultas(prereg: dict) -> dict[str, str]:
    return {t: f"{q} sourcelang:english" for t, q in prereg["fuente_noticias"]["temas"].items()}


def _respuesta_valida(cuerpo: bytes) -> bool:
    try:
        datos = json.loads(cuerpo)
    except ValueError:
        return False
    return isinstance(datos, dict) and isinstance(datos.get("timeline"), list)


def _pedir(params: dict) -> bytes:
    """GET con pausa entre peticiones; GDELT da texto plano al limitar, eso cuenta como fallo."""
    for intento in range(REINTENTOS + 1):
        time.sleep(PAUSA_S if intento == 0 else min(300, 15 * 2 ** (intento - 1)))
        try:
            r = requests.get(API, params=params, headers={"User-Agent": UA}, timeout=60)
        except requests.RequestException as e:
            print(f"  intento {intento}: {type(e).__name__}", flush=True)
            continue
        if r.status_code == 200 and _respuesta_valida(r.content):
            return r.content
        print(f"  intento {intento}: HTTP {r.status_code} {r.content[:160]!r}", flush=True)
    raise RuntimeError(f"GDELT sin respuesta válida tras {REINTENTOS} reintentos: "
                       f"{params['query']} {params['mode']} {params['startdatetime'][:4]}")


def descargar(prereg: dict) -> int:
    CARPETA.mkdir(parents=True, exist_ok=True)
    nuevos, faltan, inicio = 0, 0, time.monotonic()
    for tema, q in consultas(prereg).items():
        for modo in MODOS:
            for anio in ANIOS:
                destino = CARPETA / f"{tema}_{modo}_{anio}.json"
                if destino.exists() and _respuesta_valida(destino.read_bytes()):
                    continue
                params = {"query": q, "mode": modo, "format": "json",
                          "startdatetime": f"{anio}0101000000",
                          "enddatetime": min(f"{anio}1231235959", FIN_CORPUS)}
                if time.monotonic() - inicio > PRESUPUESTO_S:
                    faltan += 1
                    continue
                print(f"{tema} {modo} {anio}", flush=True)
                try:
                    cuerpo = _pedir(params)
                except RuntimeError as e:
                    print(f"  pendiente: {e}", flush=True)
                    faltan += 1
                    continue
                tmp = destino.with_suffix(".tmp")
                tmp.write_bytes(cuerpo)
                os.replace(tmp, destino)
                nuevos += 1
    if faltan:
        raise RuntimeError(f"GDELT: {nuevos} descargas nuevas, faltan {faltan}; volver a lanzar para reanudar")
    return nuevos


def escribir_manifiesto(prereg: dict, prereg_sha: str) -> int:
    archivos = {}
    for tema, q in consultas(prereg).items():
        for modo in MODOS:
            for anio in ANIOS:
                nombre = f"{tema}_{modo}_{anio}.json"
                ruta = CARPETA / nombre
                if not ruta.exists() or not _respuesta_valida(ruta.read_bytes()):
                    raise RuntimeError(f"falta o es inválido: {nombre}")
                archivos[nombre] = hashlib.sha256(ruta.read_bytes()).hexdigest()
    manifiesto = {"prereg_sha256": prereg_sha, "fin_corpus": CORTE.isoformat(),
                  "consultas": consultas(prereg), "archivos": archivos}
    MANIFIESTO.write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    return len(archivos)


def verificar_manifiesto(carpeta: Path = CARPETA) -> None:
    """Revisa el prereg y el sha256 de cada archivo crudo contra el manifiesto."""
    _, sha = verificar_prereg()
    man = json.loads((carpeta / "manifiesto.json").read_text(encoding="utf-8"))
    if man["prereg_sha256"] != sha:
        raise RuntimeError("el manifiesto GDELT se generó con otro prereg")
    for nombre, esperado in man["archivos"].items():
        real = hashlib.sha256((carpeta / nombre).read_bytes()).hexdigest()
        if real != esperado:
            raise RuntimeError(f"archivo GDELT alterado: {nombre}")


def _serie(carpeta: Path, tema: str, modo: str) -> pd.Series:
    """Une los años de un tema y modo; agrega por día UTC con la media."""
    puntos = []
    for anio in ANIOS:
        datos = json.loads((carpeta / f"{tema}_{modo}_{anio}.json").read_text(encoding="utf-8"))
        if not datos["timeline"]:
            continue
        for punto in datos["timeline"][0]["data"]:  # primera serie
            dia = datetime.strptime(punto["date"], "%Y%m%dT%H%M%SZ").date()
            puntos.append((dia, pd.to_numeric(punto["value"], errors="coerce")))
    if not puntos:
        return pd.Series(dtype=float)
    df = pd.DataFrame(puntos, columns=["dia", "valor"])
    return df.groupby("dia")["valor"].mean()


def cargar_diario(carpeta: Path = CARPETA, verificar: bool = True) -> pd.DataFrame:
    """Columnas <tema>_vol y <tema>_tono, indexadas por fecha UTC (datetime.date), hasta el corte."""
    if verificar:
        verificar_manifiesto(carpeta)
    prereg, _ = verificar_prereg()
    cols = {}
    for tema in prereg["fuente_noticias"]["temas"]:
        cols[f"{tema}_vol"] = _serie(carpeta, tema, "timelinevol")
        cols[f"{tema}_tono"] = _serie(carpeta, tema, "timelinetone")
    df = pd.DataFrame(cols).sort_index()
    df = df[[f <= CORTE for f in df.index]]
    df.index.name = "fecha"
    return df


def main() -> int:
    prereg, sha = verificar_prereg()
    nuevos = descargar(prereg)
    total = escribir_manifiesto(prereg, sha)
    print(f"GDELT n4: {nuevos} descargas nuevas; manifiesto con {total} archivos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
