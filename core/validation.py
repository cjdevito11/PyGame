"""Validation helpers using Pydantic with kid-friendly error messages."""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Type

from core.logging_config import get_logger, log_with_fields
from core.pydantic_compat import BaseModel, ValidationError


logger = get_logger(__name__)


def _dig_value(data: Dict[str, Any], path: Iterable[object]) -> Any:
    current: Any = data
    for part in path:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _format_error(type_name: str, data: Dict[str, Any], error: Dict[str, object]) -> str:
    location = ".".join(str(part) for part in error.get("loc", [])) or "<unknown>"
    value = _dig_value(data, error.get("loc", []))
    display_value = "<missing>" if value is None else repr(value)
    entry_name = data.get("name", "<unnamed>")
    return (
        f"{type_name}.{entry_name}.{location}: {error.get('msg', 'validation error')} "
        f"(value: {display_value})"
    )


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
            formatted_errors = [_format_error(type_name, data, error) for error in exc.errors()]
            summary = "; ".join(formatted_errors)
            log_with_fields(
                logger,
                logging.WARNING,
                "Validation failed",
                type=type_name,
                entry=data.get("name", "<unnamed>"),
                errors=summary,
            )
            raise ValueError(
                "Could not understand the data you provided. Please fix these issues: "
                f"{summary}"
            ) from exc
        log_with_fields(
            logger,
            logging.INFO,
            "Validated entry",
            type=type_name,
            entry=data.get("name", "<unnamed>"),
        )
        return model.dict()
