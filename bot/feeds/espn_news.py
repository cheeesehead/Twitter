"""Polls ESPN news endpoints for headlines to react to."""

import logging
from datetime import datetime

import aiohttp

from bot import database as db
from bot.feeds.feed_config import ESPN_NEWS_ENDPOINTS

log = logging.getLogger(__name__)


async def poll_espn_news(session: aiohttp.ClientSession) -> list[dict]:
    """Fetch new ESPN headlines across all sports. Returns unseen articles."""
    new_articles = []

    for sport, url in ESPN_NEWS_ENDPOINTS.items():
        try:
            articles = await _fetch_sport_news(session, sport, url)
            new_articles.extend(articles)
        except Exception:
            log.exception("Error fetching ESPN news for %s", sport)

    return new_articles


async def _fetch_sport_news(
    session: aiohttp.ClientSession, sport: str, url: str
) -> list[dict]:
    """Fetch news for a single sport, return only unseen articles."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.warning("ESPN news %s returned %d", sport, resp.status)
                return []
            data = await resp.json()
    except Exception:
        log.exception("ESPN news request failed for %s", sport)
        return []

    articles = data.get("articles", [])
    new_articles = []

    for article in articles:
        article_id = str(article.get("dataSourceIdentifier", "")) or str(
            article.get("id", "")
        )
        if not article_id:
            continue

        source_id = f"espn_{sport}_{article_id}"

        # Check if we've already seen this article
        if await db.article_exists(source_id):
            continue

        headline = article.get("headline", "")
        description = article.get("description", "")
        link = article.get("links", {}).get("web", {}).get("href", "")

        # Extract team names from categories if available
        teams = []
        for cat in article.get("categories", []):
            if cat.get("type") == "team":
                team_name = cat.get("description", "")
                if team_name:
                    teams.append(team_name)

        await db.insert_article({
            "source_id": source_id,
            "source": f"espn_{sport}",
            "title": headline,
            "url": link,
            "summary": description,
            "teams": ", ".join(teams),
        })

        new_articles.append({
            "source": f"espn_{sport}",
            "title": headline,
            "url": link,
            "summary": description,
            "teams": teams,
            "sport": sport,
        })

    if new_articles:
        log.info("ESPN %s: %d new articles", sport, len(new_articles))

    return new_articles
