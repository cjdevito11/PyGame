"""Integration tests for the event-driven systems."""
from pathlib import Path

import pytest

from systems import CombatSystem, EconomySystem, EventBus, QuestSystem, RegistryBundle


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_combat(bus: EventBus) -> tuple[CombatSystem, RegistryBundle]:
    bundle = RegistryBundle(DATA_DIR)
    bundle.load()
    combat = CombatSystem(bus, class_registry=bundle.classes, item_registry=bundle.items)
    for name in bundle.characters.entries():
        profile = bundle.characters.create(name)
        combat.register_character(profile.name, profile.class_name, profile.items, gold=profile.gold)
    return combat, bundle


def test_event_flow_completes_quests_and_rewards_gold() -> None:
    bus = EventBus()
    combat, bundle = _load_combat(bus)
    quests = QuestSystem(bus)
    economy = EconomySystem(bus, item_registry=bundle.items, combat_system=combat)
    economy.register_store("camp", {"lantern": 2, "bronze_sword": 4})

    for character in combat.characters.values():
        economy.sync_wallet(character.name, character.gold)

    bonus_log: list[str] = []

    def custom_bonus(event):
        event.payload["bonus_damage"] = event.payload.get("bonus_damage", 0) + 5
        bonus_log.append("applied")

    def post_attack(event):
        bonus_log.append(f"after-{event.name}")

    bus.add_hook("combat.attack", pre=custom_bonus, post=post_attack)

    quests.register_quest(
        identifier="defeat-shade",
        description="Beat Shade to unlock rewards",
        trigger_event="combat.defeated",
        owner="Aria",
        reward_gold=7,
        condition=lambda event: event.payload.get("defender") == "Shade",
    )
    bus.publish("quest.accepted", quest="defeat-shade", owner="Aria")

    bus.publish("combat.attack", attacker="Aria", defender="Shade", weapon="bronze_sword")

    assert "applied" in bonus_log
    assert combat.characters["Shade"].hit_points <= 0
    assert quests.quests["defeat-shade"].status == "completed"

    bus.publish("quest.turned_in", quest="defeat-shade", owner="Aria")
    assert quests.quests["defeat-shade"].status == "turned_in"
    assert economy.wallets["Aria"] == 12  # 5 starting gold + 7 reward

    bus.publish(
        "economy.purchase",
        buyer="Aria",
        store="camp",
        item="lantern",
        price_modifier=lambda cost: cost - 1,
    )

    assert any(item.name == "lantern" for item in combat.characters["Aria"].inventory)
    assert economy.wallets["Aria"] == 11


def test_purchase_rejects_unknown_items() -> None:
    bus = EventBus()
    combat, bundle = _load_combat(bus)
    economy = EconomySystem(bus, item_registry=bundle.items, combat_system=combat)
    economy.register_store("camp", {"lantern": 3})
    economy.sync_wallet("Aria", 1)

    with pytest.raises(ValueError):
        bus.publish("economy.purchase", buyer="Aria", store="camp", item="lantern")
