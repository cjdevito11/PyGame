import tempfile
from pathlib import Path
import json
import tempfile
import unittest
from pathlib import Path

from core.registry import Registry
from core.validation import DefinitionValidator
from persistence.loader import load_definitions
from world.entities import Appearance, Item
from world.schemas import AppearanceDefinition, ItemDefinition


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = DefinitionValidator()
        self.validator.register_schema("appearances", AppearanceDefinition)

    def test_register_and_create(self) -> None:
        registry = Registry("appearances", self.validator, Appearance.from_definition)
        registry.register(
            {
                "name": "hero",
                "description": "trusty friend",
                "symbol": "@",
                "color": "yellow",
            }
        )

        self.assertEqual(["hero"], registry.entries())
        instance = registry.create("hero")
        self.assertEqual(instance.symbol, "@")

    def test_validation_error_is_friendly(self) -> None:
        registry = Registry("appearances", self.validator, Appearance.from_definition)
        with self.assertRaises(ValueError) as ctx:
            registry.register({"name": "ghost", "symbol": "G", "color": "white"})
        self.assertIn("description", str(ctx.exception))


class LoaderTests(unittest.TestCase):
    def test_dynamic_loading_from_disk(self) -> None:
        validator = DefinitionValidator()
        validator.register_schema("items", ItemDefinition)
        registry = Registry("items", validator, Item.from_definition)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "items.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "name": "potion",
                            "description": "Heals a small amount of health.",
                            "slot": "consumable",
                            "power": 5,
                        }
                    ]
                )
            )
            definitions = load_definitions(path)
            registry.load_many(definitions)

        self.assertIn("potion", registry.entries())
        created = registry.create("potion")
        self.assertEqual(created.power, 5)

    def test_yaml_payload_and_structure_validation(self) -> None:
        validator = DefinitionValidator()
        validator.register_schema("appearances", AppearanceDefinition)
        registry = Registry("appearances", validator, Appearance.from_definition)

        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "appearances.yaml"
            yaml_path.write_text(
                """
                - name: smiley
                  description: Friendly face.
                  symbol: ":"
                  color: green
                """
            )

            definitions = load_definitions(yaml_path)
            registry.load_many(definitions)

            # corrupted content should surface as a friendly ValueError
            bad_yaml_path = Path(tmpdir) / "bad.yaml"
            bad_yaml_path.write_text("- just-a-string")
            with self.assertRaises(ValueError):
                load_definitions(bad_yaml_path)

        self.assertIn("smiley", registry.entries())


if __name__ == "__main__":
    unittest.main()
