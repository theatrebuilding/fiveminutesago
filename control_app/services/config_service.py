from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

import yaml


class ConfigValidationError(ValueError):
    """Raised when a submitted config file cannot be parsed as expected."""


class ConfigSyncError(RuntimeError):
    """Raised when the local config cannot be refreshed from the central server."""


class ConfigService:
    def __init__(
        self,
        config_path: Path,
        *,
        central_config_url: str | None = None,
        dashboard_username: str = "admin",
        dashboard_password: str = "",
        sync_timeout_seconds: float = 5,
    ) -> None:
        self._config_path = config_path
        self._central_config_url = central_config_url.strip() if central_config_url else None
        self._dashboard_username = dashboard_username
        self._dashboard_password = dashboard_password
        self._sync_timeout_seconds = sync_timeout_seconds

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

    def sync_from_central(self) -> dict[str, Any]:
        url = self._resolve_central_config_url()
        if not url:
            return {
                "attempted": False,
                "updated": False,
                "url": None,
                "message": "No central config URL is configured or derivable from server_ip.",
            }

        request = Request(_with_query_param(url, "sync", "0"), headers={"Accept": "application/json"})
        if self._dashboard_password:
            credentials = f"{self._dashboard_username}:{self._dashboard_password}".encode("utf-8")
            token = base64.b64encode(credentials).decode("ascii")
            request.add_header("Authorization", f"Basic {token}")

        try:
            with urlopen(request, timeout=self._sync_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise ConfigSyncError(f"Central config request failed with HTTP {exc.code} at {url}.") from exc
        except (OSError, URLError, json.JSONDecodeError) as exc:
            raise ConfigSyncError(f"Could not fetch central config from {url}: {exc}") from exc

        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise ConfigSyncError(f"Central config response from {url} did not include config text.")

        parsed = self.validate_text(text)
        previous_text = self.read_text() if self._config_path.exists() else None
        normalized = text.rstrip() + "\n"
        updated = previous_text != normalized
        if updated:
            self._write_normalized_text(text)

        return {
            "attempted": True,
            "updated": updated,
            "url": url,
            "server_ip": parsed.get("server_ip"),
        }

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

    def _resolve_central_config_url(self) -> str | None:
        if self._central_config_url:
            return _normalize_config_url(self._central_config_url)

        if not self._config_path.exists():
            return None

        try:
            config = self.read_data()
        except (OSError, ConfigValidationError):
            return None

        server_ip = str(config.get("server_ip") or "").strip()
        if not server_ip:
            return None
        return f"http://{server_ip}:8000/api/config"


def _normalize_config_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme:
        parsed = urlparse(f"http://{url.strip()}")
    path = parsed.path.rstrip("/")
    if not path:
        path = "/api/config"
    elif not path.endswith("/api/config"):
        path = f"{path}/api/config"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def _with_query_param(url: str, name: str, value: str) -> str:
    parsed = urlparse(url)
    query = [(key, item_value) for key, item_value in parse_qsl(parsed.query, keep_blank_values=True) if key != name]
    query.append((name, value))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), parsed.fragment))
