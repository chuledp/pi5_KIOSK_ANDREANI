"""
Gestor de credenciales y configuración local para Kiosk Fleet Manager.
Guarda las credenciales SSH y preferencias en config.json de manera segura.
"""

import os
import json
from typing import Dict, Any, Optional

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "default_ssh_user": "pi",
    "default_ssh_password": "",
    "default_ssh_port": 22,
    "web_control_port": 8080,
    "scan_subnets": [],
    "manual_devices": [],
    "device_credentials": {}  # ip -> {"user": "...", "password": "..."}
}


class CredentialsManager:
    def __init__(self, config_path: str = CONFIG_FILE):
        self.config_path = config_path
        self._config: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cfg = dict(DEFAULT_CONFIG)
                    cfg.update(data)
                    return cfg
            except Exception as e:
                print(f"[Credentials] Error cargando {self.config_path}: {e}")
        return dict(DEFAULT_CONFIG)

    def save(self) -> bool:
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[Credentials] Error guardando {self.config_path}: {e}")
            return False

    def get_ssh_credentials(self, ip: str) -> Dict[str, Any]:
        """Obtiene credenciales SSH para una IP específica o el valor por defecto."""
        dev_creds = self._config.get("device_credentials", {}).get(ip)
        if dev_creds and dev_creds.get("user"):
            return {
                "user": dev_creds["user"],
                "password": dev_creds.get("password", ""),
                "port": dev_creds.get("port", self._config.get("default_ssh_port", 22))
            }
        return {
            "user": self._config.get("default_ssh_user", "pi"),
            "password": self._config.get("default_ssh_password", ""),
            "port": self._config.get("default_ssh_port", 22)
        }

    def set_default_ssh_credentials(self, user: str, password: str, port: int = 22) -> None:
        self._config["default_ssh_user"] = user.strip()
        self._config["default_ssh_password"] = password
        self._config["default_ssh_port"] = int(port)
        self.save()

    def set_device_credentials(self, ip: str, user: str, password: str, port: int = 22) -> None:
        if "device_credentials" not in self._config:
            self._config["device_credentials"] = {}
        self._config["device_credentials"][ip] = {
            "user": user.strip(),
            "password": password,
            "port": int(port)
        }
        self.save()

    def add_manual_device(self, ip: str, name: str = "", floor: str = "") -> None:
        devices = self._config.get("manual_devices", [])
        # Evitar duplicados por IP
        devices = [d for d in devices if d.get("ip") != ip]
        devices.append({"ip": ip, "name": name or f"Raspberry {ip}", "floor": floor or "Sala"})
        self._config["manual_devices"] = devices
        self.save()

    def remove_manual_device(self, ip: str) -> None:
        devices = self._config.get("manual_devices", [])
        self._config["manual_devices"] = [d for d in devices if d.get("ip") != ip]
        self.save()

    def get_config(self) -> Dict[str, Any]:
        # Copia para devolver a la UI ocultando passwords completos si se requiere
        cfg = dict(self._config)
        return cfg

