import test from 'node:test';
import assert from 'node:assert/strict';
import {insumosDeFecha, cortarSerie, rasgos, candidatos, validarLlamada, calificarLlamada, mcnemar, wilson, grupo, nEfectivo, tramoDe, diasHabiles, bandaConfianza, regimenMensual, sumarDias} from './lib.mjs';
import {procesarFecha} from './correr.mjs';
import {escogerPares, probar} from './memoria.mjs';
import {resumirFilas} from './resumir.mjs';

const mk = (n, ini = 100, d0 = Date.UTC(2024, 0, 1)) => ({f: Array.from({length: n}, (_, i) => new Date(d0 + i * 86400000).toISOString().slice(0, 10)), p: Array.from({length: n}, (_, i) => ini + i + Math.sin(i))});
const universo = [
  {ticker: 'AAA.US', ticker_precio: 'AAA', clase: 'accion', fuente_cribado: 'sp500', referencia: 'VT', que: 'Aaa'},
  {ticker: 'TEM.US', ticker_precio: 'TEM', clase: 'accion', fuente_cribado: 'tema', referencia: 'VT', que: 'Tema'},
  {ticker: 'ETFX.UK', ticker_precio: 'ETFX.L', clase: 'ETF', referencia: 'VT', que: 'Etf X'},
  {ticker: 'BTC', ticker_precio: 'bitcoin', clase: 'cripto', referencia: 'EFECTIVO', que: 'Cripto BTC'},
  {ticker: 'ETH', ticker_precio: 'ethereum', clase: 'cripto', referencia: 'BTC', que: 'Cripto ETH'}
];
const series = () => Object.fromEntries([...universo.map(u => [u.ticker, mk(700)]), ['VT', mk(700, 90)]]);
const DIA = '2025-06-02';

test('NO MIRAR EL FUTURO: precios futuros extremos no cambian los insumos', () => {
  const s = series(), a = insumosDeFecha(DIA, universo, s);
  const extremo = Object.fromEntries(Object.entries(s).map(([k, v]) => [k, {f: v.f, p: v.p.map((x, i) => v.f[i] >= DIA ? (i % 2 ? 1e9 : 0.0001) : x)}]));
  const b = insumosDeFecha(DIA, universo, extremo);
  assert.ok(a.instrumentos.length >= 4);
  assert.deepEqual(a.instrumentos, b.instrumentos);
  assert.deepEqual(a.referencia_vt, b.referencia_vt);
  assert.ok(a.instrumentos.every(x => x.fecha_precio < DIA));
  // y los candidatos y el prompt tampoco cambian
  assert.deepEqual(candidatos(a.instrumentos, DIA, 10).map(x => x.ticker), candidatos(b.instrumentos, DIA, 10).map(x => x.ticker));
});

test('cortarSerie excluye la fecha de decisión y posteriores', () => {
  const c = cortarSerie(mk(10).f.map((f, i) => ({fecha: f, precio: i + 1})), '2024-01-05');
  assert.equal(c.at(-1).fecha, '2024-01-04');
});

test('rasgos: retornos y RSI razonables en serie creciente', () => {
  const r = rasgos(mk(300).f.map((f, i) => ({fecha: f, precio: 100 + i})));
  assert.ok(r.r_1m > 0 && r.rsi14 > 90 && r.dist_max52 === 0 && r.r_12m === null || r.r_12m > 0);
});

test('validarLlamada: precio exacto, probabilidad y plazo', () => {
  const ins = {ticker: 'X', ticker_precio: 'X', precio: 10.5, referencia: 'VT'}, raw = {direccion: 'sube', horizonte_dias: 5, probabilidad: .6, precio_ref: 10.5, razon: 'ok', invalidacion: 'cae'};
  assert.equal(validarLlamada(raw, ins).activo, 'X');
  assert.throws(() => validarLlamada({...raw, precio_ref: 10.51}, ins));
  assert.throws(() => validarLlamada({...raw, probabilidad: .9}, ins));
  assert.throws(() => validarLlamada({...raw, horizonte_dias: 7}, ins));
  assert.throws(() => validarLlamada({...raw, invalidacion: ''}, ins));
});

test('estadística: Wilson, McNemar y bandas', () => {
  const [lo, hi] = wilson(50, 100); assert.ok(lo < .5 && hi > .5 && Math.abs(lo - .404) < .01);
  assert.ok(mcnemar(10, 10) > .99); assert.ok(mcnemar(30, 5) < .001); assert.equal(mcnemar(0, 0), 1);
  assert.equal(bandaConfianza(.7), '>=0.70'); assert.equal(bandaConfianza(.6), '0.55-0.70'); assert.equal(bandaConfianza(.52), '0.50-0.55');
});

test('nEfectivo baja con correlación dentro del día', () => {
  const corr = Array.from({length: 200}, (_, i) => ({fecha_decision: 'd' + Math.floor(i / 20), acierto: Math.floor(i / 20) % 2 === 0}));
  const e = nEfectivo(corr); assert.equal(e.dias, 10); assert.ok(e.icc > .9); assert.ok(e.n_efectivo < 30);
  const indep = Array.from({length: 200}, (_, i) => ({fecha_decision: 'd' + Math.floor(i / 20), acierto: i % 2 === 0}));
  assert.ok(nEfectivo(indep).n_efectivo > 150);
});

test('tramos cubren todos los días hábiles sin solaparse', () => {
  const s = mk(700, 100, Date.UTC(2025, 0, 1)), dias = diasHabiles(s, '2025-01-02', '2026-10-16'), total = 20;
  const todos = Array.from({length: total}, (_, i) => tramoDe(dias, i, total)).flat();
  assert.deepEqual(todos, dias); assert.ok(dias.every(d => ![0, 6].includes(new Date(d + 'T12:00:00Z').getUTCDay())));
});

test('procesarFecha con modelo falso: lotes, bases, calificación y descartes', async () => {
  const s = series(); let n = 0;
  const pedir = async prompt => {
    n++; const m = [...prompt.matchAll(/"activo":"([^"]+)","precio_ref":([0-9.]+)/g)];
    const llamadas = m.slice(0, 3).map(([, activo, p], i) => ({activo, direccion: i % 2 ? 'baja' : 'sube', horizonte_dias: [1, 5, 21, 63][i], probabilidad: .6, precio_ref: Number(p), razon: 'r', fuentes: [], invalidacion: 'i', tipo: 'tendencia'}));
    llamadas.push({activo: 'NOEXISTE', direccion: 'sube', horizonte_dias: 5, probabilidad: .6, precio_ref: 1, razon: 'r', invalidacion: 'i'});
    return {datos: {llamadas}, intentos: 1, json_validos: 1, segundos: 2};
  };
  const {filas, stats} = await procesarFecha({dia: DIA, universo, series: s, modelo: 'falso', llamadas: 5, pedir});
  assert.ok(n >= 1); assert.ok(stats.llamadas_validas > 0); assert.equal(stats.descartes['Activo fuera de la lista'], n);
  assert.equal(filas.length, stats.llamadas_validas * 3);
  const v = filas.find(f => f.metodo === 'vita'); assert.ok(v.calificada); assert.equal(v.noticias, false);
  assert.ok(filas.filter(f => f.metodo !== 'vita').every(f => f.probabilidad === .5));
  // no mismo activo dos veces el mismo día
  const vs = filas.filter(f => f.metodo === 'vita').map(f => f.activo); assert.equal(new Set(vs).size, vs.length);
});

test('calificación: BTC contra efectivo, alt contra BTC, no vencida devuelve null', () => {
  const s = series(), l = {fecha_decision: DIA, activo: 'ETH', referencia: 'BTC', precio_ref: 100, precio_referencia: 100, horizonte_dias: 5, direccion: 'sube', probabilidad: .7};
  const c = calificarLlamada(l, s); assert.equal(typeof c.acierto, 'boolean'); assert.ok(Number.isFinite(c.exceso));
  assert.equal(calificarLlamada({...l, fecha_decision: '2030-01-01'}, s), null);
  const e = calificarLlamada({...l, activo: 'BTC', referencia: 'EFECTIVO', precio_referencia: 1}, s); assert.equal(e.retorno_referencia, 0);
});

test('memoria: ±3 % en más de 5 contamina; sin datos no', async () => {
  const s = series(), pares = escogerPares(universo, s, 5, '2025-01-02', '2025-12-31');
  assert.ok(pares.length >= 4);
  const sabe = await probar(pares, 'm', async () => ({datos: {cierre: 1}, json_validos: 1}));
  assert.equal(sabe.contaminado, false);
  let i = 0; const todos = Array.from({length: 20}, (_, j) => ({...pares[j % pares.length]}));
  const memoriza = await probar(todos, 'm', async () => ({datos: {cierre: todos[i++].precio_real}, json_validos: 1}));
  assert.equal(memoriza.aciertos, 20); assert.equal(memoriza.contaminado, true);
});

test('resumir: veredicto, bandas, regímenes y "no cuenta" si hay fuga', () => {
  const filas = [];
  for (let i = 0; i < 120; i++) {
    const dia = sumarDias('2025-02-03', i), base = {pid: 'p' + i, fecha_decision: dia, activo: 'A', clase: i % 2 ? 'accion' : 'ETF', horizonte_dias: 5, probabilidad: i % 3 ? .6 : .75, calificada: true, retorno: .01, exceso: .01, brier: .2};
    filas.push({...base, metodo: 'vita', id: 'v' + i, acierto: true}, {...base, metodo: 'siempre_sube', id: 's' + i, acierto: i % 2 === 0, probabilidad: .5}, {...base, metodo: 'momentum', id: 'm' + i, acierto: i % 2 === 0, probabilidad: .5});
  }
  const regimen = {'2025-02': 'VT sube', '2025-03': 'VT baja', '2025-04': 'VT sube', '2025-05': 'VT baja'};
  const ok = resumirFilas({filas, memoria: {estado: 'completa', n: 20, aciertos: 1, contaminado: false}, regimen});
  assert.equal(ok.cuenta, true); assert.equal(ok.global.veredicto, 'le gana'); assert.match(ok.veredicto, /le gana/);
  for (const k of ['>=0.70', '0.55-0.70']) assert.ok(ok.por_confianza[k].n > 0);
  assert.deepEqual(Object.keys(ok.por_clase).sort(), ['ETF', 'accion']); assert.ok(ok.por_regimen['VT sube'].n > 0 && ok.por_regimen['VT baja'].n > 0);
  assert.equal(ok.ejemplos.length, 10);
  const fuga = resumirFilas({filas, memoria: {estado: 'completa', n: 20, aciertos: 9, contaminado: true}, regimen});
  assert.equal(fuga.cuenta, false); assert.match(fuga.veredicto, /No cuenta/);
  assert.equal(resumirFilas({filas, memoria: null, regimen}).cuenta, false);
});

test('regimenMensual marca meses de VT sube/baja', () => {
  const r = regimenMensual({f: ['2025-01-31', '2025-02-28', '2025-03-31'], p: [100, 110, 100]});
  assert.equal(r['2025-02'], 'VT sube'); assert.equal(r['2025-03'], 'VT baja');
});
