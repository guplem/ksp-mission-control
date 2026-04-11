"""Persistent configuration management for KSP Mission Control."""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "ksp-mission-control"


@dataclass
class AppConfig:
    """Application configuration stored in config.json.

    All fields default to ``None`` so the app works out-of-the-box
    without a config file.  New settings are added as fields with
    defaults, keeping backward compatibility with older files.
    """

    ksp_path: str | None = field(default=None)


def get_config_dir() -> Path:
    """Return the platform-appropriate configuration directory.

    - Windows: ``%APPDATA%/ksp-mission-control/``
    - macOS:   ``~/Library/Application Support/ksp-mission-control/``
    - Linux:   ``$XDG_CONFIG_HOME/ksp-mission-control/`` (fallback ``~/.config/``)
    """
    system = platform.system()

    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"

    return base / APP_NAME


class ConfigManager:
    """Loads and saves :class:`AppConfig` to a JSON file on disk.

    Pass a custom *config_dir* for testing; otherwise the
    platform default from :func:`get_config_dir` is used.
    """

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir: Path = config_dir or get_config_dir()
        self._config_path: Path = self._config_dir / "config.json"
        self._config: AppConfig = self._load()

    @property
    def config(self) -> AppConfig:
        return self._config

    def save(self) -> None:
        """Write the current config to disk, creating directories if needed."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        data = dataclasses.asdict(self._config)
        self._config_path.write_text(json.dumps(data, indent=2))

    def _load(self) -> AppConfig:
        """Read config from disk, returning defaults on missing or corrupt files."""
        if not self._config_path.is_file():
            return AppConfig()
        try:
            raw = json.loads(self._config_path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt config at %s, using defaults", self._config_path)
            return AppConfig()
        if not isinstance(raw, dict):
            return AppConfig()
        return AppConfig(
            ksp_path=raw.get("ksp_path"),
        )
