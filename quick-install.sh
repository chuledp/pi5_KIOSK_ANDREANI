#!/usr/bin/env bash
# ========================================================
# Instalador rápido vía One-Liner para Raspberry Pi 5 (DUAL OPTOMA)
# Uso:
#   curl -sSL https://raw.githubusercontent.com/chuledp/pi5_KIOSK_ANDREANI/DUAL-OPTOMA/quick-install.sh | bash
# ========================================================

set -e

TARGET_DIR="$HOME/vlc-autoplay-studio"
REPO_URL="https://github.com/chuledp/pi5_KIOSK_ANDREANI.git"
BRANCH="DUAL-OPTOMA"

echo "=== Instalador Rápido AutoPlay Studio (DUAL OPTOMA - 2 Salidas HDMI) ==="

# Instalar dependencias necesarias (git, mpv, vlc, python3-tk, wlr-randr, xrandr)
echo "Verificando dependencias del sistema (git, mpv, vlc, python3-tk, wlr-randr, x11-xserver-utils)..."
sudo apt update && sudo apt install -y git mpv vlc python3-tk wlr-randr x11-xserver-utils

# Forzar detección hotplug en las dos salidas micro-HDMI de la Raspberry Pi 5 (vc4.force_hotplug=3)
# Esto garantiza que HDMI-A-1 y HDMI-A-2 estén habilitadas aunque un proyector Optoma encienda más tarde.
CMDLINE_FILE="/boot/firmware/cmdline.txt"
if [ -f "$CMDLINE_FILE" ]; then
    if ! grep -q "vc4.force_hotplug=3" "$CMDLINE_FILE"; then
        echo "Activando ambas salidas HDMI en el kernel (vc4.force_hotplug=3 en $CMDLINE_FILE)..."
        sudo sed -i 's/$/ vc4.force_hotplug=3/' "$CMDLINE_FILE" || true
    fi
fi

# Clonar o actualizar repositorio en la rama DUAL-OPTOMA
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

echo "=== ¡Listo! Ya podés usar AutoPlay Studio (DUAL OPTOMA) desde tu Escritorio ==="
