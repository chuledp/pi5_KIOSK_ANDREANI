"""
Módulo de Control Web Remoto para Tablet y Monitoreo Multi-Raspberry Pi.
Proporciona auto-descubrimiento en red local, API REST y panel de control web táctil.
"""

from core.web_control.discovery import DeviceRegistry, DeviceBeacon
from core.web_control.server import WebControlServer, start_web_control

__all__ = ["DeviceRegistry", "DeviceBeacon", "WebControlServer", "start_web_control"]
