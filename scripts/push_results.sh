#!/usr/bin/env bash
# Reintentar la publicación del mismo commit; nunca repetir cálculo ni resolver
# conflictos de ledger escogiendo automáticamente una versión.
set -euo pipefail
for attempt in 1 2 3 4 5; do
  git pull --rebase origin main || exit 1
  if git push origin main; then exit 0; fi
  sleep $((attempt * 2))
done
echo 'Publicación agotó reintentos; no se cuenta como corrida exitosa.' >&2
exit 1
