"""Descarga y combina velas 1m cerradas. Uso: python -m lab.archivar diario|recuperar --salida DIR."""
import argparse
import datetime as dt
import gzip
import io
from pathlib import Path

import pandas as pd
import requests

UA = {"User-Agent": "wall-street-motor/1.0 (public research)"}
LISTA = ("BTC", "ETH")

COINBASE = {"BTC": "BTC-USD", "ETH": "ETH-USD"}
COLUMNAS = ["open", "high", "low", "close", "volume"]


def descargar(simbolo, dia, sesion=None):
    """Descarga un día UTC completo; devuelve índice UTC sin minutos incompletos."""
    sesion = sesion or requests.Session()
    inicio = pd.Timestamp(dia, tz="UTC")
    fin = inicio + pd.Timedelta(days=1)
    if simbolo in COINBASE:
        producto = COINBASE.get(simbolo)
        if not producto:
            raise ValueError(f"Falta producto Coinbase para {simbolo}")
        filas = []
        cursor = inicio
        while cursor < fin:
            limite = min(cursor + pd.Timedelta(minutes=300), fin)
            r = sesion.get(f"https://api.exchange.coinbase.com/products/{producto}/candles",
                           params={"start": cursor.isoformat(), "end": limite.isoformat(), "granularity": 60},
                           headers=UA, timeout=30)
            r.raise_for_status()
            filas.extend(r.json())
            cursor = limite
        if not filas:
            return pd.DataFrame(columns=COLUMNAS, index=pd.DatetimeIndex([], tz="UTC"))
        df = pd.DataFrame(filas, columns=["time", "low", "high", "open", "close", "volume"])
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
    else:
        raise ValueError("Solo BTC y ETH de Coinbase")
    df = df[COLUMNAS].apply(pd.to_numeric, errors="coerce").dropna(subset=["open", "high", "low", "close"])
    return df[(df.index >= inicio) & (df.index < fin)].sort_index().loc[lambda d: ~d.index.duplicated(keep="last")]


def guardar(df, simbolo, salida):
    if df.empty:
        return []
    paths = []
    for mes, grupo in df.groupby(df.index.strftime("%Y-%m")):
        path = Path(salida) / "velas" / "1m" / simbolo / f"{mes}.csv.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            anterior = pd.read_csv(io.BytesIO(gzip.decompress(path.read_bytes())), parse_dates=["time"]).set_index("time")
            anterior.index = pd.DatetimeIndex(anterior.index).tz_convert("UTC")
            grupo = pd.concat([anterior, grupo]).sort_index()
            grupo = grupo[~grupo.index.duplicated(keep="last")]
        csv = grupo[COLUMNAS].rename_axis("time").to_csv(float_format="%.10g").encode()
        with path.open("wb") as f:
            with gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as z:
                z.write(csv)
        paths.append(path)
    return paths


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("modo", choices=["diario", "recuperar"])
    p.add_argument("--salida", required=True)
    p.add_argument("--dias", type=int, default=29)
    p.add_argument("--fecha", help="Último día UTC cerrado; por defecto ayer")
    args = p.parse_args()
    ultimo = dt.date.fromisoformat(args.fecha) if args.fecha else dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    dias = [ultimo - dt.timedelta(days=i) for i in range(args.dias if args.modo == "recuperar" else 1)]
    fallas = []
    with requests.Session() as sesion:
        for dia in reversed(dias):
            for simbolo in LISTA:
                try:
                    df = descargar(simbolo, dia, sesion)
                    guardar(df, simbolo, args.salida)
                    print(f"{dia} {simbolo}: {len(df)} velas", flush=True)
                except (requests.RequestException, ValueError, KeyError, TypeError) as e:
                    fallas.append(f"{dia} {simbolo}: {e}")
    if fallas:
        print("Descargas pendientes:\n" + "\n".join(fallas), flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
