"""Mock Discord DM delivery: consent, opt-out during a campaign, and private reports."""
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from sentinel.broadcast import Broadcast


class BroadcastDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.bot = SimpleNamespace(
            store=SimpleNamespace(connection=self.db, get=lambda guild_id: SimpleNamespace(language="en")),
            fetch_user=AsyncMock(),
        )
        self.cog = Broadcast(self.bot)
        for member_id in (11, 12, 13):
            self.cog.state.subscribe(2, member_id)
        self.guild = Mock(spec=discord.Guild)
        self.guild.id = 2
        self.guild.name = "VanGuard"
        self.guild.icon = None

        self.good = Mock(spec=discord.Member)
        self.good.bot = False
        self.good.send = AsyncMock()

        self.blocked = Mock(spec=discord.Member)
        self.blocked.bot = False
        response = Mock(status=403, reason="Forbidden")
        self.blocked.send = AsyncMock(
            side_effect=discord.Forbidden(response, {"message": "Cannot send messages", "code": 50007})
        )

        self.unsubscribed = Mock(spec=discord.Member)
        self.unsubscribed.bot = False
        self.unsubscribed.send = AsyncMock()

        self.staff = Mock(spec=discord.Member)
        self.staff.send = AsyncMock()

        members = {11: self.good, 12: self.blocked, 13: self.unsubscribed, 99: self.staff}
        self.guild.get_member.side_effect = lambda member_id: members.get(member_id)
        self.guild.fetch_member = AsyncMock()

    def tearDown(self):
        self.db.close()

    async def test_only_subscribers_receive_dm_and_admin_gets_report(self):
        async def unsubscribe_during_campaign(**kwargs):
            self.cog.state.unsubscribe(2, 13)

        self.good.send.side_effect = unsubscribe_during_campaign
        run_id = self.cog.state.begin(2, 99, "Welcome, subscribers!", 3)
        self.cog.active_guilds.add(2)
        with patch("sentinel.broadcast.asyncio.sleep", new_callable=AsyncMock):
            await self.cog.run_campaign(self.guild, 99, "Welcome, subscribers!", run_id)

        self.good.send.assert_awaited_once()
        self.blocked.send.assert_awaited_once()
        self.unsubscribed.send.assert_not_awaited()
        self.staff.send.assert_awaited_once()
        self.guild.fetch_member.assert_not_awaited()
        self.assertNotIn(2, self.cog.active_guilds)

        report = self.cog.state.latest(2)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["recipients"], 3)
        self.assertEqual(report["sent"], 1)
        self.assertEqual(report["blocked"], 1)
        self.assertEqual(report["skipped"], 1)
        self.assertEqual(report["failed"], 0)

    async def test_report_is_saved_when_staff_dms_are_closed(self):
        self.cog.state.unsubscribe(2, 12)
        self.cog.state.unsubscribe(2, 13)
        self.staff.send = AsyncMock(
            side_effect=discord.Forbidden(Mock(status=403, reason="Forbidden"), "Cannot send")
        )
        run_id = self.cog.state.begin(2, 99, "Announcement", 1)
        with patch("sentinel.broadcast.asyncio.sleep", new_callable=AsyncMock):
            await self.cog.run_campaign(self.guild, 99, "Announcement", run_id)
        self.assertEqual(self.cog.state.latest(2)["status"], "completed")
        self.assertEqual(self.cog.state.latest(2)["sent"], 1)


if __name__ == "__main__":
    unittest.main()
