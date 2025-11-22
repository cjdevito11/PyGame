"""Event-driven combat system that uses registries for lookups."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

from core.logging_config import get_logger, log_with_fields
from core.registry import Registry
from systems.event_bus import Event, EventBus
from world.entities import CharacterClass, Item


@dataclass
class Combatant:
    name: str
    class_name: str
    hit_points: int
    inventory: List[Item] = field(default_factory=list)
    gold: int = 0

    def is_alive(self) -> bool:
        return self.hit_points > 0


class CombatSystem:
    """Listens for combat events and applies results to registered characters."""

    def __init__(
        self,
        bus: EventBus,
        *,
        class_registry: Registry[CharacterClass],
        item_registry: Registry[Item],
    ) -> None:
        self.bus = bus
        self.class_registry = class_registry
        self.item_registry = item_registry
        self.characters: Dict[str, Combatant] = {}
        self.logger = get_logger(__name__)
        self.bus.subscribe("combat.attack", self._handle_attack)

    def register_character(self, name: str, class_name: str, inventory: Iterable[str], gold: int = 0) -> Combatant:
        if name in self.characters:
            return self.characters[name]
        char_class = self.class_registry.create(class_name)
        items = [self.item_registry.create(item_name) for item_name in inventory]
        combatant = Combatant(
            name=name,
            class_name=class_name,
            hit_points=char_class.hit_points,
            inventory=items,
            gold=gold,
        )
        self.characters[name] = combatant
        return combatant

    def add_item(self, character_name: str, item_name: str) -> None:
        if character_name not in self.characters:
            raise KeyError(f"No character named '{character_name}' registered.")
        item = self.item_registry.create(item_name)
        self.characters[character_name].inventory.append(item)
        log_with_fields(
            self.logger,
            logging.INFO,
            "Added item to inventory",
            character=character_name,
            item=item_name,
        )

    def preview_attack(
        self, attacker_name: str, defender_name: str, *, weapon_name: str | None = None, bonus_damage: int = 0
    ) -> Dict[str, int]:
        damage, remaining_hp = self._calculate_attack(attacker_name, defender_name, weapon_name, bonus_damage, persist=False)
        return {"damage": damage, "remaining_hp": remaining_hp}

    def _calculate_attack(
        self,
        attacker_name: str,
        defender_name: str,
        weapon_name: str | None,
        bonus_damage: int,
        persist: bool,
    ) -> Tuple[int, int]:
        attacker = self.characters[attacker_name]
        defender = self.characters[defender_name]

        base_damage = 1
        if weapon_name:
            weapon = next((item for item in attacker.inventory if item.name == weapon_name), None)
            if weapon is None:
                weapon = self.item_registry.create(weapon_name)
                if persist:
                    attacker.inventory.append(weapon)
            base_damage += weapon.power

        damage = max(1, base_damage + bonus_damage)
        remaining_hp = defender.hit_points - damage
        return damage, remaining_hp

    def _handle_attack(self, event: Event) -> Dict[str, int]:
        attacker_name = event.payload["attacker"]
        defender_name = event.payload["defender"]
        weapon_name = event.payload.get("weapon")
        damage_bonus = int(event.payload.get("bonus_damage", 0))

        damage, remaining_hp = self._calculate_attack(attacker_name, defender_name, weapon_name, damage_bonus, persist=True)
        defender = self.characters[defender_name]
        defender.hit_points = remaining_hp

        result = {"damage": damage, "remaining_hp": defender.hit_points}
        log_with_fields(
            self.logger,
            logging.INFO,
            "Attack resolved",
            attacker=attacker_name,
            defender=defender_name,
            weapon=weapon_name or "unarmed",
            damage=damage,
            remaining_hp=defender.hit_points,
        )
        self.bus.publish(
            "combat.damage.applied",
            attacker=attacker_name,
            defender=defender_name,
            damage=damage,
            remaining_hp=defender.hit_points,
        )
        if defender.hit_points <= 0:
            self.bus.publish(
                "combat.defeated",
                attacker=attacker_name,
                defender=defender_name,
                class_name=defender.class_name,
            )
        return result
