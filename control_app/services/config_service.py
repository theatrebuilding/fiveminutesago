from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigValidationError(ValueError):
    """Raised when a submitted config file cannot be parsed as expected."""


class ConfigService:
    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path

    @property
    def config_path(self) -> Path:
        return self._config_path

    def read_text(self) -> str:
        return self._config_path.read_text(encoding="utf-8")

    def read_data(self) -> dict[str, Any]:
        return self.validate_text(self.read_text())

    def ensure_exists(self, seed_path: Path) -> bool:
        if self._config_path.exists():
            return False
        if self._config_path == seed_path:
            return False
        if not seed_path.exists():
            return False

        text = seed_path.read_text(encoding="utf-8")
        self.validate_text(text)
        self._write_normalized_text(text)
        return True

    def validate_text(self, text: str) -> dict[str, Any]:
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigValidationError(f"Config is not valid YAML: {exc}") from exc

        if not isinstance(parsed, dict):
            raise ConfigValidationError("Config must be a top-level YAML mapping.")

        return parsed

    def write_text(self, text: str) -> dict[str, Any]:
        parsed = self.validate_text(text)
        self._write_normalized_text(text)
        return parsed

    def _write_normalized_text(self, text: str) -> None:
        normalized = text.rstrip() + "\n"
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._config_path.with_name(f".{self._config_path.name}.tmp")
        temp_path.write_text(normalized, encoding="utf-8")
        temp_path.replace(self._config_path)
