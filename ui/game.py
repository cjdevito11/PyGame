"""Pygame-powered real-time prototype for the data-driven MMORPG skeleton."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import pygame

from core.logging_config import get_logger, log_with_fields
from systems import EventBus
from ui.context import GameContext, build_context

SCREEN_SIZE = (960, 640)
BACKGROUND = (16, 18, 24)
PLAYER_NAME = "Aria"
DEFAULT_ENEMY_NAME = "Shade"
DEFAULT_DATA_PATH = Path(__file__).resolve().parent.parent / "data"


logger = get_logger(__name__)


@dataclass
class Actor:
    name: str
    color: pygame.Color
    rect: pygame.Rect
    speed: float = 220.0
    attack_cooldown: float = 0.35
    _cooldown_timer: float = 0.0

    def move(self, dx: float, dy: float, bounds: Tuple[int, int]) -> None:
        self.rect.x = max(0, min(bounds[0] - self.rect.width, int(self.rect.x + dx)))
        self.rect.y = max(0, min(bounds[1] - self.rect.height, int(self.rect.y + dy)))

    def update_cooldown(self, dt: float) -> None:
        self._cooldown_timer = max(0.0, self._cooldown_timer - dt)

    def can_attack(self) -> bool:
        return self._cooldown_timer <= 0.0

    def trigger_attack(self) -> None:
        self._cooldown_timer = self.attack_cooldown


class PygameMMO:
    """Lightweight real-time loop that reuses the shared data-driven systems."""

    def __init__(self, context: GameContext, target: str = DEFAULT_ENEMY_NAME) -> None:
        self.context = context
        self.target_name = target
        self.actors: Dict[str, Actor] = self._spawn_actors()
        self.bus: EventBus = context.bus
        self.running = False
        self.font: pygame.font.Font | None = None

    def _spawn_actors(self) -> Dict[str, Actor]:
        definitions = self.context.bundle.characters.definitions()
        appearances = self.context.bundle.appearances
        actors: Dict[str, Actor] = {}

        start_positions = [(160, 280), (640, 280), (320, 160), (480, 440)]
        for index, (name, combatant) in enumerate(self.context.combat.characters.items()):
            appearance_name = definitions[name]["appearance"]
            appearance = appearances.create(appearance_name)
            rect = pygame.Rect(start_positions[index % len(start_positions)], (54, 54))
            actors[name] = Actor(name=name, color=pygame.Color(appearance.color), rect=rect)
        return actors

    def _handle_input(self, dt: float) -> None:
        keys = pygame.key.get_pressed()
        player = self.actors.get(PLAYER_NAME)
        if not player:
            return

        dx = dy = 0.0
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            dx -= player.speed * dt
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            dx += player.speed * dt
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            dy -= player.speed * dt
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            dy += player.speed * dt

        zone_bounds = self.context.zones.active_zone.bounds if self.context.zones.active_zone else None
        limit = (zone_bounds.width, zone_bounds.height) if zone_bounds else SCREEN_SIZE
        player.move(dx, dy, limit)

    def _attempt_attack(self) -> None:
        player = self.actors.get(PLAYER_NAME)
        target = self.actors.get(self.target_name)
        if not player or not target or not player.can_attack():
            return

        if player.rect.colliderect(target.rect.inflate(8, 8)):
            log_with_fields(logger, logging.INFO, "Real-time attack", attacker=player.name, defender=target.name)
            self.bus.publish("combat.attack", attacker=player.name, defender=target.name)
            player.trigger_attack()

    def _render(self, screen: pygame.Surface) -> None:
        screen.fill(BACKGROUND)
        assert self.font is not None

        for name, actor in self.actors.items():
            pygame.draw.rect(screen, actor.color, actor.rect, border_radius=6)
            combatant = self.context.combat.characters[name]
            hp_text = self.font.render(f"{name} — HP: {combatant.hit_points}", True, (236, 240, 241))
            screen.blit(hp_text, (actor.rect.x - 8, actor.rect.y - 28))

        prompt = self.font.render("Move with WASD/arrow keys. Tap Space to attack.", True, (200, 200, 200))
        screen.blit(prompt, (16, 16))

        if self.context.zones.active_zone:
            zone = self.context.zones.active_zone
            zone_text = self.font.render(
                f"Zone: {zone.name} (danger: {zone.danger_level})", True, (170, 170, 170)
            )
            screen.blit(zone_text, (16, 44))

        pygame.display.flip()

    def _handle_defeat(self) -> None:
        defender = self.context.combat.characters.get(self.target_name)
        if defender and defender.hit_points <= 0:
            log_with_fields(logger, logging.INFO, "Enemy defeated", defender=defender.name)
            self.running = False

    def run(self) -> None:
        pygame.init()
        self.font = pygame.font.SysFont("arial", 18)
        screen = pygame.display.set_mode(SCREEN_SIZE)
        clock = pygame.time.Clock()
        self.running = True

        while self.running:
            dt = clock.tick(60) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                    self._attempt_attack()

            for actor in self.actors.values():
                actor.update_cooldown(dt)

            self._handle_input(dt)
            self._handle_defeat()
            self._render(screen)

        pygame.quit()


def main(*, data_path: Path | None = None, target: str = DEFAULT_ENEMY_NAME) -> int:
    """Start the real-time demo using bundled data by default."""

    selected_path = data_path or DEFAULT_DATA_PATH
    try:
        context = build_context(selected_path)
    except Exception as exc:  # pragma: no cover - manual smoke path
        log_with_fields(logger, logging.ERROR, "Failed to start Pygame client", error=str(exc))
        print(f"Failed to start game: {exc}")
        return 1

    app = PygameMMO(context, target=target)
    app.run()
    return 0


if __name__ == "__main__":  # pragma: no cover - manual execution entry
    raise SystemExit(main())
