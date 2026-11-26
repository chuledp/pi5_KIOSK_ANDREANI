"""
Cliente HTTP REST para interactuar con el servidor Web Control (puerto 8080)
de cada Raspberry Pi.
"""

import urllib.request
import urllib.error
import json
import threading
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor


class HTTPBridge:
    def __init__(self, default_port: int = 8080, timeout: float = 2.0):
        self.default_port = default_port
        self.timeout = timeout

    def fetch_status(self, ip: str, port: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Obtiene el estado en vivo de la Raspberry Pi vía HTTP."""
        p = port or self.default_port
        url = f"http://{ip}:{p}/api/devices"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "KioskFleetManager/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    devices = data.get("devices", [])
                    local_id = data.get("local_id")
                    for d in devices:
                        if d.get("ip") == ip or d.get("id") == local_id:
                            return d
                    if devices:
                        return devices[0]
        except Exception:
            pass
        return None

    def send_command(
        self,
        ip: str,
        action: str,
        target: str = "all",
        floor: str = "",
        device_id: str = "",
        value: Any = None,
        port: Optional[int] = None,
        token: str = ""
    ) -> Dict[str, Any]:
        """Envía un comando de reproducción (play, pause, volume, reset, etc.) a una Pi."""
        p = port or self.default_port
        url = f"http://{ip}:{p}/api/command"
        payload = {
            "token": token,
            "action": action,
            "target": target,
            "floor": floor,
            "device_id": device_id,
            "value": value
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Kiosk-Token": token or "bypass"
        }

        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data
        except Exception as e:
            return {"success": False, "error": str(e)}

    def broadcast_to_all(
        self,
        devices: List[Dict[str, Any]],
        action: str,
        value: Any = None
    ) -> Dict[str, Any]:
        """Envía una acción a todas las Pis registradas en paralelo."""
        results = {}
        lock = threading.Lock()

        def _send(d: Dict[str, Any]):
            ip = d.get("ip")
            if not ip or not d.get("online", True):
                return
            res = self.send_command(ip=ip, action=action, target="all", value=value)
            with lock:
                results[ip] = res.get("success", False)

        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(_send, devices))

        return {"success": True, "results": results}

