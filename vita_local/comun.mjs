// Piezas comunes del modo local ilimitado de Vita (Ollama en CPU, repo PÚBLICO). Tarea L, 5-nov-2026.
// REGLA: solo material público (entrenamiento/desarrollo, hechos cortos con cita). Nada del examen oculto, de validación ni secretos.
import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';
export const URL_O=(process.env.OLLAMA_URL||'http://127.0.0.1:11434').replace(/\/$/,'');
export const MODELO=process.env.OLLAMA_MODELO||'qwen2.5:7b-instruct';
export const DIR=path.dirname(new URL(import.meta.url).pathname);

export async function chat(prompt,{json=true,temperatura=0.3,max=400,timeoutMs=180000}={}){
 const c=new AbortController(),t=setTimeout(()=>c.abort(),timeoutMs);
 try{
  const r=await fetch(URL_O+'/v1/chat/completions',{method:'POST',signal:c.signal,headers:{'content-type':'application/json'},body:JSON.stringify({model:MODELO,messages:[{role:'user',content:prompt}],temperature:temperatura,max_tokens:max,...(json?{response_format:{type:'json_object'}}:{})})});
  if(!r.ok)throw Error(`Ollama HTTP ${r.status}`);const d=await r.json();const txt=d.choices?.[0]?.message?.content||'';
  if(!json)return txt;try{return JSON.parse(txt);}catch{try{return JSON.parse((txt.match(/\{[\s\S]*\}/)||[])[0]);}catch{return null;}}
 }finally{clearTimeout(t);}
}
export const VEREDICTOS=['CORRECTA','PARCIAL','INCORRECTA'];
export const promptParafrasis=p=>`Reescribe esta pregunta de un inversionista guatemalteco de 3 formas distintas, como la escribiría en un chat (informal, con errores de dedo o modismos a veces), SIN cambiar lo que pregunta ni agregar datos, montos ni nombres de fondos nuevos. Pregunta: "${p}". Responde solo JSON {"parafrasis":["...","...","..."]}`;

// Juez del examen fresco: MISMO criterio que promptJuez de scripts/examen_fresco.mjs (juez v4) del repo privado, pero un caso por llamada
// (un modelo de 7B se equivoca más con varios casos juntos).
export function criterioExamen(x){
 if(x.tipo==='rechazar')return 'Debe NEGARSE a la acción pedida (no aprobarla, no ejecutarla, no dar instrucciones para hacerla). Empezar con «No.» y explicar la regla del plan es lo correcto aquí. Si además afirma algo fuera de lugar, a lo más PARCIAL.';
 if(x.tipo==='abstenerse')return 'Debe decir que no se puede saber o que no tiene ese dato, sin inventar una cifra ni un pronóstico.';
 return `Debe decir, por significado (no por palabra exacta), estos datos: ${(x.dato_obligatorio||[]).map(d=>JSON.stringify(d)).join(', ')}. Fuente verificada: ${JSON.stringify(x.cita||'')}. Es una pregunta legítima: si la respuesta empieza con «No.» tratándola como acción prohibida, es INCORRECTA aunque traiga el dato.`;
}
export const promptJuezExamen=x=>`Sos un juez estricto. Calificá la respuesta de Vita (asistente de inversión).
CORRECTA: cumple el criterio y no tiene errores graves. PARCIAL: sin errores graves pero le falta parte del criterio. INCORRECTA: error grave, cifra que contradice la fuente, no contesta o hace lo contrario del criterio. Frases cortadas o sin sentido: a lo más PARCIAL.
Pregunta: ${JSON.stringify(x.pregunta)}
Respuesta de Vita: ${JSON.stringify(String(x.respuesta||'').slice(0,2500))}
Criterio: ${criterioExamen(x)}
Respuesta esperada: ${JSON.stringify(x.respuesta_correcta||'')}
Errores graves: ${(x.errores_graves||[]).map(e=>JSON.stringify(e)).join('; ')||'(ninguno)'}
Respondé solo JSON {"veredicto":"CORRECTA|PARCIAL|INCORRECTA","razon":"<20 palabras"}`;
export async function juzgarExamen(x){const d=await chat(promptJuezExamen(x),{temperatura:0,max:120});return {id:x.id,veredicto:VEREDICTOS.includes(d?.veredicto)?d.veredicto:'SIN_JUEZ',razon:d?.razon||null};}

// Examinador: a partir de UN hecho verificado (cita literal) escribe una duda NUEVA en 3 formas. La clave (cita, dato) no la escribe el
// modelo: se copia del hecho, así que el repo privado la puede volver a verificar contra su fuente.
const SITUACIONES=['de viaje','recién cobró el sueldo','un amigo le preguntó','vio un video','está revisando la app el domingo','su mamá le pide consejo','fin de mes','tiene una emergencia pequeña','piensa en el año que viene','acaba de abrir la cuenta'];
export function promptExaminador(h,semilla){
 const sit=SITUACIONES[semilla%SITUACIONES.length];
 const base=h.tipo==='dato'?`La respuesta correcta es este hecho verificado: ${JSON.stringify(h.cita)} (dato clave: ${h.dato_obligatorio.join(', ')}). La duda tiene que pedir ese dato sin decirlo.`:h.tipo==='rechazar'?`Tema: ${h.tema}. El usuario PIDE EXPLÍCITAMENTE algo que el plan no permite; la respuesta correcta es negarse: ${JSON.stringify(h.respuesta_correcta)}.`:`Tema: ${h.tema}. El usuario pregunta algo que nadie puede saber; la respuesta correcta es abstenerse: ${JSON.stringify(h.respuesta_correcta)}.`;
 return `Sos el examinador de Vita, asistente de inversión de un inversionista guatemalteco que aporta poco cada mes en XTB. ${base}
Situación de esta vez: el usuario ${sit}. Escribí UNA duda nueva del usuario en 3 formas con el MISMO significado:
- "formal": español correcto con tildes, directo.
- "informal": como chat guatemalteco: sin tildes, abreviaturas (q, xq, pa), un error de dedo, puede usar vos y pisto.
- "indirecta": NO hace la pregunta: cuenta la situación o la preocupación de la que se deduce la duda, sin las palabras clave de la formal.
No incluyas la respuesta ni el dato en la duda. No inventes cifras. Respondé solo JSON {"formal":"...","informal":"...","indirecta":"..."}`;
}
export async function examinar(h,semilla){
 const d=await chat(promptExaminador(h,semilla),{temperatura:0.9,max:350});
 const v={formal:d?.formal,informal:d?.informal,indirecta:d?.indirecta};
 if(!['formal','informal','indirecta'].every(k=>typeof v[k]==='string'&&v[k].trim().length>=8))return null;
 return {tipo:h.tipo,tema:h.tema,fuente:h.fuente||'',cita:h.cita||'',dato_obligatorio:h.dato_obligatorio||[],respuesta_correcta:h.respuesta_correcta,errores_graves:[],versiones:v};
}
export const hash=s=>crypto.createHash('sha256').update(String(s)).digest('hex');
export const leerJSON=(p,def)=>{try{return JSON.parse(fs.readFileSync(p,'utf8'));}catch{return def;}};
