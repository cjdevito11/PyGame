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
DEFAULT_ENEMY_NAME = "Alpha Wolf"
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

    def __init__(self, context: GameContext, player_name: str | None = None, target: str = DEFAULT_ENEMY_NAME) -> None:
        self.context = context
        self.target_name = target
        self.bus: EventBus = context.bus
        self.playable_definitions = {
            name: data
            for name, data in context.bundle.characters.definitions().items()
            if data.get("role", "hero") == "hero"
        }
        self.enemy_names = [
            name
            for name, data in context.bundle.characters.definitions().items()
            if data.get("role") == "enemy" and ("Wolf" in name or name == target)
        ]
        self.player_name = player_name or next(iter(self.playable_definitions))
        self.state = "playing" if player_name else "menu"
        self.selection_index = 0
        self.actors: Dict[str, Actor] = {}
        self.running = False
        self.font: pygame.font.Font | None = None
        self.messages: list[str] = []

        self.bus.subscribe("combat.defeated", self._record_defeat)
        self.bus.subscribe("quest.completed", self._record_quest_completion)
        self.bus.subscribe("combat.experience", self._record_experience)

        if self.state == "playing":
            self.actors = self._spawn_actors()

    def _spawn_actors(self) -> Dict[str, Actor]:
        definitions = self.context.bundle.characters.definitions()
        appearances = self.context.bundle.appearances
        actors: Dict[str, Actor] = {}

        participants = [self.player_name] + self.enemy_names
        start_positions = [(160, 280), (640, 280), (320, 160), (480, 440), (240, 420), (720, 420)]
        for index, name in enumerate(participants):
            if name not in self.context.combat.characters:
                continue
            appearance_name = definitions[name]["appearance"]
            appearance = appearances.create(appearance_name)
            rect = pygame.Rect(start_positions[index % len(start_positions)], (54, 54))
            actors[name] = Actor(name=name, color=pygame.Color(appearance.color), rect=rect)
        return actors

    def _handle_input(self, dt: float) -> None:
        keys = pygame.key.get_pressed()
        player = self.actors.get(self.player_name)
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

        player.move(dx, dy, SCREEN_SIZE)

    def _attempt_attack(self) -> None:
        player = self.actors.get(self.player_name)
        if not player or not player.can_attack():
            return

        for name, target in list(self.actors.items()):
            if name == self.player_name:
                continue
            if player.rect.colliderect(target.rect.inflate(8, 8)):
                log_with_fields(logger, logging.INFO, "Real-time attack", attacker=player.name, defender=target.name)
                self.bus.publish("combat.attack", attacker=player.name, defender=target.name)
                player.trigger_attack()
                break

    def _render_menu(self, screen: pygame.Surface) -> None:
        assert self.font is not None
        screen.fill(BACKGROUND)
        title = self.font.render("Choose your hero to defend Pinefall", True, (236, 240, 241))
        screen.blit(title, (SCREEN_SIZE[0] // 2 - title.get_width() // 2, 48))

        options = list(self.playable_definitions.items())
        for idx, (name, data) in enumerate(options):
            selected = idx == self.selection_index
            color = (255, 215, 0) if selected else (200, 200, 200)
            label = self.font.render(f"{name} — {data['class_name']} ({data['description']})", True, color)
            screen.blit(label, (120, 140 + idx * 48))

        prompt = self.font.render("Use ↑/↓ to highlight, Enter to begin your quest.", True, (180, 180, 180))
        screen.blit(prompt, (SCREEN_SIZE[0] // 2 - prompt.get_width() // 2, 360))
        pygame.display.flip()

    def _render_playing(self, screen: pygame.Surface) -> None:
        screen.fill(BACKGROUND)
        assert self.font is not None

        for name, actor in list(self.actors.items()):
            combatant = self.context.combat.characters.get(name)
            if combatant and combatant.hit_points <= 0:
                self.actors.pop(name, None)
                continue
            pygame.draw.rect(screen, actor.color, actor.rect, border_radius=6)
            if not combatant:
                continue
            hp_text = self.font.render(
                f"{name} — HP: {combatant.hit_points}  Lv {combatant.level}", True, (236, 240, 241)
            )
            screen.blit(hp_text, (actor.rect.x - 8, actor.rect.y - 28))

        player = self.context.combat.characters.get(self.player_name)
        if player:
            quest = self.context.quests.quests.get("wolf-threat")
            quest_progress = "" if not quest else f"Quest: Wolves {quest.progress}/{quest.goal_count} ({quest.status})"
            xp_line = (
                f"Lv {player.level} | XP {player.experience}/{player.experience_to_level} | Gold {player.gold}"
            )
            status = self.font.render(xp_line, True, (214, 234, 248))
            screen.blit(status, (18, 16))
            if quest_progress:
                quest_text = self.font.render(quest_progress, True, (214, 234, 248))
                screen.blit(quest_text, (18, 44))

        for i, message in enumerate(self.messages[-4:]):
            text = self.font.render(message, True, (180, 180, 180))
            screen.blit(text, (18, SCREEN_SIZE[1] - 30 * (len(self.messages[-4:]) - i)))

        prompt = self.font.render("Move with WASD/arrow keys. Tap Space to attack.", True, (200, 200, 200))
        screen.blit(prompt, (16, 84))

        pygame.display.flip()

    def _render_victory(self, screen: pygame.Surface) -> None:
        assert self.font is not None
        screen.fill(BACKGROUND)

        banner = self.font.render("Pinefall is safe — quest complete!", True, (236, 240, 241))
        prompt = self.font.render("Press Enter to return to hero select or close the window.", True, (200, 200, 200))

        screen.blit(banner, (SCREEN_SIZE[0] // 2 - banner.get_width() // 2, SCREEN_SIZE[1] // 2 - 40))
        screen.blit(prompt, (SCREEN_SIZE[0] // 2 - prompt.get_width() // 2, SCREEN_SIZE[1] // 2 + 8))

        for i, message in enumerate(self.messages[-4:]):
            text = self.font.render(message, True, (180, 180, 180))
            screen.blit(text, (18, SCREEN_SIZE[1] - 30 * (len(self.messages[-4:]) - i)))

        pygame.display.flip()

    def _handle_defeat(self) -> None:
        enemies_alive = any(
            combatant.hit_points > 0 and name != self.player_name
            for name, combatant in self.context.combat.characters.items()
            if name in self.actors
        )
        if not enemies_alive:
            log_with_fields(logger, logging.INFO, "Encounter cleared")
            self.state = "victory"

    def _record_defeat(self, event: object) -> None:
        if isinstance(event, object) and hasattr(event, "payload"):
            defender = getattr(event, "payload", {}).get("defender")
            attacker = getattr(event, "payload", {}).get("attacker")
            self.messages.append(f"{attacker} defeated {defender}!")

    def _record_quest_completion(self, event: object) -> None:
        if isinstance(event, object) and hasattr(event, "payload"):
            quest = getattr(event, "payload", {}).get("quest")
            reward_gold = getattr(event, "payload", {}).get("reward_gold", 0)
            reward_xp = getattr(event, "payload", {}).get("reward_experience", 0)
            owner = getattr(event, "payload", {}).get("owner")
            self.messages.append(f"Quest '{quest}' complete! +{reward_gold}g, +{reward_xp}xp to {owner}")
            self.state = "victory"

    def _record_experience(self, event: object) -> None:
        if isinstance(event, object) and hasattr(event, "payload"):
            payload = getattr(event, "payload", {})
            if payload.get("leveled_up"):
                self.messages.append(f"{payload.get('character')} reached level {payload.get('level')}!")

    def _start_adventure(self) -> None:
        options = list(self.playable_definitions)
        if options:
            self.player_name = options[self.selection_index % len(options)]
        self.actors = self._spawn_actors()
        self.state = "playing"
        self.messages.clear()

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
                if self.state == "menu" and event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_DOWN, pygame.K_s):
                        self.selection_index = (self.selection_index + 1) % len(self.playable_definitions)
                    if event.key in (pygame.K_UP, pygame.K_w):
                        self.selection_index = (self.selection_index - 1) % len(self.playable_definitions)
                    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        self._start_adventure()
                if self.state == "playing" and event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                    self._attempt_attack()
                if self.state == "victory" and event.type == pygame.KEYDOWN and event.key in (
                    pygame.K_RETURN,
                    pygame.K_KP_ENTER,
                ):
                    self.state = "menu"
                    self.selection_index = 0
                    self.actors.clear()

            if self.state == "playing":
                for actor in self.actors.values():
                    actor.update_cooldown(dt)
                self._handle_input(dt)
                self._handle_defeat()
                self._render_playing(screen)
            elif self.state == "menu":
                self._render_menu(screen)
            else:
                self._render_victory(screen)

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
