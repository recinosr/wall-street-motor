"""Empaque gzip reversible; no recalcula ni modifica las métricas22."""
import gzip
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'resultados'


def main():
    path=ROOT/'boveda_meses.json';data=json.loads(path.read_text(encoding='utf8'))
    for entry in data['fragmentos']:
        source=ROOT/entry['archivo'];raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Fragmento alterado')
        compressed=gzip.compress(raw,compresslevel=9,mtime=0)
        if gzip.decompress(compressed)!=raw:raise ValueError('Empaque no reversible')
        dest=source.with_suffix('.json.gz');dest.write_bytes(compressed)
        entry.update(archivo_gzip=dest.name,bytes_gzip=len(compressed),sha256_gzip=hashlib.sha256(compressed).hexdigest())
    path.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')),encoding='utf8')
    print('Gzip verificado:',sum(e['bytes'] for e in data['fragmentos']),'a',sum(e['bytes_gzip'] for e in data['fragmentos']),'bytes; metricas intactas')

if __name__=='__main__':main()
