"""Small CLI that demonstrates data-driven registries and event systems."""
import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from core.logging_config import get_logger, log_with_fields
from systems import (
    CombatSystem,
    CommandRouter,
    EconomySystem,
    EventBus,
    QuestSystem,
    RegistryBundle,
)


logger = get_logger(__name__)


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

    play_parser = subparsers.add_parser(
        "play", help="Run a lightweight duel loop between two characters"
    )
    play_parser.add_argument(
        "--player",
        default="Aria",
        help="Character controlled by the player (defaults to Aria)",
    )
    play_parser.add_argument(
        "--enemy",
        default="Shade",
        help="Opponent to fight against (defaults to Shade)",
    )
    play_parser.add_argument(
        "--weapon",
        default=None,
        help="Optional weapon name to auto-equip for the player",
    )
    play_parser.add_argument(
        "--actions",
        help="Comma-separated actions for non-interactive runs (attack,buy,inspect,quit)",
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

    debug_parser = subparsers.add_parser("debug", help="Sandbox-only helper commands")
    debug_sub = debug_parser.add_subparsers(dest="debug_command", required=True)

    spawn_parser = debug_sub.add_parser("spawn", help="Give a character a new item")
    spawn_parser.add_argument("character")
    spawn_parser.add_argument("item")

    inspect_parser = debug_sub.add_parser("inspect", help="Inspect a character without changing them")
    inspect_parser.add_argument("character")

    simulate_parser = debug_sub.add_parser("simulate", help="Preview a fight without hurting anyone")
    simulate_parser.add_argument("attacker")
    simulate_parser.add_argument("defender")
    simulate_parser.add_argument("--weapon", default=None)
    simulate_parser.add_argument("--bonus", type=int, default=0)

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
        log_with_fields(logger, logging.INFO, "Listing entries", registry=args.registry)
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
        log_with_fields(logger, logging.INFO, "Validated data", registries=list(registry_names))
        print("All registry definitions are valid.")
        return 0

    def handle_attack(args: object) -> int:
        if args.attacker not in context.combat.characters or args.defender not in context.combat.characters:
            print("Both attacker and defender must exist in the roster.")
            return 1
        log_with_fields(
            logger,
            logging.INFO,
            "Running attack",
            attacker=args.attacker,
            defender=args.defender,
            weapon=args.weapon or "unarmed",
            bonus=args.bonus,
        )
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

    def describe(character) -> str:
        items = ", ".join(item.name for item in character.inventory) or "unarmed"
        gold = context.economy.wallets.get(character.name, character.gold)
        return f"{character.name}: {character.hit_points} HP, gold={gold}, items={items}"

    def handle_play(args: object) -> int:
        player = context.combat.characters.get(args.player)
        enemy = context.combat.characters.get(args.enemy)
        if player is None or enemy is None:
            print("Both player and enemy must exist in the roster. Try --player Aria --enemy Shade.")
            return 1

        if args.weapon and all(item.name != args.weapon for item in player.inventory):
            try:
                context.combat.add_item(player.name, args.weapon)
            except Exception as exc:  # pragma: no cover - user feedback path
                print(f"Could not equip {args.weapon}: {exc}")
                return 1

        equipped_weapon = args.weapon or (player.inventory[0].name if player.inventory else None)

        scripted_actions: list[str] | None = None
        if args.actions is not None:
            scripted_actions = [action.strip().lower() for action in args.actions.split(",") if action.strip()]

        def prompt() -> str:
            if scripted_actions is not None:
                if scripted_actions:
                    return scripted_actions.pop(0)
                return "quit"
            return input("[a]ttack, [b]uy, [i]nspect, [q]uit: ").strip().lower()

        print("Welcome to the camp! Defeat your opponent to win a small reward.")
        print(describe(player))
        print(describe(enemy))

        while player.is_alive() and enemy.is_alive():
            action = prompt()
            if action in {"a", "attack"}:
                context.bus.publish(
                    "combat.attack", attacker=player.name, defender=enemy.name, weapon=equipped_weapon
                )
                if not enemy.is_alive():
                    break
                context.bus.publish("combat.attack", attacker=enemy.name, defender=player.name)
                print(describe(player))
                print(describe(enemy))
                continue

            if action in {"b", "buy"}:
                store = context.economy.stores.get("camp", {})
                if not store:
                    print("The camp store is empty today.")
                    continue
                print("Camp store (prices in gold):")
                for item_name, price in store.items():
                    print(f"- {item_name}: {price}")
                choice = prompt() if scripted_actions else input("Choose an item name to buy (or press Enter to skip): ")
                if not choice:
                    continue
                try:
                    context.bus.publish("economy.purchase", buyer=player.name, store="camp", item=choice)
                    print(f"Bought {choice}.")
                except Exception as exc:  # pragma: no cover - feedback path
                    print(f"Could not buy {choice}: {exc}")
                continue

            if action in {"i", "inspect"}:
                print(describe(player))
                print(describe(enemy))
                continue

            if action in {"q", "quit"}:
                print("Exiting duel. Come back soon!")
                return 0

            print("Unknown action. Try attack, buy, inspect, or quit.")

        if player.is_alive():
            print(f"{player.name} wins! Gold now: {context.economy.wallets[player.name]}")
            return 0
        print(f"{player.name} was defeated. Better luck next time.")
        return 1

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

    def handle_debug(args: object) -> int:
        if args.debug_command == "spawn":
            try:
                context.combat.add_item(args.character, args.item)
            except Exception as exc:
                print(f"Could not add {args.item} to {args.character}: {exc}")
                return 1
            print(f"Added {args.item} to {args.character}'s backpack.")
            return 0

        if args.debug_command == "inspect":
            character = context.combat.characters.get(args.character)
            if character is None:
                print(f"No character named {args.character} is loaded.")
                return 1
            items = ", ".join(item.name for item in character.inventory) or "nothing"
            print(
                f"{character.name}: class={character.class_name}, hp={character.hit_points}, "
                f"gold={character.gold}, items={items}"
            )
            return 0

        if args.debug_command == "simulate":
            try:
                preview = context.combat.preview_attack(
                    args.attacker,
                    args.defender,
                    weapon_name=args.weapon,
                    bonus_damage=args.bonus,
                )
            except Exception as exc:
                print(f"Could not simulate attack: {exc}")
                return 1
            print(
                f"Preview: {args.attacker} would deal {preview['damage']} damage. "
                f"{args.defender} would have {preview['remaining_hp']} HP left."
            )
            return 0

        print("Unknown debug command.")
        return 1

    router.register("list", handle_list)
    router.register("show", handle_show)
    router.register("validate", handle_validate)
    router.register("attack", handle_attack)
    router.register("quests", handle_quests)
    router.register("wallet", handle_wallet)
    router.register("buy", handle_buy)
    router.register("debug", handle_debug)
    router.register("play", handle_play)
    return router


def run(argv: list[str] | None = None) -> int:
    """Execute the CLI, returning a status code for easier testing."""

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        log_with_fields(logger, logging.INFO, "Building game context", data_path=str(args.data_path))
        context = build_context(args.data_path)
    except Exception as exc:  # pragma: no cover - smoke tested via CLI
        log_with_fields(logger, logging.ERROR, "Failed to load context", error=str(exc))
        print(f"Failed to load data: {exc}")
        return 1

    router = build_router(context)
    log_with_fields(logger, logging.INFO, "Dispatching CLI command", command=args.command)
    return router.dispatch(args)


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
