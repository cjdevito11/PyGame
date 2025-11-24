"""Shared helpers for building a game context.

This module centralizes registry loading so the real-time Pygame prototype
can reuse the same data-driven setup used throughout the systems layer.
"""
from dataclasses import dataclass
from pathlib import Path
import logging

from core.logging_config import get_logger, log_with_fields
from systems import (
    CombatSystem,
    EconomySystem,
    EventBus,
    QuestSystem,
    RegistryBundle,
)
from systems.ai import AISystem, BehaviorProfile
from systems.crafting import CraftingSystem
from systems.movement import MovementSystem, Position
from persistence.loader import load_definitions
from world.zones import ZoneRegistry


logger = get_logger(__name__)


@dataclass
class GameContext:
    bundle: RegistryBundle
    bus: EventBus
    combat: CombatSystem
    quests: QuestSystem
    economy: EconomySystem
    zones: ZoneRegistry
    movement: MovementSystem | None = None
    ai: AISystem | None = None
    crafting: CraftingSystem | None = None


def build_context(data_path: Path) -> GameContext:
    """Load data definitions and wire core systems together."""

    bundle = RegistryBundle(data_path)
    bundle.load()
    log_with_fields(
        logger,
        logging.INFO,
        "Datasets loaded",
        zones=len(bundle.zones.definitions()),
        characters=len(bundle.characters.definitions()),
        items=len(bundle.items.definitions()),
    )
    bus = EventBus()
    combat = CombatSystem(
        bus,
        class_registry=bundle.classes,
        item_registry=bundle.items,
        ability_registry=bundle.abilities,
        family_registry=bundle.families,
    )

    for name in bundle.characters.entries():
        profile = bundle.characters.create(name)
        combat.register_character(
            profile.name,
            profile.class_name,
            profile.items,
            gold=profile.gold,
            bag_capacity=profile.bag_capacity,
            family=profile.family,
            stats=profile.stats,
            skills=profile.skills,
            level=profile.level,
        )

    economy = EconomySystem(bus, item_registry=bundle.items, combat_system=combat)
    for character in combat.characters.values():
        economy.sync_wallet(character.name, character.gold)
    economy.register_store(
        "camp",
        {name: max(1, definition.get("value", definition.get("power", 1)) or 1) for name, definition in bundle.items.definitions().items()},
    )

    quests = QuestSystem(bus)
    quest_entries: list[dict] = []
    for quest_file in ("quests.yaml", "quests.json"):
        quest_path = data_path / quest_file
        if quest_path.exists():
            quest_entries = load_definitions(quest_path)
            break

    if quest_entries:
        for entry in quest_entries:
            condition = None
            if entry.get("condition_field"):
                field = entry["condition_field"]
                expected = entry.get("condition_value")
                condition = lambda event, field=field, expected=expected: event.payload.get(field) == expected  # noqa: E731
            quests.register_quest(
                identifier=entry["identifier"],
                description=entry["description"],
                trigger_event=entry["trigger_event"],
                owner=entry.get("owner"),
                reward_gold=int(entry.get("reward_gold", 0)),
                reward_items=list(entry.get("reward_items", [])),
                reward_attributes=entry.get("reward_attributes"),
                reward_skills=entry.get("reward_skills"),
                condition=condition,
                target_monsters=entry.get("target_monsters"),
                loot_queue=entry.get("loot_queue"),
                prerequisites=entry.get("prerequisites"),
                stages=entry.get("stages"),
            )
    elif "Aria" in combat.characters and "Shade" in combat.characters:
        quests.register_quest(
            identifier="defeat-shade",
            description="Defeat Shade to earn pocket money.",
            trigger_event="combat.defeated",
            owner="Aria",
            reward_gold=4,
            reward_items=["leather_armor"],
            reward_attributes={"strength": 1},
            reward_skills={"blade_mastery": 1},
            condition=lambda event: event.payload.get("defender") == "Shade",
            target_monsters={"Shade": 1},
            loot_queue=["quest_relic"],
        )
    static_zones = [bundle.zones.create(name) for name in bundle.zones.entries()]
    if not static_zones:
        log_with_fields(logger, logging.WARNING, "No zones defined; falling back to generated wilderness")
    zones = ZoneRegistry(static_zones)
    if not zones.active_zone and static_zones:
        log_with_fields(logger, logging.WARNING, "No start zone flagged; defaulting to first entry")
        zones.set_active(static_zones[0].name)
    log_with_fields(
        logger,
        logging.INFO,
        "Zone registry ready",
        available=zones.static_zones,
        active=getattr(zones.active_zone, "name", "<none>"),
    )
    movement = MovementSystem(bus)
    active_zone = zones.active_zone
    player_spawn = active_zone.get_spawn_point("player", (0, 0)) if active_zone else (0, 0)
    movement.set_position("Aria", Position(*player_spawn))
    guide_spawn = (active_zone.get_spawn_point("quest_giver", player_spawn) if active_zone else player_spawn)
    movement.set_position("Guide", Position(*guide_spawn))
    for name in combat.characters:
        movement.set_position(name, movement.positions.get(name, Position(0, 0)))
    ai = AISystem(
        bus,
        combat,
        movement,
        behaviors={
            "Shade": BehaviorProfile(name="Shade", abilities=["arcane_blast", "fireball"], preferred_range=3),
            "Aria": BehaviorProfile(name="Aria", abilities=["quick_strike"], preferred_range=1),
        },
    )
    crafting = CraftingSystem(bus, item_registry=bundle.items, profession_registry=bundle.professions, recipe_registry=bundle.recipes)
    log_with_fields(logger, logging.INFO, "Context ready", characters=list(combat.characters))
    return GameContext(
        bundle=bundle,
        bus=bus,
        combat=combat,
        quests=quests,
        economy=economy,
        zones=zones,
        movement=movement,
        ai=ai,
        crafting=crafting,
    )
