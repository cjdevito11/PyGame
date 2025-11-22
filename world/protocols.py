"""Protocol definitions for extensible game entities.

These abstractions provide clear extension points so plugins can add new
characters, stats, abilities, and world state providers while sharing a common
serialization contract.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Iterable, List, Protocol, Sequence, TypeVar, runtime_checkable


TSerializable = TypeVar("TSerializable", bound="Serializable")


@runtime_checkable
class Serializable(Protocol):
    """Entity that can be converted to and from a plain dictionary.

    Implementations should only return JSON-serializable values so game
    persistence remains backend agnostic. The accompanying ``from_dict``
    constructor must invert ``to_dict`` and may accept additional keyword
    arguments when needed.
    """

    def to_dict(self) -> Dict[str, Any]:
        """Return a dictionary that fully represents the object."""

    @classmethod
    def from_dict(cls: type[TSerializable], data: Dict[str, Any], **kwargs: Any) -> TSerializable:
        """Reconstruct an object from its serialized representation."""


@runtime_checkable
class StatBlock(Serializable, Protocol):
    """Collection of numeric stats used to evaluate actions and requirements."""

    name: str

    def get_modifier(self, key: str) -> int:
        """Return a stat modifier for the provided key (e.g., ``"strength"``)."""


@runtime_checkable
class Ability(Serializable, Protocol):
    """Action a character can perform during gameplay."""

    name: str
    description: str

    def apply(self, user: "BaseCharacter", target: "BaseCharacter | None", world: "WorldState") -> None:
        """Perform the ability using the given participants and world state."""


@runtime_checkable
class AppearanceTrait(Serializable, Protocol):
    """Lightweight description of how a character looks or is presented."""

    label: str

    def summarize(self) -> str:
        """Produce a short human-readable description of the trait."""


@runtime_checkable
class Skill(Serializable, Protocol):
    """Learnable proficiencies that combine stats, abilities, and progress."""

    name: str
    description: str
    level: int

    def level_up(self) -> None:
        """Increase the skill level according to the implementation's rules."""


@runtime_checkable
class Item(Serializable, Protocol):
    """Inventory object with gameplay effects."""

    name: str
    description: str

    def apply_to(self, character: "BaseCharacter") -> None:
        """Apply the item's effect to a character."""


@runtime_checkable
class Quest(Serializable, Protocol):
    """Trackable objective with completion state."""

    identifier: str
    description: str
    status: str

    def advance(self, world: "WorldState") -> None:
        """Progress quest state based on the provided world information."""


class BaseCharacter(Serializable, ABC):
    """Core runtime representation of a player or NPC.

    Subclasses should provide concrete behavior for decision making while
    reusing the provided composition-friendly storage for abilities, appearance
    traits, skills, and inventory items.
    """

    def __init__(
        self,
        name: str,
        stats: StatBlock,
        abilities: Sequence[Ability],
        appearance: Sequence[AppearanceTrait],
        skills: Sequence[Skill],
        items: Sequence[Item],
        quests: Sequence[Quest],
    ) -> None:
        self.name = name
        self.stats = stats
        self.abilities: List[Ability] = list(abilities)
        self.appearance: List[AppearanceTrait] = list(appearance)
        self.skills: List[Skill] = list(skills)
        self.items: List[Item] = list(items)
        self.quests: List[Quest] = list(quests)

    @abstractmethod
    def choose_action(self, world: "WorldState") -> str:
        """Determine what this character will do on their turn."""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the character and composed collaborators."""

        def _serialize_many(components: Iterable[Serializable]) -> List[Dict[str, Any]]:
            return [component.to_dict() for component in components]

        return {
            "name": self.name,
            "stats": self.stats.to_dict(),
            "abilities": _serialize_many(self.abilities),
            "appearance": _serialize_many(self.appearance),
            "skills": _serialize_many(self.skills),
            "items": _serialize_many(self.items),
            "quests": _serialize_many(self.quests),
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        *,
        stat_block_factory: Callable[[Dict[str, Any]], StatBlock],
        ability_factory: Callable[[Dict[str, Any]], Ability],
        appearance_factory: Callable[[Dict[str, Any]], AppearanceTrait],
        skill_factory: Callable[[Dict[str, Any]], Skill],
        item_factory: Callable[[Dict[str, Any]], Item],
        quest_factory: Callable[[Dict[str, Any]], Quest],
    ) -> "BaseCharacter":
        """Create a character from serialized data using supplied factories.

        The factories are responsible for converting raw dictionaries back into
        concrete implementations of each collaborator (including plugin types).
        """

        stats = stat_block_factory(data["stats"])
        abilities = [ability_factory(entry) for entry in data["abilities"]]
        appearance = [appearance_factory(entry) for entry in data["appearance"]]
        skills = [skill_factory(entry) for entry in data["skills"]]
        items = [item_factory(entry) for entry in data["items"]]
        quests = [quest_factory(entry) for entry in data["quests"]]
        return cls(
            name=data["name"],
            stats=stats,
            abilities=abilities,
            appearance=appearance,
            skills=skills,
            items=items,
            quests=quests,
        )


class WorldState(Serializable, ABC):
    """Container for all active game objects and stateful systems."""

    def __init__(self, *, characters: Sequence[BaseCharacter], quests: Sequence[Quest]):
        self.characters: List[BaseCharacter] = list(characters)
        self.quests: List[Quest] = list(quests)

    @abstractmethod
    def tick(self) -> None:
        """Advance the simulation by one step."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "characters": [character.to_dict() for character in self.characters],
            "quests": [quest.to_dict() for quest in self.quests],
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        *,
        character_factory: Callable[[Dict[str, Any]], BaseCharacter],
        quest_factory: Callable[[Dict[str, Any]], Quest],
    ) -> "WorldState":
        """Rehydrate a world state using supplied factories for characters and quests."""

        characters = [character_factory(entry) for entry in data["characters"]]
        quests = [quest_factory(entry) for entry in data["quests"]]
        return cls(characters=characters, quests=quests)
