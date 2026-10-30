"""Text-only mute regression tests: no Timeout, voice access intact, prior overrides restored."""
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from sentinel.text_mute import DENIED, TextMute


class TextMuteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.guild = Mock(spec=discord.Guild)
        self.guild.id = 123
        self.guild.owner_id = 99
        self.guild.icon = None

        self.bot_member = Mock(spec=discord.Member)
        self.bot_member.id = 999
        self.guild.me = self.bot_member
        self.guild.fetch_member = AsyncMock(return_value=self.bot_member)

        self.actor = Mock(spec=discord.Member)
        self.actor.id = 99
        self.actor.guild_permissions = SimpleNamespace(manage_roles=True)
        self.actor.top_role = Mock()

        self.member = Mock(spec=discord.Member)
        self.member.id = 456
        self.member.roles = []
        self.member.guild_permissions = SimpleNamespace(administrator=False)
        self.member.top_role = Mock()
        self.member.add_roles = AsyncMock()
        self.member.remove_roles = AsyncMock()
        self.member.timeout = AsyncMock()

        self.role = Mock(spec=discord.Role)
        self.role.id = 800
        self.role.name = "VanGuard • Muted"
        self.channel = Mock(spec=discord.TextChannel)
        self.channel.id = 1000
        self.channel.name = "general"
        self.channel.guild = self.guild
        self.channel.set_permissions = AsyncMock()
        self.channel.overwrites_for.side_effect = lambda target: (
            self.role_overwrite if target is self.role else self.user_overwrite
        )
        self.role_overwrite = discord.PermissionOverwrite()
        self.user_overwrite = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            send_messages_in_threads=None,
        )
        self.guild.channels = [self.channel]
        self.guild.get_channel.return_value = self.channel

        self.bot = SimpleNamespace(
            store=SimpleNamespace(connection=self.db, get=lambda _: SimpleNamespace(language="en")),
            user=SimpleNamespace(id=999),
        )
        self.bot.get_guild = Mock(return_value=self.guild)
        with patch.object(TextMute.expire_mutes, "start"):
            self.cog = TextMute(self.bot)
        self.cog.ensure_role = AsyncMock(return_value=self.role)
        self.cog.validate = AsyncMock()
        self.cog.muted_role = Mock(return_value=self.role)

    def tearDown(self):
        self.cog.cog_unload()
        self.db.close()

    async def test_text_mute_sets_role_and_explicit_denies_without_timeout(self):
        await self.cog.apply(self.guild, self.actor, self.member, minutes=5)
        self.member.add_roles.assert_awaited_once()
        self.member.timeout.assert_not_awaited()
        self.assertFalse(self.user_overwrite.send_messages)
        self.assertFalse(self.user_overwrite.send_messages_in_threads)
        self.assertFalse(self.user_overwrite.create_public_threads)
        self.assertFalse(self.user_overwrite.create_private_threads)
        # Only text flags change; voice access and original view permissions remain untouched.
        self.assertIsNone(self.user_overwrite.speak)
        self.assertIsNone(self.user_overwrite.connect)
        self.assertTrue(self.user_overwrite.view_channel)
        self.assertEqual(self.channel.set_permissions.await_count, 2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM text_mutes").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM text_mute_overwrites").fetchone()[0], 1)

    async def test_unmute_restores_overrides_and_does_not_clear_timeout(self):
        await self.cog.apply(self.guild, self.actor, self.member, minutes=5)
        self.member.roles = [self.role]
        await self.cog.remove(self.guild, self.actor, self.member)
        self.member.remove_roles.assert_awaited_once()
        self.member.timeout.assert_not_awaited()
        self.assertTrue(self.user_overwrite.send_messages)
        self.assertIsNone(self.user_overwrite.send_messages_in_threads)
        self.assertIsNone(self.user_overwrite.create_public_threads)
        self.assertIsNone(self.user_overwrite.create_private_threads)
        self.assertTrue(self.user_overwrite.view_channel)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM text_mutes").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM text_mute_overwrites").fetchone()[0], 0)

    async def test_mute_duration_saved_for_restart_and_expiry(self):
        await self.cog.apply(self.guild, self.actor, self.member, minutes=5)
        self.member.roles = [self.role]
        self.guild.get_member.return_value = self.member
        self.db.execute("UPDATE text_mutes SET expires_at = 0")
        self.db.commit()
        await TextMute.expire_mutes.coro(self.cog)
        self.member.remove_roles.assert_awaited_once()
        self.assertTrue(self.user_overwrite.send_messages)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM text_mutes").fetchone()[0], 0)

    async def test_new_voice_channel_chat_is_restricted_without_muting_microphone(self):
        await self.cog.apply(self.guild, self.actor, self.member, minutes=5)
        self.member.roles = [self.role]
        voice_channel = Mock(spec=discord.VoiceChannel)
        voice_channel.guild = self.guild
        voice_channel.id = 500
        voice_channel.name = "voice-chat"
        voice_channel.set_permissions = AsyncMock()
        role_overwrite = discord.PermissionOverwrite()
        member_overwrite = discord.PermissionOverwrite()
        voice_channel.overwrites_for.side_effect = lambda target: (
            role_overwrite if target is self.role else member_overwrite
        )
        self.guild.get_member.return_value = self.member
        await self.cog.on_guild_channel_create(voice_channel)
        self.assertFalse(member_overwrite.send_messages)
        self.assertIsNone(member_overwrite.speak)
        self.assertIsNone(member_overwrite.connect)


if __name__ == "__main__":
    unittest.main()
