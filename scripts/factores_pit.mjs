import fs from 'node:fs';
import zlib from 'node:zlib';
const read=(p)=>JSON.parse(fs.readFileSync(p,'utf8'));
const seriesRead=(p)=>JSON.parse((p.endsWith('.gz')?zlib.gunzipSync(fs.readFileSync(p)):fs.readFileSync(p)).toString('utf8'));
const membership=read('datos/universo_pit/sp500_miembros.json').miembros_por_fecha;
const pit=seriesRead('series_pit.json.gz').series;
const datesAapl=pit.AAPL?.f||[];
const price=(ticker,date,strictBefore=false)=>{
 const s=pit[ticker];if(!s)return null;
 let lo=0,hi=s.f.length;while(lo<hi){const mid=(lo+hi)>>1;if(s.f[mid]<date||(strictBefore&&s.f[mid]===date))lo=mid+1;else hi=mid;}
 return lo<s.f.length&&(!strictBefore||s.f[lo]<date)?{fecha:s.f[lo],precio:s.p[lo]}:null;
};
const prior=(ticker,date)=>{const s=pit[ticker];if(!s)return null;let i=s.f.findIndex(x=>x>=date);if(i<0)i=s.f.length;if(i<1)return null;return{fecha:s.f[i-1],precio:s.p[i-1],i:i-1};};
function score(ticker,date){const s=pit[ticker];if(!s)return null;const end=s.f.findIndex(x=>x>=date);const n=end<0?s.f.length:end;if(n<253)return null;const p=s.p.slice(0,n),v=p.at(-1),m=p[n-22]/p[n-253]-1,rr=p.slice(1).map((x,i)=>Math.log(x/p[i])).slice(-60),mu=rr.reduce((a,b)=>a+b,0)/rr.length,vol=Math.sqrt(rr.reduce((a,b)=>a+(b-mu)**2,0)/Math.max(1,rr.length-1)*252),high=Math.max(...p.slice(-252)),sma=p.slice(-200).reduce((a,b)=>a+b,0)/200;return{score:m-.20*vol+.15*v/high-.1*Math.max(0,sma/v-1)};}
function quantile(x,q){return x[Math.max(0,Math.min(x.length-1,Math.floor((x.length-1)*q)))];}
function bootstrap(rows,fieldA,fieldB,seed=1782,nboot=5000){const monthly=new Map();for(const r of rows){const k=r.date.slice(0,7);if(!monthly.has(k))monthly.set(k,[]);monthly.get(k).push(r[fieldA]-r[fieldB]);}const vals=[...monthly.values()].map(a=>a.reduce((s,x)=>s+x,0)/a.length);if(vals.length<3)return{meses:vals.length,ic95:null};let x=seed>>>0,draw=[];for(let i=0;i<nboot;i++){let sum=0;for(let j=0;j<vals.length;j++){x=(Math.imul(x,1664525)+1013904223)>>>0;sum+=vals[Math.floor(x/4294967296*vals.length)];}draw.push(sum/vals.length);}draw.sort((a,b)=>a-b);return{meses:vals.length,ic95:[quantile(draw,.025),quantile(draw,.975)]};}
function measure(start,end){const eligibleDates=datesAapl.filter(d=>d>=start&&d<=end),picks=[];let missingMemberDates=0,totalEligible=0,totalMembers=0;const membersInPeriod=new Set(Object.entries(membership).filter(([d])=>d>=start&&d<=end).flatMap(([,a])=>a));const missingSymbols=[...membersInPeriod].filter(t=>!pit[t]?.f?.length).sort();
 for(let i=0;i+20<eligibleDates.length;i+=21){const d=eligibleDates[i],target=eligibleDates[i+20],members=membership[d];if(!members)continue;const items=[];for(const ticker of members){totalMembers++;const s=pit[ticker];const entry=prior(ticker,d);if(!s?.f?.length||!entry){missingMemberDates++;continue;}const sc=score(ticker,d);const exit=price(ticker,target);if(!exit){missingMemberDates++;continue;}if(sc===null)continue;const ret=exit.precio/entry.precio-1;items.push({ticker,score:sc.score,ret});}if(items.length<10)continue;totalEligible+=items.length;items.sort((a,b)=>b.score-a.score);const top=items.slice(0,5),bottom=items.slice(-5),avg=items.reduce((a,x)=>a+x.ret,0)/items.length;picks.push({date:d,target,n:items.length,top5:top.reduce((a,x)=>a+x.ret,0)/top.length,universe:avg,bottom5:bottom.reduce((a,x)=>a+x.ret,0)/bottom.length,topTickers:top.map(x=>x.ticker),bottomTickers:bottom.map(x=>x.ticker)});}
 const agg=rows=>{const avg=rows.length?rows.reduce((a,x)=>a+x.top5,0)/rows.length:null,base=rows.length?rows.reduce((a,x)=>a+x.universe,0)/rows.length:null,worst=rows.length?rows.reduce((a,x)=>a+x.bottom5,0)/rows.length:null,compound=k=>rows.reduce((a,x)=>a*(1+x[k]),1)-1;return{periodos:rows.length,media_top5:avg,media_universo:base,media_peores5:worst,exceso_top5:avg===null?null:avg-base,acumulado_top5:compound('top5'),acumulado_universo:compound('universe'),acumulado_peores5:compound('bottom5'),bootstrap_mensual:bootstrap(rows,'top5','universe')};};
 const years={};for(const year of [...new Set(picks.map(x=>x.date.slice(0,4)))])years[year]=agg(picks.filter(x=>x.date.startsWith(year)));
 return{periodo:{desde:start,hasta:end},miembros_unicos:[...membersInPeriod].length,tickers_sin_serie:missingSymbols,fraccion_tickers_sin_serie:membersInPeriod.size?missingSymbols.length/membersInPeriod.size:null,metodo:'Decisión a cierre previo; factores calculados solo con precios anteriores al día de decisión. Rebalanceo cada 21 sesiones; retorno desde cierre previo hasta cierre de la sesión 21; cestas equiponderadas. Precios Yahoo no ajustados por dividendos.',universo_total_fechas:picks.length,universo_miembro_dias:totalMembers,universo_sin_precio_o_corte:missingMemberDates,fraccion_universo_sin_precio_o_corte:totalMembers?missingMemberDates/totalMembers:null,observaciones_factor:totalEligible,...agg(picks),por_anio:years,detalle:picks};}
const short=measure('2025-01-02','2026-09-30'),long=measure('2010-01-04','2024-12-31');
const out={generado_utc:new Date().toISOString(),fuente_membresia:'Wikipedia Historical components of the S&P 500, invertido desde la lista actual; datos/universo_pit/sp500_miembros.json',fuente_precios:'Yahoo Finance chart API (no ajustados; series faltantes explícitas)',periodo_corto:short,periodo_largo:long};
fs.mkdirSync('resultados/factores_pit',{recursive:true});fs.writeFileSync('resultados/factores_pit/resumen.json',JSON.stringify(out,null,2)+'\n');
const pct=x=>x==null?'n/d':`${(x*100).toFixed(2)} %`,rows=[['2025-01-02–2026-09-30',short],['2010–2024',long]].map(([p,r])=>`| ${p} | ${r.periodos} | ${pct(r.media_top5)} | ${pct(r.media_universo)} | ${pct(r.media_peores5)} | ${pct(r.exceso_top5)} | ${pct(r.bootstrap_mensual.ic95?.[0])} a ${pct(r.bootstrap_mensual.ic95?.[1])} | ${r.tickers_sin_serie.length}/${r.miembros_unicos} | ${pct(r.fraccion_tickers_sin_serie)} | ${pct(r.fraccion_universo_sin_precio_o_corte)} |`);
const annual=[...Object.entries(long.por_anio),...Object.entries(short.por_anio)].sort(([a],[b])=>a.localeCompare(b)).map(([year,r])=>`| ${year} | ${r.periodos} | ${pct(r.media_top5)} | ${pct(r.media_universo)} | ${pct(r.media_peores5)} | ${pct(r.exceso_top5)} |`);
const report=`# Factores con universo PIT

| Periodo | Rebalances | Media Top 5 | Media universo | Media peores 5 | Exceso Top 5 | IC 95% bootstrap mensual | Tickers sin serie | Fraccion sin serie | Fechas miembro sin precio/corte |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
${rows.join('\n')}

Referencia anterior: Claude reporto +8.5% de exceso por horizonte de 21 dias con el universo elegido a posteriori. En esta medicion PIT, el exceso Top 5 frente al promedio de miembros elegibles es ${pct(short.exceso_top5)}. Comparacion orientativa: la corrida anterior no dejo guardada su definicion de benchmark, asi que no es una replica exacta.

| Ano | Rebalances | Media Top 5 | Media universo | Media peores 5 | Exceso Top 5 |
|---|---:|---:|---:|---:|---:|
${annual.join('\n')}

Regla: momentum 12-1, volatilidad anualizada, distancia al maximo de 252 sesiones y penalizacion SMA200, equiponderada en cinco acciones. Rebalanceo cada 21 sesiones; horizonte de 21 sesiones sin solapamiento (salida en la sesion 21; el siguiente tramo entra desde el cierre previo). Cada fecha usa solo la membresia vigente y precios anteriores a la decision. El promedio usa miembros con historial suficiente para los factores y precio al cierre del horizonte. Las series Yahoo sin datos (HTTP 404 o sin grafico) aparecen en resumen.json; no se rellenaron ni inventaron. Los precios no incluyen dividendos. El JSON conserva los cortes anuales, intervalos bootstrap, tickers faltantes y cada rebalanceo.
`;
fs.writeFileSync('resultados/factores_pit/REPORTE.md',report);
console.log('Factores PIT: resumen.json y REPORTE.md generados.');
