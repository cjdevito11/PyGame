"""Lightweight command router to decouple parsing from business logic."""

from typing import Callable, Dict


class CommandRouter:
    """Maps parsed command names to handlers that implement the behavior."""

    def __init__(self) -> None:
        self._routes: Dict[str, Callable[[object], int]] = {}

    def register(self, name: str, handler: Callable[[object], int]) -> None:
        self._routes[name] = handler

    def dispatch(self, args: object) -> int:
        if args.command not in self._routes:
            raise KeyError(f"No handler registered for command '{args.command}'.")
        return self._routes[args.command](args)
