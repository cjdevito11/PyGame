"""World package exposing shared entity interfaces."""

from .protocols import Ability, AppearanceTrait, BaseCharacter, Item, Quest, Skill, StatBlock, WorldState  # noqa: F401
from .zones import (  # noqa: F401
    SpawnRule,
    Zone,
    ZoneBounds,
    ZoneManager,
    ZoneRegistry,
    create_outdoor_zone,
)
