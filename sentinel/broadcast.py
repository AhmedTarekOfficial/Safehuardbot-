"""Consent-based private announcement delivery with audit reports and persistent opt-in UI."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from .broadcast_store import BroadcastStore
from .common import log_action, reply
from .i18n import decorate, lang, tr

logger = logging.getLogger("sentinel.broadcast")

# Stay well below message caps and send at a deliberately conservative pace.
MAX_RECIPIENTS = 500
DM_INTERVAL_SECONDS = 1.5


def report_embed(language: str, run: dict, guild: discord.Guild | None = None) -> discord.Embed:
    embed = discord.Embed(
        title=tr(language, "bc_report_title", id=run["id"]),
        description=tr(language, "bc_report_status", status=run["status"]),
        color=discord.Color.from_rgb(77, 172, 178),
    )
    for key, label in (
        ("recipients", "bc_recipients"),
        ("sent", "bc_sent"),
        ("blocked", "bc_blocked"),
        ("failed", "bc_failed"),
        ("skipped", "bc_skipped"),
    ):
        embed.add_field(name=tr(language, label), value=str(run[key]), inline=True)
    embed.add_field(name=tr(language, "bc_report_note"),
                    value=tr(language, "bc_not_read"), inline=False)
    return decorate(embed, guild)


class SubscriptionView(discord.ui.View):
    """Registered once on each boot. The guild is taken from the interaction."""
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Subscribe / اشترك",
        emoji="📩",
        style=discord.ButtonStyle.success,
        custom_id="sentinel:broadcast:subscribe:v1",
    )
    async def subscribe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set(interaction, subscribe=True)

    @discord.ui.button(
        label="Unsubscribe / إلغاء",
        emoji="🔕",
        style=discord.ButtonStyle.secondary,
        custom_id="sentinel:broadcast:unsubscribe:v1",
    )
    async def unsubscribe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set(interaction, subscribe=False)

    async def _set(self, interaction: discord.Interaction, *, subscribe: bool):
        if interaction.guild_id is None or interaction.user.bot:
            await reply(interaction, "This panel is available in a server only.")
            return
        store = self.bot.get_cog("Broadcast").state
        if subscribe:
            created = store.subscribe(interaction.guild_id, interaction.user.id)
            key = "bc_subscribed" if created else "bc_already_subscribed"
        else:
            removed = store.unsubscribe(interaction.guild_id, interaction.user.id)
            key = "bc_unsubscribed" if removed else "bc_not_subscribed"
        await reply(interaction, tr(lang(self.bot.store, interaction.guild_id), key))


class ConfirmView(discord.ui.View):
    def __init__(self, cog, guild_id: int, author_id: int, body: str, count: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id
        self.author_id = author_id
        self.body = body
        self.count = count
        self.used = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        language = lang(self.cog.bot.store, self.guild_id)
        if interaction.guild_id != self.guild_id or interaction.user.id != self.author_id:
            await reply(interaction, tr(language, "private"))
            return False
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await reply(interaction, tr(language, "lang_need"))
            return False
        return True

    @discord.ui.button(label="Confirm send / تأكيد", emoji="📤", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        language = lang(self.cog.bot.store, self.guild_id)
        if self.used:
            await reply(interaction, tr(language, "bc_already_started"))
            return
        self.used = True
        if self.guild_id in self.cog.active_guilds:
            await interaction.response.edit_message(content=tr(language, "bc_busy"), embed=None, view=None)
            return
        # Re-confirm if subscriber counts changed, so preview remains meaningful.
        now_count = self.cog.state.count(self.guild_id)
        if now_count != self.count or now_count > MAX_RECIPIENTS or now_count == 0:
            await interaction.response.edit_message(
                content=tr(language, "bc_changed", count=now_count), embed=None, view=None
            )
            return
        run_id = self.cog.state.begin(self.guild_id, self.author_id, self.body, now_count)
        self.cog.active_guilds.add(self.guild_id)
        await interaction.response.edit_message(
            content=tr(language, "bc_started", id=run_id, count=now_count),
            embed=None, view=None,
        )
        task = asyncio.create_task(
            self.cog.run_campaign(interaction.guild, self.author_id, self.body, run_id),
            name=f"sentinel-broadcast-{self.guild_id}-{run_id}",
        )
        self.cog.tasks.add(task)
        task.add_done_callback(self.cog.tasks.discard)

    @discord.ui.button(label="Cancel / إلغاء", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.used = True
        await interaction.response.edit_message(
            content=tr(lang(self.cog.bot.store, self.guild_id), "bc_cancelled"),
            embed=None, view=None,
        )


@app_commands.guild_only()
class Broadcast(commands.GroupCog, group_name="broadcast", group_description="Opt-in announcements sent by DM"):
    def __init__(self, bot):
        self.bot = bot
        self.state = BroadcastStore(bot.store.connection)
        self.active_guilds: set[int] = set()
        self.tasks: set[asyncio.Task] = set()

    @app_commands.command(name="subscribe", description="Opt into server announcement DMs")
    async def subscribe(self, interaction: discord.Interaction):
        created = self.state.subscribe(interaction.guild_id, interaction.user.id)
        await reply(interaction, tr(lang(self.bot.store, interaction.guild_id),
                                    "bc_subscribed" if created else "bc_already_subscribed"))

    @app_commands.command(name="unsubscribe", description="Stop receiving server announcement DMs")
    async def unsubscribe(self, interaction: discord.Interaction):
        removed = self.state.unsubscribe(interaction.guild_id, interaction.user.id)
        await reply(interaction, tr(lang(self.bot.store, interaction.guild_id),
                                    "bc_unsubscribed" if removed else "bc_not_subscribed"))

    @app_commands.command(name="panel", description="Post a public opt-in announcement panel")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.bot_has_permissions(send_messages=True, embed_links=True)
    async def panel(self, interaction: discord.Interaction):
        language = lang(self.bot.store, interaction.guild_id)
        embed = discord.Embed(
            title=tr(language, "bc_panel_title"),
            description=tr(language, "bc_panel_desc"),
            color=discord.Color.from_rgb(82, 163, 214),
        )
        await interaction.response.defer(ephemeral=True)
        await interaction.channel.send(
            embed=decorate(embed, interaction.guild),
            view=SubscriptionView(self.bot),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await reply(interaction, tr(language, "bc_panel_posted"))

    @app_commands.command(name="send", description="Preview an opt-in DM announcement before confirming")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def send(self, interaction: discord.Interaction, message: app_commands.Range[str, 1, 1600]):
        language = lang(self.bot.store, interaction.guild_id)
        if interaction.guild_id in self.active_guilds:
            await reply(interaction, tr(language, "bc_busy"))
            return
        count = self.state.count(interaction.guild_id)
        if count == 0:
            await reply(interaction, tr(language, "bc_no_audience"))
            return
        if count > MAX_RECIPIENTS:
            await reply(interaction, tr(language, "bc_too_many", max=MAX_RECIPIENTS, count=count))
            return
        embed = discord.Embed(
            title=tr(language, "bc_preview_title"),
            description=message,
            color=discord.Color.from_rgb(82, 163, 214),
        )
        embed.add_field(name=tr(language, "bc_recipients"), value=str(count), inline=True)
        embed.add_field(name=tr(language, "bc_preview_note"),
                        value=tr(language, "bc_not_read"), inline=False)
        await reply(interaction, embed=decorate(embed, interaction.guild),
                    view=ConfirmView(self, interaction.guild_id, interaction.user.id, message, count))

    @app_commands.command(name="status", description="Read the latest broadcast report")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction):
        language = lang(self.bot.store, interaction.guild_id)
        run = self.state.latest(interaction.guild_id)
        if run is None:
            await reply(interaction, tr(language, "bc_no_runs"))
            return
        await reply(interaction, embed=report_embed(language, run, interaction.guild))

    @app_commands.command(name="count", description="Show the number of opted-in members")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def count(self, interaction: discord.Interaction):
        language = lang(self.bot.store, interaction.guild_id)
        await reply(interaction, tr(language, "bc_count", count=self.state.count(interaction.guild_id)))

    async def run_campaign(self, guild: discord.Guild, author_id: int, body: str, run_id: int):
        counts = dict(sent=0, blocked=0, failed=0, skipped=0)
        status = "completed"
        subscriber_ids = self.state.subscribers(guild.id)
        language = lang(self.bot.store, guild.id)
        try:
            for user_id in subscriber_ids:
                # A member may unsubscribe while the campaign is running.
                if not self.state.subscribed(guild.id, user_id):
                    counts["skipped"] += 1
                else:
                    try:
                        member = guild.get_member(user_id)
                        if member is None:
                            member = await guild.fetch_member(user_id)
                    except discord.NotFound:
                        self.state.unsubscribe(guild.id, user_id)
                        counts["skipped"] += 1
                    except discord.HTTPException:
                        counts["failed"] += 1
                    else:
                        if member.bot:
                            self.state.unsubscribe(guild.id, user_id)
                            counts["skipped"] += 1
                        elif not self.state.subscribed(guild.id, user_id):
                            counts["skipped"] += 1
                        else:
                            try:
                                embed = discord.Embed(
                                    title=f"📣 {guild.name[:170]}",
                                    description=body,
                                    color=discord.Color.from_rgb(82, 163, 214),
                                )
                                embed.set_footer(text=tr(language, "bc_dm_footer"))
                                await member.send(
                                    embed=embed,
                                    allowed_mentions=discord.AllowedMentions.none(),
                                )
                                counts["sent"] += 1
                            except discord.Forbidden:
                                counts["blocked"] += 1
                            except discord.HTTPException:
                                counts["failed"] += 1
                self.state.progress(run_id, **counts)
                await asyncio.sleep(DM_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            status = "interrupted"
            raise
        except Exception:
            status = "interrupted"
            logger.exception("Broadcast campaign %s interrupted", run_id)
        finally:
            self.state.finish(run_id, status=status, **counts)
            self.active_guilds.discard(guild.id)
            report = self.state.latest(guild.id)
            try:
                member = guild.get_member(author_id)
                recipient = member if member else await self.bot.fetch_user(author_id)
                await recipient.send(
                    embed=report_embed(language, report, guild),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.warning(
                    "Could not DM broadcast report %s to staff %s; /broadcast status is available",
                    run_id, author_id,
                )


class Announcements(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="announce", description="Post an announcement in a server channel")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def announce(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: app_commands.Range[str, 1, 1600],
    ):
        language = lang(self.bot.store, interaction.guild_id)
        bot_member = interaction.guild.me or await interaction.guild.fetch_member(self.bot.user.id)
        if not (channel.permissions_for(bot_member).view_channel
                and channel.permissions_for(bot_member).send_messages
                and channel.permissions_for(bot_member).embed_links):
            await reply(interaction, tr(language, "missing_bot"))
            return
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title=tr(language, "bc_announce_title"),
            description=message,
            color=discord.Color.from_rgb(82, 163, 214),
        )
        await channel.send(embed=decorate(embed, interaction.guild),
                           allowed_mentions=discord.AllowedMentions.none())
        await reply(interaction, tr(language, "bc_announce_done", channel=channel.mention))
        await log_action(interaction.guild, self.bot.store, "Announcement posted",
                         f"Channel {channel.id}; by {interaction.user.id}; chars {len(message)}")
