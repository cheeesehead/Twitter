import tweepy
import logging

from bot.config import X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET

log = logging.getLogger(__name__)


def create_twitter_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_TOKEN_SECRET,
    )


async def post_tweet(client: tweepy.Client, text: str) -> tuple[str | None, str | None]:
    """Post a tweet and return (tweet_id, None) on success, or (None, error_message) on failure."""
    try:
        response = client.create_tweet(text=text)
        tweet_id = response.data["id"]
        log.info("Posted tweet %s: %s", tweet_id, text[:50])
        return str(tweet_id), None
    except tweepy.TweepyException as e:
        log.exception("Failed to post tweet")
        return None, str(e)
