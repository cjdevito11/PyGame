"""Positioning helpers and simple line-of-sight checks for encounters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from core.logging_config import get_logger, log_with_fields
from systems.event_bus import EventBus


logger = get_logger(__name__)


@dataclass
class Position:
    x: int
    y: int

    def distance_to(self, other: "Position") -> int:
        return abs(self.x - other.x) + abs(self.y - other.y)


class MovementSystem:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.positions: Dict[str, Position] = {}
        self.bus.subscribe("movement.set", self._handle_set)
        self.bus.subscribe("movement.step", self._handle_step)

    def set_position(self, name: str, position: Position) -> None:
        self.positions[name] = position
        log_with_fields(logger, 20, "Position set", name=name, x=position.x, y=position.y)

    def _handle_set(self, event) -> Dict[str, int]:
        name = event.payload["name"]
        pos = Position(**event.payload["position"])
        self.set_position(name, pos)
        return {"x": pos.x, "y": pos.y}

    def _handle_step(self, event) -> Dict[str, int]:
        name = event.payload["name"]
        dx = int(event.payload.get("dx", 0))
        dy = int(event.payload.get("dy", 0))
        current = self.positions.get(name, Position(0, 0))
        updated = Position(current.x + dx, current.y + dy)
        self.set_position(name, updated)
        return {"x": updated.x, "y": updated.y}

    def in_range(self, attacker: str, defender: str, max_range: int) -> bool:
        if attacker not in self.positions or defender not in self.positions:
            return True
        return self.positions[attacker].distance_to(self.positions[defender]) <= max_range
