#!/usr/bin/env bash
# ========================================================
# Lanzador de VLC AutoPlay Studio
# ========================================================
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Seleccionar interprete de python3 con soporte tkinter
if python3 -c "import tkinter" >/dev/null 2>&1; then
    PY_BIN="python3"
elif [ -x "/usr/bin/python3" ] && /usr/bin/python3 -c "import tkinter" >/dev/null 2>&1; then
    PY_BIN="/usr/bin/python3"
else
    PY_BIN="python3"
fi

exec "$PY_BIN" "$DIR/app.py" "$@"
