import os
import tempfile
import unittest
from core.profile_manager import ProfileManager, create_default_profile
from core.autostart import AutostartManager, build_vlc_command

class TestVLCAutoPlayCore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_file = os.path.join(self.temp_dir.name, "config.json")
        self.autostart_file = os.path.join(self.temp_dir.name, "autostart.desktop")
        self.runner_file = os.path.join(self.temp_dir.name, "vlc-runner.sh")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_profile_manager_lifecycle(self):
        pm = ProfileManager(config_path=self.config_file)
        profiles = pm.get_profiles()
        self.assertEqual(len(profiles), 1)
        self.assertIsNotNone(pm.get_active_profile())

        # Add profile
        p2 = pm.add_profile("Sala 2")
        self.assertEqual(len(pm.get_profiles()), 2)
        self.assertEqual(p2["name"], "Sala 2")

        # Update profile
        pm.update_profile(p2["id"], {"file_path": "/videos/obra.mp4", "volume": 80})
        updated = pm.get_profile(p2["id"])
        self.assertEqual(updated["file_path"], "/videos/obra.mp4")
        self.assertEqual(updated["volume"], 80)

        # Set active
        pm.set_active_profile(p2["id"])
        self.assertEqual(pm.get_active_profile()["id"], p2["id"])

        # Duplicate
        dup = pm.duplicate_profile(p2["id"])
        self.assertIsNotNone(dup)
        self.assertIn("(Copia)", dup["name"])
        self.assertEqual(len(pm.get_profiles()), 3)

        # Delete
        self.assertTrue(pm.delete_profile(dup["id"]))
        self.assertEqual(len(pm.get_profiles()), 2)

    def test_vlc_command_builder(self):
        profile = create_default_profile("Test")
        profile["file_path"] = "/home/pi/Videos/loop.mp4"
        profile["fullscreen"] = True
        profile["loop"] = True
        profile["hide_osd"] = True
        profile["hide_mouse"] = True
        profile["volume"] = 75

        cmd = build_vlc_command(profile, binary="cvlc")
        self.assertIn("cvlc", cmd)
        self.assertIn("--fullscreen", cmd)
        self.assertIn("--loop", cmd)
        self.assertIn("--no-video-title-show", cmd)
        self.assertIn("--mouse-hide-timeout=0", cmd)
        self.assertIn("--gain=0.75", cmd)
        self.assertIn('"/home/pi/Videos/loop.mp4"', cmd)

    def test_autostart_manager(self):
        am = AutostartManager(
            autostart_path=self.autostart_file,
            runner_path=self.runner_file
        )
        self.assertFalse(am.is_active())

        profile = create_default_profile("Test Boot")
        profile["file_path"] = "/home/pi/exposicion.mp4"
        profile["delay_seconds"] = 8

        # Enable
        success = am.enable(profile)
        self.assertTrue(success)
        self.assertTrue(am.is_active())

        # Verify runner script content
        with open(self.runner_file, "r") as f:
            content = f.read()
            self.assertIn("sleep 8", content)
            self.assertIn("cvlc", content)
            self.assertIn("/home/pi/exposicion.mp4", content)

        # Disable
        am.disable()
        self.assertFalse(am.is_active())

if __name__ == "__main__":
    unittest.main()
