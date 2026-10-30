import tempfile
import unittest
from collections import deque
from pathlib import Path

from sentinel.config import SettingsStore
from sentinel.guard import spam_reason, INVITE_PATTERN


class TestGuardAndStore(unittest.TestCase):
    def test_spam_rate(self):
        events = deque((100.0 + i * 0.5, f"message {i}") for i in range(7))
        self.assertIsNotNone(spam_reason(events, 103, "message 6"))
        self.assertIsNone(spam_reason(deque(list(events)[:3]), 103, "different"))

    def test_repeat(self):
        events = deque((100.0 + i, "same") for i in range(4))
        self.assertIn("repeated", spam_reason(events, 103, "same"))

    def test_invite_regex(self):
        self.assertTrue(INVITE_PATTERN.search("https://discord.gg/abcd"))
        self.assertFalse(INVITE_PATTERN.search("https://example.com/docs"))

    def test_config_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.sqlite3"
            first = SettingsStore(path)
            self.assertFalse(first.get(123).antispam)
            first.update(123, antispam=True, raid=True, log_channel_id=987)
            first.close()
            second = SettingsStore(path)
            self.assertTrue(second.get(123).antispam)
            self.assertTrue(second.get(123).raid)
            self.assertEqual(second.get(123).log_channel_id, 987)
            second.close()


if __name__ == "__main__":
    unittest.main()
