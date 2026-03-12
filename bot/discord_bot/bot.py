import discord
from discord import app_commands
import logging

from bot.config import DISCORD_BOT_TOKEN, DISCORD_GUILD_ID
from bot.twitter.rate_limiter import budget_remaining
from bot import database as db

log = logging.getLogger(__name__)


class SportsBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.paused = False

    async def setup_hook(self):
        guild = discord.Object(id=DISCORD_GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.info("Slash commands synced to guild %d", DISCORD_GUILD_ID)

    async def on_ready(self):
        log.info("Discord bot connected as %s", self.user)


def create_bot() -> SportsBot:
    bot = SportsBot()

    @bot.tree.command(name="status", description="Show bot status and tweet budget")
    async def status_cmd(interaction: discord.Interaction):
        budget = await budget_remaining()
        pending = await db.get_pending_drafts()
        await interaction.response.send_message(
            f"**Sports Bot Status**\n"
            f"Paused: {bot.paused}\n"
            f"Pending drafts: {len(pending)}\n"
            f"Daily budget: {budget['daily_remaining']}/{budget['daily_limit']}\n"
            f"Monthly budget: {budget['monthly_remaining']}/{budget['monthly_limit']}",
            ephemeral=True,
        )

    @bot.tree.command(name="pause", description="Pause/unpause the bot")
    async def pause_cmd(interaction: discord.Interaction):
        bot.paused = not bot.paused
        state = "PAUSED" if bot.paused else "RUNNING"
        await interaction.response.send_message(f"Bot is now **{state}**", ephemeral=True)
        log.info("Bot %s by %s", state, interaction.user)

    return bot
