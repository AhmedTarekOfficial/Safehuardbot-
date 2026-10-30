import math
import discord
from discord import app_commands
from discord.ext import commands

from .common import permission_flags, permission_name, reply
from .i18n import tr, lang, decorate

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
        language = panel.language
        self.title = tr(language, "modal_title")
        self.search.label = tr(language, "modal_label")
        self.search.placeholder = "manage_roles, ban_members, send_messages"

    async def on_submit(self, interaction: discord.Interaction):
        if not await self.panel.can_use(interaction):
            return
        query = str(self.search.value).strip().lower().replace(" ", "_").replace("-", "_")
        names = permission_flags()
        exact = [n for n in names if n == query]
        matches = exact or [n for n in names if query in n]
        if not matches:
            await reply(interaction, tr(self.panel.language, "search_unknown", name=query))
            return
        if len(matches) > 1:
            options = ", ".join(f"`{n}`" for n in matches[:18])
            await reply(interaction, tr(self.panel.language, "search_many", names=options))
            return
        self.panel.mode = "search"
        self.panel.search_name = matches[0]
        self.panel.page = 0
        await interaction.response.edit_message(embed=self.panel.render(), view=self.panel)


class RolePicker(discord.ui.RoleSelect):
    def __init__(self, language="en"):
        super().__init__(placeholder=tr(language, "select_role"), min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction):
        panel: PermissionsView = self.view
        if not await panel.can_use(interaction):
            return
        selected = self.values[0]
        if not isinstance(selected, discord.Role) or selected.guild.id != panel.guild.id:
            await reply(interaction, tr(panel.language, "role_invalid"))
            return
        panel.mode = "role"
        panel.role_id = selected.id
        panel.page = 0
        await interaction.response.edit_message(embed=panel.render(), view=panel)


class PermissionsView(discord.ui.View):
    def __init__(self, guild: discord.Guild, opener_id: int, store=None):
        super().__init__(timeout=600)
        self.guild = guild
        self.opener_id = opener_id
        self.store = store
        self.mode = "overview"  # overview | role | search
        self.role_id: int | None = None
        self.search_name: str | None = None
        self.page = 0
        self.add_item(RolePicker(self.language))
        self._apply_labels()
        self._refresh_buttons()

    @property
    def language(self):
        return lang(self.store, self.guild.id) if self.store else "en"

    def _apply_labels(self):
        language = self.language
        self.all_roles.label = tr(language, "all_roles")
        self.search.label = tr(language, "search_perm")
        self.previous.label = tr(language, "previous")
        self.next_page.label = tr(language, "next")

    async def can_use(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opener_id:
            await reply(interaction, tr(self.language, "private"))
            return False
        if interaction.guild_id != self.guild.id or not isinstance(interaction.user, discord.Member):
            await reply(interaction, "This panel works only in its original server.")
            return False
        if not interaction.user.guild_permissions.manage_guild:
            await reply(interaction, tr(self.language, "lang_need"))
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
        self._apply_labels()
        language = self.language
        items = self._items()
        pages = max(1, math.ceil(len(items) / ITEMS_PER_PAGE))
        chunk = items[self.page * ITEMS_PER_PAGE:(self.page + 1) * ITEMS_PER_PAGE]
        embed = discord.Embed(color=discord.Color.from_rgb(106, 87, 233))

        if self.mode == "role":
            role = self.guild.get_role(self.role_id or 0)
            if role is None:
                self.mode, self.page = "overview", 0
                return self.render()
            enabled = sum(1 for _, value in role.permissions if value)
            rows = [
                f"{'🟢' if getattr(role.permissions, key) else '⚫'} **{permission_name(key)}** · `{key}`"
                for key in chunk
            ]
            embed.title = tr(language, "perm_role", name=discord.utils.escape_markdown(role.name[:170]))
            embed.description = tr(
                language, "perm_role_intro", id=role.id, count=enabled,
                rows="\n".join(rows) if rows else tr(language, "none"),
            )
            embed.add_field(name="▰" * min(10, round(enabled / max(1, len(items)) * 10)) +
                            "▱" * (10 - min(10, round(enabled / max(1, len(items)) * 10))),
                            value=f"{enabled}/{len(items)}", inline=False)
        elif self.mode == "search":
            rows = [
                f"{i + self.page * ITEMS_PER_PAGE + 1:02d}  {role.mention}  ·  "
                f"{tr(language, 'admin' if inherited else 'direct')}"
                for i, (role, inherited) in enumerate(chunk)
            ]
            embed.title = tr(language, "perm_search", name=self.search_name)
            embed.description = tr(
                language, "perm_search_intro", count=len(items),
                rows="\n".join(rows) if rows else tr(language, "none"),
            )
        else:
            rows = []
            for role in chunk:
                count = sum(1 for _, enabled in role.permissions if enabled)
                rows.append(
                    f"{role.mention}   **{count}** ✓" +
                    ("  ·  ⭐ ADMIN" if role.permissions.administrator else "")
                )
            embed.title = tr(language, "perm_title")
            embed.description = (
                tr(language, "perm_overview", count=len(items)) +
                "\n\n━━━━━━━━━━━━━━━━━━━━\n" +
                ("\n".join(rows) if rows else tr(language, "none"))
            )
        return decorate(
            embed, self.guild,
            footer=tr(language, "page", page=self.page + 1, total=pages),
        )

    @discord.ui.button(label="All Roles", emoji="🎭", style=discord.ButtonStyle.secondary, row=1)
    async def all_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "overview"
        self.page = 0
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(label="Search Permission", emoji="🔍", style=discord.ButtonStyle.primary, row=1)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PermissionSearch(self))

    @discord.ui.button(label="Previous", emoji="◀️", style=discord.ButtonStyle.secondary, row=2)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(label="Next", emoji="▶️", style=discord.ButtonStyle.secondary, row=2)
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
        panel = PermissionsView(interaction.guild, interaction.user.id, self.bot.store)
        await reply(interaction, embed=panel.render(), view=panel)
