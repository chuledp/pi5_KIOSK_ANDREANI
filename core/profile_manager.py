import os
import json
import uuid
from typing import Dict, List, Optional, Any

DEFAULT_CONFIG_DIR = os.path.expanduser("~/.config/vlc-autoplay")
DEFAULT_CONFIG_PATH = os.path.join(DEFAULT_CONFIG_DIR, "config.json")

def create_default_profile(name: str = "Mi Instalación") -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "file_path": "",
        "fullscreen": True,
        "loop": True,
        "hide_osd": True,
        "hide_mouse": True,
        "no_audio": False,
        "volume": 100,
        "delay_seconds": 5,
        "extra_args": ""
    }

class ProfileManager:
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.config_dir = os.path.dirname(self.config_path)
        self.data: Dict[str, Any] = {
            "active_profile_id": None,
            "autostart_enabled": False,
            "profiles": []
        }
        self.load()

    def load(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    self.data["active_profile_id"] = loaded.get("active_profile_id")
                    self.data["autostart_enabled"] = bool(loaded.get("autostart_enabled", False))
                    self.data["profiles"] = loaded.get("profiles", [])
            except Exception as e:
                print(f"Error cargando configuración: {e}")
                self._init_defaults()
        else:
            self._init_defaults()

    def _init_defaults(self):
        default_prof = create_default_profile("Sala Principal (Default)")
        self.data = {
            "active_profile_id": default_prof["id"],
            "autostart_enabled": False,
            "profiles": [default_prof]
        }
        self.save()

    def save(self):
        os.makedirs(self.config_dir, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def get_profiles(self) -> List[Dict[str, Any]]:
        return self.data["profiles"]

    def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        for p in self.data["profiles"]:
            if p["id"] == profile_id:
                return p
        return None

    def get_active_profile(self) -> Optional[Dict[str, Any]]:
        active_id = self.data.get("active_profile_id")
        if active_id:
            return self.get_profile(active_id)
        if self.data["profiles"]:
            return self.data["profiles"][0]
        return None

    def set_active_profile(self, profile_id: str):
        if self.get_profile(profile_id):
            self.data["active_profile_id"] = profile_id
            self.save()

    def is_autostart_enabled(self) -> bool:
        return self.data.get("autostart_enabled", False)

    def set_autostart_enabled(self, enabled: bool):
        self.data["autostart_enabled"] = enabled
        self.save()

    def add_profile(self, name: str = "Nueva Obra") -> Dict[str, Any]:
        new_prof = create_default_profile(name)
        self.data["profiles"].append(new_prof)
        if not self.data.get("active_profile_id"):
            self.data["active_profile_id"] = new_prof["id"]
        self.save()
        return new_prof

    def update_profile(self, profile_id: str, updates: Dict[str, Any]) -> bool:
        prof = self.get_profile(profile_id)
        if prof:
            prof.update(updates)
            self.save()
            return True
        return False

    def duplicate_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        source = self.get_profile(profile_id)
        if not source:
            return None
        clone = dict(source)
        clone["id"] = str(uuid.uuid4())[:8]
        clone["name"] = f"{source['name']} (Copia)"
        self.data["profiles"].append(clone)
        self.save()
        return clone

    def delete_profile(self, profile_id: str) -> bool:
        profiles = self.data["profiles"]
        if len(profiles) <= 1:
            return False  # No permitimos eliminar el único perfil
        
        self.data["profiles"] = [p for p in profiles if p["id"] != profile_id]
        if self.data.get("active_profile_id") == profile_id:
            self.data["active_profile_id"] = self.data["profiles"][0]["id"]
        self.save()
        return True
