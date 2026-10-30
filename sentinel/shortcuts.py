"""Staff-only, no-prefix shortcuts. They never bypass permission or hierarchy checks."""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from time import monotonic

import discord
from discord import app_commands
from discord.ext import commands

from .common import log_action, reply, target_error
from .i18n import tr, lang, decorate

logger = logging.getLogger("sentinel.shortcuts")
ALLOWED = (
    "timeout", "untimeout", "mute", "unmute", "vmute", "vunmute", "kick", "ban", "purge",
    "antispam_on", "antispam_off", "links_on", "links_off",
    "raid_on", "raid_off",
)
ACTION_CHOICES = [app_commands.Choice(name=name, value=name) for name in ALLOWED]
WORD = re.compile(r"^[^\W_]{2,24}$", flags=re.UNICODE)
MENTION = re.compile(r"<@!?\d+>")
ACTION_PERMISSION = {
    "timeout": "moderate_members", "untimeout": "moderate_members",
    "mute": "moderate_members", "unmute": "moderate_members",
    "vmute": "mute_members", "vunmute": "mute_members",
    "kick": "kick_members", "ban": "ban_members", "purge": "manage_messages",
    "antispam_on": "manage_guild", "antispam_off": "manage_guild",
    "links_on": "manage_guild", "links_off": "manage_guild",
    "raid_on": "manage_guild", "raid_off": "manage_guild",
}


def normalized_word(value: str) -> str:
    """Reject slash/prefix/whitespace and normalize case for Latin and Arabic words."""
    word = value.strip().casefold()
    if not WORD.fullmatch(word):
        raise ValueError("Shortcut must be one word of 2-24 alphanumeric characters")
    return word


def parse_command(content: str, aliases: dict[str, str]):
    """Return (trigger, action, remaining arguments) only on an exact first word."""
    parts = content.strip().split(maxsplit=1)
    if not parts:
        return None
    trigger = parts[0].casefold()
    action = aliases.get(trigger)
    if not action in ALLOWED:
        return None
    return trigger, action, parts[1] if len(parts) > 1 else ""


def integer_arg(text: str, minimum: int, maximum: int, *, default=None):
    clean = MENTION.sub("", text).strip()
    if not clean and default is not None:
        return default
    if not clean.isdecimal():
        return None
    number = int(clean)
    return number if minimum <= number <= maximum else None


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
class Shortcuts(commands.GroupCog, group_name="shortcut", group_description="Configure staff-only no-prefix commands"):
    def __init__(self, bot):
        self.bot = bot
        self.recent: dict[tuple[int, int], float] = {}

    @app_commands.command(name="channel", description="Choose the channel where no-prefix staff commands work")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        language = lang(self.bot.store, interaction.guild_id)
        me = interaction.guild.me or await interaction.guild.fetch_member(self.bot.user.id)
        perms = channel.permissions_for(me)
        if not (perms.view_channel and perms.send_messages and perms.read_message_history):
            await reply(interaction, tr(language, "missing_bot"))
            return
        self.bot.store.update(interaction.guild_id, shortcut_channel_id=channel.id, shortcuts_enabled=True)
        await reply(interaction, tr(language, "short_chan_saved", channel=channel.mention))

    @app_commands.command(name="anywhere", description="Allow shortcuts in any server channel (default)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def anywhere(self, interaction: discord.Interaction):
        self.bot.store.update(interaction.guild_id, shortcut_channel_id=None, shortcuts_enabled=True)
        await reply(interaction, tr(lang(self.bot.store, interaction.guild_id), "short_anywhere"))

    @app_commands.command(name="disable", description="Disable all shortcuts without deleting their definitions")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable(self, interaction: discord.Interaction):
        self.bot.store.update(interaction.guild_id, shortcuts_enabled=False)
        await reply(interaction, tr(lang(self.bot.store, interaction.guild_id), "short_disabled"))

    @app_commands.command(name="set", description="Assign a custom word to a staff action")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(action=ACTION_CHOICES)
    async def set_alias(self, interaction: discord.Interaction, word: str, action: app_commands.Choice[str]):
        language = lang(self.bot.store, interaction.guild_id)
        try:
            word = normalized_word(word)
        except ValueError:
            await reply(interaction, tr(language, "short_invalid"))
            return
        mappings = self.bot.store.shortcuts_for(interaction.guild_id)
        if word not in mappings and len(mappings) >= 25:
            await reply(interaction, tr(language, "short_limit"))
            return
        if action.value not in ALLOWED:
            await reply(interaction, tr(language, "short_failed"))
            return
        self.bot.store.set_shortcut(interaction.guild_id, word, action.value)
        settings = self.bot.store.get(interaction.guild_id)
        response = tr(language, "short_set", word=word, action=action.value)
        if not settings.shortcuts_enabled:
            response += "\n" + tr(language, "short_disabled")
        elif settings.shortcut_channel_id is not None:
            response += "\n" + tr(language, "short_scope_channel", channel=f"<#{settings.shortcut_channel_id}>")
        else:
            response += "\n" + tr(language, "short_scope_anywhere")
        await reply(interaction, response)

    @app_commands.command(name="remove", description="Delete a configured shortcut")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction, word: str):
        language = lang(self.bot.store, interaction.guild_id)
        try:
            word = normalized_word(word)
        except ValueError:
            await reply(interaction, tr(language, "short_invalid"))
            return
        removed = self.bot.store.remove_shortcut(interaction.guild_id, word)
        await reply(interaction, tr(language, "short_removed" if removed else "short_missing", word=word))

    @app_commands.command(name="list", description="See no-prefix commands configured for this server")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def list_aliases(self, interaction: discord.Interaction):
        language = lang(self.bot.store, interaction.guild_id)
        settings = self.bot.store.get(interaction.guild_id)
        mappings = self.bot.store.shortcuts_for(interaction.guild_id)
        embed = discord.Embed(
            title=tr(language, "short_title"),
            description=tr(language, "short_desc"),
            color=discord.Color.from_rgb(74, 196, 179),
        )
        embed.add_field(
            name=tr(language, "short_chan"),
            value=(tr(language, "short_disabled") if not settings.shortcuts_enabled
                   else f"<#{settings.shortcut_channel_id}>" if settings.shortcut_channel_id
                   else tr(language, "short_scope_anywhere")),
            inline=False,
        )
        lines = [f"`{word}`  →  `{action}`" for word, action in mappings.items()]
        embed.add_field(
            name=f"⚡  {len(mappings)}/25",
            value="\n".join(lines) if lines else tr(language, "short_empty"),
            inline=False,
        )
        await reply(interaction, embed=decorate(embed, interaction.guild))

    @app_commands.command(name="diagnose", description="Check shortcut status and permissions in this channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def diagnose(self, interaction: discord.Interaction, word: str = ""):
        language = lang(self.bot.store, interaction.guild_id)
        config = self.bot.store.get(interaction.guild_id)
        mappings = self.bot.store.shortcuts_for(interaction.guild_id)
        active_here = config.shortcuts_enabled and (
            config.shortcut_channel_id is None or config.shortcut_channel_id == interaction.channel_id
        )
        me = interaction.guild.me or await interaction.guild.fetch_member(self.bot.user.id)
        perms = interaction.channel.permissions_for(me)
        can_read_and_reply = perms.view_channel and perms.send_messages
        status = [
            f"**{tr(language, 'short_scope_label')}:** " +
            (tr(language, "short_scope_anywhere") if config.shortcut_channel_id is None
             else f"<#{config.shortcut_channel_id}>"),
            f"**Enabled:** {'✅' if config.shortcuts_enabled else '❌'}",
            f"**Current channel allowed:** {'✅' if active_here else '❌'}",
            f"**Bot View Channel / Send Messages:** {'✅' if can_read_and_reply else '❌'}",
            f"**Message Content Intent (code):** {'✅' if self.bot.intents.message_content else '❌'}",
            f"**Stored shortcuts:** {len(mappings)}",
        ]
        if word:
            key = word.strip().casefold()
            action = mappings.get(key)
            status.append(f"**{discord.utils.escape_markdown(word[:24])}:** " +
                          (f"`{action}`" if action else tr(language, "short_missing", word=word[:24])))
        status.append(tr(language, "short_diagnose_hint"))
        embed = discord.Embed(title="🔎 Shortcut Diagnostics", description="\n".join(status),
                              color=discord.Color.green() if active_here and can_read_and_reply
                              else discord.Color.orange())
        await reply(interaction, embed=decorate(embed, interaction.guild))

    async def target_for(self, message: discord.Message):
        if len(message.mentions) > 1:
            return None
        if message.mentions:
            member = message.mentions[0]
        elif message.reference is not None:
            original = message.reference.resolved
            if not isinstance(original, discord.Message):
                try:
                    original = await message.channel.fetch_message(message.reference.message_id)
                except (discord.HTTPException, TypeError):
                    return None
            member = original.author
        else:
            return None
        if not isinstance(member, discord.Member):
            try:
                member = await message.guild.fetch_member(member.id)
            except discord.HTTPException:
                return None
        return member

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or not isinstance(message.author, discord.Member):
            return
        config = self.bot.store.get(message.guild.id)
        if not config.shortcuts_enabled:
            return
        # None means server-wide; a specific channel ID is an optional restriction.
        if config.shortcut_channel_id is not None and config.shortcut_channel_id != message.channel.id:
            return
        parsed = parse_command(message.content, self.bot.store.shortcuts_for(message.guild.id))
        if parsed is None:
            return
        word, action, args = parsed
        language = config.language
        actor = message.author
        required = ACTION_PERMISSION[action]
        actor_perms = message.channel.permissions_for(actor) if action == "purge" else actor.guild_permissions
        if not getattr(actor_perms, required, False):
            await message.reply(tr(language, "short_denied"), mention_author=False)
            return
        me = message.guild.me
        if me is None:
            try:
                me = await message.guild.fetch_member(self.bot.user.id)
            except discord.HTTPException:
                return
        bot_perms = message.channel.permissions_for(me) if action == "purge" else me.guild_permissions
        channel_perms = message.channel.permissions_for(me)
        if not (channel_perms.view_channel and channel_perms.send_messages) or not getattr(bot_perms, required, False) or (action == "purge" and not channel_perms.read_message_history):
            logger.warning("Shortcut %s blocked: bot lacks permissions in guild %s channel %s",
                           action, message.guild.id, message.channel.id)
            return
        key = message.guild.id, actor.id
        now = monotonic()
        if now - self.recent.get(key, -1e12) < 2:
            return
        if len(self.recent) > 3000:
            self.recent = {k: v for k, v in self.recent.items() if now-v < 120}
        try:
            if action.startswith(("antispam_", "links_", "raid_")):
                feature, enabled = action.rsplit("_", 1)
                self.bot.store.update(message.guild.id, **{feature: enabled == "on"})
                detail = f"{feature} = {enabled}"
            elif action == "purge":
                amount = integer_arg(args, 1, 100)
                if amount is None:
                    await message.reply(tr(language, "short_amount"), mention_author=False)
                    return
                deleted = await message.channel.purge(limit=amount)
                detail = f"{len(deleted)} messages removed from {message.channel}"
            else:
                member = await self.target_for(message)
                if member is None:
                    await message.reply(tr(language, "short_target", word=word), mention_author=False)
                    return
                error = target_error(actor, member, me, for_timeout=action in ("timeout", "untimeout", "mute", "unmute"),
                                     language=language)
                if error:
                    await message.reply(error, mention_author=False)
                    return
                reason = f"Quick command by {actor} ({actor.id})"
                if action in ("timeout", "mute"):
                    minutes = integer_arg(args, 1, 40320, default=10)
                    if minutes is None:
                        await message.reply(tr(language, "short_minutes"), mention_author=False)
                        return
                    await member.timeout(timedelta(minutes=minutes), reason=reason)
                    detail = f"{member} ({member.id}) timed out for {minutes} min"
                elif action in ("untimeout", "unmute"):
                    await member.timeout(None, reason=reason)
                    detail = f"Timeout removed from {member} ({member.id})"
                elif action in ("vmute", "vunmute"):
                    if not member.voice or not member.voice.channel:
                        await message.reply(tr(language, "short_voice_missing"), mention_author=False)
                        return
                    voice_channel = member.voice.channel
                    if not voice_channel.permissions_for(actor).mute_members:
                        await message.reply(tr(language, "short_denied"), mention_author=False)
                        return
                    if not voice_channel.permissions_for(me).mute_members:
                        await message.reply(tr(language, "short_bot_denied"), mention_author=False)
                        return
                    is_muting = action == "vmute"
                    await member.edit(mute=is_muting, reason=reason)
                    detail = f"{member} ({member.id}) {'voice muted' if is_muting else 'voice unmuted'}"
                elif action == "kick":
                    await member.kick(reason=reason)
                    detail = f"{member} ({member.id}) kicked"
                elif action == "ban":
                    await message.guild.ban(member, reason=reason)
                    detail = f"{member} ({member.id}) banned"
                else:
                    return
            self.recent[key] = now
            await message.channel.send(
                tr(language, "short_done", action=action, actor=discord.utils.escape_markdown(actor.display_name)),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await log_action(message.guild, self.bot.store, f"Quick command: {action}",
                             f"{detail}\nBy {actor} ({actor.id})")
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Shortcut action failed in guild %s", message.guild.id)
            await message.reply(tr(language, "short_failed"), mention_author=False,
                                allowed_mentions=discord.AllowedMentions.none())
