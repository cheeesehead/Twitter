from bot.sports.base import SportMonitor, SportEvent
from bot.sports.espn_client import fetch_scoreboard, Game
import aiohttp


class NBAMonitor(SportMonitor):
    sport_key = "nba"

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
            detected = self._detect_events(game)
            events.extend(detected)
            self._save_state(game.id, {
                "status": game.status, "home_score": game.home.score,
                "away_score": game.away.score, "period": game.period, "clock": game.clock,
            })
        return events

    def _game_context(self, game: Game) -> dict:
        return {
            "home_team": game.home.name, "away_team": game.away.name,
            "home_score": game.home.score, "away_score": game.away.score,
            "home_abbr": game.home.abbreviation, "away_abbr": game.away.abbreviation,
            "period": game.period, "clock": game.clock, "situation": game.situation,
            "sport": "NBA",
        }

    def _detect_events(self, game: Game) -> list[SportEvent]:
        prev = self._get_prev(game.id)
        events = []
        ctx = self._game_context(game)

        if game.status == "final" and (not prev or prev["status"] != "final"):
            winner, loser = game.leader, game.trailer
            ctx.update(winner=winner.name, loser=loser.name, margin=game.score_diff)

            if game.score_diff <= 3:
                events.append(SportEvent(game.id, "close_game",
                    f"Thriller! {winner.name} edges {loser.name} {game.home.score}-{game.away.score}",
                    0, ctx))
            elif game.score_diff >= 30:
                events.append(SportEvent(game.id, "blowout",
                    f"{winner.name} blows out {loser.name} by {game.score_diff}", 0, ctx))
            else:
                events.append(SportEvent(game.id, "final",
                    f"Final: {winner.name} {game.home.score}, {loser.name} {game.away.score}", 0, ctx))

            if game.period not in ("4", ""):
                events.append(SportEvent(game.id, "overtime",
                    f"OT thriller! {winner.name} wins in {game.situation}", 0, ctx))

        return events
