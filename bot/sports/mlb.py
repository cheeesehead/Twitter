from bot.sports.base import SportMonitor, SportEvent
from bot.sports.espn_client import fetch_scoreboard
import aiohttp


class MLBMonitor(SportMonitor):
    sport_key = "mlb"

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
        games = await fetch_scoreboard(self.sport_key, self._session)
        events = []
        for game in games:
            prev = self._get_prev(game.id)
            ctx = {
                "home_team": game.home.name, "away_team": game.away.name,
                "home_score": game.home.score, "away_score": game.away.score,
                "period": game.period, "clock": game.clock, "situation": game.situation,
                "sport": "MLB",
            }
            if game.status == "final" and (not prev or prev.get("status") != "final"):
                w, l = game.leader, game.trailer
                ctx.update(winner=w.name, loser=l.name, margin=game.score_diff)
                events.append(SportEvent(game.id, "final",
                    f"Final: {w.name} {game.home.score}, {l.name} {game.away.score}", 0, ctx))
            self._save_state(game.id, {"status": game.status, "home_score": game.home.score,
                "away_score": game.away.score, "period": game.period})
        return events
