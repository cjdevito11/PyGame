"""Guided exercises that mirror the contributor walkthrough."""
from __future__ import annotations

from pathlib import Path
import unittest

from core.registry import Registry
from core.validation import DefinitionValidator
from persistence.loader import load_definitions
from systems.event_bus import EventBus
from systems.quests import QuestSystem
from world.entities import Appearance, CharacterClass
from world.schemas import AppearanceDefinition, ClassDefinition


FIXTURES = Path(__file__).parent / "fixtures"


class ExerciseTests(unittest.TestCase):
    def test_new_appearance_loads_from_yaml(self) -> None:
        """Add a new appearance from a data file and instantiate it via the registry."""

        validator = DefinitionValidator()
        validator.register_schema("appearances", AppearanceDefinition)

        registry = Registry("appearances", validator, Appearance.from_definition)
        entries = load_definitions(FIXTURES / "exercise_appearances.yaml")
        registry.load_many(entries)

        sprite = registry.create("ember_sprite")
        self.assertEqual(sprite.symbol, "e")
        self.assertEqual(sprite.color, "orange")

    def test_new_class_respects_stat_bounds(self) -> None:
        """Load a short class definition and verify the parsed stats."""

        validator = DefinitionValidator()
        validator.register_schema("classes", ClassDefinition)

        registry = Registry("classes", validator, CharacterClass.from_definition)
        entries = load_definitions(FIXTURES / "exercise_classes.yaml")
        registry.load_many(entries)

        tinkerer = registry.create("tinkerer")
        self.assertEqual(tinkerer.hit_points, 10)
        self.assertEqual(tinkerer.mana, 9)

    def test_quest_branch_completes_on_matching_choice(self) -> None:
        """Drive quest completion from a YAML entry and an event payload."""

        bus = EventBus()
        quests = QuestSystem(bus)
        entries = load_definitions(FIXTURES / "exercise_quests.yaml")

        for entry in entries:
            # Keep the condition readable: compare a payload field to the expected branch value.
            condition = lambda event, field=entry["condition_field"], expected=entry["condition_value"]: event.payload.get(field) == expected  # noqa: E731
            quests.register_quest(
                identifier=entry["identifier"],
                description=entry["description"],
                trigger_event=entry["trigger_event"],
                owner=entry.get("owner"),
                reward_gold=entry.get("reward_gold", 0),
                condition=condition,
            )

        quest = quests.quests["talk-to-elder"]

        # Wrong branch: quest should stay untouched.
        bus.publish("npc.choice", choice="leave")
        self.assertEqual(quest.status, "new")

        # Helpful branch: completes and emits a reward event.
        bus.publish("npc.choice", choice="help-village")
        self.assertEqual(quest.status, "completed")


if __name__ == "__main__":
    unittest.main()
