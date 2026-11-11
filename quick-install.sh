#!/usr/bin/env bash
# ========================================================
# Instalador rápido vía One-Liner para Raspberry Pi 5 + Focusrite Scarlett 8i6
# Uso:
#   curl -sSL https://raw.githubusercontent.com/chuledp/pi5_KIOSK_ANDREANI/Pi%2BScarlett/quick-install.sh | bash
# ========================================================

TARGET_DIR="$HOME/vlc-autoplay-studio"
REPO_URL="https://github.com/chuledp/pi5_KIOSK_ANDREANI.git"
BRANCH="Pi+Scarlett"

echo "=== Instalador Rápido AutoPlay Studio (Pi 5 + Focusrite Scarlett 8i6) ==="

# 1. Instalar dependencias principales (git, mpv, vlc, python3-tk, alsa-utils)
echo "Verificando dependencias del sistema (git, mpv, vlc, python3-tk, alsa-utils)..."
sudo apt update || true
sudo apt install -y git mpv vlc python3-tk alsa-utils pulseaudio-utils wlr-randr x11-xserver-utils || sudo apt install -y git mpv vlc python3-tk alsa-utils || true

# 2. Instalar alsa-scarlett-gui (opcional para control visual)
if ! command -v alsa-scarlett-gui >/dev/null 2>&1; then
    echo "Verificando alsa-scarlett-gui..."
    if ! sudo apt install -y alsa-scarlett-gui 2>/dev/null; then
        echo "Intentando compilar alsa-scarlett-gui (opcional)..."
        sudo apt install -y make gcc pkg-config libgtk-4-dev libasound2-dev libssl-dev 2>/dev/null || true
        TMP_SCARLETT="/tmp/alsa-scarlett-gui-build"
        rm -rf "$TMP_SCARLETT"
        if git clone --depth 1 https://github.com/geoffreybennett/alsa-scarlett-gui.git "$TMP_SCARLETT" 2>/dev/null; then
            if (cd "$TMP_SCARLETT/src" && make -j4 && sudo cp alsa-scarlett-gui /usr/local/bin/) 2>/dev/null; then
                echo "alsa-scarlett-gui instalado con éxito."
            else
                echo "Nota: alsa-scarlett-gui opcional no se pudo compilar. El ruteo por hardware automático vía ALSA funcionará al 100%."
            fi
            rm -rf "$TMP_SCARLETT"
        fi
    fi
fi

# 3. Clonar o actualizar repositorio en la rama Pi+Scarlett
if [ -d "$TARGET_DIR/.git" ]; then
    echo "Actualizando instalación existente en $TARGET_DIR..."
    cd "$TARGET_DIR"
    git remote set-branches origin '*' 2>/dev/null || true
    git fetch origin --all 2>/dev/null || git fetch origin || true
    git checkout -B "$BRANCH" "origin/$BRANCH" 2>/dev/null || git checkout "$BRANCH" 2>/dev/null || true
    git reset --hard "origin/$BRANCH" 2>/dev/null || git pull origin "$BRANCH" || true
else
    echo "Descargando AutoPlay Studio en $TARGET_DIR (rama $BRANCH)..."
    rm -rf "$TARGET_DIR"
    git clone -b "$BRANCH" "$REPO_URL" "$TARGET_DIR" || git clone "$REPO_URL" "$TARGET_DIR"
    cd "$TARGET_DIR"
    git checkout -B "$BRANCH" "origin/$BRANCH" 2>/dev/null || git checkout "$BRANCH" 2>/dev/null || true
fi

# 4. Ejecutar instalador de accesos directos
chmod +x install.sh app.py run.sh 2>/dev/null || true
./install.sh || true

echo "=== ¡Listo! Ya podés usar AutoPlay Studio (Edición Pi+Scarlett) desde tu Escritorio ==="
