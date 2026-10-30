"""Text-only mutes via channel permission overrides, never via Discord Timeout."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .common import log_action, reply, target_error
from .i18n import lang

logger = logging.getLogger("sentinel.text_mute")

CHANNEL_TYPES = tuple(
    cls for cls in (getattr(discord, "TextChannel", None),
                    getattr(discord, "ForumChannel", None),
                    getattr(discord, "MediaChannel", None))
    if cls is not None
)

DENIED = (
    "send_messages",
    "send_messages_in_threads",
    "create_public_threads",
    "create_private_threads",
)


class TextMuteError(Exception):
    def __init__(self, english: str, arabic: str):
        self.english, self.arabic = english, arabic
        super().__init__(english)

    def localized(self, language: str) -> str:
        return self.arabic if language == "ar" else self.english


class TextMute(commands.Cog):
    """Provides slash commands and common service for all shortcut aliases."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.store.connection
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS text_mute_roles (
                guild_id INTEGER PRIMARY KEY,
                role_id INTEGER NOT NULL
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS text_mutes (
                guild_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                PRIMARY KEY (guild_id, member_id)
            )"""
        )
        self.db.commit()
        self.expire_mutes.start()

    def cog_unload(self):
        self.expire_mutes.cancel()

    def muted_role(self, guild: discord.Guild) -> discord.Role | None:
        row = self.db.execute(
            "SELECT role_id FROM text_mute_roles WHERE guild_id=?", (guild.id,)
        ).fetchone()
        return guild.get_role(row[0]) if row else None

    async def ensure_role(self, guild: discord.Guild) -> discord.Role:
        role = self.muted_role(guild)
        if role is None:
            role = await guild.create_role(
                name="VanGuard • Muted",
                permissions=discord.Permissions.none(),
                reason="Text-only mute role for channel permissions",
            )
            self.db.execute(
                "INSERT INTO text_mute_roles(guild_id, role_id) VALUES (?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET role_id=excluded.role_id",
                (guild.id, role.id),
            )
            self.db.commit()
        return role

    @staticmethod
    def overwrite_needed(channel, role) -> bool:
        overwrite = channel.overwrites_for(role)
        return any(getattr(overwrite, name) is not False for name in DENIED)

    @staticmethod
    async def apply_overwrite(channel, role):
        overwrite = channel.overwrites_for(role)
        if all(getattr(overwrite, name) is False for name in DENIED):
            return
        for name in DENIED:
            setattr(overwrite, name, False)
        # Preserve any unrelated existing permissions for this role.
        await channel.set_permissions(
            role, overwrite=overwrite,
            reason="VanGuard text-only mute (no voice restrictions)",
        )

    async def sync_channels(self, guild: discord.Guild, role: discord.Role):
        failures = []
        for channel in guild.channels:
            if not isinstance(channel, CHANNEL_TYPES):
                continue
            if not self.overwrite_needed(channel, role):
                continue
            try:
                await self.apply_overwrite(channel, role)
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Cannot configure text mute in guild %s channel %s", guild.id, channel.id)
                failures.append(channel.name)
        if failures:
            raise TextMuteError(
                f"I couldn't configure text permissions in {len(failures)} channel(s): "
                f"{', '.join(failures[:5])}. Give the bot Manage Roles in those channels.",
                f"فشل ضبط صلاحيات الميوت في {len(failures)} قناة: "
                f"{', '.join(failures[:5])}. لازم البوت معاه Manage Roles في القنوات دي.",
            )

    async def validate(self, guild, actor, target, me, *, role=None):
        reason = target_error(actor, target, me, language=lang(self.bot.store, guild.id))
        if reason:
            raise TextMuteError(reason, reason)
        if target.guild_permissions.administrator:
            raise TextMuteError(
                "Administrators bypass text-channel restrictions; I can't text-mute this member.",
                "عضو Administrator بيتجاوز منع الكتابة؛ مينفعش أعمله Text Mute بالرول.",
            )
        if not actor.guild_permissions.manage_roles:
            raise TextMuteError("You need Manage Roles.", "محتاج صلاحية Manage Roles.")
        if not me.guild_permissions.manage_roles:
            raise TextMuteError("The bot needs Manage Roles.", "البوت محتاج صلاحية Manage Roles.")
        if role is not None:
            if role >= me.top_role:
                raise TextMuteError(
                    "Move the bot's role above VanGuard • Muted.",
                    "ارفع رول البوت فوق رول VanGuard • Muted.",
                )
            if actor.id != guild.owner_id and role >= actor.top_role:
                raise TextMuteError(
                    "Your top role must be above VanGuard • Muted.",
                    "لازم رولك الأعلى يكون فوق رول VanGuard • Muted.",
                )

    async def apply(self, guild, actor, member, minutes: int, reason: str = "No reason") -> None:
        if not (1 <= minutes <= 40320):
            raise TextMuteError("Minutes must be 1–40320.", "المدة لازم تكون من 1 لـ40320 دقيقة.")
        me = guild.me or await guild.fetch_member(self.bot.user.id)
        await self.validate(guild, actor, member, me)
        role = await self.ensure_role(guild)
        await self.validate(guild, actor, member, me, role=role)
        await self.sync_channels(guild, role)
        # Existing members may have contradictory explicit channel permissions.
        # Detect conflicts after the role has been granted and be transparent.
        if role not in member.roles:
            await member.add_roles(
                role, reason=f"Text mute by {actor} ({actor.id}): {reason[:300]}",
            )
        expires_at = int((datetime.now(timezone.utc) + timedelta(minutes=minutes)).timestamp())
        self.db.execute(
            """INSERT INTO text_mutes(guild_id, member_id, expires_at)
               VALUES (?, ?, ?)
               ON CONFLICT(guild_id, member_id) DO UPDATE SET expires_at=excluded.expires_at""",
            (guild.id, member.id, expires_at),
        )
        self.db.commit()

    async def remove(self, guild, actor, member, reason: str = "No reason") -> None:
        me = guild.me or await guild.fetch_member(self.bot.user.id)
        await self.validate(guild, actor, member, me)
        role = self.muted_role(guild)
        if role is not None:
            await self.validate(guild, actor, member, me, role=role)
            if role in member.roles:
                await member.remove_roles(
                    role, reason=f"Text unmute by {actor} ({actor.id}): {reason[:300]}",
                )
        self.db.execute(
            "DELETE FROM text_mutes WHERE guild_id=? AND member_id=?",
            (guild.id, member.id),
        )
        self.db.commit()

    @app_commands.command(name="mute", description="Prevent writing only (role-based), no Timeout or voice mute")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.describe(minutes="Minutes until the writing restriction is removed")
    async def mute(self, interaction: discord.Interaction, member: discord.Member,
                   minutes: app_commands.Range[int, 1, 40320] = 10,
                   reason: str = "No reason"):
        await interaction.response.defer(ephemeral=True)
        try:
            await self.apply(interaction.guild, interaction.user, member, minutes, reason)
        except TextMuteError as exc:
            await reply(interaction, exc.localized(lang(self.bot.store, interaction.guild_id)))
            return
        en = f"Text-muted **{discord.utils.escape_markdown(str(member))}** for **{minutes} min**. Voice unaffected."
        ar = f"تم منع **{discord.utils.escape_markdown(str(member))}** من الكتابة لمدة **{minutes} دقيقة**. الصوت مش متأثر."
        await reply(interaction, ar if lang(self.bot.store, interaction.guild_id) == "ar" else en)
        await log_action(interaction.guild, self.bot.store, "Text-only mute",
                         f"Member {member.id} | Moderator {interaction.user.id} | Minutes {minutes}")

    @app_commands.command(name="unmute", description="Allow a member to write again (remove text mute role)")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def unmute(self, interaction: discord.Interaction, member: discord.Member,
                     reason: str = "No reason"):
        await interaction.response.defer(ephemeral=True)
        try:
            await self.remove(interaction.guild, interaction.user, member, reason)
        except TextMuteError as exc:
            await reply(interaction, exc.localized(lang(self.bot.store, interaction.guild_id)))
            return
        en = f"Text mute removed from **{discord.utils.escape_markdown(str(member))}**."
        ar = f"تم السماح لـ**{discord.utils.escape_markdown(str(member))}** بالكتابة تاني."
        await reply(interaction, ar if lang(self.bot.store, interaction.guild_id) == "ar" else en)
        await log_action(interaction.guild, self.bot.store, "Text-only unmute",
                         f"Member {member.id} | Moderator {interaction.user.id}")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        if not isinstance(channel, CHANNEL_TYPES):
            return
        role = self.muted_role(channel.guild)
        if role is None:
            return
        try:
            await self.apply_overwrite(channel, role)
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Failed to apply text mute in new channel %s", channel.id)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if not isinstance(after, CHANNEL_TYPES):
            return
        role = self.muted_role(after.guild)
        if role is None or not self.overwrite_needed(after, role):
            return
        try:
            await self.apply_overwrite(after, role)
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Failed to enforce text mute in channel %s", after.id)

    @tasks.loop(seconds=30)
    async def expire_mutes(self):
        now = int(datetime.now(timezone.utc).timestamp())
        due = self.db.execute(
            "SELECT guild_id, member_id FROM text_mutes WHERE expires_at <= ? LIMIT 100",
            (now,),
        ).fetchall()
        for guild_id, member_id in due:
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue  # Retain in case the bot reconnects to this guild.
            role = self.muted_role(guild)
            try:
                member = guild.get_member(member_id)
                if member is None:
                    member = await guild.fetch_member(member_id)
                if role is not None and role in member.roles:
                    await member.remove_roles(role, reason="VanGuard text mute expired")
            except discord.NotFound:
                pass  # Member already left the server.
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Could not expire text mute for %s in %s", member_id, guild_id)
                continue  # Retry on next tick.
            self.db.execute(
                "DELETE FROM text_mutes WHERE guild_id=? AND member_id=?",
                (guild_id, member_id),
            )
            self.db.commit()

    @expire_mutes.before_loop
    async def before_expire(self):
        await self.bot.wait_until_ready()
