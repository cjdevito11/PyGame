"""Small CLI that demonstrates data-driven registries and event systems."""
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from systems import (
    CombatSystem,
    CommandRouter,
    EconomySystem,
    EventBus,
    QuestSystem,
    RegistryBundle,
)


@dataclass
class GameContext:
    bundle: RegistryBundle
    bus: EventBus
    combat: CombatSystem
    quests: QuestSystem
    economy: EconomySystem


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PyGame data-driven demo")
    parser.add_argument(
        "data_path",
        nargs="?",
        default=Path(__file__).resolve().parent.parent / "data",
        type=Path,
        help="Path to the data directory containing YAML/JSON definitions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List entries in a registry")
    list_parser.add_argument("registry", choices=["appearances", "classes", "items", "characters"])

    show_parser = subparsers.add_parser("show", help="Display a specific entry")
    show_parser.add_argument("registry", choices=["appearances", "classes", "items", "characters"])
    show_parser.add_argument("name", help="Registered name to display")

    validate_parser = subparsers.add_parser(
        "validate", help="Validate data files and summarize available entries"
    )
    validate_parser.add_argument(
        "--registry",
        choices=["appearances", "classes", "items", "characters"],
        help="Limit validation to a single registry.",
    )

    attack_parser = subparsers.add_parser("attack", help="Perform an attack between characters")
    attack_parser.add_argument("attacker")
    attack_parser.add_argument("defender")
    attack_parser.add_argument("--weapon", default=None)
    attack_parser.add_argument("--bonus", type=int, default=0, help="Bonus damage for testing plugins")

    quests_parser = subparsers.add_parser("quests", help="Show quest log")
    quests_parser.add_argument("--owner", help="Filter quests by owner", default=None)

    wallet_parser = subparsers.add_parser("wallet", help="Show a character's gold")
    wallet_parser.add_argument("name")

    buy_parser = subparsers.add_parser("buy", help="Purchase an item from the camp store")
    buy_parser.add_argument("buyer")
    buy_parser.add_argument("item")

    return parser


def build_context(data_path: Path) -> GameContext:
    bundle = RegistryBundle(data_path)
    bundle.load()
    bus = EventBus()
    combat = CombatSystem(bus, class_registry=bundle.classes, item_registry=bundle.items)

    for name in bundle.characters.entries():
        profile = bundle.characters.create(name)
        combat.register_character(profile.name, profile.class_name, profile.items, gold=profile.gold)

    economy = EconomySystem(bus, item_registry=bundle.items, combat_system=combat)
    for character in combat.characters.values():
        economy.sync_wallet(character.name, character.gold)
    economy.register_store("camp", {name: definition["power"] + 1 for name, definition in bundle.items.definitions().items()})

    quests = QuestSystem(bus)
    if "Aria" in combat.characters and "Shade" in combat.characters:
        quests.register_quest(
            identifier="defeat-shade",
            description="Defeat Shade to earn pocket money.",
            trigger_event="combat.defeated",
            owner="Aria",
            reward_gold=4,
            condition=lambda event: event.payload.get("defender") == "Shade",
        )
    return GameContext(bundle=bundle, bus=bus, combat=combat, quests=quests, economy=economy)


def build_router(context: GameContext) -> CommandRouter:
    router = CommandRouter()

    registry_map = {
        "appearances": context.bundle.appearances,
        "classes": context.bundle.classes,
        "items": context.bundle.items,
        "characters": context.bundle.characters,
    }

    def handle_list(args: object) -> int:
        registry = registry_map[args.registry]
        print("Available entries:")
        for name in registry.entries():
            print(f"- {name}")
        return 0

    def handle_show(args: object) -> int:
        registry = registry_map[args.registry]
        try:
            instance = registry.create(args.name)
        except KeyError as exc:
            print(str(exc))
            return 1
        print(instance)
        return 0

    def handle_validate(args: object) -> int:
        registry_names = [args.registry] if args.registry else registry_map.keys()
        for name in registry_names:
            entries = registry_map[name].entries()
            if not entries:
                print(f"{name}: no entries found.")
                return 1
            print(f"{name}: {len(entries)} entries OK")
        print("All registry definitions are valid.")
        return 0

    def handle_attack(args: object) -> int:
        if args.attacker not in context.combat.characters or args.defender not in context.combat.characters:
            print("Both attacker and defender must exist in the roster.")
            return 1
        context.bus.publish(
            "combat.attack",
            attacker=args.attacker,
            defender=args.defender,
            weapon=args.weapon,
            bonus_damage=args.bonus,
        )
        defender = context.combat.characters[args.defender]
        print(f"{args.defender} now has {defender.hit_points} HP")
        return 0

    def handle_quests(args: object) -> int:
        quests: Dict[str, object] = context.quests.quests
        for quest in quests.values():
            if args.owner and quest.owner != args.owner:
                continue
            print(f"{quest.identifier}: {quest.status} ({quest.description})")
        return 0

    def handle_wallet(args: object) -> int:
        gold = context.economy.wallets.get(args.name)
        if gold is None:
            print(f"No wallet found for {args.name}")
            return 1
        print(f"{args.name} has {gold} gold")
        return 0

    def handle_buy(args: object) -> int:
        try:
            context.bus.publish(
                "economy.purchase",
                buyer=args.buyer,
                store="camp",
                item=args.item,
            )
        except Exception as exc:  # pragma: no cover - user feedback path
            print(str(exc))
            return 1
        print(f"{args.buyer} bought {args.item}")
        return 0

    router.register("list", handle_list)
    router.register("show", handle_show)
    router.register("validate", handle_validate)
    router.register("attack", handle_attack)
    router.register("quests", handle_quests)
    router.register("wallet", handle_wallet)
    router.register("buy", handle_buy)
    return router


def run(argv: list[str] | None = None) -> int:
    """Execute the CLI, returning a status code for easier testing."""

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        context = build_context(args.data_path)
    except Exception as exc:  # pragma: no cover - smoke tested via CLI
        print(f"Failed to load data: {exc}")
        return 1

    router = build_router(context)
    return router.dispatch(args)


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
