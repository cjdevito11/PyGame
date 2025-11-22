"""Provide Pydantic primitives, falling back to a tiny stub when unavailable.

This keeps the validation layer working in offline environments while still
preferring the real `pydantic` package when it can be installed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import importlib.util


if importlib.util.find_spec("pydantic") is not None:  # pragma: no cover - passthrough
    from pydantic import BaseModel, Field, ValidationError
else:
    class FieldInfo:
        def __init__(
            self,
            default: Any = ...,  # noqa: ANN401 - mirror pydantic signature
            *,
            description: Optional[str] = None,
            min_length: Optional[int] = None,
            max_length: Optional[int] = None,
            ge: Optional[int] = None,
            le: Optional[int] = None,
        ) -> None:
            self.default = default
            self.description = description
            self.min_length = min_length
            self.max_length = max_length
            self.ge = ge
            self.le = le


    class ValidationError(Exception):
        def __init__(self, errors: List[Dict[str, Any]]) -> None:
            super().__init__("; ".join(error["msg"] for error in errors))
            self._errors = errors

        def errors(self) -> List[Dict[str, Any]]:
            return self._errors


    def Field(default: Any = ..., **kwargs: Any) -> FieldInfo:  # noqa: ANN401 - mirror pydantic
        return FieldInfo(default=default, **kwargs)


    class BaseModel:
        class Config:
            extra = "ignore"

        def __init__(self, **data: Any) -> None:
            errors: List[Dict[str, Any]] = []
            validated: Dict[str, Any] = {}
            annotations: Dict[str, Any] = {}
            for cls in reversed(self.__class__.mro()):
                annotations.update(getattr(cls, "__annotations__", {}))
            allowed_fields = set(annotations.keys())
            if getattr(self.Config, "extra", "ignore") == "forbid":
                extras = set(data.keys()) - allowed_fields
                for extra in extras:
                    errors.append({"loc": (extra,), "msg": "extra fields not permitted"})
            for field, expected_type in annotations.items():
                value = data.get(field, None)
                field_info: FieldInfo = getattr(self.__class__, field, FieldInfo())
                if value is None:
                    if field_info.default is ...:
                        errors.append({"loc": (field,), "msg": "field required"})
                    else:
                        validated[field] = field_info.default
                    continue
                errors.extend(self._validate_type(field, value, expected_type))
                if errors:
                    continue
                if isinstance(value, str):
                    self._validate_string_constraints(field, value, field_info, errors)
                if isinstance(value, (int, float)):
                    self._validate_numeric_constraints(field, value, field_info, errors)
                validated[field] = value
            if errors:
                raise ValidationError(errors)
            self._data = validated

        @staticmethod
        def _validate_type(field: str, value: Any, expected_type: Any) -> List[Dict[str, Any]]:
            error_loc: Tuple[str] = (field,)
            if expected_type is int and not isinstance(value, int):
                return [{"loc": error_loc, "msg": "value is not a valid integer"}]
            if expected_type is str and not isinstance(value, str):
                return [{"loc": error_loc, "msg": "value is not a valid string"}]
            return []

        @staticmethod
        def _validate_string_constraints(
            field: str, value: str, info: FieldInfo, errors: List[Dict[str, Any]]
        ) -> None:
            if info.min_length is not None and len(value) < info.min_length:
                errors.append(
                    {"loc": (field,), "msg": f"ensure this value has at least {info.min_length} characters"}
                )
            if info.max_length is not None and len(value) > info.max_length:
                errors.append(
                    {"loc": (field,), "msg": f"ensure this value has at most {info.max_length} characters"}
                )

        @staticmethod
        def _validate_numeric_constraints(
            field: str, value: float, info: FieldInfo, errors: List[Dict[str, Any]]
        ) -> None:
            if info.ge is not None and value < info.ge:
                errors.append(
                    {"loc": (field,), "msg": f"ensure this value is greater than or equal to {info.ge}"}
                )
            if info.le is not None and value > info.le:
                errors.append(
                    {"loc": (field,), "msg": f"ensure this value is less than or equal to {info.le}"}
                )

        def dict(self) -> Dict[str, Any]:
            return dict(self._data)

