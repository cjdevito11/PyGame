"""Zone definitions and helpers for static and procedural areas."""
from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Callable, Dict, Iterable, List, Sequence


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


@dataclass
class SpawnRule:
    """Describes how and when a creature or prop can appear in a zone."""

    spawn: str
    weight: int
    max_count: int | None = None

    @classmethod
    def from_definition(cls, data: Dict) -> "SpawnRule":
        return cls(spawn=data["spawn"], weight=int(data["weight"]), max_count=data.get("max_count"))


@dataclass
class Zone:
    """In-memory representation of an explorable area."""

    name: str
    description: str
    bounds: ZoneBounds
    danger_level: str
    spawn_rules: List[SpawnRule]
    is_static: bool = True

    @classmethod
    def from_definition(cls, name: str, data: Dict) -> "Zone":
        bounds_data = data["bounds"]
        bounds = ZoneBounds(
            x=int(bounds_data["x"]),
            y=int(bounds_data["y"]),
            width=int(bounds_data["width"]),
            height=int(bounds_data["height"]),
        )
        spawn_rules = [SpawnRule.from_definition(entry) for entry in data.get("spawn_rules", [])]
        return cls(
            name=name,
            description=data["description"],
            bounds=bounds,
            danger_level=data["danger_level"],
            spawn_rules=spawn_rules,
            is_static=bool(data.get("is_static", True)),
        )

    def summarize(self) -> str:
        return f"{self.name} — danger: {self.danger_level}, bounds: {self.bounds.width}x{self.bounds.height}"


def create_outdoor_zone(*, seed: int | None = None, danger_level: str | None = None) -> Zone:
    """Generate a lightweight procedural wilderness zone.

    The generator is intentionally simple: it randomizes a bounding rectangle and
    pulls a handful of themed spawn rules to hint at different outdoor biomes.
    A seed can be supplied to make generation deterministic.
    """

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

    generated_danger = danger_level or rng.choice(["low", "medium", "high"])
    return Zone(
        name=f"{selected_theme}-expanse-{rng.randint(1000, 9999)}",
        description=f"A procedurally generated {selected_theme} outside the settled roads.",
        bounds=bounds,
        danger_level=generated_danger,
        spawn_rules=spawn_rules,
        is_static=False,
    )


class ZoneManager:
    """Tracks available zones and the currently active one."""

    def __init__(
        self,
        static_zones: Sequence[Zone],
        *,
        procedural_factory: Callable[..., Zone] | None = None,
    ) -> None:
        self._static_zones: Dict[str, Zone] = {zone.name: zone for zone in static_zones}
        self._procedural_factory = procedural_factory or create_outdoor_zone
        self._active_zone: Zone | None = next(iter(static_zones), None)
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

    def spawn_outdoor_zone(self, **kwargs) -> Zone:
        zone = self._procedural_factory(**kwargs)
        self._generated_zones.append(zone)
        self._active_zone = zone
        return zone

    def describe_active(self) -> str:
        if not self._active_zone:
            return "No zone selected"
        return self._active_zone.summarize()
