"""Zone definitions, helpers, and registry utilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import Callable, Dict, Iterable, List, Mapping, Sequence, Tuple


def _parse_color(value: str | Sequence[int]) -> Tuple[int, int, int]:
    if isinstance(value, str):
        value = value.lstrip("#")
        if len(value) == 6:
            r = int(value[0:2], 16)
            g = int(value[2:4], 16)
            b = int(value[4:6], 16)
            return (r, g, b)
    elif len(value) >= 3:
        return (int(value[0]), int(value[1]), int(value[2]))
    return (16, 18, 24)


@dataclass
class ZoneBounds:
    """Axis-aligned rectangle describing a zone's spatial limits."""

    x: int
    y: int
    width: int
    height: int

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px <= self.x + self.width and self.y <= py <= self.y + self.height

    def to_dict(self) -> Dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, data: Mapping[str, int]) -> "ZoneBounds":
        return cls(
            x=int(data["x"]),
            y=int(data["y"]),
            width=int(data["width"]),
            height=int(data["height"]),
        )


@dataclass
class SpawnRule:
    """Describes how and when a creature or prop can appear in a zone."""

    spawn: str
    weight: int
    max_count: int | None = None

    @classmethod
    def from_definition(cls, data: Mapping) -> "SpawnRule":
        return cls(spawn=data["spawn"], weight=int(data["weight"]), max_count=data.get("max_count"))


@dataclass
class SpawnPoint:
    """A location used to place actors when a zone is entered."""

    x: int
    y: int

    def as_tuple(self) -> Tuple[int, int]:
        return (self.x, self.y)

    @classmethod
    def from_definition(cls, data: Mapping[str, int]) -> "SpawnPoint":
        return cls(x=int(data["x"]), y=int(data["y"]))


@dataclass
class ZoneConnection:
    """Describes how to travel from one zone into another."""

    zone: str
    entry_direction: str | None = None
    entry_spawn: str | None = None

    @classmethod
    def from_definition(cls, data: Mapping[str, object]) -> "ZoneConnection":
        return cls(
            zone=str(data["zone"]),
            entry_direction=data.get("entry_direction"),
            entry_spawn=data.get("entry_spawn"),
        )


@dataclass
class EncounterTableRef:
    """Reference to an encounter table with a selection weight."""

    table: str
    weight: int = 1

    @classmethod
    def from_definition(cls, data: Mapping) -> "EncounterTableRef":
        return cls(table=data["table"], weight=int(data.get("weight", 1)))


@dataclass
class Zone:
    """In-memory representation of an explorable area."""

    name: str
    description: str
    bounds: ZoneBounds
    danger_level: str
    spawn_rules: List[SpawnRule]
    obstacles: List[ZoneBounds]
    spawn_points: Dict[str, SpawnPoint]
    connections: Dict[str, ZoneConnection] = field(default_factory=dict)
    encounter_tables: Dict[str, List[EncounterTableRef]] = field(default_factory=dict)
    background: Tuple[int, int, int]
    theme: str | None = None
    seed: int | None = None
    start_zone: bool = False
    is_static: bool = True

    @classmethod
    def from_definition(cls, name: str, data: Mapping) -> "Zone":
        bounds = ZoneBounds.from_dict(data["bounds"])
        spawn_rules = [SpawnRule.from_definition(entry) for entry in data.get("spawn_rules", [])]
        obstacle_defs = data.get("obstacles", [])
        obstacles = [ZoneBounds.from_dict(entry) for entry in obstacle_defs]
        spawn_points = {
            key: SpawnPoint.from_definition(value)
            for key, value in data.get("spawn_points", {}).items()
        }
        connections = {
            direction: ZoneConnection.from_definition(value)
            for direction, value in data.get("connections", {}).items()
        }
        encounter_tables = {
            category: [EncounterTableRef.from_definition(entry) for entry in entries]
            for category, entries in data.get("encounter_tables", {}).items()
        }
        return cls(
            name=name,
            description=data["description"],
            bounds=bounds,
            danger_level=data["danger_level"],
            spawn_rules=spawn_rules,
            obstacles=obstacles,
            spawn_points=spawn_points,
            connections=connections,
            encounter_tables=encounter_tables,
            background=_parse_color(data.get("background", "#101218")),
            theme=data.get("theme"),
            seed=data.get("seed"),
            start_zone=bool(data.get("start_zone", False)),
            is_static=bool(data.get("is_static", True)),
        )

    def summarize(self) -> str:
        return f"{self.name} — danger: {self.danger_level}, bounds: {self.bounds.width}x{self.bounds.height}"

    def get_spawn_point(self, role: str, fallback: Tuple[int, int]) -> Tuple[int, int]:
        if role in self.spawn_points:
            return self.spawn_points[role].as_tuple()
        return fallback

    def map_settings(self) -> Dict[str, object]:
        return {
            "size": (self.bounds.width, self.bounds.height),
            "background": self.background,
            "theme": self.theme,
            "seed": self.seed,
        }

    def has_spawn(self, spawn_name: str) -> bool:
        return any(rule.spawn == spawn_name for rule in self.spawn_rules)


def create_outdoor_zone(
    *, seed: int | None = None, danger_level: str | None = None, focus_spawn: str | None = None
) -> Zone:
    """Generate a lightweight procedural wilderness zone."""

    rng = Random(seed)
    width = rng.randint(720, 1240)
    height = rng.randint(720, 1240)
    bounds = ZoneBounds(x=rng.randint(0, 120), y=rng.randint(0, 120), width=width, height=height)

    themes: Dict[str, Iterable[Dict[str, int | str | None]]] = {
        "wilds": (
            {"spawn": "wolf", "weight": 3, "max_count": 4},
            {"spawn": "boar", "weight": 2, "max_count": 3},
            {"spawn": "herb", "weight": 1, "max_count": 6},
            {"spawn": "bandit", "weight": 1, "max_count": 2},
        ),
        "highlands": (
            {"spawn": "gryphon", "weight": 2, "max_count": 2},
            {"spawn": "goat", "weight": 2, "max_count": 5},
            {"spawn": "ore-node", "weight": 1, "max_count": 3},
        ),
        "fen": (
            {"spawn": "slime", "weight": 3, "max_count": 6},
            {"spawn": "mosquito", "weight": 2, "max_count": 8},
            {"spawn": "shrub", "weight": 1, "max_count": 5},
        ),
    }
    selected_theme = rng.choice(list(themes))
    shuffled_rules = list(themes[selected_theme])
    rng.shuffle(shuffled_rules)
    chosen_rules = shuffled_rules[: rng.randint(2, len(shuffled_rules))]
    spawn_rules = [SpawnRule.from_definition(rule) for rule in chosen_rules]
    if focus_spawn and all(rule.spawn != focus_spawn for rule in spawn_rules):
        spawn_rules.append(SpawnRule(spawn=focus_spawn, weight=1, max_count=1))

    generated_danger = danger_level or rng.choice(["low", "medium", "high"])

    obstacles: List[ZoneBounds] = []
    for _ in range(rng.randint(1, 3)):
        ox = bounds.x + rng.randint(40, max(60, bounds.width // 3))
        oy = bounds.y + rng.randint(40, max(60, bounds.height // 3))
        obstacles.append(
            ZoneBounds(
                x=ox,
                y=oy,
                width=rng.randint(80, 180),
                height=rng.randint(60, 160),
            )
        )

    spawn_points = {
        "player": SpawnPoint(bounds.x + bounds.width // 2 - 80, bounds.y + bounds.height // 2 + 60),
        "quest_giver": SpawnPoint(bounds.x + bounds.width // 2, bounds.y + bounds.height // 2),
        "quest_target": SpawnPoint(bounds.x + bounds.width // 2 + 180, bounds.y + bounds.height // 2),
    }

    encounter_tables = {
        "wilderness": [
            EncounterTableRef(table=f"{selected_theme}-creatures", weight=2),
            EncounterTableRef(table=f"{selected_theme}-foraging", weight=1),
        ]
    }

    return Zone(
        name=f"{selected_theme}-expanse-{rng.randint(1000, 9999)}",
        description=f"A procedurally generated {selected_theme} outside the settled roads.",
        bounds=bounds,
        danger_level=generated_danger,
        spawn_rules=spawn_rules,
        obstacles=obstacles,
        spawn_points=spawn_points,
        encounter_tables=encounter_tables,
        connections={},
        background=(18, 20, 26),
        theme=selected_theme,
        seed=seed,
        start_zone=False,
        is_static=False,
    )


class ZoneRegistry:
    """Tracks available zones and the currently active one."""

    def __init__(
        self,
        static_zones: Sequence[Zone],
        *,
        procedural_factory: Callable[..., Zone] | None = None,
    ) -> None:
        self._static_zones: Dict[str, Zone] = {zone.name: zone for zone in static_zones}
        self._procedural_factory = procedural_factory or create_outdoor_zone
        default_zone = next((zone for zone in static_zones if zone.start_zone), None)
        self._active_zone: Zone | None = default_zone or next(iter(static_zones), None)
        self._generated_zones: List[Zone] = []

    @property
    def active_zone(self) -> Zone | None:
        return self._active_zone

    @property
    def static_zones(self) -> List[str]:
        return sorted(self._static_zones)

    @property
    def generated_zones(self) -> Sequence[Zone]:
        return tuple(self._generated_zones)

    def set_active(self, name: str) -> Zone:
        if name not in self._static_zones:
            available = ", ".join(self.static_zones) or "none"
            raise KeyError(f"Zone '{name}' is not available. Known static zones: {available}.")
        self._active_zone = self._static_zones[name]
        return self._active_zone

    def spawn_outdoor_zone(
        self, *, seed: int | None = None, danger_level: str | None = None, focus_spawn: str | None = None
    ) -> Zone:
        zone = self._procedural_factory(seed=seed, danger_level=danger_level, focus_spawn=focus_spawn)
        self._generated_zones.append(zone)
        self._active_zone = zone
        return zone

    def describe_active(self) -> str:
        if not self._active_zone:
            return "No zone selected"
        return self._active_zone.summarize()

    def map_settings(self) -> Dict[str, object]:
        if not self._active_zone:
            return {"size": (960, 640), "background": (16, 18, 24)}
        return self._active_zone.map_settings()

    def spawn_point(self, role: str, fallback: Tuple[int, int]) -> Tuple[int, int]:
        if not self._active_zone:
            return fallback
        return self._active_zone.get_spawn_point(role, fallback)


# Preserve backwards compatibility for older imports
ZoneManager = ZoneRegistry
