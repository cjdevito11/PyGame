"""Pygame-powered real-time prototype for the data-driven MMORPG skeleton."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from typing import Callable, Dict, Sequence, Tuple

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
class SpriteSheet:
    """Lightweight holder for animation frames keyed by state and direction."""

    frames: Dict[str, Dict[str, list[pygame.Surface]]]
    base_color: pygame.Color

    def sequence(self, state: str, direction: str) -> list[pygame.Surface]:
        return self.frames.get(state, {}).get(direction, [])


@dataclass
class Actor:
    name: str
    rect: pygame.Rect
    speed: float = 220.0
    attack_cooldown: float = 0.35
    _cooldown_timer: float = 0.0
    sprite_sheet: SpriteSheet | None = None
    sprite_name: str | None = None
    current_state: str = "idle"
    facing: str = "south"
    frame_index: int = 0
    frame_timer: float = 0.0
    animation_speed: float = 0.12
    minimap_color: pygame.Color = field(default_factory=lambda: pygame.Color(180, 185, 200))

    def move(self, dx: float, dy: float, bounds: Tuple[int, int]) -> None:
        self.rect.x = max(0, min(bounds[0] - self.rect.width, int(self.rect.x + dx)))
        self.rect.y = max(0, min(bounds[1] - self.rect.height, int(self.rect.y + dy)))

    def update_cooldown(self, dt: float) -> None:
        self._cooldown_timer = max(0.0, self._cooldown_timer - dt)

    def can_attack(self) -> bool:
        return self._cooldown_timer <= 0.0

    def trigger_attack(self) -> None:
        self._cooldown_timer = self.attack_cooldown

    def set_facing(self, dx: float, dy: float) -> None:
        if abs(dx) > abs(dy):
            self.facing = "east" if dx > 0 else "west"
        elif dy != 0:
            self.facing = "south" if dy > 0 else "north"

    def play_attack(self) -> None:
        self.current_state = "attack"
        self.frame_index = 0
        self.frame_timer = 0.0

    def update_animation(self, dt: float, *, moving: bool = False) -> None:
        next_state = "walk" if moving else "idle"
        if self.current_state != "attack" and self.current_state != next_state:
            self.current_state = next_state
            self.frame_index = 0
            self.frame_timer = 0.0

        frames = self._frames_for_state(self.current_state)
        self.frame_timer += dt
        if not frames:
            return

        if self.current_state == "attack":
            if self.frame_timer >= self.animation_speed:
                self.frame_timer -= self.animation_speed
                self.frame_index += 1
                if self.frame_index >= len(frames):
                    self.current_state = next_state
                    self.frame_index = 0
                    self.frame_timer = 0.0
        else:
            if self.frame_timer >= self.animation_speed:
                self.frame_timer -= self.animation_speed
                self.frame_index = (self.frame_index + 1) % len(frames)

    def _frames_for_state(self, state: str) -> list[pygame.Surface]:
        if not self.sprite_sheet:
            return []
        return self.sprite_sheet.sequence(state, self.facing)

    def current_frame(self) -> pygame.Surface | None:
        frames = self._frames_for_state(self.current_state)
        if not frames:
            return None
        return frames[min(self.frame_index, len(frames) - 1)]


@dataclass
class ItemSlot:
    rect: pygame.Rect
    item: Item | None
    slot_name: str | None
    category: str  # "equip", "pack", "sell", "drop"


@dataclass
class AbilitySlot:
    rect: pygame.Rect
    ability: str | None
    slot_id: str


@dataclass
class TalentSlot:
    rect: pygame.Rect
    node_id: str
    tier_index: int
    max_rank: int
    column: int


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
        self.screen_size = SCREEN_SIZE
        self.background = BACKGROUND
        self.quest_log: list[str] = []
        self.target_spawned = False
        self.target_defeated = False
        self.zone_prompt: str = ""
        self._apply_zone_settings(context.zones.active_zone)
        self.sprite_library: dict[str, SpriteSheet] = {}
        self.item_sprite_layers: dict[str, SpriteSheet] = {}
        self.player_composite: SpriteSheet | None = None
        self.tilemaps: dict[str, dict] = {}
        self.tile_atlas: dict[str, pygame.Surface] = {}
        self.tile_surface_cache: dict[tuple[str, int], pygame.Surface] = {}
        self.camera_position: Tuple[float, float] = (0.0, 0.0)
        self.actors: Dict[str, Actor] = self._spawn_start_area()
        self.tutorial = TutorialManager()
        self.show_inventory = False
        self.show_menu_panel = False
        self.show_skills_panel = False
        self.show_quests_panel = False
        self.show_stats_panel = False
        self.show_help_overlay = False
        self.loot_banner: str | None = None
        self.loot_banner_timer: float = 0.0
        self.mouse_pos: Tuple[int, int] = (0, 0)
        self.player_motion: Tuple[float, float] = (0.0, 0.0)
        self.pack_slots: list[ItemSlot] = []
        self.equip_slots: list[ItemSlot] = []
        self.action_slots: list[ItemSlot] = []
        self.skill_slots: list[AbilitySlot] = []
        self.hotbar_slots: list[AbilitySlot] = []
        self.talent_slots: list[TalentSlot] = []
        self.pack_canvas_slot: ItemSlot | None = None
        self.inventory_positions: dict[int, Tuple[int, int]] = {}
        self.toolbar_buttons: list[tuple[str, pygame.Rect]] = []
        self.quest_panel_tab: pygame.Rect | None = None
        self.dragging_slot: ItemSlot | None = None
        self.drag_offset: Tuple[int, int] = (0, 0)
        self.dragging_ability: str | None = None
        self.dragging_from_slot: str | None = None
        self.hovered_slot: ItemSlot | None = None
        self.hotbar_assignments: dict[str, str | None] = {f"bottom-{idx}": None for idx in range(6)}
        self.talent_ranks: dict[str, int] = {}
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

    def _initialize_render_assets(self) -> None:
        """Load sprite sheets, tile art, and equipment overlays once Pygame is ready."""

        self.tile_atlas = self._build_tile_atlas()
        self.tilemaps = self._load_zone_tilemaps()
        self.sprite_library = self._build_sprite_library()
        self.item_sprite_layers = self._build_item_layers()
        self._refresh_player_sprite_cache()
        self._assign_actor_sprites()

    def _build_tile_atlas(self) -> dict[str, pygame.Surface]:
        def tile(color: Tuple[int, int, int], accent: Tuple[int, int, int] | None = None) -> pygame.Surface:
            surf = pygame.Surface((40, 40), pygame.SRCALPHA)
            surf.fill(color)
            if accent:
                pygame.draw.rect(surf, accent, pygame.Rect(4, 4, 32, 32), 2, border_radius=6)
            return surf

        atlas: dict[str, pygame.Surface] = {
            "grass": tile((62, 104, 75), (86, 140, 103)),
            "path": tile((124, 95, 70), (150, 121, 96)),
            "flowers": tile((72, 112, 86)),
            "campfire": tile((130, 70, 40), (255, 150, 80)),
            "tent": tile((150, 136, 104), (190, 182, 140)),
            "log": tile((112, 76, 50), (144, 108, 70)),
            "hills": tile((38, 58, 72), (52, 82, 104)),
            "trees": tile((40, 70, 52), (62, 110, 78)),
            "cobble": tile((82, 84, 100), (110, 116, 132)),
            "street": tile((110, 100, 96), (140, 124, 116)),
            "market": tile((94, 71, 64), (175, 130, 90)),
            "crate": tile((124, 92, 66), (164, 130, 104)),
            "banner": tile((82, 24, 54), (162, 64, 94)),
            "well": tile((68, 78, 105), (120, 138, 170)),
            "tree": tile((54, 92, 62), (84, 132, 92)),
            "wall": tile((58, 58, 74), (96, 98, 124)),
            "roofline": tile((86, 52, 58), (150, 92, 102)),
        }
        return atlas

    def _tile_surface(self, name: str, tile_size: int) -> pygame.Surface | None:
        key = (name, tile_size)
        if key in self.tile_surface_cache:
            return self.tile_surface_cache[key]
        base = self.tile_atlas.get(name)
        if not base:
            return None
        if base.get_width() != tile_size or base.get_height() != tile_size:
            base = pygame.transform.smoothscale(base, (tile_size, tile_size))
        self.tile_surface_cache[key] = base
        return base

    def _prepare_tilemap(self, data: dict) -> dict:
        width = int(data.get("width", 0))
        height = int(data.get("height", 0))
        base = data.get("base", "grass")
        grid = [[base for _ in range(width)] for _ in range(height)]

        for override in data.get("overrides", []):
            tile_name = override.get("tile", base)
            rect = override.get("rect", [0, 0, 0, 0])
            ox, oy, ow, oh = rect
            for y in range(oy, oy + oh):
                for x in range(ox, ox + ow):
                    if 0 <= x < width and 0 <= y < height:
                        grid[y][x] = tile_name

        data["ground_grid"] = grid
        return data

    def _load_zone_tilemaps(self) -> dict[str, dict]:
        tilemap_dir = DEFAULT_DATA_PATH / "tilemaps"
        if not tilemap_dir.exists():
            return {}

        loaded: dict[str, dict] = {}
        for path in tilemap_dir.glob("*.json"):
            try:
                with path.open() as handle:
                    data = json.load(handle)
                loaded[path.stem] = self._prepare_tilemap(data)
            except Exception as exc:  # pragma: no cover - defensive asset load
                log_with_fields(logger, logging.WARNING, "Failed to load tilemap", file=str(path), error=str(exc))
        return loaded

    def _draw_character_frame(
        self,
        size: Tuple[int, int],
        body: Sequence[int],
        trim: Sequence[int],
        accent: Sequence[int],
        *,
        direction: str,
        motion_offset: int = 0,
        attack: bool = False,
    ) -> pygame.Surface:
        surf = pygame.Surface(size, pygame.SRCALPHA)
        base_rect = pygame.Rect(18 + motion_offset, 12 + abs(motion_offset), 22, 28)
        if direction == "north":
            base_rect.y += 4
        if direction == "south":
            base_rect.y -= 2
        pygame.draw.rect(surf, body, base_rect, border_radius=6)
        head = pygame.Rect(base_rect.x + 4, base_rect.y - 10, 14, 12)
        pygame.draw.ellipse(surf, body, head)
        pygame.draw.ellipse(surf, trim, head, 2)
        if attack:
            swing_rect = pygame.Rect(base_rect.right - 2, base_rect.y + 8, 12, 8)
            if direction == "west":
                swing_rect.x = base_rect.x - 12
            pygame.draw.rect(surf, accent, swing_rect, border_radius=3)
        else:
            glint = pygame.Rect(base_rect.centerx - 3, base_rect.y + 6, 6, 6)
            pygame.draw.rect(surf, accent, glint, border_radius=2)
        boot = pygame.Rect(base_rect.x, base_rect.bottom - 4, base_rect.width, 6)
        pygame.draw.rect(surf, trim, boot, border_radius=4)
        return surf

    def _sprite_sheet_from_palette(
        self, base: Tuple[int, int, int], trim: Tuple[int, int, int], accent: Tuple[int, int, int]
    ) -> SpriteSheet:
        directions = ["south", "east", "north", "west"]
        states = {state: {} for state in ("idle", "walk", "attack")}
        for direction in directions:
            states["idle"][direction] = [
                self._draw_character_frame((58, 58), base, trim, accent, direction=direction),
                self._draw_character_frame((58, 58), base, trim, accent, direction=direction, motion_offset=1),
            ]
            states["walk"][direction] = [
                self._draw_character_frame((58, 58), base, trim, accent, direction=direction, motion_offset=-2),
                self._draw_character_frame((58, 58), base, trim, accent, direction=direction, motion_offset=2),
                self._draw_character_frame((58, 58), base, trim, accent, direction=direction, motion_offset=-3),
            ]
            states["attack"][direction] = [
                self._draw_character_frame((58, 58), base, trim, accent, direction=direction, attack=True),
                self._draw_character_frame((58, 58), base, trim, accent, direction=direction, motion_offset=3, attack=True),
                self._draw_character_frame((58, 58), base, trim, accent, direction=direction, motion_offset=-3, attack=True),
            ]
        return SpriteSheet(states, pygame.Color(base))

    def _build_sprite_library(self) -> dict[str, SpriteSheet]:
        library = {
            "player_base": self._sprite_sheet_from_palette((214, 193, 119), (132, 168, 196), (237, 245, 255)),
            "guide": self._sprite_sheet_from_palette((214, 185, 110), (144, 104, 52), (255, 234, 180)),
            "ghost": self._sprite_sheet_from_palette((130, 175, 220), (82, 124, 180), (190, 230, 255)),
            "villager": self._sprite_sheet_from_palette((132, 160, 210), (92, 116, 144), (220, 230, 244)),
            "guard": self._sprite_sheet_from_palette((120, 140, 190), (88, 118, 168), (218, 225, 240)),
            "trader": self._sprite_sheet_from_palette((160, 170, 105), (118, 126, 82), (222, 230, 178)),
            "wildling": self._sprite_sheet_from_palette((170, 120, 90), (122, 76, 56), (230, 200, 180)),
            "elemental": self._sprite_sheet_from_palette((90, 200, 180), (40, 140, 120), (200, 245, 230)),
        }
        return library

    def _build_item_layers(self) -> dict[str, SpriteSheet]:
        layer_colors = {
            "bronze_sword": ((200, 140, 90), (255, 215, 160), (255, 245, 220)),
            "oak_shield": ((126, 94, 64), (166, 134, 90), (222, 200, 170)),
            "leather_armor": ((116, 90, 70), (152, 120, 90), (220, 200, 160)),
            "lantern": ((160, 150, 90), (255, 240, 150), (255, 255, 210)),
        }

        def layer_sheet(body: Tuple[int, int, int], trim: Tuple[int, int, int], accent: Tuple[int, int, int]) -> SpriteSheet:
            frames: Dict[str, Dict[str, list[pygame.Surface]]] = {state: {} for state in ("idle", "walk", "attack")}
            for direction in ("south", "east", "north", "west"):
                base = self._draw_character_frame((58, 58), (0, 0, 0, 0), trim, accent, direction=direction)
                armor = self._draw_character_frame(
                    (58, 58), body, trim, accent, direction=direction, motion_offset=1
                )
                swing = self._draw_character_frame(
                    (58, 58), body, trim, accent, direction=direction, motion_offset=2, attack=True
                )
                frames["idle"][direction] = [base]
                frames["walk"][direction] = [base, armor, base]
                frames["attack"][direction] = [armor, swing, armor]
            return SpriteSheet(frames, pygame.Color(body))

        layers = {name: layer_sheet(*colors) for name, colors in layer_colors.items()}
        return layers

    def _refresh_player_sprite_cache(self) -> None:
        base_sheet = self.sprite_library.get("player_base")
        if not base_sheet:
            return

        overlays: list[SpriteSheet] = []
        combatant = self._player_combatant()
        if combatant:
            for item in combatant.equipped.values():
                if item and item.name in self.item_sprite_layers:
                    overlays.append(self.item_sprite_layers[item.name])

        frames: Dict[str, Dict[str, list[pygame.Surface]]] = {}
        for state, directions in base_sheet.frames.items():
            frames[state] = {}
            for direction, base_frames in directions.items():
                composed: list[pygame.Surface] = []
                for idx, frame in enumerate(base_frames):
                    finished = frame.copy()
                    for overlay in overlays:
                        overlay_frames = overlay.frames.get(state, {}).get(direction) or overlay.frames.get("idle", {}).get(
                            direction, []
                        )
                        if overlay_frames:
                            finished.blit(overlay_frames[min(idx, len(overlay_frames) - 1)], (0, 0))
                    composed.append(finished)
                frames[state][direction] = composed
        self.player_composite = SpriteSheet(frames, base_sheet.base_color)

    def _assign_actor_sprites(self) -> None:
        for actor in self.actors.values():
            if actor.name == PLAYER_NAME:
                actor.sprite_sheet = self.player_composite or self.sprite_library.get("player_base")
                actor.minimap_color = (actor.sprite_sheet.base_color if actor.sprite_sheet else pygame.Color("yellow"))
                continue

            key = actor.sprite_name or actor.name
            sprite = self.sprite_library.get(key) or self.sprite_library.get("villager")
            actor.sprite_sheet = sprite
            if sprite:
                actor.minimap_color = sprite.base_color

    def _apply_zone_settings(self, zone: Zone | None) -> None:
        settings = self.context.zones.map_settings()
        size = settings.get("size", SCREEN_SIZE)
        if isinstance(size, tuple) and len(size) == 2:
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
            rect=hero_rect,
            sprite_name="player_base",
            minimap_color=pygame.Color(hero_appearance.color),
        )

        guide_rect = pygame.Rect((0, 0), (54, 54))
        guide_spawn = zone.get_spawn_point("quest_giver", zone_center) if zone else zone_center
        guide_rect.center = guide_spawn
        guide_rect = self._resolve_obstacle_collision(guide_rect, guide_rect, obstacles, zone_rect)
        guide_rect = self._clamp_to_bounds(guide_rect, zone_rect)
        actors[QUEST_GIVER_NAME] = Actor(
            name=QUEST_GIVER_NAME,
            rect=guide_rect,
            speed=0,
            sprite_name="guide",
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

    def _update_camera(self, zone: Zone | None) -> None:
        bounds = self._zone_rect(zone)
        player = self.actors.get(PLAYER_NAME)
        if not bounds or not player:
            self.render_offset = self._zone_render_offset(zone)
            return

        half_w = self.screen_size[0] // 2
        half_h = self.screen_size[1] // 2
        cam_x = player.rect.centerx - half_w
        cam_y = player.rect.centery - half_h
        cam_x = max(bounds.x, min(bounds.x + bounds.width - self.screen_size[0], cam_x))
        cam_y = max(bounds.y, min(bounds.y + bounds.height - self.screen_size[1], cam_y))
        self.camera_position = (cam_x, cam_y)
        self.render_offset = (-cam_x, -cam_y)

    def _zone_obstacles(self, zone: Zone | None) -> list[pygame.Rect]:
        if not zone:
            return []
        tilemap = self.tilemaps.get(zone.name)
        obstacles: list[pygame.Rect] = []
        if tilemap:
            tile_size = int(tilemap.get("tile_size", 40))
            for entry in tilemap.get("collision", []):
                rect = entry.get("rect", [0, 0, 0, 0])
                ox, oy, ow, oh = rect
                obstacles.append(
                    pygame.Rect(
                        zone.bounds.x + ox * tile_size,
                        zone.bounds.y + oy * tile_size,
                        ow * tile_size,
                        oh * tile_size,
                    )
                )

        if not obstacles:
            obstacles = [pygame.Rect((obs.x, obs.y), (obs.width, obs.height)) for obs in zone.obstacles]
        else:
            obstacles.extend([pygame.Rect((obs.x, obs.y), (obs.width, obs.height)) for obs in zone.obstacles])
        return obstacles

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
            guide_rect = pygame.Rect((0, 0), (54, 54))
            guide_spawn = zone.get_spawn_point("quest_giver", bounds.center)
            guide_rect.center = guide_spawn
            resolved = self._resolve_obstacle_collision(player.rect, guide_rect, obstacles, bounds)
            self.actors[QUEST_GIVER_NAME] = Actor(
                name=QUEST_GIVER_NAME,
                rect=resolved,
                speed=0,
                sprite_name="guide",
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

        moving = dx != 0.0 or dy != 0.0
        if moving:
            player.set_facing(dx, dy)

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
        self.player_motion = (dx, dy)

    def _update_actor_animations(self, dt: float) -> None:
        for name, actor in self.actors.items():
            moving = name == PLAYER_NAME and (self.player_motion[0] != 0.0 or self.player_motion[1] != 0.0)
            actor.update_animation(dt, moving=moving)

    def _attempt_attack(self, target_name: str | None = None) -> bool:
        player = self.actors.get(PLAYER_NAME)
        target_label = target_name or self.target_name
        target = self.actors.get(target_label)
        if not player or not target or not player.can_attack():
            return False

        if player.rect.colliderect(target.rect.inflate(8, 8)):
            diff_x = target.rect.centerx - player.rect.centerx
            diff_y = target.rect.centery - player.rect.centery
            player.set_facing(diff_x, diff_y)
            log_with_fields(logger, logging.INFO, "Real-time attack", attacker=player.name, defender=target.name)
            self.bus.publish("combat.attack", attacker=player.name, defender=target.name)
            player.trigger_attack()
            player.play_attack()
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

    def _start_skill_drag(self, pos: Tuple[int, int]) -> bool:
        slot = next((slot for slot in self.skill_slots if slot.rect.collidepoint(pos)), None)
        if slot:
            self.dragging_ability = slot.ability
            self.dragging_from_slot = None
            return True

        move_existing = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
        if move_existing:
            slot = next((slot for slot in self.hotbar_slots if slot.rect.collidepoint(pos) and slot.ability), None)
            if slot:
                self.dragging_ability = slot.ability
                self.dragging_from_slot = slot.slot_id
                return True
        return False

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
        slot_size = self.dragging_slot.rect.width
        if item and slot:
            if slot.category == "equip" and slot.slot_name == item.slot:
                self.context.combat.equip_item(PLAYER_NAME, item.name)
                self._forget_pack_position(item)
            elif slot.category == "pack" and self.dragging_slot.category == "equip":
                if combatant and self.dragging_slot.slot_name:
                    if combatant.equipped.get(self.dragging_slot.slot_name) is item:
                        combatant.equipped.pop(self.dragging_slot.slot_name, None)
                self._place_item_in_pack(item, (slot.rect.x, slot.rect.y), slot_size, 6)
            elif slot.category == "pack":
                self._place_item_in_pack(item, (slot.rect.x, slot.rect.y), slot_size, 6)
            elif slot.category == "pack_canvas":
                target_x = pos[0] - self.drag_offset[0]
                target_y = pos[1] - self.drag_offset[1]
                self._place_item_in_pack(item, (target_x, target_y), slot_size, 6)
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

        if item and slot and slot.category in {"sell", "drop"}:
            self._forget_pack_position(item)
        elif item and not slot and self.pack_canvas_slot and self.pack_canvas_slot.rect.collidepoint(pos):
            target_x = pos[0] - self.drag_offset[0]
            target_y = pos[1] - self.drag_offset[1]
            self._place_item_in_pack(item, (target_x, target_y), slot_size, 6)

        self._refresh_player_sprite_cache()
        self._assign_actor_sprites()

        self.dragging_slot = None

    def _complete_skill_drag(self, pos: Tuple[int, int]) -> None:
        if not self.dragging_ability:
            return

        destination = next((slot for slot in self.hotbar_slots if slot.rect.collidepoint(pos)), None)
        if destination:
            self.hotbar_assignments[destination.slot_id] = self.dragging_ability

        if self.dragging_from_slot and (not destination or destination.slot_id != self.dragging_from_slot):
            self.hotbar_assignments[self.dragging_from_slot] = None

        self.dragging_ability = None
        self.dragging_from_slot = None

    def _handle_hotbar_click(self, pos: Tuple[int, int]) -> bool:
        slot = next((slot for slot in self.hotbar_slots if slot.rect.collidepoint(pos)), None)
        if slot and slot.ability and not self.dragging_ability:
            return self._cast_ability(slot.ability)
        return False

    def _handle_talent_click(self, pos: Tuple[int, int]) -> bool:
        if not self.show_skills_panel:
            return False
        slot = next((slot for slot in self.talent_slots if slot.rect.collidepoint(pos)), None)
        if not slot:
            return False
        combatant = self._player_combatant()
        if not combatant:
            return False
        return self._allocate_talent_node(combatant.class_name, slot.node_id)

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
                rect=target_rect,
                sprite_name="ghost",
                minimap_color=pygame.Color(appearance.color),
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
                    rect=rect,
                    speed=0 if zone.is_static else 180,
                    sprite_name=self._sprite_for_spawn(spawn_name),
                    minimap_color=self._color_for_spawn(spawn_name),
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

    def _sprite_for_spawn(self, spawn: str) -> str:
        mapping = {
            "vendor": "trader",
            "campfire": "elemental",
            "villager": "villager",
            "guard": "guard",
            "trader": "trader",
            "wolf": "wildling",
            "boar": "wildling",
            "bandit": "villager",
            "herb": "elemental",
            "gryphon": "wildling",
            "goat": "villager",
            "ore-node": "elemental",
            "slime": "elemental",
            "mosquito": "elemental",
            "shrub": "elemental",
        }
        return mapping.get(spawn, "villager")

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
        for slot in self.equip_slots + self.pack_slots + ([self.pack_canvas_slot] if self.pack_canvas_slot else []) + self.action_slots:
            if slot.rect.collidepoint(pos):
                return slot
        return None

    def _ability_definitions_for_class(self, class_name: str) -> dict[str, dict]:
        abilities: dict[str, dict] = {}
        for name, definition in self.context.bundle.abilities.definitions().items():
            if definition.get("class_name") == class_name:
                abilities[name] = definition
        return abilities

    def _talent_tree_for_class(self, class_name: str) -> dict | None:
        trees = self.context.bundle.talents.definitions() if hasattr(self.context.bundle, "talents") else {}
        for entry in trees.values():
            if entry.get("class_name") == class_name:
                return entry
        return None

    def _talent_points_spent(self, class_name: str) -> int:
        tree = self._talent_tree_for_class(class_name)
        if not tree:
            return 0
        node_ids = [node.get("id") for tier in tree.get("tiers", []) for node in tier.get("nodes", [])]
        return sum(self.talent_ranks.get(node_id, 0) for node_id in node_ids if node_id)

    def _talent_budget(self, class_name: str) -> int:
        tree = self._talent_tree_for_class(class_name)
        return int(tree.get("total_points", 0)) if tree else 0

    def _talent_prereqs_met(self, node: dict) -> bool:
        return all(self.talent_ranks.get(req, 0) > 0 for req in node.get("requires", []))

    def _allocate_talent_node(self, class_name: str, node_id: str) -> bool:
        tree = self._talent_tree_for_class(class_name)
        combatant = self._player_combatant()
        if not tree or not combatant:
            return False

        budget = self._talent_budget(class_name)
        spent = self._talent_points_spent(class_name)
        if spent >= budget:
            return False

        selected = None
        tier_requirement = 0
        for idx, tier in enumerate(tree.get("tiers", [])):
            tier_nodes = tier.get("nodes", [])
            for node in tier_nodes:
                if node.get("id") == node_id:
                    selected = node
                    tier_requirement = int(tier.get("min_points", 0))
                    break
            if selected:
                break

        if not selected:
            return False

        current_rank = self.talent_ranks.get(node_id, 0)
        max_rank = int(selected.get("max_rank", 1))
        if current_rank >= max_rank:
            return False
        if spent < tier_requirement:
            return False
        if not self._talent_prereqs_met(selected):
            return False

        self.talent_ranks[node_id] = current_rank + 1
        grants = selected.get("grants_ability", [])
        if grants:
            ability_names = ", ".join(grants)
            self.quest_log.append(f"Learned talent {selected.get('name', node_id)} (rank {self.talent_ranks[node_id]}). Added: {ability_names}.")
        else:
            self.quest_log.append(f"Learned talent {selected.get('name', node_id)} (rank {self.talent_ranks[node_id]}).")
        return True

    def _ability_state(self, combatant, ability_name: str) -> tuple[dict | None, dict]:
        definitions = self.context.bundle.abilities.definitions()
        definition = definitions.get(ability_name)
        state = {
            "cooldown": combatant.cooldowns.get(ability_name, 0) if combatant else 0,
            "gcd": combatant.gcd_remaining if combatant else 0,
            "resource_missing": False,
            "ready": False,
            "resource": 0,
        }
        if not combatant or not definition:
            return definition, state

        resource_type = definition.get("resource_type") or "mana"
        cost = int(definition.get("cost") or 0)
        current = combatant.resource(resource_type)
        state["resource"] = current
        state["resource_missing"] = current < cost
        state["ready"] = state["cooldown"] <= 0 and state["gcd"] <= 0 and not state["resource_missing"]
        return definition, state

    def _current_target(self) -> str | None:
        if self.target_name in self.actors and self.target_name != PLAYER_NAME:
            return self.target_name
        for name in self.actors:
            if name not in {PLAYER_NAME, QUEST_GIVER_NAME}:
                return name
        return None

    def _cast_ability(self, ability_name: str) -> bool:
        combatant = self._player_combatant()
        if not combatant:
            return False

        definition, state = self._ability_state(combatant, ability_name)
        if not definition or not state.get("ready"):
            return False

        target = self._current_target()
        if not target:
            return False

        try:
            self.bus.publish("ability.cast", attacker=PLAYER_NAME, defender=target, ability=ability_name)
            actor = self.actors.get(PLAYER_NAME)
            if actor:
                actor.trigger_attack()
            self.tutorial.record_attack()
            return True
        except Exception as exc:  # pragma: no cover - defensive cast guard
            log_with_fields(logger, logging.WARNING, "Ability cast failed", ability=ability_name, error=str(exc))
        return False

    def _forget_pack_position(self, item: Item) -> None:
        self.inventory_positions.pop(id(item), None)

    def _place_item_in_pack(self, item: Item, pos: Tuple[int, int], slot_size: int, padding: int) -> None:
        if not self.pack_canvas_slot:
            return
        canvas = self.pack_canvas_slot.rect
        clamped_x = max(canvas.x + padding, min(canvas.right - slot_size - padding, pos[0]))
        clamped_y = max(canvas.y + padding, min(canvas.bottom - slot_size - padding, pos[1]))
        self.inventory_positions[id(item)] = (clamped_x, clamped_y)

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

    def _item_scaled_stats(self, item: Item, *, scale: float | None = None) -> Tuple[int, int, int]:
        if scale is None:
            return self.context.combat._effective_item_stats(item)

        factor = max(0.25, min(1.0, scale)) if item.max_durability else 1.0
        return int(item.power * factor), int(item.defense * factor), int(item.speed * factor)

    def _combat_projection(self, combatant: Combatant, scale_fn: Callable[[Item], Tuple[int, int, int]]) -> dict[str, int]:
        set_bonus = self.context.combat._set_bonus(combatant)
        buffs = self.context.combat._buff_totals(combatant)

        base_power = 1 + combatant.strength
        base_speed = combatant.agility // 2
        base_defense = combatant.mastery + combatant.agility // 3 + combatant.strength // 4

        gear_power = gear_speed = gear_defense = 0
        for item in combatant.equipped.values():
            power, defense, speed = scale_fn(item)
            gear_power += power
            gear_defense += defense
            gear_speed += speed

        attack_power = max(1, base_power + base_speed + gear_power + gear_speed + set_bonus["power"] + set_bonus["speed"] + buffs.power + buffs.speed)
        total_defense = base_defense + gear_defense + set_bonus["defense"] + buffs.defense

        return {
            "attack_power": attack_power,
            "defense": total_defense,
            "gear_defense": gear_defense,
            "gear_power": gear_power,
            "gear_speed": gear_speed,
            "base_defense": base_defense,
        }

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

        panel_width = 780
        panel_height = 440
        margin = 16
        padding = 16
        section_gap = 14
        panel_rect = pygame.Rect(self.screen_size[0] - panel_width - margin, margin, panel_width, panel_height)
        pygame.draw.rect(screen, (28, 32, 42), panel_rect, border_radius=12)
        pygame.draw.rect(screen, (90, 110, 130), panel_rect, 2, border_radius=12)

        self.pack_slots = []
        self.equip_slots = []
        self.action_slots = []
        self.pack_canvas_slot = None

        title = self.font.render("Inventory (I) — drag to equip, move, sell, or drop", True, (225, 232, 238))
        screen.blit(title, (panel_rect.x + padding, panel_rect.y + padding - 4))

        info_rect = pygame.Rect(
            panel_rect.x + padding,
            panel_rect.y + 34,
            panel_rect.width - padding * 2,
            76,
        )
        pygame.draw.rect(screen, (22, 26, 34), info_rect, border_radius=10)
        pygame.draw.rect(screen, (78, 96, 118), info_rect, 1, border_radius=10)

        gold_amount = self.context.economy.wallets.get(PLAYER_NAME, combatant.gold)
        gold_text = self.font.render(f"Gold: {gold_amount}", True, (240, 210, 140))
        stats_line = self.font.render(
            f"STR {combatant.strength} | AGI {combatant.agility} | MAS {combatant.mastery}",
            True,
            (205, 214, 228),
        )
        skills = ", ".join(f"{name.replace('_', ' ').title()} {rank}" for name, rank in combatant.skills.items())
        skills_line = self.font.render(f"Skills: {skills or 'None learned yet'}", True, (182, 194, 210))
        screen.blit(gold_text, (info_rect.x + 12, info_rect.y + 10))
        screen.blit(stats_line, (info_rect.x + 12, info_rect.y + 30))
        screen.blit(skills_line, (info_rect.x + 12, info_rect.y + 50))

        slot_size = 72
        spacing = 12
        gear_rect = pygame.Rect(panel_rect.x + padding, info_rect.bottom + section_gap, 262, panel_height - info_rect.height - section_gap * 2 - 88)
        pygame.draw.rect(screen, (24, 28, 36), gear_rect, border_radius=10)
        pygame.draw.rect(screen, (80, 96, 116), gear_rect, 1, border_radius=10)
        gear_title = self.font.render("Gear Slots", True, (200, 210, 224))
        screen.blit(gear_title, (gear_rect.x + 12, gear_rect.y + 10))

        paper_rect = pygame.Rect(gear_rect.x + 10, gear_rect.y + 34, gear_rect.width - 20, gear_rect.height - 44)
        pygame.draw.rect(screen, (30, 34, 44), paper_rect, border_radius=10)
        pygame.draw.rect(screen, (90, 106, 128), paper_rect, 1, border_radius=10)
        silhouette = self.font.render("Paper Doll", True, (130, 140, 152))
        screen.blit(silhouette, (paper_rect.centerx - silhouette.get_width() // 2, paper_rect.y + 10))

        center_x = paper_rect.centerx - slot_size // 2
        equip_positions = {
            "helm": (center_x, paper_rect.y + 36),
            "armor": (center_x, paper_rect.y + 126),
            "back": (center_x, paper_rect.y + 216),
            "mainhand": (paper_rect.x + 18, paper_rect.y + 126),
            "offhand": (paper_rect.right - slot_size - 18, paper_rect.y + 126),
        }

        dragging_item = self.dragging_slot.item if self.dragging_slot else None
        for slot_name, pos in equip_positions.items():
            rect = pygame.Rect(pos[0], pos[1], slot_size, slot_size)
            item = combatant.equipped.get(slot_name)
            highlight = rect.collidepoint(self.mouse_pos)
            pygame.draw.rect(screen, (36, 42, 54), rect, border_radius=8)
            pygame.draw.rect(screen, (110, 124, 140), rect, 1, border_radius=8)
            label = self.font.render(slot_name.title(), True, (140, 152, 165))
            screen.blit(label, (rect.centerx - label.get_width() // 2, rect.bottom + 4))
            self.equip_slots.append(ItemSlot(rect, item, slot_name, "equip"))
            if item and item is not dragging_item:
                self._draw_item_icon(screen, item, rect, highlight=highlight)
            elif not item:
                empty = self.font.render("Empty", True, (98, 108, 122))
                screen.blit(empty, (rect.centerx - empty.get_width() // 2, rect.centery - 10))

        pack_rect = pygame.Rect(
            gear_rect.right + section_gap,
            info_rect.bottom + section_gap,
            panel_rect.right - padding - (gear_rect.right + section_gap),
            gear_rect.height,
        )
        pygame.draw.rect(screen, (22, 26, 34), pack_rect, border_radius=10)
        pygame.draw.rect(screen, (78, 96, 118), pack_rect, 1, border_radius=10)
        pack_title = self.font.render("Pack Canvas", True, (200, 210, 224))
        screen.blit(pack_title, (pack_rect.x + 12, pack_rect.y + 10))
        capacity_note = self.font.render(
            f"Pack {len([it for it in combatant.inventory if it not in combatant.equipped.values()])}/{combatant.capacity()} (Shift to compare)",
            True,
            (190, 200, 210),
        )
        screen.blit(capacity_note, (pack_rect.x + 12, pack_rect.y + 32))

        canvas_padding = 16
        canvas_rect = pygame.Rect(
            pack_rect.x + canvas_padding,
            pack_rect.y + 52,
            pack_rect.width - canvas_padding * 2,
            pack_rect.height - canvas_padding * 2 - 28,
        )
        pygame.draw.rect(screen, (26, 30, 38), canvas_rect, border_radius=10)
        pygame.draw.rect(screen, (70, 86, 104), canvas_rect, 1, border_radius=10)
        self.pack_canvas_slot = ItemSlot(canvas_rect, None, None, "pack_canvas")

        pack_items = [item for item in combatant.inventory if item not in combatant.equipped.values()]
        cols = max(1, canvas_rect.width // (slot_size + spacing))
        for idx, item in enumerate(pack_items):
            pos = self.inventory_positions.get(id(item))
            if not pos:
                row = idx // cols
                col = idx % cols
                pos = (
                    canvas_rect.x + canvas_padding + col * (slot_size + spacing),
                    canvas_rect.y + canvas_padding + row * (slot_size + spacing),
                )
                self._place_item_in_pack(item, pos, slot_size, 4)
            x, y = self.inventory_positions.get(id(item), pos)
            rect = pygame.Rect(x, y, slot_size, slot_size)
            rect.x = max(canvas_rect.x + 6, min(canvas_rect.right - slot_size - 6, rect.x))
            rect.y = max(canvas_rect.y + 6, min(canvas_rect.bottom - slot_size - 6, rect.y))
            highlight = rect.collidepoint(self.mouse_pos)
            pygame.draw.rect(screen, (32, 36, 44), rect, border_radius=8)
            pygame.draw.rect(screen, (70, 78, 92), rect, 1, border_radius=8)
            slot = ItemSlot(rect, item, None, "pack")
            self.pack_slots.append(slot)
            if item and item is not dragging_item:
                self._draw_item_icon(screen, item, rect, highlight=highlight)

        actions_rect = pygame.Rect(panel_rect.x + padding, panel_rect.bottom - 74, panel_rect.width - padding * 2, 58)
        pygame.draw.rect(screen, (30, 36, 46), actions_rect, border_radius=10)
        pygame.draw.rect(screen, (110, 130, 150), actions_rect, 1, border_radius=10)

        sell_rect = pygame.Rect(actions_rect.x + 14, actions_rect.y + 8, 160, 42)
        drop_rect = pygame.Rect(sell_rect.right + 18, actions_rect.y + 8, 160, 42)
        action_style = pygame.Color(64, 78, 92)
        pygame.draw.rect(screen, action_style, sell_rect, border_radius=8)
        pygame.draw.rect(screen, (150, 180, 205), sell_rect, 2, border_radius=8)
        sell_label = self.font.render("Sell to Camp", True, (215, 225, 235))
        screen.blit(sell_label, (sell_rect.x + 14, sell_rect.y + 12))
        pygame.draw.rect(screen, action_style, drop_rect, border_radius=8)
        pygame.draw.rect(screen, (200, 150, 150), drop_rect, 2, border_radius=8)
        drop_label = self.font.render("Drop on Ground", True, (235, 225, 225))
        screen.blit(drop_label, (drop_rect.x + 12, drop_rect.y + 12))
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

    def _render_stats_panel(self, screen: pygame.Surface, bar_height: int) -> None:
        if not self.show_stats_panel or not self.font:
            return

        combatant = self._player_combatant()
        if not combatant:
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

        panel_width = 540
        panel_height = 480
        margin = 16
        padding = 16
        section_gap = 14
        panel_rect = pygame.Rect(margin, margin, panel_width, panel_height)
        pygame.draw.rect(screen, (28, 32, 42), panel_rect, border_radius=12)
        pygame.draw.rect(screen, (90, 110, 130), panel_rect, 2, border_radius=12)

        title = self.font.render("Character (C) — stats & gear", True, (225, 232, 238))
        screen.blit(title, (panel_rect.x + padding, panel_rect.y + padding - 4))

        current_snapshot = self._combat_projection(combatant, lambda item: self._item_scaled_stats(item))
        min_snapshot = self._combat_projection(combatant, lambda item: self._item_scaled_stats(item, scale=0.25))
        max_snapshot = self._combat_projection(combatant, lambda item: self._item_scaled_stats(item, scale=1.0))

        y_cursor = panel_rect.y + padding + 20

        core_rect = pygame.Rect(panel_rect.x + padding, y_cursor, panel_rect.width - padding * 2, 82)
        pygame.draw.rect(screen, (22, 26, 34), core_rect, border_radius=10)
        pygame.draw.rect(screen, (78, 96, 118), core_rect, 1, border_radius=10)
        core_title = self.font.render("Core Attributes", True, (200, 210, 224))
        screen.blit(core_title, (core_rect.x + 12, core_rect.y + 8))

        labels = [
            ("Strength", combatant.strength),
            ("Wisdom", combatant.mastery),
            ("Agility", combatant.agility),
        ]
        column_width = (core_rect.width - 20) // len(labels)
        for idx, (label, value) in enumerate(labels):
            x = core_rect.x + 12 + idx * column_width
            label_text = self.font.render(label, True, (180, 190, 205))
            value_text = self.font.render(str(value), True, (235, 240, 245))
            screen.blit(label_text, (x, core_rect.y + 34))
            screen.blit(value_text, (x, core_rect.y + 54))

        y_cursor = core_rect.bottom + section_gap

        resource_rect = pygame.Rect(panel_rect.x + padding, y_cursor, panel_rect.width - padding * 2, 72)
        pygame.draw.rect(screen, (22, 26, 34), resource_rect, border_radius=10)
        pygame.draw.rect(screen, (78, 96, 118), resource_rect, 1, border_radius=10)
        resource_title = self.font.render("Resource Pools", True, (200, 210, 224))
        screen.blit(resource_title, (resource_rect.x + 12, resource_rect.y + 8))

        resource_lines = [
            f"Health {combatant.hit_points}/{max_health}",
            f"{resource_type.title()} {combatant.resource(resource_type)}/{max_resource}",
        ]
        extras = [f"{key.title()} {value}" for key, value in combatant.resource_pools.items() if key != resource_type]
        if extras:
            resource_lines.append(" • ".join(extras))

        for idx, text in enumerate(resource_lines):
            line = self.font.render(text, True, (205, 214, 228))
            screen.blit(line, (resource_rect.x + 12, resource_rect.y + 30 + idx * 20))

        y_cursor = resource_rect.bottom + section_gap

        derived_rect = pygame.Rect(panel_rect.x + padding, y_cursor, panel_rect.width - padding * 2, 118)
        pygame.draw.rect(screen, (22, 26, 34), derived_rect, border_radius=10)
        pygame.draw.rect(screen, (78, 96, 118), derived_rect, 1, border_radius=10)
        derived_title = self.font.render("Derived Stats", True, (200, 210, 224))
        screen.blit(derived_title, (derived_rect.x + 12, derived_rect.y + 8))

        damage_range = f"Damage Power: {current_snapshot['attack_power']} (range {min_snapshot['attack_power']}–{max_snapshot['attack_power']})"
        armor_line = f"Armor from gear: {current_snapshot['gear_defense']} (base {current_snapshot['base_defense']})"
        mitigation_line = f"Total mitigation: {current_snapshot['defense']}"
        speed_line = f"Weapon speed bonus: +{current_snapshot['gear_speed']}"

        derived_lines = [damage_range, armor_line, mitigation_line, speed_line]
        for idx, text in enumerate(derived_lines):
            line = self.font.render(text, True, (205, 214, 228))
            screen.blit(line, (derived_rect.x + 12, derived_rect.y + 32 + idx * 20))

        y_cursor = derived_rect.bottom + section_gap

        gear_rect = pygame.Rect(panel_rect.x + padding, y_cursor, panel_rect.width - padding * 2, panel_rect.bottom - padding - y_cursor)
        pygame.draw.rect(screen, (22, 26, 34), gear_rect, border_radius=10)
        pygame.draw.rect(screen, (78, 96, 118), gear_rect, 1, border_radius=10)
        gear_title = self.font.render("Gear Contributions", True, (200, 210, 224))
        screen.blit(gear_title, (gear_rect.x + 12, gear_rect.y + 8))

        columns = ["Slot", "Item", "P", "D", "S"]
        col_widths = [90, gear_rect.width - 90 - 120, 32, 32, 32]
        x_positions = [gear_rect.x + 12]
        for width in col_widths[:-1]:
            x_positions.append(x_positions[-1] + width)
        for label, x in zip(columns, x_positions):
            header = self.font.render(label, True, (170, 180, 192))
            screen.blit(header, (x, gear_rect.y + 34))

        slot_order = ["helm", "armor", "back", "mainhand", "offhand"]
        entries: list[tuple[str, Item | None]] = []
        for slot in slot_order:
            entries.append((slot, combatant.equipped.get(slot)))
        for slot, item in combatant.equipped.items():
            if slot not in slot_order:
                entries.append((slot, item))

        line_height = self.font.get_height() + 6
        start_y = gear_rect.y + 56
        for idx, (slot, item) in enumerate(entries):
            power = defense = speed = 0
            name = "Empty"
            if item:
                power, defense, speed = self._item_scaled_stats(item)
                name = item.name.replace("_", " ").title()
            row_y = start_y + idx * line_height
            values = [slot.title(), name, str(power), str(defense), str(speed)]
            for value, x in zip(values, x_positions):
                color = (205, 214, 228) if item else (150, 160, 174)
                text = self.font.render(value, True, color)
                screen.blit(text, (x, row_y))

        totals_label = self.font.render(
            f"Totals — Power {current_snapshot['gear_power']} • Armor {current_snapshot['gear_defense']} • Speed {current_snapshot['gear_speed']}",
            True,
            (190, 200, 214),
        )
        screen.blit(totals_label, (gear_rect.x + 12, gear_rect.bottom - totals_label.get_height() - 6))

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

    def _render_combat_overlay(self, screen: pygame.Surface, bar_height: int) -> None:
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

        bar_height = max(68, bar_height)
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

        slot_size = 66
        spacing = 10
        bottom_slots = 6
        side_slots = 4
        self.hotbar_slots = []

        total_bottom_width = bottom_slots * slot_size + (bottom_slots - 1) * spacing
        bottom_y = self.screen_size[1] - bar_height - slot_size - margin
        start_x = max(margin, (self.screen_size[0] - total_bottom_width) // 2)

        def draw_slot(slot: AbilitySlot, *, key_hint: str | None = None) -> None:
            label = slot.ability.replace("_", " ").title() if slot.ability else "Empty"
            highlight = slot.rect.collidepoint(self.mouse_pos)
            drop_target = bool(self.dragging_ability and slot.rect.collidepoint(self.mouse_pos))
            base = pygame.Color(28, 32, 42)
            accent_value = 230 if drop_target else 200
            accent = pygame.Color(120, 170, accent_value)
            if drop_target:
                accent = pygame.Color(160, 210, 235)
            pygame.draw.rect(screen, base, slot.rect, border_radius=8)
            pygame.draw.rect(screen, accent, slot.rect, 2, border_radius=8)

            if slot.ability:
                definition, state = self._ability_state(combatant, slot.ability)
                name_text = self.font.render(label, True, (215, 225, 235))
                screen.blit(name_text, (slot.rect.x + 8, slot.rect.y + 6))

                cost = definition.get("cost", 0) if definition else 0
                resource_type = (definition or {}).get("resource_type", "mana")
                detail = self.font.render(f"{resource_type.title()} {cost}", True, (170, 185, 198))
                screen.blit(detail, (slot.rect.x + 8, slot.rect.bottom - detail.get_height() - 8))

                overlay = None
                overlay_text = None
                if state["cooldown"] > 0:
                    overlay_text = f"CD {state['cooldown']}"
                    overlay = pygame.Color(15, 18, 26, 170)
                elif state["gcd"] > 0:
                    overlay_text = "GCD"
                    overlay = pygame.Color(40, 60, 90, 150)
                elif state["resource_missing"]:
                    overlay_text = "Low"
                    overlay = pygame.Color(120, 60, 60, 150)

                if overlay:
                    veil = pygame.Surface((slot.rect.width, slot.rect.height), pygame.SRCALPHA)
                    veil.fill(overlay)
                    screen.blit(veil, slot.rect)
                if overlay_text:
                    text = self.font.render(overlay_text, True, (235, 240, 245))
                    screen.blit(
                        text,
                        (
                            slot.rect.centerx - text.get_width() // 2,
                            slot.rect.centery - text.get_height() // 2,
                        ),
                    )
            else:
                prompt = self.font.render("Drop Skill", True, (120, 135, 150))
                screen.blit(
                    prompt,
                    (
                        slot.rect.centerx - prompt.get_width() // 2,
                        slot.rect.centery - prompt.get_height() // 2,
                    ),
                )

            if key_hint:
                hint = self.font.render(key_hint, True, (145, 165, 190) if highlight else (100, 115, 132))
                screen.blit(hint, (slot.rect.x + slot.rect.width - hint.get_width() - 6, slot.rect.y + 6))

        for idx in range(bottom_slots):
            rect = pygame.Rect(start_x + idx * (slot_size + spacing), bottom_y, slot_size, slot_size)
            slot_id = f"bottom-{idx}"
            ability_name = self.hotbar_assignments.get(slot_id)
            self.hotbar_assignments.setdefault(slot_id, ability_name)
            slot = AbilitySlot(rect, ability_name, slot_id)
            self.hotbar_slots.append(slot)
            draw_slot(slot, key_hint=str(idx + 1))

        side_x = self.screen_size[0] - margin - slot_size
        side_start_y = max(margin, bottom_y - (slot_size + spacing) * side_slots)
        for idx in range(side_slots):
            rect = pygame.Rect(side_x, side_start_y + idx * (slot_size + spacing), slot_size, slot_size)
            slot_id = f"side-{idx}"
            ability_name = self.hotbar_assignments.get(slot_id)
            self.hotbar_assignments.setdefault(slot_id, ability_name)
            slot = AbilitySlot(rect, ability_name, slot_id)
            self.hotbar_slots.append(slot)
            draw_slot(slot, key_hint=f"F{idx + 1}")

        if self.dragging_ability:
            ghost_rect = pygame.Rect(self.mouse_pos[0] - slot_size // 2, self.mouse_pos[1] - slot_size // 2, slot_size, slot_size)
            pygame.draw.rect(screen, (30, 36, 46, 220), ghost_rect, border_radius=8)
            pygame.draw.rect(screen, (150, 200, 230), ghost_rect, 2, border_radius=8)
            ghost_label = self.font.render(self.dragging_ability.replace("_", " ").title(), True, (225, 235, 245))
            screen.blit(
                ghost_label,
                (
                    ghost_rect.centerx - ghost_label.get_width() // 2,
                    ghost_rect.centery - ghost_label.get_height() // 2,
                ),
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
        self.skill_slots = []
        self.talent_slots = []
        if not self.show_skills_panel or not self.font:
            return

        combatant = self._player_combatant()
        if not combatant:
            return

        margin = 12
        gap = 10
        panel_width = min(self.screen_size[0] - margin * 2, 700)
        panel_height = 360
        panel_rect = pygame.Rect(
            margin,
            self.screen_size[1] - bar_height - panel_height - margin,
            panel_width,
            panel_height,
        )
        pygame.draw.rect(screen, (26, 30, 38), panel_rect, border_radius=10)
        pygame.draw.rect(screen, (90, 110, 130), panel_rect, 2, border_radius=10)
        header = self.font.render("Skill Sheet — drag to hotbar • Spend talent points", True, (215, 225, 235))
        screen.blit(header, (panel_rect.x + 12, panel_rect.y + 10))

        left_width = 300
        right_width = panel_rect.width - left_width - gap * 2
        abilities_rect = pygame.Rect(panel_rect.x + gap, panel_rect.y + 36, left_width - gap, panel_rect.height - 48)
        pygame.draw.rect(screen, (22, 26, 34), abilities_rect, border_radius=8)
        pygame.draw.rect(screen, (78, 98, 122), abilities_rect, 1, border_radius=8)

        abilities = self._ability_definitions_for_class(combatant.class_name)
        y_cursor = abilities_rect.y + gap
        padding = 8
        card_height = 64
        if abilities:
            for ability_name, definition in sorted(abilities.items()):
                card_rect = pygame.Rect(abilities_rect.x + 6, y_cursor, abilities_rect.width - 12, card_height)
                highlight = card_rect.collidepoint(self.mouse_pos) or (
                    self.dragging_ability == ability_name
                )
                pygame.draw.rect(screen, (30, 36, 46), card_rect, border_radius=10)
                pygame.draw.rect(screen, (140, 170, 200) if highlight else (90, 110, 130), card_rect, 1, border_radius=10)

                slot = AbilitySlot(card_rect, ability_name, f"sheet-{ability_name}")
                self.skill_slots.append(slot)

                title = self.font.render(ability_name.replace("_", " ").title(), True, (215, 225, 235))
                screen.blit(title, (card_rect.x + padding, card_rect.y + padding))

                description = definition.get("description", "")
                desc_text = self.font.render(description, True, (185, 195, 206))
                screen.blit(desc_text, (card_rect.x + padding, card_rect.y + padding + 18))

                rank = combatant.skills.get(ability_name, 0)
                cooldown = definition.get("cooldown_turns", 0)
                cost = definition.get("cost", 0)
                resource_type = definition.get("resource_type", "mana").title()
                detail = self.font.render(
                    f"Rank {rank} • {resource_type} {cost} • Cooldown {cooldown}",
                    True,
                    (170, 185, 198),
                )
                screen.blit(detail, (card_rect.x + padding, card_rect.bottom - padding - detail.get_height()))

                _, state = self._ability_state(combatant, ability_name)
                if any((state["cooldown"], state["gcd"], state["resource_missing"])):
                    overlay = pygame.Surface((card_rect.width, card_rect.height), pygame.SRCALPHA)
                    overlay.fill((10, 14, 20, 140))
                    screen.blit(overlay, card_rect)
                    label = "Cooldown" if state["cooldown"] else "GCD" if state["gcd"] else "Resource"
                    flag = self.font.render(label, True, (230, 235, 240))
                    screen.blit(
                        flag,
                        (
                            card_rect.centerx - flag.get_width() // 2,
                            card_rect.centery - flag.get_height() // 2,
                        ),
                    )

                y_cursor += card_height + gap
                if y_cursor + card_height > abilities_rect.bottom - padding:
                    break
        else:
            note = self.font.render("No class abilities yet.", True, (170, 180, 190))
            screen.blit(note, (abilities_rect.x + 12, y_cursor))

        tree = self._talent_tree_for_class(combatant.class_name)
        tree_rect = pygame.Rect(
            abilities_rect.right + gap,
            panel_rect.y + 36,
            right_width,
            panel_rect.height - 48,
        )
        pygame.draw.rect(screen, (22, 26, 34), tree_rect, border_radius=8)
        pygame.draw.rect(screen, (78, 98, 122), tree_rect, 1, border_radius=8)

        if tree:
            budget = self._talent_budget(combatant.class_name)
            spent = self._talent_points_spent(combatant.class_name)
            available = max(0, budget - spent)
            summary = self.font.render(
                f"Talent Tree — {tree.get('description', '')}", True, (210, 220, 235)
            )
            screen.blit(summary, (tree_rect.x + 10, tree_rect.y + 8))

            status = self.font.render(
                f"Spent {spent}/{budget} • Available {available}", True, (170, 185, 198)
            )
            screen.blit(status, (tree_rect.x + 10, tree_rect.y + 28))

            tier_height = 98
            node_width = (tree_rect.width - gap * 4) // 3
            for tier_index, tier in enumerate(tree.get("tiers", [])):
                tier_y = tree_rect.y + 50 + tier_index * (tier_height + gap)
                tier_rect = pygame.Rect(tree_rect.x + 8, tier_y, tree_rect.width - 16, tier_height)
                pygame.draw.rect(screen, (18, 22, 30), tier_rect, border_radius=8)
                pygame.draw.rect(screen, (70, 90, 110), tier_rect, 1, border_radius=8)

                tier_label = self.font.render(
                    f"{tier.get('name', 'Tier')} • Requires {tier.get('min_points', 0)} points", True, (185, 195, 206)
                )
                screen.blit(tier_label, (tier_rect.x + 8, tier_rect.y + 6))

                for node in tier.get("nodes", []):
                    column = int(node.get("column", 0))
                    node_x = tier_rect.x + gap + column * (node_width + gap)
                    node_rect = pygame.Rect(node_x, tier_rect.y + 26, node_width, tier_height - 34)
                    node_id = node.get("id", "")
                    rank = self.talent_ranks.get(node_id, 0)
                    max_rank = int(node.get("max_rank", 1))
                    unlocked = spent >= int(tier.get("min_points", 0)) and self._talent_prereqs_met(node)
                    has_points = available > 0 and rank < max_rank
                    hover = node_rect.collidepoint(self.mouse_pos)

                    base = pygame.Color(30, 38, 48)
                    accent = pygame.Color(120, 150, 190) if unlocked else pygame.Color(80, 90, 105)
                    if hover and unlocked:
                        accent = pygame.Color(150, 190, 230)
                    pygame.draw.rect(screen, base, node_rect, border_radius=10)
                    pygame.draw.rect(screen, accent, node_rect, 2, border_radius=10)

                    title = self.font.render(node.get("name", node_id).title(), True, (215, 225, 235))
                    screen.blit(title, (node_rect.x + 8, node_rect.y + 6))

                    description = node.get("description", "")
                    desc_text = self.font.render(description, True, (180, 192, 206))
                    screen.blit(desc_text, (node_rect.x + 8, node_rect.y + 26))

                    rank_text = self.font.render(f"Rank {rank}/{max_rank}", True, (170, 185, 198))
                    screen.blit(rank_text, (node_rect.x + 8, node_rect.bottom - rank_text.get_height() - 8))

                    if not unlocked:
                        overlay = pygame.Surface((node_rect.width, node_rect.height), pygame.SRCALPHA)
                        overlay.fill((8, 10, 14, 160))
                        screen.blit(overlay, node_rect)
                        reason = "Spend points" if spent < int(tier.get("min_points", 0)) else "Need prereq"
                        lock_text = self.font.render(reason, True, (220, 225, 235))
                        screen.blit(lock_text, (node_rect.centerx - lock_text.get_width() // 2, node_rect.centery - lock_text.get_height() // 2))
                    elif rank >= max_rank:
                        overlay = pygame.Surface((node_rect.width, node_rect.height), pygame.SRCALPHA)
                        overlay.fill((10, 14, 20, 120))
                        screen.blit(overlay, node_rect)
                        maxed = self.font.render("Maxed", True, (230, 235, 240))
                        screen.blit(maxed, (node_rect.centerx - maxed.get_width() // 2, node_rect.centery - maxed.get_height() // 2))
                    elif has_points and hover:
                        prompt = self.font.render("Click to spend", True, (230, 235, 240))
                        screen.blit(prompt, (node_rect.centerx - prompt.get_width() // 2, node_rect.centery - prompt.get_height() // 2))

                    self.talent_slots.append(TalentSlot(node_rect, node_id, tier_index, max_rank, column))
        else:
            note = self.font.render("No talent tree defined for this class yet.", True, (170, 180, 190))
            screen.blit(note, (tree_rect.x + 12, tree_rect.y + 10))

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
            ("stats", "C", self.show_stats_panel),
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
                elif name == "stats":
                    self.show_stats_panel = not self.show_stats_panel
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
        self._update_camera(zone)
        if zone:
            self._render_zone(screen, zone)
            self._render_minimap(screen, zone)

        draw_order = sorted(self.actors.values(), key=lambda actor: actor.rect.bottom)
        for actor in draw_order:
            frame = actor.current_frame()
            position = self._screen_point(actor.rect.topleft)
            if frame:
                shadow = pygame.Surface((actor.rect.width, max(6, actor.rect.height // 6)), pygame.SRCALPHA)
                shadow.fill((0, 0, 0, 80))
                shadow_rect = shadow.get_rect()
                shadow_rect.center = (position[0] + actor.rect.width // 2, position[1] + actor.rect.height - 4)
                screen.blit(shadow, shadow_rect)
                screen.blit(frame, position)
            else:
                pygame.draw.rect(screen, actor.minimap_color, self._screen_rect(actor.rect), border_radius=6)

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
        self._render_stats_panel(screen, bar_height)
        self._render_inventory_panel(screen)
        self._render_combat_overlay(screen, bar_height)
        self._render_help_overlay(screen)
        self._render_interaction_hint(screen, margin=margin, bar_height=bar_height)
        self._render_toolbar(screen, bar_height)

        pygame.display.flip()

    def _render_zone(self, screen: pygame.Surface, zone: Zone) -> None:
        bounds = self._zone_rect(zone)
        if not bounds:
            return
        tilemap = self.tilemaps.get(zone.name)
        if tilemap:
            self._render_parallax_layers(screen, tilemap)
            self._render_tile_layers(screen, tilemap, zone)
        else:
            screen_bounds = self._screen_rect(bounds)
            pygame.draw.rect(screen, (28, 34, 46), screen_bounds, border_radius=12)
            pygame.draw.rect(screen, self.zone_boundary_color, screen_bounds, width=5, border_radius=12)

        for obstacle in self._zone_obstacles(zone):
            screen_obstacle = self._screen_rect(obstacle)
            overlay = pygame.Surface((screen_obstacle.width, screen_obstacle.height), pygame.SRCALPHA)
            overlay.fill((self.obstacle_color.r, self.obstacle_color.g, self.obstacle_color.b, 110))
            screen.blit(overlay, screen_obstacle)

        screen_bounds = self._screen_rect(bounds)
        pygame.draw.rect(screen, self.zone_boundary_color, screen_bounds, width=2, border_radius=12)

    def _render_parallax_layers(self, screen: pygame.Surface, tilemap: dict) -> None:
        layers = tilemap.get("parallax", [])
        if not layers:
            return

        for layer in layers:
            tile_name = layer.get("tile", "trees")
            speed = float(layer.get("speed", 0.5))
            offset = layer.get("offset", [0, 0])
            tile_size = int(tilemap.get("tile_size", 40)) * 2
            tile_surface = self._tile_surface(tile_name, tile_size)
            if not tile_surface:
                continue
            start_x = -int(self.camera_position[0] * speed) + int(offset[0])
            start_y = -int(self.camera_position[1] * speed) + int(offset[1])
            tile_w, tile_h = tile_surface.get_size()
            for x in range(start_x % tile_w - tile_w, self.screen_size[0] + tile_w, tile_w):
                for y in range(start_y % tile_h - tile_h, self.screen_size[1] + tile_h, tile_h):
                    screen.blit(tile_surface, (x, y))

    def _render_tile_layers(self, screen: pygame.Surface, tilemap: dict, zone: Zone) -> None:
        bounds = self._zone_rect(zone)
        if not bounds:
            return

        tile_size = int(tilemap.get("tile_size", 40))
        ground = tilemap.get("ground_grid", [])
        for y, row in enumerate(ground):
            for x, tile_name in enumerate(row):
                tile_surface = self._tile_surface(tile_name, tile_size)
                if not tile_surface:
                    continue
                world_x = bounds.x + x * tile_size
                world_y = bounds.y + y * tile_size
                screen.blit(tile_surface, self._screen_point((world_x, world_y)))

        for decoration in tilemap.get("decorations", []):
            tile_name = decoration.get("tile", "flowers")
            positions = decoration.get("positions", [])
            tile_surface = self._tile_surface(tile_name, tile_size)
            if not tile_surface:
                continue
            for pos in positions:
                px, py = pos
                world_x = bounds.x + px * tile_size
                world_y = bounds.y + py * tile_size
                screen.blit(tile_surface, self._screen_point((world_x, world_y)))

        for prop in tilemap.get("props", []):
            tile_name = prop.get("tile", "campfire")
            positions = prop.get("positions", [])
            tile_surface = self._tile_surface(tile_name, tile_size)
            if not tile_surface:
                continue
            for pos in positions:
                px, py = pos
                world_x = bounds.x + px * tile_size
                world_y = bounds.y + py * tile_size
                screen.blit(tile_surface, self._screen_point((world_x, world_y)))

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
            color = pygame.Color(200, 70, 70) if actor.name == self.target_name else actor.minimap_color
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
        except Exception as exc:  # pragma: no cover - defensive video fallback
            log_with_fields(logger, logging.WARNING, "Fullscreen mode failed, falling back", error=str(exc))
            self.screen_size = SCREEN_SIZE
            screen = pygame.display.set_mode(self.screen_size)
        clock = pygame.time.Clock()
        self.running = True
        self._initialize_render_assets()

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
                        if self._handle_talent_click(event.pos):
                            continue
                        if self.show_inventory and self._start_drag(event.pos):
                            continue
                        if not (pygame.key.get_mods() & pygame.KMOD_SHIFT):
                            if self._handle_hotbar_click(event.pos):
                                continue
                        if self._start_skill_drag(event.pos):
                            continue
                        self._handle_attack_click(event.pos)
                if event.type == pygame.MOUSEBUTTONUP:
                    self.mouse_pos = event.pos
                    if event.button == 1:
                        if self.dragging_slot:
                            self._complete_drag(event.pos)
                        if self.dragging_ability:
                            self._complete_skill_drag(event.pos)
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
            self._update_actor_animations(dt)
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
