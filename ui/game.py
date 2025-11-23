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
from world.entities import Item

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
class ItemSlot:
    rect: pygame.Rect
    item: Item | None
    slot_name: str | None
    category: str  # "equip", "pack", "sell", "drop"


RARITY_COLORS: Dict[str | None, pygame.Color] = {
    None: pygame.Color(160, 160, 170),
    "common": pygame.Color(180, 185, 200),
    "uncommon": pygame.Color(90, 173, 115),
    "rare": pygame.Color(90, 145, 205),
    "epic": pygame.Color(170, 90, 205),
    "legendary": pygame.Color(212, 146, 44),
}


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
        self.display_initialized = False
        self.screen_size = SCREEN_SIZE
        self.background = BACKGROUND
        self.quest_log: list[str] = []
        self.target_spawned = False
        self.target_defeated = False
        self.zone_prompt: str = ""
        self._apply_zone_settings(context.zones.active_zone)
        self.actors: Dict[str, Actor] = self._spawn_start_area()
        self.tutorial = TutorialManager()
        self.show_inventory = False
        self.show_menu_panel = False
        self.show_skills_panel = False
        self.show_quests_panel = False
        self.show_help_overlay = False
        self.loot_banner: str | None = None
        self.loot_banner_timer: float = 0.0
        self.mouse_pos: Tuple[int, int] = (0, 0)
        self.pack_slots: list[ItemSlot] = []
        self.equip_slots: list[ItemSlot] = []
        self.action_slots: list[ItemSlot] = []
        self.toolbar_buttons: list[tuple[str, pygame.Rect]] = []
        self.quest_panel_tab: pygame.Rect | None = None
        self.dragging_slot: ItemSlot | None = None
        self.drag_offset: Tuple[int, int] = (0, 0)
        self.hovered_slot: ItemSlot | None = None
        self.zone_boundary_color = pygame.Color(90, 130, 190)
        self.obstacle_color = pygame.Color(65, 75, 95)
        self.interaction_hint: str | None = None
        self.render_offset: Tuple[int, int] = (0, 0)
        self.bus.subscribe("quest.completed", self._on_quest_completed)
        self.bus.subscribe("quest.turned_in", self._on_quest_turned_in)
        self.bus.subscribe("quest.unlocked", self._on_quest_unlocked)
        self.bus.subscribe("quest.stage_advanced", self._on_quest_stage_advanced)
        self.bus.subscribe("quest.progress", self._on_quest_progress)
        self.bus.subscribe("zone.changed", self._on_zone_changed)
        self.bus.subscribe("inventory.item_added", self._on_item_added)
        self.show_objective_indicator = True

    def _apply_zone_settings(self, zone: Zone | None) -> None:
        settings = self.context.zones.map_settings()
        size = settings.get("size", SCREEN_SIZE)
        if not self.display_initialized and isinstance(size, tuple) and len(size) == 2:
            self.screen_size = (int(size[0]), int(size[1]))
        self.background = settings.get("background", BACKGROUND)

    def _detect_display_size(self) -> Tuple[int, int]:
        """Return the current monitor resolution for a fullscreen canvas."""

        info = pygame.display.Info()
        width = max(int(info.current_w), SCREEN_SIZE[0])
        height = max(int(info.current_h), SCREEN_SIZE[1])
        return (width, height)

    def _spawn_start_area(self) -> Dict[str, Actor]:
        definitions = self.context.bundle.characters.definitions()
        appearances = self.context.bundle.appearances
        actors: Dict[str, Actor] = {}

        zone = self.context.zones.active_zone
        zone_rect = (
            pygame.Rect((zone.bounds.x, zone.bounds.y), (zone.bounds.width, zone.bounds.height))
            if zone
            else pygame.Rect((0, 0), self.screen_size)
        )
        obstacles = self._zone_obstacles(zone) if zone else []
        self.zone_prompt = f"{zone.name.title()}: {zone.description}" if zone else "Exploring the wilderness."

        zone_center = (zone_rect.centerx, zone_rect.centery)

        hero_definition = definitions.get(PLAYER_NAME, {})
        hero_appearance = appearances.create(hero_definition.get("appearance", "hero"))
        hero_rect = pygame.Rect((0, 0), (54, 54))
        hero_spawn = zone.get_spawn_point("player", (zone_center[0] - 80, zone_center[1] + 60)) if zone else None
        hero_rect.center = hero_spawn or (zone_center[0] - 80, zone_center[1] + 60)
        hero_rect = self._resolve_obstacle_collision(hero_rect, hero_rect, obstacles, zone_rect)
        hero_rect = self._clamp_to_bounds(hero_rect, zone_rect)
        actors[PLAYER_NAME] = Actor(
            name=PLAYER_NAME,
            color=pygame.Color(hero_appearance.color),
            rect=hero_rect,
        )

        guide_color = pygame.Color(214, 185, 110)
        guide_rect = pygame.Rect((0, 0), (54, 54))
        guide_spawn = zone.get_spawn_point("quest_giver", zone_center) if zone else zone_center
        guide_rect.center = guide_spawn
        guide_rect = self._resolve_obstacle_collision(guide_rect, guide_rect, obstacles, zone_rect)
        guide_rect = self._clamp_to_bounds(guide_rect, zone_rect)
        actors[QUEST_GIVER_NAME] = Actor(
            name=QUEST_GIVER_NAME,
            color=guide_color,
            rect=guide_rect,
            speed=0,
        )
        self.quest_log.append("Check in with the Guide near the fire for available work.")
        return actors

    def _zone_rect(self, zone: Zone | None) -> pygame.Rect | None:
        if not zone:
            return None
        bounds = zone.bounds
        return pygame.Rect((bounds.x, bounds.y), (bounds.width, bounds.height))

    def _zone_render_offset(self, zone: Zone | None) -> tuple[int, int]:
        bounds = self._zone_rect(zone)
        if not bounds:
            return (0, 0)

        margin = 18
        offset_x = (self.screen_size[0] - bounds.width) // 2 - bounds.x
        offset_y = (self.screen_size[1] - bounds.height) // 2 - bounds.y

        offset_x = max(margin - bounds.x, offset_x)
        offset_y = max(margin - bounds.y, offset_y)
        return (offset_x, offset_y)

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

    def _screen_rect(self, rect: pygame.Rect) -> pygame.Rect:
        return rect.move(self.render_offset)

    def _screen_point(self, point: tuple[float, float] | tuple[int, int]) -> tuple[int, int]:
        return (int(point[0] + self.render_offset[0]), int(point[1] + self.render_offset[1]))

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
        self._apply_zone_settings(zone)
        bounds = self._zone_rect(zone) or pygame.Rect((0, 0), self.screen_size)
        obstacles = self._zone_obstacles(zone)
        rng = Random(f"{zone.name}-{zone.danger_level}")

        entry_rect = self._entry_position_for_zone(player, zone, direction)
        spawn_center = zone.get_spawn_point("player", (entry_rect.centerx, entry_rect.centery))
        entry_rect.center = spawn_center
        clamped_x = max(bounds.x, min(bounds.x + bounds.width - entry_rect.width, entry_rect.x))
        clamped_y = max(bounds.y, min(bounds.y + bounds.height - entry_rect.height, entry_rect.y))
        entry_rect.x, entry_rect.y = clamped_x, clamped_y
        player.rect = self._resolve_obstacle_collision(player.rect, entry_rect, obstacles, bounds)
        player.rect = self._clamp_to_bounds(player.rect, bounds)

        self.target_spawned = False
        if zone.is_static:
            guide_color = pygame.Color(214, 185, 110)
            guide_rect = pygame.Rect((0, 0), (54, 54))
            guide_spawn = zone.get_spawn_point("quest_giver", bounds.center)
            guide_rect.center = guide_spawn
            resolved = self._resolve_obstacle_collision(player.rect, guide_rect, obstacles, bounds)
            self.actors[QUEST_GIVER_NAME] = Actor(
                name=QUEST_GIVER_NAME,
                color=guide_color,
                rect=resolved,
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
        try:
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
                player.move(dx, dy, self.screen_size)
        except Exception as exc:  # pragma: no cover - defensive bounds guard
            log_with_fields(
                logger,
                logging.ERROR,
                "Failed to process movement within bounds",
                error=str(exc),
                zone=getattr(active_zone, "name", "none"),
            )
            player.move(dx, dy, self.screen_size)

        self.tutorial.record_movement(dx, dy)

    def _attempt_attack(self, target_name: str | None = None) -> bool:
        player = self.actors.get(PLAYER_NAME)
        target_label = target_name or self.target_name
        target = self.actors.get(target_label)
        if not player or not target or not player.can_attack():
            return False

        if player.rect.colliderect(target.rect.inflate(8, 8)):
            log_with_fields(logger, logging.INFO, "Real-time attack", attacker=player.name, defender=target.name)
            self.bus.publish("combat.attack", attacker=player.name, defender=target.name)
            player.trigger_attack()
            self.tutorial.record_attack()
            return True
        return False

    def _quests(self) -> list:
        return list(self.context.quests.quests.values())

    def _active_quest(self):
        if not self.context.quests.quests:
            return None
        priorities = ("accepted", "completed", "available", "locked")
        for status in priorities:
            quest = next((q for q in self._quests() if q.status == status), None)
            if quest:
                return quest
        return next(iter(self._quests()), None)

    def _active_stage(self, quest):
        if quest and quest.stages and quest.current_stage < len(quest.stages):
            return quest.stages[quest.current_stage]
        return None

    def _quest_targets(self, quest) -> Dict[str, int]:
        if not quest:
            return {}
        stage = self._active_stage(quest)
        if stage and stage.target_monsters:
            return stage.target_monsters
        return quest.target_monsters or {}

    def _quest_progress_summary(self, quest) -> str | None:
        targets = self._quest_targets(quest)
        if not quest or not targets:
            return None
        progress = quest.progress
        if quest.stages and quest.current_stage < len(quest.stage_progress):
            progress = quest.stage_progress[quest.current_stage]
        segments = [f"{name}: {progress.get(name, 0)}/{count}" for name, count in targets.items()]
        return ", ".join(segments)

    def _quest_prompts(self) -> list[str]:
        quest = self._active_quest()
        if not quest:
            return [f"Talk to {QUEST_GIVER_NAME} for guidance."]

        prompts: list[str] = []
        stage = self._active_stage(quest)
        description = stage.description if stage else quest.description
        progress = self._quest_progress_summary(quest)

        if quest.status == "available":
            prompts.append(f"Press E near the Guide to accept: {description}")
        elif quest.status == "accepted":
            prompts.append(f"Objective: {description}")
            if progress:
                prompts.append(f"Progress: {progress}")
        elif quest.status == "completed":
            prompts.append(f"Return to {QUEST_GIVER_NAME} to turn in {quest.description}.")
        elif quest.status == "locked":
            prereqs = ", ".join(quest.prerequisites)
            prompts.append(f"Complete {prereqs} to unlock the next task.")
        else:
            prompts.append(f"Quest complete: {quest.description}.")

        return prompts

    def _objective_target_position(self) -> Tuple[int, int] | None:
        quest = self._active_quest()
        if not quest:
            return None

        if quest.status == "completed":
            guide = self.actors.get(QUEST_GIVER_NAME)
            return guide.rect.center if guide else None

        targets = self._quest_targets(quest)
        for target_name in targets:
            actor = self.actors.get(target_name)
            if actor:
                return actor.rect.center

        guide = self.actors.get(QUEST_GIVER_NAME)
        if guide:
            return guide.rect.center
        return None

    def _target_quest(self):
        for quest in self._quests():
            if quest.status != "accepted":
                continue
            targets = self._quest_targets(quest)
            if targets and self.target_name in targets:
                return quest
        return None

    def _player_near(self, actor_name: str, radius: int = 12) -> bool:
        player = self.actors.get(PLAYER_NAME)
        actor = self.actors.get(actor_name)
        if not player or not actor:
            return False
        return player.rect.colliderect(actor.rect.inflate(radius, radius))

    def _handle_interaction(self) -> bool:
        if not self._player_near(QUEST_GIVER_NAME):
            return False

        self.bus.publish("npc.talked", npc=QUEST_GIVER_NAME, owner=PLAYER_NAME)
        completed = [quest for quest in self._quests() if quest.status == "completed"]
        if completed:
            quest = completed[0]
            self.bus.publish("quest.turned_in", quest=quest.identifier, owner=PLAYER_NAME)
            self.quest_log.append(f"Quest turned in: {quest.description}.")
            self.target_spawned = False
            return True

        available = [quest for quest in self._quests() if quest.status == "available"]
        if available:
            quest = available[0]
            self.bus.publish("quest.accepted", quest=quest.identifier, owner=PLAYER_NAME)
            self.quest_log.append(f"Quest accepted: {quest.description}.")
            if self.target_name in self._quest_targets(quest):
                self.target_defeated = False
                self.target_spawned = False
            return True

        locked = [quest for quest in self._quests() if quest.status == "locked"]
        if locked:
            prereqs = ", ".join(locked[0].prerequisites)
            self.quest_log.append(f"Finish {prereqs} before taking on a new task.")
            return True
        return False

    def _handle_attack_click(self, pos: Tuple[int, int]) -> bool:
        world_pos = (pos[0] - self.render_offset[0], pos[1] - self.render_offset[1])
        for name, actor in self.actors.items():
            if name == PLAYER_NAME:
                continue
            if actor.rect.collidepoint(world_pos):
                self.target_name = name
                return self._attempt_attack(name)
        return False

    def _start_drag(self, pos: Tuple[int, int]) -> bool:
        if not self.show_inventory:
            return False
        slot = self._slot_for_position(pos)
        if not slot or not slot.item:
            return False
        self.dragging_slot = slot
        self.drag_offset = (pos[0] - slot.rect.x, pos[1] - slot.rect.y)
        return True

    def _drop_item(self, item: Item) -> None:
        removed = self.context.combat.remove_item(PLAYER_NAME, item.name)
        if removed:
            self.quest_log.append(f"Dropped {item.name.replace('_', ' ').title()} nearby.")

    def _complete_drag(self, pos: Tuple[int, int]) -> None:
        if not self.dragging_slot:
            return

        slot = self._slot_for_position(pos)
        item = self.dragging_slot.item
        combatant = self._player_combatant()
        if item and slot:
            if slot.category == "equip" and slot.slot_name == item.slot:
                self.context.combat.equip_item(PLAYER_NAME, item.name)
            elif slot.category == "pack" and self.dragging_slot.category == "equip":
                if combatant and self.dragging_slot.slot_name:
                    if combatant.equipped.get(self.dragging_slot.slot_name) is item:
                        combatant.equipped.pop(self.dragging_slot.slot_name, None)
            elif slot.category == "sell":
                try:
                    result = self.bus.publish("economy.sell", seller=PLAYER_NAME, store="camp", item=item.name)
                    payout = result.get("payout") if isinstance(result, dict) else None
                    if payout:
                        self.quest_log.append(f"Sold {item.name.replace('_', ' ').title()} for {payout}g.")
                except Exception as exc:  # pragma: no cover - defensive UX path
                    log_with_fields(logger, logging.WARNING, "Sell failed", item=item.name, error=str(exc))
            elif slot.category == "drop":
                self._drop_item(item)

        self.dragging_slot = None

    def _maybe_spawn_target(self) -> None:
        zone = self.context.zones.active_zone
        quest = self._target_quest()
        if self.target_spawned or not quest:
            return
        if not self._zone_allows_target(zone):
            log_with_fields(
                logger,
                logging.INFO,
                "Zone does not allow quest target",
                zone=getattr(zone, "name", "<none>"),
                target=self.target_name,
            )
            return

        try:
            definitions = self.context.bundle.characters.definitions()
            appearances = self.context.bundle.appearances
            appearance_name = definitions[self.target_name]["appearance"]
            appearance = appearances.create(appearance_name)
            bounds = self._zone_rect(zone) or pygame.Rect((0, 0), self.screen_size)
            spawn_center = zone.get_spawn_point("quest_target", (bounds.centerx + 180, bounds.centery))
            target_rect = pygame.Rect((0, 0), (54, 54))
            target_rect.center = spawn_center
            target_rect = self._resolve_obstacle_collision(
                target_rect, target_rect, self._zone_obstacles(zone), bounds
            )
            target_rect = self._clamp_to_bounds(target_rect, bounds)
            self.actors[self.target_name] = Actor(
                name=self.target_name,
                color=pygame.Color(appearance.color),
                rect=target_rect,
            )
            self.target_spawned = True
            self.quest_log.append(f"{self.target_name} has appeared beyond the campfire.")
        except Exception as exc:  # pragma: no cover - defensive spawn guard
            log_with_fields(
                logger,
                logging.ERROR,
                "Failed to spawn quest target within bounds",
                error=str(exc),
                zone=getattr(zone, "name", "unknown"),
            )

    def _zone_allows_target(self, zone: Zone | None) -> bool:
        if not zone:
            return False
        return (not zone.is_static) and zone.danger_level not in {"none", "low"} and zone.has_spawn(self.target_name)

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

    def _player_combatant(self):
        return self.context.combat.characters.get(PLAYER_NAME)

    def _render_loot_banner(self, screen: pygame.Surface) -> None:
        if not self.loot_banner or self.loot_banner_timer <= 0.0:
            return
        assert self.font is not None
        banner_text = self.font.render(self.loot_banner, True, (255, 223, 128))
        padding = 10
        rect = banner_text.get_rect()
        rect.centerx = self.screen_size[0] // 2
        rect.y = 10
        box = pygame.Rect(
            rect.x - padding,
            rect.y - padding,
            rect.width + padding * 2,
            rect.height + padding * 2,
        )
        pygame.draw.rect(screen, (70, 50, 20), box, border_radius=8)
        pygame.draw.rect(screen, (255, 223, 128), box, 2, border_radius=8)
        screen.blit(banner_text, (rect.x, rect.y))

    def _slot_for_position(self, pos: Tuple[int, int]) -> ItemSlot | None:
        for slot in self.equip_slots + self.pack_slots + self.action_slots:
            if slot.rect.collidepoint(pos):
                return slot
        return None

    def _draw_item_icon(self, screen: pygame.Surface, item: Item, rect: pygame.Rect, *, highlight: bool = False) -> None:
        assert self.font is not None
        pygame.draw.rect(screen, (28, 32, 40), rect, border_radius=6)
        border_color = self._rarity_color(item.rarity)
        border_width = 3 if highlight else 2
        pygame.draw.rect(screen, border_color, rect, border_width, border_radius=6)
        name = item.name.replace("_", " ").title()
        label = self.font.render(name, True, border_color)
        stats: list[str] = []
        if item.power:
            stats.append(f"P{item.power}")
        if item.defense:
            stats.append(f"D{item.defense}")
        if item.speed:
            stats.append(f"S{item.speed}")
        stat_label = self.font.render(", ".join(stats) or "—", True, (205, 210, 220))
        screen.blit(label, (rect.x + 8, rect.y + 6))
        screen.blit(stat_label, (rect.x + 8, rect.y + rect.height - 22))

    def _rarity_color(self, rarity: str | None) -> pygame.Color:
        return RARITY_COLORS.get(rarity, RARITY_COLORS[None])

    def _item_primary_stats(self, item: Item) -> Tuple[int, int, int]:
        return item.power, item.defense, item.speed

    def _render_item_tooltip(self, screen: pygame.Surface) -> None:
        if not self.hovered_slot or not self.hovered_slot.item or not self.font:
            return

        item = self.hovered_slot.item
        rarity_color = self._rarity_color(item.rarity)
        lines: list[tuple[str, pygame.Color]] = []
        lines.append((item.name.replace("_", " ").title(), rarity_color))
        rarity_label = f"{item.rarity.title()}" if item.rarity else "Unmarked"
        lines.append((f"{rarity_label} • {item.slot.title()}", pygame.Color(200, 205, 215)))
        lines.append((item.description, pygame.Color(215, 215, 215)))

        power, defense, speed = self._item_primary_stats(item)
        stat_bits = []
        if power:
            stat_bits.append(f"+{power} Power")
        if defense:
            stat_bits.append(f"+{defense} Defense")
        if speed:
            stat_bits.append(f"+{speed} Speed")
        if item.capacity_bonus:
            stat_bits.append(f"+{item.capacity_bonus} Capacity")
        if stat_bits:
            lines.append((", ".join(stat_bits), pygame.Color(190, 205, 235)))
        if item.max_durability:
            lines.append((f"Durability {item.durability}/{item.max_durability}", pygame.Color(180, 190, 210)))
        if item.value:
            lines.append((f"Value {item.value}g", pygame.Color(205, 190, 155)))

        compare = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
        combatant = self._player_combatant()
        equipped = combatant.equipped.get(item.slot) if combatant else None
        if compare and combatant and equipped and equipped is not item:
            new_stats = self._item_primary_stats(item)
            old_stats = self._item_primary_stats(equipped)
            deltas = [new - old for new, old in zip(new_stats, old_stats)]
            labels = ["Power", "Defense", "Speed"]
            for label_text, delta in zip(labels, deltas):
                if delta:
                    sign = "+" if delta > 0 else ""
                    color = pygame.Color(120, 200, 140) if delta > 0 else pygame.Color(205, 110, 110)
                    lines.append((f"Shift: {label_text} {sign}{delta} vs equipped", color))

        padding = 10
        max_width = 0
        rendered = []
        for text, color in lines:
            surf = self.font.render(text, True, color)
            rendered.append(surf)
            max_width = max(max_width, surf.get_width())
        height = sum(s.get_height() for s in rendered) + padding * 2 + (len(rendered) - 1) * 4
        tooltip_rect = pygame.Rect(self.mouse_pos[0] + 18, self.mouse_pos[1] + 18, max_width + padding * 2, height)
        pygame.draw.rect(screen, (24, 24, 30), tooltip_rect, border_radius=8)
        pygame.draw.rect(screen, rarity_color, tooltip_rect, 2, border_radius=8)
        cursor_y = tooltip_rect.y + padding
        for surf in rendered:
            screen.blit(surf, (tooltip_rect.x + padding, cursor_y))
            cursor_y += surf.get_height() + 4

    def _render_inventory_panel(self, screen: pygame.Surface) -> None:
        if not self.show_inventory:
            return

        assert self.font is not None
        combatant = self._player_combatant()
        if not combatant:
            return

        panel_width = 660
        panel_height = 360
        margin = 14
        panel_rect = pygame.Rect(self.screen_size[0] - panel_width - margin, margin, panel_width, panel_height)
        pygame.draw.rect(screen, (30, 36, 48), panel_rect, border_radius=10)
        pygame.draw.rect(screen, (90, 110, 130), panel_rect, 2, border_radius=10)

        self.pack_slots = []
        self.equip_slots = []
        self.action_slots = []

        title = self.font.render("Inventory (I) — drag to equip, sell, or drop", True, (220, 230, 235))
        screen.blit(title, (panel_rect.x + 12, panel_rect.y + 10))

        gold_amount = self.context.economy.wallets.get(PLAYER_NAME, combatant.gold)
        gold_text = self.font.render(f"Gold: {gold_amount}", True, (240, 210, 140))
        screen.blit(gold_text, (panel_rect.x + 12, panel_rect.y + 36))

        stats_line = self.font.render(
            f"STR {combatant.strength} | AGI {combatant.agility} | MAS {combatant.mastery}",
            True,
            (200, 210, 225),
        )
        screen.blit(stats_line, (panel_rect.x + 12, panel_rect.y + 58))

        skills = ", ".join(f"{name.replace('_', ' ').title()} {rank}" for name, rank in combatant.skills.items())
        skills_line = self.font.render(f"Skills: {skills or 'None learned yet'}", True, (180, 190, 210))
        screen.blit(skills_line, (panel_rect.x + 12, panel_rect.y + 78))

        slot_size = 66
        spacing = 10
        paper_rect = pygame.Rect(panel_rect.x + 12, panel_rect.y + 112, 240, panel_height - 130)
        pygame.draw.rect(screen, (28, 32, 42), paper_rect, border_radius=8)
        pygame.draw.rect(screen, (80, 96, 116), paper_rect, 1, border_radius=8)
        silhouette = self.font.render("Paper Doll", True, (120, 130, 145))
        screen.blit(silhouette, (paper_rect.centerx - silhouette.get_width() // 2, paper_rect.y + 8))

        center_x = paper_rect.centerx - slot_size // 2
        equip_positions = {
            "helm": (center_x, paper_rect.y + 32),
            "armor": (center_x, paper_rect.y + 110),
            "back": (center_x, paper_rect.y + 188),
            "mainhand": (paper_rect.x + 20, paper_rect.y + 110),
            "offhand": (paper_rect.right - slot_size - 20, paper_rect.y + 110),
        }

        dragging_item = self.dragging_slot.item if self.dragging_slot else None
        for slot_name, pos in equip_positions.items():
            rect = pygame.Rect(pos[0], pos[1], slot_size, slot_size)
            item = combatant.equipped.get(slot_name)
            highlight = rect.collidepoint(self.mouse_pos)
            pygame.draw.rect(screen, (36, 42, 54), rect, border_radius=8)
            pygame.draw.rect(screen, (110, 124, 140), rect, 1, border_radius=8)
            label = self.font.render(slot_name.title(), True, (130, 140, 150))
            screen.blit(label, (rect.centerx - label.get_width() // 2, rect.bottom + 2))
            self.equip_slots.append(ItemSlot(rect, item, slot_name, "equip"))
            if item and item is not dragging_item:
                self._draw_item_icon(screen, item, rect, highlight=highlight)
            elif not item:
                empty = self.font.render("Empty", True, (90, 100, 115))
                screen.blit(empty, (rect.centerx - empty.get_width() // 2, rect.centery - 10))

        pack_origin_x = paper_rect.right + 18
        pack_origin_y = panel_rect.y + 110
        cols = 5
        rows = max(3, (len(combatant.inventory) + cols - 1) // cols)
        capacity_note = self.font.render(
            f"Pack {len(combatant.inventory)}/{combatant.capacity()} (Shift to compare)", True, (190, 200, 210)
        )
        screen.blit(capacity_note, (pack_origin_x, paper_rect.y - 22))

        for idx in range(rows * cols):
            row = idx // cols
            col = idx % cols
            rect = pygame.Rect(
                pack_origin_x + col * (slot_size + spacing),
                pack_origin_y + row * (slot_size + spacing),
                slot_size,
                slot_size,
            )
            item = combatant.inventory[idx] if idx < len(combatant.inventory) else None
            highlight = rect.collidepoint(self.mouse_pos)
            pygame.draw.rect(screen, (32, 36, 44), rect, border_radius=6)
            pygame.draw.rect(screen, (70, 78, 92), rect, 1, border_radius=6)
            slot = ItemSlot(rect, item, None, "pack")
            self.pack_slots.append(slot)
            if item and item is not dragging_item:
                self._draw_item_icon(screen, item, rect, highlight=highlight)

        sell_rect = pygame.Rect(pack_origin_x, panel_rect.bottom - 68, 140, 52)
        drop_rect = pygame.Rect(sell_rect.right + 12, panel_rect.bottom - 68, 140, 52)
        action_style = pygame.Color(64, 78, 92)
        pygame.draw.rect(screen, action_style, sell_rect, border_radius=8)
        pygame.draw.rect(screen, (150, 180, 205), sell_rect, 2, border_radius=8)
        sell_label = self.font.render("Sell to Camp", True, (215, 225, 235))
        screen.blit(sell_label, (sell_rect.x + 12, sell_rect.y + 16))
        pygame.draw.rect(screen, action_style, drop_rect, border_radius=8)
        pygame.draw.rect(screen, (200, 150, 150), drop_rect, 2, border_radius=8)
        drop_label = self.font.render("Drop on Ground", True, (235, 225, 225))
        screen.blit(drop_label, (drop_rect.x + 8, drop_rect.y + 16))
        self.action_slots.append(ItemSlot(sell_rect, None, None, "sell"))
        self.action_slots.append(ItemSlot(drop_rect, None, None, "drop"))

        self.hovered_slot = self._slot_for_position(self.mouse_pos)
        if self.hovered_slot and self.hovered_slot.item:
            self._render_item_tooltip(screen)

        if dragging_item:
            drag_rect = pygame.Rect(
                self.mouse_pos[0] - self.drag_offset[0],
                self.mouse_pos[1] - self.drag_offset[1],
                slot_size,
                slot_size,
            )
            self._draw_item_icon(screen, dragging_item, drag_rect, highlight=True)

    def _transition_zone(self, direction: str) -> None:
        current = self.context.zones.active_zone
        if not current:
            return

        focus_spawn = self.target_name if self._target_quest() else None
        if current.is_static:
            next_zone = self.context.zones.spawn_outdoor_zone(focus_spawn=focus_spawn)
        else:
            destination = next(iter(self.context.zones.static_zones), None)
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

    def _render_combat_overlay(self, screen: pygame.Surface) -> None:
        combatant = self._player_combatant()
        if not combatant or not self.font:
            return

        try:
            char_class = self.context.bundle.classes.create(combatant.class_name)
            max_health = max(1, int(char_class.hit_points))
            resource_type = char_class.resource_type or "mana"
            max_resource = max(1, int(char_class.resource_max or char_class.mana or 1))
        except Exception:
            max_health = max(1, combatant.hit_points)
            resource_type = next(iter(combatant.resource_pools), "mana")
            max_resource = max(1, combatant.resource_pools.get(resource_type, 1))

        resource_value = combatant.resource_pools.get(resource_type, 0)
        health_ratio = min(1.0, combatant.hit_points / max_health)
        resource_ratio = min(1.0, resource_value / max_resource)

        bar_height = 68
        margin = 14
        radius = max(46, min(74, int(min(self.screen_size) * 0.09)))
        center_y = max(radius + margin, self.screen_size[1] - bar_height - margin - radius)
        left_center = (margin + radius, center_y)
        right_center = (self.screen_size[0] - margin - radius, center_y)

        self._draw_globe(
            screen,
            left_center,
            radius,
            health_ratio,
            pygame.Color(170, 60, 60),
            "Health",
            f"{combatant.hit_points}/{max_health}",
        )
        self._draw_globe(
            screen,
            right_center,
            radius,
            resource_ratio,
            pygame.Color(70, 110, 190),
            resource_type.replace("_", " ").title(),
            f"{resource_value}/{max_resource}",
        )

    def _draw_globe(
        self,
        screen: pygame.Surface,
        center: Tuple[int, int],
        radius: int,
        fill_ratio: float,
        base_color: pygame.Color,
        label: str,
        value_text: str,
    ) -> None:
        if not self.font:
            return

        ratio = max(0.0, min(1.0, fill_ratio))
        diameter = radius * 2
        globe_surface = pygame.Surface((diameter, diameter), pygame.SRCALPHA)

        fill_height = int(diameter * ratio)
        if fill_height > 0:
            fill_surface = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
            fill_surface.set_clip(pygame.Rect(0, diameter - fill_height, diameter, fill_height))
            pygame.draw.circle(fill_surface, base_color, (radius, radius), radius)
            fill_surface.set_clip(None)
            globe_surface.blit(fill_surface, (0, 0))

        pygame.draw.circle(globe_surface, (22, 28, 36, 220), (radius, radius), radius)
        pygame.draw.circle(globe_surface, (110, 140, 170), (radius, radius), radius, 3)
        pygame.draw.circle(globe_surface, (255, 255, 255, 60), (radius, radius - radius // 3), radius // 2)

        shadow = pygame.Surface((diameter + 10, diameter + 10), pygame.SRCALPHA)
        pygame.draw.circle(shadow, (0, 0, 0, 80), (shadow.get_width() // 2, shadow.get_height() // 2), radius + 4)
        screen.blit(shadow, (center[0] - shadow.get_width() // 2, center[1] - shadow.get_height() // 2 + 4))
        screen.blit(globe_surface, (center[0] - radius, center[1] - radius))

        label_surface = self.font.render(label, True, (235, 240, 245))
        label_pos = (center[0] - label_surface.get_width() // 2, center[1] - radius - label_surface.get_height() - 6)
        screen.blit(label_surface, label_pos)

        value_surface = self.font.render(value_text, True, (230, 235, 240))
        value_pos = (
            center[0] - value_surface.get_width() // 2,
            center[1] - value_surface.get_height() // 2,
        )
        screen.blit(value_surface, value_pos)

    def _render_objective_indicator(self, screen: pygame.Surface) -> None:
        if not self.show_objective_indicator:
            return

        player = self.actors.get(PLAYER_NAME)
        if not player:
            return

        target_pos = self._objective_target_position()
        if not target_pos:
            return

        px, py = player.rect.center
        dx = target_pos[0] - px
        dy = target_pos[1] - py
        magnitude = max(1.0, (dx ** 2 + dy ** 2) ** 0.5)
        norm_x, norm_y = dx / magnitude, dy / magnitude

        start = self._screen_point((px + norm_x * 40, py + norm_y * 40))
        end = self._screen_point((px + norm_x * 80, py + norm_y * 80))
        color = (240, 200, 120)
        pygame.draw.line(screen, color, start, end, 4)

        perp_x, perp_y = -norm_y, norm_x
        arrow_tip = end
        arrow_left = (
            int(end[0] - norm_x * 14 + perp_x * 8),
            int(end[1] - norm_y * 14 + perp_y * 8),
        )
        arrow_right = (
            int(end[0] - norm_x * 14 - perp_x * 8),
            int(end[1] - norm_y * 14 - perp_y * 8),
        )
        pygame.draw.polygon(screen, color, [arrow_tip, arrow_left, arrow_right])

    def _collect_prompts(self) -> list[str]:
        prompts: list[str] = []
        if self.zone_prompt:
            prompts.append(self.zone_prompt)

        tutorial_prompts = self.tutorial.prompts()
        if tutorial_prompts:
            prompts.extend(tutorial_prompts)
        else:
            prompts.append("Press H to re-open control hints.")

        prompts.append("Press I to toggle your inventory. Drag items to equip, sell, or drop.")
        prompts.append("Press L to toggle the objective indicator.")
        prompts.append("Click monsters to attack when you're in range.")
        prompts.extend(self._quest_prompts())
        return prompts

    def _render_zone_badge(self, screen: pygame.Surface, margin: int) -> None:
        if not self.context.zones.active_zone or not self.font:
            return

        zone = self.context.zones.active_zone
        label = f"{zone.name} — danger {zone.danger_level}"
        text = self.font.render(label, True, (200, 205, 215))
        padding = 8
        rect = pygame.Rect(margin, margin, text.get_width() + padding * 2, text.get_height() + padding * 2)
        pygame.draw.rect(screen, (26, 30, 38), rect, border_radius=8)
        pygame.draw.rect(screen, (90, 110, 130), rect, 1, border_radius=8)
        screen.blit(text, (rect.x + padding, rect.y + padding))

    def _render_interaction_hint(self, screen: pygame.Surface, *, margin: int, bar_height: int) -> None:
        if not self.interaction_hint or not self.font:
            return

        bubble = self.font.render(self.interaction_hint, True, (225, 230, 240))
        padding = 10
        rect = pygame.Rect(
            margin,
            self.screen_size[1] - bar_height - bubble.get_height() - padding * 2 - margin,
            bubble.get_width() + padding * 2,
            bubble.get_height() + padding * 2,
        )
        pygame.draw.rect(screen, (24, 28, 36), rect, border_radius=10)
        pygame.draw.rect(screen, (110, 140, 165), rect, 1, border_radius=10)
        screen.blit(bubble, (rect.x + padding, rect.y + padding))

    def _render_help_overlay(self, screen: pygame.Surface) -> None:
        if not self.show_help_overlay or not self.font:
            return

        prompts = self._collect_prompts()
        if not prompts:
            return

        padding = 12
        line_height = 22
        max_width = max(self.font.size(line)[0] for line in prompts)
        width = min(self.screen_size[0] - 40, max_width + padding * 2)
        height = line_height * len(prompts) + padding * 2
        rect = pygame.Rect(20, 20, width, height)
        pygame.draw.rect(screen, (20, 24, 30), rect, border_radius=10)
        pygame.draw.rect(screen, (120, 140, 165), rect, 1, border_radius=10)
        y_cursor = rect.y + padding
        for line in prompts:
            surf = self.font.render(line, True, (210, 215, 222))
            screen.blit(surf, (rect.x + padding, y_cursor))
            y_cursor += line_height

    def _wrap_text(self, text: str, max_width: int, *, bullet_prefix: str = "") -> list[str]:
        assert self.font is not None

        if not text:
            return []

        words = text.split()
        if not words:
            return []

        lines: list[str] = []
        indent = " " * len(bullet_prefix)
        current = f"{bullet_prefix}{words[0]}" if bullet_prefix else words[0]

        for word in words[1:]:
            candidate = f"{current} {word}"
            if self.font.size(candidate)[0] <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = f"{indent}{word}" if indent else word

        lines.append(current)
        return lines

    def _render_quest_panel(self, screen: pygame.Surface, bar_height: int) -> None:
        assert self.font is not None
        margin = 10
        panel_width = 320
        available_height = self.screen_size[1] - bar_height - margin * 2

        if not self.show_quests_panel:
            tab_height = 160
            tab_y = (self.screen_size[1] - bar_height - tab_height) // 2
            self.quest_panel_tab = pygame.Rect(self.screen_size[0] - 12, tab_y, 12, tab_height)
            pygame.draw.rect(screen, (38, 44, 56), self.quest_panel_tab, border_radius=6)
            pygame.draw.rect(screen, (120, 140, 170), self.quest_panel_tab, 1, border_radius=6)
            title = self.font.render("Quests", True, (190, 200, 210))
            rotated = pygame.transform.rotate(title, 90)
            screen.blit(rotated, (self.quest_panel_tab.x - rotated.get_width() // 2, tab_y + tab_height // 2 - rotated.get_height() // 2))
            return
        self.quest_panel_tab = None

        panel_rect = pygame.Rect(
            self.screen_size[0] - panel_width,
            margin,
            panel_width - margin,
            available_height,
        )
        surface = pygame.Surface((panel_rect.width, panel_rect.height), pygame.SRCALPHA)
        surface.fill((20, 24, 32, 215))
        pygame.draw.rect(surface, (110, 130, 155), surface.get_rect(), 2, border_radius=12)
        header = self.font.render("Quest Log", True, (225, 235, 245))
        surface.blit(header, (14, 10))

        quests = self._quests()
        y_cursor = 38
        line_spacing = 6
        max_text_width = panel_rect.width - 28

        def render_section(title: str, lines: list[str], *, accent: pygame.Color = pygame.Color(170, 200, 230)) -> None:
            nonlocal y_cursor
            if not lines:
                return
            heading = self.font.render(title, True, accent)
            surface.blit(heading, (14, y_cursor))
            y_cursor += heading.get_height() + 4
            for line in lines:
                wrapped = self._wrap_text(line, max_width=max_text_width, bullet_prefix="• ")
                for wrapped_line in wrapped:
                    text = self.font.render(wrapped_line, True, (210, 215, 220))
                    if y_cursor + text.get_height() > panel_rect.height - 6:
                        return
                    surface.blit(text, (18, y_cursor))
                    y_cursor += text.get_height() + line_spacing
            y_cursor += 4

        current = self._active_quest()
        stage = self._active_stage(current)
        if current:
            tasks: list[str] = []
            targets = self._quest_targets(current)
            if current.stage_progress and current.current_stage < len(current.stage_progress):
                progress = current.stage_progress[current.current_stage]
            else:
                progress = current.progress
            for name, goal in targets.items():
                count = progress.get(name, 0) if isinstance(progress, dict) else 0
                tasks.append(f"{name.replace('_', ' ').title()}: {count}/{goal}")
            description = stage.description if stage else current.description
            render_section(
                f"Current: {current.description}",
                ([description] if description else []) + tasks,
            )

        active_quests = [q for q in quests if q.status in {"accepted", "available"} and q is not current]
        render_section(
            "Tracked Quests",
            [f"{q.description} ({q.status.replace('_', ' ')})" for q in active_quests],
        )

        completed = [q for q in quests if q.status == "completed"]
        render_section("Completed", [q.description for q in completed], accent=pygame.Color(170, 210, 180))

        available = [q for q in quests if q.status == "available" and q is not current]
        if current and available:
            render_section("Other Offers", [q.description for q in available])

        if not quests:
            empty = self.font.render("No quests yet.", True, (180, 190, 200))
            surface.blit(empty, (14, y_cursor))

        screen.blit(surface, panel_rect)

    def _render_skills_panel(self, screen: pygame.Surface, bar_height: int) -> None:
        if not self.show_skills_panel or not self.font:
            return

        combatant = self._player_combatant()
        if not combatant:
            return

        margin = 12
        panel_width = 260
        panel_height = 200
        panel_rect = pygame.Rect(
            margin,
            self.screen_size[1] - bar_height - panel_height - margin,
            panel_width,
            panel_height,
        )
        pygame.draw.rect(screen, (26, 30, 38), panel_rect, border_radius=10)
        pygame.draw.rect(screen, (90, 110, 130), panel_rect, 2, border_radius=10)
        header = self.font.render("Skills", True, (215, 225, 235))
        screen.blit(header, (panel_rect.x + 12, panel_rect.y + 10))

        abilities = []
        for name, definition in self.context.bundle.abilities.definitions().items():
            if definition.get("class_name") == combatant.class_name:
                abilities.append(name)

        y_cursor = panel_rect.y + 34
        line_height = 20
        if abilities:
            for ability in abilities[:6]:
                rank = combatant.skills.get(ability, 0)
                label = ability.replace("_", " ").title()
                text = self.font.render(f"{label} — Rank {rank}", True, (195, 205, 215))
                screen.blit(text, (panel_rect.x + 12, y_cursor))
                y_cursor += line_height
        else:
            note = self.font.render("No class abilities yet.", True, (170, 180, 190))
            screen.blit(note, (panel_rect.x + 12, y_cursor))

    def _render_toolbar(self, screen: pygame.Surface, bar_height: int) -> None:
        assert self.font is not None
        margin = 10
        bar_rect = pygame.Rect(margin, self.screen_size[1] - bar_height - margin, self.screen_size[0] - margin * 2, bar_height)
        overlay = pygame.Surface((bar_rect.width, bar_rect.height), pygame.SRCALPHA)
        overlay.fill((12, 16, 22, 160))
        pygame.draw.rect(overlay, (90, 110, 130), overlay.get_rect(), 1, border_radius=12)
        screen.blit(overlay, bar_rect)

        button_size = 48
        spacing = 8
        buttons = [
            ("menu", "≡", self.show_menu_panel or self.show_help_overlay),
            ("inventory", "I", self.show_inventory),
            ("skills", "S", self.show_skills_panel),
            ("quests", "Q", self.show_quests_panel),
        ]

        total_width = len(buttons) * button_size + (len(buttons) - 1) * spacing
        start_x = bar_rect.centerx - total_width // 2
        y = bar_rect.y + (bar_height - button_size) // 2
        self.toolbar_buttons = []
        for idx, (name, label, active) in enumerate(buttons):
            rect = pygame.Rect(start_x + idx * (button_size + spacing), y, button_size, button_size)
            self.toolbar_buttons.append((name, rect))
            base_color = (38, 44, 56)
            accent = (120, 180, 200) if active else (90, 110, 130)
            pygame.draw.rect(screen, base_color, rect, border_radius=10)
            pygame.draw.rect(screen, accent, rect, 2, border_radius=10)
            text = self.font.render(label, True, accent)
            screen.blit(text, (rect.centerx - text.get_width() // 2, rect.centery - text.get_height() // 2))

    def _handle_toolbar_click(self, pos: Tuple[int, int]) -> bool:
        for name, rect in self.toolbar_buttons:
            if rect.collidepoint(pos):
                if name == "menu":
                    self.show_menu_panel = not self.show_menu_panel
                    self.show_help_overlay = self.show_menu_panel
                elif name == "inventory":
                    self.show_inventory = not self.show_inventory
                elif name == "skills":
                    self.show_skills_panel = not self.show_skills_panel
                elif name == "quests":
                    self.show_quests_panel = not self.show_quests_panel
                return True

        if self.quest_panel_tab and self.quest_panel_tab.collidepoint(pos):
            self.show_quests_panel = True
            return True
        return False

    def _render(self, screen: pygame.Surface) -> None:
        screen.fill(self.background)
        assert self.font is not None
        self.interaction_hint = None

        zone = self.context.zones.active_zone
        self.render_offset = self._zone_render_offset(zone)
        if zone:
            self._render_zone(screen, zone)
            self._render_minimap(screen, zone)

        for name, actor in self.actors.items():
            pygame.draw.rect(screen, actor.color, self._screen_rect(actor.rect), border_radius=6)
            # Keep the playfield free of floating text; lean on HUD panels instead.

        self._render_objective_indicator(screen)
        self._render_loot_banner(screen)

        margin = 12
        bar_height = max(58, int(self.screen_size[1] * 0.08))
        quest = self._active_quest()
        status = quest.status if quest else "none"
        self._render_zone_badge(screen, margin)

        if self._player_near(QUEST_GIVER_NAME):
            self.interaction_hint = "Press E to talk" if status != "turned_in" else "Enjoy the fire."

        self._render_quest_panel(screen, bar_height)
        self._render_skills_panel(screen, bar_height)
        self._render_inventory_panel(screen)
        self._render_combat_overlay(screen)
        self._render_help_overlay(screen)
        self._render_interaction_hint(screen, margin=margin, bar_height=bar_height)
        self._render_toolbar(screen, bar_height)

        pygame.display.flip()

    def _render_zone(self, screen: pygame.Surface, zone: Zone) -> None:
        bounds = self._zone_rect(zone)
        if not bounds:
            return
        screen_bounds = self._screen_rect(bounds)
        pygame.draw.rect(screen, (28, 34, 46), screen_bounds, border_radius=12)
        pygame.draw.rect(screen, self.zone_boundary_color, screen_bounds, width=5, border_radius=12)

        for obstacle in self._zone_obstacles(zone):
            screen_obstacle = self._screen_rect(obstacle)
            pygame.draw.rect(screen, self.obstacle_color, screen_obstacle, border_radius=6)
            pygame.draw.rect(screen, (120, 140, 170), screen_obstacle, width=2, border_radius=6)

    def _render_minimap(self, screen: pygame.Surface, zone: Zone) -> None:
        if not self.font:
            return

        bounds = self._zone_rect(zone)
        if not bounds:
            return

        margin = 12
        max_dimension = min(max(self.screen_size) * 0.25, 240)
        map_size = int(max(170, max_dimension))
        map_rect = pygame.Rect(
            self.screen_size[0] - map_size - margin,
            margin,
            map_size,
            map_size,
        )

        pygame.draw.rect(screen, (16, 20, 28), map_rect, border_radius=12)
        pygame.draw.rect(screen, (90, 120, 150), map_rect, 2, border_radius=12)

        padding = 10
        available_w = map_rect.width - padding * 2
        available_h = map_rect.height - padding * 2
        scale = min(available_w / bounds.width, available_h / bounds.height)
        content_w = bounds.width * scale
        content_h = bounds.height * scale
        origin_x = map_rect.x + padding + (available_w - content_w) / 2
        origin_y = map_rect.y + padding + (available_h - content_h) / 2

        def project_rect(rect: pygame.Rect) -> pygame.Rect:
            return pygame.Rect(
                int(origin_x + (rect.x - bounds.x) * scale),
                int(origin_y + (rect.y - bounds.y) * scale),
                max(2, int(rect.width * scale)),
                max(2, int(rect.height * scale)),
            )

        pygame.draw.rect(
            screen,
            (40, 60, 82),
            pygame.Rect(int(origin_x), int(origin_y), int(content_w), int(content_h)),
            2,
            border_radius=8,
        )

        for obstacle in self._zone_obstacles(zone):
            projected = project_rect(obstacle)
            pygame.draw.rect(screen, (65, 85, 115), projected, border_radius=4)
            pygame.draw.rect(screen, (110, 140, 175), projected, 1, border_radius=4)

        for actor in self.actors.values():
            rect = project_rect(actor.rect)
            center = (rect.centerx, rect.centery)
            color = pygame.Color(200, 70, 70) if actor.name == self.target_name else actor.color
            if actor.name == PLAYER_NAME:
                color = pygame.Color(240, 220, 140)
            pygame.draw.circle(screen, color, center, max(3, int(6 * scale)), width=0)
            pygame.draw.circle(screen, (12, 14, 18), center, max(3, int(6 * scale)), 1)

        label = self.font.render(zone.name.title(), True, (210, 220, 235))
        screen.blit(label, (map_rect.x + 12, map_rect.y + 8))

    def _clamp_to_bounds(self, rect: pygame.Rect, bounds: pygame.Rect) -> pygame.Rect:
        clamped = pygame.Rect(
            max(bounds.x, min(bounds.x + bounds.width - rect.width, rect.x)),
            max(bounds.y, min(bounds.y + bounds.height - rect.height, rect.y)),
            rect.width,
            rect.height,
        )
        if clamped != rect:
            log_with_fields(
                logger,
                logging.WARNING,
                "Clamped actor to zone bounds",
                original=(rect.x, rect.y, rect.width, rect.height),
                clamped=(clamped.x, clamped.y, clamped.width, clamped.height),
            )
        return clamped

    def _handle_defeat(self) -> None:
        defender = self.context.combat.characters.get(self.target_name)
        if defender and defender.hit_points <= 0 and not self.target_defeated:
            log_with_fields(logger, logging.INFO, "Enemy defeated", defender=defender.name)
            self.target_defeated = True
            self.target_spawned = False
            self.actors.pop(self.target_name, None)
            self.quest_log.append(f"{self.target_name} is defeated.")
            target_quest = self._target_quest()
            if target_quest:
                self.quest_log.append(f"Return to {QUEST_GIVER_NAME} to turn in {target_quest.description}.")

    def _on_quest_completed(self, event) -> None:
        quest_id = event.payload["quest"]
        record = self.context.quests.quests.get(quest_id)
        description = record.description if record else quest_id
        self.quest_log.append(f"Quest objective complete: {description}.")

    def _on_quest_turned_in(self, event) -> None:
        quest_id = event.payload.get("quest", "")
        record = self.context.quests.quests.get(quest_id)
        description = record.description if record else quest_id
        self.quest_log.append(f"Turned in quest: {description}.")

        reward = event.payload.get("reward_gold")
        if reward:
            self.quest_log.append(f"Received {reward} gold from the Guide.")
        items = event.payload.get("reward_items") or []
        if items:
            named = ", ".join(item.replace("_", " ").title() for item in items)
            self.quest_log.append(f"Received items: {named}.")
        if not reward and not items:
            self.quest_log.append("The Guide thanks you for your help.")

    def _on_quest_unlocked(self, event) -> None:
        quest_id = event.payload.get("quest", "an unknown task")
        self.quest_log.append(f"New quest available: {quest_id}.")

    def _on_quest_stage_advanced(self, event) -> None:
        quest_id = event.payload.get("quest", "quest")
        description = event.payload.get("description", "Next objective ready.")
        self.quest_log.append(f"{quest_id} advanced: {description}")

    def _on_quest_progress(self, event) -> None:
        quest_id = event.payload.get("quest")
        progress = event.payload.get("progress", {})
        defeated = event.payload.get("defeated")
        if not quest_id or defeated is None:
            return
        target_text = ", ".join(f"{name}: {count}" for name, count in progress.items())
        self.quest_log.append(f"Progress for {quest_id}: {target_text}.")

    def _on_item_added(self, event) -> None:
        owner = event.payload.get("owner")
        if owner != PLAYER_NAME:
            return
        item = event.payload.get("item", "unknown item")
        self.loot_banner = f"New loot: {item.replace('_', ' ').title()}"
        self.loot_banner_timer = 3.5
        self.show_inventory = True

    def _on_zone_changed(self, event) -> None:
        current = event.payload.get("current", "unknown")
        danger = event.payload.get("danger", "unknown")
        direction = event.payload.get("direction")
        direction_note = f" via {direction}" if direction else ""
        self.quest_log.append(f"Entered {current}{direction_note}. Danger: {danger}.")

    def run(self) -> None:
        pygame.init()
        self.font = pygame.font.SysFont("arial", 18)
        try:
            self.screen_size = self._detect_display_size()
            screen = pygame.display.set_mode(self.screen_size, pygame.FULLSCREEN)
            self.display_initialized = True
        except Exception as exc:  # pragma: no cover - defensive video fallback
            log_with_fields(logger, logging.WARNING, "Fullscreen mode failed, falling back", error=str(exc))
            self.screen_size = SCREEN_SIZE
            screen = pygame.display.set_mode(self.screen_size)
            self.display_initialized = True
        clock = pygame.time.Clock()
        self.running = True

        while self.running:
            dt = clock.tick(60) / 1000.0
            self.tutorial.update(dt)
            self.loot_banner_timer = max(0.0, self.loot_banner_timer - dt)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                if event.type == pygame.MOUSEMOTION:
                    self.mouse_pos = event.pos
                if event.type == pygame.MOUSEBUTTONDOWN:
                    self.mouse_pos = event.pos
                    if event.button == 1:
                        if self._handle_toolbar_click(event.pos):
                            continue
                        if self.show_inventory and self._start_drag(event.pos):
                            continue
                        self._handle_attack_click(event.pos)
                if event.type == pygame.MOUSEBUTTONUP:
                    self.mouse_pos = event.pos
                    if event.button == 1 and self.dragging_slot:
                        self._complete_drag(event.pos)
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        self._attempt_attack()
                    if event.key == pygame.K_e:
                        if self._handle_interaction():
                            self.tutorial.record_interaction()
                    if event.key == pygame.K_h:
                        self.tutorial.request_help()
                        self.show_help_overlay = not self.show_help_overlay
                    if event.key == pygame.K_i:
                        self.show_inventory = not self.show_inventory
                    if event.key == pygame.K_l:
                        self.show_objective_indicator = not self.show_objective_indicator

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
