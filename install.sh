#!/usr/bin/env bash
# ========================================================
# Instalador de Accesos Directos para Raspberry Pi OS
# VLC AutoPlay Studio
# ========================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ICON_PATH="$DIR/assets/icon.png"
APP_EXEC="$DIR/run.sh"

echo "=== Instalando VLC AutoPlay Studio ==="

# 1. Asegurar permisos de ejecución
chmod +x "$DIR/run.sh"
chmod +x "$DIR/app.py"
chmod +x "$DIR/install.sh"

# 2. Directorios de destino
DESKTOP_DIR="$HOME/Desktop"
APPS_DIR="$HOME/.local/share/applications"

mkdir -p "$APPS_DIR"
if [ -d "$DESKTOP_DIR" ]; then
    mkdir -p "$DESKTOP_DIR"
fi

# 3. Contenido del archivo .desktop
DESKTOP_CONTENT="[Desktop Entry]
Type=Application
Name=VLC AutoPlay Studio
GenericName=Configurador Kiosk VLC
Comment=Configura video/audio en loop para instalaciones sin usar terminal
Exec=\"$APP_EXEC\"
Icon=$ICON_PATH
Terminal=false
Categories=AudioVideo;Audio;Video;Player;
StartupNotify=true
"

# 4. Instalar en el Menú de Aplicaciones
echo "$DESKTOP_CONTENT" > "$APPS_DIR/vlc-autoplay-studio.desktop"
chmod +x "$APPS_DIR/vlc-autoplay-studio.desktop"

# 5. Instalar en el Escritorio (si existe)
if [ -d "$DESKTOP_DIR" ]; then
    DESKTOP_FILE="$DESKTOP_DIR/VLC AutoPlay Studio.desktop"
    echo "$DESKTOP_CONTENT" > "$DESKTOP_FILE"
    chmod +x "$DESKTOP_FILE"
    # Si gio está presente en Raspberry Pi OS, marcar como confiable
    if command -v gio >/dev/null 2>&1; then
        gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null || true
    fi
fi

# 6. Chequear si VLC está instalado y avisar
VLC_STATUS="OK"
if ! command -v vlc >/dev/null 2>&1 && ! command -v cvlc >/dev/null 2>&1; then
    VLC_STATUS="FALTA_VLC"
fi

echo "=== Instalación completada con éxito ==="

# 7. Notificación visual al usuario
if python3 -c "import tkinter" >/dev/null 2>&1; then
    PY_BIN="python3"
elif [ -x "/usr/bin/python3" ] && /usr/bin/python3 -c "import tkinter" >/dev/null 2>&1; then
    PY_BIN="/usr/bin/python3"
else
    PY_BIN=""
fi

if [ -n "$PY_BIN" ]; then
    "$PY_BIN" -c "
import tkinter as tk
from tkinter import messagebox

root = tk.Tk()
root.withdraw()

status = '$VLC_STATUS'
if status == 'FALTA_VLC':
    messagebox.showwarning(
        'VLC AutoPlay Studio',
        '¡Acceso directo creado con éxito!\n\nNota: No se detectó VLC Media Player instalado.\nPara instalarlo, abrí una terminal y ejecutá:\nsudo apt install -y vlc'
    )
else:
    messagebox.showinfo(
        'VLC AutoPlay Studio',
        '¡Instalación completada!\n\nSe creó el acceso directo en:\n• El Escritorio\n• El Menú de Aplicaciones (Sonido y Video)\n\nYa podés abrir el programa con doble clic.'
    )
" 2>/dev/null || true
fi
