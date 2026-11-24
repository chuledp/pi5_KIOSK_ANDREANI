"""
Tests unitarios para Kiosk Guardian (Protección de Fase / Read-Only & Handshake Proyectores).
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.kiosk_guardian import (
    is_raspberry_pi,
    get_boot_config_paths,
    is_overlayfs_active,
    is_overlayfs_configured,
    is_boot_readonly,
    is_swap_disabled,
    get_system_hardening_status,
    enable_phase_cut_protection,
    disable_phase_cut_protection,
    apply_projector_handshake_fix,
    HDMIWatchdog
)


class TestKioskGuardian(unittest.TestCase):
    def test_status_structure(self):
        status = get_system_hardening_status()
        self.assertIsInstance(status, dict)
        self.assertIn("is_raspberry_pi", status)
        self.assertIn("overlayfs_active", status)
        self.assertIn("swap_disabled", status)
        self.assertIn("sd_status_text", status)
        self.assertIn("hdmi_status_text", status)
        self.assertIn("fully_protected", status)
        self.assertIn("projectors_hardened", status)

    def test_apply_projector_handshake_mock_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = os.path.join(tmp_dir, "config.txt")
            cmd_path = os.path.join(tmp_dir, "cmdline.txt")

            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write("# Config inicial\ngpu_mem=128\n")
            with open(cmd_path, "w", encoding="utf-8") as f:
                f.write("console=serial0,115200 console=tty1 root=PARTUUID=1234 fsck.repair=yes rootwait")

            with patch("core.kiosk_guardian.get_boot_config_paths", return_value=(cfg_path, cmd_path)):
                ok, msg = apply_projector_handshake_fix("1920x1080@60")
                self.assertTrue(ok)
                self.assertIn("HANDSHAKE", msg)

                # Verificar contenido en cmdline.txt
                with open(cmd_path, "r", encoding="utf-8") as f:
                    cmd_res = f.read()
                self.assertIn("video=HDMI-A-1:1920x1080@60D", cmd_res)
                self.assertIn("video=HDMI-A-2:1920x1080@60D", cmd_res)

                # Verificar contenido en config.txt
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg_res = f.read()
                self.assertIn("hdmi_force_hotplug=1", cfg_res)
                self.assertIn("hdmi_drive=2", cfg_res)
                self.assertIn("config_hdmi_boost=7", cfg_res)

    def test_phase_cut_protection_call(self):
        ok, msg = enable_phase_cut_protection()
        self.assertTrue(ok)
        self.assertIsInstance(msg, str)

        ok_dis, msg_dis = disable_phase_cut_protection()
        self.assertIsInstance(ok_dis, bool)
        self.assertIsInstance(msg_dis, str)

    def test_hdmi_watchdog_lifecycle(self):
        watchdog = HDMIWatchdog(check_interval=0.2)
        watchdog.start()
        if sys.platform.startswith("linux"):
            self.assertIsNotNone(watchdog._thread)
            self.assertTrue(watchdog._thread.is_alive())
        else:
            self.assertIsNone(watchdog._thread)
        watchdog.stop()
        self.assertIsNone(watchdog._thread)


if __name__ == "__main__":
    unittest.main()
