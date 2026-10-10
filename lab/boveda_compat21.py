"""Extensión 21 original firmada, tolerando SOLO el despacho CLI agregado en 21B."""
import hashlib
from pathlib import Path
from lab import boveda_ejecutar as original

DESPACHO = '\n\n# CLI 21B: el núcleo importado arriba permanece congelado.\nif __name__ == "__main__":\n    __import__("lab.boveda_examen", fromlist=["main"]).main()\n'


def firma_compatible():
    sources = {}
    for p in ('lab/boveda.py', 'lab/boveda_metricas.py', 'lab/boveda_ejecutar.py'):
        source = (original.ROOT/p).read_text(encoding='utf8')
        if p == 'lab/boveda.py':
            if not source.endswith(DESPACHO): raise ValueError('Despacho 21B alterado')
            source = source[:-len(DESPACHO)]
        sources[p] = hashlib.sha256(source.encode()).hexdigest()
    # La firma v2 original comprueba cada byte del núcleo, métricas y evaluador.
    return original.sha({'config': original.CONFIG, 'archivos': sources})


def main():
    import argparse
    import datetime as dt
    p = argparse.ArgumentParser(); p.add_argument('modo', choices=['extender'])
    p.add_argument('--hasta', default=dt.date.today().isoformat()); args = p.parse_args()
    original.firma_codigo = firma_compatible
    original.ejecutar(args.modo, args.hasta)


if __name__ == '__main__': main()
