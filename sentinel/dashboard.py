"""Private, themed and bilingual help and language-switching dashboards."""
import discord
from discord import app_commands

from .common import reply
from .i18n import tr, lang, decorate


class HelpView(discord.ui.View):
    def __init__(self, bot, guild, opener_id: int):
        super().__init__(timeout=600)
        self.bot, self.guild, self.opener_id = bot, guild, opener_id
        self.section = "overview"
        self.apply_labels()

    def apply_labels(self):
        language = lang(self.bot.store, self.guild.id)
        for key, button in (
            ("overview", self.home_button), ("moderation", self.moderation_button),
            ("protection", self.protection_button), ("roles", self.roles_button),
            ("shortcuts", self.shortcuts_button), ("language", self.language_button),
            ("broadcast", self.broadcast_button),
        ):
            button.label = tr(language, key)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opener_id:
            await reply(interaction, tr(lang(self.bot.store, self.guild.id), "private"))
            return False
        return True

    def render(self):
        language = lang(self.bot.store, self.guild.id)
        content = tr(language, f"{self.section}_text") if self.section != "overview" else tr(language, "overview_text")
        current = self.bot.store.get(self.guild.id)
        shield = sum([current.antispam, current.links, current.raid])
        embed = discord.Embed(
            title=tr(language, "home"),
            description=f"{tr(language, 'welcome')}\n\n━━━━━━━━━━━━━━━━━━━━\n{content}",
            color=discord.Color.from_rgb(68, 112, 238),
        )
        embed.add_field(name="🛡️ Shield", value=f"`{shield}/3`", inline=True)
        embed.add_field(name="🌐 UI", value="العربية" if language == "ar" else "English", inline=True)
        embed.add_field(name="⚡ Quick Actions", value=str(len(self.bot.store.shortcuts_for(self.guild.id))), inline=True)
        broadcast = self.bot.get_cog("Broadcast")
        if broadcast is not None:
            embed.add_field(name="📬 Subscribers", value=str(broadcast.state.count(self.guild.id)), inline=True)
        return decorate(embed, self.guild, footer=tr(language, "footer"))

    async def change(self, interaction, section: str):
        self.section = section
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(label="Overview", emoji="🏠", style=discord.ButtonStyle.primary, row=0)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.change(interaction, "overview")

    @discord.ui.button(label="Moderation", emoji="⚖️", style=discord.ButtonStyle.secondary, row=0)
    async def moderation_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.change(interaction, "moderation")

    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.secondary, row=0)
    async def protection_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.change(interaction, "protection")

    @discord.ui.button(label="Roles", emoji="🎭", style=discord.ButtonStyle.secondary, row=1)
    async def roles_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.change(interaction, "roles")

    @discord.ui.button(label="Shortcuts", emoji="⚡", style=discord.ButtonStyle.secondary, row=1)
    async def shortcuts_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.change(interaction, "shortcuts")

    @discord.ui.button(label="Language", emoji="🌐", style=discord.ButtonStyle.success, row=1)
    async def language_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await reply(interaction, tr(lang(self.bot.store, self.guild.id), "lang_need"))
            return
        panel = LanguageView(self.bot, self.guild, self.opener_id)
        await interaction.response.send_message(embed=panel.render(), view=panel, ephemeral=True)

    @discord.ui.button(label="Broadcast", emoji="📬", style=discord.ButtonStyle.secondary, row=2)
    async def broadcast_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.change(interaction, "broadcast")


class LanguageSelect(discord.ui.Select):
    def __init__(self, current: str):
        super().__init__(
            placeholder="Choose language / اختار اللغة",
            options=[
                discord.SelectOption(label="English", value="en", emoji="🌐", default=current == "en"),
                discord.SelectOption(label="العربية", value="ar", emoji="🌐", default=current == "ar"),
            ],
            min_values=1, max_values=1, row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        panel: LanguageView = self.view
        if interaction.user.id != panel.opener_id or not interaction.user.guild_permissions.manage_guild:
            await reply(interaction, tr(lang(panel.bot.store, panel.guild.id), "lang_need"))
            return
        panel.bot.store.update(panel.guild.id, language=self.values[0])
        panel.clear_items()
        panel.add_item(LanguageSelect(self.values[0]))
        await interaction.response.edit_message(embed=panel.render(), view=panel)


class LanguageView(discord.ui.View):
    def __init__(self, bot, guild, opener_id: int):
        super().__init__(timeout=600)
        self.bot, self.guild, self.opener_id = bot, guild, opener_id
        self.add_item(LanguageSelect(lang(bot.store, guild.id)))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        language = lang(self.bot.store, self.guild.id)
        if interaction.user.id != self.opener_id:
            await reply(interaction, tr(language, "private"))
            return False
        if not interaction.user.guild_permissions.manage_guild:
            await reply(interaction, tr(language, "lang_need"))
            return False
        return True

    def render(self):
        language = lang(self.bot.store, self.guild.id)
        embed = discord.Embed(
            title=tr(language, "lang_title"),
            description=tr(language, "lang_desc") + "\n\n━━━━━━━━━━━━━━━━━━━━\n🇬🇧 English       |       🇪🇬 العربية",
            color=discord.Color.from_rgb(81, 170, 221),
        )
        return decorate(embed, self.guild, footer=tr(language, "footer"))
