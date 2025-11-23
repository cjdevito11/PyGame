"""Lightweight encounter AI for autonomous enemies."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List

from core.logging_config import get_logger, log_with_fields
from systems.combat import CombatSystem
from systems.event_bus import EventBus
from systems.movement import MovementSystem


logger = get_logger(__name__)


@dataclass
class BehaviorProfile:
    name: str
    abilities: List[str] = field(default_factory=list)
    preferred_range: int = 1
    retreat_threshold: int = 0


class AISystem:
    def __init__(
        self,
        bus: EventBus,
        combat: CombatSystem,
        movement: MovementSystem,
        behaviors: Dict[str, BehaviorProfile] | None = None,
    ) -> None:
        self.bus = bus
        self.combat = combat
        self.movement = movement
        self.behaviors = behaviors or {}
        self.bus.subscribe("ai.take_turn", self._take_turn)

    def _take_turn(self, event) -> Dict[str, str]:
        actor = event.payload["actor"]
        target = event.payload["target"]
        profile = self.behaviors.get(actor, BehaviorProfile(name=actor, abilities=[]))

        if profile.retreat_threshold and self._should_retreat(actor, profile):
            self.bus.publish("movement.step", name=actor, dx=-1, dy=-1)
            return {"action": "retreat"}

        if not self.movement.in_range(actor, target, profile.preferred_range):
            self.bus.publish("movement.step", name=actor, dx=1, dy=0)
            return {"action": "move"}

        ability = random.choice(profile.abilities) if profile.abilities else None
        if ability:
            try:
                self.bus.publish("ability.cast", attacker=actor, defender=target, ability=ability)
                return {"action": "ability", "ability": ability}
            except Exception as exc:  # pragma: no cover - defensive
                log_with_fields(logger, 30, "Ability failed", actor=actor, error=str(exc))

        self.bus.publish("combat.attack", attacker=actor, defender=target)
        return {"action": "attack"}

    def _should_retreat(self, actor: str, profile: BehaviorProfile) -> bool:
        combatant = self.combat.characters.get(actor)
        if not combatant:
            return False
        return combatant.hit_points <= profile.retreat_threshold
