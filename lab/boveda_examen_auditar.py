"""Sensibilidad posmedición: signos de bloques, sin cambiar ganador/protocolo."""
import json
import numpy as np
import pandas as pd
from lab.boveda_examen import OUT
from lab.boveda_ejecutar import write


def auditar():
    result=json.loads((OUT/'boveda_rondas.json').read_text(encoding='utf8'))
    positives=[m for m in result['metricas'] if m['ventaja']]
    family=result['familia_ajuste_busqueda']+len(positives)
    tests=[]
    for cell in positives:
        name=f'boveda_examen_{cell["sim"].replace("-","_").replace(".","_")}_{cell["horizonte"]}.json'
        data=json.loads((OUT/name).read_text(encoding='utf8'))
        if data['firma']!=result['firma']:raise ValueError('Fragmento de otro protocolo')
        rows=[q for q in data['ejemplos'] if q['fecha']>='2019-01-01']
        if len(rows)!=cell['n']:raise ValueError('Cambió la muestra del contraste')
        delta=[]
        for q in rows:
            y=int(q['retorno']>0)
            base=q['pronosticos']['ingenuo']['p_sube']
            p=q['pronosticos'].get(cell['metodo'],q['pronosticos']['ingenuo'])['p_sube']
            delta.append((base-y)**2-(p-y)**2)
        dates=pd.to_datetime([q['fecha'] for q in rows])
        ids=((dates-pd.Timestamp('2005-01-01')).days//max(60,2*cell['horizonte'])).to_numpy()
        groups=sorted(set(ids)); sums=np.array([np.array(delta)[ids==g].sum() for g in groups])
        if len(groups)>20:raise ValueError('Enumeración de signos demasiado grande; no aproximar silenciosamente')
        # Null alternativo: bloques independientes con diferencias simétricas.
        # Contraste de sensibilidad, no un reemplazo retrospectivo del protocolo.
        states=np.arange(2**len(groups),dtype=np.uint64)
        signs=((states[:,None] >> np.arange(len(groups),dtype=np.uint64)) & 1).astype(float)*2-1
        p=float(np.mean(signs@sums>=sums.sum()-1e-12))
        tests.append({'sim':cell['sim'],'horizonte':cell['horizonte'],'metodo':cell['metodo'],
                      'n':len(rows),'bloques':len(groups),'permutaciones':len(states),
                      'p_bootstrap_registrada':cell['p'],'p_signos_sensibilidad':p,
                      'p_ajustada_sensibilidad':min(1.,p*family),
                      'supera_sensibilidad':p*family<.05,'habilidad':cell['habilidad']})
    audit={'version':1,'firma_examen':result['firma'],'estado':'sensibilidad posterior, no preregistrada',
           'ganador_preservado':result['ganador_congelado'],'contrastes_adicionales':len(tests),
           'familia_conservadora_sensibilidad':family,'pruebas':tests,
           'aviso':'No altera resultados iniciales ni selecciona otra variante. Signos requieren simetría/independencia de bloques; los bloques de calendario son aproximados. Validación reutilizada y muestra pequeña: señales exploratorias, no confirmación prospectiva.'}
    write(OUT/'boveda_examen_auditoria.json',audit,once=True)
    print(json.dumps(audit,ensure_ascii=False))


if __name__=='__main__': auditar()
