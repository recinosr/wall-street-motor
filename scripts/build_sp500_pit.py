#!/usr/bin/env python3
"""Rebuild daily S&P 500 membership from the two public Wikipedia tables."""
from datetime import date, timedelta
import json
import re
from urllib.parse import quote
from urllib.request import Request, urlopen
from pathlib import Path

API = "https://en.wikipedia.org/w/api.php?"
UA = "wall-street-motor public historical research/1.0"
OUT = Path("datos/universo_pit/sp500_miembros.json")
START = date(2010, 1, 1)
END = date(2026, 11, 7)

def wiki(page):
    url="https://en.wikipedia.org/w/index.php?title="+quote(page)+"&action=raw"
    req=Request(url,headers={"User-Agent":UA})
    return urlopen(req,timeout=30).read().decode("utf8")

def current_members():
    text=wiki("List_of_S&P_500_companies")
    table=text.split('{| class="wikitable sortable mw-collapsible sticky-header" id="constituents"',1)[1].split("|}",1)[0]
    tickers=[]
    for row in table.split("|-"):
        m=re.search(r"\{\{\w+Symbol\|([^}|]+)",row)
        if m: tickers.append(m.group(1).strip().upper().replace(".","-"))
    if len(tickers)>=490: return set(tickers)
    raise RuntimeError(f"Could not parse current S&P 500 members: {len(tickers)}")

def parse_events(text):
    events={}
    section=text.split('{| class="wikitable sortable" id="changes"',1)[1]
    section=section.split("|}",1)[0]
    for block in section.split("|-"):
        cells=[]
        for line in block.splitlines():
            if line.lstrip().startswith("||"):
                cells.append(line.strip()[2:].strip())
            elif line.lstrip().startswith("|") and not line.lstrip().startswith("|-"):
                cells.append(line.strip()[1:].strip())
        if len(cells)<5: continue
        raw=re.sub(r"\[\[([^]|]+)(?:\|([^]]+))?\]\]",lambda m:m.group(2) or m.group(1),cells[0])
        try: d=date.fromisoformat(raw)
        except ValueError:
            try:
                from datetime import datetime
                d=datetime.strptime(raw.replace("&nbsp;"," "),"%B %d, %Y").date()
            except ValueError: continue
        def ticker(s):
            s=re.sub(r"<.*?>","",s).strip().upper().replace(".","-")
            return s if re.fullmatch(r"[A-Z0-9-]{1,10}",s) else ""
        added,removed=ticker(cells[1]),ticker(cells[3])
        events.setdefault(d,[]).append({"agregado":added or None,"eliminado":removed or None})
    return events

def main():
    members=current_members(); events=parse_events(wiki("Historical_components_of_the_S&P_500"))
    if len(members)<490: raise RuntimeError(f"unexpected current count: {len(members)}")
    days=[]; d=END
    while d>=START:
        if d.weekday()<5: days.append(d)
        d-=timedelta(days=1)
    out={}
    for day in days:
        out[day.isoformat()]=sorted(members)
        # Reverse the switch effective this day to get the prior trading day.
        for e in events.get(day,[]):
            if e["agregado"]: members.discard(e["agregado"])
            if e["eliminado"]: members.add(e["eliminado"])
    out=dict(sorted(out.items()))
    payload={"fuente":"Wikipedia: List of S&P 500 companies; Historical components of the S&P 500","url":"https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500","generado_utc":"2026-11-07","metodo":"Lista actual invertida por cada cambio efectivo fechado; días hábiles calendario, membresía post-cambio en fecha efectiva.","desde":START.isoformat(),"hasta":END.isoformat(),"eventos_procesados":sum(map(len,events.values())),"miembros_por_fecha":out}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(payload,separators=(",",":"))+"\n",encoding="utf8")
    print(f"{len(members)} miembros al {START}; {len(out)} fechas; {payload['eventos_procesados']} eventos")
if __name__=="__main__": main()
