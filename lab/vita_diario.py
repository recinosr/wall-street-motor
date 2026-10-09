"""Diario determinista de resultados publicados. No llama a un LLM ni abre velas."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path


def build(directory,day):
    root=Path(directory);data={};sources={};failures=[]
    for name in ('marcador','enciclopedia','demo_cripto','robots','carteras_robots'):
        p=root/(name+'.json')
        try:
            raw=p.read_bytes();value=json.loads(raw);data[name]=value
            stamp=value.get('actualizado') or value.get('observado_en') or value.get('as_of')
            sources[name]={'sha256':hashlib.sha256(raw).hexdigest(),'fecha':stamp,'actualizado_hoy':str(stamp or '').startswith(day)}
        except (OSError,ValueError):failures.append(name)
    m=data.get('marcador',{});e=data.get('enciclopedia',{});demo=data.get('demo_cripto',{});robots=data.get('robots',{})
    forecasts=[{k:x.get(k) for k in ('predictor','tipo','horizonte','n','acierto_pct','brier','ic95_descriptivo')}
               for x in m.get('acumulado',[]) if x.get('sector')=='Todos']
    accounts={s:{k:a.get(k) for k in ('initial','net_liquidation','hold_equity','vs_hold','fees','quote_time')}
              for s,a in demo.get('accounts',{}).items()}
    tested=[{'fuente':name,'descripcion':{'marcador':'Registro y calificación de pronósticos publicados con recibo',
              'demo_cripto':'Observación de reglas cripto en cuentas ficticias',
              'enciclopedia':'Pruebas históricas de patrones', 'robots':'Banco histórico de robots públicos',
              'carteras_robots':'Comparación retrospectiva de reglas sistemáticas'}[name],'fecha_resultado':s['fecha']}
            for name,s in sources.items() if s['actualizado_hoy']]
    learned={'etiquetas_pronostico':m.get('etiquetas',0),'aciertos':forecasts,
             'patrones_contrastes':e.get('pruebas_BH'),'patrones_pasan':e.get('pruebas_pasan_BH'),
             'robots_contrastes':robots.get('pruebas_declaradas'),'robots_casos':len(robots.get('casos',[])),
             'decisiones_demo_acumuladas':demo.get('total_decisions',0),'cuentas_demo':accounts}
    return {'version':1,'fecha':day,'fuentes':sources,'fuentes_no_disponibles':failures,
            'que_probo_hoy':tested,'que_aprendio':learned,
            'que_piensa_probar_manana':['Seguir las reglas publicadas y esperar etiquetas maduras; no se cambia la política ni se crea un ensayo nuevo.'],
            'como_voy':{'pronosticos':forecasts,'demo_contra_mantener':accounts},
            'aviso':'Resumen determinista de resultados disponibles, no reflexión de un LLM. Una fuente con fecha anterior no es una prueba hecha hoy. Acumulados no son aciertos del día. Sin etiquetas maduras, aún no se puede medir precisión. No hay ventaja futura demostrada.'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--resultados',default='resultados');p.add_argument('--fecha',default=dt.datetime.now(dt.timezone(dt.timedelta(hours=-6))).date().isoformat());a=p.parse_args()
    value=build(a.resultados,a.fecha);root=Path(a.resultados);root.mkdir(parents=True,exist_ok=True)
    text=json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n'
    (root/'vita_diario.json').write_text(text,encoding='utf8')
    archive=root/'vita_diario';archive.mkdir(exist_ok=True);(archive/(a.fecha+'.json')).write_text(text,encoding='utf8')
    print('Diario',a.fecha,'fuentes',len(value['fuentes']),'no disponibles',len(value['fuentes_no_disponibles']))


if __name__=='__main__':main()
