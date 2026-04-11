"""Modular system readiness checks for KSP Mission Control setup."""

from __future__ import annotations

import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ksp_mission_control.setup.detector import (
    find_ksp_install,
    is_krpc_installed,
    is_valid_ksp_install,
)

KRPC_DEFAULT_RPC_PORT = 50000
KRPC_DEFAULT_STREAM_PORT = 50001


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single readiness check."""

    passed: bool
    message: str


class SetupCheck(ABC):
    """Base class for a single setup checklist item."""

    @property
    @abstractmethod
    def check_id(self) -> str:
        """Unique identifier used for the widget ID (e.g. 'check-krpc')."""

    @property
    @abstractmethod
    def label(self) -> str:
        """Human-readable label shown in the checklist."""

    @abstractmethod
    def run(self) -> CheckResult:
        """Execute the check synchronously and return the result.

        Checks that do I/O (network, filesystem) should be fast and
        use short timeouts so the UI stays responsive.
        """


class KrpcInstalledCheck(SetupCheck):
    """Verify that the kRPC mod is installed in a detected KSP installation.

    When *ksp_path* is provided (from stored config), it is checked first.
    Falls back to auto-detection if the stored path is missing or invalid.
    """

    def __init__(self, ksp_path: str | None = None) -> None:
        self._stored_path = ksp_path

    @property
    def check_id(self) -> str:
        return "check-krpc"

    @property
    def label(self) -> str:
        return "kRPC installed"

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


class KrpcCommsCheck(SetupCheck):
    """Verify that the kRPC server is reachable on its RPC port."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = KRPC_DEFAULT_RPC_PORT,
        timeout: float = 2.0,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

    @property
    def check_id(self) -> str:
        return "check-comms"

    @property
    def label(self) -> str:
        return "kRPC server reachable"

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


class VesselDetectedCheck(SetupCheck):
    """Verify that KSP has an active vessel via kRPC."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        rpc_port: int = KRPC_DEFAULT_RPC_PORT,
        stream_port: int = KRPC_DEFAULT_STREAM_PORT,
    ) -> None:
        self._host = host
        self._rpc_port = rpc_port
        self._stream_port = stream_port

    @property
    def check_id(self) -> str:
        return "check-vessel"

    @property
    def label(self) -> str:
        return "Active vessel detected"

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


def get_default_checks(ksp_path: str | None = None) -> list[SetupCheck]:
    """Return the ordered list of setup checks to run."""
    return [
        KrpcInstalledCheck(ksp_path=ksp_path),
        KrpcCommsCheck(),
        VesselDetectedCheck(),
    ]
