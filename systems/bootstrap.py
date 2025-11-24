"""Wires together registries, schemas, and persistence for the Pygame demo."""
import logging
from pathlib import Path
from typing import Dict

from core.logging_config import get_logger, log_with_fields
from core.registry import Registry
from core.validation import DefinitionValidator
from persistence.loader import load_definitions
from world.entities import (
    Ability,
    Appearance,
    CharacterClass,
    CharacterProfile,
    Item,
    MonsterFamily,
    Profession,
    Recipe,
    TalentTree,
)
from world.schemas import (
    AbilityDefinition,
    AppearanceDefinition,
    CharacterDefinition,
    ClassDefinition,
    ItemDefinition,
    MonsterFamilyDefinition,
    ProfessionDefinition,
    RecipeDefinition,
    TalentTreeDefinition,
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
        self.abilities = Registry("abilities", self.validator, Ability.from_definition)
        self.talents = Registry("talents", self.validator, TalentTree.from_definition)
        self.professions = Registry("professions", self.validator, Profession.from_definition)
        self.recipes = Registry("recipes", self.validator, Recipe.from_definition)
        self.families = Registry("monster_families", self.validator, MonsterFamily.from_definition)

    def _register_schemas(self) -> None:
        self.validator.register_schema("appearances", AppearanceDefinition)
        self.validator.register_schema("classes", ClassDefinition)
        self.validator.register_schema("items", ItemDefinition)
        self.validator.register_schema("characters", CharacterDefinition)
        self.validator.register_schema("zones", ZoneDefinition)
        self.validator.register_schema("abilities", AbilityDefinition)
        self.validator.register_schema("talents", TalentTreeDefinition)
        self.validator.register_schema("professions", ProfessionDefinition)
        self.validator.register_schema("recipes", RecipeDefinition)
        self.validator.register_schema("monster_families", MonsterFamilyDefinition)

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
            "abilities.json",
            "talents.json",
            "professions.json",
            "recipes.json",
            "monster_families.json",
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
        if "abilities" in datasets:
            self.abilities.load_many(datasets["abilities"])
        if "talents" in datasets:
            self.talents.load_many(datasets["talents"])
        if "professions" in datasets:
            self.professions.load_many(datasets["professions"])
        if "recipes" in datasets:
            self.recipes.load_many(datasets["recipes"])
        if "monster_families" in datasets:
            self.families.load_many(datasets["monster_families"])
