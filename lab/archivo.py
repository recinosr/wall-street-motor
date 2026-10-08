"""Archivo de velas cerradas de un minuto en la rama datos.

Formato: UTC ISO 8601, OHLCV; una fila por inicio de minuto. Los meses se
pueden leer desde un directorio exportado o directamente con ``git show``.
"""
import gzip
import io
import os
import re
import subprocess
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
COLUMNAS = ["open", "high", "low", "close", "volume"]


def _ruta(simbolo, mes):
    sim = simbolo.upper()
    if not re.fullmatch(r"[A-Z0-9.^_-]+", sim):
        raise ValueError("Símbolo inválido")
    if not re.fullmatch(r"\d{4}-\d{2}", mes):
        raise ValueError("Mes inválido")
    return f"velas/1m/{sim}/{mes}.csv.gz"


def leer(simbolo, desde, hasta, raiz=None, rama="datos"):
    """Devuelve velas UTC en [desde, hasta); no consulta datos vivos."""
    desde = pd.Timestamp(desde).tz_localize("UTC") if pd.Timestamp(desde).tzinfo is None else pd.Timestamp(desde).tz_convert("UTC")
    hasta = pd.Timestamp(hasta).tz_localize("UTC") if pd.Timestamp(hasta).tzinfo is None else pd.Timestamp(hasta).tz_convert("UTC")
    if hasta <= desde:
        raise ValueError("hasta debe ser posterior a desde")
    meses = pd.period_range(desde.tz_localize(None).to_period("M"),
                             (hasta - pd.Timedelta(nanoseconds=1)).tz_localize(None).to_period("M"), freq="M")
    partes = []
    for mes in meses:
        ruta = _ruta(simbolo, str(mes))
        if raiz is not None:
            archivo = Path(raiz) / ruta
            if not archivo.exists():
                continue
            contenido = archivo.read_bytes()
        else:
            archivo = RAIZ / ruta
            if archivo.exists():
                contenido = archivo.read_bytes()
            else:
                contenido = None
                for ref in (rama, f"origin/{rama}"):
                    p = subprocess.run(["git", "show", f"{ref}:{ruta}"], cwd=RAIZ,
                                       capture_output=True, check=False)
                    if p.returncode == 0:
                        contenido = p.stdout
                        break
                if contenido is None:
                    continue
        df = pd.read_csv(io.BytesIO(gzip.decompress(contenido)), parse_dates=["time"])
        df = df.set_index("time")
        df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
        partes.append(df[COLUMNAS])
    if not partes:
        raise LookupError(f"Sin velas archivadas para {simbolo} entre {desde} y {hasta}")
    out = pd.concat(partes).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out = out[(out.index >= desde) & (out.index < hasta)]
    if out.empty:
        raise LookupError(f"Sin velas archivadas para {simbolo} entre {desde} y {hasta}")
    return out
