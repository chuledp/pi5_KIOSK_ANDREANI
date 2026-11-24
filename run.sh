#!/usr/bin/env bash
# ========================================================
# Kiosk Fleet Manager - Script de Inicio
# ========================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

PORT=${1:-5050}

# Intentar abrir el navegador automáticamente según el SO
if [[ "$OSTYPE" == "darwin"* ]]; then
    (sleep 1.2 && open "http://localhost:$PORT") &
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    (sleep 1.2 && (xdg-open "http://localhost:$PORT" 2>/dev/null || true)) &
fi

python3 manager_server.py "$PORT"

