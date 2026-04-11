"""Tests for the modular setup checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

from ksp_mission_control.config import AppConfig, ConfigManager
from ksp_mission_control.setup.checks import get_default_checks
from ksp_mission_control.setup.kRPC_comms.check import KrpcCommsCheck
from ksp_mission_control.setup.kRPC_installer.check import KrpcInstalledCheck
from ksp_mission_control.setup.vessel.check import VesselDetectedCheck


def _mock_config_manager(ksp_path: str | None = None) -> ConfigManager:
    """Create a mock ConfigManager with the given ksp_path."""
    manager = Mock(spec=ConfigManager)
    manager.config = AppConfig(ksp_path=ksp_path)
    return manager


class TestKrpcInstalledCheck:
    """Tests for the kRPC installation filesystem check."""

    def test_fails_when_ksp_not_found(self) -> None:
        with patch(
            "ksp_mission_control.setup.kRPC_installer.check.find_ksp_install",
            return_value=None,
        ):
            result = KrpcInstalledCheck(_mock_config_manager()).run()
        assert result.passed is False
        assert "not found" in result.message

    def test_fails_when_ksp_found_without_krpc(self) -> None:
        info = Mock()
        info.has_krpc = False
        info.path = "/fake/ksp"
        with patch(
            "ksp_mission_control.setup.kRPC_installer.check.find_ksp_install",
            return_value=info,
        ):
            result = KrpcInstalledCheck(_mock_config_manager()).run()
        assert result.passed is False
        assert "not installed" in result.message

    def test_passes_when_krpc_installed(self) -> None:
        info = Mock()
        info.has_krpc = True
        info.path = "/fake/ksp"
        with patch(
            "ksp_mission_control.setup.kRPC_installer.check.find_ksp_install",
            return_value=info,
        ):
            result = KrpcInstalledCheck(_mock_config_manager()).run()
        assert result.passed is True

    def test_stored_path_with_krpc_passes(self, tmp_path: Path) -> None:
        """When a stored path points to a valid KSP install with kRPC, pass immediately."""
        (tmp_path / "GameData" / "kRPC").mkdir(parents=True)
        (tmp_path / "GameData" / "kRPC" / "kRPC.dll").touch()
        (tmp_path / "KSP_x64.exe").touch()

        check = KrpcInstalledCheck(_mock_config_manager(ksp_path=str(tmp_path)))
        result = check.run()
        assert result.passed is True
        assert str(tmp_path) in result.message

    def test_stored_path_valid_but_no_krpc(self, tmp_path: Path) -> None:
        """Stored path is valid KSP but kRPC not installed."""
        (tmp_path / "GameData").mkdir()
        (tmp_path / "KSP_x64.exe").touch()

        check = KrpcInstalledCheck(_mock_config_manager(ksp_path=str(tmp_path)))
        result = check.run()
        assert result.passed is False
        assert "not installed" in result.message

    def test_stored_path_invalid_falls_back_to_autodetect(self) -> None:
        """Invalid stored path falls through to auto-detect."""
        info = Mock()
        info.has_krpc = True
        info.path = "/auto/detected"
        with patch(
            "ksp_mission_control.setup.kRPC_installer.check.find_ksp_install",
            return_value=info,
        ):
            check = KrpcInstalledCheck(_mock_config_manager(ksp_path="/nonexistent/path"))
            result = check.run()
        assert result.passed is True
        assert "/auto/detected" in result.message

    def test_no_stored_path_uses_autodetect(self) -> None:
        """Without a stored path, behaves as before (auto-detect)."""
        with patch(
            "ksp_mission_control.setup.kRPC_installer.check.find_ksp_install",
            return_value=None,
        ):
            check = KrpcInstalledCheck(_mock_config_manager())
            result = check.run()
        assert result.passed is False

    def test_reads_ksp_path_fresh_on_each_run(self, tmp_path: Path) -> None:
        """Config changes between runs are picked up without re-creating the check."""
        (tmp_path / "GameData" / "kRPC").mkdir(parents=True)
        (tmp_path / "GameData" / "kRPC" / "kRPC.dll").touch()
        (tmp_path / "KSP_x64.exe").touch()

        manager = _mock_config_manager()
        check = KrpcInstalledCheck(manager)

        # First run: no ksp_path, auto-detect finds nothing
        with patch(
            "ksp_mission_control.setup.kRPC_installer.check.find_ksp_install",
            return_value=None,
        ):
            result = check.run()
        assert result.passed is False

        # User sets ksp_path via setup screen
        manager.config = AppConfig(ksp_path=str(tmp_path))

        # Second run: picks up the new path without re-creating the check
        result = check.run()
        assert result.passed is True
        assert str(tmp_path) in result.message


class TestKrpcCommsCheck:
    """Tests for the kRPC server reachability check."""

    def test_fails_when_server_unreachable(self) -> None:
        # Use a port that's almost certainly not listening
        check = KrpcCommsCheck(host="127.0.0.1", port=19999, timeout=0.1)
        result = check.run()
        assert result.passed is False
        assert "Cannot reach" in result.message

    def test_passes_when_connection_succeeds(self) -> None:
        mock_socket = Mock()
        mock_socket.__enter__ = Mock(return_value=mock_socket)
        mock_socket.__exit__ = Mock(return_value=False)
        with patch(
            "ksp_mission_control.setup.kRPC_comms.check.socket.create_connection",
            return_value=mock_socket,
        ):
            result = KrpcCommsCheck().run()
        assert result.passed is True
        assert "Connected" in result.message


class TestVesselDetectedCheck:
    """Tests for the active vessel kRPC check."""

    def test_fails_when_connection_refused(self) -> None:
        mock_krpc = Mock()
        mock_krpc.connect.side_effect = ConnectionRefusedError
        with patch.dict("sys.modules", {"krpc": mock_krpc}):
            result = VesselDetectedCheck().run()
        assert result.passed is False

    def test_fails_when_no_active_vessel(self) -> None:
        mock_conn = Mock()
        type(mock_conn.space_center).active_vessel = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("no vessel"))
        )
        mock_krpc = Mock()
        mock_krpc.connect.return_value = mock_conn
        with patch.dict("sys.modules", {"krpc": mock_krpc}):
            result = VesselDetectedCheck().run()
        assert result.passed is False

    def test_passes_when_vessel_found(self) -> None:
        mock_conn = Mock()
        mock_conn.space_center.active_vessel.name = "Kerbal X"
        mock_krpc = Mock()
        mock_krpc.connect.return_value = mock_conn
        with patch.dict("sys.modules", {"krpc": mock_krpc}):
            result = VesselDetectedCheck().run()
        assert result.passed is True
        assert "Kerbal X" in result.message


class TestGetDefaultChecks:
    """Test the default check list factory."""

    def test_returns_three_checks(self) -> None:
        checks = get_default_checks(_mock_config_manager())
        assert len(checks) == 3

    def test_check_ids_are_unique(self) -> None:
        checks = get_default_checks(_mock_config_manager())
        ids = [c.check_id for c in checks]
        assert len(ids) == len(set(ids))

    def test_check_order(self) -> None:
        checks = get_default_checks(_mock_config_manager())
        assert checks[0].check_id == "check-krpc"
        assert checks[1].check_id == "check-comms"
        assert checks[2].check_id == "check-vessel"

    def test_passes_config_manager_to_krpc_check(self) -> None:
        manager = _mock_config_manager(ksp_path="/stored/ksp")
        checks = get_default_checks(manager)
        krpc_check = checks[0]
        assert isinstance(krpc_check, KrpcInstalledCheck)
        assert krpc_check._config_manager is manager  # noqa: SLF001
