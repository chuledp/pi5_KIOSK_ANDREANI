"""
Servidor Web HTTP nativo (Python puro) para Control Remoto Kiosk y Tablet Samsung.
Sirve la interfaz web responsive y expone la API REST para el control de todas
las Raspberry Pi de la red local.
"""

import os
import sys
import json
import time
import socket
import hashlib
import secrets
import threading
import subprocess
from typing import Dict, Any, Optional, Callable
from http.server import HTTPServer, BaseHTTPRequestHandler
try:
    from http.server import ThreadingHTTPServer
    _BaseHTTPServer = ThreadingHTTPServer
except ImportError:
    _BaseHTTPServer = HTTPServer  # type: ignore

class ReusableThreadingHTTPServer(_BaseHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

from core.web_control.discovery import DeviceRegistry, DeviceBeacon, get_local_ip
from core.osc_receiver import build_osc_message

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class WebControlRequestHandler(BaseHTTPRequestHandler):
    """Manejador de peticiones HTTP para la tablet y API REST."""

    # Referencia al servidor que contiene registry, pin, controller, etc.
    server: "WebControlServer"  # type: ignore

    def log_message(self, format, *args):
        # Silenciar logs ruidosos de polling cada 1 segundo
        pass

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Kiosk-Token")

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

    @property
    def web_control(self) -> 'WebControlServer':
        """Obtiene la referencia a la instancia WebControlServer asociada."""
        return getattr(self.server, "web_control", getattr(self.server, "server", self.server))

    def _is_authenticated(self, data: Optional[Dict[str, Any]] = None) -> bool:
        """Verifica si la petición está autorizada con el PIN configurado."""
        pin = self.web_control.pin if self.web_control else ""
        if not pin or not pin.strip():
            return True  # Sin PIN requerido: acceso libre inmediato

        token = ""
        if data and "token" in data:
            token = str(data["token"]).strip()
        if not token:
            token = self.headers.get("X-Kiosk-Token", "").strip()

        return self.web_control.verify_token(token)

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            index_path = os.path.join(STATIC_DIR, "index.html")
            if os.path.exists(index_path):
                try:
                    with open(index_path, "rb") as f:
                        content = f.read()
                    self.send_response(200)
                    self._send_cors_headers()
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                except Exception as e:
                    self._send_json({"error": f"Error leyendo index.html: {e}"}, status=500)
                    return
            else:
                self._send_json({"error": "index.html no encontrado"}, status=404)
                return

        elif path == "/api/ping":
            self._send_json({"status": "ok", "time": time.time()})
            return

        elif path == "/api/devices":
            # Si el beacon está activo, enviar un ping rápido si la lista está vacía
            pin = (self.web_control.pin if self.web_control else "").strip()
            devices = self.web_control.registry.get_devices()
            self._send_json({
                "success": True,
                "server_time": time.time(),
                "local_id": self.web_control.local_device_id,
                "has_pin": bool(pin),
                "devices": devices
            })
            return

        self._send_json({"error": "Ruta no encontrada"}, status=404)

    def do_POST(self):
        path = self.path.split("?")[0]
        data = self._read_json_body()

        if path == "/api/auth":
            pin = str(data.get("pin", "")).strip()
            if self.web_control.validate_pin(pin):
                token = self.web_control.generate_token()
                self._send_json({"success": True, "token": token})
            else:
                self._send_json({"success": False, "error": "PIN incorrecto"}, status=401)
            return

        elif path == "/api/command":
            if not self._is_authenticated(data):
                self._send_json({"success": False, "error": "No autorizado. Ingrese el PIN."}, status=401)
                return

            action = str(data.get("action", "")).lower()
            target = str(data.get("target", "all")).lower()
            floor = str(data.get("floor", ""))
            device_id = str(data.get("device_id", ""))
            value = data.get("value")

            result = self.web_control.dispatch_command(
                action=action,
                target=target,
                floor=floor,
                device_id=device_id,
                value=value
            )
            self._send_json(result)
            return

        self._send_json({"error": "Ruta no encontrada"}, status=404)


class WebControlServer:
    """
    Servidor HTTP Multi-hilo con controlador de comandos y despacho OSC/REST.
    """
    def __init__(
        self,
        registry: DeviceRegistry,
        beacon: DeviceBeacon,
        local_device_id: str,
        pin: str = "",
        port: int = 8080,
        local_command_handler: Optional[Callable[[str, Any], bool]] = None
    ):
        self.registry = registry
        self.beacon = beacon
        self.local_device_id = local_device_id
        self.pin = (pin or "").strip()
        self.port = port
        self.local_command_handler = local_command_handler

        self._server: Optional[ThreadingHTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._valid_tokens: set[str] = set()
        self._token_lock = threading.Lock()

        # Socket UDP dedicado para broadcast OSC
        self._osc_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._osc_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def validate_pin(self, candidate_pin: str) -> bool:
        if not self.pin:
            return True
        return candidate_pin == self.pin

    def generate_token(self) -> str:
        token = secrets.token_hex(16)
        with self._token_lock:
            self._valid_tokens.add(token)
        return token

    def verify_token(self, token: str) -> bool:
        if not self.pin:
            return True
        if not token:
            return False
        with self._token_lock:
            return token in self._valid_tokens

    def start(self) -> bool:
        try:
            # Crear servidor HTTP multi-hilo con SO_REUSEADDR
            handler_class = WebControlRequestHandler
            self._server = ReusableThreadingHTTPServer(("0.0.0.0", self.port), handler_class)
            # Inyectar referencia de self en la instancia del servidor para que el handler acceda
            self._server.web_control = self  # type: ignore
            self._server.server = self  # type: ignore
            self._server.registry = self.registry  # type: ignore
            self._server.beacon = self.beacon  # type: ignore
            self._server.local_device_id = self.local_device_id  # type: ignore
            self._server.pin = self.pin  # type: ignore
            self._server.validate_pin = self.validate_pin  # type: ignore
            self._server.generate_token = self.generate_token  # type: ignore
            self._server.verify_token = self.verify_token  # type: ignore
            self._server.dispatch_command = self.dispatch_command  # type: ignore

            self._server_thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True,
                name="WebControlHttp"
            )
            self._server_thread.start()
            print(f"[WebControl] Servidor Web iniciado en http://0.0.0.0:{self.port}")
            return True
        except Exception as e:
            print(f"[WebControl] Error iniciando servidor HTTP en puerto {self.port}: {e}")
            return False

    def stop(self) -> None:
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
        if self.beacon:
            try:
                self.beacon.stop()
            except Exception:
                pass
        try:
            self._osc_sock.close()
        except Exception:
            pass

    def send_osc_packet(self, host: str, port: int, address: str, args: Optional[list] = None) -> None:
        """Envía un paquete OSC binario a la IP y puerto especificados."""
        try:
            pkt = build_osc_message(address, args or [])
            self._osc_sock.sendto(pkt, (host, port))
        except Exception as e:
            print(f"[WebControl] Error enviando OSC {address} a {host}:{port}: {e}")

    def dispatch_command(
        self,
        action: str,
        target: str = "all",
        floor: str = "",
        device_id: str = "",
        value: Any = None
    ) -> Dict[str, Any]:
        """
        Despacha un comando de control a toda la red, a un piso o a una Raspberry Pi individual.
        """
        # 1. Comandos de Sistema Críticos (Apagado / Reinicio)
        if action in ("shutdown", "reboot"):
            return self._dispatch_system_action(action, target, floor, device_id)

        # 2. Mapeo de acción a ruta OSC y argumentos
        osc_addr = f"/{action}"
        osc_args = []
        if action == "seek" and value is not None:
            try:
                osc_args = [float(value)]
            except Exception:
                pass
        elif action == "position" and value is not None:
            try:
                osc_args = [float(value)]
            except Exception:
                pass
        elif action == "volume" and value is not None:
            try:
                osc_args = [int(value)]
            except Exception:
                pass
        elif action == "cue" and value is not None:
            osc_args = [str(value)]

        # 3. Despacho según objetivo
        executed_count = 0

        # CASO A: Todas las Raspberry Pi (Broadcast UDP instantáneo < 2ms)
        if target == "all":
            # Enviar por broadcast UDP a todas las máquinas en puerto 9000
            self.send_osc_packet("255.255.255.255", 9000, osc_addr, osc_args)
            # Ejecutar localmente también
            if self.local_command_handler:
                try:
                    self.local_command_handler(action, value)
                except Exception:
                    pass
            # Pedir a los beacons que refresquen estado
            self.beacon.trigger_announcement()
            return {"success": True, "message": f"Comando '{action}' enviado a todo el edificio por broadcast."}

        # CASO B: Un Piso Específico (Planta Baja, 1er Piso, etc.)
        elif target == "floor":
            devices = self.registry.get_devices()
            target_devices = [d for d in devices if d.get("floor", "").lower() == floor.lower() and d.get("online", False)]
            for dev in target_devices:
                ip = dev.get("ip")
                port = int(dev.get("osc_port", 9000))
                if ip:
                    self.send_osc_packet(ip, port, osc_addr, osc_args)
                    executed_count += 1
            # Si este nodo está en ese piso, ejecutarlo localmente
            local_dev = self.registry.get_device(self.local_device_id)
            if local_dev and local_dev.get("floor", "").lower() == floor.lower():
                if self.local_command_handler:
                    try:
                        self.local_command_handler(action, value)
                    except Exception:
                        pass
            self.beacon.trigger_announcement()
            return {"success": True, "message": f"Comando '{action}' enviado a {executed_count} equipos del piso '{floor}'."}

        # CASO C: Una Raspberry Pi individual
        elif target == "device":
            if device_id == self.local_device_id:
                if self.local_command_handler:
                    ok = self.local_command_handler(action, value)
                    self.beacon.trigger_announcement()
                    return {"success": ok, "message": f"Comando '{action}' ejecutado en equipo local."}
            else:
                dev = self.registry.get_device(device_id)
                if dev and dev.get("ip"):
                    ip = dev["ip"]
                    port = int(dev.get("osc_port", 9000))
                    self.send_osc_packet(ip, port, osc_addr, osc_args)
                    return {"success": True, "message": f"Comando '{action}' enviado a {dev.get('name', device_id)} ({ip})."}
                return {"success": False, "error": f"Dispositivo '{device_id}' no encontrado o sin IP."}

        return {"success": False, "error": f"Objetivo '{target}' desconocido."}

    def _dispatch_system_action(self, action: str, target: str, floor: str, device_id: str) -> Dict[str, Any]:
        """Ejecuta apagado seguro o reinicio del sistema operativo."""
        cmd_linux = ["sudo", "systemctl", "poweroff"] if action == "shutdown" else ["sudo", "systemctl", "reboot"]

        def _execute_local_system_cmd():
            time.sleep(1.0)
            if sys.platform.startswith("linux"):
                try:
                    subprocess.run(cmd_linux, check=False)
                except Exception:
                    try:
                        subprocess.run(["sudo", "shutdown", "-h" if action == "shutdown" else "-r", "now"], check=False)
                    except Exception:
                        pass
            else:
                print(f"[WebControl Simulado] Acción de sistema local: {action}")

        # Si el objetivo es solo local o todos
        if target == "all":
            # Para las demás máquinas, si tienen el webserver podemos mandarles el trigger
            devices = self.registry.get_devices()
            for dev in devices:
                if dev.get("id") != self.local_device_id and dev.get("ip"):
                    try:
                        # Enviar petición POST a la otra Pi
                        import urllib.request
                        url = f"http://{dev['ip']}:{dev.get('port', 8080)}/api/command"
                        req_data = json.dumps({"action": action, "target": "device", "device_id": dev["id"]}).encode("utf-8")
                        req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json", "X-Kiosk-Token": "bypass"})
                        urllib.request.urlopen(req, timeout=1.5)
                    except Exception:
                        pass
            # Ejecutar en hilo de fondo para responder primero a la tablet
            threading.Thread(target=_execute_local_system_cmd, daemon=True).start()
            return {"success": True, "message": f"Iniciando {action} en todo el edificio..."}

        elif target == "device" and device_id == self.local_device_id:
            threading.Thread(target=_execute_local_system_cmd, daemon=True).start()
            return {"success": True, "message": f"Iniciando {action} en este equipo local..."}

        elif target == "device":
            dev = self.registry.get_device(device_id)
            if dev and dev.get("ip"):
                try:
                    import urllib.request
                    url = f"http://{dev['ip']}:{dev.get('port', 8080)}/api/command"
                    req_data = json.dumps({"action": action, "target": "device", "device_id": device_id}).encode("utf-8")
                    req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json", "X-Kiosk-Token": "bypass"})
                    urllib.request.urlopen(req, timeout=2.0)
                    return {"success": True, "message": f"{action} enviado a {dev.get('name')}."}
                except Exception as e:
                    return {"success": False, "error": f"No se pudo conectar a {dev.get('name')}: {e}"}

        return {"success": False, "error": f"Objetivo de sistema no válido"}


def start_web_control(
    profile: Dict[str, Any],
    status_provider: Callable[[], Dict[str, Any]],
    local_command_handler: Optional[Callable[[str, Any], bool]] = None
) -> Optional[WebControlServer]:
    """Inicia el DeviceBeacon y el WebControlServer para el perfil dado."""
    if not profile.get("web_control_enabled", True):
        return None

    port = int(profile.get("web_control_port", 8080))
    pin = str(profile.get("web_control_pin", "")).strip()
    device_id = str(profile.get("id", "pi-node"))

    registry = DeviceRegistry()
    beacon = DeviceBeacon(registry=registry, status_provider=status_provider)
    beacon.start()

    server = WebControlServer(
        registry=registry,
        beacon=beacon,
        local_device_id=device_id,
        pin=pin,
        port=port,
        local_command_handler=local_command_handler
    )
    if server.start():
        return server

    beacon.stop()
    return None

