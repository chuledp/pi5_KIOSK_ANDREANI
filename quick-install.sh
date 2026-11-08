#!/usr/bin/env bash
# ========================================================
# Instalador rápido vía One-Liner para Raspberry Pi 5 + Focusrite Scarlett 8i6
# Uso:
#   curl -sSL https://raw.githubusercontent.com/chuledp/pi5_KIOSK_ANDREANI/Pi%2BScarlett/quick-install.sh | bash
# ========================================================

set -e

TARGET_DIR="$HOME/vlc-autoplay-studio"
REPO_URL="https://github.com/chuledp/pi5_KIOSK_ANDREANI.git"
BRANCH="Pi+Scarlett"

echo "=== Instalador Rápido AutoPlay Studio (Pi 5 + Focusrite Scarlett 8i6) ==="

# 1. Instalar dependencias principales (git, mpv, vlc, python3-tk, alsa-utils)
echo "Verificando dependencias del sistema (git, mpv, vlc, python3-tk, alsa-utils)..."
sudo apt update && sudo apt install -y git mpv vlc python3-tk alsa-utils pulseaudio-utils

# 2. Instalar alsa-scarlett-gui (vía apt o compilando desde el repo oficial de Geoffrey Bennett)
if ! command -v alsa-scarlett-gui >/dev/null 2>&1; then
    echo "Instalando alsa-scarlett-gui para control visual de Focusrite Scarlett..."
    if ! sudo apt install -y alsa-scarlett-gui 2>/dev/null; then
        echo "Compilando alsa-scarlett-gui desde código fuente..."
        sudo apt install -y make gcc libgtk-4-dev libasound2-dev libssl-dev || true
        TMP_SCARLETT="/tmp/alsa-scarlett-gui-build"
        rm -rf "$TMP_SCARLETT"
        if git clone --depth 1 https://github.com/geoffreybennett/alsa-scarlett-gui.git "$TMP_SCARLETT"; then
            (cd "$TMP_SCARLETT/src" && make -j4 && sudo make install) || echo "Nota: No se pudo compilar alsa-scarlett-gui, el ruteo automático por amixer seguirá funcionando."
            rm -rf "$TMP_SCARLETT"
        fi
    fi
fi

# 3. Clonar o actualizar repositorio en la rama Pi+Scarlett
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

# 4. Ejecutar instalador de accesos directos
chmod +x install.sh app.py run.sh
./install.sh

echo "=== ¡Listo! Ya podés usar AutoPlay Studio (Edición Pi+Scarlett) desde tu Escritorio ==="
