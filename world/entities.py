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
    resource_type: str = "mana"
    resource_max: int = 0
    resource_regen: int = 0
    gcd_seconds: float = 1.2

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "CharacterClass":
        return cls(
            name=name,
            description=data["description"],
            hit_points=data["hit_points"],
            mana=data["mana"],
            resource_type=data.get("resource_type", data.get("primary_resource", "mana")),
            resource_max=data.get("resource_max", data.get("mana", 0)),
            resource_regen=data.get("resource_regen", 0),
            gcd_seconds=float(data.get("gcd_seconds", 1.2)),
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
    rarity: str | None = None
    sockets: int = 0
    enchant: str | None = None
    tertiary: str | None = None
    on_use: str | None = None
    loot_table: str | None = None

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
            rarity=data.get("rarity"),
            sockets=int(data.get("sockets", 0)),
            enchant=data.get("enchant"),
            tertiary=data.get("tertiary"),
            on_use=data.get("on_use"),
            loot_table=data.get("loot_table"),
        )


@dataclass
class Ability:
    name: str
    description: str
    class_name: str
    resource_type: str
    cost: int
    cooldown_turns: int
    gcd_turns: int
    power: int
    heal: int
    range: int
    school: str
    cast_time: float
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "Ability":
        return cls(
            name=name,
            description=data["description"],
            class_name=data["class_name"],
            resource_type=data.get("resource_type", "mana"),
            cost=int(data.get("cost", 0)),
            cooldown_turns=int(data.get("cooldown_turns", 0)),
            gcd_turns=int(data.get("gcd_turns", 1)),
            power=int(data.get("power", 0)),
            heal=int(data.get("heal", 0)),
            range=int(data.get("range", 1)),
            school=data.get("school", "physical"),
            cast_time=float(data.get("cast_time", 0.0)),
            tags=list(data.get("tags", [])),
        )


@dataclass
class TalentNode:
    id: str
    name: str
    description: str
    max_rank: int = 1
    row: int = 0
    column: int = 0
    requires: list[str] = field(default_factory=list)
    grants_ability: list[str] = field(default_factory=list)

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "TalentNode":
        return cls(
            id=data.get("id", name),
            name=data.get("name", name.title()),
            description=data.get("description", ""),
            max_rank=int(data.get("max_rank", 1)),
            row=int(data.get("row", 0)),
            column=int(data.get("column", 0)),
            requires=list(data.get("requires", [])),
            grants_ability=list(data.get("grants_ability", [])),
        )


@dataclass
class TalentTier:
    name: str
    min_points: int
    nodes: list[TalentNode]

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "TalentTier":
        nodes = [TalentNode.from_definition(entry.get("id", node_name), entry) for node_name, entry in enumerate(data.get("nodes", []))]
        return cls(name=data.get("name", name), min_points=int(data.get("min_points", 0)), nodes=nodes)


@dataclass
class TalentTree:
    name: str
    description: str
    class_name: str
    total_points: int
    tiers: list[TalentTier]

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "TalentTree":
        tiers = [TalentTier.from_definition(f"tier-{idx}", entry) for idx, entry in enumerate(data.get("tiers", []))]
        return cls(
            name=name,
            description=data.get("description", ""),
            class_name=data.get("class_name", ""),
            total_points=int(data.get("total_points", 0)),
            tiers=tiers,
        )


@dataclass
class Profession:
    name: str
    description: str
    type: str
    perks: list[str] = field(default_factory=list)

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "Profession":
        return cls(name=name, description=data["description"], type=data["type"], perks=list(data.get("perks", [])))


@dataclass
class Recipe:
    name: str
    description: str
    profession: str
    reagents: list[str]
    result: str
    skill_required: int = 0
    teaches: list[str] = field(default_factory=list)

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "Recipe":
        return cls(
            name=name,
            description=data["description"],
            profession=data["profession"],
            reagents=list(data.get("reagents", [])),
            result=data.get("result", ""),
            skill_required=int(data.get("skill_required", 0)),
            teaches=list(data.get("teaches", [])),
        )


@dataclass
class MonsterFamily:
    name: str
    description: str
    resistances: dict[str, int] = field(default_factory=dict)
    immunities: list[str] = field(default_factory=list)
    rarity_bias: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "MonsterFamily":
        return cls(
            name=name,
            description=data["description"],
            resistances=dict(data.get("resistances", {})),
            immunities=list(data.get("immunities", [])),
            rarity_bias=dict(data.get("rarity_bias", {})),
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
    family: str | None = None
    stats: dict[str, int] = field(default_factory=dict)
    skills: dict[str, int] = field(default_factory=dict)
    level: int = 1

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "CharacterProfile":
        return cls(
            name=name,
            class_name=data["class_name"],
            appearance=data["appearance"],
            items=list(data.get("items", [])),
            gold=int(data.get("gold", 0)),
            bag_capacity=int(data.get("bag_capacity", 10)),
            family=data.get("family"),
            stats=dict(data.get("stats", {})),
            skills=dict(data.get("skills", {})),
            level=int(data.get("level", 1)),
        )
