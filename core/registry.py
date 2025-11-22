"""Generic registry for pluggable game data."""
from typing import Callable, Dict, Generic, Iterable, List, TypeVar

from core.validation import DefinitionValidator

T = TypeVar("T")


class Registry(Generic[T]):
    """Maintains validated definitions and creates runtime objects."""

    def __init__(
        self, name: str, validator: DefinitionValidator, factory: Callable[[str, Dict], T]
    ) -> None:
        self.name = name
        self.validator = validator
        self.factory = factory
        self._definitions: Dict[str, Dict] = {}

    def register(self, raw_data: Dict) -> None:
        validated = self.validator.validate(self.name, raw_data)
        entry_name = validated["name"]
        self._definitions[entry_name] = validated

    def load_many(self, definitions: Iterable[Dict]) -> None:
        for definition in definitions:
            self.register(definition)

    def create(self, type_name: str) -> T:
        if type_name not in self._definitions:
            available = ", ".join(sorted(self._definitions)) or "none"
            raise KeyError(
                f"No {self.name} named '{type_name}' is available. "
                f"Currently registered: {available}."
            )
        return self.factory(type_name, self._definitions[type_name])

    def entries(self) -> List[str]:
        return sorted(self._definitions)

    def definitions(self) -> Dict[str, Dict]:
        return dict(self._definitions)
