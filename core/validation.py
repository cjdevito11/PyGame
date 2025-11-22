"""Validation helpers using Pydantic with kid-friendly error messages."""
from typing import Dict, Type

from core.pydantic_compat import BaseModel, ValidationError


class DefinitionValidator:
    """Registers schemas and validates incoming data with friendly errors."""

    def __init__(self) -> None:
        self._schemas: Dict[str, Type[BaseModel]] = {}

    def register_schema(self, type_name: str, schema: Type[BaseModel]) -> None:
        self._schemas[type_name] = schema

    def validate(self, type_name: str, data: Dict) -> Dict:
        if type_name not in self._schemas:
            raise ValueError(f"No schema registered for '{type_name}'.")
        schema = self._schemas[type_name]
        try:
            model = schema(**data)
        except ValidationError as exc:
            friendly_errors = "; ".join(
                f"{error['loc'][0]}: {error['msg']}" for error in exc.errors()
            )
            raise ValueError(
                f"Could not understand the {type_name} you provided. "
                f"Please fix these issues: {friendly_errors}"
            ) from exc
        return model.dict()
