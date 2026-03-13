import asyncio

import discord
from discord import app_commands
import logging

from bot.config import DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, DISCORD_APPROVALS_CHANNEL_ID
from bot.twitter.rate_limiter import budget_remaining
from bot.twitter.tweet_fetcher import is_tweet_url, fetch_tweet_content, format_tweet_content, extract_tweet_id
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

        for tweet_dict in tweets:
            tweet_text = tweet_dict["text"]
            meme_id = tweet_dict.get("meme_id")
            article_url = tweet_dict.get("article_url")

            draft_id = await db.insert_draft({
                "event_id": None,
                "tweet_text": tweet_text,
                "status": "pending",
                "discord_message_id": None,
                "meme_id": meme_id,
                "article_url": article_url,
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
                on_revise=bot.on_revise,
                meme_id=meme_id,
                article_url=article_url,
            )
            if msg:
                bot.draft_messages[draft_id] = msg
                await db.update_draft(draft_id, discord_message_id=str(msg.id))

        await interaction.followup.send(f"Generated {len(tweets)} tweet(s) — check #approvals!", ephemeral=True)

    class LearnModal(discord.ui.Modal, title="Learn from a tweet"):
        tweet_input = discord.ui.TextInput(
            label="Tweet URL or text",
            style=discord.TextStyle.long,
            placeholder="Paste a tweet URL or the full tweet text (line breaks OK)",
            required=True,
            max_length=2000,
        )

        async def on_submit(self, interaction: discord.Interaction):
            try:
                await _save_style_reference(interaction, self.tweet_input.value)
            except Exception:
                log.exception("Error in /learn modal")
                if interaction.response.is_done():
                    await interaction.followup.send("Something went wrong. Try again.", ephemeral=True)
                else:
                    await interaction.response.send_message("Something went wrong. Try again.", ephemeral=True)

    async def _save_style_reference(interaction: discord.Interaction, tweet: str):
        """Shared logic for saving a style reference from a URL or text."""
        source_url = None
        content = tweet

        if is_tweet_url(tweet.strip()):
            session = getattr(bot, "http_session", None)
            if not session:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "Bot HTTP session not available. Try again in a moment.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "Bot HTTP session not available. Try again in a moment.",
                        ephemeral=True,
                    )
                return

            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            tweet_data = await fetch_tweet_content(tweet.strip(), session)
            if not tweet_data:
                await interaction.followup.send(
                    "Couldn't fetch that tweet. Check the URL and try again.",
                    ephemeral=True,
                )
                return

            content = format_tweet_content(tweet_data)
            source_url = tweet.strip()

        ref_id = await db.insert_style_reference(
            content=content,
            source_url=source_url,
            added_by=str(interaction.user),
        )
        count = await db.get_style_reference_count()

        msg = f"Saved style reference #{ref_id} ({count} total):\n> {content[:300]}"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        log.info("Style reference #%d added by %s", ref_id, interaction.user)

    @bot.tree.command(name="learn", description="Save a tweet or text as a style reference for Claude")
    @app_commands.describe(input="Tweet URL or text to learn from (skips the popup)")
    async def learn_cmd(interaction: discord.Interaction, input: str | None = None):
        if input:
            await interaction.response.defer(ephemeral=True)
            try:
                await _save_style_reference(interaction, input)
            except Exception:
                log.exception("Error in /learn command")
                await interaction.followup.send("Something went wrong. Try again.", ephemeral=True)
        else:
            await interaction.response.send_modal(LearnModal())

    class LearnBulkModal(discord.ui.Modal, title="Bulk import tweets"):
        urls_input = discord.ui.TextInput(
            label="Tweet URLs (one per line)",
            style=discord.TextStyle.long,
            placeholder="https://x.com/MikeBeauvais/status/123456789\nhttps://x.com/MikeBeauvais/status/987654321",
            required=True,
            max_length=4000,
        )

        async def on_submit(self, interaction: discord.Interaction):
            try:
                await _save_bulk_style_references(interaction, self.urls_input.value)
            except Exception:
                log.exception("Error in /learn-bulk modal")
                if interaction.response.is_done():
                    await interaction.followup.send("Something went wrong. Try again.", ephemeral=True)
                else:
                    await interaction.response.send_message("Something went wrong. Try again.", ephemeral=True)

    async def _save_bulk_style_references(interaction: discord.Interaction, raw_input: str):
        """Parse multiple tweet URLs and save each as a style reference."""
        await interaction.response.defer(ephemeral=True)

        session = getattr(bot, "http_session", None)
        if not session:
            await interaction.followup.send(
                "Bot HTTP session not available. Try again in a moment.", ephemeral=True
            )
            return

        # Parse URLs from input (split on whitespace/newlines)
        urls = [token.strip() for token in raw_input.split() if is_tweet_url(token.strip())]

        if not urls:
            await interaction.followup.send(
                "No valid tweet URLs found. Paste URLs like:\nhttps://x.com/user/status/123456",
                ephemeral=True,
            )
            return

        saved = 0
        skipped = 0
        failed = 0
        previews = []

        for url in urls:
            tweet_id = extract_tweet_id(url)
            if not tweet_id:
                failed += 1
                continue

            if await db.style_reference_exists_by_tweet_id(tweet_id):
                skipped += 1
                continue

            tweet_data = await fetch_tweet_content(url, session)
            if not tweet_data:
                failed += 1
                previews.append(f"Failed: {url}")
                continue

            content = format_tweet_content(tweet_data)
            ref_id = await db.insert_style_reference(
                content=content,
                source_url=url,
                added_by=str(interaction.user),
            )
            saved += 1
            previews.append(f"#{ref_id}: {content[:80]}")

            await asyncio.sleep(0.5)

        count = await db.get_style_reference_count()
        summary = f"**Bulk import complete** ({count} total references)\n"
        summary += f"Saved: {saved} | Skipped (duplicate): {skipped} | Failed: {failed}"
        if previews:
            summary += "\n\n" + "\n".join(previews[:20])

        await interaction.followup.send(summary, ephemeral=True)
        log.info("Bulk import by %s: %d saved, %d skipped, %d failed", interaction.user, saved, skipped, failed)

    @bot.tree.command(name="learn-bulk", description="Import multiple tweets as style references at once")
    async def learn_bulk_cmd(interaction: discord.Interaction):
        await interaction.response.send_modal(LearnBulkModal())

    @bot.tree.command(name="references", description="View or manage saved style references")
    @app_commands.describe(action="What to do", ref_id="Reference ID (for delete)")
    @app_commands.choices(action=[
        app_commands.Choice(name="list", value="list"),
        app_commands.Choice(name="delete", value="delete"),
        app_commands.Choice(name="count", value="count"),
    ])
    async def references_cmd(interaction: discord.Interaction, action: str = "list", ref_id: int = 0):
        if action == "count":
            count = await db.get_style_reference_count()
            await interaction.response.send_message(f"You have **{count}** style references saved.", ephemeral=True)
        elif action == "delete":
            if ref_id <= 0:
                await interaction.response.send_message("Provide a ref_id to delete.", ephemeral=True)
                return
            await db.delete_style_reference(ref_id)
            await interaction.response.send_message(f"Deleted style reference #{ref_id}.", ephemeral=True)
            log.info("Style reference #%d deleted by %s", ref_id, interaction.user)
        else:
            refs = await db.get_style_references(limit=20)
            if not refs:
                await interaction.response.send_message("No style references saved yet. Use `/learn` to add some!", ephemeral=True)
                return
            lines = []
            for ref in refs:
                preview = ref["content"][:80] + ("..." if len(ref["content"]) > 80 else "")
                lines.append(f"**#{ref['id']}** — {preview}")
            await interaction.response.send_message("\n".join(lines), ephemeral=True)

    class QuoteModal(discord.ui.Modal, title="Quote tweet"):
        tweet_input = discord.ui.TextInput(
            label="Tweet URL or text",
            style=discord.TextStyle.long,
            placeholder="Paste a tweet URL or the full tweet text (line breaks OK)",
            required=True,
            max_length=2000,
        )
        context_input = discord.ui.TextInput(
            label="Context (optional)",
            style=discord.TextStyle.short,
            placeholder="e.g. 'this is about the Sixers trade'",
            required=False,
            max_length=200,
        )

        async def on_submit(self, interaction: discord.Interaction):
            try:
                tweet = self.tweet_input.value
                context = self.context_input.value or ""
                source_text = tweet

                # If it's a URL, fetch the actual tweet content (including any quoted tweet)
                if is_tweet_url(tweet.strip()):
                    session = getattr(bot, "http_session", None)
                    if not session:
                        await interaction.response.send_message(
                            "Bot HTTP session not available. Try again in a moment.",
                            ephemeral=True,
                        )
                        return

                    await interaction.response.defer(ephemeral=True)
                    tweet_data = await fetch_tweet_content(tweet.strip(), session)
                    if not tweet_data:
                        await interaction.followup.send(
                            "Couldn't fetch that tweet. Check the URL and try again.",
                            ephemeral=True,
                        )
                        return

                    source_text = format_tweet_content(tweet_data)
                else:
                    await interaction.response.defer(ephemeral=True)

                tweets = await generate_quote_tweets(source_text, context)
                if not tweets:
                    await interaction.followup.send("Couldn't generate a take on that. Try again?", ephemeral=True)
                    return

                for tweet_dict in tweets:
                    tweet_text = tweet_dict["text"]
                    meme_id = tweet_dict.get("meme_id")
                    article_url = tweet_dict.get("article_url")

                    draft_id = await db.insert_draft({
                        "event_id": None,
                        "tweet_text": tweet_text,
                        "status": "pending",
                        "discord_message_id": None,
                        "meme_id": meme_id,
                        "article_url": article_url,
                    })
                    await db.increment_stat("drafts_created")

                    msg = await send_draft_for_approval(
                        bot,
                        draft_id=draft_id,
                        tweet_text=tweet_text,
                        event_type="quote_tweet",
                        event_description=f"Quote: {source_text[:100]}",
                        on_approve=bot.on_approve,
                        on_reject=bot.on_reject,
                        on_revise=bot.on_revise,
                        meme_id=meme_id,
                        article_url=article_url,
                    )
                    if msg:
                        bot.draft_messages[draft_id] = msg
                        await db.update_draft(draft_id, discord_message_id=str(msg.id))

                await interaction.followup.send(f"Generated {len(tweets)} quote tweet(s) — check #approvals!", ephemeral=True)
            except Exception:
                log.exception("Error in /quote command")
                if interaction.response.is_done():
                    await interaction.followup.send("Something went wrong. Try again.", ephemeral=True)
                else:
                    await interaction.response.send_message("Something went wrong. Try again.", ephemeral=True)

    @bot.tree.command(name="quote", description="Generate a quote tweet reaction")
    async def quote_cmd(interaction: discord.Interaction):
        await interaction.response.send_modal(QuoteModal())

    return bot
