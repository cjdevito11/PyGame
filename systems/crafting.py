"""Professions and recipe-based crafting."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from core.logging_config import get_logger, log_with_fields
from core.registry import Registry
from systems.event_bus import EventBus
from world.entities import Item, Profession, Recipe


logger = get_logger(__name__)


@dataclass
class CrafterProgress:
    known_recipes: List[str] = field(default_factory=list)
    professions: List[str] = field(default_factory=list)
    skill: Dict[str, int] = field(default_factory=dict)


class CraftingSystem:
    def __init__(
        self,
        bus: EventBus,
        item_registry: Registry[Item],
        profession_registry: Registry[Profession],
        recipe_registry: Registry[Recipe],
    ) -> None:
        self.bus = bus
        self.item_registry = item_registry
        self.professions = profession_registry
        self.recipes = recipe_registry
        self.progress: Dict[str, CrafterProgress] = {}
        self.bus.subscribe("craft.learn", self._handle_learn)
        self.bus.subscribe("craft.execute", self._handle_execute)

    def ensure_profile(self, owner: str) -> CrafterProgress:
        if owner not in self.progress:
            self.progress[owner] = CrafterProgress()
        return self.progress[owner]

    def _handle_learn(self, event) -> Dict[str, object]:
        owner = event.payload["owner"]
        recipe_name = event.payload["recipe"]
        profile = self.ensure_profile(owner)
        if recipe_name not in profile.known_recipes:
            profile.known_recipes.append(recipe_name)
        return {"known_recipes": profile.known_recipes}

    def _handle_execute(self, event) -> Dict[str, object]:
        owner = event.payload["owner"]
        recipe_name = event.payload["recipe"]
        profile = self.ensure_profile(owner)
        if recipe_name not in profile.known_recipes:
            raise PermissionError("Recipe not known")
        recipe = self.recipes.create(recipe_name)
        item = self.item_registry.create(recipe.result)
        log_with_fields(logger, 20, "Crafted item", owner=owner, result=recipe.result)
        self.bus.publish("loot.grant", owner=owner, item=item.name, reason="craft")
        return {"result": item.name}
