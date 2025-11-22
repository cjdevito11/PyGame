"""Utility for loading JSON and YAML data definitions."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import importlib.util
import json
import logging

from core.logging_config import get_logger, log_with_fields

logger = get_logger(__name__)
if importlib.util.find_spec("yaml") is not None:  # pragma: no cover - passthrough
    import yaml
else:  # pragma: no cover - fallback
    yaml = None

SUPPORTED_EXTENSIONS = {".json", ".yml", ".yaml"}


def _read_file(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        log_with_fields(logger, logging.ERROR, "Failed to read file", path=str(path))
        raise


def _parse_yaml_list(raw_text: str) -> Any:
    if yaml is None:
        # Minimal YAML list parser fallback for environments without PyYAML.
        items: List[Dict[str, Any]] = []
        current: Dict[str, Any] | None = None
        for line in raw_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("-"):
                if current:
                    items.append(current)
                current = {}
                stripped = stripped.lstrip("- ")
                if stripped:
                    key, value = stripped.split(":", 1)
                    current[key.strip()] = value.strip().strip('"')
            elif current is not None and ":" in stripped:
                key, value = stripped.split(":", 1)
                current[key.strip()] = _coerce_value(value.strip())
        if current:
            items.append(current)
        return items
    return yaml.safe_load(raw_text)


def _coerce_value(value: str) -> Any:
    if value.isdigit():
        return int(value)
    if value.startswith("\"") and value.endswith("\""):
        return value.strip('"')
    return value


def _ensure_list(payload: Any, *, source: Path | None = None) -> List[Dict[str, Any]]:
    if not isinstance(payload, list):
        source_hint = f" in {source.name}" if source else ""
        raise ValueError(f"Data files{source_hint} must contain a list of definitions.")
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(
                f"Definition at position {index} in {source or 'data file'} is not an object; "
                f"got {type(item).__name__}."
            )
    return payload


def load_definitions(path: Path) -> List[Dict[str, Any]]:
    if path.suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    log_with_fields(logger, logging.INFO, "Loading definitions", path=str(path))
    raw_text = _read_file(path)
    if path.suffix == ".json":
        payload = json.loads(raw_text)
    else:
        payload = _parse_yaml_list(raw_text)
    validated_payload = _ensure_list(payload, source=path)
    log_with_fields(
        logger,
        logging.DEBUG,
        "Loaded entries",
        path=str(path),
        count=len(validated_payload),
    )
    return validated_payload


def load_from_directory(directory: Path) -> Dict[str, List[Dict[str, Any]]]:
    definitions: Dict[str, List[Dict[str, Any]]] = {}
    for path in directory.iterdir():
        if path.suffix in SUPPORTED_EXTENSIONS:
            definitions[path.stem] = load_definitions(path)
    return definitions
