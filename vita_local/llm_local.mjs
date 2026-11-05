// Modo «local ilimitado» de Vita (3-nov-2026; tarea L 5-nov): un modelo pequeño (Ollama, qwen 7B cuantizado, CPU) corre en GitHub Actions
// de este repo PÚBLICO (minutos sin límite en repos públicos) para generar paráfrasis de preguntas y juzgar respuestas sin cuota.
// REGLA: aquí solo entran preguntas públicas (entrenamiento/desarrollo del laboratorio o escritas a mano). Nada del examen oculto
// ni de la validación sellada; ningún secreto. Lo que diga el modelo es dato a revisar, no evidencia.
// Uso: OLLAMA_URL=http://127.0.0.1:11434 node vita_local/llm_local.mjs <parafrasis|juez|juez-examen|prueba> [entrada.json]
// El ciclo horario automático es vita_local/ciclo.mjs.
import fs from 'node:fs';import path from 'node:path';
import {chat,MODELO,DIR,promptParafrasis,juzgarExamen} from './comun.mjs';
const [tarea='prueba',archivo]=process.argv.slice(2);
const lista=a=>(a||[]).map(c=>`- ${c}`).join('\n')||'- (ninguno)';
const promptJuez=x=>`Eres un juez estricto. Pregunta: "${x.pregunta}"\nRespuesta de la asistente: "${x.respuesta}"\n\nCriterios obligatorios:\n${lista(x.criterios_obligatorios)}\n\nErrores graves (si aparece cualquiera es INCORRECTA):\n${lista(x.errores_graves)}\n\nCalifica: CORRECTA si cumple todos los criterios y no tiene errores graves; PARCIAL si no tiene errores graves pero falta algún criterio; INCORRECTA si tiene un error grave o no contesta. Responde solo JSON {"veredicto":"CORRECTA|PARCIAL|INCORRECTA","razon":"<15 palabras"}`;
const PRUEBA=[{id:'prueba-1',pregunta:'¿Qué es un ETF de acumulación?',respuesta:'Un ETF de acumulación reinvierte los dividendos dentro del fondo en lugar de pagarlos.',criterios_obligatorios:['Dice que reinvierte los dividendos'],errores_graves:['Dice que paga los dividendos en efectivo']},
 {id:'prueba-2',pregunta:'¿Conviene vender todo cuando la bolsa cae 20 %?',respuesta:'Sí, vendé todo y esperá a que baje más.',criterios_obligatorios:['No recomienda vender por pánico'],errores_graves:['Recomienda vender todo']}];
const entrada=archivo?JSON.parse(fs.readFileSync(archivo,'utf8')):PRUEBA;
if(!Array.isArray(entrada)||entrada.length>200)throw Error('La entrada debe ser una lista de hasta 200 elementos');
const out={fecha:new Date().toISOString(),modelo:MODELO,tarea,entrada:archivo?path.basename(archivo):null,filas:[]};const t0=Date.now();
for(const x of entrada){const t=Date.now();
 if(tarea==='parafrasis'){const d=await chat(promptParafrasis(x.pregunta),{temperatura:0.8});out.filas.push({id:x.id,original:x.pregunta,parafrasis:(d?.parafrasis||[]).filter(s=>typeof s==='string').slice(0,3),segundos:(Date.now()-t)/1000});}
 else if(tarea==='juez-examen'){out.filas.push({...(await juzgarExamen(x)),segundos:(Date.now()-t)/1000});}
 else{const d=await chat(promptJuez(x),{temperatura:0,max:120});out.filas.push({id:x.id,veredicto:['CORRECTA','PARCIAL','INCORRECTA'].includes(d?.veredicto)?d.veredicto:'SIN_JUEZ',razon:d?.razon||null,esperado:x.esperado??null,segundos:(Date.now()-t)/1000});}
}
out.segundos_total=(Date.now()-t0)/1000;
const dir=path.join(DIR,'salida');fs.mkdirSync(dir,{recursive:true});
const f=path.join(dir,archivo&&tarea==='juez-examen'?`juez-examen-${path.basename(archivo)}`:`${tarea}-${out.fecha.slice(0,10)}.json`);fs.writeFileSync(f,JSON.stringify(out,null,1)+'\n');
console.log(JSON.stringify({tarea,modelo:MODELO,n:out.filas.length,segundos_total:out.segundos_total,archivo:path.relative(process.cwd(),f)}));
