from __future__ import annotations

from ksp_mission_control.setup.checks import (
    KRPC_DEFAULT_RPC_PORT,
    KRPC_DEFAULT_STREAM_PORT,
    CheckResult,
    SetupCheck,
)


class VesselDetectedCheck(SetupCheck):
    """Verify that KSP has an active vessel via kRPC."""

    check_id = "check-vessel"
    label = "Active vessel detected"
    screen = None

    def __init__(
        self,
        host: str = "127.0.0.1",
        rpc_port: int = KRPC_DEFAULT_RPC_PORT,
        stream_port: int = KRPC_DEFAULT_STREAM_PORT,
    ) -> None:
        self._host = host
        self._rpc_port = rpc_port
        self._stream_port = stream_port

    def run(self) -> CheckResult:
        try:
            import krpc  # noqa: PLC0415 — lazy import to avoid hard dep at module level

            conn = krpc.connect(
                name="KSP-MC Setup Check",
                address=self._host,
                rpc_port=self._rpc_port,
                stream_port=self._stream_port,
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
