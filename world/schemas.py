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
    resource_type: str = Field(default="mana")
    resource_max: int = Field(default=0, ge=0, le=999)
    resource_regen: int = Field(default=0, ge=0, le=99)
    gcd_seconds: float = Field(default=1.2, ge=0, le=60)


class ItemDefinition(BaseDefinition):
    slot: str
    power: int = Field(default=0)
    defense: int = Field(default=0)
    speed: int = Field(default=0)
    item_type: str = Field(default="equipment", description="equipment or consumable")
    duration_turns: int = Field(default=0, ge=0)
    capacity_bonus: int = Field(default=0, ge=0)
    max_durability: int = Field(default=0, ge=0)
    set_name: str | None = Field(default=None)
    value: int = Field(default=0, ge=0)
    appearance_states: list[str] = Field(default_factory=list)
    quest_item: bool = Field(default=False)
    rarity: str | None = Field(default=None)
    sockets: int = Field(default=0, ge=0)
    enchant: str | None = Field(default=None)
    tertiary: str | None = Field(default=None)
    on_use: str | None = Field(default=None)
    loot_table: str | None = Field(default=None)


class CharacterDefinition(BaseDefinition):
    class_name: str = Field(..., description="Name of a class definition to use")
    appearance: str = Field(..., description="Appearance to display")
    items: list[str] = Field(default=[])
    gold: int = Field(default=0, ge=0)
    bag_capacity: int = Field(default=10, ge=1)
    family: str | None = Field(default=None)
    stats: dict[str, int] = Field(default_factory=dict)
    skills: dict[str, int] = Field(default_factory=dict)


class AbilityDefinition(BaseDefinition):
    class_name: str = Field(..., description="Class that owns the spell or skill")
    resource_type: str = Field(default="mana")
    cost: int = Field(default=0, ge=0)
    cooldown_turns: int = Field(default=0, ge=0)
    gcd_turns: int = Field(default=1, ge=0)
    power: int = Field(default=0)
    heal: int = Field(default=0)
    range: int = Field(default=1, ge=0)
    school: str = Field(default="physical")
    cast_time: float = Field(default=0.0, ge=0, le=10)
    tags: list[str] = Field(default_factory=list)


class TalentNodeDefinition(BaseModel):
    id: str
    name: str
    description: str
    max_rank: int = Field(default=1, ge=1, le=10)
    row: int = Field(default=0, ge=0, le=8)
    column: int = Field(default=0, ge=0, le=8)
    requires: list[str] = Field(default_factory=list)
    grants_ability: list[str] = Field(default_factory=list)


class TalentTierDefinition(BaseModel):
    name: str
    min_points: int = Field(default=0, ge=0, le=99)
    nodes: list[TalentNodeDefinition] = Field(default_factory=list)


class TalentTreeDefinition(BaseDefinition):
    class_name: str
    total_points: int = Field(default=6, ge=0, le=99)
    tiers: list[TalentTierDefinition] = Field(default_factory=list)


class ProfessionDefinition(BaseDefinition):
    type: str
    perks: list[str] = Field(default_factory=list)


class RecipeDefinition(BaseDefinition):
    profession: str
    reagents: list[str]
    result: str
    skill_required: int = Field(default=0, ge=0)
    teaches: list[str] = Field(default_factory=list)


class MonsterFamilyDefinition(BaseDefinition):
    resistances: dict[str, int] = Field(default_factory=dict)
    immunities: list[str] = Field(default_factory=list)
    rarity_bias: dict[str, int] = Field(default_factory=dict)


class BoundsDefinition(BaseModel):
    x: int
    y: int
    width: int
    height: int


class SpawnRuleDefinition(BaseModel):
    spawn: str
    weight: int = Field(..., ge=1)
    max_count: int | None = Field(default=None, ge=1)


class SpawnPointDefinition(BaseModel):
    x: int
    y: int


class EncounterTableDefinition(BaseModel):
    table: str
    weight: int = Field(default=1, ge=1)


class ZoneDefinition(BaseDefinition):
    bounds: BoundsDefinition
    danger_level: str
    spawn_rules: list[SpawnRuleDefinition] = Field(default_factory=list)
    obstacles: list[BoundsDefinition] = Field(default_factory=list)
    spawn_points: dict[str, SpawnPointDefinition] = Field(default_factory=dict)
    encounter_tables: dict[str, list[EncounterTableDefinition]] = Field(default_factory=dict)
    background: str = Field(default="#101218")
    theme: str | None = None
    seed: int | None = None
    start_zone: bool = Field(default=False)
    is_static: bool = Field(default=True)
