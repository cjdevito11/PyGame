"""Wires together registries, schemas, and persistence for the Pygame demo."""
import logging
from pathlib import Path
from typing import Dict

from core.logging_config import get_logger, log_with_fields
from core.registry import Registry
from core.validation import DefinitionValidator
from persistence.loader import load_definitions
from world.entities import Appearance, CharacterClass, CharacterProfile, Item
from world.schemas import (
    AppearanceDefinition,
    CharacterDefinition,
    ClassDefinition,
    ItemDefinition,
    ZoneDefinition,
)
from world.zones import Zone


class RegistryBundle:
    def __init__(self, base_path: Path) -> None:
        self.logger = get_logger(__name__)
        self.validator = DefinitionValidator()
        self._register_schemas()
        self.base_path = base_path
        self.appearances = Registry("appearances", self.validator, Appearance.from_definition)
        self.classes = Registry("classes", self.validator, CharacterClass.from_definition)
        self.items = Registry("items", self.validator, Item.from_definition)
        self.characters = Registry("characters", self.validator, CharacterProfile.from_definition)
        self.zones = Registry("zones", self.validator, Zone.from_definition)

    def _register_schemas(self) -> None:
        self.validator.register_schema("appearances", AppearanceDefinition)
        self.validator.register_schema("classes", ClassDefinition)
        self.validator.register_schema("items", ItemDefinition)
        self.validator.register_schema("characters", CharacterDefinition)
        self.validator.register_schema("zones", ZoneDefinition)

    def load(self) -> None:
        datasets: Dict[str, list] = {}
        for file_name in (
            "appearances.yaml",
            "classes.yaml",
            "items.json",
            "characters.yaml",
            "characters.json",
            "zones.yaml",
            "zones.json",
        ):
            path = self.base_path / file_name
            if path.exists():
                log_with_fields(self.logger, logging.INFO, "Loading dataset", path=str(path))
                datasets[path.stem] = load_definitions(path)
        if "appearances" in datasets:
            self.appearances.load_many(datasets["appearances"])
        if "classes" in datasets:
            self.classes.load_many(datasets["classes"])
        if "items" in datasets:
            self.items.load_many(datasets["items"])
        if "characters" in datasets:
            self.characters.load_many(datasets["characters"])
        if "zones" in datasets:
            self.zones.load_many(datasets["zones"])
