"""Event-driven combat system that uses registries for lookups."""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List

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
        self.characters[character_name].inventory.append(self.item_registry.create(item_name))

    def _handle_attack(self, event: Event) -> Dict[str, int]:
        attacker = self.characters[event.payload["attacker"]]
        defender = self.characters[event.payload["defender"]]
        weapon_name = event.payload.get("weapon")
        damage_bonus = int(event.payload.get("bonus_damage", 0))

        base_damage = 1
        if weapon_name:
            weapon = next((item for item in attacker.inventory if item.name == weapon_name), None)
            if weapon is None:
                weapon = self.item_registry.create(weapon_name)
                attacker.inventory.append(weapon)
            base_damage += weapon.power

        damage = max(1, base_damage + damage_bonus)
        defender.hit_points -= damage

        result = {"damage": damage, "remaining_hp": defender.hit_points}
        self.bus.publish(
            "combat.damage.applied",
            attacker=attacker.name,
            defender=defender.name,
            damage=damage,
            remaining_hp=defender.hit_points,
        )
        if defender.hit_points <= 0:
            self.bus.publish(
                "combat.defeated",
                attacker=attacker.name,
                defender=defender.name,
                class_name=defender.class_name,
            )
        return result
