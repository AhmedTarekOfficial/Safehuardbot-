from __future__ import annotations

from collections import defaultdict, deque
from datetime import timedelta
from time import monotonic
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from .common import log_action, reply, target_error
from .i18n import tr, lang, decorate

logger = logging.getLogger("sentinel.guard")

INVITE_PATTERN = re.compile(
    r"(?i)(?:https?://)?(?:www\.)?(?:discord\.gg/|discord(?:app)?\.com/invite/)[a-z0-9-]+"
)
URL_PATTERN = re.compile(r"(?i)https?://[^\s<>]+|www\.[^\s<>]+")
SPAM_WINDOW = 8.0
SPAM_COUNT = 7
REPEAT_WINDOW = 12.0
REPEAT_COUNT = 4
LINK_SPAM_WINDOW = 12.0
LINK_SPAM_COUNT = 3
RAID_WINDOW = 20.0
RAID_COUNT = 8
AUTO_TIMEOUT_MINUTES = 10
QUARANTINE_ROLE_NAME = "VanGuard • Unverified Bot"
DANGEROUS_PERMS = (
    "administrator",
    "ban_members",
    "kick_members",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_webhooks",
    "mention_everyone",
    "moderate_members",
)


def spam_reason(events: deque[tuple[float, str]], now: float, content: str) -> str | None:
    """Pure rate evaluator for testability; events must contain only recent items."""
    if sum(1 for ts, _ in events if now - ts <= SPAM_WINDOW) >= SPAM_COUNT:
        return f"{SPAM_COUNT}+ messages within {int(SPAM_WINDOW)} seconds"
    if content and sum(1 for ts, text in events if now - ts <= REPEAT_WINDOW and text == content) >= REPEAT_COUNT:
        return f"{REPEAT_COUNT}+ repeated messages"
    return None


def link_spam_reason(events: deque[tuple[float, str]], now: float) -> str | None:
    if sum(1 for ts, _ in events if now - ts <= LINK_SPAM_WINDOW) >= LINK_SPAM_COUNT:
        return f"{LINK_SPAM_COUNT}+ link messages within {int(LINK_SPAM_WINDOW)} seconds"
    return None


def message_scan_text(message: discord.Message) -> str:
    """Include embed/attachment URLs so bot spam in embeds is still caught."""
    parts = [message.content or ""]
    for embed in message.embeds:
        for value in (embed.title, embed.description, embed.url, getattr(embed.author, "url", None),
                      getattr(embed.footer, "text", None)):
            if value:
                parts.append(str(value))
        for field in embed.fields:
            parts.append(f"{field.name} {field.value}")
    for attachment in message.attachments:
        if attachment.url:
            parts.append(attachment.url)
    return "\n".join(parts)


def contains_invite(text: str) -> bool:
    return bool(INVITE_PATTERN.search(text or ""))


def contains_url(text: str) -> bool:
    return bool(URL_PATTERN.search(text or "") or INVITE_PATTERN.search(text or ""))


def is_dangerous_bot(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return any(getattr(perms, name, False) for name in DANGEROUS_PERMS)


class ApproveBotView(discord.ui.View):
    """Staff can allowlist a kicked/quarantined bot from the log alert."""

    def __init__(self, store, guild_id: int, bot_id: int):
        super().__init__(timeout=3600)
        self.store = store
        self.guild_id = guild_id
        self.bot_id = bot_id

    @discord.ui.button(label="Approve bot", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        language = lang(self.store, interaction.guild_id)
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await reply(interaction, tr(language, "missing_user"))
            return
        self.store.approve_bot(self.guild_id, self.bot_id, interaction.user.id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await reply(interaction, tr(language, "bot_approved", bot=str(self.bot_id)))
        await log_action(
            interaction.guild, self.store, "Bot approved",
            f"Bot ID: `{self.bot_id}`\nBy: {interaction.user} (`{interaction.user.id}`)\n"
            "Re-invite the bot if it was kicked.",
        )


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
class Guard(commands.GroupCog, group_name="guard", group_description="Configure protection and security logs"):
    def __init__(self, bot):
        self.bot = bot
        self.messages: dict[tuple[int, int], deque[tuple[float, str]]] = defaultdict(lambda: deque(maxlen=30))
        self.link_messages: dict[tuple[int, int], deque[tuple[float, str]]] = defaultdict(lambda: deque(maxlen=20))
        self.joins: dict[int, deque[float]] = defaultdict(lambda: deque(maxlen=50))
        self.last_action: dict[tuple[int, int], float] = {}
        self.last_raid_alert: dict[int, float] = {}

    @app_commands.command(description="Enable or disable automatic spam detection and timeout/kick")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def antispam(self, interaction: discord.Interaction, enabled: bool):
        self.bot.store.update(interaction.guild_id, antispam=enabled)
        language = lang(self.bot.store, interaction.guild_id)
        await reply(interaction, tr(language, "guard_updated",
                                    name=tr(language, "spam"), state=tr(language, "on" if enabled else "off")))

    @app_commands.command(description="Enable or disable invite/URL spam link filtering")
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

    @app_commands.command(name="botguard", description="Kick/quarantine new bots until staff approve them")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botguard(self, interaction: discord.Interaction, enabled: bool):
        self.bot.store.update(interaction.guild_id, bot_guard=enabled)
        language = lang(self.bot.store, interaction.guild_id)
        note = "\n" + tr(language, "bot_guard_note") if enabled else ""
        await reply(interaction, tr(language, "guard_updated",
                                    name=tr(language, "bot_guard"), state=tr(language, "on" if enabled else "off")) + note)

    @app_commands.command(description="Allowlist a bot so bot-guard will not kick it on join")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def approvebot(self, interaction: discord.Interaction, bot: discord.User):
        language = lang(self.bot.store, interaction.guild_id)
        if not bot.bot:
            await reply(interaction, tr(language, "bot_not_bot"))
            return
        if bot.id == self.bot.user.id:
            await reply(interaction, tr(language, "bot_self"))
            return
        self.bot.store.approve_bot(interaction.guild_id, bot.id, interaction.user.id)
        # Lift quarantine role if the bot is currently in the server.
        member = interaction.guild.get_member(bot.id)
        if member is not None:
            await self._lift_quarantine(member, interaction.user)
        await reply(interaction, tr(language, "bot_approved", bot=f"{bot} (`{bot.id}`)"))
        await log_action(interaction.guild, self.bot.store, "Bot approved",
                         f"Bot: {bot} (`{bot.id}`)\nBy: {interaction.user} (`{interaction.user.id}`)")

    @app_commands.command(description="Remove a bot from the allowlist")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def revokebot(self, interaction: discord.Interaction, bot: discord.User):
        language = lang(self.bot.store, interaction.guild_id)
        if not bot.bot:
            await reply(interaction, tr(language, "bot_not_bot"))
            return
        removed = self.bot.store.revoke_bot(interaction.guild_id, bot.id)
        await reply(interaction, tr(language, "bot_revoked" if removed else "bot_not_approved",
                                    bot=f"{bot} (`{bot.id}`)"))
        if removed:
            await log_action(interaction.guild, self.bot.store, "Bot approval revoked",
                             f"Bot: {bot} (`{bot.id}`)\nBy: {interaction.user} (`{interaction.user.id}`)")

    @app_commands.command(description="List bots approved for this server")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botlist(self, interaction: discord.Interaction):
        language = lang(self.bot.store, interaction.guild_id)
        ids = self.bot.store.approved_bots(interaction.guild_id)
        if not ids:
            await reply(interaction, tr(language, "bot_list_empty"))
            return
        lines = []
        for bot_id in ids[:40]:
            member = interaction.guild.get_member(bot_id)
            label = f"{member} (`{bot_id}`)" if member else f"`{bot_id}`"
            lines.append(f"• {label}")
        embed = discord.Embed(
            title=tr(language, "bot_list_title"),
            description="\n".join(lines),
            color=discord.Color.from_rgb(46, 184, 148),
        )
        await reply(interaction, embed=decorate(embed, interaction.guild))

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
        flags = (c.antispam, c.links, c.raid, c.bot_guard)
        enabled_count = sum(flags)
        embed = discord.Embed(
            title=tr(language, "guard_title"),
            description=tr(language, "guard_desc") +
            "\n━━━━━━━━━━━━━━━━━━━━\n" +
            ("▰" * enabled_count) + ("▱" * (4 - enabled_count)) + f"   {enabled_count}/4",
            color=discord.Color.from_rgb(46, 184, 148) if enabled_count else discord.Color.from_rgb(221, 153, 75),
        )
        for name, enabled in (
            ("spam", c.antispam), ("links", c.links), ("raid", c.raid), ("bot_guard", c.bot_guard)
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
        approved = len(self.bot.store.approved_bots(interaction.guild_id))
        embed.add_field(name=tr(language, "bot_list_title"), value=str(approved), inline=True)
        embed.add_field(name="ℹ️", value=tr(language, "raid_note") + "\n" + tr(language, "bot_guard_note"), inline=False)
        await reply(interaction, embed=decorate(embed, interaction.guild))

    def _staff_exempt(self, member: discord.Member, channel) -> bool:
        if member.id == member.guild.owner_id:
            return True
        # Foreign bots are never staff-exempt, even with Manage Messages / Administrator.
        if member.bot:
            return False
        return channel.permissions_for(member).manage_messages

    async def _punish_spammer(self, member: discord.Member, me: discord.Member, reason: str) -> str:
        if member.bot:
            if me.guild_permissions.kick_members and me.top_role > member.top_role:
                try:
                    await member.kick(reason=f"Sentinel anti-spam: {reason}")
                    return "Foreign bot kicked"
                except discord.HTTPException:
                    return "Kick failed (check permissions/hierarchy)"
            return "Could not kick foreign bot (check permissions/hierarchy)"
        if me.guild_permissions.moderate_members and not target_error(me, member, me, for_timeout=True):
            try:
                await member.timeout(timedelta(minutes=AUTO_TIMEOUT_MINUTES), reason=f"Sentinel anti-spam: {reason}")
                return f"Timed out for {AUTO_TIMEOUT_MINUTES} minutes"
            except discord.HTTPException:
                return "Timeout failed (check permissions/hierarchy)"
        return "Could not timeout (check permissions/hierarchy)"

    async def _ensure_quarantine_role(self, guild: discord.Guild) -> discord.Role | None:
        existing = discord.utils.get(guild.roles, name=QUARANTINE_ROLE_NAME)
        if existing is not None:
            return existing
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return None
        try:
            role = await guild.create_role(
                name=QUARANTINE_ROLE_NAME,
                permissions=discord.Permissions.none(),
                reason="Quarantine role for unverified bots",
                colour=discord.Colour.dark_grey(),
            )
        except discord.HTTPException:
            logger.exception("Failed creating quarantine role in guild %s", guild.id)
            return None
        for channel in guild.channels:
            if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.ForumChannel,
                                        discord.StageChannel, discord.CategoryChannel)):
                continue
            try:
                overwrite = channel.overwrites_for(role)
                overwrite.view_channel = False
                overwrite.send_messages = False
                overwrite.connect = False
                overwrite.speak = False
                overwrite.create_instant_invite = False
                await channel.set_permissions(role, overwrite=overwrite, reason="Unverified bot quarantine")
            except (discord.Forbidden, discord.HTTPException):
                continue
        return role

    async def _quarantine_bot(self, member: discord.Member) -> str:
        """Best-effort lockdown when kick is impossible. Admin bots bypass overwrites."""
        if is_dangerous_bot(member):
            return "CRITICAL: admin/dangerous bot could not be kicked — remove it manually"
        role = await self._ensure_quarantine_role(member.guild)
        me = member.guild.me
        if role is None or me is None or not me.guild_permissions.manage_roles:
            return "Quarantine failed (need Manage Roles + Kick Members)"
        if role >= me.top_role:
            return "Quarantine failed (raise bot role above quarantine role)"
        try:
            await member.add_roles(role, reason="Unverified bot quarantine pending staff approval")
        except discord.HTTPException:
            return "Quarantine role assign failed"
        # Extra member denies on text channels (ignored by Administrator).
        for channel in member.guild.text_channels:
            try:
                overwrite = channel.overwrites_for(member)
                overwrite.view_channel = False
                overwrite.send_messages = False
                overwrite.send_messages_in_threads = False
                await channel.set_permissions(member, overwrite=overwrite, reason="Unverified bot quarantine")
            except (discord.Forbidden, discord.HTTPException):
                continue
        return "Quarantined (no chat/voice access) until /guard approvebot"

    async def _lift_quarantine(self, member: discord.Member, actor: discord.Member) -> None:
        role = discord.utils.get(member.guild.roles, name=QUARANTINE_ROLE_NAME)
        me = member.guild.me
        if role is not None and role in member.roles and me and me.guild_permissions.manage_roles and role < me.top_role:
            try:
                await member.remove_roles(role, reason=f"Bot approved by {actor}")
            except discord.HTTPException:
                pass
        for channel in member.guild.text_channels:
            try:
                await channel.set_permissions(member, overwrite=None, reason=f"Bot approved by {actor}")
            except (discord.Forbidden, discord.HTTPException):
                continue

    async def _handle_unverified_bot(self, member: discord.Member) -> None:
        if member.id == self.bot.user.id:
            return
        if self.bot.store.is_bot_approved(member.guild.id, member.id):
            return
        me = member.guild.me
        if me is None:
            return
        dangerous = is_dangerous_bot(member)
        action = "no action"
        kicked = False
        if me.guild_permissions.kick_members and me.top_role > member.top_role:
            try:
                await member.kick(
                    reason="Unverified bot — /guard approvebot then re-invite",
                )
                action = "Kicked pending staff approval"
                kicked = True
            except discord.HTTPException:
                action = await self._quarantine_bot(member)
        else:
            action = await self._quarantine_bot(member)
            if dangerous and "CRITICAL" not in action:
                action = "CRITICAL: could not kick dangerous bot — " + action

        language = lang(self.bot.store, member.guild.id)
        detail = (
            f"Bot: {member} (`{member.id}`)\n"
            f"Dangerous permissions: {'yes' if dangerous else 'no'}\n"
            f"Action: {action}\n"
            f"Approve with `/guard approvebot` then re-invite if kicked."
        )
        settings = self.bot.store.get(member.guild.id)
        channel = member.guild.get_channel(settings.log_channel_id) if settings.log_channel_id else None
        view = ApproveBotView(self.bot.store, member.guild.id, member.id)
        if isinstance(channel, discord.TextChannel) and channel.permissions_for(me).send_messages:
            embed = discord.Embed(
                title=tr(language, "bot_join_title"),
                description=detail,
                color=discord.Color.red() if dangerous else discord.Color.orange(),
            )
            try:
                await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
                return
            except discord.HTTPException:
                pass
        await log_action(member.guild, self.bot.store, tr(language, "bot_join_title"), detail)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or not isinstance(message.author, discord.Member):
            return
        # Always ignore ourselves; still moderate other bots and humans.
        if message.author.id == self.bot.user.id:
            return
        config = self.bot.store.get(message.guild.id)
        if not (config.antispam or config.links):
            return
        member = message.author
        if self._staff_exempt(member, message.channel):
            return
        me = message.guild.me
        if me is None:
            return
        bot_permissions = message.channel.permissions_for(me)
        text = message_scan_text(message)

        if config.links and bot_permissions.manage_messages:
            invite = contains_invite(text)
            url = contains_url(text)
            if invite or (member.bot and url):
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
                else:
                    label = "Invite/link spam removed (bot)" if member.bot else "Invite link removed"
                    await log_action(
                        message.guild, self.bot.store, label,
                        f"Member: {member} (`{member.id}`)\nChannel: {message.channel.mention}",
                    )
                if invite or member.bot:
                    # Link floods from bots escalate to kick via antispam path below when enabled.
                    if not config.antispam:
                        return
            if url:
                now = monotonic()
                link_key = (message.guild.id, member.id)
                link_entries = self.link_messages[link_key]
                while link_entries and now - link_entries[0][0] > LINK_SPAM_WINDOW:
                    link_entries.popleft()
                link_entries.append((now, "link"))
                link_reason = link_spam_reason(link_entries, now)
                if link_reason and now - self.last_action.get(link_key, -1e12) >= 60:
                    self.last_action[link_key] = now
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        pass
                    action = await self._punish_spammer(member, me, link_reason)
                    await log_action(
                        message.guild, self.bot.store, "Link spam blocked",
                        f"Member: {member} (`{member.id}`)\nReason: {link_reason}\n"
                        f"Action: {action}\nChannel: {message.channel.mention}",
                    )
                    return

        if not config.antispam:
            return
        now = monotonic()
        key = (message.guild.id, member.id)
        entries = self.messages[key]
        while entries and now - entries[0][0] > REPEAT_WINDOW:
            entries.popleft()
        normalized = " ".join((message.content or "").casefold().split())[:500]
        # Bots often spam via embeds with empty content — still count the event.
        if not normalized and message.author.bot:
            normalized = f"bot-embed:{hash(text) & 0xFFFF}"
        entries.append((now, normalized))
        if len(self.messages) > 10000:
            self.messages = defaultdict(lambda: deque(maxlen=30), {
                k: v for k, v in self.messages.items() if v and now - v[-1][0] < 60
            })
        reason = spam_reason(entries, now, normalized)
        if not reason and len(message.mentions) >= 8:
            reason = "8+ user mentions in one message"
        # Foreign bots: lower threshold — 4 messages in the spam window.
        if not reason and member.bot:
            if sum(1 for ts, _ in entries if now - ts <= SPAM_WINDOW) >= 4:
                reason = "Foreign bot message flood"
        if not reason or now - self.last_action.get(key, -1e12) < 60:
            return
        self.last_action[key] = now
        if bot_permissions.manage_messages:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
        action = await self._punish_spammer(member, me, reason)
        await log_action(
            message.guild, self.bot.store, "Anti-spam triggered",
            f"Member: {member} (`{member.id}`)\nReason: {reason}\nAction: {action}\n"
            f"Channel: {message.channel.mention}",
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = self.bot.store.get(member.guild.id)
        if member.bot:
            if config.bot_guard:
                await self._handle_unverified_bot(member)
            return
        if not config.raid:
            return
        now = monotonic()
        joins = self.joins[member.guild.id]
        while joins and now - joins[0] > RAID_WINDOW:
            joins.popleft()
        joins.append(now)
        if len(joins) < RAID_COUNT or now - self.last_raid_alert.get(member.guild.id, -1e12) < 120:
            return
        self.last_raid_alert[member.guild.id] = now
        await log_action(
            member.guild, self.bot.store, "Possible join raid detected",
            f"At least **{len(joins)}** members joined within **{int(RAID_WINDOW)} seconds**.\n"
            "This detection is alert-only; no members were automatically kicked/banned.",
        )
