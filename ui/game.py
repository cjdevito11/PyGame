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
QUEST_GIVER_NAME = "Guide"
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
        self.bus: EventBus = context.bus
        self.running = False
        self.font: pygame.font.Font | None = None
        self.quest_log: list[str] = []
        self.target_spawned = False
        self.target_defeated = False
        self.actors: Dict[str, Actor] = self._spawn_start_area()
        self.bus.subscribe("quest.completed", self._on_quest_completed)
        self.bus.subscribe("quest.turned_in", self._on_quest_turned_in)

    def _spawn_start_area(self) -> Dict[str, Actor]:
        definitions = self.context.bundle.characters.definitions()
        appearances = self.context.bundle.appearances
        actors: Dict[str, Actor] = {}

        hero_definition = definitions.get(PLAYER_NAME, {})
        hero_appearance = appearances.create(hero_definition.get("appearance", "hero"))
        actors[PLAYER_NAME] = Actor(
            name=PLAYER_NAME,
            color=pygame.Color(hero_appearance.color),
            rect=pygame.Rect((260, 320), (54, 54)),
        )

        guide_color = pygame.Color(214, 185, 110)
        actors[QUEST_GIVER_NAME] = Actor(
            name=QUEST_GIVER_NAME,
            color=guide_color,
            rect=pygame.Rect((360, 320), (54, 54)),
            speed=0,
        )
        self.quest_log.append("Find the Guide and press E to accept the quest.")
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

    def _quest_status(self) -> str:
        record = self.context.quests.quests.get("defeat-shade")
        return record.status if record else "unknown"

    def _player_near(self, actor_name: str, radius: int = 12) -> bool:
        player = self.actors.get(PLAYER_NAME)
        actor = self.actors.get(actor_name)
        if not player or not actor:
            return False
        return player.rect.colliderect(actor.rect.inflate(radius, radius))

    def _handle_interaction(self) -> None:
        if not self._player_near(QUEST_GIVER_NAME):
            return

        status = self._quest_status()
        if status == "available":
            self.bus.publish("quest.accepted", quest="defeat-shade", owner=PLAYER_NAME)
            self.quest_log.append("Quest accepted: Defeat Shade before returning to camp.")
        elif status == "completed":
            self.bus.publish("quest.turned_in", quest="defeat-shade", owner=PLAYER_NAME)
            self.quest_log.append("Quest turned in: The Guide rewards your effort.")

    def _maybe_spawn_target(self) -> None:
        if self.target_spawned or self._quest_status() != "accepted":
            return

        definitions = self.context.bundle.characters.definitions()
        appearances = self.context.bundle.appearances
        appearance_name = definitions[self.target_name]["appearance"]
        appearance = appearances.create(appearance_name)
        self.actors[self.target_name] = Actor(
            name=self.target_name,
            color=pygame.Color(appearance.color),
            rect=pygame.Rect((640, 280), (54, 54)),
        )
        self.target_spawned = True
        self.quest_log.append("Shade has appeared beyond the campfire.")

    def _render(self, screen: pygame.Surface) -> None:
        screen.fill(BACKGROUND)
        assert self.font is not None

        for name, actor in self.actors.items():
            pygame.draw.rect(screen, actor.color, actor.rect, border_radius=6)
            combatant = self.context.combat.characters.get(name)
            label = f"{name}"
            if combatant:
                label = f"{name} — HP: {combatant.hit_points}"
            hp_text = self.font.render(label, True, (236, 240, 241))
            screen.blit(hp_text, (actor.rect.x - 8, actor.rect.y - 28))

        prompts: list[str] = ["Move with WASD/arrow keys."]
        status = self._quest_status()
        if status == "available":
            prompts.append("Press E near the Guide to accept the quest.")
        elif status == "accepted":
            prompts.append("Hunt down Shade. Tap Space to attack when in range.")
        elif status == "completed":
            prompts.append("Return to the Guide and press E to turn in the quest.")
        elif status == "turned_in":
            prompts.append("Quest complete! Explore the camp at your pace.")

        for idx, message in enumerate(prompts):
            prompt = self.font.render(message, True, (200, 200, 200))
            screen.blit(prompt, (16, 16 + idx * 22))

        if self._player_near(QUEST_GIVER_NAME):
            interaction_text = "Press E to talk" if status != "turned_in" else "Enjoy the fire."
            bubble = self.font.render(interaction_text, True, (240, 240, 240))
            guide = self.actors[QUEST_GIVER_NAME]
            screen.blit(bubble, (guide.rect.x - 8, guide.rect.y - 28))

        log_title = self.font.render("Quest Log", True, (170, 186, 193))
        screen.blit(log_title, (16, SCREEN_SIZE[1] - 120))
        for idx, entry in enumerate(self.quest_log[-4:]):
            log_line = self.font.render(f"• {entry}", True, (210, 210, 210))
            screen.blit(log_line, (16, SCREEN_SIZE[1] - 96 + idx * 20))

        if self.context.zones.active_zone:
            zone = self.context.zones.active_zone
            zone_text = self.font.render(
                f"Zone: {zone.name} (danger: {zone.danger_level})", True, (170, 170, 170)
            )
            screen.blit(zone_text, (16, 44))

        pygame.display.flip()

    def _handle_defeat(self) -> None:
        defender = self.context.combat.characters.get(self.target_name)
        if defender and defender.hit_points <= 0 and not self.target_defeated:
            log_with_fields(logger, logging.INFO, "Enemy defeated", defender=defender.name)
            self.target_defeated = True
            self.target_spawned = False
            self.actors.pop(self.target_name, None)
            self.quest_log.append("Shade is defeated. Return to the Guide.")

    def _on_quest_completed(self, event) -> None:
        quest_name = event.payload["quest"]
        self.quest_log.append(f"Quest objective complete: {quest_name}.")

    def _on_quest_turned_in(self, event) -> None:
        reward = event.payload.get("reward_gold")
        if reward:
            self.quest_log.append(f"Received {reward} gold from the Guide.")
        else:
            self.quest_log.append("The Guide thanks you for your help.")

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
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        self._attempt_attack()
                    if event.key == pygame.K_e:
                        self._handle_interaction()

            for actor in self.actors.values():
                actor.update_cooldown(dt)

            self._handle_input(dt)
            self._maybe_spawn_target()
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
