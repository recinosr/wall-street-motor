// Prueba de memoria: 20 preguntas «¿cuál fue el cierre de X el día D?» sin darle datos al modelo.
// Si acierta ±3 % en más de 5, el período NO cuenta (el modelo recuerda precios de ese período).
// Uso: node memoria.mjs --series=series.json.gz --universo=universo.json --modelo=... --salida=memoria.json
import fs from 'node:fs';
import {leerJSON, aFilas} from './lib.mjs';
import {pedirJSON} from './ollama.mjs';

const args = Object.fromEntries(process.argv.slice(2).map(s => s.replace(/^--/, '').split('=')));
const hash = s => { let h = 2166136261; for (const c of s) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0; };

export function escogerPares(universo, series, n = 20, desde = '2025-01-02', hasta = '2026-10-16') {
  const cand = [];
  for (const f of universo.filter(x => x.clase !== 'cripto' || x.ticker === 'BTC')) {
    const s = aFilas(series[f.ticker]).filter(x => x.fecha >= desde && x.fecha <= hasta);
    if (s.length < 50) continue;
    const x = s[hash(f.ticker + 'mem') % s.length];
    cand.push({activo: f.ticker, nombre: f.clase === 'cripto' ? 'Bitcoin (BTC-USD)' : f.que.replace(/\s*\(.*\)$/, ''), simbolo: f.ticker_precio, fecha: x.fecha, precio_real: x.precio, clase: f.clase});
  }
  // Mezcla de clases: acciones conocidas, ETF y BTC
  cand.sort((a, b) => hash(a.activo + 'orden') - hash(b.activo + 'orden'));
  const out = [], quota = {accion: 14, ETF: 4, ETC: 1, cripto: 1};
  for (const c of cand) { if (quota[c.clase] > 0 && out.length < n) { out.push(c); quota[c.clase]--; } }
  for (const c of cand) if (out.length < n && !out.includes(c)) out.push(c);
  return out.slice(0, n);
}

export async function probar(pares, modelo, pedir = pedirJSON) {
  const resp = [];
  for (const [i, p] of pares.entries()) {
    const prompt = `Sin consultar herramientas ni recibir datos: ¿cuál fue el precio de cierre de ${p.nombre} (símbolo ${p.simbolo}) el día ${p.fecha}, en la moneda de su mercado? Respondé solo JSON {"cierre": número o null}`;
    const r = await pedir(prompt, {modelo, semilla: 100 + i, maxTokens: 60, ctx: 1024, temperatura: 0}, d => d && ('cierre' in d));
    const est = Number(r.datos?.cierre);
    resp.push({activo: p.activo, fecha: p.fecha, precio_real: p.precio_real, estimado: Number.isFinite(est) && est > 0 ? est : null, acierto: Number.isFinite(est) && est > 0 && Math.abs(est / p.precio_real - 1) <= 0.03, json_valido: r.json_validos > 0});
  }
  const aciertos = resp.filter(x => x.acierto).length;
  return {estado: 'completa', n: pares.length, aciertos, contaminado: aciertos > 5, regla: 'si acierta ±3 % en más de 5 de 20, el período no cuenta', modelo, respuestas: resp};
}

async function main() {
  const universo = leerJSON(args.universo).instrumentos, series = leerJSON(args.series).series;
  const pares = escogerPares(universo, series);
  console.log('Pares de memoria:', pares.length);
  const m = await probar(pares, args.modelo);
  console.log(`Memoria: ${m.aciertos}/${m.n} dentro de ±3 %; contaminado=${m.contaminado}`);
  fs.writeFileSync(args.salida, JSON.stringify(m, null, 1));
}
if (process.argv[1]?.endsWith('memoria.mjs')) main();
