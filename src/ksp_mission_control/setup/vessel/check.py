from __future__ import annotations

from ksp_mission_control.config import ConfigManager
from ksp_mission_control.setup.checks import CheckResult, SetupCheck
from ksp_mission_control.setup.kRPC_comms.parser import resolve_krpc_connection
from ksp_mission_control.setup.vessel.screen import VesselScreen


class VesselDetectedCheck(SetupCheck):
    """Verify that KSP has an active vessel via kRPC."""

    check_id = "check-vessel"
    label = "Active vessel detected"
    screen = VesselScreen

    def __init__(self, config_manager: ConfigManager) -> None:
        self._config_manager = config_manager

    def run(self) -> CheckResult:
        settings = resolve_krpc_connection(self._config_manager)
        try:
            import krpc  # noqa: PLC0415

            conn = krpc.connect(
                name="KSP-MC Setup Check",
                address=settings.address,
                rpc_port=settings.rpc_port,
                stream_port=settings.stream_port,
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
                    message=f"No active vessel)\n{exc}",
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
