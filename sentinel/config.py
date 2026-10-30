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

    # Outside Railway (Botkeep, local Docker, VPS), use an explicit path
    # when provided; otherwise create the SQLite file in the project folder.
    return Path(override) if override else DEFAULT_DATABASE_PATH


@dataclass(frozen=True)
class GuildSettings:
    antispam: bool = False
    links: bool = False
    raid: bool = False
    log_channel_id: int | None = None
    language: str = "en"
    shortcut_channel_id: int | None = None
    shortcuts_enabled: bool = True


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
        # Non-destructive migrations for existing SQLite installations.
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(guild_settings)")}
        if "language" not in columns:
            self.connection.execute("ALTER TABLE guild_settings ADD COLUMN language TEXT NOT NULL DEFAULT 'en'")
        if "shortcut_channel_id" not in columns:
            self.connection.execute("ALTER TABLE guild_settings ADD COLUMN shortcut_channel_id INTEGER")
        if "shortcuts_enabled" not in columns:
            self.connection.execute("ALTER TABLE guild_settings ADD COLUMN shortcuts_enabled INTEGER NOT NULL DEFAULT 1")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS guild_shortcuts (
            guild_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            action TEXT NOT NULL,
            PRIMARY KEY (guild_id, word)
        )""")
        self.connection.commit()
        self.cache: dict[int, GuildSettings] = {}
        for guild_id, antispam, links, raid, log_channel_id, language, shortcut_channel_id, shortcuts_enabled in self.connection.execute(
            "SELECT guild_id, antispam, links, raid, log_channel_id, language, shortcut_channel_id, shortcuts_enabled FROM guild_settings"
        ):
            self.cache[guild_id] = GuildSettings(
                bool(antispam), bool(links), bool(raid), log_channel_id,
                language if language in ("en", "ar") else "en", shortcut_channel_id,
                bool(shortcuts_enabled)
            )

    def get(self, guild_id: int) -> GuildSettings:
        return self.cache.get(guild_id, GuildSettings())

    def update(self, guild_id: int, **changes) -> GuildSettings:
        before = self.get(guild_id)
        fields = {"antispam", "links", "raid", "log_channel_id", "language", "shortcut_channel_id", "shortcuts_enabled"}
        if not changes.keys() <= fields:
            raise ValueError("Invalid settings field")
        if "language" in changes and changes["language"] not in ("en", "ar"):
            raise ValueError("Language must be 'en' or 'ar'")
        data = {name: getattr(before, name) for name in fields}
        data.update(changes)
        updated = GuildSettings(**data)
        self.connection.execute(
            """INSERT INTO guild_settings
               (guild_id, antispam, links, raid, log_channel_id, language, shortcut_channel_id, shortcuts_enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                   antispam=excluded.antispam,
                   links=excluded.links,
                   raid=excluded.raid,
                   log_channel_id=excluded.log_channel_id,
                   language=excluded.language,
                   shortcut_channel_id=excluded.shortcut_channel_id,
                   shortcuts_enabled=excluded.shortcuts_enabled""",
            (guild_id, int(updated.antispam), int(updated.links),
             int(updated.raid), updated.log_channel_id, updated.language,
             updated.shortcut_channel_id, int(updated.shortcuts_enabled)),
        )
        self.connection.commit()
        self.cache[guild_id] = updated
        return updated

    def shortcuts_for(self, guild_id: int) -> dict[str, str]:
        return dict(self.connection.execute(
            "SELECT word, action FROM guild_shortcuts WHERE guild_id = ? ORDER BY word",
            (guild_id,),
        ))

    def set_shortcut(self, guild_id: int, word: str, action: str) -> None:
        self.connection.execute(
            """INSERT INTO guild_shortcuts (guild_id, word, action) VALUES (?, ?, ?)
               ON CONFLICT(guild_id, word) DO UPDATE SET action=excluded.action""",
            (guild_id, word, action),
        )
        self.connection.commit()

    def remove_shortcut(self, guild_id: int, word: str) -> bool:
        cursor = self.connection.execute(
            "DELETE FROM guild_shortcuts WHERE guild_id=? AND word=?",
            (guild_id, word),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def close(self):
        self.connection.close()
