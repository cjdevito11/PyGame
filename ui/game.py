"""Pygame-powered real-time prototype for the data-driven MMORPG skeleton."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import Dict, Tuple

import pygame

from core.logging_config import get_logger, log_with_fields
from systems import EventBus
from world.zones import Zone
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


@dataclass
class TutorialManager:
    """Tracks onboarding checklist steps and temporary help prompts."""

    help_flash_timer: float = 0.0
    move_complete: bool = False
    interact_complete: bool = False
    attack_complete: bool = False

    def update(self, dt: float) -> None:
        self.help_flash_timer = max(0.0, self.help_flash_timer - dt)

    def request_help(self) -> None:
        self.help_flash_timer = 6.0

    def record_movement(self, dx: float, dy: float) -> None:
        if self.move_complete:
            return
        if dx != 0.0 or dy != 0.0:
            self.move_complete = True

    def record_interaction(self) -> None:
        self.interact_complete = True

    def record_attack(self) -> None:
        self.attack_complete = True

    def active(self) -> bool:
        return not self.is_complete() or self.help_flash_timer > 0.0

    def is_complete(self) -> bool:
        return self.move_complete and self.interact_complete and self.attack_complete

    def prompts(self) -> list[str]:
        if not self.active():
            return []

        entries = [
            (self.move_complete, "Move with WASD/arrow keys."),
            (self.interact_complete, "Talk to the Guide with E."),
            (self.attack_complete, "Press Space near enemies to attack."),
        ]
        checklist = ["Tutorial:" if not self.is_complete() else "Help: controls & objectives"]
        for done, text in entries:
            marker = "✓" if done else "○"
            checklist.append(f"  {marker} {text}")
        return checklist


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
        self.zone_prompt: str = ""
        self.actors: Dict[str, Actor] = self._spawn_start_area()
        self.tutorial = TutorialManager()
        self.bus.subscribe("quest.completed", self._on_quest_completed)
        self.bus.subscribe("quest.turned_in", self._on_quest_turned_in)
        self.bus.subscribe("zone.changed", self._on_zone_changed)

    def _spawn_start_area(self) -> Dict[str, Actor]:
        definitions = self.context.bundle.characters.definitions()
        appearances = self.context.bundle.appearances
        actors: Dict[str, Actor] = {}

        zone = self.context.zones.active_zone
        zone_rect = (
            pygame.Rect((zone.bounds.x, zone.bounds.y), (zone.bounds.width, zone.bounds.height))
            if zone
            else pygame.Rect((0, 0), SCREEN_SIZE)
        )
        obstacles = self._zone_obstacles(zone) if zone else []
        self.zone_prompt = f"{zone.name.title()}: {zone.description}" if zone else "Exploring the wilderness."

        starting_y = zone_rect.y + zone_rect.height - 160
        starting_x = zone_rect.x + 60

        hero_definition = definitions.get(PLAYER_NAME, {})
        hero_appearance = appearances.create(hero_definition.get("appearance", "hero"))
        hero_rect = pygame.Rect((starting_x, starting_y), (54, 54))
        actors[PLAYER_NAME] = Actor(
            name=PLAYER_NAME,
            color=pygame.Color(hero_appearance.color),
            rect=self._resolve_obstacle_collision(hero_rect, hero_rect, obstacles, zone_rect),
        )

        guide_color = pygame.Color(214, 185, 110)
        guide_rect = pygame.Rect((starting_x + 120, starting_y - 20), (54, 54))
        actors[QUEST_GIVER_NAME] = Actor(
            name=QUEST_GIVER_NAME,
            color=guide_color,
            rect=self._resolve_obstacle_collision(guide_rect, guide_rect, obstacles, zone_rect),
            speed=0,
        )
        self.quest_log.append("Find the Guide and press E to accept the quest.")
        return actors

    def _zone_rect(self, zone: Zone | None) -> pygame.Rect | None:
        if not zone:
            return None
        bounds = zone.bounds
        return pygame.Rect((bounds.x, bounds.y), (bounds.width, bounds.height))

    def _zone_obstacles(self, zone: Zone | None) -> list[pygame.Rect]:
        if not zone:
            return []
        return [pygame.Rect((obs.x, obs.y), (obs.width, obs.height)) for obs in zone.obstacles]

    def _resolve_obstacle_collision(
        self,
        original: pygame.Rect,
        candidate: pygame.Rect,
        obstacles: list[pygame.Rect],
        bounds: pygame.Rect,
    ) -> pygame.Rect:
        if not obstacles:
            return candidate
        if not any(candidate.colliderect(obstacle) for obstacle in obstacles):
            return candidate

        horizontal = pygame.Rect((candidate.x, original.y), (candidate.width, candidate.height))
        vertical = pygame.Rect((original.x, candidate.y), (candidate.width, candidate.height))

        if not any(horizontal.colliderect(obstacle) for obstacle in obstacles):
            return horizontal
        if not any(vertical.colliderect(obstacle) for obstacle in obstacles):
            return vertical
        return original

    def _detect_boundary_crossing(self, proposed: pygame.Rect, bounds: pygame.Rect) -> str | None:
        if proposed.x < bounds.x:
            return "west"
        if proposed.x + proposed.width > bounds.x + bounds.width:
            return "east"
        if proposed.y < bounds.y:
            return "north"
        if proposed.y + proposed.height > bounds.y + bounds.height:
            return "south"
        return None

    def _entry_position_for_zone(self, player: Actor, zone: Zone, direction: str | None) -> pygame.Rect:
        bounds = self._zone_rect(zone)
        assert bounds is not None
        margin = 24
        if direction == "west":
            x = bounds.x + bounds.width - player.rect.width - margin
            y = bounds.y + bounds.height // 2
        elif direction == "east":
            x = bounds.x + margin
            y = bounds.y + bounds.height // 2
        elif direction == "north":
            x = bounds.x + bounds.width // 2
            y = bounds.y + bounds.height - player.rect.height - margin
        else:
            x = bounds.x + bounds.width // 2
            y = bounds.y + margin
        return pygame.Rect((x, y), (player.rect.width, player.rect.height))

    def _reset_zone_population(self, zone: Zone, direction: str | None = None) -> None:
        player = self.actors.get(PLAYER_NAME)
        if not player:
            return

        self.actors = {PLAYER_NAME: player}
        self.zone_prompt = f"{zone.name.title()}: {zone.description}"
        bounds = self._zone_rect(zone) or pygame.Rect((0, 0), SCREEN_SIZE)
        obstacles = self._zone_obstacles(zone)
        rng = Random(f"{zone.name}-{zone.danger_level}")

        entry_rect = self._entry_position_for_zone(player, zone, direction)
        clamped_x = max(bounds.x, min(bounds.x + bounds.width - entry_rect.width, entry_rect.x))
        clamped_y = max(bounds.y, min(bounds.y + bounds.height - entry_rect.height, entry_rect.y))
        entry_rect.x, entry_rect.y = clamped_x, clamped_y
        player.rect = self._resolve_obstacle_collision(player.rect, entry_rect, obstacles, bounds)

        self.target_spawned = False
        if zone.is_static:
            guide_color = pygame.Color(214, 185, 110)
            guide_rect = pygame.Rect((player.rect.x + 120, player.rect.y - 20), (54, 54))
            self.actors[QUEST_GIVER_NAME] = Actor(
                name=QUEST_GIVER_NAME,
                color=guide_color,
                rect=self._resolve_obstacle_collision(player.rect, guide_rect, obstacles, bounds),
                speed=0,
            )

        self._seed_zone_spawns(zone, bounds, obstacles, rng)
        self._maybe_spawn_target()

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

        active_zone = self.context.zones.active_zone
        bounds = self._zone_rect(active_zone)
        if bounds:
            proposed = pygame.Rect(
                (int(player.rect.x + dx), int(player.rect.y + dy)), (player.rect.width, player.rect.height)
            )
            direction = self._detect_boundary_crossing(proposed, bounds)
            if direction:
                self._transition_zone(direction)
                return

            clamped_x = max(bounds.x, min(bounds.x + bounds.width - player.rect.width, proposed.x))
            clamped_y = max(bounds.y, min(bounds.y + bounds.height - player.rect.height, proposed.y))
            candidate = pygame.Rect((clamped_x, clamped_y), (player.rect.width, player.rect.height))
            obstacles = self._zone_obstacles(active_zone)
            player.rect = self._resolve_obstacle_collision(player.rect, candidate, obstacles, bounds)
        else:
            player.move(dx, dy, SCREEN_SIZE)

        self.tutorial.record_movement(dx, dy)

    def _attempt_attack(self) -> bool:
        player = self.actors.get(PLAYER_NAME)
        target = self.actors.get(self.target_name)
        if not player or not target or not player.can_attack():
            return False

        if player.rect.colliderect(target.rect.inflate(8, 8)):
            log_with_fields(logger, logging.INFO, "Real-time attack", attacker=player.name, defender=target.name)
            self.bus.publish("combat.attack", attacker=player.name, defender=target.name)
            player.trigger_attack()
            self.tutorial.record_attack()
            return True
        return False

    def _quest_status(self) -> str:
        record = self.context.quests.quests.get("defeat-shade")
        return record.status if record else "unknown"

    def _player_near(self, actor_name: str, radius: int = 12) -> bool:
        player = self.actors.get(PLAYER_NAME)
        actor = self.actors.get(actor_name)
        if not player or not actor:
            return False
        return player.rect.colliderect(actor.rect.inflate(radius, radius))

    def _handle_interaction(self) -> bool:
        if not self._player_near(QUEST_GIVER_NAME):
            return False

        status = self._quest_status()
        if status == "available":
            self.bus.publish("quest.accepted", quest="defeat-shade", owner=PLAYER_NAME)
            self.quest_log.append("Quest accepted: Defeat Shade before returning to the Guide.")
            return True
        if status == "completed":
            self.bus.publish("quest.turned_in", quest="defeat-shade", owner=PLAYER_NAME)
            self.quest_log.append("Quest turned in: The Guide rewards your effort.")
            return True
        return False

    def _maybe_spawn_target(self) -> None:
        zone = self.context.zones.active_zone
        if (
            self.target_spawned
            or self._quest_status() != "accepted"
            or not self._zone_allows_target(zone)
        ):
            return

        definitions = self.context.bundle.characters.definitions()
        appearances = self.context.bundle.appearances
        appearance_name = definitions[self.target_name]["appearance"]
        appearance = appearances.create(appearance_name)
        zone = self.context.zones.active_zone
        bounds = self._zone_rect(zone) or pygame.Rect((0, 0), SCREEN_SIZE)
        spawn_x = bounds.x + bounds.width - 220
        spawn_y = bounds.y + bounds.height // 2
        target_rect = pygame.Rect((spawn_x, spawn_y), (54, 54))
        target_rect = self._resolve_obstacle_collision(
            target_rect, target_rect, self._zone_obstacles(zone), bounds
        )
        self.actors[self.target_name] = Actor(
            name=self.target_name,
            color=pygame.Color(appearance.color),
            rect=target_rect,
        )
        self.target_spawned = True
        self.quest_log.append("Shade has appeared beyond the campfire.")

    def _zone_allows_target(self, zone: Zone | None) -> bool:
        if not zone:
            return False
        return (not zone.is_static) and zone.danger_level not in {"none", "low"}

    def _seed_zone_spawns(
        self, zone: Zone, bounds: pygame.Rect, obstacles: list[pygame.Rect], rng: Random
    ) -> None:
        if not zone.spawn_rules:
            return

        spawn_rolls = self._roll_zone_spawns(zone, rng)
        for spawn_name, count in spawn_rolls.items():
            for _ in range(count):
                rect = self._random_spawn_location(bounds, obstacles, rng)
                rect = self._resolve_obstacle_collision(rect, rect, obstacles, bounds)
                actor_name = self._unique_actor_name(spawn_name)
                self.actors[actor_name] = Actor(
                    name=actor_name,
                    color=self._color_for_spawn(spawn_name),
                    rect=rect,
                    speed=0 if zone.is_static else 180,
                )

    def _roll_zone_spawns(self, zone: Zone, rng: Random) -> Dict[str, int]:
        if not zone.spawn_rules:
            return {}

        baseline = 3 if zone.danger_level in {"none", "low"} else 5
        max_slots = 6 if zone.danger_level in {"none", "low"} else 9
        slots = rng.randint(baseline, max_slots)

        available: Dict[str, int | None] = {rule.spawn: rule.max_count for rule in zone.spawn_rules}
        weights = [(rule.spawn, rule.weight) for rule in zone.spawn_rules]
        chosen: dict[str, int] = defaultdict(int)

        for _ in range(slots):
            pool = [
                (spawn, weight)
                for spawn, weight in weights
                if available[spawn] is None or chosen[spawn] < available[spawn]
            ]
            if not pool:
                break
            options, pool_weights = zip(*pool)
            selection = rng.choices(options, weights=pool_weights, k=1)[0]
            chosen[selection] += 1

        return dict(chosen)

    def _color_for_spawn(self, spawn: str) -> pygame.Color:
        palette: Dict[str, Tuple[int, int, int]] = {
            "vendor": (185, 155, 110),
            "campfire": (215, 115, 80),
            "villager": (110, 160, 210),
            "guard": (120, 140, 190),
            "trader": (160, 170, 105),
            "wolf": (140, 140, 140),
            "boar": (170, 120, 90),
            "bandit": (200, 95, 95),
            "herb": (90, 170, 110),
            "gryphon": (190, 190, 140),
            "goat": (210, 210, 210),
            "ore-node": (110, 110, 130),
            "slime": (90, 200, 180),
            "mosquito": (190, 60, 90),
            "shrub": (70, 120, 80),
        }
        return pygame.Color(palette.get(spawn, (150, 150, 160)))

    def _random_spawn_location(
        self, bounds: pygame.Rect, obstacles: list[pygame.Rect], rng: Random
    ) -> pygame.Rect:
        margin = 28
        size = (48, 48)
        attempts = 20
        for _ in range(attempts):
            x = rng.randint(bounds.x + margin, max(bounds.x + margin, bounds.x + bounds.width - size[0] - margin))
            y = rng.randint(bounds.y + margin, max(bounds.y + margin, bounds.y + bounds.height - size[1] - margin))
            rect = pygame.Rect((x, y), size)
            if rect.collidelist(obstacles) == -1 and all(
                not rect.colliderect(actor.rect.inflate(6, 6)) for actor in self.actors.values()
            ):
                return rect
        return pygame.Rect((bounds.x + margin, bounds.y + margin), size)

    def _unique_actor_name(self, base: str) -> str:
        if base not in self.actors:
            return base
        counter = 2
        candidate = f"{base}-{counter}"
        while candidate in self.actors:
            counter += 1
            candidate = f"{base}-{counter}"
        return candidate

    def _transition_zone(self, direction: str) -> None:
        current = self.context.zones.active_zone
        if not current:
            return

        if current.is_static:
            next_zone = self.context.zones.spawn_outdoor_zone()
        else:
            destination = (
                "town"
                if "town" in self.context.zones.static_zones
                else next(iter(self.context.zones.static_zones), None)
            )
            if destination:
                next_zone = self.context.zones.set_active(destination)
            else:
                return

        self.bus.publish(
            "zone.changed",
            previous=current.name,
            current=next_zone.name,
            direction=direction,
            danger=next_zone.danger_level,
        )
        self._reset_zone_population(next_zone, direction)

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

        margin = 16
        line_height = 22
        section_spacing = 10

        status = self._quest_status()
        y_cursor = margin

        if self.context.zones.active_zone:
            zone = self.context.zones.active_zone
            zone_text = self.font.render(
                f"Zone: {zone.name} (danger: {zone.danger_level})", True, (170, 170, 170)
            )
            screen.blit(zone_text, (margin, y_cursor))
            y_cursor += line_height + section_spacing

        prompts: list[str] = []
        if self.zone_prompt:
            prompts.append(self.zone_prompt)

        tutorial_prompts = self.tutorial.prompts()
        if tutorial_prompts:
            prompts.extend(tutorial_prompts)
        else:
            prompts.append("Press H to re-open control hints.")

        if status == "available":
            prompts.append("Press E near the Guide to accept the quest.")
        elif status == "accepted":
            prompts.append("Hunt down Shade. Tap Space to attack when in range.")
        elif status == "completed":
            prompts.append("Return to the Guide and press E to turn in the quest.")
        elif status == "turned_in":
            prompts.append("Quest complete! Explore the camp at your pace.")

        for message in prompts:
            prompt = self.font.render(message, True, (200, 200, 200))
            screen.blit(prompt, (margin, y_cursor))
            y_cursor += line_height

        if prompts:
            y_cursor += section_spacing

        if self._player_near(QUEST_GIVER_NAME):
            interaction_text = "Press E to talk" if status != "turned_in" else "Enjoy the fire."
            bubble = self.font.render(interaction_text, True, (240, 240, 240))
            guide = self.actors[QUEST_GIVER_NAME]
            screen.blit(bubble, (guide.rect.x - 8, guide.rect.y - 28))

        log_title_y = SCREEN_SIZE[1] - 120
        log_title = self.font.render("Quest Log", True, (170, 186, 193))
        screen.blit(log_title, (margin, log_title_y))
        for idx, entry in enumerate(self.quest_log[-4:]):
            log_line = self.font.render(f"• {entry}", True, (210, 210, 210))
            screen.blit(log_line, (margin, log_title_y + 24 + idx * 20))

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

    def _on_zone_changed(self, event) -> None:
        current = event.payload.get("current", "unknown")
        danger = event.payload.get("danger", "unknown")
        direction = event.payload.get("direction")
        direction_note = f" via {direction}" if direction else ""
        self.quest_log.append(f"Entered {current}{direction_note}. Danger: {danger}.")

    def run(self) -> None:
        pygame.init()
        self.font = pygame.font.SysFont("arial", 18)
        screen = pygame.display.set_mode(SCREEN_SIZE)
        clock = pygame.time.Clock()
        self.running = True

        while self.running:
            dt = clock.tick(60) / 1000.0
            self.tutorial.update(dt)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        self._attempt_attack()
                    if event.key == pygame.K_e:
                        if self._handle_interaction():
                            self.tutorial.record_interaction()
                    if event.key == pygame.K_h:
                        self.tutorial.request_help()

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
