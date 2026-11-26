"""Configuration loader merging YAML, environment variables, and CLI overrides."""

import os
from pathlib import Path
from typing import Any

import yaml

from .models import Settings


def load_settings(
    config_path: Path | str | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> Settings:
    """Load and merge configuration sources.

    Precedence (lowest -> highest):
        1. Default field values
        2. YAML configuration file
        3. Environment variables (RTL_SDR__SECTION__FIELD)
        4. CLI override dictionary

    Args:
        config_path: Optional path to a YAML configuration file. If explicitly
            supplied and missing, raises :class:`FileNotFoundError`.
        cli_overrides: Flat dictionary of dot-notation keys and values
            from CLI arguments, e.g. ``{"receiver.frequency": 98e6}``.

    Returns:
        Validated :class:`Settings` instance.
    """
    yaml_data: dict[str, Any] = {}
    if config_path is not None:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        with open(path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                yaml_data = loaded

    env_overrides = _read_env_overrides()
    if env_overrides:
        _deep_update(yaml_data, env_overrides)

    settings = Settings(**yaml_data)

    if cli_overrides:
        current = settings.model_dump()
        for dot_key, value in cli_overrides.items():
            if value is not None:
                _set_nested(current, dot_key.split("."), value)
        settings = Settings(**current)

    return settings


def _read_env_overrides() -> dict[str, Any]:
    """Parse ``RTL_SDR__*`` environment variables into a nested dictionary."""
    overrides: dict[str, Any] = {}
    prefix = "RTL_SDR__"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        path = [part for part in key[len(prefix) :].lower().split("__") if part]
        if not path:
            continue
        _set_nested(overrides, path, _coerce_env_value(value))
    return overrides


def _coerce_env_value(value: str) -> Any:
    """Coerce explicit boolean/null strings while preserving numbers for Pydantic."""
    stripped = value.strip()
    lowered = stripped.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("none", "null", ""):
        return None
    return stripped


def _set_nested(data: dict[str, Any], keys: list[str], value: Any) -> None:
    """Set a nested dictionary value by key path."""
    for key in keys[:-1]:
        node = data.get(key)
        if not isinstance(node, dict):
            node = {}
            data[key] = node
        data = node
    data[keys[-1]] = value


def _deep_update(base: dict[str, Any], overrides: dict[str, Any]) -> None:
    """Recursively merge overrides into base."""
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
