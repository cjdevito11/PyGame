"""Small CLI that demonstrates data-driven registries."""
import argparse
from pathlib import Path

from systems.bootstrap import RegistryBundle


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
    list_parser.add_argument("registry", choices=["appearances", "classes", "items"])

    show_parser = subparsers.add_parser("show", help="Display a specific entry")
    show_parser.add_argument("registry", choices=["appearances", "classes", "items"])
    show_parser.add_argument("name", help="Registered name to display")

    validate_parser = subparsers.add_parser(
        "validate", help="Validate data files and summarize available entries"
    )
    validate_parser.add_argument(
        "--registry",
        choices=["appearances", "classes", "items"],
        help="Limit validation to a single registry.",
    )

    return parser


def run(argv: list[str] | None = None) -> int:
    """Execute the CLI, returning a status code for easier testing."""

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        bundle = RegistryBundle(args.data_path)
        bundle.load()
    except Exception as exc:  # pragma: no cover - smoke tested via CLI
        print(f"Failed to load data: {exc}")
        return 1

    registry_map = {
        "appearances": bundle.appearances,
        "classes": bundle.classes,
        "items": bundle.items,
    }

    if args.command in {"list", "show"}:
        registry = registry_map[args.registry]

    if args.command == "list":
        print("Available entries:")
        for name in registry.entries():
            print(f"- {name}")
        return 0
    if args.command == "show":
        try:
            instance = registry.create(args.name)
        except KeyError as exc:
            print(str(exc))
            return 1
        print(instance)
        return 0
    if args.command == "validate":
        registry_names = [args.registry] if args.registry else registry_map.keys()
        for name in registry_names:
            entries = registry_map[name].entries()
            if not entries:
                print(f"{name}: no entries found.")
                return 1
            print(f"{name}: {len(entries)} entries OK")
        print("All registry definitions are valid.")
        return 0

    parser.error("Unknown command")
    return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
