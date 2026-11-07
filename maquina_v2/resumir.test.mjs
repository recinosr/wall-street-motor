import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

test('resumir acepta y marca un tramo parcial en carpeta PIT propia',()=>{
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'resumir-pit-'));
 try{
  const input=path.join(tmp,'artefactos','tramo-01','solo_compra,factores');
  fs.mkdirSync(input,{recursive:true});fs.writeFileSync(path.join(input,'filas.jsonl'),'');
  const script=fileURLToPath(new URL('./resumir.mjs',import.meta.url));
  const r=spawnSync(process.execPath,[script,'--artefactos=artefactos','--modelo=qwen2.5:7b','--variantes=solo_compra,factores','--desde=2025-01-02','--hasta=2026-10-16','--llamadas=10','--universo_pit=true'],{cwd:tmp,encoding:'utf8'});
  assert.equal(r.status,0,r.stderr);
  const out=JSON.parse(fs.readFileSync(path.join(tmp,'resultados','maquina_v2','qwen2.5_7b','solo_compra,factores_pit','resumen.json'),'utf8'));
  assert.equal(out.tramos_disponibles,1);assert.equal(out.tramos_esperados,20);assert.equal(out.parcial,true);assert.equal(out.universo_pit,true);
 }finally{fs.rmSync(tmp,{recursive:true,force:true});}
});
