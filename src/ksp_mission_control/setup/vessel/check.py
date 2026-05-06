from __future__ import annotations

import contextlib
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from ksp_mission_control.config import ConfigManager
from ksp_mission_control.setup.checks import CheckResult, SetupCheck
from ksp_mission_control.setup.kRPC_comms.parser import KrpcServerSettings, resolve_krpc_connection
from ksp_mission_control.setup.vessel.screen import VesselScreen

_KRPC_CALL_TIMEOUT = 10.0
"""Seconds before a kRPC vessel query is considered hung."""


class VesselDetectedCheck(SetupCheck):
    """Verify that KSP has an active vessel via kRPC."""

    check_id = "check-vessel"
    label = "Active vessel detected"
    screen = VesselScreen

    def __init__(self, config_manager: ConfigManager) -> None:
        self._config_manager = config_manager
        self.vessel_name: str | None = None
        """Name of the active vessel from the most recent successful check."""

    def run(self) -> CheckResult:
        # kRPC calls can hang if KSP is frozen. Run in a thread pool with
        # a timeout so the setup screen stays responsive.
        self.vessel_name = None
        settings = resolve_krpc_connection(self._config_manager)
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._query_vessel, settings)
        try:
            result, vessel_name = future.result(timeout=_KRPC_CALL_TIMEOUT)
            self.vessel_name = vessel_name
            return result
        except FutureTimeout:
            return CheckResult(passed=False, message="Vessel query timed out")
        except ConnectionRefusedError:
            return CheckResult(passed=False, message="kRPC server not available")
        except Exception as exc:
            return CheckResult(passed=False, message=f"Failed to query vessel ({exc})")
        finally:
            pool.shutdown(wait=False)  # don't block on a hung thread

    @staticmethod
    def _query_vessel(settings: KrpcServerSettings) -> tuple[CheckResult, str | None]:
        """Connect to kRPC and check for an active vessel (runs in a thread)."""
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
                return CheckResult(passed=False, message="No active vessel"), None
            name = vessel.name
            return CheckResult(passed=True, message=f"Vessel: {name}"), name
        except Exception as exc:
            return CheckResult(passed=False, message=f"No active vessel ({exc})"), None
        finally:
            with contextlib.suppress(Exception):
                conn.close()
