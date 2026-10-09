"""S&P 500 completo: lista con sector, precios diarios y fundamentales oficiales de la SEC.

Uso: python -m lab.sp500 [--salida salida/sp500.json]
Fundamentales: SEC XBRL "frames" (un archivo por concepto con todas las empresas).
La SEC exige un User-Agent con contacto real: variable SEC_CONTACT ("Nombre correo").
Sin SEC_CONTACT se publican lista, sector y precios, y los fundamentales quedan vacíos.
Cada dato fundamental guarda el periodo y la fecha de presentación (sin mirar al futuro).
"""
import argparse
import datetime as dt
import io
import json
import math
import os
import time
from pathlib import Path

import pandas as pd
import requests

RAIZ = Path(__file__).resolve().parents[1]
WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SPARK = "https://query1.finance.yahoo.com/v7/finance/spark"
FRAMES = "https://data.sec.gov/api/xbrl/frames/{tax}/{tag}/{uom}/{periodo}.json"
UA = {"User-Agent": "Mozilla/5.0"}
SECTORES = {"Information Technology": "Tecnología", "Health Care": "Salud", "Financials": "Finanzas",
            "Consumer Discretionary": "Consumo discrecional", "Communication Services": "Comunicación",
            "Industrials": "Industria", "Consumer Staples": "Consumo básico", "Energy": "Energía",
            "Utilities": "Servicios públicos", "Real Estate": "Inmobiliario", "Materials": "Materiales"}
# Conceptos alternativos: se usa el primero que la empresa reporte.
CONCEPTOS = {
    "ingresos": ["Revenues", "RevenueFromContractWithCustomerIncludingAssessedTax", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "utilidad_neta": ["NetIncomeLoss"],
    "utilidad_operativa": ["OperatingIncomeLoss"],
    "flujo_operativo": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}
BALANCE = {
    "patrimonio": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "deuda_lp": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "efectivo": ["CashAndCashEquivalentsAtCarryingValue"],
}


def lista():
    html = requests.get(WIKI, headers=UA, timeout=30).text
    t = pd.read_html(io.StringIO(html))[0]
    out = []
    for _, r in t.iterrows():
        out.append({"sim": str(r["Symbol"]).replace(".", "-"), "nombre": str(r["Security"]),
                    "sector": SECTORES.get(str(r["GICS Sector"]), str(r["GICS Sector"])),
                    "industria": str(r["GICS Sub-Industry"]), "cik": int(r["CIK"]),
                    "sede": str(r["Headquarters Location"]), "desde": str(r["Date added"])})
    return out


def precios(simbolos, lote=20):
    res = {}
    for i in range(0, len(simbolos), lote):
        grupo = simbolos[i:i + lote]
        try:
            j = requests.get(SPARK, params={"symbols": ",".join(grupo), "range": "1y", "interval": "1d"},
                             headers=UA, timeout=30).json()
            for item in j["spark"]["result"]:
                rr = item["response"][0]
                c = [x for x in rr["indicators"]["quote"][0]["close"] if x is not None]
                if len(c) < 30:
                    continue
                ts = rr["timestamp"][-1]
                res[item["symbol"]] = {"precio": c[-1], "fecha": dt.datetime.utcfromtimestamp(ts).date().isoformat(),
                                       "cambio_dia_pct": (c[-1] / c[-2] - 1) * 100,
                                       "max_52s": max(c), "min_52s": min(c),
                                       "momentum_12_1_pct": (c[-22] / c[0] - 1) * 100 if len(c) > 230 else None,
                                       "ret_1a_pct": (c[-1] / c[0] - 1) * 100}
        except Exception:
            pass
        time.sleep(0.3)
    return res


def frame(tag, periodo, contacto, uom="USD", tax="us-gaap"):
    r = requests.get(FRAMES.format(tax=tax, tag=tag, uom=uom, periodo=periodo),
                     headers={"User-Agent": contacto, "Accept-Encoding": "gzip, deflate"}, timeout=60)
    time.sleep(0.15)  # límite de la SEC: 10 solicitudes por segundo
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    return {d["cik"]: {"valor": d["val"], "periodo": periodo, "presentado": d.get("filed"), "fin": d.get("end")}
            for d in r.json().get("data", [])}


def fundamentales(ciks, contacto, anio):
    datos = {c: {} for c in ciks}
    for campo, tags in CONCEPTOS.items():
        for y in (anio, anio - 1):
            for tag in tags:
                f = frame(tag, f"CY{y}", contacto)
                for c in ciks:
                    clave = campo if y == anio else campo + "_previo"
                    if c in f and clave not in datos[c]:
                        datos[c][clave] = f[c]
    for campo, tags in BALANCE.items():
        for periodo in (f"CY{anio}Q4I", f"CY{anio}Q3I", f"CY{anio}Q2I"):
            for tag in tags:
                f = frame(tag, periodo, contacto)
                for c in ciks:
                    if c in f and campo not in datos[c]:
                        datos[c][campo] = f[c]
    for periodo in (f"CY{anio + 1}Q2I", f"CY{anio + 1}Q1I", f"CY{anio}Q4I"):
        f = frame("EntityCommonStockSharesOutstanding", periodo, contacto, uom="shares", tax="dei")
        for c in ciks:
            if c in f and "acciones" not in datos[c]:
                datos[c]["acciones"] = f[c]
    return datos


def _v(d, k):
    x = d.get(k)
    return x["valor"] if x else None


def metricas(f, precio):
    m = {}
    ing, ing0, un = _v(f, "ingresos"), _v(f, "ingresos_previo"), _v(f, "utilidad_neta")
    op, fo, cx = _v(f, "utilidad_operativa"), _v(f, "flujo_operativo"), _v(f, "capex")
    pat, deuda, acc = _v(f, "patrimonio"), _v(f, "deuda_lp"), _v(f, "acciones")
    if ing and ing0:
        m["crecimiento_ingresos_pct"] = (ing / ing0 - 1) * 100
    if ing and op is not None:
        m["margen_operativo_pct"] = op / ing * 100
    if ing and un is not None:
        m["margen_neto_pct"] = un / ing * 100
    fcf = fo - cx if fo is not None and cx is not None else None
    if fcf is not None:
        m["flujo_libre"] = fcf
    if pat and pat > 0 and deuda is not None:
        m["deuda_patrimonio"] = deuda / pat
    if acc and precio:
        cap = acc * precio
        m["capitalizacion"] = cap
        if un and un > 0:
            m["pe"] = cap / un
        if fcf and fcf > 0:
            m["p_fcf"] = cap / fcf
            m["rend_fcf_pct"] = fcf / cap * 100
    m.update({k: v for k, v in (("ingresos", ing), ("utilidad_neta", un)) if v is not None})
    return {k: (round(v, 4) if isinstance(v, float) and math.isfinite(v) else v) for k, v in m.items()}


def construir(contacto=None, anio=None):
    anio = anio or dt.date.today().year - 1
    emp = lista()
    pr = precios([e["sim"] for e in emp])
    fund = fundamentales([e["cik"] for e in emp], contacto, anio) if contacto else {}
    salida = []
    for e in emp:
        p = pr.get(e["sim"], {})
        f = fund.get(e["cik"], {})
        fila = {**e, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()}}
        if f:
            fila["fundamentales"] = metricas(f, p.get("precio"))
            fila["fuentes"] = {k: {"periodo": v["periodo"], "presentado": v["presentado"]} for k, v in f.items()}
        salida.append(fila)
    return {"version": 1, "actualizado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "anio_fiscal": anio, "empresas": len(salida), "con_precio": sum(1 for x in salida if "precio" in x),
            "con_fundamentales": sum(1 for x in salida if x.get("fundamentales")),
            "fuentes": {"lista": WIKI, "precios": "Yahoo Finance (diario)", "fundamentales": "SEC EDGAR XBRL frames"},
            "aviso": "Datos para estudiar empresas; un filtro no garantiza ganarle al índice.", "datos": salida}


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--salida", default=str(RAIZ / "salida" / "sp500.json"))
    a.add_argument("--anio", type=int)
    args = a.parse_args()
    t = time.time()
    r = construir(os.environ.get("SEC_CONTACT"), args.anio)
    Path(args.salida).write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{r['empresas']} empresas · {r['con_precio']} con precio · {r['con_fundamentales']} con fundamentales · {time.time() - t:.0f}s")
