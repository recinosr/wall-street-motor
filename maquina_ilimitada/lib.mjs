// Biblioteca de la máquina del tiempo ilimitada. Sin llaves; red solo a Yahoo (preparar.mjs) y Ollama local.
// Regla de oro: los insumos de la fecha D usan SOLO cierres con fecha < D.
import fs from 'node:fs';
import zlib from 'node:zlib';

export const num = x => typeof x === 'number' && Number.isFinite(x);
export const fmt = ms => new Date(ms).toISOString().slice(0, 10);
export const sumarDias = (d, n) => fmt(Date.parse(d + 'T00:00:00Z') + n * 86400000);
export const leerJSON = (p, def = null) => { try { const b = fs.readFileSync(p); return JSON.parse((p.endsWith('.gz') ? zlib.gunzipSync(b) : b).toString('utf8')); } catch { return def; } };
export const guardarJSON = (p, x) => { const s = JSON.stringify(x); fs.writeFileSync(p, p.endsWith('.gz') ? zlib.gzipSync(s) : s + '\n'); };
export const leerJSONL = p => { try { const b = fs.readFileSync(p); const t = (p.endsWith('.gz') ? zlib.gunzipSync(b) : b).toString('utf8'); return t.split('\n').filter(Boolean).map(JSON.parse); } catch { return []; } };

// ---- Series: {ticker: {f:[fechas], p:[precios]}} o [{fecha,precio}] ----
export function aFilas(s) { return s && s.f ? s.f.map((f, i) => ({ fecha: f, precio: s.p[i] })) : (s || []); }
export function cortarSerie(serie, dia) { return serie.filter(x => x.fecha < dia && num(x.precio)).sort((a, b) => a.fecha.localeCompare(b.fecha)); }

// ---- Rasgos (idénticos a scripts/analista/datos.mjs del repo principal) ----
const ret = (a, n) => a.length > n ? a.at(-1) / a.at(-1 - n) - 1 : null;
export function rasgos(serie) {
  const p = serie.map(x => x.precio), v = p.at(-1), retornos = p.slice(1).map((x, i) => Math.log(x / p[i]));
  const ult = retornos.slice(-20), media = ult.reduce((a, b) => a + b, 0) / ult.length;
  const vol = Math.sqrt(252 * ult.reduce((a, b) => a + (b - media) ** 2, 0) / Math.max(1, ult.length - 1));
  const m200 = p.slice(-200).reduce((a, b) => a + b, 0) / Math.min(200, p.length);
  const sd = Math.sqrt(p.slice(-200).reduce((a, b) => a + (b - m200) ** 2, 0) / Math.min(200, p.length));
  const cambios = p.slice(-15).map((x, i, a) => i ? x - a[i - 1] : 0).slice(1);
  const gain = cambios.reduce((a, b) => a + Math.max(0, b), 0) / 14, loss = cambios.reduce((a, b) => a + Math.max(0, -b), 0) / 14;
  return {
    precio: Number(v.toFixed(4)), fecha_precio: serie.at(-1)?.fecha,
    r_1s: ret(p, 5), r_1m: ret(p, 21), r_3m: ret(p, 63), r_12m: ret(p, 252),
    vol20: ult.length >= 20 ? vol : null,
    dist_max52: p.length >= 252 ? v / Math.max(...p.slice(-252)) - 1 : null,
    z200: p.length >= 200 && sd ? (v - m200) / sd : null,
    rsi14: gain + loss ? 100 * gain / (gain + loss) : null
  };
}

// ---- Cribado de acciones (igual que cribarAcciones del principal, calculado de las series) ----
export function fichaCribado(sim, serie) {
  const p = serie.map(x => x.precio), v = p.at(-1);
  return { sim, precio: v, cambio_dia_pct: p.length > 1 ? 100 * (v / p.at(-2) - 1) : 0, max_52s: Math.max(...p.slice(-252)), min_52s: Math.min(...p.slice(-252)), momentum_12_1_pct: p.length > 252 ? 100 * (p.at(-22) / p.at(-253) - 1) : 0 };
}
export function cribarAcciones(acciones, sp500, max = 30) {
  const info = new Map(sp500.map(e => [e.sim, e]));
  const puntos = a => {
    const e = info.get(a.ticker_precio); if (!e || !Number.isFinite(e.precio)) return -1;
    const alto = e.max_52s ? e.precio / e.max_52s : 0, bajo = e.min_52s ? e.precio / e.min_52s : 9;
    return Math.abs(e.cambio_dia_pct || 0) / 2 + (alto >= .97 ? 2 : 0) + (bajo <= 1.05 ? 2 : 0) + (Math.abs(e.momentum_12_1_pct || 0) > 40 ? 1 : 0);
  };
  const temas = acciones.filter(a => a.fuente_cribado === 'tema');
  const resto = acciones.filter(a => a.fuente_cribado !== 'tema').map(a => [a, puntos(a)]).filter(([, p]) => p >= 0).sort((x, y) => y[1] - x[1]).slice(0, max).map(([a]) => a);
  return [...resto, ...temas];
}

// ---- Insumos de una fecha, sin mirar el futuro ----
export function insumosDeFecha(dia, universo, series) {
  const prev = new Map(universo.map(f => [f.ticker, cortarSerie(aFilas(series[f.ticker]), dia)]));
  const acciones = universo.filter(f => f.clase === 'accion');
  const sp = acciones.map(f => [f, prev.get(f.ticker)]).filter(([, s]) => s.length >= 25).map(([f, s]) => fichaCribado(f.ticker_precio, s));
  const seleccion = [...universo.filter(f => f.clase !== 'accion'), ...cribarAcciones(acciones, sp)];
  const instrumentos = seleccion.filter(f => prev.get(f.ticker)?.length >= 25).map(f => ({ ...f, ...rasgos(prev.get(f.ticker)), noticias: [] }));
  const vt = cortarSerie(aFilas(series.VT), dia);
  return { version: 1, simulada: true, fecha_decision: dia, instrumentos, referencia_vt: vt.length >= 25 ? rasgos(vt) : null };
}

// ---- Candidatos (como candidatos() de llamar.mjs, sin noticias) y reparto en lotes ----
const hash = s => { let h = 2166136261; for (const c of s) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0; };
export function candidatos(rows, dia, max = 40) {
  const grupos = new Map();
  for (const x of rows.filter(x => x.precio && x.r_1m !== null)) {
    const clase = claseDe(x.clase);
    const puntos = (Math.abs(x.r_1m || 0) > .08 ? 2 : 0) + (x.rsi14 < 30 || x.rsi14 > 70 ? 2 : 0) + (Math.abs(x.z200 || 0) > .15 ? 1 : 0);
    if (!grupos.has(clase)) grupos.set(clase, []);
    grupos.get(clase).push({ ...x, puntos, _h: hash(dia + x.ticker) });
  }
  for (const a of grupos.values()) a.sort((x, y) => y.puntos - x.puntos || x._h - y._h);
  const out = [], orden = ['accion', 'ETF', 'cripto'];
  while (out.length < max && orden.some(k => grupos.get(k)?.length)) for (const k of orden) if (out.length < max && grupos.get(k)?.length) out.push(grupos.get(k).shift());
  return out;
}
export function lotes(cand, nLotes) { const L = Array.from({ length: nLotes }, () => []); cand.forEach((c, i) => L[i % nLotes].push(c)); return L.filter(l => l.length); }

// ---- Prompt y validación (iguales a llamar.mjs / comun.mjs, sin titulares) ----
export function armarPrompt(dia, cand, cupo) {
  const r4 = v => (typeof v === 'number' && Number.isFinite(v)) ? Number(v.toFixed(4)) : null; // redondeo solo de presentación; precio_ref va exacto
  const contexto = cand.map(x => ({ activo: x.ticker, precio_ref: x.precio, fecha_precio: x.fecha_precio, referencia: x.referencia, rasgos: { semana: r4(x.r_1s), mes: r4(x.r_1m), trimestre: r4(x.r_3m), ano: r4(x.r_12m), volatilidad: r4(x.vol20), z200: r4(x.z200), rsi14: r4(x.rsi14) }, titulares: [] }));
  return `Sos Vita analista en un experimento histórico simulado. Fecha de decisión ${dia}. Emití exactamente ${cupo} hipótesis verificables, cada una de un activo distinto de la lista, con plazos variados. Solo JSON {"llamadas":[{"activo":"ticker exacto","direccion":"sube|baja","horizonte_dias":1|5|21|63,"probabilidad":0.50-0.85,"precio_ref":número exacto entregado,"razon":"máximo 3 frases en español, causa concreta y duda","fuentes":[],"invalidacion":"dato que contradice la hipótesis","tipo":"tendencia|valuacion|evento"}]}. No inventes precios ni uses conocimientos posteriores a la fecha. No hay titulares: fuentes va vacío. Si los datos no sostienen convicción, usa 0.50. Datos disponibles: ${JSON.stringify({ contexto, eventos: [], clima: null })}`;
}
export function validarLlamada(raw, insumo, abiertas = []) {
  if (!raw || !['sube', 'baja'].includes(raw.direccion) || ![1, 5, 21, 63].includes(raw.horizonte_dias) || !num(raw.probabilidad) || raw.probabilidad < .5 || raw.probabilidad > .85) throw Error('Dirección, plazo o probabilidad inválidos');
  if (!insumo || !num(insumo.precio) || raw.precio_ref !== insumo.precio) throw Error('Precio de referencia no coincide');
  if (!String(raw.razon || '').trim() || !String(raw.invalidacion || '').trim()) throw Error('Falta razón o invalidación');
  if (abiertas.some(a => a.activo === insumo.ticker && a.horizonte_dias === raw.horizonte_dias)) throw Error('Llamada duplicada');
  const tipo = ['evento', 'tendencia', 'valuacion'].includes(raw.tipo) ? raw.tipo : 'tendencia';
  return { ...raw, activo: insumo.ticker, ticker_precio: insumo.ticker_precio, precio_ref: insumo.precio, referencia: insumo.referencia, razon: String(raw.razon).trim().split(/(?<=[.!?])\s+/).slice(0, 3).join(' ').slice(0, 500), invalidacion: String(raw.invalidacion).trim().slice(0, 300), fuentes: [], tipo };
}

// ---- Calificación (misma fórmula que calificar() de comun.mjs) ----
export function primerCierreDesde(serie, objetivo) { return serie.find(x => x.fecha >= objetivo && num(x.precio)); }
export function claveSerieRef(l) { return l.referencia === 'VT' ? 'VT' : l.referencia === 'BTC' ? 'BTC' : null; }
export function calificarLlamada(l, series) {
  const obj = sumarDias(l.fecha_decision, l.horizonte_dias);
  const x = primerCierreDesde(aFilas(series[l.activo]), obj);
  if (!x) return null;
  const R = claveSerieRef(l); let pRef = 1;
  if (R) { const y = primerCierreDesde(aFilas(series[R]), obj); if (!y) return null; pRef = y.precio; }
  const r = x.precio / l.precio_ref - 1, br = pRef / l.precio_referencia - 1, acierto = l.direccion === 'sube' ? r > 0 : r < 0;
  return { acierto, retorno: r, retorno_referencia: br, exceso: (r - br) * (l.direccion === 'sube' ? 1 : -1), brier: (l.probabilidad - (acierto ? 1 : 0)) ** 2, fecha_resultado: x.fecha };
}
// Precio de la referencia al cierre previo a la fecha de decisión
export function precioReferencia(referencia, series, dia) {
  if (referencia === 'EFECTIVO') return 1;
  const s = cortarSerie(aFilas(series[referencia === 'VT' ? 'VT' : 'BTC']), dia);
  return s.length ? Number(s.at(-1).precio.toFixed(4)) : null;
}

// ---- Estadística ----
export function wilson(k, n) { if (!n) return null; const z = 1.9599639845, p = k / n, d = 1 + z * z / n, c = (p + z * z / (2 * n)) / d, e = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d; return [c - e, c + e]; }
// McNemar exacto (binomial bilateral sobre discordantes), estable para n grande
export function mcnemar(a, b) {
  const n = a + b; if (!n) return 1; const lim = Math.min(a, b);
  let s = 0, lc = 0;
  for (let i = 0; i <= lim; i++) { if (i > 0) lc += Math.log((n - i + 1) / i); s += Math.exp(lc + n * Math.log(.5)); }
  return Math.min(1, 2 * s);
}
const prom = (a, k) => a.length ? a.reduce((s, x) => s + x[k], 0) / a.length : null;
function rng(seed) { let s = seed >>> 0; return () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; }; }
// IC 95 % de (pct Vita - pct base) remuestreando días completos (respeta la correlación dentro del día)
export function bootstrapDias(pares, B = 1000) {
  const porDia = new Map();
  for (const [v, y] of pares) { const d = v.fecha_decision; if (!porDia.has(d)) porDia.set(d, [0, 0, 0]); const t = porDia.get(d); t[0] += v.acierto ? 1 : 0; t[1] += y.acierto ? 1 : 0; t[2]++; }
  const dias = [...porDia.values()]; if (dias.length < 5) return null; const R = rng(12345), difs = [];
  for (let b = 0; b < B; b++) { let a = 0, c = 0, n = 0; for (let i = 0; i < dias.length; i++) { const t = dias[Math.floor(R() * dias.length)]; a += t[0]; c += t[1]; n += t[2]; } difs.push((a - c) / n); }
  difs.sort((x, y) => x - y); return [difs[Math.floor(.025 * B)], difs[Math.floor(.975 * B)]];
}
// n efectivo: ICC de los aciertos dentro del mismo día (ANOVA) y efecto de diseño
export function nEfectivo(vita) {
  const porDia = new Map(); for (const x of vita) { if (!porDia.has(x.fecha_decision)) porDia.set(x.fecha_decision, []); porDia.get(x.fecha_decision).push(x.acierto ? 1 : 0); }
  const n = vita.length, k = porDia.size; if (!n || k < 2) return { n, dias: k, icc: null, deff: null, n_efectivo: n };
  const gs = [...porDia.values()], media = vita.filter(x => x.acierto).length / n;
  let ssb = 0, ssw = 0; for (const g of gs) { const m = g.reduce((a, b) => a + b, 0) / g.length; ssb += g.length * (m - media) ** 2; for (const v of g) ssw += (v - m) ** 2; }
  const msb = ssb / (k - 1), msw = ssw / Math.max(1, n - k), n0 = (n - gs.reduce((s, g) => s + g.length ** 2, 0) / n) / (k - 1);
  const den = msb + (n0 - 1) * msw, icc = den > 0 ? Math.max(0, Math.min(1, (msb - msw) / den)) : 0, mbar = n / k, deff = 1 + (mbar - 1) * icc;
  return { n, dias: k, icc, deff, n_efectivo: Math.min(n, Math.round(n / deff)) };
}
// rows: filas calificadas (vita + bases), unidas por pid
export function grupo(rows) {
  const a = rows.filter(x => x.metodo === 'vita'), bases = {}, k = a.filter(x => x.acierto).length, n = a.length;
  for (const metodo of ['siempre_sube', 'momentum']) {
    const map = new Map(rows.filter(x => x.metodo === metodo).map(x => [x.pid, x])), pares = a.map(x => [x, map.get(x.pid)]).filter(x => x[1]);
    let gana = 0, pierde = 0; for (const [v, y] of pares) { if (v.acierto && !y.acierto) gana++; if (!v.acierto && y.acierto) pierde++; }
    const b = pares.map(x => x[1]), pctB = b.length ? b.filter(x => x.acierto).length / b.length : null;
    const ic = bootstrapDias(pares), p = mcnemar(gana, pierde), pctV = pares.length ? pares.filter(x => x[0].acierto).length / pares.length : null;
    const estado = pares.length < 30 || ic === null ? 0 : (p < .05 && ic[0] > 0) ? 1 : (p < .05 && ic[1] < 0) ? -1 : 0;
    bases[metodo] = { n: b.length, pct: pctB, brier: prom(b, 'brier'), exceso_promedio: prom(b, 'exceso'), vita_pct_pareado: pctV, dif_pct: pctV === null ? null : pctV - pctB, ic95_dif_bootstrap_dias: ic, p_valor_mcnemar: p, discordantes: { vita_gana: gana, vita_pierde: pierde }, estado };
  }
  const e = Object.values(bases).map(x => x.estado);
  const veredicto = n < 30 ? 'muestra insuficiente' : e.every(x => x === 1) ? 'le gana' : e.some(x => x === -1) ? 'pierde' : 'no se distingue';
  return { n, aciertos: k, pct: n ? k / n : null, ic95_pct: wilson(k, n), brier: prom(a, 'brier'), exceso_promedio: prom(a, 'exceso'), retorno_promedio: prom(a, 'retorno'), bases, veredicto };
}
export const grupoPor = (rows, f) => {
  const vita = rows.filter(x => x.metodo === 'vita'), claves = [...new Set(vita.map(f))].filter(x => x !== undefined && x !== null).sort();
  return Object.fromEntries(claves.map(c => { const pids = new Set(vita.filter(x => f(x) === c).map(x => x.pid)); return [c, grupo(rows.filter(x => pids.has(x.pid)))]; }));
};
export const bandaConfianza = p => p >= .70 ? '>=0.70' : p >= .55 ? '0.55-0.70' : '0.50-0.55';
export function claseDe(c) { return c === 'accion' ? 'accion' : c === 'cripto' ? 'cripto' : 'ETF'; }
// Régimen: según el retorno mensual de VT del mes de la fecha de decisión
export function regimenMensual(serieVT) {
  const f = aFilas(serieVT), ult = new Map(); for (const x of f) ult.set(x.fecha.slice(0, 7), x.precio);
  const meses = [...ult.keys()].sort(), out = {};
  for (let i = 1; i < meses.length; i++) out[meses[i]] = ult.get(meses[i]) / ult.get(meses[i - 1]) - 1 > 0 ? 'VT sube' : 'VT baja';
  return out;
}
// Días de negociación del rango, según las fechas con cierre de VT
export function diasHabiles(serieVT, desde, hasta) { return aFilas(serieVT).map(x => x.fecha).filter(f => f >= desde && f <= hasta && ![0, 6].includes(new Date(f + 'T12:00:00Z').getUTCDay())); }
export function tramoDe(dias, tramo, total) { const n = dias.length, a = Math.floor(n * tramo / total), b = Math.floor(n * (tramo + 1) / total); return dias.slice(a, b); }
