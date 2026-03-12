from bot.sports.base import SportMonitor, SportEvent
from bot.sports.espn_client import fetch_scoreboard
import aiohttp


class F1Monitor(SportMonitor):
    sport_key = "f1"

    def __init__(self):
        super().__init__()
        self._session: aiohttp.ClientSession | None = None

    async def ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def poll(self) -> list[SportEvent]:
        await self.ensure_session()
        # F1 ESPN endpoint structure differs from team sports
        # The scoreboard shows race events rather than head-to-head games
        # We'll fetch and parse what's available
        try:
            games = await fetch_scoreboard(self.sport_key, self._session)
        except Exception:
            return []

        events = []
        for game in games:
            prev = self._get_prev(game.id)
            ctx = {
                "home_team": game.home.name, "away_team": game.away.name,
                "home_score": game.home.score, "away_score": game.away.score,
                "situation": game.situation, "sport": "F1",
            }
            if game.status == "final" and (not prev or prev.get("status") != "final"):
                events.append(SportEvent(game.id, "final",
                    f"F1: {game.situation}", 0, ctx))
            self._save_state(game.id, {"status": game.status})
        return events
