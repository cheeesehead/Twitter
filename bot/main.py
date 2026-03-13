import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import web

from bot import database as db
from bot.config import (
    DISCORD_BOT_TOKEN, EVENT_SCORE_THRESHOLD,
    FEED_ACTIVE_START, FEED_ACTIVE_END, TIMEZONE,
)
from bot.sports.season_manager import create_monitors
from bot.sports.scheduler import SportsScheduler
from bot.sports.base import SportEvent
from bot.content.event_scorer import filter_events
from bot.content.generator import generate_tweets, generate_tweets_from_news, revise_tweet
from bot.discord_bot.bot import create_bot
from bot.discord_bot.channels import (
    send_draft_for_approval, send_log, update_approval_message, mark_rejected,
    mark_revised,
)
from bot.twitter.client import create_twitter_client, create_twitter_api, post_tweet, upload_media
from bot.media.meme_picker import get_meme_path
from bot.twitter.rate_limiter import can_tweet
from bot.feeds.espn_news import poll_espn_news
from bot.feeds.rss_reader import poll_rss_feeds

log = logging.getLogger(__name__)


class SportsBotApp:
    def __init__(self, test_mode: bool = False):
        self.test_mode = test_mode
        self.discord_bot = create_bot()
        self.twitter_client = None if test_mode else create_twitter_client()
        self.twitter_api = None if test_mode else create_twitter_api()
        self.monitors = create_monitors()
        self.scheduler = SportsScheduler(self.monitors, self._on_events)
        # Map draft_id -> discord message for updating after approve/reject
        self._draft_messages: dict[int, object] = {}
        # Expose approve/reject/revise handlers and draft map on the bot for /suggest
        self.discord_bot.on_approve = self._handle_approve
        self.discord_bot.on_reject = self._handle_reject
        self.discord_bot.on_revise = self._handle_revise
        self.discord_bot.draft_messages = self._draft_messages
        self._start_time = time.monotonic()

    async def _health_handler(self, request):
        uptime = int(time.monotonic() - self._start_time)
        return web.json_response({
            "status": "ok",
            "uptime_seconds": uptime,
            "bot_ready": self.discord_bot.is_ready() if hasattr(self.discord_bot, "is_ready") else False,
        })

    async def _start_health_server(self):
        app = web.Application()
        app.router.add_get("/health", self._health_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.environ.get("PORT", 10000))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        log.info("Health server listening on 0.0.0.0:%d", port)
        return runner

    async def start(self):
        await db.init_db()

        active = [m.sport_key for m in self.monitors]
        log.info("Active sports: %s", active)
        if not active:
            log.warning("No sports are currently in season! Bot will poll but find no games.")

        # Create shared aiohttp session for feed polling and tweet fetching
        self._http_session = aiohttp.ClientSession()
        self.discord_bot.http_session = self._http_session

        # Register news/RSS feed polling jobs (poll only — no processing)
        self.scheduler.register_feed("feed_espn_news", self._poll_espn_news)
        self.scheduler.register_feed("feed_rss", self._poll_rss_feeds)
        # Single backlog processor runs on same interval, caps output globally
        self.scheduler.register_feed("process_backlog", self._process_article_backlog)

        self.scheduler.start()
        log.info("News/RSS feed polling and backlog processor registered")

        # Start health-check server for Render, then run Discord bot
        self._health_runner = await self._start_health_server()
        self._keep_alive_task = asyncio.create_task(self._keep_alive_loop())
        try:
            await self.discord_bot.start(DISCORD_BOT_TOKEN)
        finally:
            await self._health_runner.cleanup()

    async def _keep_alive_loop(self):
        port = int(os.environ.get("PORT", 10000))
        url = f"http://localhost:{port}/health"
        while True:
            await asyncio.sleep(840)  # 14 minutes
            try:
                async with self._http_session.get(url) as resp:
                    log.debug("Keep-alive ping: %d", resp.status)
            except Exception:
                log.debug("Keep-alive ping failed (non-critical)")

    async def shutdown(self):
        if hasattr(self, "_keep_alive_task"):
            self._keep_alive_task.cancel()
        self.scheduler.stop()
        for monitor in self.monitors:
            if hasattr(monitor, "close"):
                await monitor.close()
        if hasattr(self, "_http_session") and self._http_session:
            await self._http_session.close()
        await db.close_db()
        await self.discord_bot.close()

    async def _on_events(self, events: list[SportEvent]):
        if self.discord_bot.paused:
            log.info("Bot is paused, ignoring %d events", len(events))
            return

        # Score and filter
        worthy = filter_events(events, threshold=EVENT_SCORE_THRESHOLD)
        if not worthy:
            return

        # Filter out events from games the user has rejected
        filtered = []
        for event in worthy:
            if not event.game_id.startswith("article_") and await db.is_game_suppressed(event.game_id):
                log.info("Suppressed (rejected game): %s", event.description)
                continue
            filtered.append(event)
        worthy = filtered
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
        for tweet_dict in tweets:
            tweet_text = tweet_dict["text"]
            meme_id = tweet_dict.get("meme_id")
            article_url = tweet_dict.get("article_url")

            draft_id = await db.insert_draft({
                "event_id": event_id,
                "tweet_text": tweet_text,
                "status": "pending",
                "discord_message_id": None,
                "meme_id": meme_id,
                "article_url": article_url,
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
                on_revise=self._handle_revise,
                meme_id=meme_id,
                article_url=article_url,
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

        # Look up draft for meme_id and article_url
        draft = await db.get_draft(draft_id)
        meme_id = draft.get("meme_id") if draft else None
        article_url = draft.get("article_url") if draft else None

        # Upload meme image if present
        media_ids = None
        if meme_id and self.twitter_api:
            meme_path = get_meme_path(meme_id)
            if meme_path:
                media_id = upload_media(self.twitter_api, meme_path)
                if media_id:
                    media_ids = [media_id]

        # Append article URL to tweet text (Twitter auto-unfurls)
        post_text = tweet_text
        if article_url:
            post_text = f"{tweet_text} {article_url}"

        tweet_id, error = await post_tweet(self.twitter_client, post_text, media_ids=media_ids)
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
            error_msg = f"Failed to post tweet: {error}" if error else "Failed to post tweet (unknown error)"
            await send_log(self.discord_bot, error_msg)
            if interaction:
                await interaction.followup.send(error_msg, ephemeral=True)

    # --- News/RSS feed polling ---

    @staticmethod
    def _is_active_hours() -> bool:
        now = datetime.now(ZoneInfo(TIMEZONE))
        return FEED_ACTIVE_START <= now.hour < FEED_ACTIVE_END

    async def _poll_espn_news(self):
        """Poll ESPN for new articles and save to DB. No processing here."""
        if self.discord_bot.paused:
            return
        articles = await poll_espn_news(self._http_session)
        if articles:
            log.info("Polled %d new ESPN articles", len(articles))

    async def _poll_rss_feeds(self):
        """Poll RSS feeds for new articles and save to DB. No processing here."""
        if self.discord_bot.paused:
            return
        articles = await poll_rss_feeds(self._http_session)
        if articles:
            log.info("Polled %d new RSS articles", len(articles))

    async def _process_article_backlog(self):
        """Process unprocessed article backlog — runs as a single scheduled job.

        Keeps the top MAX_BACKLOG articles by score and drip-feeds
        MAX_PER_CYCLE each polling interval.  Low-scoring and overflow
        articles are marked processed so they don't accumulate forever.
        """
        if self.discord_bot.paused:
            return
        if not self._is_active_hours():
            return

        MAX_BACKLOG = 15
        MAX_PER_CYCLE = 3

        all_unprocessed = await db.get_unprocessed_articles()
        if not all_unprocessed:
            return

        # Filter out articles whose topics have been rejected
        suppressed_ids = []
        for row in all_unprocessed:
            if await db.is_topic_suppressed(row["title"]):
                suppressed_ids.append(row["source_id"])
                log.info("Suppressed (rejected topic): %s", row["title"])
        if suppressed_ids:
            await db.mark_articles_processed(suppressed_ids)
            all_unprocessed = [r for r in all_unprocessed
                               if r["source_id"] not in set(suppressed_ids)]
        if not all_unprocessed:
            return

        # Convert DB rows to SportEvents and score via the existing pipeline
        events = []
        local_news_sources = ("philly_news", "inquirer", "billypenn", "r_philadelphia")
        for row in all_unprocessed:
            source = row["source"]
            etype = "local_news" if source.startswith(local_news_sources) else "news_reaction"
            event = SportEvent(
                game_id=f"article_{source}",
                event_type=etype,
                description=row["title"],
                score=0,
                data={
                    "source_id": row["source_id"],
                    "source": row["source"],
                    "title": row["title"],
                    "url": row.get("url", ""),
                    "summary": row.get("summary", ""),
                    "sport": row.get("sport", ""),
                    "teams": row.get("teams", []),
                },
            )
            events.append(event)

        worthy = filter_events(events, threshold=EVENT_SCORE_THRESHOLD)

        # Mark unworthy articles as processed — they'll never score high enough
        worthy_source_ids = {e.data.get("source_id") for e in worthy}
        unworthy_ids = [row["source_id"] for row in all_unprocessed
                        if row["source_id"] not in worthy_source_ids]
        if unworthy_ids:
            await db.mark_articles_processed(unworthy_ids)

        if not worthy:
            return

        # Cap backlog to top MAX_BACKLOG — worthy is already sorted by score desc
        if len(worthy) > MAX_BACKLOG:
            overflow = worthy[MAX_BACKLOG:]
            overflow_ids = [e.data.get("source_id") for e in overflow]
            await db.mark_articles_processed(overflow_ids)
            worthy = worthy[:MAX_BACKLOG]

        # Process top MAX_PER_CYCLE this cycle
        batch = worthy[:MAX_PER_CYCLE]
        log.info("Processing %d worthy articles (of %d unprocessed, %d in backlog)",
                 len(batch), len(all_unprocessed), len(worthy))

        for event in batch:
            try:
                await self._process_news_event(event)
            except Exception:
                log.exception("Error processing news article: %s", event.description)

        # Mark only the processed batch as done
        batch_ids = [e.data.get("source_id") for e in batch]
        await db.mark_articles_processed(batch_ids)

        remaining = len(worthy) - len(batch)
        if remaining > 0:
            log.info("%d backlog articles queued for next cycle", remaining)

    async def _process_news_event(self, event: SportEvent):
        """Generate tweets from a news article and send for approval."""
        tweets = await generate_tweets_from_news(event.data, event_type=event.event_type)
        if not tweets:
            log.warning("No tweets generated for article: %s", event.description)
            return

        # Save as a pseudo-event in the events table
        event_id = await db.insert_event(event.to_db_dict())

        for tweet_dict in tweets:
            tweet_text = tweet_dict["text"]
            meme_id = tweet_dict.get("meme_id")
            article_url = tweet_dict.get("article_url")

            draft_id = await db.insert_draft({
                "event_id": event_id,
                "tweet_text": tweet_text,
                "status": "pending",
                "discord_message_id": None,
                "meme_id": meme_id,
                "article_url": article_url,
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
                event_type=event.event_type,
                event_description=f"[{'LOCAL' if event.event_type == 'local_news' else 'NEWS'}] {event.description}",
                on_approve=self._handle_approve,
                on_reject=self._handle_reject,
                on_revise=self._handle_revise,
                meme_id=meme_id,
                article_url=article_url,
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

        # Only cascade + suppress on explicit rejection (not timeout)
        if interaction:
            draft = await db.get_draft(draft_id)
            event_id = draft.get("event_id") if draft else None
            if event_id:
                # Reject all sibling pending drafts from the same event
                siblings = await db.get_pending_drafts_by_event(event_id)
                for sib in siblings:
                    if sib["id"] == draft_id:
                        continue
                    await db.update_draft(sib["id"], status="rejected", resolved_at="now")
                    await db.increment_stat("drafts_rejected")
                    sib_msg = self._draft_messages.pop(sib["id"], None)
                    if sib_msg:
                        await mark_rejected(sib_msg, "Rejected")
                    log.info("Draft #%d: auto-rejected (sibling of #%d)", sib["id"], draft_id)

                # Suppress the topic so similar articles are skipped
                event = await db.get_event(event_id)
                if event and event.get("data"):
                    try:
                        event_data = json.loads(event["data"])
                    except (json.JSONDecodeError, TypeError):
                        event_data = {}
                    title = event_data.get("title") or event.get("description") or ""
                    keywords = db.extract_topic_keywords(title)
                    if len(keywords) >= 2:
                        await db.insert_rejected_topic(keywords, title, event_id)
                        await send_log(
                            self.discord_bot,
                            f"Topic suppressed (48h): **{title}**\nKeywords: {', '.join(keywords)}"
                        )

                        # Reject all other pending drafts matching the suppressed topic
                        keyword_set = set(keywords)
                        all_pending = await db.get_pending_drafts_with_events()
                        for pd in all_pending:
                            if pd["event_id"] == event_id:
                                continue  # already handled above
                            pd_title = ""
                            if pd.get("data"):
                                try:
                                    pd_data = json.loads(pd["data"])
                                    pd_title = pd_data.get("title") or ""
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            pd_title = pd_title or pd.get("description") or ""
                            pd_keywords = set(db.extract_topic_keywords(pd_title))
                            if len(pd_keywords & keyword_set) >= 2:
                                await db.update_draft(pd["draft_id"], status="rejected", resolved_at="now")
                                await db.increment_stat("drafts_rejected")
                                pd_msg = self._draft_messages.pop(pd["draft_id"], None)
                                if pd_msg:
                                    await mark_rejected(pd_msg, "Rejected")
                                log.info("Draft #%d: auto-rejected (topic match with #%d)", pd["draft_id"], draft_id)

                    # Suppress the entire game for live events (6h TTL)
                    game_id = event.get("game_id", "")
                    if game_id and not game_id.startswith("article_"):
                        await db.insert_rejected_topic(
                            keywords=[], source_title=title or game_id,
                            event_id=event_id, ttl_hours=6, game_id=game_id
                        )
                        await send_log(
                            self.discord_bot,
                            f"Game suppressed (6h): **{title or game_id}**"
                        )

    async def _handle_revise(self, draft_id: int, tweet_text: str, feedback: str,
                             interaction=None):
        # 1. Save feedback for future learning
        await db.insert_feedback_note(feedback, original_tweet=tweet_text)
        log.info("Draft #%d: revision requested — %s", draft_id, feedback)

        # 2. Mark original draft as revised
        await db.update_draft(draft_id, status="revised", resolved_at="now")
        old_msg = self._draft_messages.pop(draft_id, None)
        if old_msg:
            await mark_revised(old_msg)

        # 3. Generate revised tweets
        revised = await revise_tweet(tweet_text, feedback)
        if not revised:
            if interaction:
                await interaction.followup.send(
                    "Couldn't generate a revision. Try again or edit manually.",
                    ephemeral=True,
                )
            return

        # 4. Get original draft to inherit event_id
        original = await db.get_draft(draft_id)
        event_id = original["event_id"] if original else None

        # 5. Send revised drafts for approval
        for tweet_dict in revised:
            new_tweet = tweet_dict["text"]
            meme_id = tweet_dict.get("meme_id")
            article_url = tweet_dict.get("article_url")

            new_draft_id = await db.insert_draft({
                "event_id": event_id,
                "tweet_text": new_tweet,
                "status": "pending",
                "discord_message_id": None,
                "meme_id": meme_id,
                "article_url": article_url,
            })
            await db.increment_stat("drafts_created")

            msg = await send_draft_for_approval(
                self.discord_bot,
                draft_id=new_draft_id,
                tweet_text=new_tweet,
                event_type="revision",
                event_description=f"Revised from Draft #{draft_id} — Feedback: {feedback[:100]}",
                on_approve=self._handle_approve,
                on_reject=self._handle_reject,
                on_revise=self._handle_revise,
                meme_id=meme_id,
                article_url=article_url,
            )
            if msg:
                self._draft_messages[new_draft_id] = msg
                await db.update_draft(new_draft_id, discord_message_id=str(msg.id))


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
