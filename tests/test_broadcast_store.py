"""Unit tests for consent-only message campaigns and persistent SQLite reports."""
import sqlite3
import unittest

from sentinel.broadcast_store import BroadcastStore


class BroadcastStoreTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.store = BroadcastStore(self.db)

    def tearDown(self):
        self.db.close()

    def test_subscription_requires_opt_in_and_is_scoped_to_guild(self):
        self.assertEqual(self.store.subscribers(1), [])
        self.assertFalse(self.store.subscribed(1, 20))
        self.assertTrue(self.store.subscribe(1, 20))
        self.assertFalse(self.store.subscribe(1, 20))
        self.assertTrue(self.store.subscribed(1, 20))
        self.assertFalse(self.store.subscribed(2, 20))
        self.assertEqual(self.store.count(1), 1)
        self.assertEqual(self.store.count(2), 0)
        self.assertTrue(self.store.unsubscribe(1, 20))
        self.assertFalse(self.store.unsubscribe(1, 20))
        self.assertEqual(self.store.subscribers(1), [])

    def test_campaign_report_is_durable(self):
        for i in (20, 30, 40):
            self.store.subscribe(42, i)
        run_id = self.store.begin(42, 70, "Announcement", recipients=3)
        self.store.progress(run_id, sent=1, blocked=1, failed=0, skipped=0)
        running = self.store.latest(42)
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["recipients"], 3)
        self.store.finish(run_id, status="completed", sent=1, blocked=1, failed=0, skipped=1)
        result = self.store.latest(42)
        self.assertEqual((result["sent"], result["blocked"], result["skipped"]), (1, 1, 1))
        self.assertEqual(result["status"], "completed")
        self.assertIsNotNone(result["finished_at"])
        self.assertIsNone(self.store.latest(99))

    def test_restart_marks_running_jobs_as_interrupted_without_resending(self):
        run_id = self.store.begin(1, 70, "News", recipients=2)
        self.store.progress(run_id, sent=1, blocked=0, failed=0, skipped=0)
        again = BroadcastStore(self.db)
        run = again.latest(1)
        self.assertEqual(run["status"], "interrupted")
        self.assertEqual(run["sent"], 1)
        self.assertEqual(again.subscribers(1), [])

    def test_finish_rejects_invented_status(self):
        run_id = self.store.begin(2, 30, "Info", recipients=0)
        with self.assertRaises(ValueError):
            self.store.finish(run_id, status="unknown", sent=0, blocked=0, failed=0, skipped=0)


if __name__ == "__main__":
    unittest.main()
