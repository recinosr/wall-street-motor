import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

// La SEC exige un contacto real; en Actions del repo privado viene del secreto SEC_CONTACT.
const UA = process.env.SEC_CONTACT || 'ProyectoWallStreet recinosr@users.noreply.github.com';
const OUT = 'datos/sec/fundamentales.json.gz';
const TAGS = {
  ingresos: ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'],
  utilidad_operativa: ['OperatingIncomeLoss'],
  utilidad_neta: ['NetIncomeLoss', 'ProfitLoss'],
  bpa_diluido: ['EarningsPerShareDiluted'],
};
let lastRequest = 0;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function getJSON(url) {
  for (let attempt = 1; attempt <= 5; attempt++) {
    const wait = Math.max(0, 125 - (Date.now() - lastRequest));
    if (wait) await sleep(wait);
    lastRequest = Date.now();
    try {
      const response = await fetch(url, {headers: {'user-agent': UA, accept: 'application/json'}, signal: AbortSignal.timeout(45000)});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      if (attempt === 5) throw error;
      await sleep(attempt * 2000);
    }
  }
}

function extract(company) {
  const result = {};
  for (const [field, names] of Object.entries(TAGS)) {
    const name = names.find(tag => company.facts?.['us-gaap']?.[tag]);
    if (!name) continue;
    const units = company.facts['us-gaap'][name].units || {};
    const values = Object.values(units).flat()
      .filter(x => x.filed && x.end && x.val != null)
      .map(({start, end, filed, fy, fp, val, form}) => ({start, end, filed, fy, fp, val, form}))
      .filter(x => x.start && (Date.parse(x.end) - Date.parse(x.start)) / 86400000 >= 70);
    result[field] = values;
  }
  return result;
}

const universe = JSON.parse(fs.readFileSync('maquina_ilimitada/universo.json', 'utf8')).instrumentos;
const membership = JSON.parse(fs.readFileSync('datos/universo_pit/sp500_miembros.json', 'utf8')).miembros_por_fecha;
if (!membership || typeof membership !== 'object') throw new Error('sp500_miembros.json no contiene miembros_por_fecha');
const tickers = new Set(universe.filter(x => x.clase === 'accion').map(x => x.ticker_precio.replace(/\.US$/, '').toUpperCase()));
for (const members of Object.values(membership)) for (const ticker of members) tickers.add(String(ticker).toUpperCase());

console.log(`Tickers únicos del universo y miembros PIT: ${tickers.size}`);
const tickerMap = await getJSON('https://www.sec.gov/files/company_tickers.json');
const cikByTicker = new Map(Object.values(tickerMap).map(x => [String(x.ticker).toUpperCase(), String(x.cik_str).padStart(10, '0')]));
const cikTickers = new Map();
const omitidos = [];
for (const ticker of tickers) {
  const cik = cikByTicker.get(ticker);
  if (!cik) { omitidos.push({ticker, razon: 'sin CIK en company_tickers.json de SEC'}); continue; }
  if (!cikTickers.has(cik)) cikTickers.set(cik, []);
  cikTickers.get(cik).push(ticker);
}

const datos = {};
let count = 0;
for (const [cik, symbols] of cikTickers) {
  try {
    const company = await getJSON(`https://data.sec.gov/api/xbrl/companyfacts/CIK${cik}.json`);
    const compact = extract(company);
    if (!Object.keys(compact).length) { omitidos.push({ticker: symbols.join(','), cik, razon: 'sin conceptos fundamentales requeridos'}); continue; }
    for (const ticker of symbols) datos[ticker] = compact;
  } catch (error) { omitidos.push({ticker: symbols.join(','), cik, razon: error.message}); }
  count++;
  if (count % 50 === 0 || count === cikTickers.size) {
    fs.mkdirSync(path.dirname(OUT), {recursive: true});
    fs.writeFileSync(OUT, zlib.gzipSync(JSON.stringify({version: 2, fuente: 'SEC EDGAR companyfacts; campos trimestrales con filed', descargado_utc: new Date().toISOString(), tickers_solicitados: tickers.size, datos, omitidos}), {level: 9}));
    console.log(`Descargadas ${count}/${cikTickers.size} compañías; tickers guardados: ${Object.keys(datos).length}`);
  }
}

console.log(`Guardado ${OUT}: ${Object.keys(datos).length} tickers; ${omitidos.length} omitidos; ${fs.statSync(OUT).size} bytes gzip`);
