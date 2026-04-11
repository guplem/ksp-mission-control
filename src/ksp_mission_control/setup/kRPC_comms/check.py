from __future__ import annotations

import socket

from ksp_mission_control.setup.checks import (
    KRPC_DEFAULT_RPC_PORT,
    CheckResult,
    SetupCheck,
)
from ksp_mission_control.setup.kRPC_comms.screen import KrpcCommsScreen


class KrpcCommsCheck(SetupCheck):
    """Verify that the kRPC server is reachable on its RPC port."""

    check_id = "check-comms"
    label = "kRPC server reachable"
    screen = KrpcCommsScreen

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = KRPC_DEFAULT_RPC_PORT,
        timeout: float = 2.0,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

    def run(self) -> CheckResult:
        try:
            with socket.create_connection((self._host, self._port), timeout=self._timeout):
                return CheckResult(
                    passed=True,
                    message=f"Connected to kRPC at {self._host}:{self._port}",
                )
        except OSError as exc:
            return CheckResult(
                passed=False,
                message=f"Cannot reach kRPC at {self._host}:{self._port} ({exc})",
            )
