#!/usr/bin/env bash
# ========================================================
# Instalador rápido vía One-Liner para Raspberry Pi 5 (Sync & OSC)
# Uso:
#   curl -sSL https://raw.githubusercontent.com/chuledp/pi5_KIOSK_ANDREANI/sync-osc/quick-install.sh | bash
# ========================================================

set -e

TARGET_DIR="$HOME/vlc-autoplay-studio"
REPO_URL="https://github.com/chuledp/pi5_KIOSK_ANDREANI.git"
BRANCH="sync-osc"

echo "=== Instalador Rápido AutoPlay Studio (Sync & OSC) ==="

# Instalar dependencias necesarias (git, mpv, vlc, python3-tk)
echo "Verificando dependencias del sistema (git, mpv, vlc, python3-tk)..."
sudo apt update && sudo apt install -y git mpv vlc python3-tk

# Clonar o actualizar repositorio en la rama sync-osc
if [ -d "$TARGET_DIR/.git" ]; then
    echo "Actualizando instalación existente en $TARGET_DIR..."
    cd "$TARGET_DIR"
    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    echo "Descargando AutoPlay Studio en $TARGET_DIR (rama $BRANCH)..."
    rm -rf "$TARGET_DIR"
    git clone -b "$BRANCH" "$REPO_URL" "$TARGET_DIR"
    cd "$TARGET_DIR"
fi

# Ejecutar instalador de accesos directos
chmod +x install.sh app.py run.sh
./install.sh

echo "=== ¡Listo! Ya podés usar AutoPlay Studio con Sync & OSC desde tu Escritorio ==="
