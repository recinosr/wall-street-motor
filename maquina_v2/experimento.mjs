// Motor VITA v2. Todas las caracterÃ­sticas para D se calculan con cierres anteriores a D.
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import {createHash} from 'node:crypto';
import {leerJSON, leerJSONL, aFilas, insumosDeFecha, candidatos, lotes, validarLlamada, calificarLlamada, precioReferencia, claseDe, diasHabiles, tramoDe, rasgos, mcnemar} from '../maquina_ilimitada/lib.mjs';
import {pedirJSON} from '../maquina_ilimitada/ollama.mjs';
import {rasgosFundamentales,scoreFundamentales} from './fundamentales.mjs';

const argv=Object.fromEntries(process.argv.slice(2).map(x=>x.replace(/^--/,'').split('=')));
const round=x=>Number.isFinite(x)?Number(x.toFixed(6)):null;
const hash=s=>createHash('sha256').update(s).digest().readUInt32BE(0);
const wait=ms=>new Promise(r=>setTimeout(r,ms));

export function puntuacionFactor(x, hist){
 const p=hist.map(y=>y.precio), n=p.length; if(n<253)return null;
 const m12=p[n-22]/p[n-253]-1, rr=p.slice(1).map((v,i)=>Math.log(v/p[i])).slice(-60), mu=rr.reduce((a,b)=>a+b,0)/Math.max(1,rr.length), vol=Math.sqrt(rr.reduce((a,b)=>a+(b-mu)**2,0)/Math.max(1,rr.length-1)*252);
 const max=Math.max(...p.slice(-252)), sma=p.slice(-200).reduce((a,b)=>a+b,0)/200;
 return {momentum_12_1:m12,volatilidad:vol,distancia_maximo:x.precio/max,tendencia_sma200:x.precio/sma-1,puntuacion:m12-.20*vol+0.15*(x.precio/max)-0.1*Math.max(0,sma/x.precio-1)};
}
export function tasaBaseHistorica(series, universo, dia){
 let up=0,n=0;
 for(const ins of universo){const rows=aFilas(series[ins.ticker]).filter(r=>r.fecha<dia); for(let i=0;i+21<rows.length;i++){if(rows[i+21].fecha>=dia)break; n++; if(rows[i+21].precio>rows[i].precio)up++;}}
 return n?up/n:.57;
}
export function seleccionarNoticias(cache, ticker, dia){
 const min=new Date(Date.parse(dia+'T00:00:00Z')-72*3600_000).toISOString();
 return cache.filter(x=>x.ticker===ticker && x.seendate>=min && x.seendate<dia+'T00:00:00Z').slice(0,5).map(x=>({titulo:x.title,fecha:x.seendate,fuente:x.domain}));
}
async function noticiasDia(dir, ticker, dia){
 const mes=dia.slice(0,7), f=path.join(dir,`${mes}.jsonl.gz`);fs.mkdirSync(dir,{recursive:true});
 const rows=leerJSONL(f), cached=rows.filter(x=>x.ticker===ticker&&x.dia===dia);if(cached.length)return cached.flatMap(x=>x.items||[]);
 const q=encodeURIComponent(ticker.replace(/\..*$/,'')+' stock');let items=[];
 try {const end=Date.parse(dia+'T00:00:00Z'),start=new Date(end-72*3600_000),fmt=x=>x.toISOString().replace(/[-:T]/g,'').slice(0,14);const url=`https://api.gdeltproject.org/api/v2/doc/doc?query=${q}&mode=ArtList&format=json&startdatetime=${fmt(start)}&enddatetime=${fmt(new Date(end-1000))}&maxrecords=20&sort=HybridRel`;
   let r;for(let attempt=0;attempt<3;attempt++){r=await fetch(url,{headers:{'user-agent':'VITA-v2-historical-experiment/1.0'},signal:AbortSignal.timeout(15000)});if(r.status!==429)break;await wait(5000*(attempt+1));}if(!r.ok)throw Error(`GDELT HTTP ${r.status}`);
   const j=await r.json(),iso=s=>/^\d{8}T\d{6}Z$/.test(s)?`${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}T${s.slice(9,11)}:${s.slice(11,13)}:${s.slice(13,15)}Z`:s;items=(j.articles||[]).map(a=>({...a,seendate:iso(a.seendate)})).filter(a=>a.seendate&&a.seendate>=start.toISOString()&&a.seendate<dia+'T00:00:00Z').map(a=>({title:a.title,seendate:a.seendate,domain:a.domain}));
 } catch {}
 rows.push({ticker,dia,items,consultado:true});fs.writeFileSync(f,zlib.gzipSync(rows.map(JSON.stringify).join('\n')+'\n'));return items;
}
const promptFor=(dia,items,count,variant,base)=>`Sos Vita, en una simulaciÃ³n histÃ³rica fechada ${dia}. ContestÃ¡ SOLO JSON {"llamadas":[{"activo":"ticker exacto","direccion":"sube|baja","horizonte_dias":21,"probabilidad":0.50-0.85,"precio_ref":nÃºmero exacto,"razon":"en espaÃ±ol","invalidacion":"en espaÃ±ol","tipo":"tendencia"}]}. GenerÃ¡ hasta ${count} activos Ãºnicos. ${variant.includes('solo_compra')?'Solo podÃ©s recomendar sube; prohibido baja.':''} ${variant.includes('calibrada')?`La tasa base histÃ³rica disponible hasta antes de esta fecha es ${base.toFixed(3)}. PartÃ­ de ella y reportÃ¡ probabilidades honestas, sin falsa precisiÃ³n.`:''} InformaciÃ³n (solo pasada): ${JSON.stringify(items)}`;
async function call(prompt,model,seed){return pedirJSON(prompt,{modelo:model,semilla:seed},d=>Array.isArray(d?.llamadas));}
export async function procesarDia({dia,universo,series,modelo,variante,llamadas=20,pedir=call,cacheNoticias='resultados/cache_gdelt',datosFundamentales={}}){
 const active=variante.split(',').filter(Boolean), ins=insumosDeFecha(dia,universo,series);let cands=candidatos(ins.instrumentos,dia,Math.max(40,llamadas*2));
 const feats=new Map(); if(active.includes('factores')){for(const x of ins.instrumentos){const hist=aFilas(series[x.ticker]).filter(r=>r.fecha<dia);const f=puntuacionFactor(x,hist);if(f)feats.set(x.ticker,{...f,fecha_corte:hist.at(-1)?.fecha});}cands=cands.map(x=>({...x,...(feats.get(x.ticker)||{})})).sort((a,b)=>(b.puntuacion??-Infinity)-(a.puntuacion??-Infinity)).slice(0,30);}
 const fundamentals=new Map();if(active.includes('fundamentales')){for(const x of ins.instrumentos.filter(y=>y.clase==='accion')){const ticker=x.ticker_precio.replace(/\.US$/,'').toUpperCase(),f=rasgosFundamentales(datosFundamentales[ticker],dia);if(f){fundamentals.set(x.ticker,f);}}cands=cands.map(x=>({...x,...(fundamentals.has(x.ticker)?{fundamentales:fundamentals.get(x.ticker)}:{})}));}
 if(active.includes('noticias'))for(const x of cands){const n=await noticiasDia(cacheNoticias,x.ticker,dia);x.noticias=seleccionarNoticias(n.map(y=>({...y,ticker:x.ticker})),x.ticker,dia);}
 const base=tasaBaseHistorica(series,universo,dia);let raw=[];const models=active.includes('conjunto')?['qwen2.5:7b','llama3.1:8b',...(modelo.includes('14b')?['qwen2.5:14b']:[])]:[modelo];
 const batch=Math.min(5,llamadas), prompts=active.includes('debate')?3:1;
 for(let k=0;k<Math.ceil(llamadas/batch);k++){
  const lote=cands.slice(k*batch*2,(k+1)*batch*2);if(!lote.length)break;
  const ctx=lote.map(x=>({activo:x.ticker,precio_ref:x.precio,referencia:x.referencia,clase:claseDe(x.clase),rasgos:{semana:x.r_1s,mes:x.r_1m,trimestre:x.r_3m,ano:x.r_12m,volatilidad:x.vol20,dist_max52:x.dist_max52,z200:x.z200},factores:feats.get(x.ticker)||null,fundamentales:fundamentals.get(x.ticker)||null,titulares:x.noticias||[],sin_noticias:active.includes('noticias')&&!(x.noticias?.length)}));
  const collect=[];
  for(const model of models){let consensus;
    if(active.includes('debate')){const pos=await call(`Tesis optimista para cada candidato (sin decidir): ${JSON.stringify(ctx)}`,model,k*10+1);const neg=await call(`Tesis pesimista para cada candidato (sin decidir): ${JSON.stringify(ctx)}`,model,k*10+2);consensus=await call(`DecidÃ­ usando ambas tesis, datos anteriores a ${dia}; respuesta ${JSON.stringify(ctx)} OPT ${JSON.stringify(pos.datos)} PES ${JSON.stringify(neg.datos)}`,model,k*10+3);}
    else consensus=await call(promptFor(dia,ctx,batch,active,base),model,k);
    for(const x of consensus.datos?.llamadas||[]) collect.push({...x,_model:model});
  }
  if(active.includes('conjunto')){const by=new Map();for(const x of collect){if(!by.has(x.activo))by.set(x.activo,new Map());by.get(x.activo).set(x._model,x);}raw.push(...[...by.values()].map(v=>[...v.values()]).filter(v=>v.length>=2&&new Set(v.map(x=>x.direccion)).size===1).map(v=>({...v[0],probabilidad:v.reduce((s,x)=>s+x.probabilidad,0)/v.length})));}
  else raw.push(...collect);
 }
 const filas=[],used=new Set();for(const x of raw.slice(0,llamadas)){try{const c=cands.find(y=>y.ticker===x.activo);if(!c||used.has(x.activo))continue;if(active.includes('solo_compra')&&x.direccion!=='sube')continue;const l=validarLlamada(x,c,[]), pref=precioReferencia(c.referencia,series,dia);if(!pref)continue;used.add(x.activo);const pid=`${dia}-${c.ticker}-${l.horizonte_dias}`;let p=l.probabilidad;
  if(active.includes('calibrada'))p=Math.max(.5,Math.min(.85,p));
  const row={pid,fecha_decision:dia,tramo:0,activo:c.ticker,clase:claseDe(c.clase),horizonte_dias:l.horizonte_dias,precio_ref:l.precio_ref,referencia:c.referencia,precio_referencia:pref,tipo:l.tipo,noticias:active.includes('noticias'),noticias_disponibles:!!c.noticias?.length,modelo,variante,direccion:l.direccion,probabilidad:p,razon:l.razon,invalidacion:l.invalidacion,metodo:'vita',puntuacion_factor:feats.get(c.ticker)?.puntuacion??null,fecha_factor:feats.get(c.ticker)?.fecha_corte??null};filas.push(row);
  }catch{}}
 const baseRows=[];for(const v of filas){const x=cands.find(y=>y.ticker===v.activo);for(const [metodo,direccion] of [['siempre_sube','sube'],['momentum',x.r_1m>=0?'sube':'baja']])baseRows.push({...v,id:v.pid+'-'+metodo,metodo,direccion,probabilidad:.5,razon:'LÃ­nea base cuantitativa.'});
  const cls=claseDe(v.clase), pool=ins.instrumentos.filter(y=>claseDe(y.clase)===cls);for(let i=0;i<20;i++){const y=pool[hash(`${dia}/${v.activo}/${i}`)%pool.length];const rr=precioReferencia(y.referencia,series,dia);if(rr)baseRows.push({...v,pid:`${v.pid}-azar-${i}`,id:`${v.pid}-azar-${i}`,activo:y.ticker,clase:cls,precio_ref:y.precio,referencia:y.referencia,precio_referencia:rr,direccion:'sube',metodo:'azar_clase',probabilidad:.5});}
 }
 if(active.includes('factores'))for(const y of [...cands].sort((a,b)=>(b.puntuacion??-1e9)-(a.puntuacion??-1e9)).slice(0,5)){const rr=precioReferencia(y.referencia,series,dia);if(rr)baseRows.push({pid:`${dia}-${y.ticker}-21`,id:`${dia}-${y.ticker}-solo_factores`,fecha_decision:dia,tramo:0,activo:y.ticker,clase:claseDe(y.clase),horizonte_dias:21,precio_ref:y.precio,referencia:y.referencia,precio_referencia:rr,modelo,variante,direccion:'sube',probabilidad:.5,metodo:'solo_factores'});}
 if(active.includes('fundamentales'))for(const y of ins.instrumentos.filter(x=>x.clase==='accion'&&fundamentals.has(x.ticker)).sort((a,b)=>scoreFundamentales(fundamentals.get(b.ticker))-scoreFundamentales(fundamentals.get(a.ticker))).slice(0,5)){const rr=precioReferencia(y.referencia,series,dia);if(rr)baseRows.push({pid:`${dia}-${y.ticker}-21`,id:`${dia}-${y.ticker}-solo_fundamentales`,fecha_decision:dia,tramo:0,activo:y.ticker,clase:claseDe(y.clase),horizonte_dias:21,precio_ref:y.precio,referencia:y.referencia,precio_referencia:rr,modelo,variante,direccion:'sube',probabilidad:.5,metodo:'solo_fundamentales',puntuacion_fundamental:scoreFundamentales(fundamentals.get(y.ticker)),fundamentales:fundamentals.get(y.ticker)});}
 for(const f of [...filas,...baseRows]){const q=calificarLlamada(f,series);if(q)Object.assign(f,q,{calificada:true});else f.calificada=false;}
 return {filas:[...filas,...baseRows],stats:{dia,llamadas_validas:filas.length,variante,noticias_sin_resultado:filas.filter(x=>x.noticias&&!x.noticias_disponibles).length}};
}
export function resumen(filas,meta={}){
 const vita=filas.filter(x=>x.metodo==='vita'&&x.calificada),mean=a=>a.length?a.reduce((s,x)=>s+x,0)/a.length:null;
 const summarize=rows=>({n:rows.length,n_efectivo:new Set(rows.map(x=>x.fecha_decision)).size,acierto:mean(rows.map(x=>+x.acierto)),Brier:mean(rows.map(x=>x.brier)),exceso_promedio:mean(rows.map(x=>x.exceso))});
 const groups=k=>Object.fromEntries([...new Set(vita.map(x=>x[k]))].map(v=>[v,summarize(vita.filter(x=>x[k]===v))]));
 const byPid=new Map();for(const x of filas.filter(x=>x.calificada))if(x.metodo!=='azar_clase')byPid.set(`${x.pid}/${x.metodo}`,x);
 const comps={};for(const method of ['azar_clase','siempre_sube','momentum','solo_factores','solo_fundamentales']){const pairs=vita.map(v=>[v,method==='azar_clase'?filas.find(x=>x.pid===v.pid+'-azar-0'):byPid.get(`${v.pid}/${method}`)]).filter(x=>x[1]?.calificada);let wins=0,losses=0;for(const [v,b]of pairs){if(v.acierto&&!b.acierto)wins++;if(!v.acierto&&b.acierto)losses++;}const daysMap=new Map();for(const [v,b]of pairs){let z=daysMap.get(v.fecha_decision);if(!z)daysMap.set(v.fecha_decision,z=[0,0,0]);z[0]+=Number(v.acierto);z[1]+=Number(b.acierto);z[2]++;}const d=[...daysMap.values()], rng0=()=>{let s=1729;return()=>((s=Math.imul(s,1664525)+1013904223|0)>>>0)/4294967296},rand=rng0(),boots=[];if(d.length>=5)for(let k=0;k<1000;k++){let a=0,b=0,n=0;for(let j=0;j<d.length;j++){const z=d[Math.floor(rand()*d.length)];a+=z[0];b+=z[1];n+=z[2];}boots.push((a-b)/n);}boots.sort((a,b)=>a-b);comps[method]={n:pairs.length,dif_acierto:pairs.length?pairs.reduce((s,[v,b])=>s+Number(v.acierto)-Number(b.acierto),0)/pairs.length:null,ic95_bootstrap_dias:boots.length?[boots[25],boots[974]]:null,discordantes:{vita_gana:wins,vita_pierde:losses},mcnemar_p:mcnemar(wins,losses)};}
 return {version:2,actualizado_utc:new Date().toISOString(),...meta,...summarize(vita),comparaciones:comps,por_clase:groups('clase'),por_horizonte:groups('horizonte_dias'),por_confianza:{'0.50-0.55':summarize(vita.filter(x=>x.probabilidad<.55)), '0.55-0.70':summarize(vita.filter(x=>x.probabilidad>=.55&&x.probabilidad<.7)), '>=0.70':summarize(vita.filter(x=>x.probabilidad>=.7))},calibracion:[.5,.55,.6,.65,.7,.75,.8].map((p,i,a)=>{const r=vita.filter(x=>x.probabilidad>=p&&(i===a.length-1?x.probabilidad<=.85:x.probabilidad<a[i+1]));return{desde:p,hasta:a[i+1]??.85,...summarize(r),probabilidad_media:mean(r.map(x=>x.probabilidad))}}),bases:Object.fromEntries(['azar_clase','siempre_sube','momentum','solo_factores','solo_fundamentales'].map(m=>[m,summarize(filas.filter(x=>x.metodo===m&&x.calificada))])),veredicto:vita.length<30?'Muestra insuficiente para concluir.':'Resultado exploratorio; interpretar junto con intervalos por dÃ­a.'};
}
async function main(){const seriesFile=leerJSON(argv.series),series=seriesFile.series,uni=leerJSON(argv.universo).instrumentos,variant=argv.variante||'base',model=argv.modelo||'qwen2.5:7b';const fundamentalsFile=variant.split(',').includes('fundamentales')?leerJSON(argv.fundamentales||'fundamentales.json.gz'):null,datosFundamentales=fundamentalsFile?.datos||{};const days=tramoDe(diasHabiles(series.VT,argv.desde||'2024-01-02',argv.hasta||'2024-12-31'),Number(argv.tramo||0),Number(argv.total||20)),out=argv.salida||'salida';fs.mkdirSync(out,{recursive:true});const p=path.join(out,'filas.jsonl'),stat=path.join(out,'avance.jsonl'),done=new Set(leerJSONL(stat).map(x=>x.dia));for(const dia of days){if(done.has(dia))continue;const r=await procesarDia({dia,universo:uni,series,modelo:model,variante:variant,llamadas:Number(argv.llamadas||20),datosFundamentales});fs.appendFileSync(p,r.filas.map(JSON.stringify).join('\n')+'\n');fs.appendFileSync(stat,JSON.stringify(r.stats)+'\n');console.log(`${dia}: ${r.stats.llamadas_validas} vÃ¡lidas`);} }
if(process.argv[1]?.endsWith('experimento.mjs'))main();
