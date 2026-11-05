// Diagnóstico de GitHub Models (tarea L, 4/5-nov-2026). Desde el 3-nov, en Actions, POST a models.github.ai/inference/chat/completions
// contesta 200 text/plain «OK\r\n» en ~40 ms a cualquier modelo. Esto prueba, sin mostrar el token, QUIÉN contesta:
//  - DNS y certificado TLS del servidor (si el certificado no es de GitHub, algo intercepta la conexión);
//  - todas las cabeceras de respuesta (server, x-github-request-id, via…), con y sin seguir redirecciones;
//  - el catálogo (GET /catalog/models), el endpoint anterior de Azure, una llamada a api.github.com con el mismo token
//    (¿qué permisos trae?) y la variante por organización/usuario;
//  - el mismo POST con curl (otro cliente HTTP) para descartar un problema de fetch de Node.
// Uso: GITHUB_TOKEN=… node scripts/diagnostico_github_models.mjs [--salida archivo.json]
// Gemelo idéntico en el repo privado proyecto-wall-street (scripts/diagnostico_github_models.mjs).
import fs from 'node:fs';import tls from 'node:tls';import dns from 'node:dns/promises';import {execFileSync} from 'node:child_process';

const TOKEN=process.env.GITHUB_TOKEN||'';
const ocultar=s=>String(s??'').split(TOKEN||'\u0000').join('[token]').replace(/gh[pousr]_[\w-]+|github_pat_[\w-]+/g,'[token]');
const CUERPO=JSON.stringify({model:'openai/gpt-4.1-mini',messages:[{role:'user',content:'Responde solo {"ok":true}'}],max_tokens:20});
const BASE={'content-type':'application/json',authorization:'Bearer '+TOKEN};
const GH={accept:'application/vnd.github+json','x-github-api-version':'2022-11-28'};
const NO_MOSTRAR=/^(set-cookie|authorization)$/i;

async function probar(nombre,url,{method='POST',headers=BASE,body=CUERPO,redirect='follow'}={}){
 const t0=Date.now();
 try{
  const r=await fetch(url,{method,headers,body:method==='GET'?undefined:body,redirect});
  const texto=await r.text();
  const cab=Object.fromEntries([...r.headers].filter(([k])=>!NO_MOSTRAR.test(k)));
  return {nombre,url,metodo:method,estado:r.status,redirigido:r.redirected,url_final:r.url,ms:Date.now()-t0,tipo:r.headers.get('content-type'),cabeceras:cab,cuerpo:ocultar(texto.slice(0,300)),es_json:(()=>{try{JSON.parse(texto);return true;}catch{return false;}})()};
 }catch(e){return {nombre,url,metodo:method,error:ocultar(e.message),causa:ocultar(e.cause?.code||e.cause?.message||''),ms:Date.now()-t0};}
}
function certificado(host){
 return new Promise(res=>{const s=tls.connect({host,port:443,servername:host,timeout:8000},()=>{const c=s.getPeerCertificate();res({host,ip:s.remoteAddress,sujeto:c?.subject?.CN||null,emisor:c?.issuer?.O||c?.issuer?.CN||null,autorizado:s.authorized,valido_hasta:c?.valid_to||null});s.end();});
  s.on('error',e=>res({host,error:e.message}));s.on('timeout',()=>{res({host,error:'timeout'});s.destroy();});});
}
function conCurl(url){
 try{const out=execFileSync('curl',['-sS','-o','/dev/stdout','-w','\\n__CURL__ %{http_code} %{content_type} %{remote_ip} %{num_redirects}','-X','POST',url,'-H','content-type: application/json','-H','authorization: Bearer '+TOKEN,'-H','accept: application/vnd.github+json','-H','x-github-api-version: 2022-11-28','--data',CUERPO,'--max-time','30'],{encoding:'utf8'});
  const [cuerpo,meta]=out.split('\n__CURL__ ');const [estado,tipo,ip,redir]=(meta||'').trim().split(' ');return {cliente:'curl',estado:+estado,tipo,ip,redirecciones:+redir,cuerpo:ocultar(cuerpo.slice(0,300))};}
 catch(e){return {cliente:'curl',error:ocultar(e.message).slice(0,200)};}
}

export async function diagnosticar(){
 const out={fecha:new Date().toISOString(),repo:process.env.GITHUB_REPOSITORY||null,runner:process.env.RUNNER_NAME||null,hay_token:!!TOKEN,
  token_tipo:TOKEN.startsWith('ghs_')?'GITHUB_TOKEN de Actions (ghs_)':TOKEN.startsWith('github_pat_')?'PAT fino':TOKEN.startsWith('ghp_')?'PAT clásico':TOKEN?'otro':'ninguno',
  proxy_env:Object.fromEntries(['HTTPS_PROXY','HTTP_PROXY','https_proxy','http_proxy','NO_PROXY','NODE_USE_ENV_PROXY'].map(k=>[k,!!process.env[k]]))};
 out.dns={};for(const h of ['models.github.ai','models.inference.ai.azure.com','api.github.com']){try{out.dns[h]=(await dns.lookup(h,{all:true})).map(x=>x.address);}catch(e){out.dns[h]='error '+e.code;}}
 out.tls=[await certificado('models.github.ai'),await certificado('api.github.com')];
 out.pruebas=[
  await probar('chat basico','https://models.github.ai/inference/chat/completions'),
  await probar('chat cabeceras GitHub','https://models.github.ai/inference/chat/completions',{headers:{...BASE,...GH}}),
  await probar('chat sin seguir redirecciones','https://models.github.ai/inference/chat/completions',{headers:{...BASE,...GH},redirect:'manual'}),
  await probar('chat SIN token (control)','https://models.github.ai/inference/chat/completions',{headers:{'content-type':'application/json',...GH}}),
  await probar('chat por cuenta (recinosr)','https://models.github.ai/orgs/recinosr/inference/chat/completions',{headers:{...BASE,...GH}}),
  await probar('catalogo','https://models.github.ai/catalog/models',{method:'GET',headers:{authorization:'Bearer '+TOKEN,...GH}}),
  await probar('endpoint anterior Azure','https://models.inference.ai.azure.com/chat/completions',{body:JSON.stringify({model:'gpt-4o-mini',messages:[{role:'user',content:'Responde solo {"ok":true}'}],max_tokens:20})}),
  await probar('api.github.com /rate_limit (mismo token)','https://api.github.com/rate_limit',{method:'GET',headers:{authorization:'Bearer '+TOKEN,...GH}})
 ];
 out.curl=conCurl('https://models.github.ai/inference/chat/completions');
 // Lectura: ¿algún endpoint de inferencia devolvió JSON con choices?
 const ok=out.pruebas.find(p=>p.es_json&&/choices/.test(p.cuerpo||''));
 const okJSON=out.pruebas.filter(p=>/chat/.test(p.nombre)&&p.estado===200&&!p.es_json);
 out.veredicto=ok?`FUNCIONA: «${ok.nombre}» devolvió inferencia JSON`:okJSON.length?'200 sin JSON en los endpoints de chat: no es inferencia (ver cabeceras/servidor)':'sin inferencia (ver estados)';
 return out;
}
const i=process.argv.indexOf('--salida');
if(import.meta.url===`file://${process.argv[1]}`){
 const d=await diagnosticar();const txt=JSON.stringify(d,null,1);console.log(txt);
 if(i>0&&process.argv[i+1])fs.writeFileSync(process.argv[i+1],txt+'\n');
}
