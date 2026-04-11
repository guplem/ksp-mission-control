"""Tests for KSP installation detection."""

from pathlib import Path

import pytest

from ksp_mission_control.setup.detector import (
    KSP_STEAM_APP_ID,
    KspInstallInfo,
    find_ksp_install,
    get_default_search_paths,
    is_krpc_installed,
    is_valid_ksp_install,
)


class TestIsValidKspInstall:
    """Tests for validating a KSP installation directory."""

    def test_valid_ksp_directory(self, tmp_path: Path) -> None:
        """A directory with KSP.x86_64 (or equivalent) and GameData/ is valid."""
        (tmp_path / "GameData").mkdir()
        (tmp_path / "KSP.x86_64").touch()
        assert is_valid_ksp_install(tmp_path) is True

    def test_valid_ksp_with_windows_exe(self, tmp_path: Path) -> None:
        """Windows KSP uses KSP_x64.exe."""
        (tmp_path / "GameData").mkdir()
        (tmp_path / "KSP_x64.exe").touch()
        assert is_valid_ksp_install(tmp_path) is True

    def test_valid_ksp_with_macos_app(self, tmp_path: Path) -> None:
        """macOS KSP uses KSP.app."""
        (tmp_path / "GameData").mkdir()
        (tmp_path / "KSP.app").mkdir()
        assert is_valid_ksp_install(tmp_path) is True

    def test_missing_gamedata(self, tmp_path: Path) -> None:
        """Missing GameData directory means invalid."""
        (tmp_path / "KSP.x86_64").touch()
        assert is_valid_ksp_install(tmp_path) is False

    def test_missing_executable(self, tmp_path: Path) -> None:
        """GameData but no KSP executable means invalid."""
        (tmp_path / "GameData").mkdir()
        assert is_valid_ksp_install(tmp_path) is False

    def test_empty_directory(self, tmp_path: Path) -> None:
        assert is_valid_ksp_install(tmp_path) is False

    def test_nonexistent_path(self) -> None:
        assert is_valid_ksp_install(Path("/nonexistent/path")) is False

    def test_file_not_directory(self, tmp_path: Path) -> None:
        file_path = tmp_path / "somefile.txt"
        file_path.touch()
        assert is_valid_ksp_install(file_path) is False


class TestIsKrpcInstalled:
    """Tests for checking if kRPC mod is present in a KSP install."""

    def test_krpc_installed(self, tmp_path: Path) -> None:
        """kRPC is installed if GameData/kRPC/ directory exists with kRPC.dll."""
        krpc_dir = tmp_path / "GameData" / "kRPC"
        krpc_dir.mkdir(parents=True)
        (krpc_dir / "kRPC.dll").touch()
        assert is_krpc_installed(tmp_path) is True

    def test_krpc_not_installed(self, tmp_path: Path) -> None:
        (tmp_path / "GameData").mkdir()
        assert is_krpc_installed(tmp_path) is False

    def test_krpc_directory_without_dll(self, tmp_path: Path) -> None:
        """An empty kRPC directory (incomplete install) is not valid."""
        (tmp_path / "GameData" / "kRPC").mkdir(parents=True)
        assert is_krpc_installed(tmp_path) is False

    def test_no_gamedata(self, tmp_path: Path) -> None:
        assert is_krpc_installed(tmp_path) is False


class TestGetDefaultSearchPaths:
    """Tests for platform-specific default search paths."""

    def test_returns_list_of_paths(self) -> None:
        paths = get_default_search_paths()
        assert isinstance(paths, list)
        assert all(isinstance(p, Path) for p in paths)

    def test_contains_at_least_one_path(self) -> None:
        """Every platform should have at least one search path."""
        paths = get_default_search_paths()
        assert len(paths) >= 1


class TestFindKspInstall:
    """Tests for auto-detecting KSP installation."""

    def test_finds_ksp_in_search_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should find KSP when it exists in one of the search paths."""
        ksp_dir = tmp_path / "KSP_linux"
        ksp_dir.mkdir()
        (ksp_dir / "GameData").mkdir()
        (ksp_dir / "KSP.x86_64").touch()

        monkeypatch.setattr(
            "ksp_mission_control.setup.detector.get_default_search_paths",
            lambda: [ksp_dir],
        )
        result = find_ksp_install()
        assert result is not None
        assert result.path == ksp_dir

    def test_returns_none_when_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "ksp_mission_control.setup.detector.get_default_search_paths",
            lambda: [],
        )
        result = find_ksp_install()
        assert result is None

    def test_returns_ksp_install_info(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ksp_dir = tmp_path / "KSP"
        ksp_dir.mkdir()
        (ksp_dir / "GameData").mkdir()
        (ksp_dir / "KSP.x86_64").touch()

        monkeypatch.setattr(
            "ksp_mission_control.setup.detector.get_default_search_paths",
            lambda: [ksp_dir],
        )
        result = find_ksp_install()
        assert isinstance(result, KspInstallInfo)
        assert result.path == ksp_dir
        assert result.has_krpc is False

    def test_detects_krpc_presence(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        ksp_dir = tmp_path / "KSP"
        ksp_dir.mkdir()
        (ksp_dir / "GameData").mkdir()
        (ksp_dir / "KSP.x86_64").touch()
        krpc_dir = ksp_dir / "GameData" / "kRPC"
        krpc_dir.mkdir()
        (krpc_dir / "kRPC.dll").touch()

        monkeypatch.setattr(
            "ksp_mission_control.setup.detector.get_default_search_paths",
            lambda: [ksp_dir],
        )
        result = find_ksp_install()
        assert result is not None
        assert result.has_krpc is True

    def test_skips_invalid_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should skip directories that aren't valid KSP installs."""
        invalid = tmp_path / "not_ksp"
        invalid.mkdir()

        valid = tmp_path / "ksp"
        valid.mkdir()
        (valid / "GameData").mkdir()
        (valid / "KSP.x86_64").touch()

        monkeypatch.setattr(
            "ksp_mission_control.setup.detector.get_default_search_paths",
            lambda: [invalid, valid],
        )
        result = find_ksp_install()
        assert result is not None
        assert result.path == valid


class TestKspInstallInfo:
    """Tests for the KspInstallInfo dataclass."""

    def test_gamedata_path(self, tmp_path: Path) -> None:
        info = KspInstallInfo(path=tmp_path, has_krpc=False)
        assert info.gamedata_path == tmp_path / "GameData"


class TestSteamAppId:
    """Verify the Steam app ID constant."""

    def test_ksp_steam_app_id(self) -> None:
        assert KSP_STEAM_APP_ID == "220200"
