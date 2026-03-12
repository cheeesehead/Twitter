"""Quick smoke test: fetch ESPN scoreboard and verify parsing."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.sports.espn_client import fetch_scoreboard


async def main():
    print("Fetching NCAA Men's Basketball scoreboard...")
    games = await fetch_scoreboard("mens_college_basketball")
    print(f"Found {len(games)} games\n")
    for g in games[:5]:
        seed_h = f"#{g.home.seed} " if g.home.seed else ""
        seed_a = f"#{g.away.seed} " if g.away.seed else ""
        print(f"  {seed_a}{g.away.name} @ {seed_h}{g.home.name}")
        print(f"    Score: {g.away.score} - {g.home.score} | Status: {g.status} | {g.situation}")
        print()

    print("Fetching NBA scoreboard...")
    nba = await fetch_scoreboard("nba")
    print(f"Found {len(nba)} NBA games\n")
    for g in nba[:3]:
        print(f"  {g.away.name} @ {g.home.name}: {g.away.score}-{g.home.score} ({g.status})")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
