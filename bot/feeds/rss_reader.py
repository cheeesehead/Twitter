"""Polls RSS feeds for Philly sports content to react to."""

import logging
from datetime import datetime

import aiohttp
import feedparser

from bot import database as db
from bot.feeds.feed_config import ALL_RSS_FEEDS

log = logging.getLogger(__name__)


async def poll_rss_feeds(session: aiohttp.ClientSession) -> list[dict]:
    """Fetch all RSS feeds and return unseen articles."""
    new_articles = []

    for feed_name, feed_url in ALL_RSS_FEEDS.items():
        try:
            articles = await _fetch_feed(session, feed_name, feed_url)
            new_articles.extend(articles)
        except Exception:
            log.exception("Error fetching RSS feed %s", feed_name)

    return new_articles


async def _fetch_feed(
    session: aiohttp.ClientSession, feed_name: str, feed_url: str
) -> list[dict]:
    """Fetch a single RSS feed, return only unseen entries."""
    try:
        headers = {"User-Agent": "BroadStTakes/1.0"}
        async with session.get(
            feed_url, timeout=aiohttp.ClientTimeout(total=15), headers=headers
        ) as resp:
            if resp.status != 200:
                log.warning("RSS feed %s returned %d", feed_name, resp.status)
                return []
            raw = await resp.text()
    except Exception:
        log.exception("RSS request failed for %s", feed_name)
        return []

    feed = feedparser.parse(raw)
    new_articles = []

    for entry in feed.entries[:10]:  # Only check latest 10 per feed
        # Build a unique ID from the entry
        guid = entry.get("id") or entry.get("link") or entry.get("title", "")
        if not guid:
            continue

        source_id = f"rss_{feed_name}_{guid}"

        # Truncate source_id if absurdly long (some Reddit GUIDs are URLs)
        if len(source_id) > 500:
            source_id = source_id[:500]

        if await db.article_exists(source_id):
            continue

        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        summary = entry.get("summary", "").strip()

        # Clean up HTML from summary (basic strip)
        if "<" in summary:
            import re
            summary = re.sub(r"<[^>]+>", "", summary).strip()

        # Truncate long summaries
        if len(summary) > 500:
            summary = summary[:500] + "..."

        if not title:
            continue

        await db.insert_article({
            "source_id": source_id,
            "source": f"rss_{feed_name}",
            "title": title,
            "url": link,
            "summary": summary,
            "teams": "",
        })

        new_articles.append({
            "source": f"rss_{feed_name}",
            "title": title,
            "url": link,
            "summary": summary,
            "feed_name": feed_name,
        })

    if new_articles:
        log.info("RSS %s: %d new articles", feed_name, len(new_articles))

    return new_articles
