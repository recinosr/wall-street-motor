"""Empaque del banco educativo por activo/horizonte, sin recalcular resultados."""
import json
from collections import defaultdict
from pathlib import Path
from lab.boveda_ejecutar import write, sha


def empacar(out):
    path = Path(out)/'boveda_examenes.json'
    data = json.loads(path.read_text(encoding='utf8'))
    if data.get('fragmentado'): return data
    groups = defaultdict(list)
    for q in data['ejemplos']: groups[q['sim'], q['horizonte']].append(q)
    manifest = {k: v for k, v in data.items() if k != 'ejemplos'}
    manifest['fragmentado'] = True; manifest['sha256_banco_completo'] = sha(data)
    manifest['ejemplos'] = [{k: q[k] for k in ('sim', 'fecha', 'horizonte')} for q in data['ejemplos']]
    manifest['fragmentos'] = []
    for (sim, h), questions in sorted(groups.items()):
        name = f'boveda_examen_{sim.replace("-", "_").replace(".", "_")}_{h}.json'
        payload = {'version': 1, 'firma': data['firma'], 'ejemplos': questions}
        write(Path(out)/name, payload)
        manifest['fragmentos'].append({'sim': sim, 'horizonte': h, 'archivo': name,
                                      'n': len(questions), 'sha256': sha(payload)})
    # Conserva todas las preguntas, pronósticos y revelaciones exactamente.
    write(path, manifest)
    return manifest


if __name__ == '__main__':
    from lab.boveda_examen import OUT
    m = empacar(OUT); print(len(m['ejemplos']), 'casos;', len(m['fragmentos']), 'fragmentos; sin recalcular métricas')
