from datetime import date

from bot.sports.base import SportMonitor
from bot.sports.march_madness import MarchMadnessMonitor
from bot.sports.nba import NBAMonitor
from bot.sports.nfl import NFLMonitor
from bot.sports.mlb import MLBMonitor
from bot.sports.cfb import CFBMonitor
from bot.sports.soccer import PremierLeagueMonitor, ChampionsLeagueMonitor, USASoccerMonitor
from bot.sports.f1 import F1Monitor

# Approximate season date ranges (month, day) -> (start_m, start_d, end_m, end_d)
SEASONS = {
    "mens_college_basketball": {"monitor": MarchMadnessMonitor, "ranges": [(11, 1, 4, 15)]},
    "nba": {"monitor": NBAMonitor, "ranges": [(10, 15, 4, 30), (5, 1, 6, 30)]},
    "nfl": {"monitor": NFLMonitor, "ranges": [(9, 1, 2, 15)]},
    "mlb": {"monitor": MLBMonitor, "ranges": [(3, 20, 11, 5)]},
    "college_football": {"monitor": CFBMonitor, "ranges": [(8, 24, 1, 20)]},
    "premier_league": {"monitor": PremierLeagueMonitor, "ranges": [(8, 1, 5, 31)]},
    "champions_league": {"monitor": ChampionsLeagueMonitor, "ranges": [(9, 1, 6, 15)]},
    "usa_soccer_men": {"monitor": USASoccerMonitor, "ranges": [(2, 15, 11, 15)]},
    "f1": {"monitor": F1Monitor, "ranges": [(3, 1, 12, 15)]},
}


def _in_range(today: date, start_m: int, start_d: int, end_m: int, end_d: int) -> bool:
    start = date(today.year, start_m, start_d)
    if end_m < start_m:
        end = date(today.year + 1, end_m, end_d)
    else:
        end = date(today.year, end_m, end_d)

    if end_m < start_m:
        return today >= start or today <= date(today.year, end_m, end_d)
    return start <= today <= end


def get_active_sports(today: date | None = None) -> list[str]:
    today = today or date.today()
    active = []
    for sport, info in SEASONS.items():
        for rng in info["ranges"]:
            if _in_range(today, *rng):
                active.append(sport)
                break
    return active


def create_monitors(today: date | None = None) -> list[SportMonitor]:
    active = get_active_sports(today)
    monitors = []
    for sport in active:
        monitor_cls = SEASONS[sport]["monitor"]
        monitors.append(monitor_cls())
    return monitors
