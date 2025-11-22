"""Quest tracking built on top of the event bus."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Dict

from core.logging_config import get_logger, log_with_fields
from systems.event_bus import Event, EventBus


@dataclass
class QuestRecord:
    identifier: str
    description: str
    trigger_event: str
    owner: str | None = None
    reward_gold: int = 0
    status: str = "new"


class QuestSystem:
    """Registers quests and advances them when trigger events fire."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.quests: Dict[str, QuestRecord] = {}
        self.logger = get_logger(__name__)

    def register_quest(
        self,
        *,
        identifier: str,
        description: str,
        trigger_event: str,
        owner: str | None = None,
        reward_gold: int = 0,
        condition: Callable[[Event], bool] | None = None,
    ) -> None:
        record = QuestRecord(
            identifier=identifier,
            description=description,
            trigger_event=trigger_event,
            owner=owner,
            reward_gold=reward_gold,
        )
        self.quests[identifier] = record
        self.bus.subscribe(trigger_event, lambda event: self._handle_trigger(record, event, condition))
        log_with_fields(
            self.logger,
            logging.INFO,
            "Registered quest",
            identifier=identifier,
            trigger=trigger_event,
            owner=owner or "<none>",
        )

    def _handle_trigger(
        self, quest: QuestRecord, event: Event, condition: Callable[[Event], bool] | None
    ) -> QuestRecord:
        if quest.status == "completed":
            return quest
        if condition and not condition(event):
            return quest

        quest.status = "completed"
        self.bus.publish(
            "quest.completed",
            quest=quest.identifier,
            owner=quest.owner,
            reward_gold=quest.reward_gold,
        )
        log_with_fields(
            self.logger,
            logging.INFO,
            "Quest completed",
            identifier=quest.identifier,
            owner=quest.owner or "<none>",
            reward=quest.reward_gold,
        )
        return quest
