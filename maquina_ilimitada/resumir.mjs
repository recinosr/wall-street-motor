// Junta los artefactos de los 20 tramos y produce resumen.json + llamadas.jsonl.gz.
// Uso: node resumir.mjs --artefactos=artefactos --series=series.json.gz --memoria=memoria.json --salida=resultados/maquina_ilimitada --modelo=... --desde=... --hasta=...
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import {leerJSON, leerJSONL, grupo, grupoPor, bandaConfianza, nEfectivo, regimenMensual, wilson, aFilas} from './lib.mjs';

export function resumirFilas({filas, stats = [], tramos = [], memoria = null, regimen = {}, meta = {}}) {
  const calif = filas.filter(x => x.calificada), vita = calif.filter(x => x.metodo === 'vita');
  const todasVita = filas.filter(x => x.metodo === 'vita');
  const global = grupo(calif), ne = nEfectivo(vita);
  const sol = stats.filter(x => !x.error), sum = k => sol.reduce((s, x) => s + (x[k] || 0), 0);
  const porRegimen = grupoPor(calif, x => regimen[x.fecha_decision.slice(0, 7)]);
  const ejemplos = vita.length ? Array.from({length: Math.min(10, vita.length)}, (_, i) => vita[Math.floor(i * vita.length / Math.min(10, vita.length))]).map(x => ({activo: x.activo, direccion: x.direccion, horizonte_dias: x.horizonte_dias, probabilidad: x.probabilidad, acierto: x.acierto, retorno: x.retorno, emitida_utc: x.fecha_decision + 'T12:00:00Z', razon: x.razon})) : [];
  const memOk = memoria && memoria.estado === 'completa';
  let veredicto, cuenta = true;
  if (!memOk) { cuenta = false; veredicto = 'No cuenta: falta la prueba de memoria completa, no se puede descartar que el modelo recuerde los precios.'; }
  else if (memoria.contaminado) { cuenta = false; veredicto = `No cuenta: en la prueba de memoria el modelo acertó ${memoria.aciertos} de ${memoria.n} cierres a ±3 % sin recibir datos, así que pudo memorizar este período.`; }
  else {
    const b = global.bases, f = x => x == null ? 'n/d' : (100 * x).toFixed(1) + ' %';
    const frase = {'le gana': 'Vita le gana a las dos líneas base', 'pierde': 'Vita pierde frente a al menos una línea base', 'no se distingue': 'Vita no se distingue de las líneas base', 'muestra insuficiente': 'Muestra insuficiente para concluir'}[global.veredicto];
    veredicto = `${frase} (Vita ${f(global.pct)} vs siempre sube ${f(b.siempre_sube.pct)} vs momentum ${f(b.momentum.pct)}; n=${global.n}, n efectivo≈${ne.n_efectivo} en ${ne.dias} días).`;
  }
  const por_horizonte = grupoPor(calif, x => String(x.horizonte_dias)), por_clase = grupoPor(calif, x => x.clase), por_confianza = grupoPor(calif, x => bandaConfianza(x.probabilidad));
  return {
    version: 1, actualizado_utc: new Date().toISOString(), ...meta,
    estado: tramos.length && tramos.every(t => t.completo) ? 'completo' : 'parcial',
    cuenta, veredicto, memoria,
    global: {...global, n_efectivo: ne},
    por_confianza, por_clase, por_horizonte, por_regimen: porRegimen,
    produccion: {
      llamadas_vita_emitidas: todasVita.length, calificadas: vita.length, sin_vencer: todasVita.length - vita.length,
      solicitudes: sum('solicitudes'), lotes_con_json_valido: sum('json_validos'), pct_json_valido: sum('solicitudes') ? sum('json_validos') / sum('solicitudes') : null,
      intentos_totales: sum('intentos'), llamadas_crudas: sum('llamadas_crudas'), llamadas_validas: sum('llamadas_validas'), pct_llamadas_validas: sum('llamadas_crudas') ? sum('llamadas_validas') / sum('llamadas_crudas') : null,
      segundos_modelo: Number(sum('segundos').toFixed(0)), segundos_por_solicitud: sum('solicitudes') ? sum('segundos') / sum('solicitudes') : null, segundos_por_llamada_valida: sum('llamadas_validas') ? sum('segundos') / sum('llamadas_validas') : null,
      fechas_procesadas: sol.length, fechas_con_error: stats.length - sol.length
    },
    tramos,
    ejemplos,
    noticias: false,
    metodo: 'Solo precios (sin noticias): cada fecha usa únicamente cierres anteriores a ella; la calificación usa el primer cierre igual o posterior al vencimiento en días calendario. Acierto por signo; Brier probabilístico; IC Wilson 95 %; McNemar exacto pareado frente a siempre sube y momentum, más bootstrap por días completos para respetar la correlación dentro del día. Referencia: VT para acciones y ETF, BTC para cripto alt, efectivo para BTC. Precios de Yahoo sin ajuste de dividendos. Universo actual: posible sesgo de supervivencia. Un modelo entrenado después del período no reproduce un pronóstico emitido entonces; la prueba de memoria reduce, no elimina, esa duda. Subgrupos exploratorios, sin ajuste por comparaciones múltiples.',
    comparaciones_subgrupos: Object.keys(por_horizonte).length + Object.keys(por_clase).length + Object.keys(por_confianza).length + Object.keys(porRegimen).length
  };
}

function main() {
  const a = Object.fromEntries(process.argv.slice(2).map(s => s.replace(/^--/, '').split('=')));
  const dirs = fs.existsSync(a.artefactos) ? fs.readdirSync(a.artefactos).filter(d => d.startsWith('tramo-')).sort() : [];
  let filas = [], stats = [], tramos = [];
  for (const d of dirs) {
    const base = path.join(a.artefactos, d);
    filas.push(...leerJSONL(path.join(base, 'llamadas.jsonl')));
    stats.push(...leerJSONL(path.join(base, 'estadisticas.jsonl')));
    const t = leerJSON(path.join(base, 'tramo.json')); if (t) tramos.push({...t, artefacto: d});
  }
  const serieVT = leerJSON(a.series)?.series?.VT, memoria = leerJSON(a.memoria);
  const res = resumirFilas({filas, stats, tramos, memoria, regimen: regimenMensual(serieVT), meta: {modelo: a.modelo, periodo: {desde: a.desde, hasta: a.hasta}, llamadas_por_dia: Number(a.llamadas_por_dia || 20), run_id: process.env.GITHUB_RUN_ID || null}});
  fs.mkdirSync(a.salida, {recursive: true});
  fs.writeFileSync(path.join(a.salida, 'resumen.json'), JSON.stringify(res, null, 1) + '\n');
  fs.writeFileSync(path.join(a.salida, 'llamadas.jsonl.gz'), zlib.gzipSync(filas.map(f => JSON.stringify(f)).join('\n') + '\n'));
  console.log(res.veredicto); console.log(`Vita calificadas ${res.global.n}; tramos ${tramos.length}; estado ${res.estado}`);
}
if (process.argv[1]?.endsWith('resumir.mjs')) main();
