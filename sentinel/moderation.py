from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands

from .common import log_action, reply, role_error, target_error
from .i18n import lang


def bilingual(bot, interaction, en: str, ar: str) -> str:
    return ar if lang(bot.store, interaction.guild_id) == "ar" else en



def audit_reason(actor: discord.Member, reason: str) -> str:
    return f"By {actor} ({actor.id}): {(reason or 'No reason')[:350]}"[:512]


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def bot_member(self, guild: discord.Guild) -> discord.Member | None:
        return guild.me or await guild.fetch_member(self.bot.user.id)

    async def check_member(self, interaction: discord.Interaction, member: discord.Member,
                           *, for_timeout: bool = False) -> bool:
        me = await self.bot_member(interaction.guild)
        error = target_error(interaction.user, member, me, for_timeout=for_timeout)
        if error:
            await reply(interaction, error)
            return False
        return True

    @app_commands.command(description="Kick a member out of the server")
    @app_commands.guild_only()
    @app_commands.default_permissions(kick_members=True)
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.checks.bot_has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
        await interaction.response.defer(ephemeral=True)
        if not await self.check_member(interaction, member):
            return
        await member.kick(reason=audit_reason(interaction.user, reason))
        await reply(interaction, bilingual(self.bot, interaction,
            f"Kicked **{discord.utils.escape_markdown(str(member))}**.",
            f"تم طرد **{discord.utils.escape_markdown(str(member))}**."))
        await log_action(interaction.guild, self.bot.store, "Member kicked",
                         f"Member: {member} (`{member.id}`)\nBy: {interaction.user} (`{interaction.user.id}`)\nReason: {reason}")

    @app_commands.command(description="Ban a server member")
    @app_commands.guild_only()
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.describe(delete_hours="Past message history to delete: 0–168 hours")
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason",
                  delete_hours: app_commands.Range[int, 0, 168] = 0):
        await interaction.response.defer(ephemeral=True)
        if not await self.check_member(interaction, member):
            return
        await interaction.guild.ban(member, reason=audit_reason(interaction.user, reason),
                                    delete_message_seconds=delete_hours * 3600)
        await reply(interaction, bilingual(self.bot, interaction,
            f"Banned **{discord.utils.escape_markdown(str(member))}**.",
            f"تم حظر **{discord.utils.escape_markdown(str(member))}**."))
        await log_action(interaction.guild, self.bot.store, "Member banned",
                         f"Member: {member} (`{member.id}`)\nBy: {interaction.user}\nReason: {reason}")

    @app_commands.command(description="Unban a user using their numeric Discord ID")
    @app_commands.guild_only()
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason"):
        await interaction.response.defer(ephemeral=True)
        if not user_id.isdecimal() or not (1 <= int(user_id) < 2**64):
            await reply(interaction, bilingual(self.bot, interaction,
                        "Provide a valid numeric Discord User ID.", "اكتب User ID صحيح بالأرقام."))
            return
        user = discord.Object(id=int(user_id))
        try:
            await interaction.guild.unban(user, reason=audit_reason(interaction.user, reason))
        except discord.NotFound:
            await reply(interaction, bilingual(self.bot, interaction, "This user is not banned.", "العضو ده مش محظور."))
            return
        await reply(interaction, bilingual(self.bot, interaction,
            f"Unbanned user ID `{user_id}`.", f"تم فك الحظر عن `{user_id}`."))
        await log_action(interaction.guild, self.bot.store, "User unbanned",
                         f"User ID: `{user_id}`\nBy: {interaction.user}\nReason: {reason}")

    @app_commands.command(name="timeout", description="Temporarily prevent a member from chatting")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.describe(minutes="Timeout length in minutes, maximum 28 days")
    async def timeout_member(self, interaction: discord.Interaction, member: discord.Member,
                             minutes: app_commands.Range[int, 1, 40320], reason: str = "No reason"):
        await interaction.response.defer(ephemeral=True)
        if not await self.check_member(interaction, member, for_timeout=True):
            return
        await member.timeout(timedelta(minutes=minutes), reason=audit_reason(interaction.user, reason))
        await reply(interaction, bilingual(self.bot, interaction,
            f"Timed out **{discord.utils.escape_markdown(str(member))}** for **{minutes} minutes**.",
            f"تم عمل Timeout للعضو **{discord.utils.escape_markdown(str(member))}** لمدة **{minutes} دقيقة**."))
        await log_action(interaction.guild, self.bot.store, "Member timed out",
                         f"Member: {member} (`{member.id}`)\nBy: {interaction.user}\nDuration: {minutes} minutes\nReason: {reason}")

    @app_commands.command(description="Remove a member's timeout")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
        await interaction.response.defer(ephemeral=True)
        if not await self.check_member(interaction, member, for_timeout=True):
            return
        await member.timeout(None, reason=audit_reason(interaction.user, reason))
        await reply(interaction, bilingual(self.bot, interaction,
            f"Removed timeout from **{discord.utils.escape_markdown(str(member))}**.",
            f"تم إلغاء Timeout من **{discord.utils.escape_markdown(str(member))}**."))
        await log_action(interaction.guild, self.bot.store, "Timeout removed",
                         f"Member: {member} (`{member.id}`)\nBy: {interaction.user}\nReason: {reason}")

    @app_commands.command(description="Delete recent messages from the current channel")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
    @app_commands.describe(amount="Messages to delete, from 1 to 100")
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await reply(interaction, bilingual(self.bot, interaction, "This works only in text channels or threads.", "الأمر ده متاح في القنوات النصية بس."))
            return
        deleted = await channel.purge(limit=amount)
        await reply(interaction, bilingual(self.bot, interaction,
            f"Deleted **{len(deleted)}** messages from this channel.",
            f"تم حذف **{len(deleted)}** رسالة من القناة."))
        await log_action(interaction.guild, self.bot.store, "Messages deleted",
                         f"Channel: {channel.mention}\nBy: {interaction.user}\nCount: {len(deleted)}")


@app_commands.guild_only()
@app_commands.default_permissions(manage_roles=True)
class Roles(commands.GroupCog, group_name="role", group_description="Give and remove roles safely"):
    def __init__(self, bot):
        self.bot = bot

    async def validate(self, interaction, member, role):
        me = interaction.guild.me or await interaction.guild.fetch_member(self.bot.user.id)
        error = role_error(interaction.user, me, role)
        if not error:
            error = target_error(interaction.user, member, me)
        if error:
            await reply(interaction, error)
            return False
        return True

    @app_commands.command(description="Give a role to a member")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        if not await self.validate(interaction, member, role):
            return
        if role in member.roles:
            await reply(interaction, bilingual(self.bot, interaction, "This member already has that role.", "العضو عنده الرول دي بالفعل."))
            return
        await member.add_roles(role, reason=audit_reason(interaction.user, "Role added"))
        await reply(interaction, bilingual(self.bot, interaction,
            f"Added **{role.name}** to **{discord.utils.escape_markdown(str(member))}**.",
            f"تم إضافة **{role.name}** للعضو **{discord.utils.escape_markdown(str(member))}**."))
        await log_action(interaction.guild, self.bot.store, "Role added",
                         f"Role: {role.name} (`{role.id}`)\nMember: {member} (`{member.id}`)\nBy: {interaction.user}")

    @app_commands.command(description="Remove a role from a member")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def remove(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        if not await self.validate(interaction, member, role):
            return
        if role not in member.roles:
            await reply(interaction, bilingual(self.bot, interaction, "This member does not have that role.", "العضو معندوش الرول دي."))
            return
        await member.remove_roles(role, reason=audit_reason(interaction.user, "Role removed"))
        await reply(interaction, bilingual(self.bot, interaction,
            f"Removed **{role.name}** from **{discord.utils.escape_markdown(str(member))}**.",
            f"تم إزالة **{role.name}** من **{discord.utils.escape_markdown(str(member))}**."))
        await log_action(interaction.guild, self.bot.store, "Role removed",
                         f"Role: {role.name} (`{role.id}`)\nMember: {member} (`{member.id}`)\nBy: {interaction.user}")
