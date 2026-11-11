"""
Módulo de Auto-Descubrimiento en Red Local (UDP Beacon) para Raspberry Pi Kiosk.
Permite que todas las Raspberry Pi conectadas a la misma red se descubran solas
y reporten su estado en tiempo real sin necesidad de configurar direcciones IP a mano.
"""

import os
import sys
import json
import time
import socket
import select
import threading
from typing import Dict, Any, List, Optional, Callable

DEFAULT_DISCOVERY_PORT = 9002


def get_local_ip() -> str:
    """Detecta la IP local de la Raspberry Pi en la red LAN activa."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No requiere conexión a internet real, solo resuelve interfaz de salida
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    finally:
        s.close()
    return ip


class DeviceRegistry:
    """Registro en memoria protegido por hilo de todas las Raspberry Pi vistas en la red."""
    def __init__(self, offline_timeout: float = 6.0):
        self._lock = threading.Lock()
        self._devices: Dict[str, Dict[str, Any]] = {}
        self.offline_timeout = offline_timeout

    def register_or_update(self, data: Dict[str, Any]) -> None:
        device_id = str(data.get("id") or data.get("ip") or "unknown")
        data["last_seen"] = time.time()
        with self._lock:
            # Si ya existía, preservamos ciertos campos y actualizamos
            self._devices[device_id] = data

    def get_devices(self) -> List[Dict[str, Any]]:
        now = time.time()
        result = []
        with self._lock:
            for dev_id, dev in list(self._devices.items()):
                dev_copy = dict(dev)
                is_online = (now - dev_copy.get("last_seen", 0)) < self.offline_timeout
                dev_copy["online"] = is_online
                if not is_online:
                    dev_copy["status"] = "offline"
                result.append(dev_copy)

        # Ordenar por piso (Planta Baja primero, 1er Piso, 2do Piso...) y por nombre
        def sort_key(d):
            floor = d.get("floor", "").lower()
            order = 0
            if "baja" in floor or "pb" in floor:
                order = 1
            elif "1" in floor:
                order = 2
            elif "2" in floor:
                order = 3
            elif "3" in floor:
                order = 4
            else:
                order = 9
            return (order, d.get("name", "").lower())

        result.sort(key=sort_key)
        return result

    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            dev = self._devices.get(device_id)
            if not dev:
                return None
            dev_copy = dict(dev)
            dev_copy["online"] = (time.time() - dev_copy.get("last_seen", 0)) < self.offline_timeout
            return dev_copy

    def remove_device(self, device_id: str) -> None:
        with self._lock:
            self._devices.pop(device_id, None)


class DeviceBeacon:
    """
    Emisor y receptor de beacons UDP en broadcast (puerto 9002).
    - Emite periódicamente el estado de la Raspberry Pi local.
    - Escucha beacons de las demás Raspberry Pi y las agrega al DeviceRegistry.
    """
    def __init__(
        self,
        registry: DeviceRegistry,
        status_provider: Callable[[], Dict[str, Any]],
        port: int = DEFAULT_DISCOVERY_PORT,
        broadcast_interval: float = 1.5
    ):
        self.registry = registry
        self.status_provider = status_provider
        self.port = port
        self.broadcast_interval = broadcast_interval
        self._running = False
        self._send_thread: Optional[threading.Thread] = None
        self._recv_thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        # Socket UDP reutilizable para broadcast
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except Exception:
                pass

        try:
            self._sock.bind(("0.0.0.0", self.port))
        except Exception as e:
            print(f"[DeviceBeacon] Nota: No se pudo enlazar a 0.0.0.0:{self.port}: {e}")

        self._recv_thread = threading.Thread(target=self._listen_loop, daemon=True, name="BeaconRecv")
        self._send_thread = threading.Thread(target=self._broadcast_loop, daemon=True, name="BeaconSend")

        self._recv_thread.start()
        self._send_thread.start()
        # Enviar un anuncio inicial inmediato
        self.trigger_announcement()

    def stop(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def trigger_announcement(self) -> None:
        """Fuerza un envío inmediato del estado local."""
        if not self._sock or not self._running:
            return
        try:
            data = self.status_provider()
            if not data.get("ip") or data.get("ip") == "127.0.0.1":
                data["ip"] = get_local_ip()
            # Registrar localmente en el registro propio
            self.registry.register_or_update(data)
            payload = json.dumps(data).encode("utf-8")
            self._sock.sendto(payload, ("255.255.255.255", self.port))
        except Exception:
            pass

    def send_ping(self) -> None:
        """Pide a todas las Raspberry Pi de la red que respondan de inmediato."""
        if not self._sock or not self._running:
            return
        try:
            ping_msg = json.dumps({"action": "WHOIS"}).encode("utf-8")
            self._sock.sendto(ping_msg, ("255.255.255.255", self.port))
        except Exception:
            pass

    def _broadcast_loop(self) -> None:
        while self._running:
            self.trigger_announcement()
            time.sleep(self.broadcast_interval)

    def _listen_loop(self) -> None:
        buf_size = 4096
        while self._running:
            if not self._sock:
                break
            try:
                r, _, _ = select.select([self._sock], [], [], 0.5)
                if not r or not self._running:
                    continue
                data, addr = self._sock.recvfrom(buf_size)
                if not data:
                    continue

                try:
                    parsed = json.loads(data.decode("utf-8", errors="ignore"))
                except Exception:
                    continue

                if not isinstance(parsed, dict):
                    continue

                # Si es un WHOIS de otra máquina o tablet, responder con nuestro estado
                if parsed.get("action") == "WHOIS":
                    self.trigger_announcement()
                    continue

                # Si viene con IP nula o localhost, actualizarla con la dirección remitente
                if not parsed.get("ip") or parsed.get("ip") == "127.0.0.1":
                    parsed["ip"] = addr[0]

                # Registrar equipo en la lista de dispositivos activos
                self.registry.register_or_update(parsed)

            except Exception:
                if not self._running:
                    break
                time.sleep(0.1)

