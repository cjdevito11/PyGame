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
    reward_item: str | None = None
    condition: Callable[[Event], bool] | None = None
    status: str = "available"
    target_monsters: Dict[str, int] | None = None
    loot_queue: list[str] = None
    progress: Dict[str, int] = None


class QuestSystem:
    """Registers quests and advances them when trigger events fire."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.quests: Dict[str, QuestRecord] = {}
        self.logger = get_logger(__name__)
        self.bus.subscribe("quest.accepted", self._on_accept_event)
        self.bus.subscribe("quest.turned_in", self._on_turn_in_event)
        self.bus.subscribe("combat.defeated", self._on_defeat_event)

    def register_quest(
        self,
        *,
        identifier: str,
        description: str,
        trigger_event: str,
        owner: str | None = None,
        reward_gold: int = 0,
        reward_item: str | None = None,
        condition: Callable[[Event], bool] | None = None,
        target_monsters: Dict[str, int] | None = None,
        loot_queue: list[str] | None = None,
    ) -> None:
        record = QuestRecord(
            identifier=identifier,
            description=description,
            trigger_event=trigger_event,
            owner=owner,
            reward_gold=reward_gold,
            reward_item=reward_item,
            condition=condition,
            target_monsters=target_monsters or {},
            loot_queue=list(loot_queue or []),
            progress={},
        )
        self.quests[identifier] = record
        self.bus.subscribe(trigger_event, lambda event: self._handle_trigger(record.identifier, event))
        log_with_fields(
            self.logger,
            logging.INFO,
            "Registered quest",
            identifier=identifier,
            trigger=trigger_event,
            owner=owner or "<none>",
        )

    def _handle_trigger(self, quest_id: str, event: Event) -> QuestRecord:
        quest = self.quests[quest_id]
        if quest.status != "accepted":
            return quest
        if quest.condition and not quest.condition(event):
            return quest

        quest.status = "completed"
        self.bus.publish(
            "quest.completed",
            quest=quest.identifier,
            owner=quest.owner,
        )
        log_with_fields(
            self.logger,
            logging.INFO,
            "Quest completed",
            identifier=quest.identifier,
            owner=quest.owner or "<none>",
        )
        return quest

    def _check_monster_objectives(self, quest: QuestRecord, defeated: str, attacker: str | None) -> None:
        if quest.status != "accepted" or not quest.target_monsters:
            return
        if quest.owner and attacker and quest.owner != attacker:
            return
        target_count = quest.target_monsters.get(defeated)
        if target_count is None:
            return
        quest.progress[defeated] = quest.progress.get(defeated, 0) + 1
        self.bus.publish("quest.progress", quest=quest.identifier, defeated=defeated, progress=quest.progress)

        if quest.loot_queue:
            loot_item = quest.loot_queue.pop(0)
            self.bus.publish("loot.grant", owner=quest.owner, item=loot_item, reason="questloot")

        if all(quest.progress.get(monster, 0) >= count for monster, count in quest.target_monsters.items()):
            self._handle_trigger(quest.identifier, Event(name="combat.defeated", payload={"defender": defeated}))

    def accept_quest(self, identifier: str, *, owner: str | None = None) -> QuestRecord:
        quest = self.quests[identifier]
        if quest.status != "available":
            return quest
        quest.owner = owner or quest.owner
        quest.status = "accepted"
        log_with_fields(
            self.logger,
            logging.INFO,
            "Quest accepted",
            identifier=quest.identifier,
            owner=quest.owner or "<none>",
        )
        return quest

    def turn_in_quest(self, identifier: str) -> QuestRecord:
        quest = self.quests[identifier]
        if quest.status != "completed":
            return quest
        quest.status = "turned_in"
        if quest.reward_gold:
            self.bus.publish("economy.reward", recipient=quest.owner, reward_gold=quest.reward_gold)
        if quest.reward_item:
            self.bus.publish("loot.grant", owner=quest.owner, item=quest.reward_item, reason="quest")
        log_with_fields(
            self.logger,
            logging.INFO,
            "Quest turned in",
            identifier=quest.identifier,
            owner=quest.owner or "<none>",
            reward=quest.reward_gold,
        )
        return quest

    def _on_accept_event(self, event: Event) -> QuestRecord:
        quest_id = event.payload["quest"]
        owner = event.payload.get("owner")
        return self.accept_quest(quest_id, owner=owner)

    def _on_turn_in_event(self, event: Event) -> QuestRecord:
        quest_id = event.payload["quest"]
        quest = self.turn_in_quest(quest_id)
        if quest.status == "turned_in":
            event.payload["reward_gold"] = quest.reward_gold
        return quest

    def _on_defeat_event(self, event: Event) -> None:
        monster = event.payload.get("defender")
        attacker = event.payload.get("attacker")
        for quest in self.quests.values():
            self._check_monster_objectives(quest, monster, attacker)
