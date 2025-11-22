"""Simple publish/subscribe event bus with plugin-friendly hooks."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, DefaultDict, Dict, List

from core.logging_config import get_logger, log_with_fields


@dataclass
class Event:
    """Container describing an emitted event."""

    name: str
    payload: Dict[str, Any]


class EventBus:
    """Lightweight synchronous event dispatcher.

    Listeners subscribe to named events. Plugin hooks can run before and
    after subscribers to adjust payloads or record observations without
    altering the core system loops.
    """

    def __init__(self) -> None:
        self._subscribers: DefaultDict[str, List[Callable[[Event], Any]]] = defaultdict(list)
        self._pre_hooks: DefaultDict[str, List[Callable[[Event], Any]]] = defaultdict(list)
        self._post_hooks: DefaultDict[str, List[Callable[[Event], Any]]] = defaultdict(list)
        self._logger = get_logger(__name__)

    def subscribe(self, event_name: str, handler: Callable[[Event], Any]) -> None:
        """Register a handler for a specific event name."""

        self._subscribers[event_name].append(handler)

    def add_hook(
        self,
        event_name: str,
        *,
        pre: Callable[[Event], Any] | None = None,
        post: Callable[[Event], Any] | None = None,
    ) -> None:
        """Attach plugin hooks that run before or after an event is processed."""

        if pre:
            self._pre_hooks[event_name].append(pre)
        if post:
            self._post_hooks[event_name].append(post)

    def publish(self, event_name: str, **payload: Any) -> List[Any]:
        """Dispatch an event to hooks and subscribers, returning handler results."""

        event = Event(name=event_name, payload=dict(payload))
        log_with_fields(self._logger, logging.DEBUG, "Publishing event", name=event_name, payload=payload)
        for hook in self._pre_hooks.get(event_name, []):
            hook(event)

        results: List[Any] = []
        for handler in self._subscribers.get(event_name, []):
            results.append(handler(event))

        for hook in self._post_hooks.get(event_name, []):
            hook(event)

        return results
