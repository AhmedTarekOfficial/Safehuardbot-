from dataclasses import dataclass
from pathlib import Path
import os
import sqlite3

DEFAULT_DATABASE_PATH = Path(__file__).resolve().parent.parent / "sentinel.sqlite3"


def database_path() -> Path:
    """Resolve settings at initialization so dotenv and Railway variables work."""
    override = os.getenv("SENTINEL_DB_PATH", "").strip()
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_SERVICE_ID"):
        mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
        if not mount:
            raise RuntimeError(
                "Railway requires a persistent Volume to keep bot settings. "
                "Mount a Volume at /app/data and set SENTINEL_DB_PATH=/app/data/sentinel.sqlite3."
            )
        # On Railway, refuse a database path outside its persistent Volume.
        target = Path(override) if override else Path(mount) / "sentinel.sqlite3"
        mount_path = Path(mount).resolve()
        if not target.is_absolute() or not target.resolve().is_relative_to(mount_path) or target.resolve() == mount_path:
            raise RuntimeError("SENTINEL_DB_PATH must point to a file inside the Railway Volume mount.")
        return target


@dataclass(frozen=True)
class GuildSettings:
    antispam: bool = False
    links: bool = False
    raid: bool = False
    log_channel_id: int | None = None


class SettingsStore:
    def __init__(self, path: Path | str | None = None):
        db_path = Path(path) if path is not None else database_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(db_path)
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                antispam INTEGER NOT NULL DEFAULT 0,
                links INTEGER NOT NULL DEFAULT 0,
                raid INTEGER NOT NULL DEFAULT 0,
                log_channel_id INTEGER
            )"""
        )
        self.connection.commit()
        self.cache: dict[int, GuildSettings] = {}
        for guild_id, antispam, links, raid, log_channel_id in self.connection.execute(
            "SELECT guild_id, antispam, links, raid, log_channel_id FROM guild_settings"
        ):
            self.cache[guild_id] = GuildSettings(
                bool(antispam), bool(links), bool(raid), log_channel_id
            )

    def get(self, guild_id: int) -> GuildSettings:
        return self.cache.get(guild_id, GuildSettings())

    def update(self, guild_id: int, **changes) -> GuildSettings:
        before = self.get(guild_id)
        fields = {"antispam", "links", "raid", "log_channel_id"}
        if not changes.keys() <= fields:
            raise ValueError("Invalid settings field")
        data = {name: getattr(before, name) for name in fields}
        data.update(changes)
        updated = GuildSettings(**data)
        self.connection.execute(
            """INSERT INTO guild_settings
               (guild_id, antispam, links, raid, log_channel_id)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                   antispam=excluded.antispam,
                   links=excluded.links,
                   raid=excluded.raid,
                   log_channel_id=excluded.log_channel_id""",
            (guild_id, int(updated.antispam), int(updated.links),
             int(updated.raid), updated.log_channel_id),
        )
        self.connection.commit()
        self.cache[guild_id] = updated
        return updated

    def close(self):
        self.connection.close()
