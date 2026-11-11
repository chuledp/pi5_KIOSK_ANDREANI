"""
Daemon de ejecución y sincronización para modo Boot y background.
Coordina MPV con el receptor o emisor OSC según el rol del perfil activo.
"""

import os
import sys
import time
import signal
import shutil
import subprocess
from typing import Optional

from core.profile_manager import ProfileManager
from core.mpv_controller import MPVController
from core.autostart import build_vlc_args, ensure_system_volume_max
from core.dual_display import enable_dual_hdmi_mirror
from core.osc_receiver import OSCReceiver
from core.osc_broadcaster import OSCBroadcaster
from core.web_control import start_web_control, WebControlServer
from core.web_control.discovery import get_local_ip

def _resolve_vlc_binary() -> str:
    if shutil.which("cvlc"):
        return "cvlc"
    if shutil.which("vlc"):
        return "vlc"
    mac_vlc = "/Applications/VLC.app/Contents/MacOS/VLC"
    if os.path.exists(mac_vlc):
        return mac_vlc
    return "cvlc"

class SyncDaemon:
    def __init__(self, profile_manager: Optional[ProfileManager] = None):
        self.pm = profile_manager or ProfileManager()
        self.mpv = MPVController()
        self.vlc_process: Optional[subprocess.Popen] = None
        self.osc_recv: Optional[OSCReceiver] = None
        self.osc_broad: Optional[OSCBroadcaster] = None
        self.web_server: Optional[WebControlServer] = None
        self.is_running = False

    def start(self, profile_id: Optional[str] = None):
        prof = self.pm.get_profile(profile_id) if profile_id else self.pm.get_active_profile()
        if not prof:
            print("No hay perfil configurado.")
            return

        role = prof.get("network_role", "follower")
        engine = prof.get("player_engine", "mpv")
        port = int(prof.get("osc_port", 9000))
        broadcast_ip = prof.get("osc_broadcast_ip", "255.255.255.255")
        mappings = prof.get("osc_mappings", {})

        # Asegurar el volumen maestro de la Raspberry Pi al 100% antes de reproducir
        if not prof.get("no_audio", False):
            ensure_system_volume_max()

        # Asegurar que ambas salidas HDMI (HDMI-A-1 y HDMI-A-2) estén encendidas y espejadas
        enable_dual_hdmi_mirror(prof)

        print(f"Iniciando SyncDaemon con perfil '{prof['name']}' (Rol: {role.upper()}, Motor: {engine.upper()}, Puerto: {port})")

        # 1. Iniciar reproductor según rol y motor elegido
        if role == "standalone" and engine == "vlc":
            vlc_bin = _resolve_vlc_binary()
            vlc_args = build_vlc_args(prof, binary=vlc_bin)
            self.vlc_process = subprocess.Popen(
                vlc_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.is_running = True
            return

        self.mpv.launch(prof)
        self.is_running = True

        # Invertir mapeos: ruta_recibida -> accion_estandar
        # Por ej: {"/resolume/play": "/play"}
        route_to_action = {}
        for action, custom_route in mappings.items():
            route_to_action[custom_route] = action

        # 2. Configurar según rol
        if role == "follower":
            self.osc_recv = OSCReceiver(port=port)

            def handle_osc(addr, args):
                action = route_to_action.get(addr, addr)
                # print(f"[OSC Recv] {addr} -> {action} | args: {args}")
                if action == "/play":
                    self.mpv.play()
                elif action == "/pause":
                    self.mpv.pause()
                elif action == "/stop":
                    self.mpv.stop()
                elif action == "/resume":
                    self.mpv.play()
                elif action == "/seek" and args:
                    try:
                        self.mpv.seek(float(args[0]))
                    except Exception:
                        pass
                elif action == "/position" and args:
                    try:
                        self.mpv.set_position(float(args[0]))
                    except Exception:
                        pass
                elif action == "/volume" and args:
                    try:
                        self.mpv.set_volume(int(args[0]))
                    except Exception:
                        pass
                elif action == "/cue" and args:
                    cue_val = str(args[0])
                    # Buscar perfil que coincida en nombre o ID
                    for p in self.pm.get_profiles():
                        if p["id"] == cue_val or p["name"].lower() == cue_val.lower():
                            if p.get("file_path"):
                                self.mpv.load_file(p["file_path"])
                            break
                elif action == "/sync/clock" and args:
                    try:
                        master_time = float(args[0])
                        self.mpv.sync_with_master_time(master_time)
                    except Exception:
                        pass

            self.osc_recv.on_any(handle_osc)
            self.osc_recv.start()

        elif role == "master":
            self.osc_broad = OSCBroadcaster(target_host=broadcast_ip, port=port)
            # Iniciar pulso de reloj continuo
            self.osc_broad.start_clock_sync(self.mpv.get_time_pos, interval=0.15)

        # 3. Iniciar Servidor de Control Web para Tablet y Auto-Discovery
        if prof.get("web_control_enabled", True):
            def get_local_status() -> dict:
                is_paused = self.mpv.is_paused() if self.mpv and self.mpv.is_running() else False
                is_running = self.mpv.is_running() if self.mpv else (self.vlc_process is not None)
                status_str = "offline" if not is_running else ("paused" if is_paused else "playing")
                time_pos = self.mpv.get_time_pos() if (self.mpv and self.mpv.is_running()) else 0.0
                duration = self.mpv.get_duration() if (self.mpv and self.mpv.is_running()) else 0.0
                return {
                    "id": prof.get("id", "pi-node"),
                    "name": prof.get("device_name") or prof.get("name", "Raspberry Pi"),
                    "floor": prof.get("device_floor", "Planta Baja"),
                    "ip": get_local_ip(),
                    "port": int(prof.get("web_control_port", 8080)),
                    "osc_port": port,
                    "status": status_str,
                    "current_file": prof.get("file_path", ""),
                    "time_pos": max(0.0, float(time_pos)),
                    "duration": max(0.0, float(duration)),
                    "volume": int(prof.get("volume", 100)),
                    "engine": engine
                }

            def handle_local_cmd(action: str, val: Any) -> bool:
                if action == "play":
                    self.mpv.play()
                    return True
                elif action == "pause":
                    self.mpv.pause()
                    return True
                elif action == "stop":
                    self.mpv.stop()
                    return True
                elif action == "seek" and val is not None:
                    self.mpv.seek(float(val))
                    return True
                elif action == "volume" and val is not None:
                    self.mpv.set_volume(int(val))
                    return True
                return False

            self.web_server = start_web_control(
                profile=prof,
                status_provider=get_local_status,
                local_command_handler=handle_local_cmd
            )

    def stop(self):
        self.is_running = False
        if self.osc_recv:
            self.osc_recv.stop()
            self.osc_recv = None
        if self.osc_broad:
            self.osc_broad.close()
            self.osc_broad = None
        if self.web_server:
            try:
                self.web_server.beacon.stop()
                self.web_server.stop()
            except Exception:
                pass
            self.web_server = None
        if self.vlc_process:
            try:
                self.vlc_process.terminate()
                self.vlc_process.wait(timeout=1.0)
            except Exception:
                try:
                    self.vlc_process.kill()
                except Exception:
                    pass
            self.vlc_process = None
        self.mpv.terminate()

def run_daemon_cli():
    daemon = SyncDaemon()

    def sig_handler(sig, frame):
        print("\nDeteniendo SyncDaemon...")
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    prof_id = sys.argv[1] if len(sys.argv) > 1 else None
    daemon.start(profile_id=prof_id)

    try:
        while daemon.is_running:
            time.sleep(1)
    except KeyboardInterrupt:
        daemon.stop()

if __name__ == "__main__":
    run_daemon_cli()
