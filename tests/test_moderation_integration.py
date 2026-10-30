"""Mocked Discord API checks for acknowledgement and command execution."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from sentinel.moderation import Moderation, Roles


class CommandAcknowledgementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = SimpleNamespace(store=Mock())
        self.interaction = Mock()
        self.interaction.user = Mock()
        self.interaction.user.id = 100
        self.interaction.guild = Mock()
        self.interaction.response.defer = AsyncMock()
        self.interaction.response.is_done.return_value = True
        self.interaction.followup.send = AsyncMock()

    async def test_kick_acks_before_api_call(self):
        calls = []

        async def defer(**kwargs):
            calls.append("defer")

        async def kick(**kwargs):
            calls.append("kick")

        self.interaction.response.defer.side_effect = defer
        member = Mock(spec=discord.Member)
        member.kick = AsyncMock(side_effect=kick)
        member.id = 200
        cog = Moderation(self.bot)
        cog.check_member = AsyncMock(return_value=True)
        with patch("sentinel.moderation.log_action", new_callable=AsyncMock):
            await Moderation.kick.callback(cog, self.interaction, member, "test")
        self.assertEqual(calls, ["defer", "kick"])
        self.interaction.followup.send.assert_awaited_once()

    async def test_invalid_target_still_acks(self):
        cog = Moderation(self.bot)
        cog.check_member = AsyncMock(return_value=False)
        member = Mock(spec=discord.Member)
        await Moderation.kick.callback(cog, self.interaction, member)
        self.interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        member.kick.assert_not_called()

    async def test_role_add_acks_before_mutation(self):
        calls = []

        async def defer(**kwargs):
            calls.append("defer")

        async def add_roles(*args, **kwargs):
            calls.append("add_roles")

        self.interaction.response.defer.side_effect = defer
        member = Mock(spec=discord.Member)
        member.roles = []
        member.add_roles = AsyncMock(side_effect=add_roles)
        member.id = 200
        role = Mock(spec=discord.Role)
        role.name = "Helpers"
        role.id = 300
        cog = Roles(self.bot)
        cog.validate = AsyncMock(return_value=True)
        with patch("sentinel.moderation.log_action", new_callable=AsyncMock):
            await Roles.add.callback(cog, self.interaction, member, role)
        self.assertEqual(calls, ["defer", "add_roles"])
        self.interaction.followup.send.assert_awaited_once()

    async def test_purge_acks_then_follows_up(self):
        channel = Mock(spec=discord.TextChannel)
        channel.purge = AsyncMock(return_value=[Mock(), Mock()])
        channel.mention = "#general"
        self.interaction.channel = channel
        cog = Moderation(self.bot)
        with patch("sentinel.moderation.log_action", new_callable=AsyncMock):
            await Moderation.purge.callback(cog, self.interaction, 2)
        self.interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        channel.purge.assert_awaited_once_with(limit=2)
        self.interaction.followup.send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
