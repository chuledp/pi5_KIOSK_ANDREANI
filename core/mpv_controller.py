"""
Controlador de MPV con socket IPC Unix.
Proporciona control frame-accurate, búsqueda instantánea y algoritmo de sincronización suave (drift correction).
"""

import os
import sys
import json
import time
import shlex
import socket
import threading
import subprocess
from typing import Optional, Dict, Any, List

from core.dual_display import enable_dual_hdmi_mirror
try:
    from core.scarlett_mixer import (
        build_mpv_audio_filter,
        apply_scarlett_mix_levels,
        detect_scarlett_card,
        set_default_scarlett_sink
    )
    HAS_SCARLETT = True
except ImportError:
    HAS_SCARLETT = False

DEFAULT_SOCKET_PATH = "/tmp/mpv-autoplay-socket"
DEFAULT_LOG_PATH = "/tmp/mpv-autoplay.log"

# Errores típicos en Raspberry Pi 5 cuando falla el mapeo DRM/SAND128 en H.265 (pantalla azul)
HWDEC_ERROR_PATTERNS = (
    "Initializing texture for hardware decoding failed",
    "unsupported DRM image format",
    "Unsupported pixel format",
    "Impossible to convert between the formats",
    "Failed to transfer data from hardware surface",
    "Hardware decoding of this stream is unsupported",
    "mapping DRM dmabuf failed",
)


class MPVController:
    def __init__(self, socket_path: str = DEFAULT_SOCKET_PATH, log_path: str = DEFAULT_LOG_PATH):
        self.socket_path = socket_path
        self.secondary_socket_path = f"{socket_path}-hdmi2"
        self.log_path = log_path
        self.process: Optional[subprocess.Popen] = None
        self.secondary_process: Optional[subprocess.Popen] = None
        self._sock: Optional[socket.socket] = None
        self._secondary_sock: Optional[socket.socket] = None
        self._request_id = 1
        self._current_file: str = ""
        self._fallback_triggered: bool = False

    def is_running(self) -> bool:
        if self.process is not None:
            if self.process.poll() is None:
                return True
        return os.path.exists(self.socket_path)

    def launch(self, profile: Dict[str, Any], binary: str = "mpv") -> bool:
        """Inicia el proceso MPV en modo kiosk con socket IPC activado (y soporte Dual HDMI Optoma)."""
        self.terminate()

        # Configurar ambas salidas HDMI (HDMI-A-1 y HDMI-A-2) antes de abrir MPV
        enable_dual_hdmi_mirror(profile)

        # Limpiar sockets y logs previos si existen
        for path in (self.socket_path, self.secondary_socket_path, self.log_path):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

        cmd = [
            binary,
            f"--input-ipc-server={self.socket_path}",
            f"--log-file={self.log_path}",
            "--idle=yes",
            "--no-terminal",
            "--keep-open=yes",
            "--osd-level=0",
            "--no-osd-bar"
        ]

        if profile.get("fullscreen", True):
            cmd.append("--fullscreen")

        if profile.get("loop", True):
            cmd.append("--loop-file=inf")
            cmd.append("--loop-playlist=inf")

        if profile.get("hide_mouse", True):
            cmd.append("--cursor-autohide=always")

        cmd.append("--volume-max=300")
        if profile.get("no_audio", False):
            cmd.append("--mute=yes")
        else:
            vol = max(0, min(300, int(profile.get("volume", 100))))
            cmd.append(f"--volume={vol}")

            scarlett_enabled = bool(profile.get("scarlett_enabled", True))
            scarlett_info = detect_scarlett_card() if (HAS_SCARLETT and scarlett_enabled) else {"found": False}

            if HAS_SCARLETT and scarlett_enabled and scarlett_info.get("found"):
                # Asignar la interfaz USB Scarlett directamente en MPV
                cmd.append(f"--audio-device={scarlett_info['mpv_device']}")
                cmd.append("--audio-channels=auto-safe")
                set_default_scarlett_sink()
                af_str = build_mpv_audio_filter(profile)
                if af_str:
                    cmd.append(f"--af={af_str}")
            else:
                # Salida por defecto (HDMI / Sistema)
                if profile.get("audio_boost", True):
                    cmd.append("--af=lavfi=[dynaudnorm=f=200:g=15:p=0.95]")

        # Configuración de decodificación y renderizado para Raspberry Pi 5 (H.265 / HEVC)
        # Nota: '--hwdec=auto-safe' elige 'drm' zero-copy (formato SAND128), lo cual en el
        # escritorio Wayland/X11 de la Pi 5 falla al crear la textura OpenGL y deja la pantalla azul.
        # 'drm-copy' (con fallback automático a 'no' / CPU multihilo) evita la pantalla azul.
        hwdec_mode = profile.get("hwdec_mode", "drm-copy")
        is_linux = sys.platform.startswith("linux")

        if is_linux:
            if hwdec_mode == "no":
                cmd.extend([
                    "--hwdec=no",
                    "--vo=gpu",
                    "--gpu-api=opengl",
                    "--gpu-dumb-mode=yes",
                    "--profile=fast",
                    "--vd-lavc-threads=4"
                ])
            elif hwdec_mode == "drm":
                cmd.extend([
                    "--hwdec=drm",
                    "--vo=gpu",
                    "--gpu-context=drm",
                    "--profile=fast",
                    "--vd-lavc-threads=4"
                ])
            elif hwdec_mode == "auto-safe":
                cmd.extend([
                    "--hwdec=auto-safe",
                    "--vo=gpu",
                    "--gpu-api=opengl",
                    "--gpu-dumb-mode=yes",
                    "--profile=fast",
                    "--vd-lavc-threads=4"
                ])
            else:
                # Default: drm-copy (decodifica H.265 por hardware y copia a RAM estándar evitando pantalla azul)
                cmd.extend([
                    "--hwdec=drm-copy",
                    "--vo=gpu",
                    "--gpu-api=opengl",
                    "--gpu-dumb-mode=yes",
                    "--profile=fast",
                    "--vd-lavc-threads=4"
                ])
        else:
            # macOS / otros entornos de prueba
            if hwdec_mode == "no":
                cmd.append("--hwdec=no")
            else:
                cmd.append("--hwdec=auto-safe")

        extra = profile.get("extra_args", "").strip()
        if extra:
            try:
                cmd.extend(shlex.split(extra))
            except Exception:
                cmd.append(extra)

        dual_enabled = bool(profile.get("dual_hdmi_enabled", True))
        dual_mode = profile.get("dual_hdmi_mode", "mirror")

        file_path = profile.get("file_path", "").strip()
        self._current_file = file_path
        self._fallback_triggered = (hwdec_mode == "no")

        primary_cmd = list(cmd)
        if dual_enabled and dual_mode == "dual_mpv":
            primary_cmd.extend(["--screen=0", "--fs-screen=0"])
        if file_path:
            primary_cmd.append(file_path)

        try:
            self.process = subprocess.Popen(
                primary_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            # Si está en modo Doble Ventana (dual_mpv), lanzar un segundo MPV sincronizado en HDMI-2 (Screen 1)
            if dual_enabled and dual_mode == "dual_mpv":
                sec_cmd = [
                    arg if not arg.startswith("--input-ipc-server=") else f"--input-ipc-server={self.secondary_socket_path}"
                    for arg in cmd
                    if not arg.startswith("--log-file=") and not arg.startswith("--volume=") and not arg.startswith("--af=")
                ]
                sec_cmd.extend(["--mute=yes", "--screen=1", "--fs-screen=1"])
                if file_path:
                    sec_cmd.append(file_path)
                try:
                    self.secondary_process = subprocess.Popen(
                        sec_cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                except Exception as sec_err:
                    print(f"Nota lanzando MPV secundario (HDMI 2): {sec_err}")

            # Esperar a que el socket esté disponible
            for _ in range(30):
                time.sleep(0.1)
                if os.path.exists(self.socket_path):
                    break

            # Asegurar que no quede en pausa al iniciar
            self.play()

            # Iniciar watchdog anti-pantalla-azul para H.265 en Pi 5
            if not self._fallback_triggered:
                self._start_hwdec_watchdog()

            return True
        except Exception as e:
            print(f"Error lanzando MPV: {e}")
            return False

    def _start_hwdec_watchdog(self):
        """
        Monitorea el log de MPV durante los primeros segundos tras cargar un video H.265.
        Si detecta que el driver V3D/OpenGL de la Pi 5 rechazó la textura de hardware
        (causante de la pantalla azul), cambia automáticamente a decodificación por CPU
        multihilo (hwdec=no) y recarga el video sin intervención del usuario.
        """
        def _watch():
            for _ in range(16):  # Monitorear durante ~4 segundos
                time.sleep(0.25)
                if self._fallback_triggered or not self.is_running():
                    return
                if not os.path.exists(self.log_path):
                    continue
                try:
                    with open(self.log_path, "r", encoding="utf-8", errors="ignore") as f:
                        log_text = f.read()
                    if any(pat in log_text for pat in HWDEC_ERROR_PATTERNS):
                        print("[MPV Watchdog] Detectado fallo de textura HW H.265 (pantalla azul). Cambiando a hwdec=no...")
                        self._fallback_triggered = True
                        self.send_command(["set_property", "hwdec", "no"])
                        if self._current_file:
                            self.send_command(["loadfile", self._current_file, "replace"])
                            self.play()
                        return
                except Exception:
                    pass

        t = threading.Thread(target=_watch, daemon=True)
        t.start()

    def _ensure_socket(self) -> bool:
        if self._sock:
            return True
        if not os.path.exists(self.socket_path):
            return False
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(self.socket_path)
            s.settimeout(0.5)
            self._sock = s
            return True
        except Exception as e:
            # print(f"Error conectando al socket MPV: {e}")
            self._sock = None
            return False

    def _send_to_secondary(self, command: List[Any]) -> None:
        """Reenvía comandos de transporte al segundo reproductor MPV (HDMI-2) si está activo."""
        if not os.path.exists(self.secondary_socket_path):
            return
        try:
            if not self._secondary_sock:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(self.secondary_socket_path)
                s.settimeout(0.2)
                self._secondary_sock = s
            req = {"command": command, "request_id": self._request_id}
            self._secondary_sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
        except Exception:
            if self._secondary_sock:
                try:
                    self._secondary_sock.close()
                except Exception:
                    pass
                self._secondary_sock = None

    def send_command(self, command: List[Any]) -> Optional[Dict[str, Any]]:
        """Envía un comando JSON por el socket IPC de MPV (y lo replica en HDMI-2 si usa dual_mpv)."""
        if command and (
            command[0] in ("loadfile", "quit")
            or (len(command) >= 2 and command[0] == "set_property" and command[1] in ("pause", "time-pos", "speed", "hwdec"))
        ):
            self._send_to_secondary(command)

        if not self._ensure_socket():
            return None
        try:
            req = {
                "command": command,
                "request_id": self._request_id
            }
            self._request_id += 1
            payload = json.dumps(req) + "\n"
            self._sock.sendall(payload.encode("utf-8"))

            # Leer respuesta
            resp_data = b""
            while b"\n" not in resp_data:
                chunk = self._sock.recv(1024)
                if not chunk:
                    break
                resp_data += chunk

            if resp_data:
                line = resp_data.split(b"\n")[0]
                return json.loads(line.decode("utf-8"))
        except Exception as e:
            # Desconectar para reconectar en el próximo intento
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
        return None

    # Métodos de transporte de alto nivel
    def is_paused(self) -> bool:
        res = self.send_command(["get_property", "pause"])
        if res and "data" in res:
            return bool(res["data"])
        return False

    def play(self):
        self.send_command(["set_property", "pause", False])

    def pause(self):
        self.send_command(["set_property", "pause", True])

    def stop(self):
        self.send_command(["set_property", "time-pos", 0])
        self.send_command(["set_property", "pause", True])

    def seek(self, seconds: float):
        self.send_command(["set_property", "time-pos", max(0.0, float(seconds))])

    def set_position(self, norm_pos: float):
        """Salta a una posición normalizada (0.0 a 1.0)."""
        duration = self.get_duration()
        if duration > 0:
            target = max(0.0, min(duration, norm_pos * duration))
            self.seek(target)

    def set_volume(self, volume: int):
        self.send_command(["set_property", "volume", max(0, min(300, int(volume)))])

    def set_audio_boost(self, enabled: bool):
        af_val = "lavfi=[dynaudnorm=f=200:g=15:p=0.95]" if enabled else ""
        self.send_command(["set_property", "af", af_val])

    def update_audio_routing(self, profile: Dict[str, Any]):
        """Actualiza en vivo los niveles de los 6 canales en MPV y en los Mixes de la Scarlett 8i6."""
        if HAS_SCARLETT:
            if profile.get("scarlett_enabled", True):
                apply_scarlett_mix_levels(profile)
            af_val = build_mpv_audio_filter(profile)
            self.send_command(["set_property", "af", af_val])

    def load_file(self, file_path: str):
        self._current_file = file_path
        self.send_command(["loadfile", file_path, "replace"])
        self.play()
        if not self._fallback_triggered:
            self._start_hwdec_watchdog()

    def get_time_pos(self) -> float:
        res = self.send_command(["get_property", "time-pos"])
        if res and "data" in res and res["data"] is not None:
            return float(res["data"])
        return 0.0

    def get_duration(self) -> float:
        res = self.send_command(["get_property", "duration"])
        if res and "data" in res and res["data"] is not None:
            return float(res["data"])
        return 0.0

    def set_speed(self, speed: float):
        self.send_command(["set_property", "speed", float(speed)])

    def sync_with_master_time(self, master_time: float):
        """
        Algoritmo de sincronización suave (Drift Correction):
        - Desfase < 50ms: sincronizado, velocidad 1.0.
        - Desfase entre 50ms y 300ms: ajuste sutil de velocidad (1.02 o 0.98) sin cortes de audio.
        - Desfase > 300ms: salto duro (seek).
        """
        local_time = self.get_time_pos()
        delta = master_time - local_time

        if abs(delta) < 0.05:
            # En sincronía casi perfecta
            self.set_speed(1.0)
        elif 0.05 <= delta < 0.35:
            # Local atrasado respecto al master -> acelerar suavemente
            self.set_speed(1.025)
        elif -0.35 < delta <= -0.05:
            # Local adelantado respecto al master -> desacelerar suavemente
            self.set_speed(0.975)
        else:
            # Desfase importante -> salto directo
            self.seek(master_time)
            self.set_speed(1.0)

    def terminate(self):
        """Cierra la conexión al socket y termina el proceso MPV (principal y secundario)."""
        if self._sock:
            try:
                self.send_command(["quit"])
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        if self._secondary_sock:
            try:
                self._secondary_sock.close()
            except Exception:
                pass
            self._secondary_sock = None

        for proc in (self.process, self.secondary_process):
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=1.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        self.process = None
        self.secondary_process = None

        for spath in (self.socket_path, self.secondary_socket_path):
            if os.path.exists(spath):
                try:
                    os.remove(spath)
                except Exception:
                    pass
