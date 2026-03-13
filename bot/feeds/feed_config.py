"""RSS feed URLs organized by sport/team for Philly-focused content discovery."""

# PhillyVoice sport-specific feeds
PHILLY_VOICE_FEEDS = {
    "eagles": "https://www.phillyvoice.com/eagles/rss/",
    "sixers": "https://www.phillyvoice.com/sixers/rss/",
    "phillies": "https://www.phillyvoice.com/phillies/rss/",
    "flyers": "https://www.phillyvoice.com/flyers/rss/",
}

# NBC Sports Philadelphia
NBC_SPORTS_PHILLY_FEEDS = {
    "nbc_sports_philly": "https://www.nbcsportsphiladelphia.com/rss",
}

# Reddit RSS (append .rss to any subreddit)
REDDIT_FEEDS = {
    "r_eagles": "https://www.reddit.com/r/eagles/hot/.rss",
    "r_sixers": "https://www.reddit.com/r/sixers/hot/.rss",
    "r_phillies": "https://www.reddit.com/r/phillies/hot/.rss",
}

# Philly local news (non-sports)
PHILLY_NEWS_FEEDS = {
    "philly_news": "https://www.phillyvoice.com/news/rss/",
    "inquirer": "https://www.inquirer.com/arcio/rss/category/news/",
    "billypenn": "https://billypenn.com/feed/",
    "r_philadelphia": "https://www.reddit.com/r/philadelphia/hot/.rss",
}

# All RSS feeds combined
ALL_RSS_FEEDS: dict[str, str] = {}
ALL_RSS_FEEDS.update(PHILLY_VOICE_FEEDS)
ALL_RSS_FEEDS.update(NBC_SPORTS_PHILLY_FEEDS)
ALL_RSS_FEEDS.update(REDDIT_FEEDS)
ALL_RSS_FEEDS.update(PHILLY_NEWS_FEEDS)

# ESPN news endpoints by sport
ESPN_NEWS_ENDPOINTS = {
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news",
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news",
    "mlb": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/news",
    "nhl": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/news",
    "college_basketball": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/news",
    "college_football": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/news",
}
