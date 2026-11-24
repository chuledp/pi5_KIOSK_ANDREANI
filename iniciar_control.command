#!/bin/bash
# ========================================================
# KIOSK FLEET MANAGER - Lanzador para macOS
# Doble clic para iniciar la Torre de Control y abrir el navegador
# ========================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "========================================================"
echo "🚀 INICIANDO KIOSK FLEET MANAGER (TORRE DE CONTROL)"
echo "========================================================"
echo "Directorio: $DIR"

# Abrir el navegador tras 1 segundo
(sleep 1.2 && open "http://localhost:5050") &

# Ejecutar el servidor Python
python3 manager_server.py 5050
