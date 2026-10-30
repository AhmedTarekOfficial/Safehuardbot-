"""SQLite-backed, explicit opt-in announcements and campaign reports."""
from __future__ import annotations

from datetime import datetime, timezone
import sqlite3


class BroadcastStore:
    def __init__(self, connection: sqlite3.Connection):
        self.db = connection
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS broadcast_subscribers (
                 guild_id INTEGER NOT NULL,
                 user_id INTEGER NOT NULL,
                 joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                 PRIMARY KEY (guild_id, user_id)
               )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS broadcast_runs (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 guild_id INTEGER NOT NULL,
                 staff_id INTEGER NOT NULL,
                 status TEXT NOT NULL,
                 preview TEXT NOT NULL,
                 recipients INTEGER NOT NULL,
                 sent INTEGER NOT NULL DEFAULT 0,
                 blocked INTEGER NOT NULL DEFAULT 0,
                 failed INTEGER NOT NULL DEFAULT 0,
                 skipped INTEGER NOT NULL DEFAULT 0,
                 started_at TEXT NOT NULL,
                 finished_at TEXT
               )"""
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_broadcast_runs_guild ON broadcast_runs(guild_id, id)"
        )
        # Do not retry interrupted campaigns automatically: it risks duplicate DMs.
        self.db.execute(
            "UPDATE broadcast_runs SET status='interrupted', finished_at=? WHERE status='running'",
            (datetime.now(timezone.utc).isoformat(),),
        )
        self.db.commit()

    def subscribe(self, guild_id: int, user_id: int) -> bool:
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO broadcast_subscribers (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id),
        )
        self.db.commit()
        return cursor.rowcount == 1

    def unsubscribe(self, guild_id: int, user_id: int) -> bool:
        cursor = self.db.execute(
            "DELETE FROM broadcast_subscribers WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        self.db.commit()
        return cursor.rowcount > 0

    def subscribed(self, guild_id: int, user_id: int) -> bool:
        return self.db.execute(
            "SELECT 1 FROM broadcast_subscribers WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        ).fetchone() is not None

    def count(self, guild_id: int) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM broadcast_subscribers WHERE guild_id=?",
            (guild_id,),
        ).fetchone()[0]

    def subscribers(self, guild_id: int) -> list[int]:
        return [
            row[0]
            for row in self.db.execute(
                "SELECT user_id FROM broadcast_subscribers WHERE guild_id=? ORDER BY joined_at, user_id",
                (guild_id,),
            )
        ]

    def begin(self, guild_id: int, staff_id: int, preview: str, recipients: int) -> int:
        cursor = self.db.execute(
            """INSERT INTO broadcast_runs
                (guild_id, staff_id, status, preview, recipients, started_at)
               VALUES (?, ?, 'running', ?, ?, ?)""",
            (guild_id, staff_id, preview[:250], recipients, datetime.now(timezone.utc).isoformat()),
        )
        self.db.commit()
        return cursor.lastrowid

    def progress(self, run_id: int, *, sent: int, blocked: int, failed: int, skipped: int) -> None:
        self.db.execute(
            """UPDATE broadcast_runs SET sent=?, blocked=?, failed=?, skipped=?
               WHERE id=? AND status='running'""",
            (sent, blocked, failed, skipped, run_id),
        )
        self.db.commit()

    def finish(self, run_id: int, *, status: str, sent: int, blocked: int, failed: int, skipped: int) -> None:
        if status not in ("completed", "cancelled", "interrupted"):
            raise ValueError("Invalid broadcast status")
        self.db.execute(
            """UPDATE broadcast_runs
               SET status=?, sent=?, blocked=?, failed=?, skipped=?, finished_at=?
               WHERE id=?""",
            (status, sent, blocked, failed, skipped, datetime.now(timezone.utc).isoformat(), run_id),
        )
        self.db.commit()

    def latest(self, guild_id: int):
        row = self.db.execute(
            """SELECT id, guild_id, staff_id, status, preview, recipients,
                      sent, blocked, failed, skipped, started_at, finished_at
               FROM broadcast_runs WHERE guild_id=? ORDER BY id DESC LIMIT 1""",
            (guild_id,),
        ).fetchone()
        if row is None:
            return None
        columns = (
            "id", "guild_id", "staff_id", "status", "preview", "recipients",
            "sent", "blocked", "failed", "skipped", "started_at", "finished_at",
        )
        return dict(zip(columns, row))
