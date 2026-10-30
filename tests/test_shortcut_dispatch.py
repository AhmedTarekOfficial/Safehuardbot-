"""Mock gateway events: verify global default, optional channel restriction and voice mute."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from sentinel.config import SettingsStore
from sentinel.shortcuts import Shortcuts


class ShortcutDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SettingsStore(Path(self.tmp.name) / "shortcuts.sqlite3")
        self.bot = SimpleNamespace(
            store=self.store,
            user=SimpleNamespace(id=999),
            intents=SimpleNamespace(message_content=True),
        )
        self.cog = Shortcuts(self.bot)
        self.store.set_shortcut(1, "درع", "antispam_on")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def message(self, content="درع", channel_id=10):
        author = Mock(spec=discord.Member)
        author.id = 123
        author.bot = False
        author.display_name = "Moderator"
        author.guild_permissions = SimpleNamespace(manage_guild=True, mute_members=False)
        bot_member = Mock(spec=discord.Member)
        bot_member.id = 999
        bot_member.guild_permissions = SimpleNamespace(manage_guild=True, mute_members=False)
        guild = Mock()
        guild.id = 1
        guild.me = bot_member
        channel = Mock()
        channel.id = channel_id
        channel.send = AsyncMock()
        channel.permissions_for.return_value = SimpleNamespace(
            view_channel=True, send_messages=True, read_message_history=True,
        )
        msg = Mock(spec=discord.Message)
        msg.guild = guild
        msg.channel = channel
        msg.author = author
        msg.content = content
        msg.mentions = []
        msg.reference = None
        msg.reply = AsyncMock()
        return msg

    async def test_global_default_dispatches_from_any_channel(self):
        for channel_id in (10, 20):
            self.store.update(1, antispam=False)
            self.cog.recent.clear()
            msg = self.message(channel_id=channel_id)
            with patch("sentinel.shortcuts.log_action", new_callable=AsyncMock):
                await self.cog.on_message(msg)
            self.assertTrue(self.store.get(1).antispam)
            msg.channel.send.assert_awaited_once()

    async def test_optional_channel_restriction(self):
        self.store.update(1, shortcut_channel_id=10)
        outside = self.message(channel_id=20)
        await self.cog.on_message(outside)
        self.assertFalse(self.store.get(1).antispam)
        outside.channel.send.assert_not_awaited()
        allowed = self.message(channel_id=10)
        with patch("sentinel.shortcuts.log_action", new_callable=AsyncMock):
            await self.cog.on_message(allowed)
        self.assertTrue(self.store.get(1).antispam)

    async def test_disable_shortcuts_without_deleting_mappings(self):
        self.store.update(1, shortcuts_enabled=False)
        msg = self.message()
        await self.cog.on_message(msg)
        self.assertFalse(self.store.get(1).antispam)
        self.assertEqual(self.store.shortcuts_for(1)["درع"], "antispam_on")
        msg.channel.send.assert_not_awaited()

    async def test_voice_mute_checks_target_voice_channel(self):
        self.store.set_shortcut(1, "سك", "vmute")
        msg = self.message(content="سك <@!200>", channel_id=20)
        voice_channel = Mock()
        voice_channel.permissions_for.return_value = SimpleNamespace(mute_members=True)
        member = Mock(spec=discord.Member)
        member.id = 200
        member.voice = SimpleNamespace(channel=voice_channel)
        member.edit = AsyncMock()
        self.cog.target_for = AsyncMock(return_value=member)
        with patch("sentinel.shortcuts.target_error", return_value=None), \\
             patch("sentinel.shortcuts.log_action", new_callable=AsyncMock):
            await self.cog.on_message(msg)
        member.edit.assert_awaited_once()
        self.assertTrue(member.edit.await_args.kwargs["mute"])


if __name__ == "__main__":
    unittest.main()
