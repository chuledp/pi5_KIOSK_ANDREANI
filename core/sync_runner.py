"""
Daemon de ejecución y sincronización para modo Boot y background.
Coordina MPV con el receptor o emisor OSC según el rol del perfil activo.
"""

import os
import sys
import time
import signal
from typing import Optional

from core.profile_manager import ProfileManager
from core.mpv_controller import MPVController
from core.osc_receiver import OSCReceiver
from core.osc_broadcaster import OSCBroadcaster

class SyncDaemon:
    def __init__(self, profile_manager: Optional[ProfileManager] = None):
        self.pm = profile_manager or ProfileManager()
        self.mpv = MPVController()
        self.osc_recv: Optional[OSCReceiver] = None
        self.osc_broad: Optional[OSCBroadcaster] = None
        self.is_running = False

    def start(self, profile_id: Optional[str] = None):
        prof = self.pm.get_profile(profile_id) if profile_id else self.pm.get_active_profile()
        if not prof:
            print("No hay perfil configurado.")
            return

        role = prof.get("network_role", "follower")
        port = int(prof.get("osc_port", 9000))
        broadcast_ip = prof.get("osc_broadcast_ip", "255.255.255.255")
        mappings = prof.get("osc_mappings", {})

        print(f"Iniciando SyncDaemon con perfil '{prof['name']}' (Rol: {role.upper()}, Puerto: {port})")

        # 1. Iniciar MPV
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

    def stop(self):
        self.is_running = False
        if self.osc_recv:
            self.osc_recv.stop()
            self.osc_recv = None
        if self.osc_broad:
            self.osc_broad.close()
            self.osc_broad = None
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
