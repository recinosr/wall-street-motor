"""Ingesta con caché y hora de disponibilidad para los ensayos del Oráculo.

Cada observación lleva available_at en UTC. Las funciones de consulta filtran
por ese instante; una fecha del evento nunca sustituye a la publicación.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "datos" / "cache" / "oraculo-pit"
NY = ZoneInfo("America/New_York")
UTC = timezone.utc


def utc(value):
    """Parsea un instante y exige zona horaria para evitar fechas ambiguas."""
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("El instante debe incluir zona horaria")
    return dt.astimezone(UTC)


def visibles(registros, corte):
    instante = utc(corte)
    return [r for r in registros if utc(r["available_at"]) <= instante]


def _get(url, cache_key, ttl=86400, timeout=30):
    """GET con caché de contenido y escritura atómica; propaga errores de red."""
    if not re.fullmatch(r"[a-f0-9]{64}", cache_key):
        raise ValueError("Clave de caché inválida")
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{cache_key}.json"
    if path.exists() and time.time() - path.stat().st_mtime < ttl:
        return json.loads(path.read_text(encoding="utf-8"))
    req = Request(url, headers={"User-Agent": "ProyectoWallStreet research jose@example.invalid", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as response:
            body = response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        raise RuntimeError(f"No se pudo descargar fuente ({type(exc).__name__})") from exc
    payload = {"url_sha256": hashlib.sha256(url.encode()).hexdigest(),
               "fetched_at": datetime.now(UTC).isoformat(), "body": body.decode("utf-8")}
    fd, tmp = tempfile.mkstemp(dir=CACHE, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return payload


def _key(fuente, params):
    return hashlib.sha256(json.dumps([fuente, params], sort_keys=True).encode()).hexdigest()


def precios_yahoo(simbolo, inicio, fin):
    """Velas diarias Yahoo con disponibilidad estimada al cierre NY (16:00).

    Fin es exclusivo. Los cierres ajustados se retienen para retornos, pero
    Yahoo puede reescribirlos por acciones corporativas posteriores: para
    ensayos estrictos se usan open/high/low/close no ajustados.
    """
    import pandas as pd
    a, b = int(pd.Timestamp(inicio, tz="UTC").timestamp()), int(pd.Timestamp(fin, tz="UTC").timestamp())
    params = {"symbol": simbolo, "period1": a, "period2": b, "interval": "1d"}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}?{urlencode(params)}"
    payload = _get(url, _key("yahoo-chart", params), ttl=7 * 86400)
    result = json.loads(payload["body"])["chart"]["result"]
    if not result:
        raise ValueError("Yahoo no devolvió precios")
    q = result[0]
    quote = q["indicators"]["quote"][0]
    adj = q["indicators"].get("adjclose", [{}])[0].get("adjclose", [])
    rows = []
    for i, stamp in enumerate(q["timestamp"]):
        day = datetime.fromtimestamp(stamp, UTC).date()
        close_at = datetime.combine(day, datetime.min.time(), NY).replace(hour=16).astimezone(UTC)
        vals = {k: quote[k][i] for k in ("open", "high", "low", "close", "volume")}
        if vals["close"] is None:
            continue
        vals.update({"symbol": simbolo, "date": day.isoformat(),
                     "available_at": close_at.isoformat(), "source": "Yahoo Finance chart API"})
        if i < len(adj) and adj[i] is not None:
            vals["adj_close"] = adj[i]
        rows.append(vals)
    return rows


def fomc(inicio="1994-01-01", fin="2100-01-01"):
    """Fechas de anuncios de tasa publicados por Fed, disponibles desde 14:00 ET."""
    params = {"from": inicio, "to": fin}
    url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    payload = _get(url, _key("fed-fomc-calendar", params), ttl=30 * 86400)
    dates = sorted(set(re.findall(r"monetary(\d{8})a\.htm", payload["body"], re.I)))
    events = []
    for stamp in dates:
        day = datetime.strptime(stamp, "%Y%m%d").date()
        if not (inicio <= day.isoformat() < fin):
            continue
        available = datetime(day.year, day.month, day.day, 14, 0, tzinfo=NY).astimezone(UTC)
        events.append({"tipo": "FOMC_statement", "date": day.isoformat(), "available_at": available.isoformat(),
                       "source": url, "source_sha256": hashlib.sha256(payload["body"].encode()).hexdigest()})
    return {"source": "Federal Reserve FOMC calendars", "events": events,
            "coverage": "releases enlazados en el calendario actual; no incluye fechas de primera publicación del calendario de reuniones",
            "fetched_at": payload["fetched_at"]}


def edgar_presentaciones(cik, desde="1994-01-01", hasta="2100-01-01"):
    cik = str(cik).zfill(10)
    if not cik.isdigit():
        raise ValueError("CIK debe ser numérico")
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    payload = _get(url, _key("sec-submissions", {"cik": cik}), ttl=7 * 86400)
    data = json.loads(payload["body"])
    recent = data.get("filings", {}).get("recent", {})
    rows = []
    for i, accession in enumerate(recent.get("accessionNumber", [])):
        filed = recent["filingDate"][i]
        if not (desde <= filed < hasta):
            continue
        accepted = (recent.get("acceptanceDateTime") or [None] * len(recent["filingDate"]))[i]
        if not accepted:
            continue
        available = datetime.strptime(accepted, "%Y%m%d%H%M%S").replace(tzinfo=NY).astimezone(UTC)
        rows.append({"cik": cik, "form": recent["form"][i], "filed": filed,
                     "accession": accession, "available_at": available.isoformat(),
                     "source": "SEC EDGAR submissions"})
    return {"rows": rows, "coverage": "solo bloque recent del endpoint; archivos históricos no descargados",
            "fetched_at": payload["fetched_at"]}


def gdelt(temas, inicio, fin, maxrecords=250):
    """Busca titulares GDELT por término y conserva la hora de indexación.

    GDELT DOC devuelve ``seendate`` (cuando lo indexó), no siempre la hora
    original de publicación. Se usa como disponibilidad conservadora y se
    nombra con honestidad; el endpoint gratuito limita el histórico consultable.
    """
    terms = [str(t).strip() for t in temas if str(t).strip()]
    if not terms:
        raise ValueError("Se requiere al menos un término")
    start, end = utc(inicio), utc(fin)
    if end <= start:
        raise ValueError("fin debe ser posterior a inicio")
    params = {"query": " OR ".join(f'"{x}"' for x in terms), "mode": "ArtList", "format": "json",
              "startdatetime": start.strftime("%Y%m%d%H%M%S"), "enddatetime": end.strftime("%Y%m%d%H%M%S"),
              "maxrecords": min(250, max(1, int(maxrecords))), "sort": "DateDesc"}
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode(params)
    payload = _get(url, _key("gdelt-doc", params), ttl=365 * 86400)
    raw = json.loads(payload["body"])
    rows = []
    for art in raw.get("articles", []):
        pub = datetime.strptime(art["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        rows.append({"title": art.get("title", ""), "url": art.get("url"), "source": art.get("domain"),
                     "gdelt_seen_at": pub.isoformat(), "available_at": pub.isoformat(), "query_terms": terms})
    return rows


def serie_cpi_bls(inicio, fin):
    """Fechas de publicaciones CPI del archivo BLS, al momento de release 08:30 ET."""
    url = "https://www.bls.gov/bls/news-release/cpi.htm"
    params = {"from": inicio, "to": fin}
    payload = _get(url, _key("bls-cpi-archive", params), ttl=30 * 86400)
    dates = sorted(set(re.findall(r"cpi_(\d{8})\.pdf", payload["body"], re.I)))
    events = []
    for stamp in dates:
        day = datetime.strptime(stamp, "%m%d%Y").date()
        if not (inicio <= day.isoformat() < fin):
            continue
        available = datetime(day.year, day.month, day.day, 8, 30, tzinfo=NY).astimezone(UTC)
        events.append({"tipo": "CPI_release", "date": day.isoformat(), "available_at": available.isoformat(),
                       "source": url, "source_sha256": hashlib.sha256(payload["body"].encode()).hexdigest()})
    return {"series": "CPI", "events": events,
            "coverage": "PDFs disponibles en el archivo BLS; CPI no publicado por cierres de gobierno queda ausente",
            "fetched_at": payload["fetched_at"]}
