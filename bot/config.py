import os
from dotenv import load_dotenv

load_dotenv()


# X / Twitter
X_API_KEY = os.environ["X_API_KEY"]
X_API_SECRET = os.environ["X_API_SECRET"]
X_ACCESS_TOKEN = os.environ["X_ACCESS_TOKEN"]
X_ACCESS_TOKEN_SECRET = os.environ["X_ACCESS_TOKEN_SECRET"]

# Anthropic
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# Discord
DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])
DISCORD_APPROVALS_CHANNEL_ID = int(os.environ["DISCORD_APPROVALS_CHANNEL_ID"])
DISCORD_LOG_CHANNEL_ID = int(os.environ["DISCORD_LOG_CHANNEL_ID"])

# Rate limits (X free tier)
MONTHLY_TWEET_LIMIT = 1500
DAILY_TWEET_LIMIT = 45  # safety buffer under 48/day

# Polling intervals (seconds)
LIVE_POLL_INTERVAL = 60
IDLE_POLL_INTERVAL = 300

# Event scoring
EVENT_SCORE_THRESHOLD = 6

# Database
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot.db")

# Claude model
CLAUDE_MODEL = "claude-sonnet-4-20250514"
