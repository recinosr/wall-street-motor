// Baja TODAS las series diarias de Yahoo una sola vez y las guarda en series.json.gz (artefacto para los 20 trabajos).
// Uso: node preparar.mjs <universo.json> <salida.json.gz>
import {leerJSON, guardarJSON, fmt} from './lib.mjs';

const YAHOO_CRIPTO = {bitcoin: 'BTC-USD', ethereum: 'ETH-USD', solana: 'SOL-USD', chainlink: 'LINK-USD', ripple: 'XRP-USD', cardano: 'ADA-USD', 'avalanche-2': 'AVAX-USD', polkadot: 'DOT-USD'};
const esperar = ms => new Promise(r => setTimeout(r, ms));

export async function serieYahoo(sym, inicio, fin, intentos = 4) {
  const p1 = Math.floor(Date.parse(inicio + 'T00:00:00Z') / 1000), p2 = Math.floor(Date.parse(fin + 'T00:00:00Z') / 1000);
  let last;
  for (let i = 0; i < intentos; i++) {
    try {
      const r = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?period1=${p1}&period2=${p2}&interval=1d`, {headers: {'user-agent': 'Mozilla/5.0 MaquinaIlimitada/1.0'}, signal: AbortSignal.timeout(25000)});
      if (!r.ok) throw Error('HTTP ' + r.status);
      const x = (await r.json()).chart?.result?.[0];
      if (!x?.timestamp) throw Error('sin chart');
      const q = x.indicators.quote[0].close, f = [], p = [];
      x.timestamp.forEach((t, j) => { const d = fmt(t * 1000); if (Number.isFinite(q[j]) && d < fin) { if (f.at(-1) === d) { p[p.length - 1] = q[j]; } else { f.push(d); p.push(q[j]); } } });
      return {f, p};
    } catch (e) { last = e; await esperar(1500 * (i + 1)); }
  }
  throw last;
}

async function main() {
  const [uniP, salida] = process.argv.slice(2);
  const universo = leerJSON(uniP).instrumentos;
  const hoy = fmt(Date.now()), inicio = process.env.INICIO_SERIES || '2023-10-01';
  const pedidos = [...universo.map(f => [f.ticker, f.clase === 'cripto' ? YAHOO_CRIPTO[f.ticker_precio] : f.ticker_precio]), ['VT', 'VT']];
  const series = {}, fallas = [];
  let i = 0;
  await Promise.all(Array.from({length: 6}, async () => {
    while (i < pedidos.length) {
      const [t, sym] = pedidos[i++];
      try { series[t] = await serieYahoo(sym, inicio, hoy); } catch (e) { series[t] = {f: [], p: []}; fallas.push(`${t} (${sym}): ${e.message}`); }
      await esperar(120);
    }
  }));
  const ok = Object.values(series).filter(s => s.f.length > 100).length;
  console.log(`Series: ${ok}/${pedidos.length} con datos; fallas ${fallas.length}`);
  if (fallas.length) console.log(fallas.slice(0, 30).join('\n'));
  if (!series.VT?.f.length) throw Error('Sin serie de VT: no se puede continuar');
  guardarJSON(salida, {generado_utc: new Date().toISOString(), hasta: hoy, fallas, series});
}
if (process.argv[1]?.endsWith('preparar.mjs')) main();
