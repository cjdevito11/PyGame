"""Lightweight runtime objects for the demo game world."""
from dataclasses import dataclass, field
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
    defense: int = 0
    speed: int = 0
    item_type: str = "equipment"
    duration_turns: int = 0
    capacity_bonus: int = 0
    max_durability: int = 0
    durability: int | None = None
    set_name: str | None = None
    value: int = 0
    appearance_states: list[str] = field(default_factory=list)
    quest_item: bool = False

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "Item":
        return cls(
            name=name,
            description=data["description"],
            slot=data["slot"],
            power=data.get("power", 0),
            defense=data.get("defense", 0),
            speed=data.get("speed", 0),
            item_type=data.get("item_type", "equipment"),
            duration_turns=data.get("duration_turns", 0),
            capacity_bonus=data.get("capacity_bonus", 0),
            max_durability=data.get("max_durability", 0),
            durability=data.get("max_durability", 0) or data.get("durability"),
            set_name=data.get("set_name"),
            value=data.get("value", 0),
            appearance_states=list(data.get("appearance_states", [])),
            quest_item=bool(data.get("quest_item", False)),
        )


@dataclass
class CharacterProfile:
    """Lightweight container describing how to instantiate a character."""

    name: str
    class_name: str
    appearance: str
    items: list[str]
    gold: int
    bag_capacity: int = 10

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "CharacterProfile":
        return cls(
            name=name,
            class_name=data["class_name"],
            appearance=data["appearance"],
            items=list(data.get("items", [])),
            gold=int(data.get("gold", 0)),
            bag_capacity=int(data.get("bag_capacity", 10)),
        )
