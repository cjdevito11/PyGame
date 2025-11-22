"""Lightweight runtime objects for the demo game world."""
from dataclasses import dataclass
from typing import Dict


@dataclass
class Appearance:
    name: str
    description: str
    symbol: str
    color: str

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "Appearance":
        return cls(name=name, description=data["description"], symbol=data["symbol"], color=data["color"])


@dataclass
class CharacterClass:
    name: str
    description: str
    hit_points: int
    mana: int

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "CharacterClass":
        return cls(
            name=name,
            description=data["description"],
            hit_points=data["hit_points"],
            mana=data["mana"],
        )


@dataclass
class Item:
    name: str
    description: str
    slot: str
    power: int

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "Item":
        return cls(name=name, description=data["description"], slot=data["slot"], power=data["power"])
