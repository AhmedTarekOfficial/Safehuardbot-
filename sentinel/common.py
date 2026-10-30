import discord
from discord import app_commands

from .i18n import tr


async def reply(interaction: discord.Interaction, content: str = None, *, embed=None, view=None):
    kwargs = {
        "ephemeral": True,
        "allowed_mentions": discord.AllowedMentions.none(),
    }
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view
    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)


def target_error(actor: discord.Member, target: discord.Member, bot: discord.Member,
                 *, for_timeout: bool = False, language: str = "en") -> str | None:
    """Mirror hierarchy safety for the invoker AND the bot."""
    guild = actor.guild
    if target.id == actor.id:
        return "مينفعش تنفذ الأمر على نفسك." if language == "ar" else "You cannot moderate yourself."
    if target.id == bot.id:
        return "البوت مينفعش ينفذ الأمر على نفسه." if language == "ar" else "I cannot moderate myself."
    if target.id == guild.owner_id:
        return "مينفعش تعاقب مالك السيرفر." if language == "ar" else "The server owner cannot be moderated."
    if actor.id != guild.owner_id and actor.top_role <= target.top_role:
        return "لازم أعلى رول عندك يكون أعلى من رول العضو." if language == "ar" else "Your highest role must be above the target's highest role."
    if bot.top_role <= target.top_role:
        return "لازم ترفع رول البوت فوق رول العضو." if language == "ar" else "Move my bot role above the target's highest role."
    if for_timeout and target.guild_permissions.administrator:
        return "مينفعش تعمل Timeout لعضو Administrator." if language == "ar" else "Discord does not permit timing out administrators."
    return None


def role_error(actor: discord.Member, bot: discord.Member, role: discord.Role, *, language: str = "en") -> str | None:
    if role.is_default() or role.managed:
        return "الرول دي تابعة لـ Discord أو @everyone ومينفعش تعديلها." if language == "ar" else "This role is managed by Discord/integrations or is @everyone."
    if bot.top_role <= role:
        return "ارفع رول البوت فوق الرول المطلوب." if language == "ar" else "Move my bot role above the role you want to manage."
    if actor.id != actor.guild.owner_id and actor.top_role <= role:
        return "مينفعش تدير رول أعلى من رولك أو مساوية ليه." if language == "ar" else "You cannot manage a role at or above your highest role."
    # Disallow using a more-privileged bot as an escalation path.
    rights = actor.guild_permissions
    if actor.id != actor.guild.owner_id and not rights.administrator:
        missing_bits = role.permissions.value & ~rights.value
        if missing_bits:
            return "الرول دي بتدي صلاحيات انت مش معاك." if language == "ar" else "This role grants permissions you do not have yourself."
    return None


async def log_action(guild: discord.Guild, store, title: str, detail: str):
    settings = store.get(guild.id)
    if not settings.log_channel_id:
        return
    channel = guild.get_channel(settings.log_channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    me = guild.me
    if me and not channel.permissions_for(me).send_messages:
        return
    embed = discord.Embed(
        title=title[:256],
        description=detail[:4000],
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow(),
    )
    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass


def permission_name(s: str) -> str:
    return s.replace("_", " ").title()


def permission_flags() -> list[str]:
    """Get supported boolean permission names from installed discord.py."""
    return sorted(name for name, enabled in discord.Permissions.none() if isinstance(enabled, bool))


async def require_guild_member(interaction: discord.Interaction) -> discord.Member | None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await reply(interaction, "This command is only available inside a server.")
        return None
    return interaction.user
