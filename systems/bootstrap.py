"""Wires together registries, schemas, and persistence for the CLI demo."""
from pathlib import Path
from typing import Dict

from core.registry import Registry
from core.validation import DefinitionValidator
from persistence.loader import load_definitions
from world.entities import Appearance, CharacterClass, Item
from world.schemas import AppearanceDefinition, ClassDefinition, ItemDefinition


class RegistryBundle:
    def __init__(self, base_path: Path) -> None:
        self.validator = DefinitionValidator()
        self._register_schemas()
        self.base_path = base_path
        self.appearances = Registry("appearances", self.validator, Appearance.from_definition)
        self.classes = Registry("classes", self.validator, CharacterClass.from_definition)
        self.items = Registry("items", self.validator, Item.from_definition)

    def _register_schemas(self) -> None:
        self.validator.register_schema("appearances", AppearanceDefinition)
        self.validator.register_schema("classes", ClassDefinition)
        self.validator.register_schema("items", ItemDefinition)

    def load(self) -> None:
        datasets: Dict[str, list] = {}
        for file_name in ("appearances.yaml", "classes.yaml", "items.json"):
            path = self.base_path / file_name
            if path.exists():
                datasets[path.stem] = load_definitions(path)
        if "appearances" in datasets:
            self.appearances.load_many(datasets["appearances"])
        if "classes" in datasets:
            self.classes.load_many(datasets["classes"])
        if "items" in datasets:
            self.items.load_many(datasets["items"])
