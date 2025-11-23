"""Shared helpers for building a game context.

This module centralizes registry loading so the real-time Pygame prototype
can reuse the same data-driven setup used throughout the systems layer.
"""
from dataclasses import dataclass
from pathlib import Path
import logging

from core.logging_config import get_logger, log_with_fields
from systems import CombatSystem, EconomySystem, EventBus, QuestSystem, RegistryBundle
from world.zones import ZoneManager


logger = get_logger(__name__)


@dataclass
class GameContext:
    bundle: RegistryBundle
    bus: EventBus
    combat: CombatSystem
    quests: QuestSystem
    economy: EconomySystem
    zones: ZoneManager


def build_context(data_path: Path) -> GameContext:
    """Load data definitions and wire core systems together."""

    bundle = RegistryBundle(data_path)
    bundle.load()
    bus = EventBus()
    combat = CombatSystem(bus, class_registry=bundle.classes, item_registry=bundle.items)

    for name in bundle.characters.entries():
        profile = bundle.characters.create(name)
        combat.register_character(
            profile.name, profile.class_name, profile.items, gold=profile.gold, bag_capacity=profile.bag_capacity
        )

    economy = EconomySystem(bus, item_registry=bundle.items, combat_system=combat)
    for character in combat.characters.values():
        economy.sync_wallet(character.name, character.gold)
    economy.register_store(
        "camp",
        {name: max(1, definition.get("value", definition.get("power", 1)) or 1) for name, definition in bundle.items.definitions().items()},
    )

    quests = QuestSystem(bus)
    if "Aria" in combat.characters and "Shade" in combat.characters:
        quests.register_quest(
            identifier="defeat-shade",
            description="Defeat Shade to earn pocket money.",
            trigger_event="combat.defeated",
            owner="Aria",
            reward_gold=4,
            reward_item="leather_armor",
            condition=lambda event: event.payload.get("defender") == "Shade",
            target_monsters={"Shade": 1},
            loot_queue=["quest_relic"],
        )
    zones = ZoneManager([bundle.zones.create(name) for name in bundle.zones.entries()])
    if "town" in bundle.zones.entries():
        zones.set_active("town")
    elif "camp" in bundle.zones.entries():
        zones.set_active("camp")
    log_with_fields(logger, logging.INFO, "Context ready", characters=list(combat.characters))
    return GameContext(bundle=bundle, bus=bus, combat=combat, quests=quests, economy=economy, zones=zones)
