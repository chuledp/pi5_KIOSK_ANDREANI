#!/usr/bin/env bash
# ========================================================
# Instalador rápido vía One-Liner para Raspberry Pi 5
# Uso:
#   curl -sSL https://raw.githubusercontent.com/chuledp/pi5_KIOSK_ANDREANI/main/quick-install.sh | bash
# ========================================================

set -e

TARGET_DIR="$HOME/vlc-autoplay-studio"
REPO_URL="https://github.com/chuledp/pi5_KIOSK_ANDREANI.git"

echo "=== Instalador Rápido VLC AutoPlay Studio ==="

# Instalar git y vlc si no estuvieran presentes
if ! command -v git >/dev/null 2>&1 || ! command -v vlc >/dev/null 2>&1; then
    echo "Instalando dependencias necesarias (git, vlc)..."
    sudo apt update && sudo apt install -y git vlc python3-tk
fi

# Clonar o actualizar repositorio
if [ -d "$TARGET_DIR/.git" ]; then
    echo "Actualizando instalación existente en $TARGET_DIR..."
    cd "$TARGET_DIR"
    git pull
else
    echo "Descargando VLC AutoPlay Studio en $TARGET_DIR..."
    rm -rf "$TARGET_DIR"
    git clone "$REPO_URL" "$TARGET_DIR"
    cd "$TARGET_DIR"
fi

# Ejecutar instalador de accesos directos
chmod +x install.sh app.py run.sh
./install.sh

echo "=== ¡Listo! Ya podés usar VLC AutoPlay Studio desde tu Escritorio ==="
