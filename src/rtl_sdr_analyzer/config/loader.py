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

    Priority (lowest → highest):
        1. Default field values
        2. YAML configuration file
        3. Environment variables (RTL_SDR__*)
        4. CLI override dictionary

    Args:
        config_path: Path to a YAML configuration file.
        cli_overrides: Flat dictionary of dot-notation keys and values
            from CLI arguments, e.g. {"receiver.frequency": 98e6}.

    Returns:
        Validated Settings instance.
    """
    # 1. Load YAML file if provided
    yaml_data: dict[str, Any] = {}
    if config_path:
        path = Path(config_path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    yaml_data = loaded

    # 2. Read environment variables (RTL_SDR__SECTION__FIELD)
    env_overrides = _read_env_overrides()
    if env_overrides:
        _deep_update(yaml_data, env_overrides)

    # 3. Create settings — pydantic-settings may also read env vars, but we
    #    explicitly inject them above to guarantee nested merging works.
    settings = Settings(**yaml_data)

    # 4. Apply CLI overrides (highest priority)
    if cli_overrides:
        current = settings.model_dump()
        for dot_key, value in cli_overrides.items():
            if value is not None:
                _set_nested(current, dot_key.split("."), value)
        settings = Settings(**current)

    return settings


def _read_env_overrides() -> dict[str, Any]:
    """Parse RTL_SDR__* environment variables into a nested dict."""
    overrides: dict[str, Any] = {}
    prefix = "RTL_SDR__"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        path = key[len(prefix) :].lower().split("__")
        _set_nested(overrides, path, _coerce_env_value(value))
    return overrides


def _coerce_env_value(value: str) -> Any:
    """Convert string env values to int/float/bool when possible."""
    lowered = value.lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _set_nested(data: dict[str, Any], keys: list[str], value: Any) -> None:
    """Set a nested dictionary value by key path."""
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value


def _deep_update(base: dict[str, Any], overrides: dict[str, Any]) -> None:
    """Recursively merge overrides into base."""
    for key, value in overrides.items():
        if isinstance(value, dict) and key in base and isinstance(base[key], dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
