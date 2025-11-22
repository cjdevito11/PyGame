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
