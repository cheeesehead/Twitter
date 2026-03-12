import aiohttp

from bot.sports.base import SportMonitor, SportEvent
from bot.sports.espn_client import fetch_scoreboard, Game


class MarchMadnessMonitor(SportMonitor):
    sport_key = "mens_college_basketball"

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
            self._save_state(game.id, self._snapshot(game))
        return events

    def _snapshot(self, game: Game) -> dict:
        return {
            "status": game.status,
            "home_score": game.home.score,
            "away_score": game.away.score,
            "period": game.period,
            "clock": game.clock,
        }

    def _game_context(self, game: Game) -> dict:
        return {
            "home_team": game.home.name,
            "away_team": game.away.name,
            "home_score": game.home.score,
            "away_score": game.away.score,
            "home_seed": game.home.seed,
            "away_seed": game.away.seed,
            "home_abbr": game.home.abbreviation,
            "away_abbr": game.away.abbreviation,
            "period": game.period,
            "clock": game.clock,
            "situation": game.situation,
            "venue": game.venue,
            "broadcast": game.broadcast,
            "sport": "March Madness",
        }

    def _detect_events(self, game: Game) -> list[SportEvent]:
        prev = self._get_prev(game.id)
        events = []
        ctx = self._game_context(game)

        # Game just ended
        if game.status == "final" and (not prev or prev["status"] != "final"):
            events.extend(self._final_events(game, ctx))

        # Live game events
        if game.status == "in_progress":
            events.extend(self._live_events(game, prev, ctx))

        return events

    def _final_events(self, game: Game, ctx: dict) -> list[SportEvent]:
        events = []
        diff = game.score_diff
        winner = game.leader
        loser = game.trailer

        ctx["winner"] = winner.name
        ctx["loser"] = loser.name
        ctx["winner_seed"] = winner.seed
        ctx["loser_seed"] = loser.seed
        ctx["margin"] = diff

        # Upset detection (higher seed number = lower ranked = underdog)
        if winner.seed and loser.seed and winner.seed > loser.seed:
            seed_diff = winner.seed - loser.seed
            if seed_diff >= 7:
                events.append(SportEvent(
                    game_id=game.id, event_type="upset",
                    description=f"MASSIVE UPSET! #{winner.seed} {winner.name} beats #{loser.seed} {loser.name} {game.home.score}-{game.away.score}",
                    score=0, data={**ctx, "seed_diff": seed_diff, "upset_magnitude": "massive"},
                ))
            elif seed_diff >= 4:
                events.append(SportEvent(
                    game_id=game.id, event_type="upset",
                    description=f"Upset! #{winner.seed} {winner.name} knocks off #{loser.seed} {loser.name}",
                    score=0, data={**ctx, "seed_diff": seed_diff, "upset_magnitude": "notable"},
                ))

            # Cinderella: 12-seed or higher wins
            if winner.seed >= 12:
                events.append(SportEvent(
                    game_id=game.id, event_type="cinderella",
                    description=f"Cinderella alert! #{winner.seed} {winner.name} advances!",
                    score=0, data={**ctx, "cinderella_seed": winner.seed},
                ))

        # Close game
        if diff <= 3:
            events.append(SportEvent(
                game_id=game.id, event_type="close_game",
                description=f"Nail-biter! {winner.name} edges {loser.name} {game.home.score}-{game.away.score}",
                score=0, data={**ctx, "margin": diff},
            ))

        # Blowout (25+ points)
        if diff >= 25:
            events.append(SportEvent(
                game_id=game.id, event_type="blowout",
                description=f"Blowout! {winner.name} destroys {loser.name} by {diff}",
                score=0, data={**ctx, "margin": diff},
            ))

        # Regular final (always generate, scorer can filter)
        if not events:
            events.append(SportEvent(
                game_id=game.id, event_type="final",
                description=f"Final: {winner.name} {game.home.score}, {loser.name} {game.away.score}",
                score=0, data=ctx,
            ))

        return events

    def _live_events(self, game: Game, prev: dict | None, ctx: dict) -> list[SportEvent]:
        events = []

        # Halftime transition
        if game.period == "2" and prev and prev.get("period") == "1":
            leader = game.leader
            events.append(SportEvent(
                game_id=game.id, event_type="halftime",
                description=f"Halftime: {game.home.name} {game.home.score}, {game.away.name} {game.away.score}",
                score=0, data={**ctx, "halftime_leader": leader.name},
            ))

        # Big run detection: 10+ point swing since last poll
        if prev:
            prev_diff = prev["home_score"] - prev["away_score"]
            curr_diff = game.home.score - game.away.score
            swing = abs(curr_diff - prev_diff)
            if swing >= 10:
                # Figure out who went on the run
                if curr_diff > prev_diff:
                    runner = game.home.name
                else:
                    runner = game.away.name
                events.append(SportEvent(
                    game_id=game.id, event_type="big_run",
                    description=f"{runner} on a huge run! Swing of {swing} points",
                    score=0, data={**ctx, "swing": swing, "runner": runner},
                ))

        # Close game in final 2 minutes
        if game.score_diff <= 5:
            try:
                clock_parts = game.clock.split(":")
                minutes = int(clock_parts[0]) if clock_parts else 99
            except (ValueError, IndexError):
                minutes = 99
            is_second_half = game.period in ("2", "OT", "3", "4")
            if minutes <= 2 and is_second_half:
                if not prev or abs((prev["home_score"] - prev["away_score"]) - game.score_diff) > 0:
                    events.append(SportEvent(
                        game_id=game.id, event_type="crunch_time",
                        description=f"Crunch time! {game.home.name} {game.home.score} - {game.away.name} {game.away.score} with {game.clock} left",
                        score=0, data={**ctx, "time_remaining": game.clock},
                    ))

        return events
