"""Descarga y caché versionada (datos/pit) para el currículo del Oráculo.

Todo queda en el repo en formato compacto y con hora de disponibilidad en UTC:
  - precios diarios (Yahoo chart API) -> datos/pit/precios/<SIMBOLO>.csv.gz
  - FOMC (federalreserve.gov), CPI y empleo (ALFRED, fechas de release) y
    8-K de EDGAR (acceptanceDateTime) -> datos/pit/eventos.csv
  - datos/pit/manifiesto.json con fuente, hash y cobertura.

Uso: python -m lab.oraculo_datos [--solo precios|eventos]
Las fuentes que fallen no borran lo ya guardado (se conserva la caché previa).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PIT = ROOT / "datos" / "pit"
PRECIOS = PIT / "precios"
EVENTOS = PIT / "eventos.csv"
MANIFIESTO = PIT / "manifiesto.json"
NY = ZoneInfo("America/New_York")
UTC = timezone.utc
UA = os.environ.get("SEC_USER_AGENT") or "ProyectoWallStreet research admin@proyectowallstreet.org"  # SEC exige contacto; sobrescribir con SEC_USER_AGENT

SIMBOLOS = ["^GSPC", "SPY", "QQQ", "GLD", "TLT", "VT", "SCHD", "VWRA.L", "IBIT", "BTC-USD",
            "TSLA", "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META"]
CIKS = {"TSLA": 1318605, "NVDA": 1045810, "AAPL": 320193, "MSFT": 789019,
        "GOOGL": 1652044, "AMZN": 1018724, "META": 1326801}
MESES = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"])}


def http(url, timeout=60, reintentos=4, pausa=0.15):
    ultimo = None
    for k in range(reintentos):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urlopen(req, timeout=timeout) as r:
                body = r.read()
            time.sleep(pausa)
            return body
        except (HTTPError, URLError, TimeoutError) as exc:
            ultimo = exc
            time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"fallo al descargar {url}: {ultimo}")


def a_utc_ny(dia, hora, minuto=0):
    return datetime(dia.year, dia.month, dia.day, hora, minuto, tzinfo=NY).astimezone(UTC)


# ---------------------------------------------------------------- precios
def descargar_precios(simbolo):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo.replace('^', '%5E')}"
           f"?period1=-631152000&period2={int(time.time()) + 86400}&interval=1d&events=div,splits")
    data = json.loads(http(url, timeout=120))
    res = data["chart"]["result"]
    if not res:
        raise RuntimeError(f"Yahoo sin datos para {simbolo}")
    r = res[0]
    q = r["indicators"]["quote"][0]
    filas = []
    for i, ts in enumerate(r.get("timestamp") or []):
        c = q["close"][i]
        if c is None:
            continue
        # Fecha local de la bolsa (gmtoffset del instrumento).
        off = r["meta"].get("gmtoffset", 0)
        d = (datetime(1970, 1, 1) + timedelta(seconds=ts + off)).date()
        if d.weekday() >= 5 and simbolo != "BTC-USD":
            continue
        # Disponible al cierre NY (16:00) para bolsas de EE. UU.; Londres 16:30 UK;
        # BTC cierra a 00:00 UTC del día siguiente.
        if simbolo == "BTC-USD":
            disp = datetime(d.year, d.month, d.day, tzinfo=UTC).replace(hour=23, minute=59)
        elif simbolo.endswith(".L"):
            disp = datetime(d.year, d.month, d.day, 16, 30, tzinfo=ZoneInfo("Europe/London")).astimezone(UTC)
        else:
            disp = a_utc_ny(d, 16)
        filas.append([d.isoformat(), q["open"][i], q["high"][i], q["low"][i], c, q["volume"][i],
                      disp.strftime("%Y-%m-%dT%H:%M:%SZ")])
    # Descarta la vela del día en curso si la bolsa aún no cerró (no es dato final).
    ahora = datetime.now(UTC)
    filas = [f for f in filas if datetime.strptime(f[6], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) <= ahora]
    # Una fila por fecha (la última gana).
    únicas = {}
    for f in filas:
        únicas[f[0]] = f
    return [únicas[k] for k in sorted(únicas)]


def guardar_precios(simbolo, filas):
    PRECIOS.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["date", "open", "high", "low", "close", "volume", "available_at"])
    for f in filas:
        w.writerow([f[0]] + [("" if v is None else round(v, 6) if isinstance(v, float) else v) for v in f[1:6]] + [f[6]])
    path = PRECIOS / f"{simbolo.replace('^', '_')}.csv.gz"
    # mtime=0 -> bytes deterministas: sin cambios de datos no hay diff en git.
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        gz.write(buf.getvalue().encode())
    return path


def actualizar_precios():
    info = {}
    for s in SIMBOLOS:
        try:
            filas = descargar_precios(s)
            p = guardar_precios(s, filas)
            info[s] = {"archivo": str(p.relative_to(ROOT)).replace("\\", "/"), "filas": len(filas),
                       "primera": filas[0][0], "ultima": filas[-1][0],
                       "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            print(f"precios {s}: {len(filas)} filas {filas[0][0]}..{filas[-1][0]}")
        except Exception as exc:  # conserva la caché previa
            print(f"precios {s}: FALLÓ {exc}", file=sys.stderr)
            info[s] = {"error": str(exc)[:200]}
    return info


# ---------------------------------------------------------------- eventos
def _fechas_reunion(texto_mes, texto_dias, anio):
    """('January','27-28') -> último día; ('Jan/Feb','31-1') o 'January 31-February 1' -> 1-feb."""
    abrev = {m[:3]: n for m, n in MESES.items()}
    meses = [abrev[w[:3]] for w in re.findall(r"[A-Za-z]+", texto_mes + " " + texto_dias) if w[:3] in abrev]
    dias = [int(x) for x in re.findall(r"\d+", texto_dias)]
    if not dias or not meses:
        return None
    return date(anio, meses[-1], dias[-1])


def fomc():
    ev = []
    hoy = date.today()
    for anio in range(1994, 2021):
        html = http(f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{anio}.htm").decode("utf8", "ignore")
        for m in re.finditer(r"([A-Z][a-z]+(?:/[A-Z][a-z]+)?)\s+([\dA-Za-z\-]+?)\s+Meeting\s*-\s*(\d{4})", html):
            d = _fechas_reunion(m.group(1), m.group(2), int(m.group(3)))
            if d:
                ev.append(d)
    html = http("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm").decode("utf8", "ignore")
    partes = re.split(r"(\d{4}) FOMC Meetings", html)
    for i in range(1, len(partes) - 1, 2):
        anio = int(partes[i])
        if anio < 2021:
            continue
        for m in re.finditer(r'fomc-meeting__month[^>]*><strong>([^<]+)</strong></div>\s*<div class="fomc-meeting__date[^>]*>\s*([^<]+?)\s*(?:\*|</div>)', partes[i + 1]):
            if "notation" in m.group(2):
                continue
            d = _fechas_reunion(m.group(1), m.group(2), anio)
            if d:
                ev.append(d)
    filas = []
    for d in sorted(set(ev)):
        # Comunicado ~14:00-14:15 ET desde 1999; antes solo hubo comunicado si cambiaba la tasa
        # y la hora varía: se usa el cierre (16:00 ET) como disponibilidad conservadora.
        disp = a_utc_ny(d, 14, 30) if d.year >= 1999 else a_utc_ny(d, 16)
        filas.append(["FOMC", d.isoformat(), disp.strftime("%Y-%m-%dT%H:%M:%SZ"), "", "programado" if d > hoy else "ocurrido"])
    return filas


def alfred_release(rid, tipo):
    import openpyxl
    body = http(f"https://alfred.stlouisfed.org/release/downloaddates?rid={rid}&ff=csv", timeout=90)
    ws = openpyxl.load_workbook(io.BytesIO(body))["Release Dates"]
    filas = []
    for (v,) in ws.iter_rows(min_row=2, values_only=True):
        if isinstance(v, datetime):
            d = v.date()
        elif isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            d = date.fromisoformat(v)
        else:
            continue
        if d.year < 1990:
            continue
        filas.append([tipo, d.isoformat(), a_utc_ny(d, 8, 30).strftime("%Y-%m-%dT%H:%M:%SZ"), "", "ALFRED release date"])
    return filas


def _aceptado(txt):
    txt = str(txt)
    if re.fullmatch(r"\d{14}", txt):
        return datetime.strptime(txt, "%Y%m%d%H%M%S").replace(tzinfo=NY).astimezone(UTC)
    return datetime.fromisoformat(txt.replace("Z", "+00:00")).astimezone(UTC)


def edgar_8k(ticker, cik):
    base = json.loads(http(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))
    bloques = [base["filings"]["recent"]]
    for f in base["filings"].get("files", []):
        bloques.append(json.loads(http("https://data.sec.gov/submissions/" + f["name"])))
    filas = []
    for b in bloques:
        for i, form in enumerate(b.get("form", [])):
            if form != "8-K":
                continue
            acc = (b.get("acceptanceDateTime") or [None] * len(b["form"]))[i]
            if not acc:
                continue
            items = b.get("items", [""] * len(b["form"]))[i]
            filas.append(["8-K", b["filingDate"][i], _aceptado(acc).strftime("%Y-%m-%dT%H:%M:%SZ"), ticker, items])
    return filas


def actualizar_eventos():
    por_fuente, todo = {}, []
    previos = leer_eventos_csv()
    for nombre, fn in [("FOMC", fomc), ("CPI", lambda: alfred_release(10, "CPI")),
                       ("EMPLEO", lambda: alfred_release(50, "EMPLEO"))] + \
                      [(f"8-K {t}", (lambda t=t, c=c: edgar_8k(t, c))) for t, c in CIKS.items()]:
        try:
            filas = fn()
            por_fuente[nombre] = len(filas)
            todo.extend(filas)
            print(f"eventos {nombre}: {len(filas)}")
        except Exception as exc:
            print(f"eventos {nombre}: FALLÓ {exc}; se conserva la caché previa", file=sys.stderr)
            prev = [r for r in previos if _fuente(r) == nombre]
            todo.extend(prev)
            por_fuente[nombre] = {"error": str(exc)[:200], "conservadas": len(prev)}
    todo = sorted({tuple(r) for r in todo}, key=lambda r: (r[1], r[0], r[3]))
    PIT.mkdir(parents=True, exist_ok=True)
    with open(EVENTOS, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["tipo", "fecha", "available_at", "ticker", "detalle"])
        w.writerows(todo)
    return por_fuente


def _fuente(r):
    return {"FOMC": "FOMC", "CPI": "CPI", "EMPLEO": "EMPLEO"}.get(r[0], f"8-K {r[3]}")


def leer_eventos_csv():
    if not EVENTOS.exists():
        return []
    with open(EVENTOS, encoding="utf-8") as f:
        rd = csv.reader(f)
        next(rd, None)
        return [r for r in rd]


def main(argv=None):
    argv = argv or sys.argv[1:]
    solo = argv[argv.index("--solo") + 1] if "--solo" in argv else None
    PIT.mkdir(parents=True, exist_ok=True)
    man = json.loads(MANIFIESTO.read_text(encoding="utf-8")) if MANIFIESTO.exists() else {}
    if solo in (None, "precios"):
        man["precios"] = actualizar_precios()
    if solo in (None, "eventos"):
        man["eventos"] = actualizar_eventos()
        man["eventos_sha256"] = hashlib.sha256(EVENTOS.read_bytes()).hexdigest()
    man["reglas_disponibilidad"] = {
        "precios": "cierre de la bolsa (NY 16:00, Londres 16:30, BTC 23:59 UTC); OHLC con splits ajustados, sin ajuste por dividendos",
        "FOMC": "14:30 ET del último día de reunión programada desde 1999; 16:00 ET antes. Sin llamadas de emergencia",
        "CPI/EMPLEO": "08:30 ET de la fecha de release de ALFRED (incluye fechas de revisión de la serie)",
        "8-K": "acceptanceDateTime de EDGAR convertido a UTC",
    }
    man["fuentes"] = {"precios": "Yahoo Finance chart API", "FOMC": "federalreserve.gov calendarios y páginas históricas",
                      "CPI/EMPLEO": "ALFRED (St. Louis Fed) release dates rid=10 y rid=50", "8-K": "SEC EDGAR submissions"}
    MANIFIESTO.write_text(json.dumps(man, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")


# --------------------------------------------------------------- lectores
def cargar_precios(simbolo):
    import pandas as pd
    path = PRECIOS / f"{simbolo.replace('^', '_')}.csv.gz"
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    df["available_at"] = pd.to_datetime(df["available_at"], utc=True)
    return df


def cargar_eventos():
    import pandas as pd
    df = pd.read_csv(EVENTOS, dtype=str, keep_default_na=False)
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["available_at"] = pd.to_datetime(df["available_at"], utc=True)
    return df


if __name__ == "__main__":
    main()
