"""Quest tracking built on top of the event bus."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

from core.logging_config import get_logger, log_with_fields
from systems.event_bus import Event, EventBus


@dataclass
class QuestStage:
    description: str
    trigger_event: str
    condition: Callable[[Event], bool] | None = None
    target_monsters: Dict[str, int] | None = None
    loot_queue: list[str] = field(default_factory=list)


@dataclass
class QuestRecord:
    identifier: str
    description: str
    trigger_event: str
    owner: str | None = None
    reward_gold: int = 0
    reward_item: str | None = None
    reward_items: list[str] = field(default_factory=list)
    reward_attributes: Dict[str, int] = field(default_factory=dict)
    reward_skills: Dict[str, int] = field(default_factory=dict)
    condition: Callable[[Event], bool] | None = None
    status: str = "available"
    target_monsters: Dict[str, int] | None = None
    loot_queue: list[str] = field(default_factory=list)
    progress: Dict[str, int] = field(default_factory=dict)
    rewards_granted: bool = False
    prerequisites: List[str] = field(default_factory=list)
    stages: List[QuestStage] = field(default_factory=list)
    stage_progress: List[Dict[str, int]] = field(default_factory=list)
    current_stage: int = 0


class QuestSystem:
    """Registers quests and advances them when trigger events fire."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.quests: Dict[str, QuestRecord] = {}
        self.dependents: Dict[str, list[str]] = {}
        self.logger = get_logger(__name__)
        self.bus.subscribe("quest.accepted", self._on_accept_event)
        self.bus.subscribe("quest.turned_in", self._on_turn_in_event)
        self.bus.subscribe("combat.defeated", self._on_defeat_event)
        self.bus.subscribe("npc.talked", self._on_talk_event)
        self.bus.subscribe("inventory.item_added", self._on_inventory_event)

    def register_quest(
        self,
        *,
        identifier: str,
        description: str,
        trigger_event: str,
        owner: str | None = None,
        reward_gold: int = 0,
        reward_item: str | None = None,
        reward_items: list[str] | None = None,
        reward_attributes: Dict[str, int] | None = None,
        reward_skills: Dict[str, int] | None = None,
        condition: Callable[[Event], bool] | None = None,
        target_monsters: Dict[str, int] | None = None,
        loot_queue: list[str] | None = None,
        prerequisites: list[str] | None = None,
        stages: list[Dict[str, Any]] | None = None,
    ) -> None:
        items = list(reward_items or [])
        if reward_item:
            items.append(reward_item)

        stage_objects: list[QuestStage] = []
        for stage in stages or []:
            condition = stage.get("condition")
            if not condition and stage.get("condition_field"):
                field = stage["condition_field"]
                expected = stage.get("condition_value")
                condition = lambda event, field=field, expected=expected: event.payload.get(field) == expected  # noqa: E731
            stage_objects.append(
                QuestStage(
                    description=stage["description"],
                    trigger_event=stage.get("trigger_event", trigger_event),
                    condition=condition,
                    target_monsters=stage.get("target_monsters"),
                    loot_queue=list(stage.get("loot_queue", []) or []),
                )
            )

        prerequisites = list(prerequisites or [])
        record = QuestRecord(
            identifier=identifier,
            description=description,
            trigger_event=trigger_event,
            owner=owner,
            reward_gold=reward_gold,
            reward_item=reward_item,
            reward_items=items,
            reward_attributes=dict(reward_attributes or {}),
            reward_skills=dict(reward_skills or {}),
            condition=condition,
            target_monsters=target_monsters or {},
            loot_queue=list(loot_queue or []),
            prerequisites=prerequisites,
            stages=stage_objects,
            stage_progress=[{} for _ in stage_objects],
            status="locked" if prerequisites else "available",
        )
        self.quests[identifier] = record
        self.bus.subscribe(trigger_event, lambda event: self._handle_trigger(record.identifier, event))
        for idx, stage in enumerate(stage_objects):
            self.bus.subscribe(
                stage.trigger_event,
                lambda event, quest_id=record.identifier, stage_index=idx: self._handle_stage_trigger(
                    quest_id, stage_index, event
                ),
            )
        for quest_name in prerequisites:
            self.dependents.setdefault(quest_name, []).append(identifier)
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

        return self._complete_quest(quest)

    def _handle_stage_trigger(self, quest_id: str, stage_index: int, event: Event) -> QuestRecord:
        quest = self.quests[quest_id]
        if quest.status != "accepted" or quest.current_stage != stage_index:
            return quest

        stage = quest.stages[stage_index]
        if stage.condition and not stage.condition(event):
            return quest

        if stage.target_monsters:
            defeated = event.payload.get("defender")
            attacker = event.payload.get("attacker")
            self._check_monster_objectives(quest, defeated, attacker, stage_index=stage_index)
            return quest

        self._complete_stage(quest)
        return quest

    def _complete_quest(self, quest: QuestRecord) -> QuestRecord:
        quest.status = "completed"
        completion_payload = {
            "quest": quest.identifier,
            "owner": quest.owner,
            "reward_gold": quest.reward_gold,
            "reward_item": quest.reward_item,
            "reward_items": quest.reward_items,
            "reward_attributes": quest.reward_attributes,
            "reward_skills": quest.reward_skills,
        }
        self.bus.publish("quest.completed", **completion_payload)
        log_with_fields(
            self.logger,
            logging.INFO,
            "Quest completed",
            identifier=quest.identifier,
            owner=quest.owner or "<none>",
        )
        return quest

    def _complete_stage(self, quest: QuestRecord) -> QuestRecord:
        quest.current_stage += 1
        if quest.current_stage >= len(quest.stages):
            return self._complete_quest(quest)

        next_stage = quest.stages[quest.current_stage]
        self.bus.publish(
            "quest.stage_advanced",
            quest=quest.identifier,
            stage=quest.current_stage,
            description=next_stage.description,
        )
        log_with_fields(
            self.logger,
            logging.INFO,
            "Quest stage advanced",
            identifier=quest.identifier,
            stage=quest.current_stage,
        )
        return quest

    def _check_monster_objectives(
        self, quest: QuestRecord, defeated: str, attacker: str | None, *, stage_index: int | None = None
    ) -> None:
        if quest.status != "accepted":
            return
        targets = quest.target_monsters
        if stage_index is not None and quest.stages:
            targets = quest.stages[stage_index].target_monsters
        if not targets:
            return
        if quest.owner and attacker and quest.owner != attacker:
            return
        target_count = targets.get(defeated)
        if target_count is None:
            return
        progress = quest.progress
        if stage_index is not None and quest.stages:
            progress = quest.stage_progress[stage_index]
        progress[defeated] = progress.get(defeated, 0) + 1
        self.bus.publish(
            "quest.progress",
            quest=quest.identifier,
            defeated=defeated,
            progress=progress,
            stage=stage_index,
        )

        loot_queue = quest.loot_queue
        if stage_index is not None and quest.stages and quest.stages[stage_index].loot_queue:
            loot_queue = quest.stages[stage_index].loot_queue

        if loot_queue:
            loot_item = loot_queue.pop(0)
            self.bus.publish("loot.grant", owner=quest.owner, item=loot_item, reason="questloot")

        if all(progress.get(monster, 0) >= count for monster, count in targets.items()):
            if stage_index is not None and quest.stages:
                self._complete_stage(quest)
            else:
                self._handle_trigger(quest.identifier, Event(name="combat.defeated", payload={"defender": defeated}))

    def accept_quest(self, identifier: str, *, owner: str | None = None) -> QuestRecord:
        quest = self.quests[identifier]
        if quest.status != "available":
            return quest
        quest.current_stage = 0
        quest.progress.clear()
        quest.stage_progress = [{} for _ in quest.stages]
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
        if not quest.rewards_granted:
            if quest.reward_gold:
                self.bus.publish("economy.reward", recipient=quest.owner, reward_gold=quest.reward_gold)
            for item_name in quest.reward_items:
                self.bus.publish("loot.grant", owner=quest.owner, item=item_name, reason="quest")
            quest.rewards_granted = True
        self._unlock_dependents(identifier)
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
            event.payload["reward_items"] = quest.reward_items
            event.payload["reward_attributes"] = quest.reward_attributes
            event.payload["reward_skills"] = quest.reward_skills
        return quest

    def _on_defeat_event(self, event: Event) -> None:
        monster = event.payload.get("defender")
        attacker = event.payload.get("attacker")
        for quest in self.quests.values():
            if quest.stages:
                continue
            self._check_monster_objectives(quest, monster, attacker)

    def _on_talk_event(self, event: Event) -> None:
        npc = event.payload.get("npc")
        if not npc:
            return
        for quest in self.quests.values():
            if quest.status != "accepted" or not quest.stages:
                continue
            stage = quest.stages[quest.current_stage]
            if stage.trigger_event == "npc.talked":
                self._handle_stage_trigger(quest.identifier, quest.current_stage, event)

    def _on_inventory_event(self, event: Event) -> None:
        for quest in self.quests.values():
            if quest.status != "accepted" or not quest.stages:
                continue
            stage = quest.stages[quest.current_stage]
            if stage.trigger_event == "inventory.item_added":
                self._handle_stage_trigger(quest.identifier, quest.current_stage, event)

    def _unlock_dependents(self, quest_id: str) -> None:
        for dependent in self.dependents.get(quest_id, []):
            quest = self.quests.get(dependent)
            if not quest or quest.status != "locked":
                continue
            if not all(self.quests[req].status == "turned_in" for req in quest.prerequisites):
                continue
            quest.status = "available"
            self.bus.publish("quest.unlocked", quest=quest.identifier, prerequisites=quest.prerequisites)
            log_with_fields(
                self.logger,
                logging.INFO,
                "Quest unlocked",
                identifier=quest.identifier,
                prerequisites=quest.prerequisites,
            )
