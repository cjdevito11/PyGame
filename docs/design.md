# Entity extension design

This project supports pluggable game entities by defining small, focused
interfaces that new content can implement.

## Core protocols

- `Serializable` requires `to_dict`/`from_dict` so every entity can persist
  itself to JSON-like structures.
- `StatBlock`, `Ability`, `AppearanceTrait`, `Skill`, `Item`, and `Quest`
  describe narrow responsibilities (stats, actions, visuals, progression,
  inventory, and objectives). Plugins can implement any of these without
  subclassing engine classes.
- `BaseCharacter` composes lists of abilities, appearance traits, skills,
  items, and quests. It provides serialization that delegates to those
  collaborators so custom implementations save/load automatically.
- `WorldState` wraps the active game, exposing serialization hooks and a `tick`
  lifecycle method that concrete engines can extend.

## Serialization expectations

Each entity must return only JSON-serializable values from `to_dict`.
Factories passed into `from_dict` methods resolve the appropriate concrete
classes (including plugins). This keeps the core classes decoupled from
registration concerns while allowing flexible persistence formats.

## Composition-first architecture

Characters do not inherit abilities or appearance traits. Instead, the
interfaces encourage composing lists of small behaviors and descriptions. This
keeps plugins focused and avoids deep inheritance hierarchies.
