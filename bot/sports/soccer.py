from bot.sports.base import SportMonitor, SportEvent
from bot.sports.espn_client import fetch_scoreboard, Game
import aiohttp


class SoccerMonitor(SportMonitor):
    def __init__(self, sport_key: str, display_name: str):
        super().__init__()
        self._sport_key = sport_key
        self._display_name = display_name
        self._session: aiohttp.ClientSession | None = None

    @property
    def sport_key(self) -> str:
        return self._sport_key

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
            ctx = self._game_context(game)

            if game.status == "final" and (not prev or prev.get("status") != "final"):
                events.extend(self._final_events(game, ctx))

            self._save_state(game.id, {
                "status": game.status, "home_score": game.home.score,
                "away_score": game.away.score, "period": game.period,
            })
        return events

    def _game_context(self, game: Game) -> dict:
        return {
            "home_team": game.home.name, "away_team": game.away.name,
            "home_score": game.home.score, "away_score": game.away.score,
            "home_abbr": game.home.abbreviation, "away_abbr": game.away.abbreviation,
            "period": game.period, "clock": game.clock, "situation": game.situation,
            "sport": self._display_name,
        }

    def _final_events(self, game: Game, ctx: dict) -> list[SportEvent]:
        events = []
        winner, loser = game.leader, game.trailer
        ctx.update(winner=winner.name, loser=loser.name, margin=game.score_diff)

        if game.score_diff == 0:
            events.append(SportEvent(game.id, "close_game",
                f"Draw! {game.home.name} {game.home.score} - {game.away.name} {game.away.score}",
                0, {**ctx, "margin": 0}))
        elif game.score_diff == 1:
            events.append(SportEvent(game.id, "close_game",
                f"Tight one! {winner.name} edges {loser.name} {game.home.score}-{game.away.score}",
                0, ctx))
        elif game.score_diff >= 4:
            events.append(SportEvent(game.id, "blowout",
                f"Rout! {winner.name} smashes {loser.name} {game.home.score}-{game.away.score}",
                0, ctx))
        else:
            events.append(SportEvent(game.id, "final",
                f"Final: {game.home.name} {game.home.score} - {game.away.name} {game.away.score}",
                0, ctx))

        return events


class PremierLeagueMonitor(SoccerMonitor):
    def __init__(self):
        super().__init__("premier_league", "Premier League")


class ChampionsLeagueMonitor(SoccerMonitor):
    def __init__(self):
        super().__init__("champions_league", "Champions League")


class USASoccerMonitor(SoccerMonitor):
    def __init__(self):
        super().__init__("usa_soccer_men", "MLS / USMNT")
