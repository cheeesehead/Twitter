import asyncio
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

from bot import database as db
from bot.config import (
    DISCORD_BOT_TOKEN, EVENT_SCORE_THRESHOLD,
    FEED_ACTIVE_START, FEED_ACTIVE_END, TIMEZONE,
)
from bot.sports.season_manager import create_monitors
from bot.sports.scheduler import SportsScheduler
from bot.sports.base import SportEvent
from bot.content.event_scorer import filter_events
from bot.content.generator import generate_tweets, generate_tweets_from_news
from bot.discord_bot.bot import create_bot
from bot.discord_bot.channels import (
    send_draft_for_approval, send_log, update_approval_message, mark_rejected,
)
from bot.twitter.client import create_twitter_client, post_tweet
from bot.twitter.rate_limiter import can_tweet
from bot.feeds.espn_news import poll_espn_news
from bot.feeds.rss_reader import poll_rss_feeds

log = logging.getLogger(__name__)


class SportsBotApp:
    def __init__(self, test_mode: bool = False):
        self.test_mode = test_mode
        self.discord_bot = create_bot()
        self.twitter_client = None if test_mode else create_twitter_client()
        self.monitors = create_monitors()
        self.scheduler = SportsScheduler(self.monitors, self._on_events)
        # Map draft_id -> discord message for updating after approve/reject
        self._draft_messages: dict[int, object] = {}
        # Expose approve/reject handlers and draft map on the bot for /suggest
        self.discord_bot.on_approve = self._handle_approve
        self.discord_bot.on_reject = self._handle_reject
        self.discord_bot.draft_messages = self._draft_messages

    async def start(self):
        await db.init_db()

        active = [m.sport_key for m in self.monitors]
        log.info("Active sports: %s", active)
        if not active:
            log.warning("No sports are currently in season! Bot will poll but find no games.")

        # Create shared aiohttp session for feed polling and tweet fetching
        self._http_session = aiohttp.ClientSession()
        self.discord_bot.http_session = self._http_session

        # Register news/RSS feed polling jobs
        self.scheduler.register_feed("feed_espn_news", self._poll_espn_news)
        self.scheduler.register_feed("feed_rss", self._poll_rss_feeds)

        self.scheduler.start()
        log.info("News and RSS feed polling registered")

        # Run Discord bot (this blocks until bot shuts down)
        await self.discord_bot.start(DISCORD_BOT_TOKEN)

    async def shutdown(self):
        self.scheduler.stop()
        for monitor in self.monitors:
            if hasattr(monitor, "close"):
                await monitor.close()
        if hasattr(self, "_http_session") and self._http_session:
            await self._http_session.close()
        await self.discord_bot.close()

    async def _on_events(self, events: list[SportEvent]):
        if self.discord_bot.paused:
            log.info("Bot is paused, ignoring %d events", len(events))
            return

        # Score and filter
        worthy = filter_events(events, threshold=EVENT_SCORE_THRESHOLD)
        if not worthy:
            return

        log.info("Processing %d worthy events (of %d total)", len(worthy), len(events))

        for event in worthy:
            try:
                await self._process_event(event)
            except Exception:
                log.exception("Error processing event: %s", event.description)

    async def _process_event(self, event: SportEvent):
        # Save event to DB
        event_id = await db.insert_event(event.to_db_dict())
        await db.upsert_game({
            "id": event.game_id, "sport": event.data.get("sport", ""),
            "home_team": event.data.get("home_team", ""),
            "away_team": event.data.get("away_team", ""),
            "home_score": event.data.get("home_score", 0),
            "away_score": event.data.get("away_score", 0),
            "status": event.data.get("status", ""),
            "period": event.data.get("period", ""),
            "clock": event.data.get("clock", ""),
            "start_time": "", "last_updated": "",
        })

        # Generate tweets
        tweets = await generate_tweets(event)
        if not tweets:
            log.warning("No tweets generated for event: %s", event.description)
            return

        # Send each tweet option to Discord for approval
        for tweet_text in tweets:
            draft_id = await db.insert_draft({
                "event_id": event_id,
                "tweet_text": tweet_text,
                "status": "pending",
                "discord_message_id": None,
            })
            await db.increment_stat("drafts_created")

            if self.test_mode:
                log.info("[TEST MODE] Draft #%d: %s", draft_id, tweet_text)
                await send_log(
                    self.discord_bot,
                    f"[TEST] Draft #{draft_id}: {tweet_text}"
                )
                continue

            msg = await send_draft_for_approval(
                self.discord_bot,
                draft_id=draft_id,
                tweet_text=tweet_text,
                event_type=event.event_type,
                event_description=event.description,
                on_approve=self._handle_approve,
                on_reject=self._handle_reject,
            )
            if msg:
                self._draft_messages[draft_id] = msg
                await db.update_draft(draft_id, discord_message_id=str(msg.id))

    async def _handle_approve(self, draft_id: int, tweet_text: str, interaction=None):
        allowed, reason = await can_tweet()
        if not allowed:
            log.warning("Cannot tweet: %s", reason)
            if interaction:
                await interaction.followup.send(f"Cannot post: {reason}", ephemeral=True)
            return

        if self.test_mode:
            log.info("[TEST MODE] Would post: %s", tweet_text)
            await db.update_draft(draft_id, status="approved", resolved_at="now")
            return

        tweet_id = await post_tweet(self.twitter_client, tweet_text)
        if tweet_id:
            await db.update_draft(draft_id, status="approved", resolved_at="now")
            await db.log_tweet(draft_id, tweet_id, tweet_text)
            await db.increment_stat("tweets_posted")
            await db.increment_stat("drafts_approved")

            tweet_url = f"https://x.com/i/status/{tweet_id}"
            msg = self._draft_messages.pop(draft_id, None)
            if msg:
                await update_approval_message(msg, tweet_url)
            await send_log(self.discord_bot, f"Posted tweet: {tweet_url}")
            log.info("Tweet posted: %s", tweet_url)
        else:
            if interaction:
                await interaction.followup.send("Failed to post tweet. Check logs.", ephemeral=True)

    # --- News/RSS feed polling ---

    @staticmethod
    def _is_active_hours() -> bool:
        now = datetime.now(ZoneInfo(TIMEZONE))
        return FEED_ACTIVE_START <= now.hour < FEED_ACTIVE_END

    async def _poll_espn_news(self):
        if self.discord_bot.paused:
            return
        # Always poll to save articles for dedup (they get processed=0 in DB)
        articles = await poll_espn_news(self._http_session)
        if not self._is_active_hours():
            if articles:
                log.info("Outside active hours — queued %d ESPN articles for later", len(articles))
            return
        # During active hours: process new articles + any overnight backlog
        await self._process_articles_with_backlog(articles)

    async def _poll_rss_feeds(self):
        if self.discord_bot.paused:
            return
        articles = await poll_rss_feeds(self._http_session)
        if not self._is_active_hours():
            if articles:
                log.info("Outside active hours — queued %d RSS articles for later", len(articles))
            return
        await self._process_articles_with_backlog(articles)

    async def _process_articles_with_backlog(self, new_articles: list[dict]):
        """Process new articles plus any unprocessed backlog from off-hours."""
        # Fetch all unprocessed articles (includes overnight backlog + just-polled)
        all_unprocessed = await db.get_unprocessed_articles()
        if not all_unprocessed:
            return

        # Convert DB rows to the article dict format _process_articles expects
        articles = []
        for row in all_unprocessed:
            articles.append({
                "source_id": row["source_id"],
                "source": row["source"],
                "title": row["title"],
                "url": row.get("url", ""),
                "summary": row.get("summary", ""),
                "teams": row.get("teams", ""),
            })

        if len(all_unprocessed) > len(new_articles or []):
            backlog = len(all_unprocessed) - len(new_articles or [])
            log.info("Processing %d backlogged articles from off-hours", backlog)

        await self._process_articles(articles)

        # Mark all as processed
        source_ids = [row["source_id"] for row in all_unprocessed]
        await db.mark_articles_processed(source_ids)

    async def _process_articles(self, articles: list[dict]):
        if not articles:
            return

        # Score articles as SportEvents to reuse the filtering pipeline
        events = []
        for article in articles:
            event = SportEvent(
                game_id=f"article_{article['source']}",
                event_type="news_reaction",
                description=article["title"],
                score=0,
                data={
                    "source": article["source"],
                    "title": article["title"],
                    "url": article.get("url", ""),
                    "summary": article.get("summary", ""),
                    "sport": article.get("sport", ""),
                    "teams": article.get("teams", []),
                },
            )
            events.append(event)

        worthy = filter_events(events, threshold=EVENT_SCORE_THRESHOLD)
        if not worthy:
            return

        log.info("Processing %d worthy articles (of %d total)", len(worthy), len(events))

        for event in worthy:
            try:
                await self._process_news_event(event)
            except Exception:
                log.exception("Error processing news article: %s", event.description)

    async def _process_news_event(self, event: SportEvent):
        """Generate tweets from a news article and send for approval."""
        tweets = await generate_tweets_from_news(event.data)
        if not tweets:
            log.warning("No tweets generated for article: %s", event.description)
            return

        # Save as a pseudo-event in the events table
        event_id = await db.insert_event(event.to_db_dict())

        for tweet_text in tweets:
            draft_id = await db.insert_draft({
                "event_id": event_id,
                "tweet_text": tweet_text,
                "status": "pending",
                "discord_message_id": None,
            })
            await db.increment_stat("drafts_created")

            if self.test_mode:
                log.info("[TEST MODE] News Draft #%d: %s", draft_id, tweet_text)
                await send_log(self.discord_bot, f"[TEST] News Draft #{draft_id}: {tweet_text}")
                continue

            msg = await send_draft_for_approval(
                self.discord_bot,
                draft_id=draft_id,
                tweet_text=tweet_text,
                event_type="news_reaction",
                event_description=f"[NEWS] {event.description}",
                on_approve=self._handle_approve,
                on_reject=self._handle_reject,
            )
            if msg:
                self._draft_messages[draft_id] = msg
                await db.update_draft(draft_id, discord_message_id=str(msg.id))

    async def _handle_reject(self, draft_id: int, interaction=None):
        await db.update_draft(draft_id, status="rejected", resolved_at="now")
        await db.increment_stat("drafts_rejected")

        msg = self._draft_messages.pop(draft_id, None)
        reason = "Rejected" if interaction else "Expired (timeout)"
        if msg:
            await mark_rejected(msg, reason)
        log.info("Draft #%d: %s", draft_id, reason)


async def run(test_mode: bool = False):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = SportsBotApp(test_mode=test_mode)
    try:
        await app.start()
    except KeyboardInterrupt:
        pass
    finally:
        await app.shutdown()
