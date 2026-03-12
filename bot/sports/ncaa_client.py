"""NCAA bracket/seeding data supplement.

The ESPN API already provides seed data in curatedRank for tournament games,
so this module is reserved for additional NCAA-specific data if needed
(e.g., bracket region, round info from NCAA endpoints).

For now, the MarchMadnessMonitor gets seeds directly from ESPN.
"""

import aiohttp
import logging

log = logging.getLogger(__name__)

NCAA_SCOREBOARD_URL = "https://data.ncaa.com/casablanca/scoreboard/basketball-men/d1/2026/03/12/scoreboard.json"


async def fetch_ncaa_scoreboard(date_str: str, session: aiohttp.ClientSession | None = None) -> dict:
    """Fetch NCAA scoreboard for a given date (YYYY/MM/DD format)."""
    url = f"https://data.ncaa.com/casablanca/scoreboard/basketball-men/d1/{date_str}/scoreboard.json"
    close = session is None
    session = session or aiohttp.ClientSession()
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                log.debug("NCAA API returned %d", resp.status)
                return {}
            return await resp.json()
    except Exception:
        log.debug("NCAA API unavailable")
        return {}
    finally:
        if close:
            await session.close()
