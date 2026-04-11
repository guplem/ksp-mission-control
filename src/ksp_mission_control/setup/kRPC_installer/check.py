from __future__ import annotations

from pathlib import Path

from ksp_mission_control.setup.checks import CheckResult, SetupCheck
from ksp_mission_control.setup.kRPC_installer.detector import (
    find_ksp_install,
    is_krpc_installed,
    is_valid_ksp_install,
)
from ksp_mission_control.setup.kRPC_installer.screen import KrpcSetupScreen


class KrpcInstalledCheck(SetupCheck):
    """Verify that the kRPC mod is installed in a detected KSP installation.

    When *ksp_path* is provided (from stored config), it is checked first.
    Falls back to auto-detection if the stored path is missing or invalid.
    """

    check_id = "check-krpc"
    label = "kRPC installed"
    screen = KrpcSetupScreen

    def __init__(self, ksp_path: str | None = None) -> None:
        self._stored_path = ksp_path

    def run(self) -> CheckResult:
        if self._stored_path is not None:
            path = Path(self._stored_path)
            if is_valid_ksp_install(path):
                if is_krpc_installed(path):
                    return CheckResult(passed=True, message=f"kRPC found at {path}")
                return CheckResult(
                    passed=False,
                    message=f"KSP found at {path}, but kRPC is not installed",
                )

        result = find_ksp_install()
        if result is None:
            return CheckResult(passed=False, message="KSP installation not found")
        if not result.has_krpc:
            return CheckResult(
                passed=False,
                message=f"KSP found at {result.path}, but kRPC is not installed",
            )
        return CheckResult(passed=True, message=f"kRPC found at {result.path}")
