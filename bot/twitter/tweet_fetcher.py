"""Fetch tweet content from URLs using the FxTwitter API."""

import re
import logging

import aiohttp

log = logging.getLogger(__name__)

TWEET_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/\w+/status/(\d+)"
)
FXTWITTER_API = "https://api.fxtwitter.com/status/{tweet_id}"


def extract_tweet_id(url: str) -> str | None:
    """Extract the tweet ID from a twitter.com or x.com URL."""
    match = TWEET_URL_PATTERN.search(url)
    return match.group(1) if match else None


def is_tweet_url(text: str) -> bool:
    """Check if the text looks like a tweet URL."""
    return bool(TWEET_URL_PATTERN.search(text))


async def fetch_tweet_content(url: str, session: aiohttp.ClientSession) -> dict | None:
    """Fetch tweet content via FxTwitter API.

    Returns dict with keys: text, author, quoted_text (optional), quoted_author (optional).
    Returns None on failure.
    """
    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return None

    api_url = FXTWITTER_API.format(tweet_id=tweet_id)
    try:
        async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                log.warning("FxTwitter API returned %d for tweet %s", resp.status, tweet_id)
                return None
            data = await resp.json()
    except Exception:
        log.exception("Failed to fetch tweet %s", tweet_id)
        return None

    tweet = data.get("tweet")
    if not tweet:
        log.warning("No tweet data in FxTwitter response for %s", tweet_id)
        return None

    result = {
        "text": tweet.get("text", ""),
        "author": tweet.get("author", {}).get("screen_name", "unknown"),
    }

    # Include quote tweet if present
    quote = tweet.get("quote")
    if quote:
        result["quoted_text"] = quote.get("text", "")
        result["quoted_author"] = quote.get("author", {}).get("screen_name", "unknown")

    return result


def format_tweet_content(tweet_data: dict) -> str:
    """Format fetched tweet data into a readable string for style references."""
    text = f"\"{tweet_data['text']}\" \u2014@{tweet_data['author']}"
    if tweet_data.get("quoted_text"):
        text += f"\nQuoting: \"{tweet_data['quoted_text']}\" \u2014@{tweet_data['quoted_author']}"
    return text
