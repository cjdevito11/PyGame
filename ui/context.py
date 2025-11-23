"""Shared helpers for building a game context.

This module centralizes registry loading so the real-time Pygame prototype
can reuse the same data-driven setup used throughout the systems layer.
"""
from dataclasses import dataclass
from pathlib import Path
import logging

from core.logging_config import get_logger, log_with_fields
from systems import CombatSystem, EconomySystem, EventBus, QuestSystem, RegistryBundle


logger = get_logger(__name__)


@dataclass
class GameContext:
    bundle: RegistryBundle
    bus: EventBus
    combat: CombatSystem
    quests: QuestSystem
    economy: EconomySystem


def build_context(data_path: Path) -> GameContext:
    """Load data definitions and wire core systems together."""

    bundle = RegistryBundle(data_path)
    bundle.load()
    bus = EventBus()
    combat = CombatSystem(bus, class_registry=bundle.classes, item_registry=bundle.items)

    for name in bundle.characters.entries():
        profile = bundle.characters.create(name)
        combat.register_character(
            profile.name,
            profile.class_name,
            profile.items,
            gold=profile.gold,
            level=profile.level,
            experience=profile.experience,
        )

    economy = EconomySystem(bus, item_registry=bundle.items, combat_system=combat)
    for character in combat.characters.values():
        economy.sync_wallet(character.name, character.gold)
    economy.register_store(
        "camp",
        {name: definition["power"] + 1 for name, definition in bundle.items.definitions().items()},
    )

    quests = QuestSystem(bus)
    if "Aria" in combat.characters and "Shade" in combat.characters:
        quests.register_quest(
            identifier="defeat-shade",
            description="Defeat Shade to earn pocket money.",
            trigger_event="combat.defeated",
            owner="Aria",
            reward_gold=4,
            reward_experience=3,
            condition=lambda event: event.payload.get("defender") == "Shade",
        )

    wolf_targets = {"Stray Wolf", "Pack Wolf", "Alpha Wolf"}
    quests.register_quest(
        identifier="wolf-threat",
        description="Hunt the wolf pack menacing the town.",
        trigger_event="combat.defeated",
        owner=None,
        reward_gold=12,
        reward_experience=8,
        goal_count=len(wolf_targets),
        condition=lambda event: event.payload.get("defender") in wolf_targets,
    )
    log_with_fields(logger, logging.INFO, "Context ready", characters=list(combat.characters))
    return GameContext(bundle=bundle, bus=bus, combat=combat, quests=quests, economy=economy)
