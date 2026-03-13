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


def create_twitter_api() -> tweepy.API:
    """Create a v1.1 API instance (needed for media uploads)."""
    auth = tweepy.OAuth1UserHandler(
        X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
    )
    return tweepy.API(auth)


def upload_media(api: tweepy.API, file_path: str) -> str | None:
    """Upload media via v1.1 API and return media_id string."""
    try:
        media = api.media_upload(filename=file_path)
        media_id = str(media.media_id)
        log.info("Uploaded media %s from %s", media_id, file_path)
        return media_id
    except tweepy.TweepyException:
        log.exception("Failed to upload media: %s", file_path)
        return None


async def post_tweet(client: tweepy.Client, text: str, media_ids: list[str] | None = None) -> tuple[str | None, str | None]:
    """Post a tweet and return (tweet_id, None) on success, or (None, error_message) on failure."""
    try:
        kwargs = {"text": text}
        if media_ids:
            kwargs["media_ids"] = media_ids
        response = client.create_tweet(**kwargs)
        tweet_id = response.data["id"]
        log.info("Posted tweet %s: %s", tweet_id, text[:50])
        return str(tweet_id), None
    except tweepy.TweepyException as e:
        log.exception("Failed to post tweet")
        return None, str(e)
