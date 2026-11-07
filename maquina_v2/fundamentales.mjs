import fs from 'node:fs';
import zlib from 'node:zlib';

const wait = ms => new Promise(r => setTimeout(r, ms));
const UA = 'ProyectoWallStreet investigacion';

export async function descargarFundamentales(universo, salida='fundamentales.json.gz', fetcher=fetch) {
  const acciones = universo.filter(x => x.clase === 'accion');
  const mapaResp = await fetcher('https://www.sec.gov/files/company_tickers.json', {headers:{'user-agent':UA}, signal:AbortSignal.timeout(30000)});
  if (!mapaResp.ok) throw Error(`SEC ticker map HTTP ${mapaResp.status}`);
  const mapJson = await mapaResp.json(), porTicker = new Map();
  for (const item of Object.values(mapJson)) porTicker.set(String(item.ticker).toUpperCase(), String(item.cik_str).padStart(10,'0'));
  const ciKs = new Map();
  for (const a of acciones) {
    const ticker = a.ticker_precio.replace(/\.US$/,'').toUpperCase(), cik = porTicker.get(ticker);
    if (cik) { if(!ciKs.has(cik))ciKs.set(cik,[]); ciKs.get(cik).push(ticker); }
  }
  const datos = {}, omitidos = [];
  let previo=0;
  for (const [cik,tickers] of ciKs) {
    const ticker=tickers[0];
    const restante=1000-(Date.now()-previo); if(previo&&restante>0)await wait(restante);
    previo=Date.now();
    try { const r=await fetcher(`https://data.sec.gov/api/xbrl/companyfacts/CIK${cik}.json`,{headers:{'user-agent':UA,'accept':'application/json'},signal:AbortSignal.timeout(30000)}); if(!r.ok)throw Error(`HTTP ${r.status}`); const company=await r.json();for(const t of tickers)datos[t]=company; }
    catch(e){omitidos.push({ticker,cik,razon:e.message});}
  }
  const tags=['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet','EarningsPerShareDiluted','OperatingIncomeLoss'];
  for(const a of acciones){const t=a.ticker_precio.replace(/\.US$/,'').toUpperCase();if(!datos[t]&&!omitidos.some(x=>x.ticker===t))omitidos.push({ticker:t,razon:'sin CIK en mapa SEC'});else if(datos[t]&&!tags.some(tag=>datos[t]?.facts?.['us-gaap']?.[tag])&&!omitidos.some(x=>x.ticker===t))omitidos.push({ticker:t,razon:'companyfacts sin conceptos fundamentales requeridos'});}
  fs.writeFileSync(salida,zlib.gzipSync(JSON.stringify({version:1,fuente:'SEC EDGAR companyfacts',descargado_utc:new Date().toISOString(),datos,omitidos})));
  console.log(`SEC companyfacts: ${Object.keys(datos).length} CIK; omitidos ${omitidos.length}`);
  return {datos,omitidos};
}

function facts(company, names) { for(const name of names){const f=company?.facts?.['us-gaap']?.[name];if(f)return f;}return null; }
function quarterly(company,names,decision) {
  const units=facts(company,names)?.units||{}; const entries=Object.values(units).flat().filter(x=>x.filed<decision&&x.end<decision&&x.val!=null);
  const q=entries.filter(x=>x.start&&(Date.parse(x.end)-Date.parse(x.start))/86400000>=70&&(Date.parse(x.end)-Date.parse(x.start))/86400000<=110).sort((a,b)=>b.end.localeCompare(a.end)||b.filed.localeCompare(a.filed));
  // 10-Q YTD facts for Q2/Q3: derive the standalone quarter from prior YTD filing.
  const ytd=entries.filter(x=>x.start&&(Date.parse(x.end)-Date.parse(x.start))/86400000>110&&(Date.parse(x.end)-Date.parse(x.start))/86400000<300).sort((a,b)=>b.end.localeCompare(a.end)||b.filed.localeCompare(a.filed));
  for(const cur of ytd){const prev=ytd.filter(x=>x.fy===cur.fy&&x.end<cur.end&&x.filed<=cur.filed).sort((a,b)=>b.end.localeCompare(a.end))[0];if(prev)q.push({...cur,val:cur.val-prev.val});}
  const byEnd=new Map();for(const x of q){const prev=byEnd.get(x.end);if(!prev||x.filed>prev.filed)byEnd.set(x.end,x);}return [...byEnd.values()].sort((a,b)=>b.end.localeCompare(a.end));
}
export function rasgosFundamentales(company,decision) {
  const rev=quarterly(company,['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet'],decision);
  const eps=quarterly(company,['EarningsPerShareDiluted'],decision);
  const op=quarterly(company,['OperatingIncomeLoss'],decision);
  const yearAgo=a=>a.length? a.find(x=>{const d=(Date.parse(a[0].end)-Date.parse(x.end))/86400000;return d>=330&&d<=400;}):null;
  const yoy=(a)=>{const old=yearAgo(a);return a.length&&old&&old.val!==0?a[0].val/old.val-1:null;};
  const margin=op.length&&rev.find(x=>x.end===op[0].end)&&rev.find(x=>x.end===op[0].end).val!==0?op[0].val/rev.find(x=>x.end===op[0].end).val:null;
  const oldOp=yearAgo(op),oldRev=oldOp&&rev.find(x=>x.end===oldOp.end),priorMargin=oldOp&&oldRev&&oldRev.val!==0?oldOp.val/oldRev.val:null;
  const filed=[...rev,...eps,...op].map(x=>x.filed).filter(x=>x<decision).sort();
  if(!filed.length)return null;
  const age=Math.floor((Date.parse(decision)-Date.parse(filed.at(-1)))/86400000);
  return {crecimiento_ingresos_yoy:yoy(rev),crecimiento_eps_diluido_yoy:yoy(eps),margen_operativo:margin,cambio_margen_operativo_yoy:margin!=null&&priorMargin!=null?margin-priorMargin:null,dias_desde_reporte:age,fecha_ultimo_reporte:filed.at(-1)};
}
export function scoreFundamentales(f){return (f?.crecimiento_ingresos_yoy??0)+(f?.crecimiento_eps_diluido_yoy??0)+(f?.cambio_margen_operativo_yoy??0);}
