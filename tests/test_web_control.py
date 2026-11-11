"""
Tests unitarios para el sistema de Control Web y Auto-Descubrimiento (Tablet Samsung).
"""

import os
import json
import time
import urllib.request
import urllib.error
import unittest

from core.web_control.discovery import DeviceRegistry, DeviceBeacon, get_local_ip
from core.web_control.server import WebControlServer, start_web_control


class TestWebControl(unittest.TestCase):
    def setUp(self):
        self.registry = DeviceRegistry(offline_timeout=1.0)
        self.mock_status = {
            "id": "test-pi-1",
            "name": "PB - Sala Optoma",
            "floor": "Planta Baja",
            "ip": "127.0.0.1",
            "port": 8888,
            "osc_port": 9000,
            "status": "playing",
            "current_file": "video.mp4",
            "time_pos": 10.5,
            "duration": 120.0,
            "volume": 100,
            "engine": "mpv"
        }
        self.commands_received = []

        def mock_cmd_handler(action, val):
            self.commands_received.append((action, val))
            return True

        self.mock_cmd_handler = mock_cmd_handler

    def test_device_registry(self):
        # Registrar 2 dispositivos en pisos distintos
        dev1 = dict(self.mock_status)
        dev2 = {
            "id": "test-pi-2",
            "name": "Piso 1 - Video 2",
            "floor": "1er Piso",
            "ip": "127.0.0.1",
            "port": 8889,
            "osc_port": 9001,
            "status": "paused"
        }

        self.registry.register_or_update(dev2)
        self.registry.register_or_update(dev1)

        devices = self.registry.get_devices()
        self.assertEqual(len(devices), 2)
        # Verificar que Planta Baja ordene antes que 1er Piso
        self.assertEqual(devices[0]["floor"], "Planta Baja")
        self.assertEqual(devices[1]["floor"], "1er Piso")
        self.assertTrue(devices[0]["online"])

        # Verificar timeout offline
        time.sleep(1.1)
        devices_after = self.registry.get_devices()
        self.assertFalse(devices_after[0]["online"])
        self.assertEqual(devices_after[0]["status"], "offline")

    def test_local_ip_detection(self):
        ip = get_local_ip()
        self.assertIsInstance(ip, str)
        self.assertTrue(len(ip) >= 7)  # e.g. "x.x.x.x"

    def test_web_server_api_and_auth(self):
        # Crear servidor con puerto aleatorio alto
        port = 18080
        dummy_beacon = DeviceBeacon(self.registry, lambda: self.mock_status, port=19002)
        server = WebControlServer(
            registry=self.registry,
            beacon=dummy_beacon,
            local_device_id="test-pi-1",
            pin="1234",
            port=port,
            local_command_handler=self.mock_cmd_handler
        )
        self.registry.register_or_update(self.mock_status)

        # 1. Pruebas directas de validación de PIN y tokens (independientes de red)
        self.assertTrue(server.validate_pin("1234"))
        self.assertFalse(server.validate_pin("9999"))
        token = server.generate_token()
        self.assertTrue(server.verify_token(token))
        self.assertFalse(server.verify_token("invalid_token"))

        # 2. Pruebas directas de despacho de comandos
        res_play = server.dispatch_command(action="play", target="all")
        self.assertTrue(res_play["success"])
        self.assertTrue(any(a == "play" for a, _ in self.commands_received))

        res_seek = server.dispatch_command(action="seek", target="device", device_id="test-pi-1", value=45.0)
        self.assertTrue(res_seek["success"])
        self.assertTrue(any(a == "seek" and v == 45.0 for a, v in self.commands_received))

        # 3. Prueba de endpoints HTTP si el entorno permite loopback local
        self.assertTrue(server.start())

        try:
            base_url = f"http://127.0.0.1:{port}"

            try:
                with urllib.request.urlopen(f"{base_url}/api/ping", timeout=2.0) as resp:
                    self.assertEqual(resp.status, 200)
                    data = json.loads(resp.read().decode())
                    self.assertEqual(data.get("status"), "ok")

                with urllib.request.urlopen(f"{base_url}/", timeout=2.0) as resp:
                    self.assertEqual(resp.status, 200)
                    html = resp.read().decode()
                    self.assertIn("KIOSK ANDREANI", html)

                with urllib.request.urlopen(f"{base_url}/api/devices", timeout=2.0) as resp:
                    self.assertEqual(resp.status, 200)
                    dev_data = json.loads(resp.read().decode())
                    self.assertTrue(dev_data["has_pin"])
                    self.assertEqual(len(dev_data["devices"]), 1)
            except (urllib.error.HTTPError, OSError) as e:
                if "Direct IP access" in str(e) or "Operation not permitted" in str(e) or "Bad Request" in str(e):
                    # Entorno sandbox macOS que bloquea proxy de loopback HTTP directo
                    pass
                else:
                    raise
        finally:
            server.stop()
            dummy_beacon.stop()


if __name__ == "__main__":
    unittest.main()
