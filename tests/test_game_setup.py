"""Smoke tests for the real-time Pygame prototype setup."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import types
import unittest

if importlib.util.find_spec("pygame") is None:
    class _DummyColor:
        def __init__(self, value: str | tuple[int, int, int] | None = None):
            self.value = value or "white"

    class _DummyRect:
        def __init__(self, position: tuple[int, int], size: tuple[int, int]):
            self.x, self.y = position
            self.width, self.height = size

        @property
        def topleft(self) -> tuple[int, int]:
            return (self.x, self.y)

        @topleft.setter
        def topleft(self, value: tuple[int, int]) -> None:
            self.x, self.y = value

        def colliderect(self, other: "_DummyRect") -> bool:
            return not (
                self.x + self.width <= other.x
                or other.x + other.width <= self.x
                or self.y + self.height <= other.y
                or other.y + other.height <= self.y
            )

        def inflate(self, dx: int, dy: int) -> "_DummyRect":
            return _DummyRect((self.x - dx // 2, self.y - dy // 2), (self.width + dx, self.height + dy))

    class _DummyFont:
        def render(self, *args, **kwargs):  # pragma: no cover - debug stub
            return "text"

    class _DummyScreen:
        def fill(self, *_: object, **__: object) -> None:
            return None

        def blit(self, *_: object, **__: object) -> None:
            return None

    class _DummyDraw:
        def rect(self, *_: object, **__: object) -> None:
            return None

    class _DummyDisplay:
        def set_mode(self, *_: object, **__: object) -> _DummyScreen:
            return _DummyScreen()

        def flip(self) -> None:
            return None

    class _DummyClock:
        def tick(self, *_: object, **__: object) -> int:
            return 16

    class _DummyEventModule:
        def get(self) -> list:
            return []

    dummy_pygame = types.SimpleNamespace(
        Color=_DummyColor,
        Rect=_DummyRect,
        QUIT="QUIT",
        KEYDOWN="KEYDOWN",
        K_SPACE="SPACE",
        K_a="A",
        K_d="D",
        K_w="W",
        K_s="S",
        K_LEFT="LEFT",
        K_RIGHT="RIGHT",
        K_UP="UP",
        K_DOWN="DOWN",
        draw=_DummyDraw(),
        display=_DummyDisplay(),
        event=_DummyEventModule(),
        font=types.SimpleNamespace(SysFont=lambda *args, **kwargs: _DummyFont()),
        key=types.SimpleNamespace(get_pressed=lambda: {}),
        time=types.SimpleNamespace(Clock=_DummyClock),
        init=lambda: None,
        quit=lambda: None,
    )
    sys.modules["pygame"] = dummy_pygame
    sys.modules["pygame.font"] = dummy_pygame.font


from ui.context import build_context
from ui.game import DEFAULT_ENEMY_NAME, PLAYER_NAME, PygameMMO, QUEST_GIVER_NAME

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class GameSetupTest(unittest.TestCase):
    def test_spawn_actors_from_data(self) -> None:
        context = build_context(DATA_DIR)
        game = PygameMMO(context)

        self.assertIn(PLAYER_NAME, game.actors)
        self.assertIn(QUEST_GIVER_NAME, game.actors)
        self.assertNotIn(DEFAULT_ENEMY_NAME, game.actors)

        game.bus.publish("quest.accepted", quest="defeat-shade", owner=PLAYER_NAME)
        game._maybe_spawn_target()
        self.assertIn(DEFAULT_ENEMY_NAME, game.actors)

        player_rect = game.actors[PLAYER_NAME].rect
        self.assertGreater(player_rect.width, 0)
        self.assertGreater(player_rect.height, 0)

    def test_attack_event_reduces_enemy_health(self) -> None:
        context = build_context(DATA_DIR)
        game = PygameMMO(context)

        player = game.actors[PLAYER_NAME]
        game.bus.publish("quest.accepted", quest="defeat-shade", owner=PLAYER_NAME)
        game._maybe_spawn_target()
        target = game.actors[DEFAULT_ENEMY_NAME]
        player.rect.topleft = target.rect.topleft

        starting_hp = context.combat.characters[DEFAULT_ENEMY_NAME].hit_points
        game._attempt_attack()

        self.assertLess(context.combat.characters[DEFAULT_ENEMY_NAME].hit_points, starting_hp)
        self.assertGreater(player._cooldown_timer, 0)


if __name__ == "__main__":
    unittest.main()
