from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
import json


@dataclass
class SportEvent:
    game_id: str
    event_type: str  # upset, close_game, buzzer_beater, blowout, cinderella, final, halftime
    description: str
    score: float  # 0-10 importance score assigned by event_scorer later
    data: dict  # full context for Claude content generation

    def to_db_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "event_type": self.event_type,
            "description": self.description,
            "score": self.score,
            "data": json.dumps(self.data),
        }


class SportMonitor(ABC):
    def __init__(self):
        self._previous_states: dict[str, dict] = {}

    @property
    @abstractmethod
    def sport_key(self) -> str:
        ...

    @abstractmethod
    async def poll(self) -> list[SportEvent]:
        ...

    def _get_prev(self, game_id: str) -> dict | None:
        return self._previous_states.get(game_id)

    def _save_state(self, game_id: str, state: dict):
        self._previous_states[game_id] = state
