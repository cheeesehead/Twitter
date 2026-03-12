import discord
from discord import app_commands
import logging

from bot.config import DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, DISCORD_APPROVALS_CHANNEL_ID
from bot.twitter.rate_limiter import budget_remaining
from bot.content.generator import generate_tweets_from_idea, generate_quote_tweets
from bot.discord_bot.channels import send_draft_for_approval
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

    @bot.tree.command(name="suggest", description="Suggest a tweet idea for Claude to write")
    @app_commands.describe(idea="Your tweet idea or topic")
    async def suggest_cmd(interaction: discord.Interaction, idea: str):
        await interaction.response.defer(ephemeral=True)
        tweets = await generate_tweets_from_idea(idea)
        if not tweets:
            await interaction.followup.send("Claude couldn't generate tweets from that. Try again?", ephemeral=True)
            return

        for tweet_text in tweets:
            draft_id = await db.insert_draft({
                "event_id": None,
                "tweet_text": tweet_text,
                "status": "pending",
                "discord_message_id": None,
            })
            await db.increment_stat("drafts_created")

            msg = await send_draft_for_approval(
                bot,
                draft_id=draft_id,
                tweet_text=tweet_text,
                event_type="suggestion",
                event_description=f"User idea: {idea}",
                on_approve=bot.on_approve,
                on_reject=bot.on_reject,
            )
            if msg:
                bot.draft_messages[draft_id] = msg
                await db.update_draft(draft_id, discord_message_id=str(msg.id))

        await interaction.followup.send(f"Generated {len(tweets)} tweet(s) — check #approvals!", ephemeral=True)

    @bot.tree.command(name="quote", description="Generate a quote tweet reaction")
    @app_commands.describe(
        tweet="The tweet text or URL you want to quote tweet",
        context="Optional extra context (e.g. 'this is about the Sixers trade')",
    )
    async def quote_cmd(interaction: discord.Interaction, tweet: str, context: str = ""):
        await interaction.response.defer(ephemeral=True)
        tweets = await generate_quote_tweets(tweet, context)
        if not tweets:
            await interaction.followup.send("Couldn't generate a take on that. Try again?", ephemeral=True)
            return

        for tweet_text in tweets:
            draft_id = await db.insert_draft({
                "event_id": None,
                "tweet_text": tweet_text,
                "status": "pending",
                "discord_message_id": None,
            })
            await db.increment_stat("drafts_created")

            msg = await send_draft_for_approval(
                bot,
                draft_id=draft_id,
                tweet_text=tweet_text,
                event_type="quote_tweet",
                event_description=f"Quote: {tweet[:100]}",
                on_approve=bot.on_approve,
                on_reject=bot.on_reject,
            )
            if msg:
                bot.draft_messages[draft_id] = msg
                await db.update_draft(draft_id, discord_message_id=str(msg.id))

        await interaction.followup.send(f"Generated {len(tweets)} quote tweet(s) — check #approvals!", ephemeral=True)

    return bot
