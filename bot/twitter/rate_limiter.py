from datetime import date

from bot import database as db
from bot.config import DAILY_TWEET_LIMIT, MONTHLY_TWEET_LIMIT


async def can_tweet() -> tuple[bool, str]:
    daily = await db.get_daily_stats()
    monthly = await db.get_monthly_tweet_count()

    if monthly >= MONTHLY_TWEET_LIMIT:
        return False, f"Monthly limit reached ({monthly}/{MONTHLY_TWEET_LIMIT})"
    if daily["tweets_posted"] >= DAILY_TWEET_LIMIT:
        return False, f"Daily limit reached ({daily['tweets_posted']}/{DAILY_TWEET_LIMIT})"
    return True, "OK"


async def budget_remaining() -> dict:
    daily = await db.get_daily_stats()
    monthly = await db.get_monthly_tweet_count()
    return {
        "daily_remaining": DAILY_TWEET_LIMIT - daily["tweets_posted"],
        "daily_limit": DAILY_TWEET_LIMIT,
        "monthly_remaining": MONTHLY_TWEET_LIMIT - monthly,
        "monthly_limit": MONTHLY_TWEET_LIMIT,
    }
