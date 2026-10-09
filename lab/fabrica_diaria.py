"""102 reglas diarias declaradas, evaluación cronológica y reserva cerrada por BH.

Lee solo velas públicas BTC/ETH. Publica métricas, nunca precios crudos.
No ajusta variantes después de mirar validación o reserva.
"""
import hashlib
import json
import random
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from .fabrica import benjamini_hochberg

ROOT = Path(__file__).resolve().parents[1]
START = "2021-01-01"
TRAIN_END = "2023-01-01"
RESERVE_START = "2025-04-01"
COST = .001


def rules(root=ROOT):
    def template(name):
        return json.loads((root / "ideas" / name).read_text(encoding="utf-8"))
    trend = template("tendencia_diaria.json")
    momentum = template("momentum_diario.json")
    candles = template("velas_diarias.json")
    season = template("estacionalidad_diaria.json")
    for asset in ("BTC", "ETH"):
        for n in trend["meses"]:
            yield {"family": trend["id"], "asset": asset, "n": n}
        for n in momentum["dias"]:
            yield {"family": momentum["id"], "asset": asset, "n": n}
        for pattern in candles["patrones"]:
            for horizon in candles["horizontes"]:
                yield {"family": candles["id"], "asset": asset, "pattern": pattern, "horizon": horizon}
        for weekday in season["dias_semana"]:
            yield {"family": "dia_semana", "asset": asset, "weekday": weekday}
        for last in season["dias_fin_mes"]:
            yield {"family": "fin_mes", "asset": asset, "last": last}


def fetch_daily(asset, begin, end):
    """[begin,end) en páginas de 190 días; no persiste la serie."""
    result = {}
    day = date.fromisoformat(begin)
    final = date.fromisoformat(end)
    while day < final:
        stop = min(day + timedelta(days=190), final)
        params = urlencode({"granularity": 86400, "start": day.isoformat()+"T00:00:00Z",
                            "end": stop.isoformat()+"T00:00:00Z"})
        req = Request(f"https://api.exchange.coinbase.com/products/{asset}-USD/candles?{params}",
                      headers={"User-Agent": "WallStreetMotorResearch/1"})
        with urlopen(req, timeout=20) as response:
            rows = json.load(response)
        if not isinstance(rows, list):
            raise ValueError("Coinbase no devolvió velas diarias")
        for row in rows:
            if len(row) != 6:
                raise ValueError("Vela diaria inválida")
            stamp, low, high, opening, close, volume = row
            d = datetime.fromtimestamp(stamp, timezone.utc).date()
            if day <= d < stop and min(low, high, opening, close) > 0:
                result[d.isoformat()] = (opening, high, low, close, volume)
        day = stop
    df = pd.DataFrame.from_dict(result, orient="index", columns=["open", "high", "low", "close", "volume"])
    if df.empty:
        raise LookupError("Sin velas diarias")
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


def patterns(df):
    """Port exacto de las nueve definiciones privadas; no reelige umbrales."""
    o,h,l,c = (df[k] for k in ("open", "high", "low", "close"))
    body = (c-o).abs()
    spread = (h-l).replace(0, np.nan)
    upper, lower = h-np.maximum(o,c), np.minimum(o,c)-l
    down5, up5 = c<c.shift(5), c>c.shift(5)
    mid = (o.shift(2)+c.shift(2))/2
    return {
        "doji": body<=.1*spread,
        "martillo": (lower>=2*body)&(upper<=.3*body+1e-9)&down5,
        "estrella_fugaz": (upper>=2*body)&(lower<=.3*body+1e-9)&up5,
        "envolvente_alcista": (c.shift(1)<o.shift(1))&(c>o)&(o<=c.shift(1))&(c>=o.shift(1))&down5,
        "envolvente_bajista": (c.shift(1)>o.shift(1))&(c<o)&(o>=c.shift(1))&(c<=o.shift(1))&up5,
        "estrella_manana": (c.shift(2)<o.shift(2))&(body.shift(1)<.3*body.shift(2))&(c>o)&(c>mid)&down5.shift(1).fillna(False),
        "estrella_atardecer": (c.shift(2)>o.shift(2))&(body.shift(1)<.3*body.shift(2))&(c<o)&(c<mid)&up5.shift(1).fillna(False),
        "tres_soldados_blancos": (c>o)&(c.shift(1)>o.shift(1))&(c.shift(2)>o.shift(2))&(c>c.shift(1))&(c.shift(1)>c.shift(2)),
        "tres_cuervos_negros": (c<o)&(c.shift(1)<o.shift(1))&(c.shift(2)<o.shift(2))&(c<c.shift(1))&(c.shift(1)<c.shift(2)),
    }


def signal(rule, df, cache=None):
    c = df.close
    family = rule["family"]
    if family == "tendencia_mensual":
        # Promedio que incluye el cierre conocido del mes, igual que la regla A.
        months = c.resample("MS").last()
        decision = months > months.rolling(rule["n"], min_periods=rule["n"]).mean()
        # El cierre mensual solo es conocido desde el último día de ese mes.
        month_ends = c.groupby(c.index.strftime("%Y-%m")).tail(1)
        values = pd.Series([None]*len(df), index=df.index, dtype=object)
        for stamp, close in month_ends.items():
            if (stamp + pd.Timedelta(days=1)).month != stamp.month:
                values.loc[stamp] = bool(decision.loc[stamp.strftime("%Y-%m-01")])
        return values.ffill().fillna(False).astype(bool)
    if family == "momentum_diario":
        return (c > c.shift(rule["n"])).fillna(False)
    if family == "velas_japonesas":
        return (cache or patterns(df))[rule["pattern"]].fillna(False)
    target = df.index + pd.Timedelta(days=1)
    if family == "dia_semana":
        return pd.Series(target.weekday == rule["weekday"], index=df.index)
    remaining = (target + pd.offsets.MonthEnd(0)).normalize() - target.normalize()
    return pd.Series(remaining.days < rule["last"], index=df.index)


def _valid(df, i, h):
    # Coinbase opera todos los días. No rellenar huecos ni saltarlos.
    return i+h < len(df) and (df.index[i+h]-df.index[i]).days == h


def _schedule(rule, df, signal_values):
    family = rule["family"]
    if family in ("tendencia_mensual", "momentum_diario"):
        return None
    horizon = rule.get("horizon", 1)
    result = []
    last_exit = -1
    for i in range(len(df)-horizon):
        if i+1 <= last_exit or not bool(signal_values.iat[i]) or not _valid(df, i, horizon):
            continue
        result.append((i+1, i+horizon))
        last_exit = i+horizon
    return result


def _returns(df, positions, events=None):
    """Capital diario marcado al cierre; costo solo al cambiar de posición."""
    n = len(df)
    out = np.zeros(n, dtype=float)
    close, opening = df.close.to_numpy(float), df.open.to_numpy(float)
    was = False
    for i in range(1, n):
        held = bool(positions[i])
        if held and was:
            gross = close[i]/close[i-1]
        elif held:
            gross = close[i]/opening[i]*(1-COST)
        elif was:
            gross = opening[i]/close[i-1]*(1-COST)
        else:
            gross = 1.
        if events is not None and i in events:
            gross *= (1-COST)
        out[i] = gross-1
        was = held and not (events is not None and i in events)
    return out


def _random_events(df, events, rule_id):
    if not events:
        return []
    horizon = events[0][1]-events[0][0]+1
    possible = [i for i in range(1, len(df)-horizon+1) if _valid(df, i-1, horizon)]
    rng = random.Random(int(rule_id[:12], 16))
    for _ in range(50):
        rng.shuffle(possible)
        chosen = []
        for start in possible:
            if all(start > end or start+horizon-1 < begin for begin, end in chosen):
                chosen.append((start, start+horizon-1))
            if len(chosen) == len(events):
                return sorted(chosen)
    return []


def _random_positions(held, rule_id):
    """Permuta duraciones de rachas; preserva exposición y cambios."""
    if not len(held):
        return held
    runs = []
    start = 0
    for i in range(1, len(held)+1):
        if i == len(held) or held[i] != held[start]:
            runs.append((bool(held[start]), i-start))
            start = i
    rng = random.Random(int(rule_id[:12], 16))
    lengths = {state: [n for value,n in runs if value == state] for state in (False, True)}
    for group in lengths.values():
        rng.shuffle(group)
    result = np.zeros(len(held), dtype=bool)
    cursor = 0
    for state, _ in runs:
        n = lengths[state].pop()
        result[cursor:cursor+n] = state
        cursor += n
    return result


def _event_returns(df, events):
    held = np.zeros(len(df), dtype=bool)
    exits = set()
    for start, end in events:
        held[start:end+1] = True
        exits.add(end)
    return _returns(df, held, exits)


def score(rule, df):
    """Meses en orden. La regla queda fija; costos y controles usan mismos días."""
    if len(df) < max(rule.get("n", 0), 15)+20:
        return {"months": [], "operations": 0, "reason": "insufficient_data"}
    if any(delta.days != 1 for delta in df.index.to_series().diff().dropna()):
        return {"months": [], "operations": 0, "reason": "missing_daily_candles"}
    rid = hashlib.sha256(json.dumps(rule, sort_keys=True).encode()).hexdigest()[:16]
    s = signal(rule, df)
    starts = []
    if rule["family"] in ("tendencia_mensual", "momentum_diario"):
        held = np.r_[False, s.to_numpy(bool)[:-1]]
        net = _returns(df, held)
        starts = list(np.where(np.diff(held.astype(int)) != 0)[0]+1)
        operations = len(starts)
        random_held = _random_positions(held, rid)
        control = _returns(df, random_held)
        if held[-1]:
            net[-1] = (1+net[-1])*(1-COST)-1
        if random_held[-1]:
            control[-1] = (1+control[-1])*(1-COST)-1
    else:
        events = _schedule(rule, df, s)
        starts = [a for a,b in events]
        net = _event_returns(df, events)
        operations = len(events)
        random_events = _random_events(df, events, rid)
        if events and len(random_events) != len(events):
            return {"months": [], "operations": operations, "reason": "random_frequency_mismatch"}
        control = _event_returns(df, random_events)
    hold = np.zeros(len(df), dtype=float)
    hold[1:] = df.close.to_numpy(float)[1:]/df.close.to_numpy(float)[:-1]-1
    if len(hold)>1:
        hold[1] = (1+hold[1])*(1-COST)-1
        hold[-1] = (1+hold[-1])*(1-COST)-1
    months = []
    for period, group in df.groupby(df.index.strftime("%Y-%m")):
        indices = df.index.get_indexer(group.index)
        compound = lambda values: float(np.prod(1+values[indices])-1)
        months.append({"month": str(period), "net": compound(net), "random": compound(control),
                       "hold": compound(hold), "operations": sum(i in indices for i in starts)})
    return {"months": months, "operations": operations, "reason": "measured"}


def p_bootstrap(months, seed, samples=1999):
    values = np.array([m["net"]-max(m["random"], m["hold"]) for m in months], dtype=float)
    if len(values) < 12 or values.mean() <= 0:
        return 1.
    centered = values-values.mean()
    rng = np.random.default_rng(seed)
    draws = centered[rng.integers(0, len(values), (samples, len(values)))].mean(axis=1)
    return float((np.count_nonzero(draws >= values.mean())+1)/(samples+1))


def compound(months, key):
    return float(np.prod([1+m[key] for m in months])-1) if months else 0.


def run(fetcher=fetch_daily, root=ROOT, today=None):
    today = today or datetime.now(timezone.utc).date()
    plan = list(rules(root))
    if len(plan) != 102:
        raise ValueError("El universo registrado debe contener exactamente 102 pruebas")
    screen = {a: fetcher(a, START, RESERVE_START) for a in ("BTC", "ETH")}
    registry = {}
    for rule in plan:
        rid = hashlib.sha256(json.dumps(rule, sort_keys=True).encode()).hexdigest()[:16]
        df = screen[rule["asset"]]
        measured = score(rule, df)
        train = [m for m in measured["months"] if m["month"] < TRAIN_END[:7]]
        valid = [m for m in measured["months"] if m["month"] >= TRAIN_END[:7]]
        p = p_bootstrap(valid, int(rid, 16))
        registry[rid] = {"rule": rule, "train": {"months": len(train), "net": compound(train, "net")},
                         "validation": {"months": len(valid), "operations": sum(m["operations"] for m in valid),
                                        "net": compound(valid, "net"),
                                        "random": compound(valid, "random"),
                                        "hold": compound(valid, "hold"),
                                        "reason": measured["reason"]}, "p": p}
    accepted = benjamini_hochberg({k: v["p"] for k,v in registry.items()})
    # Reserva aislada: esta llamada no se ejecuta si no pasa BH completo.
    if accepted:
        reserve = {a: fetcher(a, RESERVE_START, today.isoformat()) for a in ("BTC", "ETH")}
        for rid in accepted:
            row = registry[rid]
            asset = row["rule"]["asset"]
            warm = screen[asset].iloc[-370:]
            combined = pd.concat([warm, reserve[asset]])
            result = score(row["rule"], combined)
            final = [m for m in result["months"] if m["month"] >= RESERVE_START[:7]]
            row["reserved"] = {"months": len(final), "operations": sum(m["operations"] for m in final),
                               "net": compound(final, "net"),
                               "random": compound(final, "random"),
                               "hold": compound(final, "hold")}
    report = {"version": 1, "as_of": today.isoformat(), "source": "Coinbase Exchange daily public BTC/ETH",
              "train": [START, TRAIN_END], "validation": [TRAIN_END, RESERVE_START],
              "reserved_from": RESERVE_START, "cost_per_side": COST,
              "coverage": {a: {"first": df.index[0].date().isoformat(), "last": df.index[-1].date().isoformat(),
                                "daily_candles": len(df)} for a,df in screen.items()},
              "method": "102 variantes predefinidas; meses cronológicos; control aleatorio y mantener; bootstrap unilateral por mes; BH q=0.05 sobre las 102 pruebas antes de abrir la reserva",
              "tested": len(registry), "uncorrected": sum(v["p"]<.05 for v in registry.values()),
              "bh_passed": len(accepted), "reasons": dict(Counter(v["validation"]["reason"] for v in registry.values())),
              "registry": registry}
    path = root / "resultados/fabrica_diaria.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, separators=(",", ":"))+"\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({k:result[k] for k in ("tested", "uncorrected", "bh_passed", "reasons")}, ensure_ascii=False))
