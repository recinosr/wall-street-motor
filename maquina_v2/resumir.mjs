import fs from 'node:fs';import path from 'node:path';import {leerJSONL} from '../maquina_ilimitada/lib.mjs';import {resumen} from './experimento.mjs';
const a=Object.fromEntries(process.argv.slice(2).map(x=>x.replace(/^--/,'').split('=')));
const variants=(a.variantes||'solo_compra,factores').split(';').filter(Boolean), root=a.artefactos||'artefactos';const all=[];
for(const variant of variants){const vrows=[];for(let i=0;i<20;i++){vrows.push(...leerJSONL(path.join(root,`tramo-${String(i).padStart(2,'0')}`,variant,'filas.jsonl')));}const r=resumen(vrows,{modelo:a.modelo,variante:variant,periodo:{desde:a.desde,hasta:a.hasta},llamadas_por_dia:Number(a.llamadas||20)});const slug=(a.modelo||'qwen2.5:7b').replace(/[:/]/g,'_');const dir=path.join('resultados','maquina_v2',slug,variant);fs.mkdirSync(dir,{recursive:true});fs.writeFileSync(path.join(dir,'resumen.json'),JSON.stringify(r,null,2)+'\n');all.push({variant,r});}
const cells=all.map(({variant,r})=>`| ${variant} | ${r.n} | ${r.n_efectivo} | ${r.acierto==null?'n/d':(100*r.acierto).toFixed(1)+' %'} | ${r.Brier?.toFixed(4)??'n/d'} | ${r.exceso_promedio==null?'n/d':(100*r.exceso_promedio).toFixed(2)+' %'} | ${r.veredicto} |`);fs.mkdirSync('resultados/maquina_v2',{recursive:true});fs.writeFileSync('resultados/maquina_v2/tabla.md',`# Comparación VITA v2\n\nModelo: ${a.modelo}; periodo ${a.desde} a ${a.hasta}. Los resultados permanecen vacíos hasta ejecutar la corrida autorizada.\n\n| Variante | n | Días efectivos | Acierto | Brier | Exceso medio | Veredicto |\n|---|---:|---:|---:|---:|---:|---|\n${cells.join('\n')}\n`);
if(variants.some(v=>v.split(',').includes('fundamentales'))){
 const runId=process.env.GITHUB_RUN_ID||'no-disponible';
 const f=all.find(x=>x.variant==='solo_compra,fundamentales,factores')||all.find(x=>x.variant.split(',').includes('fundamentales'));
 const fundamental=f?.r?.bases?.solo_fundamentales;
 const pct=x=>x==null?'n/d':`${(100*x).toFixed(2)} %`;
 const report=`# Reporte de la variante fundamentales\n\nRun de GitHub Actions: ${runId}\n\n- Modelo: ${a.modelo}\n- Período: ${a.desde} a ${a.hasta}\n- Variantes: ${variants.join(', ')}\n- Llamadas por día: ${a.llamadas}\n- Observaciones base solo_fundamentales: ${fundamental?.n??0}\n- Acierto: ${pct(fundamental?.acierto)}\n- Exceso promedio: ${pct(fundamental?.exceso_promedio)}\n\nLos rasgos fundamentales usan solo registros SEC EDGAR con filed anterior a cada fecha de decisión.\n`;
 fs.writeFileSync(path.join('maquina_v2','REPORTE_fundamentales.md'),report);
}
