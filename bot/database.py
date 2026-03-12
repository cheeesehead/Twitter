import aiosqlite
from datetime import datetime, date

from bot.config import DB_PATH

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

CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT PRIMARY KEY,
    tweets_posted INTEGER DEFAULT 0,
    drafts_created INTEGER DEFAULT 0,
    drafts_approved INTEGER DEFAULT 0,
    drafts_rejected INTEGER DEFAULT 0
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


# --- Games ---

async def upsert_game(game: dict):
    async with await get_db() as db:
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
    async with await get_db() as db:
        cursor = await db.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


# --- Events ---

async def insert_event(event: dict) -> int:
    async with await get_db() as db:
        cursor = await db.execute(
            """INSERT INTO events (game_id, event_type, description, score, data)
               VALUES (:game_id, :event_type, :description, :score, :data)""",
            event,
        )
        await db.commit()
        return cursor.lastrowid


async def get_recent_events(game_id: str, limit: int = 10) -> list[dict]:
    async with await get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM events WHERE game_id = ? ORDER BY created_at DESC LIMIT ?",
            (game_id, limit),
        )
        return [dict(r) for r in await cursor.fetchall()]


# --- Drafts ---

async def insert_draft(draft: dict) -> int:
    async with await get_db() as db:
        cursor = await db.execute(
            """INSERT INTO drafts (event_id, tweet_text, status, discord_message_id)
               VALUES (:event_id, :tweet_text, :status, :discord_message_id)""",
            draft,
        )
        await db.commit()
        return cursor.lastrowid


async def update_draft(draft_id: int, **kwargs):
    async with await get_db() as db:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [draft_id]
        await db.execute(f"UPDATE drafts SET {sets} WHERE id = ?", vals)
        await db.commit()


async def get_draft(draft_id: int) -> dict | None:
    async with await get_db() as db:
        cursor = await db.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_pending_drafts() -> list[dict]:
    async with await get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM drafts WHERE status = 'pending' ORDER BY created_at ASC"
        )
        return [dict(r) for r in await cursor.fetchall()]


# --- Tweet Log ---

async def log_tweet(draft_id: int, tweet_id: str, tweet_text: str):
    async with await get_db() as db:
        await db.execute(
            "INSERT INTO tweet_log (draft_id, tweet_id, tweet_text) VALUES (?, ?, ?)",
            (draft_id, tweet_id, tweet_text),
        )
        await db.commit()


# --- Daily Stats ---

async def get_daily_stats(day: str | None = None) -> dict:
    day = day or date.today().isoformat()
    async with await get_db() as db:
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
    async with await get_db() as db:
        await db.execute(
            f"UPDATE daily_stats SET {stat} = {stat} + 1 WHERE date = ?", (day,)
        )
        await db.commit()


async def get_monthly_tweet_count() -> int:
    month_prefix = date.today().strftime("%Y-%m")
    async with await get_db() as db:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(tweets_posted), 0) FROM daily_stats WHERE date LIKE ?",
            (f"{month_prefix}%",),
        )
        row = await cursor.fetchone()
        return row[0]
