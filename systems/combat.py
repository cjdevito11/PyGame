"""Event-driven combat system that uses registries for lookups."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

from core.logging_config import get_logger, log_with_fields
from core.registry import Registry
from systems.event_bus import Event, EventBus
from world.entities import Ability, CharacterClass, Item, MonsterFamily


@dataclass
class Combatant:
    name: str
    class_name: str
    hit_points: int
    resource_pools: Dict[str, int] = field(default_factory=dict)
    inventory: List[Item] = field(default_factory=list)
    gold: int = 0
    equipped: Dict[str, Item] = field(default_factory=dict)
    base_capacity: int = 10
    buffs: list["Buff"] = field(default_factory=list)
    gcd_remaining: int = 0
    cooldowns: Dict[str, int] = field(default_factory=dict)
    family: str | None = None
    position: Tuple[int, int] = (0, 0)
    strength: int = 0
    agility: int = 0
    mastery: int = 0
    skills: Dict[str, int] = field(default_factory=dict)

    def is_alive(self) -> bool:
        return self.hit_points > 0

    def capacity(self) -> int:
        bonus = sum(item.capacity_bonus for item in self.equipped.values())
        return self.base_capacity + bonus

    def resource(self, resource_type: str) -> int:
        return self.resource_pools.get(resource_type, 0)


@dataclass
class Buff:
    source: str
    power: int = 0
    defense: int = 0
    speed: int = 0
    turns_remaining: int = 0


class CombatSystem:
    """Listens for combat events and applies results to registered characters."""

    def __init__(
        self,
        bus: EventBus,
        *,
        class_registry: Registry[CharacterClass],
        item_registry: Registry[Item],
        ability_registry: Registry["Ability"] | None = None,
        family_registry: Registry["MonsterFamily"] | None = None,
    ) -> None:
        self.bus = bus
        self.class_registry = class_registry
        self.item_registry = item_registry
        self.ability_registry = ability_registry
        self.family_registry = family_registry
        self.characters: Dict[str, Combatant] = {}
        self.logger = get_logger(__name__)
        self.bus.subscribe("combat.attack", self._handle_attack)
        self.bus.subscribe("loot.grant", self._handle_loot)
        self.bus.subscribe("inventory.consume", self._handle_consume)
        self.bus.subscribe("ability.cast", self._handle_ability)

    def register_character(
        self,
        name: str,
        class_name: str,
        inventory: Iterable[str],
        gold: int = 0,
        *,
        bag_capacity: int = 10,
        family: str | None = None,
        stats: Dict[str, int] | None = None,
        skills: Dict[str, int] | None = None,
    ) -> Combatant:
        if name in self.characters:
            return self.characters[name]
        char_class = self.class_registry.create(class_name)
        items = [self.item_registry.create(item_name) for item_name in inventory]
        combatant = Combatant(
            name=name,
            class_name=class_name,
            hit_points=char_class.hit_points,
            resource_pools={char_class.resource_type: char_class.resource_max or char_class.mana},
            inventory=items,
            gold=gold,
            base_capacity=bag_capacity,
            family=family,
            strength=int((stats or {}).get("strength", 0)),
            agility=int((stats or {}).get("agility", 0)),
            mastery=int((stats or {}).get("mastery", 0)),
            skills=dict(skills or {}),
        )
        for item in items:
            self._maybe_equip(combatant, item)
        self.characters[name] = combatant
        return combatant

    def add_item(self, character_name: str, item_name: str, *, reason: str | None = None) -> None:
        if character_name not in self.characters:
            raise KeyError(f"No character named '{character_name}' registered.")
        item = self.item_registry.create(item_name)
        combatant = self.characters[character_name]
        capacity = combatant.capacity()
        if not item.quest_item and len(combatant.inventory) >= capacity:
            log_with_fields(
                self.logger,
                logging.WARNING,
                "Inventory full; item rejected",
                character=character_name,
                item=item_name,
            )
            self.bus.publish("inventory.full", owner=character_name, item=item_name)
            return
        combatant.inventory.append(item)
        self._maybe_equip(combatant, item)
        log_with_fields(
            self.logger,
            logging.INFO,
            "Added item to inventory",
            character=character_name,
            item=item_name,
            reason=reason or "event",
        )
        self.bus.publish("inventory.item_added", owner=character_name, item=item_name, reason=reason)

    def equip_item(self, character_name: str, item_name: str) -> Item:
        """Explicitly equip a carried item, overriding any auto-picks."""

        combatant = self.characters[character_name]
        item = next((it for it in combatant.inventory if it.name == item_name), None)
        if not item:
            raise KeyError(f"{character_name} cannot equip missing item {item_name}")
        combatant.equipped[item.slot] = item
        log_with_fields(
            self.logger,
            logging.INFO,
            "Item equipped",
            character=character_name,
            item=item_name,
            slot=item.slot,
        )
        self.bus.publish("inventory.equipped", owner=character_name, item=item_name, slot=item.slot)
        return item

    def _handle_loot(self, event: Event) -> Dict[str, str]:
        owner = event.payload["owner"]
        item_name = event.payload["item"]
        reason = event.payload.get("reason", "loot")
        self.add_item(owner, item_name, reason=reason)
        return {"owner": owner, "item": item_name}

    def _handle_consume(self, event: Event) -> Dict[str, object]:
        owner = event.payload["owner"]
        item_name = event.payload["item"]
        return self.consume_item(owner, item_name)

    def remove_item(self, character_name: str, item_name: str) -> Item | None:
        combatant = self.characters[character_name]
        for idx, item in enumerate(combatant.inventory):
            if item.name == item_name:
                combatant.inventory.pop(idx)
                if combatant.equipped.get(item.slot) is item:
                    combatant.equipped.pop(item.slot, None)
                return item
        return None

    def consume_item(self, character_name: str, item_name: str) -> Dict[str, object]:
        combatant = self.characters[character_name]
        item = next((it for it in combatant.inventory if it.name == item_name), None)
        if not item:
            raise KeyError(f"{character_name} lacks consumable {item_name}")
        if item.item_type != "consumable":
            raise ValueError(f"{item_name} is not usable")

        combatant.inventory.remove(item)
        buff = Buff(
            source=item.name,
            power=item.power,
            defense=item.defense,
            speed=item.speed,
            turns_remaining=item.duration_turns or 2,
        )
        combatant.buffs.append(buff)
        log_with_fields(
            self.logger,
            logging.INFO,
            "Consumable used",
            owner=character_name,
            item=item_name,
            duration=buff.turns_remaining,
        )
        self.bus.publish("inventory.consumed", owner=character_name, item=item_name, duration=buff.turns_remaining)
        return {"buff": buff}

    def repair_item(self, character_name: str, item_name: str) -> Dict[str, int]:
        combatant = self.characters[character_name]
        item = next((it for it in combatant.inventory if it.name == item_name), None)
        if not item or not item.max_durability:
            raise ValueError(f"{item_name} cannot be repaired")
        missing = (item.max_durability - (item.durability or 0))
        item.durability = item.max_durability
        log_with_fields(
            self.logger,
            logging.INFO,
            "Item repaired",
            character=character_name,
            item=item_name,
            restored=missing,
        )
        return {"restored": missing, "max": item.max_durability}

    def preview_attack(
        self, attacker_name: str, defender_name: str, *, weapon_name: str | None = None, bonus_damage: int = 0
    ) -> Dict[str, int]:
        damage, remaining_hp = self._calculate_attack(attacker_name, defender_name, weapon_name, bonus_damage, persist=False)
        return {"damage": damage, "remaining_hp": remaining_hp}

    def _effective_item_stats(self, item: Item) -> Tuple[int, int, int]:
        if item.max_durability and item.durability is not None:
            ratio = max(0, item.durability) / item.max_durability
            scale = max(0.25, ratio)
        else:
            scale = 1.0
        return int(item.power * scale), int(item.defense * scale), int(item.speed * scale)

    def _condition_label(self, item: Item) -> str:
        if not item.max_durability:
            return "steady"
        ratio = max(0, item.durability or 0) / item.max_durability
        if ratio >= 0.66:
            return item.appearance_states[0] if item.appearance_states else "sturdy"
        if ratio >= 0.33:
            return item.appearance_states[1] if len(item.appearance_states) > 1 else "worn"
        return item.appearance_states[2] if len(item.appearance_states) > 2 else "broken"

    def _maybe_equip(self, combatant: Combatant, item: Item) -> None:
        current = combatant.equipped.get(item.slot)
        if current is None:
            combatant.equipped[item.slot] = item
            return

        def _score(equipment: Item) -> int:
            power, defense, speed = self._effective_item_stats(equipment)
            return power + defense + speed + equipment.capacity_bonus

        if _score(item) > _score(current):
            combatant.equipped[item.slot] = item

    def _attack_power(self, attacker: Combatant, weapon_name: str | None, *, persist: bool) -> int:
        base_power = 1 + attacker.strength
        speed_bonus = attacker.agility // 2

        for item in attacker.equipped.values():
            pwr, _, spd = self._effective_item_stats(item)
            base_power += pwr
            speed_bonus += spd

        set_bonus = self._set_bonus(attacker)
        base_power += set_bonus["power"]
        speed_bonus += set_bonus["speed"]

        buff = self._buff_totals(attacker)
        base_power += buff.power
        speed_bonus += buff.speed

        weapon: Item | None = None
        if weapon_name:
            weapon = next((item for item in attacker.inventory if item.name == weapon_name), None)
            if weapon is None:
                weapon = self.item_registry.create(weapon_name)
                if persist:
                    attacker.inventory.append(weapon)
                    self._maybe_equip(attacker, weapon)
            if weapon not in attacker.equipped.values():
                pwr, _, spd = self._effective_item_stats(weapon)
                base_power += pwr
                speed_bonus += spd

        attack_power = max(1, base_power + speed_bonus)
        return attack_power

    def _calculate_resilience(self, defender: Combatant) -> int:
        total_defense = defender.mastery + defender.agility // 3 + defender.strength // 4
        for item in defender.equipped.values():
            _, defense, _ = self._effective_item_stats(item)
            total_defense += defense
        set_bonus = self._set_bonus(defender)
        total_defense += set_bonus["defense"]

        buff = self._buff_totals(defender)
        total_defense += buff.defense
        return total_defense

    def _family_resistance(self, defender: Combatant, school: str) -> int:
        if not self.family_registry or not defender.family:
            return 0
        family = self.family_registry.definitions().get(defender.family)
        if not family:
            return 0
        if school in family.get("immunities", []):
            return 999
        return int(family.get("resistances", {}).get(school, 0))

    def _set_bonus(self, combatant: Combatant) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in combatant.equipped.values():
            if item.set_name:
                counts[item.set_name] = counts.get(item.set_name, 0) + 1

        bonus = {"power": 0, "defense": 0, "speed": 0}
        for set_name, count in counts.items():
            if set_name == "obsidian":
                if count >= 2:
                    bonus["defense"] += 1
                if count >= 3:
                    bonus["power"] += 2
                    bonus["speed"] += 1
        return bonus

    def _buff_totals(self, combatant: Combatant) -> Buff:
        total = Buff(source="aggregate", power=0, defense=0, speed=0, turns_remaining=0)
        for buff in list(combatant.buffs):
            total.power += buff.power
            total.defense += buff.defense
            total.speed += buff.speed
        return total

    def _tick_buffs(self, combatant: Combatant) -> None:
        remaining: list[Buff] = []
        for buff in combatant.buffs:
            if buff.turns_remaining > 1:
                buff.turns_remaining -= 1
                remaining.append(buff)
        combatant.buffs = remaining

    def _advance_turns(self, combatant: Combatant) -> None:
        combatant.gcd_remaining = max(0, combatant.gcd_remaining - 1)
        cooled: Dict[str, int] = {}
        for ability, remaining in combatant.cooldowns.items():
            if remaining > 1:
                cooled[ability] = remaining - 1
        combatant.cooldowns = cooled

    def _spend_resource(self, combatant: Combatant, resource_type: str, cost: int) -> bool:
        current = combatant.resource_pools.get(resource_type, 0)
        if current < cost:
            return False
        combatant.resource_pools[resource_type] = current - cost
        return True

    def _apply_durability_loss(self, combatant: Combatant, slots: Iterable[str], amount: int = 1) -> None:
        for slot in slots:
            item = combatant.equipped.get(slot)
            if not item or not item.max_durability:
                continue
            item.durability = max(0, (item.durability if item.durability is not None else item.max_durability) - amount)
            condition = self._condition_label(item)
            log_with_fields(
                self.logger,
                logging.DEBUG,
                "Durability reduced",
                character=combatant.name,
                item=item.name,
                remaining=item.durability,
                condition=condition,
            )

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
        attack_power = self._attack_power(attacker, weapon_name, persist=persist)
        defense = self._calculate_resilience(defender)

        damage = max(1, attack_power + bonus_damage - defense)
        remaining_hp = defender.hit_points - damage
        if persist:
            self._apply_durability_loss(attacker, ["mainhand", "offhand"])
            self._apply_durability_loss(defender, ["armor", "offhand"], amount=2)
            self._tick_buffs(attacker)
            self._tick_buffs(defender)
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
            for item in list(defender.inventory):
                self.bus.publish(
                    "loot.grant",
                    owner=attacker_name,
                    item=item.name,
                    reason="drop",
                    source=defender_name,
                )
            defender.inventory.clear()
        return result

    def _handle_ability(self, event: Event) -> Dict[str, object]:
        if not self.ability_registry:
            raise RuntimeError("No ability registry configured")
        attacker_name = event.payload["attacker"]
        defender_name = event.payload.get("defender")
        ability_name = event.payload["ability"]
        attacker = self.characters[attacker_name]
        ability = self.ability_registry.create(ability_name)

        if attacker.class_name != ability.class_name:
            raise PermissionError(f"{attacker.class_name} cannot use {ability.name}")
        if attacker.gcd_remaining > 0:
            raise RuntimeError("Global cooldown active")
        if attacker.cooldowns.get(ability.name, 0) > 0:
            raise RuntimeError("Ability on cooldown")
        if not self._spend_resource(attacker, ability.resource_type, ability.cost):
            raise RuntimeError("Insufficient resources")

        damage = 0
        healing = 0
        defender = self.characters.get(defender_name) if defender_name else None
        if defender:
            defense = self._calculate_resilience(defender)
            school_resist = self._family_resistance(defender, ability.school)
            attack_power = self._attack_power(attacker, weapon_name=None, persist=True) + ability.power
            damage = max(1, attack_power - defense - school_resist)
            defender.hit_points -= damage
        if ability.heal and defender:
            defender.hit_points += ability.heal
            healing = ability.heal

        attacker.cooldowns[ability.name] = max(1, ability.cooldown_turns)
        attacker.gcd_remaining = max(1, ability.gcd_turns)
        self._apply_durability_loss(attacker, ["mainhand"], amount=1)
        self._tick_buffs(attacker)
        if defender:
            self._tick_buffs(defender)
        self._advance_turns(attacker)
        if defender:
            self._advance_turns(defender)

        payload = {
            "attacker": attacker_name,
            "defender": defender_name,
            "ability": ability.name,
            "damage": damage,
            "healing": healing,
            "remaining_hp": defender.hit_points if defender else None,
        }
        log_with_fields(self.logger, logging.INFO, "Ability resolved", **payload)
        self.bus.publish("combat.ability", **payload)
        return payload
