import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from roccatmouse.config import AppConfig, config_path, load_config, save_config, telemetry_path


class ConfigTests(unittest.TestCase):
    def test_resolves_roaming_config_and_local_telemetry_paths(self):
        env = {"APPDATA": r"C:\Roaming", "LOCALAPPDATA": r"C:\Local"}
        self.assertEqual(config_path(env), Path(r"C:\Roaming") / "RoccatMouse" / "config.json")
        self.assertEqual(
            telemetry_path(env), Path(r"C:\Local") / "RoccatMouse" / "telemetry.sqlite3"
        )

    def test_missing_config_uses_safe_defaults(self):
        with TemporaryDirectory() as directory:
            self.assertEqual(load_config(Path(directory) / "missing.json"), AppConfig())

    def test_save_and_load_round_trip_via_atomic_replace(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            expected = AppConfig(retention_days=14, queue_size=500, marker_context_seconds=45)
            with patch("roccatmouse.config.os.replace", wraps=os.replace) as replace:
                save_config(expected, path)
            self.assertEqual(load_config(path), expected)
            replace.assert_called_once()
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_corrupt_config_is_quarantined(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(load_config(path), AppConfig())
            self.assertFalse(path.exists())
            self.assertEqual(len(list(path.parent.glob("config.json.corrupt-*"))), 1)

    def test_unknown_keys_do_not_break_forward_compatibility(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"retention_days": 7, "future": True}), encoding="utf-8")
            self.assertEqual(load_config(path).retention_days, 7)


if __name__ == "__main__":
    unittest.main()
