import test from 'node:test';
import assert from 'node:assert/strict';
import {rasgosFundamentales,scoreFundamentales} from './fundamentales.mjs';

const company=(filed,rev,eps,op)=>({facts:{'us-gaap':{
 RevenueFromContractWithCustomerExcludingAssessedTax:{units:{USD:[{start:'2024-01-01',end:'2024-03-31',filed:'2024-05-01',val:100},{start:'2025-01-01',end:'2025-03-31',filed,val:rev},{start:'2025-04-01',end:'2025-06-30',filed,val:120},{start:'2025-01-01',end:'2025-06-30',filed,val:220},{start:'2024-04-01',end:'2024-06-30',filed:'2024-08-01',val:90}] }},
 EarningsPerShareDiluted:{units:{'USD / shares':[ {start:'2024-01-01',end:'2024-03-31',filed:'2024-05-01',val:1},{start:'2025-01-01',end:'2025-03-31',filed,val:eps}] }},
 OperatingIncomeLoss:{units:{USD:[{start:'2024-01-01',end:'2024-03-31',filed:'2024-05-01',val:10},{start:'2025-01-01',end:'2025-03-31',filed,val:op}]}}
}}});
test('companyfacts solo usa filed anterior a la fecha de decisión',()=>{
 const before=rasgosFundamentales(company('2025-04-20',130,2,26),'2025-05-01');
 const later=company('2025-04-20',130,2,26);for(const [tag,val] of [['RevenueFromContractWithCustomerExcludingAssessedTax',9999],['EarningsPerShareDiluted',99],['OperatingIncomeLoss',9999]])later.facts['us-gaap'][tag].units[tag==='EarningsPerShareDiluted'?'USD / shares':'USD'].push({start:'2025-01-01',end:'2025-03-31',filed:'2025-05-02',val});
 const changedFuture=rasgosFundamentales(later,'2025-05-01');
 assert.deepEqual(changedFuture,before);
 assert.ok(Math.abs(before.crecimiento_ingresos_yoy-.3)<1e-12);
 assert.equal(before.margen_operativo,.2);
 assert.ok(before.dias_desde_reporte>0);
});
test('puntuación combina crecimiento y mejora del margen',()=>assert.ok(Math.abs(scoreFundamentales({crecimiento_ingresos_yoy:.1,crecimiento_eps_diluido_yoy:.2,cambio_margen_operativo_yoy:.03})-.33)<1e-12));
test('el extracto SEC compacto conserva filed y calcula rasgos sin companyfacts completo',()=>{
 const compacto={
  ingresos:[{start:'2024-01-01',end:'2024-03-31',filed:'2024-05-01',fy:2024,fp:'Q1',val:100},{start:'2025-01-01',end:'2025-03-31',filed:'2025-04-20',fy:2025,fp:'Q1',val:130}],
  utilidad_operativa:[{start:'2024-01-01',end:'2024-03-31',filed:'2024-05-01',val:10},{start:'2025-01-01',end:'2025-03-31',filed:'2025-04-20',val:26}],
  utilidad_neta:[{start:'2024-01-01',end:'2024-03-31',filed:'2024-05-01',val:8},{start:'2025-01-01',end:'2025-03-31',filed:'2025-04-20',val:12}],
  bpa_diluido:[{start:'2024-01-01',end:'2024-03-31',filed:'2024-05-01',val:1},{start:'2025-01-01',end:'2025-03-31',filed:'2025-04-20',val:2}],
 };
 const before=rasgosFundamentales(compacto,'2025-05-01');
 assert.ok(Math.abs(before.crecimiento_ingresos_yoy-.3)<1e-12);
 assert.ok(Math.abs(before.crecimiento_utilidad_neta_yoy-.5)<1e-12);
 assert.ok(Math.abs(before.crecimiento_eps_diluido_yoy-1)<1e-12);
 assert.equal(before.margen_operativo,.2);
 assert.equal(rasgosFundamentales(compacto,'2025-04-20').fecha_ultimo_reporte,'2024-05-01');
});
