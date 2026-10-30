import logging
import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Load local .env before importing components that may read settings.
# Railway environment variables take priority (load_dotenv never overrides them).
load_dotenv()

from sentinel.config import SettingsStore
from sentinel.common import reply
from sentinel.guard import Guard
from sentinel.moderation import Moderation, Roles
from sentinel.panel import PermissionsCog
from sentinel.shortcuts import Shortcuts
from sentinel.dashboard import HelpView, LanguageView
from sentinel.i18n import tr, lang

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("sentinel")


class SentinelBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True  # needed for raid detection
        intents.message_content = True  # needed for automatic content moderation
        super().__init__(command_prefix=commands.when_mentioned, intents=intents,
                         allowed_mentions=discord.AllowedMentions.none())
        self.store = SettingsStore()

    async def setup_hook(self):
        for cog in (Moderation(self), Roles(self), Guard(self), PermissionsCog(self), Shortcuts(self)):
            await self.add_cog(cog)
        guild_id = os.getenv("DEV_GUILD_ID", "").strip()
        if guild_id:
            if not guild_id.isdecimal():
                raise RuntimeError("DEV_GUILD_ID must be a numeric server ID")
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info("Synced %d development commands to guild %s", len(synced), guild_id)
        else:
            synced = await self.tree.sync()
            logger.info("Synced %d global commands (may take time to appear)", len(synced))

    async def on_ready(self):
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id)

    async def close(self):
        await super().close()
        self.store.close()


bot = SentinelBot()


@bot.tree.command(name="helpbot", description="Open the interactive staff command dashboard")
@app_commands.guild_only()
async def helpbot(interaction: discord.Interaction):
    panel = HelpView(bot, interaction.guild, interaction.user.id)
    await reply(interaction, embed=panel.render(), view=panel)


@bot.tree.command(name="language", description="Change the server dashboard language / تغيير لغة البوت")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def language(interaction: discord.Interaction):
    panel = LanguageView(bot, interaction.guild, interaction.user.id)
    await reply(interaction, embed=panel.render(), view=panel)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    language = lang(bot.store, interaction.guild_id)
    if isinstance(error, app_commands.MissingPermissions):
        return await reply(interaction, tr(language, "missing_user"))
    if isinstance(error, app_commands.BotMissingPermissions):
        return await reply(interaction, tr(language, "missing_bot"))
    if isinstance(error, app_commands.NoPrivateMessage):
        return await reply(interaction, "This command only works inside a server.")
    if isinstance(error, app_commands.CheckFailure):
        return await reply(interaction, "You cannot run this command here.")
    if isinstance(error, app_commands.CommandOnCooldown):
        return await reply(interaction, f"Try again in {error.retry_after:.1f} seconds.")
    if isinstance(error, app_commands.CommandInvokeError) and isinstance(error.original, discord.Forbidden):
        return await reply(interaction, tr(language, "command_failed"))
    if isinstance(error, app_commands.CommandInvokeError) and isinstance(error.original, discord.HTTPException):
        return await reply(interaction, tr(language, "command_failed"))
    logger.error("Unhandled application command error", exc_info=(type(error), error, error.__traceback__))
    try:
        await reply(interaction, tr(language, "command_failed"))
    except discord.HTTPException:
        pass


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        raise SystemExit("Set DISCORD_TOKEN in your .env file first.")
    bot.run(token, log_handler=None)
