"""Guard: link spam helpers, approved-bot allowlist, and foreign-bot message handling."""
import tempfile
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from sentinel.config import SettingsStore
from sentinel.guard import (
    Guard,
    contains_invite,
    contains_url,
    is_dangerous_bot,
    link_spam_reason,
    message_scan_text,
)


class GuardHelperTests(unittest.TestCase):
    def test_invite_and_url_detection(self):
        self.assertTrue(contains_invite("join https://discord.gg/abcd now"))
        self.assertTrue(contains_url("see https://evil.example/spam"))
        self.assertFalse(contains_invite("https://example.com/docs"))
        self.assertFalse(contains_url("hello without links"))

    def test_link_spam_threshold(self):
        events = deque((100.0 + i, "link") for i in range(3))
        self.assertIsNotNone(link_spam_reason(events, 105))
        self.assertIsNone(link_spam_reason(deque(list(events)[:2]), 105))

    def test_message_scan_includes_embed_urls(self):
        message = Mock(spec=discord.Message)
        message.content = ""
        embed = Mock()
        embed.title = None
        embed.description = "click https://discord.gg/spam"
        embed.url = None
        embed.author = None
        embed.footer = None
        embed.fields = []
        message.embeds = [embed]
        message.attachments = []
        self.assertTrue(contains_invite(message_scan_text(message)))

    def test_dangerous_bot_detection(self):
        member = Mock(spec=discord.Member)
        member.guild_permissions = SimpleNamespace(
            administrator=True, ban_members=False, kick_members=False,
            manage_guild=False, manage_roles=False, manage_channels=False,
            manage_webhooks=False, mention_everyone=False, moderate_members=False,
        )
        self.assertTrue(is_dangerous_bot(member))
        member.guild_permissions.administrator = False
        self.assertFalse(is_dangerous_bot(member))


class ApprovedBotStoreTests(unittest.TestCase):
    def test_approve_revoke_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SettingsStore(Path(tmp) / "guard.sqlite3")
            self.assertFalse(store.is_bot_approved(1, 99))
            store.approve_bot(1, 99, approved_by=5)
            self.assertTrue(store.is_bot_approved(1, 99))
            self.assertEqual(store.approved_bots(1), [99])
            self.assertTrue(store.revoke_bot(1, 99))
            self.assertFalse(store.is_bot_approved(1, 99))
            store.close()

    def test_bot_guard_setting_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.sqlite3"
            first = SettingsStore(path)
            first.update(10, bot_guard=True, antispam=True, links=True)
            first.close()
            second = SettingsStore(path)
            self.assertTrue(second.get(10).bot_guard)
            self.assertTrue(second.get(10).antispam)
            self.assertTrue(second.get(10).links)
            second.close()


class GuardDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SettingsStore(Path(self.tmp.name) / "live.sqlite3")
        self.bot = SimpleNamespace(store=self.store, user=SimpleNamespace(id=1))
        self.cog = Guard(self.bot)
        self.store.update(7, antispam=True, links=True, bot_guard=True)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _message(self, *, content="https://discord.gg/x", is_bot=False):
        author = Mock(spec=discord.Member)
        author.id = 50
        author.bot = is_bot
        author.guild_permissions = SimpleNamespace(administrator=False)
        author.top_role = Mock()
        guild = Mock()
        guild.id = 7
        guild.owner_id = 9
        guild.me = Mock(spec=discord.Member)
        guild.me.id = 1
        guild.me.guild_permissions = SimpleNamespace(
            kick_members=True, moderate_members=True, manage_messages=True, manage_roles=True,
        )
        guild.me.top_role = Mock()
        guild.me.top_role.__gt__ = Mock(return_value=True)
        guild.me.top_role.__lt__ = Mock(return_value=False)
        channel = Mock()
        channel.mention = "#chat"
        channel.permissions_for.side_effect = lambda who: SimpleNamespace(
            manage_messages=False if who is author else True,
            send_messages=True, view_channel=True,
        )
        message = Mock(spec=discord.Message)
        message.guild = guild
        message.author = author
        message.channel = channel
        message.content = content
        message.embeds = []
        message.attachments = []
        message.mentions = []
        message.delete = AsyncMock()
        author.kick = AsyncMock()
        author.timeout = AsyncMock()
        return message

    async def test_invite_from_foreign_bot_is_deleted(self):
        msg = self._message(is_bot=True)
        with patch("sentinel.guard.log_action", new_callable=AsyncMock):
            await self.cog.on_message(msg)
        msg.delete.assert_awaited()

    async def test_unverified_bot_join_is_kicked(self):
        member = Mock(spec=discord.Member)
        member.id = 88
        member.bot = True
        member.guild = Mock()
        member.guild.id = 7
        member.guild.me = Mock()
        member.guild.me.guild_permissions = SimpleNamespace(kick_members=True, manage_roles=True)
        member.guild.me.top_role = Mock()
        member.guild.me.top_role.__gt__ = Mock(return_value=True)
        member.guild_permissions = SimpleNamespace(
            administrator=True, ban_members=True, kick_members=True,
            manage_guild=True, manage_roles=True, manage_channels=True,
            manage_webhooks=False, mention_everyone=False, moderate_members=False,
        )
        member.top_role = Mock()
        member.kick = AsyncMock()
        member.guild.get_channel.return_value = None
        with patch("sentinel.guard.log_action", new_callable=AsyncMock) as logged:
            await self.cog.on_member_join(member)
        member.kick.assert_awaited_once()
        logged.assert_awaited()

    async def test_approved_bot_join_is_not_kicked(self):
        self.store.approve_bot(7, 88, approved_by=1)
        member = Mock(spec=discord.Member)
        member.id = 88
        member.bot = True
        member.guild = Mock()
        member.guild.id = 7
        member.kick = AsyncMock()
        await self.cog.on_member_join(member)
        member.kick.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
