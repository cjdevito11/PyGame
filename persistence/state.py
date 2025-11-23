"""Simple JSON persistence for characters and inventories."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from core.logging_config import get_logger, log_with_fields
from systems.combat import CombatSystem


logger = get_logger(__name__)


def save_characters(path: Path, combat: CombatSystem) -> None:
    snapshot = {}
    for name, combatant in combat.characters.items():
        snapshot[name] = {
            "class_name": combatant.class_name,
            "hit_points": combatant.hit_points,
            "resources": combatant.resource_pools,
            "inventory": [item.name for item in combatant.inventory],
            "gold": combatant.gold,
            "bag_capacity": combatant.base_capacity,
            "family": combatant.family,
        }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2)
    log_with_fields(logger, 20, "Saved characters", path=str(path), count=len(snapshot))


def load_characters(path: Path, combat: CombatSystem) -> Dict[str, dict]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    for name, data in payload.items():
        combat.register_character(
            name,
            data["class_name"],
            data.get("inventory", []),
            gold=data.get("gold", 0),
            bag_capacity=data.get("bag_capacity", 10),
            family=data.get("family"),
        )
        combatant = combat.characters[name]
        combatant.hit_points = data.get("hit_points", combatant.hit_points)
        combatant.resource_pools.update(data.get("resources", {}))
    log_with_fields(logger, 20, "Loaded characters", path=str(path), count=len(payload))
    return payload
