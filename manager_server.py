"""
Kiosk Fleet Manager - Servidor de la Torre de Control
Aplicación web local liviana ejecutada en la notebook del usuario.
Monitorea, sincroniza y gestiona todas las Raspberry Pi de la exhibición sin código.
"""

import os
import sys
import json
import time
import threading
import mimetypes
import email
import re
from typing import Dict, Any, Optional
from http.server import HTTPServer, BaseHTTPRequestHandler
try:
    from http.server import ThreadingHTTPServer
    _BaseServer = ThreadingHTTPServer
except ImportError:
    _BaseServer = HTTPServer  # type: ignore

from core.credentials import CredentialsManager
from core.discovery import FleetDiscovery, get_local_ip
from core.ssh_bridge import SSHBridge
from core.http_bridge import HTTPBridge

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)


class FleetManagerApp:
    def __init__(self, port: int = 5050):
        self.port = port
        self.creds = CredentialsManager()
        self.discovery = FleetDiscovery(web_port=self.creds.get_config().get("web_control_port", 8080))
        self.ssh = SSHBridge(self.creds)
        self.http = HTTPBridge(default_port=self.creds.get_config().get("web_control_port", 8080))
        self.hw_stats_cache: Dict[str, Dict[str, Any]] = {}
        self._running = False
        self._stop_event = threading.Event()
        self._server = None

    def start_background_monitors(self):
        """Inicia escaneo inicial y bucle de refresco continuo de estados."""
        def _initial_scan():
            if self._stop_event.wait(1.0):
                return
            print("[FleetManager] Iniciando escaneo de red local...")
            self.discovery.scan_network()
            print(f"[FleetManager] Escaneo inicial completo. Equipos detectados: {len(self.discovery.get_all_devices())}")

        def _refresh_loop():
            while self._running:
                devices = self.discovery.get_all_devices()
                for dev in devices:
                    if not self._running:
                        break
                    ip = dev.get("ip")
                    if ip:
                        status = self.http.fetch_status(ip)
                        if status:
                            status["ip"] = ip
                            self.discovery.register_device(status)
                if self._stop_event.wait(3.0):
                    break

        threading.Thread(target=_initial_scan, daemon=True, name="FleetScan").start()
        threading.Thread(target=_refresh_loop, daemon=True, name="FleetRefresh").start()

    def stop(self):
        """Detiene de forma limpia todos los monitores y el servidor HTTP."""
        self._running = False
        self._stop_event.set()
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass


class FleetRequestHandler(BaseHTTPRequestHandler):
    app: FleetManagerApp  # Asignado en el servidor

    def log_message(self, format, *args):
        # Silenciar logs continuos de polling
        pass

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Connection", "close")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def _send_json(self, data: Dict[str, Any], status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8", errors="ignore")
            return json.loads(raw)
        except Exception:
            return {}

    def do_GET(self):
        path = self.path.split("?")[0]

        # 1. API: Lista de equipos y flota completa
        if path == "/api/fleet":
            devices = self.app.discovery.get_all_devices()
            # Enriquecer con hardware stats cacheados si existen
            for dev in devices:
                ip = dev.get("ip")
                if ip and ip in self.app.hw_stats_cache:
                    dev["hardware"] = self.app.hw_stats_cache[ip]
            self._send_json({"success": True, "devices": devices})
            return

        # 2. API: Configuración y credenciales
        elif path == "/api/config":
            cfg = self.app.creds.get_config()
            # Ocultar password en la respuesta por seguridad
            safe_cfg = dict(cfg)
            if safe_cfg.get("default_ssh_password"):
                safe_cfg["default_ssh_password_set"] = True
                safe_cfg["default_ssh_password"] = "******"
            else:
                safe_cfg["default_ssh_password_set"] = False
            self._send_json({"success": True, "config": safe_cfg})
            return

        # 3. API: Listar videos en una Pi remota (/api/device/<ip>/videos)
        elif path.startswith("/api/device/") and path.endswith("/videos"):
            ip = path.split("/")[3]
            videos = self.app.ssh.list_remote_videos(ip)
            self._send_json({"success": True, "videos": videos})
            return

        # 4. API: Estadísticas de hardware (/api/device/<ip>/stats)
        elif path.startswith("/api/device/") and path.endswith("/stats"):
            ip = path.split("/")[3]
            stats = self.app.ssh.get_system_stats(ip)
            if stats:
                self.app.hw_stats_cache[ip] = stats
            self._send_json({"success": True, "stats": stats})
            return

        # 5. API: Logs del reproductor (/api/device/<ip>/logs)
        elif path.startswith("/api/device/") and path.endswith("/logs"):
            ip = path.split("/")[3]
            logs = self.app.ssh.get_logs(ip, lines=90)
            self._send_json({"success": True, "logs": logs})
            return

        # 6. API: Estado de blindaje SD y proyectores (/api/device/<ip>/guardian)
        elif path.startswith("/api/device/") and path.endswith("/guardian"):
            ip = path.split("/")[3]
            status = self.app.ssh.get_remote_guardian_status(ip)
            self._send_json({"success": True, "guardian": status})
            return

        # 6. Servir archivos estáticos del frontend
        if path == "/" or path == "/index.html":
            file_path = os.path.join(STATIC_DIR, "index.html")
        else:
            rel_path = path.lstrip("/")
            file_path = os.path.join(STATIC_DIR, rel_path)

        if os.path.isfile(file_path):
            mime_type, _ = mimetypes.guess_type(file_path)
            mime_type = mime_type or "application/octet-stream"
            try:
                with open(file_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                self.send_error(500, f"Error leyendo archivo: {e}")
        else:
            self.send_error(404, "Recurso no encontrado")

    def do_POST(self):
        path = self.path.split("?")[0]

        # 1. API: Forzar escaneo de red
        if path == "/api/scan":
            devices = self.app.discovery.scan_network()
            self._send_json({"success": True, "count": len(devices), "devices": devices})
            return

        # 2. API: Comandos de reproducción (Play, Pause, Volume, Reset, etc.)
        elif path == "/api/command":
            body = self._read_json_body()
            action = body.get("action", "play")
            target = body.get("target", "all")
            val = body.get("value")
            ip = body.get("ip")

            if target == "all" or not ip:
                devices = self.app.discovery.get_all_devices()
                res = self.app.http.broadcast_to_all(devices, action, val)
                self._send_json(res)
            else:
                res = self.app.http.send_command(ip=ip, action=action, target=target, value=val)
                self._send_json(res)
            return

        # 3. API: Cambiar video activo en la Pi (/api/device/<ip>/switch_video)
        elif path.startswith("/api/device/") and path.endswith("/switch_video"):
            ip = path.split("/")[3]
            body = self._read_json_body()
            video_path = body.get("video_path")
            if not video_path:
                self._send_json({"success": False, "error": "Ruta de video vacía"}, status=400)
                return

            ok, msg = self.app.ssh.switch_active_video(ip, video_path)
            self._send_json({"success": ok, "message": msg})
            return

        # 4. API: Subir archivo de video a la Pi (/api/device/<ip>/upload)
        elif path.startswith("/api/device/") and path.endswith("/upload"):
            ip = path.split("/")[3]
            self._handle_video_upload(ip)
            return

        # 5. API: Actualizar configuraciones de perfil (/api/device/<ip>/settings)
        elif path.startswith("/api/device/") and path.endswith("/settings"):
            ip = path.split("/")[3]
            body = self._read_json_body()
            settings = body.get("settings", {})
            ok, msg = self.app.ssh.update_profile_settings(ip, settings)
            if ok and body.get("restart", True):
                self.app.ssh.restart_player_service(ip)
            self._send_json({"success": ok, "message": msg})
            return

        # 6. API: Acciones de sistema (reboot, shutdown, git_pull) (/api/device/<ip>/action)
        elif path.startswith("/api/device/") and path.endswith("/action"):
            ip = path.split("/")[3]
            body = self._read_json_body()
            action = body.get("action")

            if action == "reboot":
                ok, msg = self.app.ssh.reboot_remote(ip)
            elif action == "shutdown":
                ok, msg = self.app.ssh.shutdown_remote(ip)
            elif action == "git_pull":
                ok, msg = self.app.ssh.git_pull_remote(ip)
            elif action == "restart_player":
                ok, msg = self.app.ssh.restart_player_service(ip)
            elif action == "enable_readonly":
                ok, msg = self.app.ssh.enable_remote_phase_cut_protection(ip)
            elif action == "disable_readonly":
                ok, msg = self.app.ssh.disable_remote_phase_cut_protection(ip)
            elif action == "fix_handshake":
                ok, msg = self.app.ssh.apply_remote_projector_handshake(ip)
            else:
                ok, msg = False, f"Acción desconocida: {action}"

            self._send_json({"success": ok, "message": msg})
            return

        # 7. API: Blindaje de toda la flota (/api/fleet/guardian)
        elif path == "/api/fleet/guardian":
            body = self._read_json_body()
            action = body.get("action")
            devices = self.app.discovery.get_all_devices()
            results = {}
            lock = threading.Lock()

            def _guardian_task(d):
                dev_ip = d.get("ip")
                if not dev_ip or not d.get("online", True):
                    return
                if action == "enable_readonly":
                    res_ok, res_msg = self.app.ssh.enable_remote_phase_cut_protection(dev_ip)
                elif action == "disable_readonly":
                    res_ok, res_msg = self.app.ssh.disable_remote_phase_cut_protection(dev_ip)
                elif action == "fix_handshake":
                    res_ok, res_msg = self.app.ssh.apply_remote_projector_handshake(dev_ip)
                else:
                    res_ok, res_msg = False, "Acción desconocida"
                with lock:
                    results[dev_ip] = {"success": res_ok, "message": res_msg}

            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(_guardian_task, devices))

            self._send_json({"success": True, "results": results})
            return

        # 7. API: Guardar credenciales globales
        elif path == "/api/config":
            body = self._read_json_body()
            user = body.get("default_ssh_user")
            password = body.get("default_ssh_password")
            port = body.get("default_ssh_port", 22)
            if user:
                # Si password es '******', no modificar el existente
                if password == "******":
                    password = self.app.creds.get_config().get("default_ssh_password", "")
                self.app.creds.set_default_ssh_credentials(user, password or "", port)
            self._send_json({"success": True, "message": "Credenciales guardadas"})
            return

        # 8. API: Agregar dispositivo manual
        elif path == "/api/manual_device":
            body = self._read_json_body()
            ip = body.get("ip", "").strip()
            name = body.get("name", "").strip()
            floor = body.get("floor", "").strip()
            if ip:
                self.app.creds.add_manual_device(ip, name, floor)
                dev = self.app.discovery.probe_device(ip) or {
                    "id": f"pi-{ip.replace('.', '-')}",
                    "name": name or f"Raspberry {ip}",
                    "ip": ip,
                    "floor": floor or "Sala",
                    "status": "online"
                }
                self.app.discovery.register_device(dev)
                self._send_json({"success": True, "device": dev})
            else:
                self._send_json({"success": False, "error": "IP requerida"}, status=400)
            return

        self.send_error(404, "Endpoint no encontrado")

    def _handle_video_upload(self, ip: str):
        """Procesa la subida de un video en multipart/form-data y lo envía por SFTP/SCP a la Pi."""
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._send_json({"success": False, "error": "Content-Type debe ser multipart/form-data"}, status=400)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length)

            # Parsear multipart usando módulo estándar email
            mime_header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1")
            msg = email.message_from_bytes(mime_header + raw_body)

            file_payload = None
            filename = None
            auto_play = True

            for part in msg.walk():
                if part.is_multipart():
                    continue
                cd = part.get("Content-Disposition", "")
                if 'name="auto_play"' in cd:
                    val = (part.get_payload(decode=True) or b"").decode("utf-8").strip().lower()
                    auto_play = (val == "true")
                elif 'name="file"' in cd:
                    m = re.search(r'filename="([^"]+)"', cd)
                    if m:
                        filename = os.path.basename(m.group(1))
                        file_payload = part.get_payload(decode=True)

            if not file_payload or not filename:
                self._send_json({"success": False, "error": "No se recibió archivo de video válido"}, status=400)
                return

            local_save_path = os.path.join(UPLOADS_DIR, filename)
            with open(local_save_path, "wb") as f:
                f.write(file_payload)

            # Transferir por SCP a la Raspberry Pi
            ok, remote_dest = self.app.ssh.upload_video_file(ip, local_save_path)

            # Limpiar archivo temporal de la notebook
            try:
                os.remove(local_save_path)
            except Exception:
                pass

            if ok:
                if auto_play:
                    self.app.ssh.switch_active_video(ip, remote_dest)
                self._send_json({
                    "success": True,
                    "message": f"Video '{filename}' transferido exitosamente a la Raspberry Pi",
                    "remote_path": remote_dest
                })
            else:
                self._send_json({"success": False, "error": remote_dest}, status=500)

        except Exception as e:
            self._send_json({"success": False, "error": f"Error en transferencia: {e}"}, status=500)


def run_fleet_manager(port: int = 5050):
    app = FleetManagerApp(port=port)
    app._running = True
    app.start_background_monitors()

    server_address = ("0.0.0.0", port)
    FleetRequestHandler.app = app

    try:
        httpd = _BaseServer(server_address, FleetRequestHandler)
        app._server = httpd
        local_ip = get_local_ip()
        print("\n" + "=" * 62)
        print("🚀 KIOSK FLEET MANAGER - TORRE DE CONTROL")
        print("=" * 62)
        print(f"➜ Panel Local en tu compu: http://localhost:{port}")
        print(f"➜ Red LAN:                 http://{local_ip}:{port}")
        print("=" * 62 + "\n")
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[FleetManager] Deteniendo servidor...")
        app.stop()
    except Exception as e:
        print(f"[FleetManager] Error iniciando servidor en puerto {port}: {e}")


if __name__ == "__main__":
    p = 5050
    if len(sys.argv) > 1:
        try:
            p = int(sys.argv[1])
        except Exception:
            pass
    run_fleet_manager(port=p)
