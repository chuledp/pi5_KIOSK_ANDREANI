import unittest
import os
import sys
import subprocess

FLEET_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "kiosk-fleet-manager"))


class TestKioskFleetManagerSuite(unittest.TestCase):
    def test_run_fleet_manager_test_suite(self):
        """Ejecuta los tests del fork kiosk-fleet-manager en su propio entorno aislado."""
        cmd = [sys.executable, "-W", "error::ResourceWarning", "-m", "unittest", "discover", "tests"]
        res = subprocess.run(cmd, cwd=FLEET_DIR, capture_output=True, text=True)
        if res.returncode != 0:
            print("Fleet Manager Test Output:\n", res.stdout, res.stderr)
        self.assertEqual(res.returncode, 0, f"Tests in kiosk-fleet-manager failed:\n{res.stderr}")


if __name__ == "__main__":
    unittest.main()
