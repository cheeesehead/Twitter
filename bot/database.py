import json
import re
import aiosqlite
from datetime import datetime, date

from bot.config import DB_PATH

STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "has", "have", "been", "will", "with",
    "this", "that", "from", "they", "been", "said", "each", "which", "their",
    "about", "would", "there", "could", "other", "into", "more", "some",
    "than", "them", "very", "when", "what", "your", "how", "its", "may",
    "after", "before", "just", "over", "also", "did", "get", "got", "why",
    "new", "now", "old", "see", "way", "who", "does", "let", "say",
    # Generic sports terms to avoid false positives
    "nba", "nfl", "nhl", "mlb", "mls", "game", "team", "player", "season",
    "trade", "draft", "coach", "play", "win", "loss", "score", "report",
    "update", "news", "sports", "league", "series", "match", "round",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_score INTEGER DEFAULT 0,
    away_score INTEGER DEFAULT 0,
    status TEXT DEFAULT 'scheduled',
    period TEXT,
    clock TEXT,
    start_time TEXT,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    description TEXT,
    score REAL DEFAULT 0,
    data TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (game_id) REFERENCES games(id)
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER,
    tweet_text TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    discord_message_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT,
    FOREIGN KEY (event_id) REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS tweet_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id INTEGER,
    tweet_id TEXT,
    tweet_text TEXT NOT NULL,
    posted_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (draft_id) REFERENCES drafts(id)
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    summary TEXT,
    teams TEXT,
    processed INTEGER DEFAULT 0,
    seen_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS style_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    source_url TEXT,
    added_by TEXT,
    added_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT PRIMARY KEY,
    tweets_posted INTEGER DEFAULT 0,
    drafts_created INTEGER DEFAULT 0,
    drafts_approved INTEGER DEFAULT 0,
    drafts_rejected INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS feedback_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback TEXT NOT NULL,
    original_tweet TEXT,
    added_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rejected_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keywords TEXT NOT NULL,
    source_title TEXT NOT NULL,
    event_id INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);
"""

_db: aiosqlite.Connection | None = None


async def init_db():
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    # Migration: add processed column if missing (existing DBs)
    cursor = await _db.execute("PRAGMA table_info(articles)")
    columns = [row[1] for row in await cursor.fetchall()]
    if "processed" not in columns:
        await _db.execute("ALTER TABLE articles ADD COLUMN processed INTEGER DEFAULT 0")

    # Migration: add meme_id and article_url columns to drafts
    cursor = await _db.execute("PRAGMA table_info(drafts)")
    draft_columns = [row[1] for row in await cursor.fetchall()]
    if "meme_id" not in draft_columns:
        await _db.execute("ALTER TABLE drafts ADD COLUMN meme_id TEXT")
    if "article_url" not in draft_columns:
        await _db.execute("ALTER TABLE drafts ADD COLUMN article_url TEXT")

    # Migration: create rejected_topics table for existing DBs
    await _db.execute("""CREATE TABLE IF NOT EXISTS rejected_topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keywords TEXT NOT NULL,
        source_title TEXT NOT NULL,
        event_id INTEGER,
        created_at TEXT DEFAULT (datetime('now')),
        expires_at TEXT NOT NULL
    )""")

    # Migration: add game_id column to rejected_topics
    cursor = await _db.execute("PRAGMA table_info(rejected_topics)")
    rt_columns = [row[1] for row in await cursor.fetchall()]
    if "game_id" not in rt_columns:
        await _db.execute("ALTER TABLE rejected_topics ADD COLUMN game_id TEXT")

    await _db.commit()


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


def get_db() -> aiosqlite.Connection:
    assert _db is not None, "Database not initialized — call init_db() first"
    return _db


# --- Games ---

async def upsert_game(game: dict):
    db = get_db()
    await db.execute(
        """INSERT INTO games (id, sport, home_team, away_team, home_score, away_score,
           status, period, clock, start_time, last_updated)
           VALUES (:id, :sport, :home_team, :away_team, :home_score, :away_score,
           :status, :period, :clock, :start_time, :last_updated)
           ON CONFLICT(id) DO UPDATE SET
           home_score=:home_score, away_score=:away_score, status=:status,
           period=:period, clock=:clock, last_updated=:last_updated""",
        game,
    )
    await db.commit()


async def get_game(game_id: str) -> dict | None:
    db = get_db()
    cursor = await db.execute("SELECT * FROM games WHERE id = ?", (game_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


# --- Events ---

async def insert_event(event: dict) -> int:
    db = get_db()
    cursor = await db.execute(
        """INSERT INTO events (game_id, event_type, description, score, data)
           VALUES (:game_id, :event_type, :description, :score, :data)""",
        event,
    )
    await db.commit()
    return cursor.lastrowid


async def get_recent_events(game_id: str, limit: int = 10) -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        "SELECT * FROM events WHERE game_id = ? ORDER BY created_at DESC LIMIT ?",
        (game_id, limit),
    )
    return [dict(r) for r in await cursor.fetchall()]


# --- Drafts ---

async def insert_draft(draft: dict) -> int:
    db = get_db()
    cursor = await db.execute(
        """INSERT INTO drafts (event_id, tweet_text, status, discord_message_id, meme_id, article_url)
           VALUES (:event_id, :tweet_text, :status, :discord_message_id, :meme_id, :article_url)""",
        draft,
    )
    await db.commit()
    return cursor.lastrowid


async def update_draft(draft_id: int, **kwargs):
    db = get_db()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [draft_id]
    await db.execute(f"UPDATE drafts SET {sets} WHERE id = ?", vals)
    await db.commit()


async def get_draft(draft_id: int) -> dict | None:
    db = get_db()
    cursor = await db.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_pending_drafts() -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        "SELECT * FROM drafts WHERE status = 'pending' ORDER BY created_at ASC"
    )
    return [dict(r) for r in await cursor.fetchall()]


# --- Tweet Log ---

async def log_tweet(draft_id: int, tweet_id: str, tweet_text: str):
    db = get_db()
    await db.execute(
        "INSERT INTO tweet_log (draft_id, tweet_id, tweet_text) VALUES (?, ?, ?)",
        (draft_id, tweet_id, tweet_text),
    )
    await db.commit()


# --- Daily Stats ---

async def get_daily_stats(day: str | None = None) -> dict:
    day = day or date.today().isoformat()
    db = get_db()
    cursor = await db.execute("SELECT * FROM daily_stats WHERE date = ?", (day,))
    row = await cursor.fetchone()
    if row:
        return dict(row)
    await db.execute(
        "INSERT INTO daily_stats (date) VALUES (?)", (day,)
    )
    await db.commit()
    return {"date": day, "tweets_posted": 0, "drafts_created": 0,
            "drafts_approved": 0, "drafts_rejected": 0}


async def increment_stat(stat: str, day: str | None = None):
    day = day or date.today().isoformat()
    await get_daily_stats(day)  # ensure row exists
    db = get_db()
    await db.execute(
        f"UPDATE daily_stats SET {stat} = {stat} + 1 WHERE date = ?", (day,)
    )
    await db.commit()


# --- Articles (news/RSS dedup) ---

async def article_exists(source_id: str) -> bool:
    db = get_db()
    cursor = await db.execute(
        "SELECT 1 FROM articles WHERE source_id = ?", (source_id,)
    )
    return await cursor.fetchone() is not None


async def insert_article(article: dict):
    db = get_db()
    await db.execute(
        """INSERT OR IGNORE INTO articles (source_id, source, title, url, summary, teams)
           VALUES (:source_id, :source, :title, :url, :summary, :teams)""",
        article,
    )
    await db.commit()


async def get_unprocessed_articles() -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        "SELECT * FROM articles WHERE processed = 0 ORDER BY seen_at ASC"
    )
    return [dict(r) for r in await cursor.fetchall()]


async def mark_articles_processed(source_ids: list[str]):
    if not source_ids:
        return
    db = get_db()
    placeholders = ",".join("?" for _ in source_ids)
    await db.execute(
        f"UPDATE articles SET processed = 1 WHERE source_id IN ({placeholders})",
        source_ids,
    )
    await db.commit()


# --- Style References ---

async def insert_style_reference(content: str, source_url: str | None = None,
                                  added_by: str | None = None) -> int:
    db = get_db()
    cursor = await db.execute(
        """INSERT INTO style_references (content, source_url, added_by)
           VALUES (?, ?, ?)""",
        (content, source_url, added_by),
    )
    await db.commit()
    return cursor.lastrowid


async def get_style_references(limit: int = 50) -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        "SELECT * FROM style_references ORDER BY added_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def delete_style_reference(ref_id: int):
    db = get_db()
    await db.execute("DELETE FROM style_references WHERE id = ?", (ref_id,))
    await db.commit()


async def get_style_reference_count() -> int:
    db = get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM style_references")
    row = await cursor.fetchone()
    return row[0]


async def style_reference_exists_by_tweet_id(tweet_id: str) -> bool:
    """Check if a style reference with this tweet ID already exists."""
    db = get_db()
    cursor = await db.execute(
        "SELECT 1 FROM style_references WHERE source_url LIKE ?",
        (f"%/status/{tweet_id}%",),
    )
    return await cursor.fetchone() is not None


# --- Feedback Notes ---

async def insert_feedback_note(feedback: str, original_tweet: str | None = None) -> int:
    db = get_db()
    cursor = await db.execute(
        "INSERT INTO feedback_notes (feedback, original_tweet) VALUES (?, ?)",
        (feedback, original_tweet),
    )
    await db.commit()
    return cursor.lastrowid


async def get_feedback_notes(limit: int = 30) -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        "SELECT * FROM feedback_notes ORDER BY added_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_monthly_tweet_count() -> int:
    month_prefix = date.today().strftime("%Y-%m")
    db = get_db()
    cursor = await db.execute(
        "SELECT COALESCE(SUM(tweets_posted), 0) FROM daily_stats WHERE date LIKE ?",
        (f"{month_prefix}%",),
    )
    row = await cursor.fetchone()
    return row[0]


# --- Events (single-row fetch) ---

async def get_event(event_id: int) -> dict | None:
    db = get_db()
    cursor = await db.execute("SELECT * FROM events WHERE id = ?", (event_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


# --- Rejected Topics ---

def extract_topic_keywords(title: str) -> list[str]:
    """Extract up to 5 meaningful keywords from a title for topic matching."""
    words = re.findall(r"[a-z]+", title.lower())
    keywords = [w for w in words if len(w) >= 3 and w not in STOPWORDS]
    return keywords[:5]


async def insert_rejected_topic(keywords: list[str], source_title: str,
                                 event_id: int | None = None, ttl_hours: int = 48,
                                 game_id: str | None = None):
    db = get_db()
    await db.execute(
        """INSERT INTO rejected_topics (keywords, source_title, event_id, expires_at, game_id)
           VALUES (?, ?, ?, datetime('now', ?), ?)""",
        (json.dumps(keywords), source_title, event_id, f"+{ttl_hours} hours", game_id),
    )
    await db.commit()


async def is_topic_suppressed(title: str) -> bool:
    """Check if a title has 2+ keyword overlap with any non-expired rejected topic."""
    title_keywords = set(extract_topic_keywords(title))
    if len(title_keywords) < 2:
        return False

    db = get_db()
    cursor = await db.execute(
        "SELECT keywords FROM rejected_topics WHERE expires_at > datetime('now')"
    )
    rows = await cursor.fetchall()
    for row in rows:
        rejected_keywords = set(json.loads(row[0]))
        if len(title_keywords & rejected_keywords) >= 2:
            return True
    return False


async def is_game_suppressed(game_id: str) -> bool:
    """Check if a game_id has been rejected and is still within its suppression window."""
    db = get_db()
    cursor = await db.execute(
        "SELECT 1 FROM rejected_topics WHERE game_id = ? AND expires_at > datetime('now') LIMIT 1",
        (game_id,),
    )
    return await cursor.fetchone() is not None


async def get_pending_drafts_by_event(event_id: int) -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        "SELECT * FROM drafts WHERE event_id = ? AND status = 'pending'",
        (event_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_pending_drafts_with_events() -> list[dict]:
    """Get all pending drafts joined with their event data."""
    db = get_db()
    cursor = await db.execute(
        """SELECT d.id as draft_id, d.event_id, e.description, e.data, e.game_id
           FROM drafts d
           JOIN events e ON d.event_id = e.id
           WHERE d.status = 'pending'"""
    )
    return [dict(r) for r in await cursor.fetchall()]
