"""Pydantic schemas describing data-driven game entities."""
from core.pydantic_compat import BaseModel, Field


class BaseDefinition(BaseModel):
    name: str = Field(..., description="Unique id for the entry")
    description: str

    class Config:
        extra = "forbid"


class AppearanceDefinition(BaseDefinition):
    symbol: str = Field(..., min_length=1, max_length=1)
    color: str


class ClassDefinition(BaseDefinition):
    hit_points: int = Field(..., ge=1, le=999)
    mana: int = Field(..., ge=0, le=999)


class ItemDefinition(BaseDefinition):
    slot: str
    power: int = Field(..., ge=0)


class CharacterDefinition(BaseDefinition):
    class_name: str = Field(..., description="Name of a class definition to use")
    appearance: str = Field(..., description="Appearance to display")
    items: list[str] = Field(default=[])
    gold: int = Field(default=0, ge=0)


class BoundsDefinition(BaseModel):
    x: int
    y: int
    width: int
    height: int


class SpawnRuleDefinition(BaseModel):
    spawn: str
    weight: int = Field(..., ge=1)
    max_count: int | None = Field(default=None, ge=1)


class ZoneDefinition(BaseDefinition):
    bounds: BoundsDefinition
    danger_level: str
    spawn_rules: list[SpawnRuleDefinition] = Field(default_factory=list)
    is_static: bool = Field(default=True)
