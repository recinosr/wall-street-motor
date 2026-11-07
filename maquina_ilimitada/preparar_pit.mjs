// Descarga series Yahoo para cada símbolo con membresía S&P 500 PIT.
import fs from 'node:fs';
import zlib from 'node:zlib';
import {serieYahoo} from './preparar.mjs';
import {fmt} from './lib.mjs';
const [membershipPath='datos/universo_pit/sp500_miembros.json',out='series_pit.json.gz']=process.argv.slice(2);
const membership=JSON.parse(fs.readFileSync(membershipPath,'utf8')).miembros_por_fecha;
const symbols=[...new Set(Object.values(membership).flat())].sort(),series={},faltantes=[];
let i=0;
await Promise.all(Array.from({length:8},async()=>{while(i<symbols.length){const ticker=symbols[i++],yahoo=ticker.replaceAll('.','-');try{series[ticker]=await serieYahoo(yahoo,'2009-10-01',fmt(Date.now()));}catch(e){series[ticker]={f:[],p:[]};faltantes.push({ticker,yahoo,error:String(e.message||e)});}await new Promise(r=>setTimeout(r,100));}}));
const cobertura=Object.values(series).filter(s=>s.f.length).length;
const data={generado_utc:new Date().toISOString(),fuente:'Yahoo Finance chart API; adjusted prices not used',desde:'2009-10-01',hasta:fmt(Date.now()),tickers_total:symbols.length,tickers_con_datos:cobertura,faltantes,series};
fs.writeFileSync(out,zlib.gzipSync(JSON.stringify(data)));
console.log(`Series S&P PIT con datos: ${cobertura}/${symbols.length}; sin datos: ${faltantes.length}`);
