"""Integration tests for the event-driven systems."""
from __future__ import annotations

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
        combat.register_character(
            profile.name, profile.class_name, profile.items, gold=profile.gold, bag_capacity=profile.bag_capacity
        )
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
    loot_log: list[str] = []

    def custom_bonus(event):
        event.payload["bonus_damage"] = event.payload.get("bonus_damage", 0) + 5
        bonus_log.append("applied")

    def post_attack(event):
        bonus_log.append(f"after-{event.name}")

    bus.add_hook("combat.attack", pre=custom_bonus, post=post_attack)
    bus.subscribe("inventory.item_added", lambda event: loot_log.append(event.payload.get("item", "")))

    quests.register_quest(
        identifier="defeat-shade",
        description="Beat Shade to unlock rewards",
        trigger_event="combat.defeated",
        owner="Aria",
        reward_gold=7,
        reward_item="oak_shield",
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
    assert "oak_shield" in loot_log
    assert any(item.name == "oak_shield" for item in combat.characters["Aria"].inventory)

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


def test_defense_from_equipment_reduces_damage() -> None:
    bus = EventBus()
    combat, _ = _load_combat(bus)

    combat.add_item("Shade", "oak_shield")
    preview = combat.preview_attack("Aria", "Shade", weapon_name="bronze_sword")

    assert preview["damage"] == 2  # attack power 5 reduced by 3 defense


def test_consumable_buff_applies_and_expires() -> None:
    bus = EventBus()
    combat, _ = _load_combat(bus)

    combat.add_item("Aria", "speed_potion")
    bus.publish("inventory.consume", owner="Aria", item="speed_potion")

    boosted = combat.preview_attack("Aria", "Shade", weapon_name="bronze_sword")
    assert boosted["damage"] > 1

    for _ in range(3):
        bus.publish("combat.attack", attacker="Aria", defender="Shade", weapon="bronze_sword")

    assert not combat.characters["Aria"].buffs


def test_capacity_blocks_overflowing_loot() -> None:
    bus = EventBus()
    combat, _ = _load_combat(bus)
    combat.characters["Aria"].base_capacity = 1

    rejected: list[str] = []
    bus.subscribe("inventory.full", lambda event: rejected.append(event.payload["item"]))
    combat.add_item("Aria", "oak_shield")

    assert "oak_shield" in rejected


def test_repair_and_trading_flow() -> None:
    bus = EventBus()
    combat, bundle = _load_combat(bus)
    economy = EconomySystem(bus, item_registry=bundle.items, combat_system=combat)
    economy.register_store("camp", {"bronze_sword": 4})
    economy.sync_wallet("Aria", 20)
    combat.characters["Aria"].equipped["mainhand"].durability = 5

    bus.publish("economy.repair", owner="Aria", item="bronze_sword", rate=1)
    assert combat.characters["Aria"].equipped["mainhand"].durability == 18

    bus.publish("economy.sell", seller="Aria", store="camp", item="bronze_sword")
    assert economy.wallets["Aria"] > 0

    bus.publish("loot.grant", owner="Shade", item="obsidian_crown")
    bus.publish("trade.execute", giver="Shade", receiver="Aria", items=["obsidian_crown"], gold=0)
    assert any(item.name == "obsidian_crown" for item in combat.characters["Aria"].inventory)


def test_set_bonus_contributes_to_attack_and_defense() -> None:
    bus = EventBus()
    combat, _ = _load_combat(bus)

    combat.add_item("Aria", "obsidian_blade")
    combat.add_item("Aria", "obsidian_crown")
    combat.add_item("Aria", "hardened_mail")

    power = combat.preview_attack("Aria", "Shade", weapon_name="obsidian_blade")["damage"]
    combat.add_item("Shade", "hardened_mail")
    defense = combat.preview_attack("Aria", "Shade", weapon_name="obsidian_blade")["damage"]

    assert power > 1
    assert defense < power
