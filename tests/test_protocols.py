import pytest

from world.protocols import Ability, AppearanceTrait, BaseCharacter, Item, Quest, Skill, StatBlock, WorldState


class DummyStatBlock:
    def __init__(self, name: str, modifiers: dict[str, int]):
        self.name = name
        self._modifiers = modifiers

    def get_modifier(self, key: str) -> int:
        return self._modifiers.get(key, 0)

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "modifiers": self._modifiers}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "DummyStatBlock":
        return cls(name=data["name"], modifiers=dict(data.get("modifiers", {})))


class DummyAbility:
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.used = False

    def apply(self, user: "BaseCharacter", target: "BaseCharacter | None", world: "WorldState") -> None:
        self.used = True
        world.log.append(f"{user.name} uses {self.name}")

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "description": self.description}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "DummyAbility":
        return cls(name=data["name"], description=data.get("description", ""))


class DummyAppearance:
    def __init__(self, label: str):
        self.label = label

    def summarize(self) -> str:
        return self.label

    def to_dict(self) -> dict[str, object]:
        return {"label": self.label}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "DummyAppearance":
        return cls(label=data["label"])


class DummySkill:
    def __init__(self, name: str, description: str, level: int):
        self.name = name
        self.description = description
        self.level = level

    def level_up(self) -> None:
        self.level += 1

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "description": self.description, "level": self.level}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "DummySkill":
        return cls(name=data["name"], description=data.get("description", ""), level=int(data["level"]))


class DummyItem:
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.applied_to: list[str] = []

    def apply_to(self, character: "BaseCharacter") -> None:
        self.applied_to.append(character.name)

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "description": self.description}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "DummyItem":
        return cls(name=data["name"], description=data.get("description", ""))


class DummyQuest:
    def __init__(self, identifier: str, description: str, status: str):
        self.identifier = identifier
        self.description = description
        self.status = status

    def advance(self, world: "WorldState") -> None:
        world.log.append(f"Quest {self.identifier} advanced")
        self.status = "updated"

    def to_dict(self) -> dict[str, object]:
        return {"identifier": self.identifier, "description": self.description, "status": self.status}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "DummyQuest":
        return cls(identifier=data["identifier"], description=data.get("description", ""), status=data.get("status", "new"))


class DummyCharacter(BaseCharacter):
    def __init__(self, name: str, stats: StatBlock, abilities, appearance, skills, items, quests):
        super().__init__(name, stats, abilities, appearance, skills, items, quests)
        self.actions_chosen: list[str] = []

    def choose_action(self, world: "WorldState") -> str:
        self.actions_chosen.append("wait")
        return "wait"


class DummyWorldState(WorldState):
    def __init__(self, *, characters, quests):
        super().__init__(characters=characters, quests=quests)
        self.log: list[str] = []

    def tick(self) -> None:
        self.log.append("tick")


@pytest.fixture
def populated_character() -> DummyCharacter:
    stats = DummyStatBlock(name="hero-stats", modifiers={"strength": 2})
    abilities = [DummyAbility(name="slash", description=""), DummyAbility(name="shout", description="")]
    appearance = [DummyAppearance(label="red cloak"), DummyAppearance(label="tall")]
    skills = [DummySkill(name="sword", description="", level=1)]
    items = [DummyItem(name="potion", description="heal")]
    quests = [DummyQuest(identifier="quest-1", description="", status="new")]
    return DummyCharacter(
        name="Hero",
        stats=stats,
        abilities=abilities,
        appearance=appearance,
        skills=skills,
        items=items,
        quests=quests,
    )


def test_serialization_round_trip(populated_character: DummyCharacter) -> None:
    world = DummyWorldState(characters=[populated_character], quests=populated_character.quests)
    populated_character.abilities[0].apply(populated_character, None, world)
    serialized = populated_character.to_dict()

    recreated = DummyCharacter.from_dict(
        serialized,
        stat_block_factory=DummyStatBlock.from_dict,
        ability_factory=DummyAbility.from_dict,
        appearance_factory=DummyAppearance.from_dict,
        skill_factory=DummySkill.from_dict,
        item_factory=DummyItem.from_dict,
        quest_factory=DummyQuest.from_dict,
    )

    assert isinstance(recreated, BaseCharacter)
    assert recreated.name == populated_character.name
    assert recreated.stats.get_modifier("strength") == 2
    assert [a.to_dict() for a in recreated.abilities] == [
        a.to_dict() for a in populated_character.abilities
    ]
    assert [trait.summarize() for trait in recreated.appearance] == [
        trait.summarize() for trait in populated_character.appearance
    ]
    assert [skill.level for skill in recreated.skills] == [
        skill.level for skill in populated_character.skills
    ]
    assert [item.name for item in recreated.items] == [
        item.name for item in populated_character.items
    ]


def test_world_state_restores_characters(populated_character: DummyCharacter) -> None:
    world = DummyWorldState(characters=[populated_character], quests=populated_character.quests)
    world.tick()
    serialized = world.to_dict()

    recreated_world = DummyWorldState.from_dict(
        serialized,
        character_factory=lambda data: DummyCharacter.from_dict(
            data,
            stat_block_factory=DummyStatBlock.from_dict,
            ability_factory=DummyAbility.from_dict,
            appearance_factory=DummyAppearance.from_dict,
            skill_factory=DummySkill.from_dict,
            item_factory=DummyItem.from_dict,
            quest_factory=DummyQuest.from_dict,
        ),
        quest_factory=DummyQuest.from_dict,
    )

    assert isinstance(recreated_world, WorldState)
    assert recreated_world.characters[0].name == "Hero"
    assert recreated_world.quests[0].identifier == "quest-1"
    assert isinstance(recreated_world.characters[0].abilities[0], Ability)
    assert isinstance(recreated_world.characters[0].appearance[0], AppearanceTrait)
    assert isinstance(recreated_world.characters[0].items[0], Item)
    assert isinstance(recreated_world.characters[0].skills[0], Skill)
    assert isinstance(recreated_world.quests[0], Quest)
