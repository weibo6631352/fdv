from __future__ import annotations

from dataclasses import fields, is_dataclass
import json
from pathlib import Path
import tomllib
from typing import Any, TypeVar

from pydantic import TypeAdapter, ValidationError

from strategy_sdk.errors import StrategyLoadError

T = TypeVar("T")


def load_mapping_file(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise StrategyLoadError(f"strategy file not found: {config_path}")
    if config_path.suffix == ".json":
        data = json.loads(config_path.read_text(encoding="utf-8"))
    elif config_path.suffix == ".toml":
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    else:
        raise StrategyLoadError(
            f"unsupported strategy file format '{config_path.suffix or '<none>'}', expected .json or .toml"
        )
    if not isinstance(data, dict):
        raise StrategyLoadError(f"strategy file must contain an object at top level: {config_path}")
    return data


def load_strategy_config(config_type: type[T], config_path: str | None) -> T | None:
    if config_path is None:
        return None
    if not is_dataclass(config_type):
        raise StrategyLoadError(f"config type {config_type!r} must be a dataclass")
    data = load_mapping_file(config_path)
    field_names = {field.name for field in fields(config_type)}
    filtered = {key: value for key, value in data.items() if key in field_names}
    try:
        return TypeAdapter(config_type).validate_python(filtered)
    except ValidationError as exc:
        raise StrategyLoadError(
            f"failed to build config {config_type.__name__} from {config_path}: {exc}"
        ) from exc
