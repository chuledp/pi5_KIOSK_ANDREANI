"""
Motor de descubrimiento de red para Kiosk Fleet Manager.
Escanea la subred local para encontrar todas las Raspberry Pi activas.
"""

import socket
import urllib.request
import json
import threading
import time
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor


def get_local_ip() -> str:
    """Detecta la IP local de la notebook en la interfaz de red activa."""
    for target in [("1.1.1.1", 80), ("8.8.8.8", 80), ("10.254.254.254", 1), ("192.168.1.254", 1)]:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(target)
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


class FleetDiscovery:
    def __init__(self, web_port: int = 8080, offline_timeout: float = 300.0):
        self.web_port = web_port
        self.offline_timeout = offline_timeout
        self._lock = threading.Lock()
        self._devices: Dict[str, Dict[str, Any]] = {}
        self._scanning = False

    def probe_device(self, ip: str, port: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Intenta consultar la API REST o el puerto SSH de la Raspberry Pi en la IP dada."""
        # Evitar auto-descubrir la propia Mac
        if ip == get_local_ip():
            return None

        p = port or self.web_port
        url = f"http://{ip}:{p}/api/devices"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "KioskFleetManager/1.0"})
            with urllib.request.urlopen(req, timeout=0.6) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    devices_list = data.get("devices", [])
                    # Encontrar el nodo local de esa IP o usar el primer dispositivo
                    for d in devices_list:
                        if d.get("ip") == ip or d.get("id") == data.get("local_id"):
                            return d
                    if devices_list:
                        return devices_list[0]
                    # Si no devolvió lista, armar dict básico
                    return {
                        "id": f"pi-{ip.replace('.', '-')}",
                        "name": f"Raspberry Pi ({ip})",
                        "ip": ip,
                        "port": p,
                        "status": "online",
                        "floor": "Sala"
                    }
        except Exception:
            pass

        # Fallback inteligente: Si HTTP (8080) aún no está levantado, chequear si SSH (22) está activo
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4)
        try:
            s.connect((ip, 22))
            return {
                "id": f"pi-{ip.replace('.', '-')}",
                "name": f"Raspberry Pi ({ip})",
                "ip": ip,
                "port": p,
                "status": "online",
                "ssh_only": True,
                "floor": "Sala"
            }
        except Exception:
            pass
        finally:
            s.close()

        return None

    def scan_network(self, custom_subnets: Optional[List[str]] = None, max_workers: int = 40) -> List[Dict[str, Any]]:
        """Escanea todas las IPs de la subred local en paralelo."""
        with self._lock:
            if self._scanning:
                return self.get_all_devices()
            self._scanning = True

        try:
            subnets = custom_subnets or []
            local_ip = get_local_ip()
            if local_ip and local_ip != "127.0.0.1" and "." in local_ip:
                prefix = local_ip.rsplit(".", 1)[0]
                if prefix not in subnets:
                    subnets.append(prefix)

            candidates = []
            for sub in subnets:
                for i in range(1, 255):
                    candidates.append(f"{sub}.{i}")

            discovered = []
            disc_lock = threading.Lock()

            def _worker(ip: str):
                dev = self.probe_device(ip)
                if dev:
                    dev["last_seen"] = time.time()
                    dev["online"] = True
                    self.register_device(dev)
                    with disc_lock:
                        discovered.append(dev)

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                list(pool.map(_worker, candidates))

            now = time.time()
            with self._lock:
                disc_ips = {x.get("ip") for x in discovered if x.get("ip")}
                for d in self._devices.values():
                    if d.get("ip") in disc_ips:
                        d["last_seen"] = now
                        d["status"] = "online"
                        d["online"] = True

            return self.get_all_devices()
        finally:
            with self._lock:
                self._scanning = False

    def register_device(self, dev_info: Dict[str, Any]) -> None:
        dev_id = dev_info.get("id") or f"pi-{dev_info.get('ip', 'unknown').replace('.', '-')}"
        with self._lock:
            existing = self._devices.get(dev_id, {})
            merged = dict(existing)
            merged.update(dev_info)
            merged["id"] = dev_id
            merged["last_seen"] = time.time()
            merged["online"] = True
            self._devices[dev_id] = merged

    def get_all_devices(self) -> List[Dict[str, Any]]:
        now = time.time()
        res = []
        with self._lock:
            for dev_id, dev in list(self._devices.items()):
                item = dict(dev)
                last_seen = item.get("last_seen", 0)
                is_online = (now - last_seen) < self.offline_timeout
                item["online"] = is_online
                if not is_online:
                    item["status"] = "offline"
                res.append(item)
        return res

    def get_device_by_ip(self, ip: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for dev in self._devices.values():
                if dev.get("ip") == ip:
                    return dict(dev)
        return None

    def remove_device(self, dev_id: str) -> None:
        with self._lock:
            if dev_id in self._devices:
                del self._devices[dev_id]

