// Un tramo de la máquina del tiempo: por cada fecha arma insumos SIN futuro, pide N llamadas al modelo local,
// añade las dos líneas base y califica lo que ya venció. Guarda avance en cada fecha.
// Uso: node correr.mjs --tramo=3 --total=20 --desde=2025-01-02 --hasta=2026-10-16 --series=series.json.gz --universo=universo.json --salida=salida --modelo=qwen2.5:7b-instruct --llamadas=20 --presupuesto_min=335
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {leerJSON, leerJSONL, aFilas, insumosDeFecha, candidatos, lotes, armarPrompt, validarLlamada, calificarLlamada, precioReferencia, claseDe, diasHabiles, tramoDe} from './lib.mjs';
import {pedirJSON} from './ollama.mjs';

const args = Object.fromEntries(process.argv.slice(2).map(s => s.replace(/^--/, '').split('=')));
const num = (k, d) => Number(args[k] ?? d);

export async function procesarFecha({dia, universo, series, modelo, llamadas = 20, tramo = 0, pedir = pedirJSON}) {
  const ins = insumosDeFecha(dia, universo, series);
  const nLotes = Math.max(1, Math.ceil(llamadas / 5)), cupo = Math.ceil(llamadas / nLotes);
  const cand = candidatos(ins.instrumentos, dia, Math.min(ins.instrumentos.length, llamadas * 2));
  const stats = {dia, solicitudes: 0, json_validos: 0, intentos: 0, llamadas_crudas: 0, llamadas_validas: 0, descartes: {}, segundos: 0};
  const filas = [], usados = new Set();
  let k = 0;
  for (const lote of lotes(cand, nLotes)) {
    const prompt = armarPrompt(dia, lote, cupo);
    const r = await pedir(prompt, {modelo, semilla: 7 + k}, d => Array.isArray(d?.llamadas));
    stats.solicitudes++; stats.intentos += r.intentos; stats.json_validos += r.json_validos > 0 ? 1 : 0; stats.segundos += r.segundos;
    if (!r.datos) { stats.descartes['sin JSON válido'] = (stats.descartes['sin JSON válido'] || 0) + 1; continue; }
    for (const raw of r.datos.llamadas.slice(0, cupo)) {
      stats.llamadas_crudas++;
      try {
        const x = lote.find(c => c.ticker === raw?.activo);
        if (!x) throw Error('Activo fuera de la lista');
        if (usados.has(x.ticker)) throw Error('Activo repetido en el día');
        const l = validarLlamada(raw, x, []);
        const pref = precioReferencia(x.referencia, series, dia);
        if (!pref) throw Error('Sin precio de referencia');
        const pid = `${dia}-${x.ticker}-${l.horizonte_dias}`;
        const base = {pid, fecha_decision: dia, tramo, activo: x.ticker, clase: claseDe(x.clase), horizonte_dias: l.horizonte_dias, precio_ref: l.precio_ref, referencia: x.referencia, precio_referencia: pref, tipo: l.tipo, noticias: false, modelo};
        const vita = {...base, id: pid + '-vita', metodo: 'vita', direccion: l.direccion, probabilidad: l.probabilidad, razon: l.razon, invalidacion: l.invalidacion, segundos_lote: Number((r.segundos / Math.max(1, r.datos.llamadas.length)).toFixed(1))};
        const mom = {...base, id: pid + '-momentum', metodo: 'momentum', direccion: x.r_1m >= 0 ? 'sube' : 'baja', probabilidad: .5, razon: 'Línea base: dirección del último mes.', modelo: 'regla fija'};
        const sube = {...base, id: pid + '-siempre_sube', metodo: 'siempre_sube', direccion: 'sube', probabilidad: .5, razon: 'Línea base: siempre sube.', modelo: 'regla fija'};
        usados.add(x.ticker);
        for (const f of [vita, sube, mom]) filas.push(f);
        stats.llamadas_validas++;
      } catch (e) { stats.descartes[e.message] = (stats.descartes[e.message] || 0) + 1; }
    }
    k++;
  }
  for (const f of filas) { const c = calificarLlamada(f, series); if (c) Object.assign(f, c, {calificada: true}); else f.calificada = false; }
  return {filas, stats};
}


// Las corridas largas no muestran su registro por la API hasta terminar: cada pocas fechas el trabajo publica un
// resumen de avance (pocos bytes) en resultados/maquina_ilimitada/progreso/. No es un resultado: solo permite vigilar.
function publicarProgreso(salida, tramo, total) {
  if (process.env.GITHUB_ACTIONS !== 'true' || process.env.PROGRESO === '0') return;
  try {
    const est = leerJSONL(path.join(salida, 'estadisticas.jsonl')).filter(x => !x.error), sum = k => est.reduce((a, x) => a + (x[k] || 0), 0);
    const slug = String(args.modelo).replace(/[:/]/g, '_'), dir = `resultados/maquina_ilimitada/progreso/${slug}`, f = `${dir}/tramo-${String(tramo).padStart(2, '0')}.json`;
    const prog = {tramo, modelo: args.modelo, run_id: process.env.GITHUB_RUN_ID, fechas_hechas: est.length, fechas_total: total, solicitudes: sum('solicitudes'), lotes_con_json_valido: sum('json_validos'), llamadas_crudas: sum('llamadas_crudas'), llamadas_validas: sum('llamadas_validas'), segundos_modelo: Math.round(sum('segundos')), ultima_fecha: est.at(-1)?.dia, actualizado_utc: new Date().toISOString()};
    for (let i = 0; i < 5; i++) {
      try {
        const g = (...a) => execFileSync('git', a, {stdio: 'pipe'});
        g('fetch', '-q', '--depth=1', 'origin', 'main'); g('checkout', '-q', '--detach', 'FETCH_HEAD');
        fs.mkdirSync(dir, {recursive: true}); fs.writeFileSync(f, JSON.stringify(prog, null, 1) + String.fromCharCode(10));
        g('-c', 'user.name=motor-bot', '-c', 'user.email=motor-bot@users.noreply.github.com', 'add', f);
        g('-c', 'user.name=motor-bot', '-c', 'user.email=motor-bot@users.noreply.github.com', 'commit', '-q', '-m', `maquina-ilimitada: avance tramo ${tramo} (${est.length}/${total})`);
        g('push', '-q', 'origin', 'HEAD:main'); return;
      } catch (e) { execFileSync('sleep', [String(2 + Math.floor(Math.random() * 8))]); }
    }
  } catch (e) { console.log('Avance no publicado:', e.message); }
}

async function main() {
  const inicio = Date.now(), presupuesto = num('presupuesto_min', 335) * 60000;
  const salida = args.salida || 'salida'; fs.mkdirSync(salida, {recursive: true});
  const universo = leerJSON(args.universo).instrumentos, serieArch = leerJSON(args.series), series = serieArch.series;
  const dias = tramoDe(diasHabiles(series.VT, args.desde, args.hasta), num('tramo', 0), num('total', 20));
  const pLl = path.join(salida, 'llamadas.jsonl'), pEst = path.join(salida, 'estadisticas.jsonl');
  const hechos = new Set(leerJSONL(pEst).filter(x => !x.error).map(x => x.dia));
  console.log(`Tramo ${args.tramo}/${args.total}: ${dias.length} fechas (${dias[0]} a ${dias.at(-1)}), modelo ${args.modelo}, ${args.llamadas} llamadas/día, ya hechas ${hechos.size}`);
  let parada = null;
  for (const dia of dias) {
    if (hechos.has(dia)) continue;
    if (Date.now() - inicio > presupuesto) { parada = 'presupuesto de tiempo agotado antes de ' + dia; break; }
    try {
      const {filas, stats} = await procesarFecha({dia, universo, series, modelo: args.modelo, llamadas: num('llamadas', 20), tramo: num('tramo', 0)});
      if (filas.length) fs.appendFileSync(pLl, filas.map(f => JSON.stringify(f)).join('\n') + '\n');
      fs.appendFileSync(pEst, JSON.stringify(stats) + '\n');
      const hechas = leerJSONL(pEst).filter(x => !x.error).length; if (hechas === 1 || hechas % 3 === 0) publicarProgreso(salida, num('tramo', 0), dias.length);
      console.log(`${dia}: ${stats.llamadas_validas}/${stats.llamadas_crudas} válidas (${stats.json_validos}/${stats.solicitudes} lotes con JSON válido, ${stats.intentos} intentos), ${stats.segundos.toFixed(0)} s, descartes ${JSON.stringify(stats.descartes)}`);
    } catch (e) { console.log(`${dia}: error ${e.message}`); fs.appendFileSync(pEst, JSON.stringify({dia, error: e.message}) + '\n'); }
  }
  const est = leerJSONL(pEst);
  fs.writeFileSync(path.join(salida, 'tramo.json'), JSON.stringify({tramo: num('tramo', 0), desde: dias[0], hasta: dias.at(-1), fechas: dias.length, fechas_hechas: est.filter(x => !x.error).length, completo: !parada && dias.every(d => est.some(x => x.dia === d && !x.error)), parada, modelo: args.modelo, minutos: Number(((Date.now() - inicio) / 60000).toFixed(1))}, null, 1));
  console.log(parada || 'Tramo terminado');
}
if (process.argv[1]?.endsWith('correr.mjs')) main();
