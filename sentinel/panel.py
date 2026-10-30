import math
import discord
from discord import app_commands
from discord.ext import commands

from .common import permission_flags, permission_name, reply

ITEMS_PER_PAGE = 9


class PermissionSearch(discord.ui.Modal, title="Search for a permission"):
    search = discord.ui.TextInput(
        label="Permission name",
        placeholder="e.g. manage_roles, ban_members, send_messages",
        required=True,
        max_length=80,
    )

    def __init__(self, panel: "PermissionsView"):
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction):
        if not await self.panel.can_use(interaction):
            return
        query = str(self.search.value).strip().lower().replace(" ", "_").replace("-", "_")
        names = permission_flags()
        exact = [n for n in names if n == query]
        matches = exact or [n for n in names if query in n]
        if not matches:
            await reply(interaction, f"No permission named `{query}`. Try `manage_roles`.")
            return
        if len(matches) > 1:
            options = ", ".join(f"`{n}`" for n in matches[:18])
            await reply(interaction, f"Multiple matches. Search with the exact name:\n{options}")
            return
        self.panel.mode = "search"
        self.panel.search_name = matches[0]
        self.panel.page = 0
        await interaction.response.edit_message(embed=self.panel.render(), view=self.panel)


class RolePicker(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="Choose a role to inspect its permissions", min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction):
        panel: PermissionsView = self.view
        if not await panel.can_use(interaction):
            return
        selected = self.values[0]
        if not isinstance(selected, discord.Role) or selected.guild.id != panel.guild.id:
            await reply(interaction, "Please select a role from this server.")
            return
        panel.mode = "role"
        panel.role_id = selected.id
        panel.page = 0
        await interaction.response.edit_message(embed=panel.render(), view=panel)


class PermissionsView(discord.ui.View):
    def __init__(self, guild: discord.Guild, opener_id: int):
        super().__init__(timeout=600)
        self.guild = guild
        self.opener_id = opener_id
        self.mode = "overview"  # overview | role | search
        self.role_id: int | None = None
        self.search_name: str | None = None
        self.page = 0
        self.add_item(RolePicker())
        self._refresh_buttons()

    async def can_use(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opener_id:
            await reply(interaction, "Only the person who opened this private panel can use it.")
            return False
        if interaction.guild_id != self.guild.id or not isinstance(interaction.user, discord.Member):
            await reply(interaction, "This panel works only in its original server.")
            return False
        if not interaction.user.guild_permissions.manage_guild:
            await reply(interaction, "You need Manage Server to inspect roles here.")
            return False
        return True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.can_use(interaction)

    def _roles(self):
        return sorted(self.guild.roles, key=lambda role: role.position, reverse=True)

    def _search_roles(self):
        if not self.search_name:
            return []
        permission = self.search_name
        matches = []
        for role in self._roles():
            explicitly = bool(getattr(role.permissions, permission, False))
            inherited = role.permissions.administrator and permission != "administrator" and not explicitly
            if explicitly or inherited:
                matches.append((role, inherited))
        return matches

    def _items(self):
        if self.mode == "role":
            return permission_flags()
        if self.mode == "search":
            return self._search_roles()
        return self._roles()

    def _refresh_buttons(self):
        page_count = max(1, math.ceil(len(self._items()) / ITEMS_PER_PAGE))
        self.page = min(self.page, page_count - 1)
        self.previous.disabled = self.page <= 0
        self.next_page.disabled = self.page >= page_count - 1

    def render(self) -> discord.Embed:
        self._refresh_buttons()
        items = self._items()
        page_count = max(1, math.ceil(len(items) / ITEMS_PER_PAGE))
        chunk = items[self.page * ITEMS_PER_PAGE:(self.page + 1) * ITEMS_PER_PAGE]
        embed = discord.Embed(color=discord.Color.blurple())

        if self.mode == "role":
            role = self.guild.get_role(self.role_id or 0)
            if role is None:
                self.mode = "overview"
                self.page = 0
                return self.render()
            active = sum(1 for _, value in role.permissions if value)
            embed.title = f"Role permissions: {role.name[:180]}"
            embed.description = (
                f"Role ID: `{role.id}` | Explicitly enabled: **{active}**\n"
                "These are raw role flags. `Administrator` bypasses most permission checks. "
                "Other roles and channel overrides can change a member's effective permissions.\n\n"
                + "\n".join(
                    f"{'✅' if getattr(role.permissions, key) else '❌'} "
                    f"**{permission_name(key)}** (`{key}`)" for key in chunk
                )
            )
        elif self.mode == "search":
            embed.title = f"Permission search: {self.search_name}"
            embed.description = (
                f"**{len(items)}** role(s) have this permission, directly or through Administrator.\n"
                "This checks server role flags only, not channel overrides.\n\n"
                + ("\n".join(
                    f"{i + self.page * ITEMS_PER_PAGE + 1}. {role.mention} — "
                    f"{'via Administrator' if inherited else 'direct permission'}"
                    for i, (role, inherited) in enumerate(chunk)
                ) if chunk else "No roles have this permission.")
            )
        else:
            embed.title = f"Permissions Dashboard — {self.guild.name[:150]}"
            embed.description = (
                f"**{len(items)}** role(s). Choose any role above, or search for a permission.\n"
                "Counts below show directly enabled role flags, not combined/effective permissions.\n\n"
                + "\n".join(
                    f"{role.mention} — **{sum(1 for _, enabled in role.permissions if enabled)}** enabled"
                    + (" **[ADMIN]**" if role.permissions.administrator else "")
                    for role in chunk
                )
            )
        embed.set_footer(text=f"Page {self.page + 1}/{page_count} • Private panel • Expires after 10 minutes")
        return embed

    @discord.ui.button(label="All Roles", style=discord.ButtonStyle.secondary, row=1)
    async def all_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "overview"
        self.page = 0
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(label="Search Permission", style=discord.ButtonStyle.primary, row=1)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PermissionSearch(self))

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, row=2)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, row=2)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await interaction.response.edit_message(embed=self.render(), view=self)


class PermissionsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="permissions", description="Open a role permissions dashboard with search and paging")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def permissions(self, interaction: discord.Interaction):
        panel = PermissionsView(interaction.guild, interaction.user.id)
        await reply(interaction, embed=panel.render(), view=panel)
