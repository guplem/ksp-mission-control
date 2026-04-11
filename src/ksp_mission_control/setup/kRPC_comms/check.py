from __future__ import annotations

import socket

from ksp_mission_control.config import ConfigManager
from ksp_mission_control.setup.checks import CheckResult, SetupCheck
from ksp_mission_control.setup.kRPC_comms.parser import resolve_krpc_connection
from ksp_mission_control.setup.kRPC_comms.screen import KrpcCommsScreen


class KrpcCommsCheck(SetupCheck):
    """Verify that the kRPC server is reachable on its RPC port."""

    check_id = "check-comms"
    label = "kRPC server reachable"
    screen = KrpcCommsScreen

    def __init__(
        self,
        config_manager: ConfigManager,
        timeout: float = 2.0,
    ) -> None:
        self._config_manager = config_manager
        self._timeout = timeout

    def run(self) -> CheckResult:
        settings = resolve_krpc_connection(self._config_manager)
        host, port = settings.address, settings.rpc_port
        try:
            with socket.create_connection((host, port), timeout=self._timeout):
                return CheckResult(
                    passed=True,
                    message=f"Connected to kRPC at {host}:{port}",
                )
        except OSError as exc:
            return CheckResult(
                passed=False,
                message=f"Cannot reach kRPC at {host}:{port} ({exc})",
            )
