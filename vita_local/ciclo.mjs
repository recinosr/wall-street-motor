// Ciclo horario del modo local ilimitado de Vita (tarea L, 5-nov-2026). Corre en Actions de este repo PÚBLICO (minutos sin límite)
// con Ollama en CPU. Sin llaves, sin cuota de nadie. Hace, en este orden y hasta agotar CICLO_MINUTOS:
//  1. JUEZ: casos en vita_local/entrada/juzgar/*.json que aún no tengan veredicto -> resultados/vita_local/juez/<archivo>.
//  2. EXAMINADOR: CICLO_GRUPOS grupos nuevos del examen fresco (misma duda en 3 formas) a partir de hechos_publicos.json
//     -> resultados/vita_local/examen_pool.json. La clave (cita/dato) se copia del hecho; el repo privado la vuelve a verificar
//     contra su fuente y descarta lo que ya vio Vita.
//  3. PARÁFRASIS: preguntas públicas (publicas.json, solo entrenamiento/desarrollo) en orden rotativo, 3 por pregunta
//     -> resultados/vita_local/parafrasis/AAAA-MM-DD.jsonl y la ventana resultados/vita_local/practica.json.
// El repo privado lee resultados/vita_local/* por raw.githubusercontent.com (este repo no puede leer el privado).
import fs from 'node:fs';import path from 'node:path';
import {chat,MODELO,DIR,promptParafrasis,juzgarExamen,examinar,hash,leerJSON} from './comun.mjs';
const RAIZ=path.resolve(DIR,'..'),OUT=path.join(RAIZ,'resultados/vita_local');fs.mkdirSync(path.join(OUT,'parafrasis'),{recursive:true});fs.mkdirSync(path.join(OUT,'juez'),{recursive:true});
const T0=Date.now(),LIMITE=T0+(+process.env.CICLO_MINUTOS||40)*60000,GRUPOS=+process.env.CICLO_GRUPOS||6,MAX_PARAF=+process.env.CICLO_PARAFRASIS||80;
const quedan=()=>LIMITE-Date.now();
const escribir=(f,d)=>fs.writeFileSync(f,JSON.stringify(d,null,1)+'\n');
const estadoPath=path.join(OUT,'estado.json'),estado=leerJSON(estadoPath,{cursor:0,semilla:0});
const ciclo={fecha:new Date().toISOString(),modelo:MODELO,juzgados:0,grupos:0,grupos_fallidos:0,parafrasis:0,parafrasis_fallidas:0,revisar:0};

// 1) Juez
const dirJ=path.join(DIR,'entrada/juzgar');
for(const f of fs.existsSync(dirJ)?fs.readdirSync(dirJ).filter(f=>f.endsWith('.json')).sort():[]){
 const salida=path.join(OUT,'juez',f);if(fs.existsSync(salida))continue;
 const casos=leerJSON(path.join(dirJ,f),[]);if(!Array.isArray(casos))continue;
 const filas=[];for(const x of casos.slice(0,200)){if(quedan()<5*60000)break;const t=Date.now();filas.push({...(await juzgarExamen(x)),segundos:(Date.now()-t)/1000});}
 if(filas.length===Math.min(casos.length,200)){escribir(salida,{fecha:new Date().toISOString(),modelo:MODELO,entrada:f,filas});ciclo.juzgados+=filas.length;}
}

// 2) Examinador
const hechos=leerJSON(path.join(DIR,'entrada/hechos_publicos.json'),{hechos:[]}).hechos||[];
const poolPath=path.join(OUT,'examen_pool.json'),pool=leerJSON(poolPath,{grupos:[]});
for(let k=0;k<GRUPOS&&hechos.length&&quedan()>8*60000;k++){
 const s=estado.semilla++,h=hechos[(s*7+3)%hechos.length];
 const g=await examinar(h,Math.floor(s/hechos.length)+s);
 if(g){pool.grupos.push({id:'ol-'+hash(JSON.stringify(g.versiones)).slice(0,12),fecha:new Date().toISOString(),modelo:MODELO,...g});ciclo.grupos++;}else ciclo.grupos_fallidos++;
}
pool.grupos=pool.grupos.slice(-400);pool.actualizado=new Date().toISOString();pool.nota='Grupos del examinador local (Ollama). El repo privado verifica la cita y descarta lo ya visto.';escribir(poolPath,pool);

// 3) Paráfrasis
const pub=leerJSON(path.join(DIR,'entrada/publicas.json'),{preguntas:[]}).preguntas||[];
const dia=new Date().toISOString().slice(0,10),diario=path.join(OUT,'parafrasis',`${dia}.jsonl`),nuevas=[];
const tickers=s=>new Set((String(s).match(/\b[A-Z]{2,5}\b|\d+/g)||[]));
while(pub.length&&nuevas.length<MAX_PARAF&&quedan()>60000){
 const x=pub[estado.cursor%pub.length];estado.cursor=(estado.cursor+1)%pub.length;const t=Date.now();
 const d=await chat(promptParafrasis(x.pregunta),{temperatura:0.8}).catch(()=>null);
 const ps=[...new Set((d?.parafrasis||[]).filter(s=>typeof s==='string'&&s.trim().length>=8&&s.trim()!==x.pregunta.trim()).map(s=>s.trim()))].slice(0,3);
 if(!ps.length){ciclo.parafrasis_fallidas++;continue;}
 const orig=tickers(x.pregunta),revisar=ps.some(p=>[...tickers(p)].some(t=>!orig.has(t)));if(revisar)ciclo.revisar++;
 const fila={id:x.id,origen:x.origen,original:x.pregunta,parafrasis:ps,revisar,fecha:new Date().toISOString(),segundos:(Date.now()-t)/1000};
 fs.appendFileSync(diario,JSON.stringify(fila)+'\n');nuevas.push(fila);ciclo.parafrasis++;
}
const practicaPath=path.join(OUT,'practica.json'),practica=leerJSON(practicaPath,{filas:[]});
practica.filas=[...practica.filas,...nuevas].slice(-1500);practica.actualizado=new Date().toISOString();practica.modelo=MODELO;
practica.nota='Paráfrasis de preguntas PÚBLICAS (entrenamiento/desarrollo). revisar=true: la paráfrasis trae una cifra o sigla que no estaba en la original.';escribir(practicaPath,practica);

estado.actualizado=new Date().toISOString();escribir(estadoPath,estado);
ciclo.segundos=(Date.now()-T0)/1000;fs.appendFileSync(path.join(OUT,'ciclos.jsonl'),JSON.stringify(ciclo)+'\n');
console.log(JSON.stringify(ciclo));
