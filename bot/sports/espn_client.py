import aiohttp
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Team:
    id: str
    name: str
    abbreviation: str
    score: int = 0
    seed: int | None = None
    record: str = ""
    logo_url: str = ""


@dataclass
class Game:
    id: str
    sport: str
    home: Team
    away: Team
    status: str  # "scheduled", "in_progress", "final"
    period: str = ""
    clock: str = ""
    start_time: str = ""
    venue: str = ""
    broadcast: str = ""
    situation: str = ""  # e.g. "End of 1st Half"

    @property
    def score_diff(self) -> int:
        return abs(self.home.score - self.away.score)

    @property
    def leader(self) -> Team:
        return self.home if self.home.score >= self.away.score else self.away

    @property
    def trailer(self) -> Team:
        return self.away if self.home.score >= self.away.score else self.home

    def to_db_dict(self) -> dict:
        return {
            "id": self.id,
            "sport": self.sport,
            "home_team": self.home.name,
            "away_team": self.away.name,
            "home_score": self.home.score,
            "away_score": self.away.score,
            "status": self.status,
            "period": self.period,
            "clock": self.clock,
            "start_time": self.start_time,
            "last_updated": datetime.utcnow().isoformat(),
        }


# ESPN API sport slugs
SPORT_ENDPOINTS = {
    "mens_college_basketball": "basketball/mens-college-basketball",
    "womens_college_basketball": "basketball/womens-college-basketball",
    "nba": "basketball/nba",
    "nfl": "football/nfl",
    "college_football": "football/college-football",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
}

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"


async def fetch_scoreboard(sport: str, session: aiohttp.ClientSession | None = None) -> list[Game]:
    endpoint = SPORT_ENDPOINTS.get(sport)
    if not endpoint:
        return []

    url = f"{BASE_URL}/{endpoint}/scoreboard"
    close_session = session is None
    session = session or aiohttp.ClientSession()

    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
    finally:
        if close_session:
            await session.close()

    return _parse_scoreboard(data, sport)


def _parse_scoreboard(data: dict, sport: str) -> list[Game]:
    games = []
    for event in data.get("events", []):
        competition = event.get("competitions", [{}])[0]
        competitors = competition.get("competitors", [])
        if len(competitors) < 2:
            continue

        home_data = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away_data = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        home = _parse_team(home_data)
        away = _parse_team(away_data)

        status_obj = event.get("status", {})
        status_type = status_obj.get("type", {})
        state = status_type.get("state", "pre")
        status_map = {"pre": "scheduled", "in": "in_progress", "post": "final"}

        period_num = status_obj.get("period", 0)
        clock = status_obj.get("displayClock", "")
        situation_text = status_type.get("shortDetail", "")

        venue_obj = competition.get("venue", {})
        venue = venue_obj.get("fullName", "")

        broadcasts = competition.get("broadcasts", [])
        broadcast = ""
        if broadcasts:
            names = broadcasts[0].get("names", [])
            broadcast = names[0] if names else ""

        games.append(Game(
            id=event["id"],
            sport=sport,
            home=home,
            away=away,
            status=status_map.get(state, state),
            period=str(period_num),
            clock=clock,
            start_time=event.get("date", ""),
            venue=venue,
            broadcast=broadcast,
            situation=situation_text,
        ))

    return games


def _parse_team(data: dict) -> Team:
    team_info = data.get("team", {})
    seed_str = data.get("curatedRank", {}).get("current")
    if seed_str and seed_str != 99:
        seed = int(seed_str)
    else:
        seed = None

    return Team(
        id=team_info.get("id", ""),
        name=team_info.get("displayName", team_info.get("name", "Unknown")),
        abbreviation=team_info.get("abbreviation", ""),
        score=int(data.get("score", 0) or 0),
        seed=seed,
        record=data.get("records", [{}])[0].get("summary", "") if data.get("records") else "",
        logo_url=team_info.get("logo", ""),
    )
