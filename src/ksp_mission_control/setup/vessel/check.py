from __future__ import annotations

import contextlib
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

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

    def run(self) -> CheckResult:
        settings = resolve_krpc_connection(self._config_manager)
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._query_vessel, settings)
        try:
            return future.result(timeout=_KRPC_CALL_TIMEOUT)
        except FutureTimeout:
            return CheckResult(passed=False, message="Vessel query timed out")
        except ConnectionRefusedError:
            return CheckResult(passed=False, message="kRPC server not available")
        except Exception as exc:
            return CheckResult(passed=False, message=f"Failed to query vessel ({exc})")
        finally:
            pool.shutdown(wait=False)

    @staticmethod
    def _query_vessel(settings: KrpcServerSettings) -> CheckResult:
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
                return CheckResult(passed=False, message="No active vessel")
            return CheckResult(passed=True, message=f"Vessel: {vessel.name}")
        except Exception as exc:
            return CheckResult(passed=False, message=f"No active vessel ({exc})")
        finally:
            with contextlib.suppress(Exception):
                conn.close()
