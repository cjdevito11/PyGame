from pathlib import Path

from systems import RegistryBundle
from world.zones import ZoneManager, create_outdoor_zone

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def test_static_zones_load_from_data() -> None:
    bundle = RegistryBundle(DATA_DIR)
    bundle.load()

    names = bundle.zones.entries()
    assert "camp" in names
    camp = bundle.zones.create("camp")
    assert camp.bounds.width == 960
    assert any(rule.spawn == "vendor" for rule in camp.spawn_rules)
    assert camp.obstacles


def test_zone_manager_handles_procedural_zones() -> None:
    bundle = RegistryBundle(DATA_DIR)
    bundle.load()
    static_zones = [bundle.zones.create(name) for name in bundle.zones.entries()]
    manager = ZoneManager(static_zones)

    generated = manager.spawn_outdoor_zone(seed=42, danger_level="medium")

    assert manager.active_zone == generated
    assert generated.is_static is False
    assert generated.danger_level == "medium"
    assert generated.bounds.width >= 720
    assert manager.generated_zones[-1] == generated


def test_procedural_generation_is_repeatable() -> None:
    first = create_outdoor_zone(seed=1234)
    second = create_outdoor_zone(seed=1234)

    assert first.name == second.name
    assert first.bounds.to_dict() == second.bounds.to_dict()
    assert [rule.spawn for rule in first.spawn_rules] == [rule.spawn for rule in second.spawn_rules]
