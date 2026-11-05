// node --test tests/vita_local.test.mjs — modo local de Vita (tarea L, 5-nov-2026).
import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';
import {criterioExamen,promptExaminador,promptJuezExamen} from '../vita_local/comun.mjs';
const ruta=f=>new URL('../vita_local/entrada/'+f,import.meta.url);const leer=f=>JSON.parse(fs.readFileSync(ruta(f),'utf8'));
const hay=f=>fs.existsSync(ruta(f));
test('publicas.json solo trae entrenamiento/desarrollo y nada sellado', {skip:!hay('publicas.json')&&'sin publicas.json'}, ()=>{
 const p=leer('publicas.json').preguntas;assert.ok(p.length>500);
 assert.ok(p.every(x=>['realista_v3','gimnasio_v2','reglas_trampas'].includes(x.origen)));
 assert.ok(!JSON.stringify(p).includes('"validacion":true'));assert.ok(!/sellad/i.test(JSON.stringify(p)));
});
test('hechos públicos: cita y dato, sin enlaces', {skip:!hay('hechos_publicos.json')&&'sin hechos_publicos.json'}, ()=>{
 const h=leer('hechos_publicos.json').hechos;assert.ok(h.length>=10);
 for(const x of h.filter(x=>x.tipo==='dato')){assert.ok(x.cita.length>=12);assert.ok(x.dato_obligatorio.length);assert.ok(!/https?:/.test(x.cita));}
});
test('juez del examen: criterio por tipo y la clave no sale del modelo', ()=>{
 assert.match(criterioExamen({tipo:'rechazar'}),/NEGARSE/);assert.match(criterioExamen({tipo:'abstenerse'}),/no se puede saber/);
 assert.match(criterioExamen({tipo:'dato',dato_obligatorio:['US$30'],cita:'Retirar menos de US$100 cuesta US$30'}),/US\$30/);
 assert.match(promptJuezExamen({tipo:'dato',pregunta:'p',respuesta:'r',dato_obligatorio:['x']}),/"veredicto"/);
 assert.match(promptExaminador({tipo:'dato',cita:'Conversión de moneda: 0.5 %',dato_obligatorio:['0.5 %']},3),/formal.*informal.*indirecta/s);
});
