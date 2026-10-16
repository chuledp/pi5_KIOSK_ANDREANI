import os
import tempfile
import unittest
from core.profile_manager import ProfileManager, create_default_profile
from core.sync_runner import SyncDaemon

class TestSyncRunner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_file = os.path.join(self.temp_dir.name, "config.json")
        self.pm = ProfileManager(config_path=self.config_file)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_daemon_initialization(self):
        p = self.pm.get_active_profile()
        self.assertIsNotNone(p)
        self.assertEqual(p["network_role"], "follower")
        self.assertEqual(p["osc_port"], 9000)

        daemon = SyncDaemon(self.pm)
        self.assertFalse(daemon.is_running)

    def test_osc_custom_mappings(self):
        p = self.pm.get_active_profile()
        p["osc_mappings"] = {
            "/play": "/resolume/layer1/play",
            "/cue": "/td/cue"
        }
        self.pm.update_profile(p["id"], p)
        updated = self.pm.get_profile(p["id"])
        self.assertEqual(updated["osc_mappings"]["/play"], "/resolume/layer1/play")

if __name__ == "__main__":
    unittest.main()
