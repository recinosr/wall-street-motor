function facts(company, names) { for(const name of names){const f=company?.facts?.['us-gaap']?.[name];if(f)return f;}return null; }
function quarterly(company,names,decision) {
  const found=company?.[names[0]]||facts(company,names), units=found?.units||{}; const entries=(Array.isArray(found)?found:Object.values(units).flat()).filter(x=>x.filed<decision&&x.end<decision&&x.val!=null);
  const q=entries.filter(x=>x.start&&(Date.parse(x.end)-Date.parse(x.start))/86400000>=70&&(Date.parse(x.end)-Date.parse(x.start))/86400000<=110).sort((a,b)=>b.end.localeCompare(a.end)||b.filed.localeCompare(a.filed));
  // 10-Q YTD facts for Q2/Q3: derive the standalone quarter from prior YTD filing.
  const ytd=entries.filter(x=>x.start&&(Date.parse(x.end)-Date.parse(x.start))/86400000>110&&(Date.parse(x.end)-Date.parse(x.start))/86400000<300).sort((a,b)=>b.end.localeCompare(a.end)||b.filed.localeCompare(a.filed));
  for(const cur of ytd){const prev=ytd.filter(x=>x.fy===cur.fy&&x.end<cur.end&&x.filed<=cur.filed).sort((a,b)=>b.end.localeCompare(a.end))[0];if(prev)q.push({...cur,val:cur.val-prev.val});}
  const byEnd=new Map();for(const x of q){const prev=byEnd.get(x.end);if(!prev||x.filed>prev.filed)byEnd.set(x.end,x);}return [...byEnd.values()].sort((a,b)=>b.end.localeCompare(a.end));
}
export function rasgosFundamentales(company,decision) {
  const rev=quarterly(company,['ingresos','RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet'],decision);
  const eps=quarterly(company,['bpa_diluido','EarningsPerShareDiluted'],decision);
  const op=quarterly(company,['utilidad_operativa','OperatingIncomeLoss'],decision);
  const net=quarterly(company,['utilidad_neta','NetIncomeLoss','ProfitLoss'],decision);
  const yearAgo=a=>a.length? a.find(x=>{const d=(Date.parse(a[0].end)-Date.parse(x.end))/86400000;return d>=330&&d<=400;}):null;
  const yoy=(a)=>{const old=yearAgo(a);return a.length&&old&&old.val!==0?a[0].val/old.val-1:null;};
  const margin=op.length&&rev.find(x=>x.end===op[0].end)&&rev.find(x=>x.end===op[0].end).val!==0?op[0].val/rev.find(x=>x.end===op[0].end).val:null;
  const oldOp=yearAgo(op),oldRev=oldOp&&rev.find(x=>x.end===oldOp.end),priorMargin=oldOp&&oldRev&&oldRev.val!==0?oldOp.val/oldRev.val:null;
  const filed=[...rev,...eps,...op,...net].map(x=>x.filed).filter(x=>x<decision).sort();
  if(!filed.length)return null;
  const age=Math.floor((Date.parse(decision)-Date.parse(filed.at(-1)))/86400000);
  return {crecimiento_ingresos_yoy:yoy(rev),crecimiento_utilidad_neta_yoy:yoy(net),crecimiento_eps_diluido_yoy:yoy(eps),margen_operativo:margin,cambio_margen_operativo_yoy:margin!=null&&priorMargin!=null?margin-priorMargin:null,dias_desde_reporte:age,fecha_ultimo_reporte:filed.at(-1)};
}
export function scoreFundamentales(f){return (f?.crecimiento_ingresos_yoy??0)+(f?.crecimiento_eps_diluido_yoy??0)+(f?.cambio_margen_operativo_yoy??0);}
