"""Smoke tests for the three main interactive UI components."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from sentinel.config import GuildSettings
from sentinel.dashboard import HelpView, LanguageView
from sentinel.panel import PermissionsView


class DashboardSmokeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guild = SimpleNamespace(id=10, name="Test Guild", icon=None, roles=[])
        self.bot = SimpleNamespace(store=Mock(), get_cog=Mock(return_value=None))
        self.bot.store.shortcuts_for.return_value = {"اص": "mute"}

    async def test_help_dashboard_english(self):
        self.bot.store.get.return_value = GuildSettings(language="en")
        view = HelpView(self.bot, self.guild, 123)
        self.assertIn("CONTROL CENTER", view.render().title)
        view.section = "shortcuts"
        self.assertIn("اص", view.render().description)

    async def test_help_dashboard_arabic(self):
        self.bot.store.get.return_value = GuildSettings(language="ar", antispam=True)
        view = HelpView(self.bot, self.guild, 123)
        self.assertIn("مركز التحكم", view.render().title)
        self.assertIn("الرئيسية", view.home_button.label)

    async def test_language_picker(self):
        self.bot.store.get.return_value = GuildSettings(language="ar")
        view = LanguageView(self.bot, self.guild, 123)
        self.assertIn("اللغة", view.render().title)
        self.assertEqual(len(view.children), 1)

    async def test_permissions_panel(self):
        self.bot.store.get.return_value = GuildSettings(language="ar")
        view = PermissionsView(self.guild, 123, self.bot.store)
        self.assertIn("الصلاحيات", view.render().title)
        self.assertEqual(len(view.children), 5)


if __name__ == "__main__":
    unittest.main()
