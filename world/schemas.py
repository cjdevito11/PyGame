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
    hair: str = Field(default="short", description="Hair style descriptor")
    eyes: str = Field(default="brown", description="Eye color")
    outfit: str = Field(default="travel gear", description="Primary outfit descriptor")
    accent: str = Field(default="leather", description="Accent color or material")


class ClassDefinition(BaseDefinition):
    hit_points: int = Field(..., ge=1, le=999)
    mana: int = Field(..., ge=0, le=999)


class ItemDefinition(BaseDefinition):
    slot: str
    power: int = Field(..., ge=0)


class CharacterDefinition(BaseDefinition):
    class_name: str = Field(..., description="Name of a class definition to use")
    appearance: str = Field(..., description="Appearance to display")
    appearance_options: list[str] | None = Field(
        default=None, description="Optional appearance palette for hero customization"
    )
    items: list[str] = Field(default=[])
    gold: int = Field(default=0, ge=0)
    level: int = Field(default=1, ge=1, le=99)
    experience: int = Field(default=0, ge=0)
    role: str = Field(default="hero", description="Role tag used to drive spawning and selection")
