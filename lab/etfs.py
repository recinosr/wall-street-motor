"""Catálogo de ETFs: qué empresas tienen, cuánto cobran, cuánto rindieron y qué le cuesta a alguien en Guatemala.

Uso: python -m lab.etfs [--salida salida/etfs.json]
Datos: yfinance (posiciones, sectores, gasto anual, activos) y precios ajustados de Yahoo.
"Costo para Guatemala" = gasto anual + retención estimada de dividendos:
  - ETF de EE. UU. que reparte: 30 % del rendimiento por dividendo (sin tratado).
  - ETF irlandés: ~15 % sobre la parte estadounidense del dividendo, ya dentro del fondo (estimado).
"""
import argparse
import datetime as dt
import json
import math
import time
from pathlib import Path

import numpy as np
import yfinance as yf

RAIZ = Path(__file__).resolve().parents[1]
# sim, nombre, grupo, domicilio, política (acumula/reparte), parte EE. UU. aproximada para el cálculo irlandés
CATALOGO = [
    ("VT", "Vanguard Total World Stock", "Mundo", "EE. UU.", "reparte", 0.62),
    ("VWRA.L", "Vanguard FTSE All-World (Acc, USD)", "Mundo", "Irlanda", "acumula", 0.62),
    ("VWRL.L", "Vanguard FTSE All-World (Dist)", "Mundo", "Irlanda", "reparte", 0.62),
    ("IWDA.L", "iShares Core MSCI World (Acc)", "Mundo desarrollado", "Irlanda", "acumula", 0.72),
    ("VOO", "Vanguard S&P 500", "EE. UU. grandes", "EE. UU.", "reparte", 1),
    ("SPY", "SPDR S&P 500", "EE. UU. grandes", "EE. UU.", "reparte", 1),
    ("IVV", "iShares Core S&P 500", "EE. UU. grandes", "EE. UU.", "reparte", 1),
    ("CSPX.L", "iShares Core S&P 500 (Acc, USD)", "EE. UU. grandes", "Irlanda", "acumula", 1),
    ("VUAA.L", "Vanguard S&P 500 (Acc, USD)", "EE. UU. grandes", "Irlanda", "acumula", 1),
    ("VTI", "Vanguard Total Stock Market", "EE. UU. total", "EE. UU.", "reparte", 1),
    ("QQQ", "Invesco QQQ (Nasdaq 100)", "Tecnología / Nasdaq", "EE. UU.", "reparte", 1),
    ("QQQM", "Invesco Nasdaq 100 (más barato)", "Tecnología / Nasdaq", "EE. UU.", "reparte", 1),
    ("EQQQ.L", "Invesco EQQQ Nasdaq-100 (Dist)", "Tecnología / Nasdaq", "Irlanda", "reparte", 1),
    ("VGT", "Vanguard Information Technology", "Tecnología / Nasdaq", "EE. UU.", "reparte", 1),
    ("SMH", "VanEck Semiconductores", "Tecnología / Nasdaq", "EE. UU.", "reparte", 0.8),
    ("SCHD", "Schwab US Dividend Equity", "Dividendos", "EE. UU.", "reparte", 1),
    ("VYM", "Vanguard High Dividend Yield", "Dividendos", "EE. UU.", "reparte", 1),
    ("JEPI", "JPMorgan Equity Premium Income", "Dividendos", "EE. UU.", "reparte", 1),
    ("VXUS", "Vanguard Total International (sin EE. UU.)", "Fuera de EE. UU.", "EE. UU.", "reparte", 0),
    ("VWO", "Vanguard Emerging Markets", "Emergentes", "EE. UU.", "reparte", 0),
    ("EIMI.L", "iShares Core MSCI EM IMI (Acc)", "Emergentes", "Irlanda", "acumula", 0),
    ("BND", "Vanguard Total Bond Market", "Bonos", "EE. UU.", "reparte", 1),
    ("AGG", "iShares Core US Aggregate Bond", "Bonos", "EE. UU.", "reparte", 1),
    ("GLD", "SPDR Gold Shares (oro)", "Oro", "EE. UU.", "no paga", 0),
    ("IAU", "iShares Gold Trust (oro, más barato)", "Oro", "EE. UU.", "no paga", 0),
    ("IBIT", "iShares Bitcoin Trust", "Bitcoin", "EE. UU.", "no paga", 0),
    ("ARKK", "ARK Innovation", "Temático", "EE. UU.", "reparte", 1),
    ("DIA", "SPDR Dow Jones Industrial", "EE. UU. grandes", "EE. UU.", "reparte", 1),
]
CATALOGO += [('ITA', 'ITA ? Defensa', 'Defensa', 'EE. UU.', 'reparte', 1), ('XAR', 'XAR ? Defensa', 'Defensa', 'EE. UU.', 'reparte', 1), ('PPA', 'PPA ? Defensa', 'Defensa', 'EE. UU.', 'reparte', 1), ('SHLD', 'SHLD ? Defensa', 'Defensa', 'EE. UU.', 'reparte', 1), ('CIBR', 'CIBR ? Ciberseguridad', 'Ciberseguridad', 'EE. UU.', 'reparte', 1), ('HACK', 'HACK ? Ciberseguridad', 'Ciberseguridad', 'EE. UU.', 'reparte', 1), ('BOTZ', 'BOTZ ? IA y robótica', 'IA y robótica', 'EE. UU.', 'reparte', 1), ('AIQ', 'AIQ ? IA y robótica', 'IA y robótica', 'EE. UU.', 'reparte', 1), ('XLV', 'XLV ? Salud', 'Salud', 'EE. UU.', 'reparte', 1), ('XLE', 'XLE ? Energía', 'Energía', 'EE. UU.', 'reparte', 1), ('XLF', 'XLF ? Finanzas', 'Finanzas', 'EE. UU.', 'reparte', 1), ('IWM', 'IWM ? Small caps', 'Small caps', 'EE. UU.', 'reparte', 1), ('VB', 'VB ? Small caps', 'Small caps', 'EE. UU.', 'reparte', 1), ('VIG', 'VIG ? Dividendos crecientes', 'Dividendos crecientes', 'EE. UU.', 'reparte', 1), ('DGRO', 'DGRO ? Dividendos crecientes', 'Dividendos crecientes', 'EE. UU.', 'reparte', 1), ('URA', 'URA ? Uranio', 'Uranio', 'EE. UU.', 'reparte', 1), ('EWZ', 'EWZ ? Brasil', 'Brasil', 'EE. UU.', 'reparte', 1), ('EWW', 'EWW ? México', 'México', 'EE. UU.', 'reparte', 1), ('INDA', 'INDA ? India', 'India', 'EE. UU.', 'reparte', 1), ('FXI', 'FXI ? China', 'China', 'EE. UU.', 'reparte', 1), ('EWJ', 'EWJ ? Japón', 'Japón', 'EE. UU.', 'reparte', 1), ('VNQ', 'VNQ ? Inmobiliario', 'Inmobiliario', 'EE. UU.', 'reparte', 1), ('SHY', 'SHY ? Bonos cortos', 'Bonos cortos', 'EE. UU.', 'reparte', 1), ('BIL', 'BIL ? Bonos cortos', 'Bonos cortos', 'EE. UU.', 'reparte', 1), ('GDX', 'GDX ? Oro minero', 'Oro minero', 'EE. UU.', 'reparte', 1), ('ETHA', 'ETHA ? Ethereum', 'Ethereum', 'EE. UU.', 'no paga', 1)]

# Gasto anual tomado de la ficha del emisor cuando la fuente automática no lo trae.
TER_FICHA = {"VWRA.L": (0.14, "Vanguard, ficha 31-jul-2026 (bajó de 0.19 % el 28-jul-2026)"),
             "VWRL.L": (0.14, "Vanguard, misma clase de fondo; baja del 28-jul-2026"),
             "VUAA.L": (0.07, "Vanguard / etfstream")}
# Rendimiento por dividendo aproximado de lo que hay dentro, para estimar la retención de los fondos irlandeses.
DIV_SUBYACENTE = {"Mundo": 1.6, "Mundo desarrollado": 1.5, "EE. UU. grandes": 1.1, "Tecnología / Nasdaq": 0.5, "Emergentes": 2.5}


def _num(x):
    try:
        x = float(x)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def rendimientos(hist):
    c = hist["Close"].dropna()
    if len(c) < 30:
        return {}
    fin = c.index[-1]
    out = {"precio": round(float(c.iloc[-1]), 4), "fecha": fin.date().isoformat(), "desde": c.index[0].date().isoformat()}
    for nombre, anios in (("1a", 1), ("3a", 3), ("5a", 5), ("10a", 10)):
        ini = c[c.index <= fin - dt.timedelta(days=int(365.25 * anios))]
        if len(ini):
            total = c.iloc[-1] / ini.iloc[-1] - 1
            out[f"ret_{nombre}_pct"] = round(float(total * 100), 2)
            out[f"anual_{nombre}_pct"] = round(float(((1 + total) ** (1 / anios) - 1) * 100), 2)
    dd = (c / c.cummax() - 1).min()
    out["peor_caida_pct"] = round(float(dd * 100), 1)
    r = c.pct_change().dropna()
    out["volatilidad_anual_pct"] = round(float(r.std() * np.sqrt(252) * 100), 1)
    return out


def ficha(sim, nombre, grupo, dom, pol, parte_us):
    t = yf.Ticker(sim)
    f = {"sim": sim, "nombre": nombre, "grupo": grupo, "domicilio": dom, "dividendos": pol}
    try:
        f.update(rendimientos(t.history(period="max", auto_adjust=True)))
    except Exception as e:
        f["error_precios"] = str(e)[:80]
    info = {}
    try:
        info = t.info or {}
    except Exception:
        pass
    rend_div = _num(info.get("yield") or info.get("trailingAnnualDividendYield"))
    f["rend_dividendo_pct"] = round(rend_div * 100, 2) if rend_div is not None else None
    try:
        fd = t.funds_data
        ops = fd.fund_operations
        if ops is not None and len(ops):
            col = ops.iloc[:, 0].to_dict()
            ter = _num(col.get("Annual Report Expense Ratio"))
            f["gasto_anual_pct"] = round(ter * 100, 3) if ter is not None else None
            f["rotacion"] = _num(col.get("Annual Holdings Turnover"))
            aum = _num(col.get("Total Net Assets"))
            f["activos_millones"] = round(aum, 0) if aum else None
        th = fd.top_holdings
        if th is not None and len(th):
            f["top"] = [{"sim": str(i), "nombre": str(r["Name"]), "peso_pct": round(float(r["Holding Percent"]) * 100, 2)}
                        for i, r in th.head(10).iterrows()]
            f["peso_top10_pct"] = round(sum(x["peso_pct"] for x in f["top"]), 1)
        sw = fd.sector_weightings
        if sw:
            f["sectores"] = {k: round(float(v) * 100, 1) for k, v in sorted(sw.items(), key=lambda kv: -kv[1]) if v}
        f["categoria"] = (fd.fund_overview or {}).get("categoryName")
    except Exception:
        pass
    if f.get("gasto_anual_pct") is None and sim in TER_FICHA:
        f["gasto_anual_pct"], f["fuente_gasto"] = TER_FICHA[sim]
    # Costo estimado para un inversionista en Guatemala (puntos porcentuales por año)
    ter = f.get("gasto_anual_pct")
    rd = f.get("rend_dividendo_pct")
    if dom == "EE. UU." and pol == "reparte":
        ret = rd * 0.30 if rd is not None else None
        nota = "EE. UU. retiene 30 % de cada dividendo (Guatemala no tiene tratado)."
    elif dom == "Irlanda":
        ret = DIV_SUBYACENTE.get(grupo, rd or 1.5) * parte_us * 0.15
        nota = "El fondo irlandés paga ~15 % sobre dividendos de EE. UU. por tratado; a ti no te retienen 30 %."
    else:
        ret = 0.0
        nota = "No reparte dividendos."
    f["retencion_estimada_pct"] = round(ret, 2) if ret is not None else None
    f["costo_total_guatemala_pct"] = round(ter + ret, 2) if ter is not None and ret is not None else None
    f["nota_costo"] = nota + " Costos parciales: faltan fondeo, cambio, intermediario, retiro e impuestos locales; disponibilidad desde Guatemala no verificada." + ("" if ter is not None else " Gasto anual no disponible en la fuente: revisa la ficha del emisor.")
    return f


def construir():
    fichas = []
    previous_path=RAIZ/("resultados" if (RAIZ/"resultados").is_dir() else "salida")/"etfs.json"
    previous=json.loads(previous_path.read_text(encoding='utf8')) if previous_path.exists() else {}
    saved={x['sim']:x for x in previous.get('etfs',[])}
    for fila in CATALOGO:
        try:
            item=ficha(*fila)
            if not item.get('top') and saved.get(fila[0],{}).get('top'):
                old=saved[fila[0]]
                for key in ('top','sectores','peso_top10_pct','gasto_anual_pct','rend_dividendo_pct','retencion_estimada_pct','costo_total_guatemala_pct','nota_costo'):
                    if key in old:item[key]=old[key]
                item['posiciones_recuperadas_de']=old.get('posiciones_recuperadas_de',previous.get('actualizado'))
                item['nota_cobertura']='La fuente no devolvió posiciones nuevas; última captura conservada, top10 parcial.'
            item.pop("precio", None)
            fichas.append(item)
        except Exception as e:
            fichas.append({"sim": fila[0], "nombre": fila[1], "grupo": fila[2], "error": str(e)[:100]})
        time.sleep(0.4)
    return {"version": 1, "actualizado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "fuente": "Yahoo Finance vía yfinance (posiciones, sectores, gasto) y precios ajustados con dividendos",
            "aviso": "Retornos pasados con dividendos reinvertidos, antes de impuestos personales. El costo para Guatemala es una estimación.",
            "etfs": fichas}


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--salida", default=str(RAIZ / "salida" / "etfs.json"))
    args = a.parse_args()
    t0 = time.time()
    r = construir()
    from lab.universo import inverse
    Path("resultados/en_que_etfs.json").write_text(json.dumps(inverse(r), ensure_ascii=False), encoding="utf8")
    Path(args.salida).write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    ok = sum(1 for x in r["etfs"] if x.get("top"))
    print(f"{len(r['etfs'])} ETFs · {ok} con posiciones · {time.time() - t0:.0f}s")
