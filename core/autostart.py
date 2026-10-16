import os
import stat
import subprocess
from typing import Dict, Any, Optional

DEFAULT_AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
DEFAULT_AUTOSTART_DESKTOP = os.path.join(DEFAULT_AUTOSTART_DIR, "vlc-autoplay.desktop")
DEFAULT_RUNNER_DIR = os.path.expanduser("~/.config/vlc-autoplay")
DEFAULT_RUNNER_PATH = os.path.join(DEFAULT_RUNNER_DIR, "vlc-runner.sh")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def build_vlc_command(profile: Dict[str, Any], binary: str = "cvlc") -> str:
    """
    Construye el comando exacto para ejecutar VLC según las opciones del perfil.
    Usa 'cvlc' por defecto para evitar cualquier menú o interfaz de VLC en modo kiosk.
    """
    args = [binary]

    if profile.get("fullscreen", True):
        args.append("--fullscreen")

    if profile.get("loop", True):
        args.append("--loop")

    if profile.get("hide_osd", True):
        args.append("--no-video-title-show")

    if profile.get("hide_mouse", True):
        args.append("--mouse-hide-timeout=0")

    if profile.get("no_audio", False):
        args.append("--no-audio")
    else:
        vol = profile.get("volume", 100)
        gain = max(0.0, min(2.0, vol / 100.0))
        args.append(f"--gain={gain:.2f}")

    extra = profile.get("extra_args", "").strip()
    if extra:
        args.append(extra)

    file_path = profile.get("file_path", "").strip()
    if file_path:
        args.append(f'"{file_path}"')

    return " ".join(args)

class AutostartManager:
    def __init__(
        self,
        autostart_path: Optional[str] = None,
        runner_path: Optional[str] = None,
        project_dir: Optional[str] = None
    ):
        self.autostart_path = autostart_path or DEFAULT_AUTOSTART_DESKTOP
        self.runner_path = runner_path or DEFAULT_RUNNER_PATH
        self.autostart_dir = os.path.dirname(self.autostart_path)
        self.runner_dir = os.path.dirname(self.runner_path)
        self.project_dir = project_dir or PROJECT_ROOT

    def is_active(self) -> bool:
        """Verifica si el autostart está configurado y el archivo .desktop existe."""
        return os.path.isfile(self.autostart_path) and os.path.isfile(self.runner_path)

    def enable(self, profile: Dict[str, Any]) -> bool:
        """
        Crea o actualiza el script vlc-runner.sh y el archivo autostart .desktop.
        """
        try:
            os.makedirs(self.autostart_dir, exist_ok=True)
            os.makedirs(self.runner_dir, exist_ok=True)

            delay = int(profile.get("delay_seconds", 5))
            engine = profile.get("player_engine", "mpv")
            role = profile.get("network_role", "follower")
            profile_id = profile.get("id", "")

            vlc_cmd = build_vlc_command(profile, binary="cvlc")

            runner_content = f"""#!/usr/bin/env bash
# ========================================================
# Script generado automáticamente por VLC / MPV AutoPlay Studio
# Perfil: {profile.get('name', 'Instalación')}
# Rol: {role.upper()} | Motor: {engine.upper()}
# ========================================================

# Esperar a que el entorno gráfico (Wayland/X11) y el audio estén listos
sleep {delay}

# Asegurar que el salvapantallas no interfiera
if command -v xset >/dev/null 2>&1; then
    xset s off -dpms || true
fi

# Iniciar reproducción según el motor y rol configurado
if [ "{engine}" = "mpv" ] || [ "{role}" != "standalone" ]; then
    cd "{self.project_dir}"
    exec python3 -m core.sync_runner "{profile_id}"
else
    exec {vlc_cmd}
fi
"""
            with open(self.runner_path, "w", encoding="utf-8") as f:
                f.write(runner_content)

            # Dar permisos de ejecución
            st = os.stat(self.runner_path)
            os.chmod(self.runner_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

            desktop_content = f"""[Desktop Entry]
Type=Application
Name=VLC AutoPlay Studio
Comment=Arranque automático de video/audio en loop para instalaciones
Exec={self.runner_path}
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
"""
            with open(self.autostart_path, "w", encoding="utf-8") as f:
                f.write(desktop_content)

            return True
        except Exception as e:
            print(f"Error habilitando autostart: {e}")
            return False

    def disable(self) -> bool:
        """Elimina el archivo .desktop para desactivar el inicio automático."""
        try:
            if os.path.exists(self.autostart_path):
                os.remove(self.autostart_path)
            return True
        except Exception as e:
            print(f"Error deshabilitando autostart: {e}")
            return False
