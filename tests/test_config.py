"""Tests for the config management module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ksp_mission_control.config import AppConfig, ConfigManager, get_config_dir


class TestAppConfig:
    """Tests for the AppConfig dataclass."""

    def test_default_values(self) -> None:
        config = AppConfig()
        assert config.ksp_path is None

    def test_is_mutable(self) -> None:
        config = AppConfig()
        config.ksp_path = "/some/path"
        assert config.ksp_path == "/some/path"

    def test_construct_with_values(self) -> None:
        config = AppConfig(ksp_path="/ksp/dir")
        assert config.ksp_path == "/ksp/dir"


class TestGetConfigDir:
    """Tests for platform-specific config directory resolution."""

    def test_returns_path_object(self) -> None:
        result = get_config_dir()
        assert isinstance(result, Path)

    def test_ends_with_app_name(self) -> None:
        result = get_config_dir()
        assert result.name == "ksp-mission-control"

    def test_windows_uses_appdata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("ksp_mission_control.config.platform.system", lambda: "Windows")
        monkeypatch.setenv("APPDATA", "C:\\Users\\test\\AppData\\Roaming")
        result = get_config_dir()
        assert result == Path("C:\\Users\\test\\AppData\\Roaming") / "ksp-mission-control"

    def test_linux_uses_xdg_config_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("ksp_mission_control.config.platform.system", lambda: "Linux")
        monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/config")
        result = get_config_dir()
        assert result == Path("/custom/config/ksp-mission-control")

    def test_linux_defaults_to_dot_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("ksp_mission_control.config.platform.system", lambda: "Linux")
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        result = get_config_dir()
        assert result == Path.home() / ".config" / "ksp-mission-control"

    def test_macos_uses_library(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("ksp_mission_control.config.platform.system", lambda: "Darwin")
        result = get_config_dir()
        assert result == Path.home() / "Library" / "Application Support" / "ksp-mission-control"


class TestConfigManager:
    """Tests for ConfigManager load/save operations."""

    def test_load_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        manager = ConfigManager(config_dir=tmp_path)
        assert manager.config.ksp_path is None

    def test_save_creates_file(self, tmp_path: Path) -> None:
        manager = ConfigManager(config_dir=tmp_path)
        manager.config.ksp_path = "/ksp"
        manager.save()
        assert (tmp_path / "config.json").is_file()

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        manager = ConfigManager(config_dir=tmp_path)
        manager.config.ksp_path = "/path/to/ksp"
        manager.save()

        loaded = ConfigManager(config_dir=tmp_path)
        assert loaded.config.ksp_path == "/path/to/ksp"

    def test_load_corrupt_json_returns_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text("not valid json {{{")
        manager = ConfigManager(config_dir=tmp_path)
        assert manager.config.ksp_path is None

    def test_load_partial_json_fills_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"unknown_key": "value"}))
        manager = ConfigManager(config_dir=tmp_path)
        assert manager.config.ksp_path is None

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested"
        manager = ConfigManager(config_dir=nested)
        manager.config.ksp_path = "/ksp"
        manager.save()
        assert (nested / "config.json").is_file()

    def test_config_property_returns_config(self, tmp_path: Path) -> None:
        manager = ConfigManager(config_dir=tmp_path)
        assert isinstance(manager.config, AppConfig)

    def test_save_preserves_only_known_fields(self, tmp_path: Path) -> None:
        manager = ConfigManager(config_dir=tmp_path)
        manager.config.ksp_path = "/ksp"
        manager.save()

        raw = json.loads((tmp_path / "config.json").read_text())
        assert raw == {"ksp_path": "/ksp", "theme": "mission-control"}

    def test_save_null_path_writes_null(self, tmp_path: Path) -> None:
        manager = ConfigManager(config_dir=tmp_path)
        manager.save()

        raw = json.loads((tmp_path / "config.json").read_text())
        assert raw["ksp_path"] is None
