import fs from 'node:fs';import {leerJSON} from '../maquina_ilimitada/lib.mjs';import {escogerPares,probar} from '../maquina_ilimitada/memoria.mjs';
const a=Object.fromEntries(process.argv.slice(2).map(x=>x.replace(/^--/,'').split('=')));const u=leerJSON(a.universo).instrumentos,s=leerJSON(a.series).series;
const pares=escogerPares(u,s,20,a.desde,a.hasta);const r=await probar(pares,a.modelo);fs.writeFileSync(a.salida,JSON.stringify({...r,periodo:{desde:a.desde,hasta:a.hasta}},null,2)+'\n');console.log(`Prueba de memoria: ${r.aciertos}/${r.n}; contaminado=${r.contaminado}`);
