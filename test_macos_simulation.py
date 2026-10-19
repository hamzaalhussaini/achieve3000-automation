"""
Test suite to validate macOS path resolution, bundle simulation,
error logging, and UI initialization without requiring a physical Mac.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import launcher


class TestMacOSCompatibility(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_darwin_user_data_dir_resolution(self):
        """Verify that on macOS (darwin), user settings and crash logs resolve to Library/Application Support."""
        with patch("launcher.IS_MAC", True), patch("launcher.IS_WIN", False), patch.object(Path, "home", return_value=self.test_root):
            mac_data_dir = launcher.get_user_data_dir()
            expected = self.test_root / "Library" / "Application Support" / "Achieve3000"
            self.assertEqual(mac_data_dir, expected)
            self.assertTrue(mac_data_dir.exists())

    def test_asset_path_meipass_resolution(self):
        """Verify that bundled assets unpack and resolve dynamically via sys._MEIPASS."""
        fake_meipass = self.test_root / "fake_meipass"
        fake_meipass.mkdir()
        fake_asset = fake_meipass / "test_asset.txt"
        fake_asset.write_text("ok")

        with patch.object(sys, "_MEIPASS", str(fake_meipass), create=True):
            resolved = launcher.get_asset_path("test_asset.txt")
            self.assertEqual(resolved, str(fake_asset))

    def test_macos_bundle_resources_resolution(self):
        """Simulate a macOS .app bundle directory structure (Contents/MacOS and Contents/Resources)."""
        app_bundle = self.test_root / "Achieve3000Launcher.app" / "Contents"
        macos_dir = app_bundle / "MacOS"
        resources_dir = app_bundle / "Resources"
        macos_dir.mkdir(parents=True)
        resources_dir.mkdir(parents=True)

        fake_browser_dir = resources_dir / "playwright-browsers"
        fake_browser_dir.mkdir()
        (fake_browser_dir / "marker.txt").write_text("browser-ok")

        fake_exe = macos_dir / "Achieve3000Launcher"
        fake_exe.touch()

        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(fake_exe)):
            resolved = launcher.get_asset_path("playwright-browsers")
            self.assertEqual(Path(resolved).resolve(), fake_browser_dir.resolve())

    def test_read_only_filesystem_settings_safety(self):
        """Verify that attempting to write settings on a read-only filesystem does not crash or raise modal errors."""
        read_only_dir = self.test_root / "read_only_location"
        read_only_dir.mkdir()
        target_settings = read_only_dir / "settings.json"

        # Create a mock launcher instance with the required Tk StringVar mocks
        mock_launcher = MagicMock()
        mock_launcher.api_key.get.return_value = "fake_key"
        mock_launcher.username.get.return_value = "fake_user"
        mock_launcher.password.get.return_value = "fake_pass"
        mock_launcher.headless.get.return_value = True

        with patch("launcher.SETTINGS_FILE", target_settings):
            with patch.object(Path, "write_text", side_effect=OSError("Read-only file system")):
                try:
                    launcher.AutomationLauncher._save_settings(mock_launcher)
                except Exception as exc:
                    self.fail(f"_save_settings raised an unexpected exception: {exc}")

    def test_crash_log_recording(self):
        """Verify that uncaught exceptions write stack traces to desktop_crash_log.txt."""
        test_crash_log = self.test_root / "desktop_crash_log.txt"
        with patch("launcher.CRASH_LOG_FILE", test_crash_log):
            try:
                raise ValueError("Simulated macOS Cocoa test exception")
            except ValueError:
                launcher.log_crash(*sys.exc_info())

            self.assertTrue(test_crash_log.exists())
            content = test_crash_log.read_text(encoding="utf-8")
            self.assertIn("Simulated macOS Cocoa test exception", content)
            self.assertIn("CRASH OCCURRED", content)

    def test_gui_instantiation_and_layout(self):
        """Verify that the GUI window initializes and renders widgets without errors."""
        try:
            app = launcher.AutomationLauncher()
            self.assertIsNotNone(app.start_button)
            self.assertIsNotNone(app.stop_button)
            self.assertIsNotNone(app.output)
            app.update_idletasks()
            app.destroy()
        except Exception as exc:
            if "no display name" in str(exc).lower() or "display" in str(exc).lower():
                self.skipTest(f"Skipping GUI test in headless environment: {exc}")
            else:
                self.fail(f"AutomationLauncher initialization failed: {exc}")


if __name__ == "__main__":
    unittest.main()
