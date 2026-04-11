from __future__ import annotations

import socket
from pathlib import Path

from ksp_mission_control.config import ConfigManager
from ksp_mission_control.setup.checks import (
    KRPC_DEFAULT_RPC_PORT,
    CheckResult,
    SetupCheck,
)
from ksp_mission_control.setup.kRPC_comms.parser import (
    KrpcSettingsParseError,
    parse_krpc_settings,
)
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
        host, port = self._resolve_connection()
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

    def _resolve_connection(self) -> tuple[str, int]:
        """Read address and RPC port from kRPC settings, falling back to defaults."""
        stored_path = self._config_manager.config.ksp_path
        if stored_path is not None:
            try:
                settings = parse_krpc_settings(Path(stored_path))
                return settings.address, settings.rpc_port
            except KrpcSettingsParseError:
                pass
        return "127.0.0.1", KRPC_DEFAULT_RPC_PORT
