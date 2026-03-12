"""Full pipeline test: ESPN -> event detection -> Claude -> Discord approval."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from bot.sports.march_madness import MarchMadnessMonitor
from bot.sports.nba import NBAMonitor
from bot.content.event_scorer import score_event, filter_events
from bot.content.generator import generate_tweets
from bot.sports.base import SportEvent


async def main():
    # Step 1: Fetch live data
    print("=== Step 1: Fetching ESPN data ===")
    mm = MarchMadnessMonitor()
    nba = NBAMonitor()

    # Poll twice to detect state changes (first poll = baseline, second = detect finals)
    print("First poll (baseline)...")
    await mm.poll()
    await nba.poll()

    # For games already final, manually create test events from current data
    from bot.sports.espn_client import fetch_scoreboard
    games = await fetch_scoreboard("mens_college_basketball")
    print(f"Found {len(games)} CBB games")

    # Find a finished game to test with
    test_event = None
    for g in games:
        if g.status == "final" and g.home.seed and g.away.seed:
            winner = g.leader
            loser = g.trailer
            seed_diff = abs(winner.seed - loser.seed) if winner.seed and loser.seed else 0
            etype = "upset" if winner.seed > loser.seed and seed_diff >= 4 else "final"

            test_event = SportEvent(
                game_id=g.id,
                event_type=etype,
                description=f"{'Upset! ' if etype == 'upset' else 'Final: '}{winner.name} beats {loser.name} {g.home.score}-{g.away.score}",
                score=0,
                data={
                    "sport": "March Madness",
                    "home_team": g.home.name, "away_team": g.away.name,
                    "home_score": g.home.score, "away_score": g.away.score,
                    "home_seed": g.home.seed, "away_seed": g.away.seed,
                    "winner": winner.name, "loser": loser.name,
                    "winner_seed": winner.seed, "loser_seed": loser.seed,
                    "margin": g.score_diff, "seed_diff": seed_diff,
                    "situation": g.situation,
                },
            )
            print(f"Using game: {g.away.name} @ {g.home.name} ({g.away.score}-{g.home.score})")
            break

    if not test_event:
        print("No suitable finished tournament game found. Using a mock event.")
        test_event = SportEvent("mock1", "upset", "Mock upset for testing", 0, {
            "sport": "March Madness", "seed_diff": 8, "upset_magnitude": "massive",
            "winner": "Underdog U", "loser": "Goliath State",
            "winner_seed": 12, "loser_seed": 4,
            "home_team": "Goliath State", "away_team": "Underdog U",
            "home_score": 65, "away_score": 70, "margin": 5,
        })

    await mm.close()
    await nba.close()

    # Step 2: Score event
    print(f"\n=== Step 2: Scoring event ===")
    test_event.score = score_event(test_event)
    print(f"Event: {test_event.event_type} | Score: {test_event.score}")

    # Step 3: Generate tweets
    print(f"\n=== Step 3: Generating tweets with Claude ===")
    tweets = await generate_tweets(test_event)
    for i, t in enumerate(tweets):
        print(f"  Tweet {i+1} ({len(t)} chars): {t.encode('ascii', 'replace').decode()}")

    if not tweets:
        print("No tweets generated!")
        return

    # Step 4: Send to Discord
    print(f"\n=== Step 4: Sending to Discord for approval ===")
    import discord
    from bot.config import DISCORD_BOT_TOKEN, DISCORD_APPROVALS_CHANNEL_ID

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        channel = client.get_channel(DISCORD_APPROVALS_CHANNEL_ID)
        if not channel:
            print(f"ERROR: Channel {DISCORD_APPROVALS_CHANNEL_ID} not found!")
            await client.close()
            return

        embed = discord.Embed(
            title="[TEST] Tweet Draft",
            description=tweets[0],
            color=discord.Color.gold(),
        )
        embed.add_field(name="Event", value=test_event.description[:200], inline=False)
        embed.add_field(name="Chars", value=f"{len(tweets[0])}/280", inline=True)
        embed.add_field(name="Score", value=f"{test_event.score}/10", inline=True)
        if len(tweets) > 1:
            embed.add_field(name="Alt Tweet", value=tweets[1], inline=False)

        await channel.send(embed=embed)
        print("Draft sent to #approvals!")
        await client.close()

    await client.start(DISCORD_BOT_TOKEN)
    print("\nFull pipeline test complete!")


if __name__ == "__main__":
    asyncio.run(main())
