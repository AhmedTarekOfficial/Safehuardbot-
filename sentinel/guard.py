from collections import defaultdict, deque
from datetime import timedelta
from time import monotonic
import re

import discord
from discord import app_commands
from discord.ext import commands

from .common import log_action, reply, target_error
from .i18n import tr, lang, decorate

INVITE_PATTERN = re.compile(r"(?i)(?:https?://)?(?:www\.)?(?:discord\.gg/|discord(?:app)?\.com/invite/)[a-z0-9-]+")
SPAM_WINDOW = 8.0
SPAM_COUNT = 7
REPEAT_WINDOW = 12.0
REPEAT_COUNT = 4
RAID_WINDOW = 20.0
RAID_COUNT = 8
AUTO_TIMEOUT_MINUTES = 10


def spam_reason(events: deque[tuple[float, str]], now: float, content: str) -> str | None:
    """Pure rate evaluator for testability; events must contain only recent items."""
    if sum(1 for ts, _ in events if now - ts <= SPAM_WINDOW) >= SPAM_COUNT:
        return f"{SPAM_COUNT}+ messages within {int(SPAM_WINDOW)} seconds"
    if content and sum(1 for ts, text in events if now - ts <= REPEAT_WINDOW and text == content) >= REPEAT_COUNT:
        return f"{REPEAT_COUNT}+ repeated messages"
    return None


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
class Guard(commands.GroupCog, group_name="guard", group_description="Configure protection and security logs"):
    def __init__(self, bot):
        self.bot = bot
        self.messages: dict[tuple[int, int], deque[tuple[float, str]]] = defaultdict(lambda: deque(maxlen=30))
        self.joins: dict[int, deque[float]] = defaultdict(lambda: deque(maxlen=50))
        self.last_action: dict[tuple[int, int], float] = {}
        self.last_raid_alert: dict[int, float] = {}

    @app_commands.command(description="Enable or disable automatic spam detection and timeout")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def antispam(self, interaction: discord.Interaction, enabled: bool):
        self.bot.store.update(interaction.guild_id, antispam=enabled)
        language = lang(self.bot.store, interaction.guild_id)
        await reply(interaction, tr(language, "guard_updated",
                                    name=tr(language, "spam"), state=tr(language, "on" if enabled else "off")))

    @app_commands.command(description="Enable or disable deletion of Discord invite links")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def links(self, interaction: discord.Interaction, enabled: bool):
        self.bot.store.update(interaction.guild_id, links=enabled)
        language = lang(self.bot.store, interaction.guild_id)
        await reply(interaction, tr(language, "guard_updated",
                                    name=tr(language, "links"), state=tr(language, "on" if enabled else "off")))

    @app_commands.command(description="Enable or disable join-spike (raid) alerts")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def raid(self, interaction: discord.Interaction, enabled: bool):
        self.bot.store.update(interaction.guild_id, raid=enabled)
        language = lang(self.bot.store, interaction.guild_id)
        await reply(interaction, tr(language, "guard_updated",
                                    name=tr(language, "raid"), state=tr(language, "on" if enabled else "off")) +
                                    "\n" + tr(language, "raid_note"))

    @app_commands.command(description="Set the channel that receives moderation and guard events")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def logs(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        me = interaction.guild.me or await interaction.guild.fetch_member(self.bot.user.id)
        perms = channel.permissions_for(me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            await reply(interaction, tr(lang(self.bot.store, interaction.guild_id), "logs_perms"))
            return
        self.bot.store.update(interaction.guild_id, log_channel_id=channel.id)
        await reply(interaction, tr(lang(self.bot.store, interaction.guild_id), "logs_saved", channel=channel.mention))

    @app_commands.command(description="Turn off moderation and guard logs")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def clearlogs(self, interaction: discord.Interaction):
        self.bot.store.update(interaction.guild_id, log_channel_id=None)
        await reply(interaction, tr(lang(self.bot.store, interaction.guild_id), "logs_clear"))

    @app_commands.command(description="See current guard settings")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction):
        c = self.bot.store.get(interaction.guild_id)
        language = c.language
        enabled_count = sum((c.antispam, c.links, c.raid))
        embed = discord.Embed(
            title=tr(language, "guard_title"),
            description=tr(language, "guard_desc") +
            "\n━━━━━━━━━━━━━━━━━━━━\n" +
            ("▰" * enabled_count) + ("▱" * (3 - enabled_count)) + f"   {enabled_count}/3",
            color=discord.Color.from_rgb(46, 184, 148) if enabled_count else discord.Color.from_rgb(221, 153, 75),
        )
        for name, enabled in (
            ("spam", c.antispam), ("links", c.links), ("raid", c.raid)
        ):
            embed.add_field(
                name=f"{'🟢' if enabled else '⚫'}  {tr(language, name)}",
                value=tr(language, "on" if enabled else "off"),
                inline=True,
            )
        embed.add_field(
            name="📋  " + tr(language, "logs"),
            value=f"<#{c.log_channel_id}>" if c.log_channel_id else tr(language, "not_set"),
            inline=False,
        )
        embed.add_field(name="ℹ️", value=tr(language, "raid_note"), inline=False)
        await reply(interaction, embed=decorate(embed, interaction.guild))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or not isinstance(message.author, discord.Member):
            return
        config = self.bot.store.get(message.guild.id)
        if not (config.antispam or config.links):
            return
        member = message.author
        if member.id == message.guild.owner_id or message.channel.permissions_for(member).manage_messages:
            return
        me = message.guild.me
        if me is None:
            return
        bot_permissions = message.channel.permissions_for(me)
        if config.links and INVITE_PATTERN.search(message.content) and bot_permissions.manage_messages:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            else:
                await log_action(message.guild, self.bot.store, "Invite link removed",
                                 f"Member: {member} (`{member.id}`)\nChannel: {message.channel.mention}")
            return
        if not config.antispam:
            return
        now = monotonic()
        key = (message.guild.id, member.id)
        entries = self.messages[key]
        while entries and now - entries[0][0] > REPEAT_WINDOW:
            entries.popleft()
        normalized = " ".join(message.content.casefold().split())[:500]
        entries.append((now, normalized))
        if len(self.messages) > 10000:
            self.messages = defaultdict(lambda: deque(maxlen=30), {k: v for k, v in self.messages.items()
                if v and now - v[-1][0] < 60})
        reason = spam_reason(entries, now, normalized)
        if not reason and len(message.mentions) >= 8:
            reason = "8+ user mentions in one message"
        if not reason or now - self.last_action.get(key, -1e12) < 60:
            return
        self.last_action[key] = now
        if bot_permissions.manage_messages:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
        if me.guild_permissions.moderate_members and not target_error(me, member, me, for_timeout=True):
            try:
                await member.timeout(timedelta(minutes=AUTO_TIMEOUT_MINUTES), reason=f"Sentinel anti-spam: {reason}")
                action = f"Timed out for {AUTO_TIMEOUT_MINUTES} minutes"
            except discord.HTTPException:
                action = "Timeout failed (check permissions/hierarchy)"
        else:
            action = "Could not timeout (check permissions/hierarchy)"
        await log_action(message.guild, self.bot.store, "Anti-spam triggered",
                         f"Member: {member} (`{member.id}`)\nReason: {reason}\nAction: {action}\nChannel: {message.channel.mention}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not self.bot.store.get(member.guild.id).raid:
            return
        now = monotonic()
        joins = self.joins[member.guild.id]
        while joins and now - joins[0] > RAID_WINDOW:
            joins.popleft()
        joins.append(now)
        if len(joins) < RAID_COUNT or now - self.last_raid_alert.get(member.guild.id, -1e12) < 120:
            return
        self.last_raid_alert[member.guild.id] = now
        await log_action(member.guild, self.bot.store, "Possible join raid detected",
                         f"At least **{len(joins)}** members joined within **{int(RAID_WINDOW)} seconds**.\n"
                         "This detection is alert-only; no members were automatically kicked/banned.")
