"""
Controlador de MPV con socket IPC Unix.
Proporciona control frame-accurate, búsqueda instantánea y algoritmo de sincronización suave (drift correction).
"""

import os
import json
import time
import socket
import subprocess
from typing import Optional, Dict, Any, List

DEFAULT_SOCKET_PATH = "/tmp/mpv-autoplay-socket"

class MPVController:
    def __init__(self, socket_path: str = DEFAULT_SOCKET_PATH):
        self.socket_path = socket_path
        self.process: Optional[subprocess.Popen] = None
        self._sock: Optional[socket.socket] = None
        self._request_id = 1

    def is_running(self) -> bool:
        if self.process is not None:
            if self.process.poll() is None:
                return True
        return os.path.exists(self.socket_path)

    def launch(self, profile: Dict[str, Any], binary: str = "mpv") -> bool:
        """Inicia el proceso MPV en modo kiosk con socket IPC activado."""
        self.terminate()

        # Limpiar socket previo si existe
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except Exception:
                pass

        cmd = [
            binary,
            f"--input-ipc-server={self.socket_path}",
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

        if profile.get("hide_mouse", True):
            cmd.append("--cursor-autohide=always")

        if profile.get("no_audio", False):
            cmd.append("--mute=yes")
        else:
            vol = profile.get("volume", 100)
            cmd.append(f"--volume={vol}")

        # Optimizaciones de hardware para Raspberry Pi 5
        cmd.extend(["--hwdec=auto-safe"])

        file_path = profile.get("file_path", "").strip()
        if file_path:
            cmd.append(file_path)

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            # Esperar a que el socket esté disponible
            for _ in range(30):
                time.sleep(0.1)
                if os.path.exists(self.socket_path):
                    return True
            return True
        except Exception as e:
            print(f"Error lanzando MPV: {e}")
            return False

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

    def send_command(self, command: List[Any]) -> Optional[Dict[str, Any]]:
        """Envía un comando JSON por el socket IPC de MPV."""
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
        self.send_command(["set_property", "volume", max(0, min(100, int(volume)))])

    def load_file(self, file_path: str):
        self.send_command(["loadfile", file_path])

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
        """Cierra la conexión al socket y termina el proceso MPV."""
        if self._sock:
            try:
                self.send_command(["quit"])
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=1.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except Exception:
                pass
