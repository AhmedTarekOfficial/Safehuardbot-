import discord
from discord import app_commands


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
                 *, for_timeout: bool = False) -> str | None:
    """Mirror hierarchy safety for the invoker AND the bot."""
    guild = actor.guild
    if target.id == actor.id:
        return "You cannot moderate yourself."
    if target.id == bot.id:
        return "I cannot moderate myself."
    if target.id == guild.owner_id:
        return "The server owner cannot be moderated."
    if actor.id != guild.owner_id and actor.top_role <= target.top_role:
        return "Your highest role must be above the target's highest role."
    if bot.top_role <= target.top_role:
        return "Move my bot role above the target's highest role."
    if for_timeout and target.guild_permissions.administrator:
        return "Discord does not permit timing out administrators."
    return None


def role_error(actor: discord.Member, bot: discord.Member, role: discord.Role) -> str | None:
    if role.is_default() or role.managed:
        return "This role is managed by Discord/integrations or is @everyone."
    if bot.top_role <= role:
        return "Move my bot role above the role you want to manage."
    if actor.id != actor.guild.owner_id and actor.top_role <= role:
        return "You cannot manage a role at or above your highest role."
    # Disallow using a more-privileged bot as an escalation path.
    rights = actor.guild_permissions
    if actor.id != actor.guild.owner_id and not rights.administrator:
        missing_bits = role.permissions.value & ~rights.value
        if missing_bits:
            return "This role grants permissions you do not have yourself."
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
