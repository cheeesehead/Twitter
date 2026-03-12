"""Test the event detection + scoring pipeline with mock data."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.sports.base import SportEvent
from bot.content.event_scorer import score_event, filter_events


def test_scoring():
    events = [
        SportEvent("1", "upset", "16 seed beats 1 seed!", 0, {
            "sport": "March Madness", "seed_diff": 15, "upset_magnitude": "massive",
            "winner": "Fairleigh Dickinson", "loser": "Purdue",
            "winner_seed": 16, "loser_seed": 1,
            "home_team": "Purdue", "away_team": "Fairleigh Dickinson",
            "home_score": 61, "away_score": 63,
        }),
        SportEvent("2", "cinderella", "15 seed advances!", 0, {
            "sport": "March Madness", "cinderella_seed": 15,
            "home_team": "Team A", "away_team": "Team B",
            "home_score": 50, "away_score": 55,
        }),
        SportEvent("3", "halftime", "Halftime update", 0, {
            "sport": "March Madness",
            "home_team": "Team C", "away_team": "Team D",
            "home_score": 30, "away_score": 28,
            "halftime_leader": "Team C",
        }),
        SportEvent("4", "close_game", "One point game!", 0, {
            "sport": "March Madness", "margin": 1,
            "home_team": "Duke", "away_team": "UNC",
            "home_score": 70, "away_score": 71,
        }),
        SportEvent("5", "final", "Regular final", 0, {
            "sport": "NBA",
            "home_team": "Lakers", "away_team": "Celtics",
            "home_score": 105, "away_score": 98,
        }),
    ]

    print("Event Scoring Test:")
    print("-" * 60)
    for e in events:
        s = score_event(e)
        print(f"  {e.event_type:15s} | Score: {s:5.1f} | {e.description[:40]}")

    print(f"\nFiltered (threshold 6):")
    worthy = filter_events(events, threshold=6)
    for e in worthy:
        print(f"  {e.event_type:15s} | Score: {e.score:5.1f} | {e.description[:40]}")

    print(f"\n{len(worthy)} of {len(events)} events passed threshold")


if __name__ == "__main__":
    test_scoring()
