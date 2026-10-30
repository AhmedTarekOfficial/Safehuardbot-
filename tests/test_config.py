"""Regression tests for SQLite persistence and Railway deployment settings."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sentinel.config import SettingsStore, database_path


class SettingsStoreTests(unittest.TestCase):
    def test_creates_missing_parents_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "nested" / "settings.sqlite3"
            first = SettingsStore(path)
            first.update(7, antispam=True, links=True, raid=True, log_channel_id=1234)
            first.close()
            self.assertTrue(path.is_file())
            second = SettingsStore(path)
            settings = second.get(7)
            self.assertTrue(settings.antispam)
            self.assertTrue(settings.links)
            self.assertTrue(settings.raid)
            self.assertEqual(settings.log_channel_id, 1234)
            second.close()

    def test_reads_env_on_initialization(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "later" / "from-env.db"
            with patch.dict(os.environ, {"SENTINEL_DB_PATH": str(path)}, clear=True):
                self.assertEqual(database_path(), path)
                db = SettingsStore()
                db.close()
            self.assertTrue(path.is_file())

    def test_default_path_without_railway_or_override(self):
        with patch.dict(os.environ, {}, clear=True):
            resolved = database_path()
            self.assertIsInstance(resolved, Path)
            self.assertEqual(resolved.name, "sentinel.sqlite3")
            self.assertTrue(resolved.is_absolute())

    def test_botkeep_startup_creates_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "data" / "botkeep.sqlite3"
            with patch.dict(os.environ, {
                "P_SERVER_UUID": "ptero",
                "SENTINEL_DB_PATH": str(target),
            }, clear=True):
                self.assertEqual(database_path(), target)
                store = SettingsStore()
                store.update(42, antispam=True)
                store.close()
            self.assertTrue(target.is_file())
            reopened = SettingsStore(target)
            self.assertTrue(reopened.get(42).antispam)
            reopened.close()

    def test_empty_path_falls_back_outside_railway(self):
        with patch.dict(os.environ, {"SENTINEL_DB_PATH": "  "}, clear=True):
            self.assertEqual(database_path().name, "sentinel.sqlite3")

    def test_railway_requires_volume(self):
        with patch.dict(os.environ, {"RAILWAY_SERVICE_ID": "svc", "RAILWAY_VOLUME_MOUNT_PATH": ""}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "persistent Volume"):
                database_path()

    def test_railway_rejects_ephemeral_path_and_defaults_to_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            mount = Path(tmp) / "volume"
            with patch.dict(os.environ, {"RAILWAY_SERVICE_ID": "svc", "RAILWAY_VOLUME_MOUNT_PATH": str(mount)}, clear=True):
                with patch.dict(os.environ, {"SENTINEL_DB_PATH": str(Path(tmp) / "wrong.db")}):
                    with self.assertRaisesRegex(RuntimeError, "inside the Railway Volume"):
                        database_path()
                self.assertEqual(database_path(), mount / "sentinel.sqlite3")
                with patch.dict(os.environ, {"SENTINEL_DB_PATH": str(mount / "my.db")}):
                    self.assertEqual(database_path(), mount / "my.db")


if __name__ == "__main__":
    unittest.main()
