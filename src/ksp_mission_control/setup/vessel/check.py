from __future__ import annotations

from pathlib import Path

from ksp_mission_control.config import ConfigManager
from ksp_mission_control.setup.checks import (
    KRPC_DEFAULT_RPC_PORT,
    KRPC_DEFAULT_STREAM_PORT,
    CheckResult,
    SetupCheck,
)
from ksp_mission_control.setup.kRPC_comms.parser import (
    KrpcSettingsParseError,
    parse_krpc_settings,
)


class VesselDetectedCheck(SetupCheck):
    """Verify that KSP has an active vessel via kRPC."""

    check_id = "check-vessel"
    label = "Active vessel detected"
    screen = None

    def __init__(self, config_manager: ConfigManager) -> None:
        self._config_manager = config_manager

    def run(self) -> CheckResult:
        host, rpc_port, stream_port = self._resolve_connection()
        try:
            import krpc  # noqa: PLC0415 — lazy import to avoid hard dep at module level

            conn = krpc.connect(
                name="KSP-MC Setup Check",
                address=host,
                rpc_port=rpc_port,
                stream_port=stream_port,
            )
            try:
                vessel = conn.space_center.active_vessel
                if vessel is None:
                    return CheckResult(passed=False, message="No active vessel")
                name: str = vessel.name
                return CheckResult(passed=True, message=f"Vessel: {name}")
            except Exception as exc:
                return CheckResult(
                    passed=False,
                    message=f"No active vessel ({exc})",
                )
            finally:
                conn.close()
        except ConnectionRefusedError:
            return CheckResult(
                passed=False,
                message="kRPC server not available",
            )
        except Exception as exc:
            return CheckResult(passed=False, message=f"Failed to query vessel ({exc})")

    def _resolve_connection(self) -> tuple[str, int, int]:
        """Read connection details from kRPC settings, falling back to defaults."""
        stored_path = self._config_manager.config.ksp_path
        if stored_path is not None:
            try:
                settings = parse_krpc_settings(Path(stored_path))
                return settings.address, settings.rpc_port, settings.stream_port
            except KrpcSettingsParseError:
                pass
        return "127.0.0.1", KRPC_DEFAULT_RPC_PORT, KRPC_DEFAULT_STREAM_PORT
