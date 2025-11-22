"""Lightweight command router to decouple parsing from business logic."""

from __future__ import annotations

import logging
import time
from typing import Callable, Dict

from core.logging_config import get_logger, log_with_fields


class CommandRouter:
    """Maps parsed command names to handlers that implement the behavior."""

    def __init__(self, *, io_retries: int = 1, retry_delay: float = 0.05) -> None:
        self._routes: Dict[str, Callable[[object], int]] = {}
        self._logger = get_logger(__name__)
        self.io_retries = io_retries
        self.retry_delay = retry_delay

    def register(self, name: str, handler: Callable[[object], int]) -> None:
        log_with_fields(self._logger, logging.DEBUG, "Registering handler", command=name)
        self._routes[name] = handler

    def dispatch(self, args: object) -> int:
        if args.command not in self._routes:
            raise KeyError(f"No handler registered for command '{args.command}'.")

        handler = self._routes[args.command]
        attempt = 0
        while attempt <= self.io_retries:
            try:
                log_with_fields(
                    self._logger,
                    logging.INFO,
                    "Dispatching command",
                    command=args.command,
                    attempt=attempt + 1,
                )
                return handler(args)
            except OSError as exc:  # pragma: no cover - retry branch is environment dependent
                attempt += 1
                log_with_fields(
                    self._logger,
                    logging.WARNING,
                    "I/O hiccup during command",
                    command=args.command,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt > self.io_retries:
                    print(
                        f"Could not finish '{args.command}' because of a file issue: {exc}. "
                        "Please check your data path and try again."
                    )
                    return 1
                print(
                    f"Hit a file hiccup running {args.command}. Retrying "
                    f"({attempt}/{self.io_retries + 1})..."
                )
                time.sleep(self.retry_delay)
            except Exception as exc:  # pragma: no cover - friendly error path
                log_with_fields(
                    self._logger,
                    logging.ERROR,
                    "Command failed",
                    command=args.command,
                    error=str(exc),
                )
                print(f"Sorry, {args.command} had a problem: {exc}")
                return 1
        return 1
