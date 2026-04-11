"""Modular system readiness checks for KSP Mission Control setup."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from textual.screen import Screen

from ksp_mission_control.config import ConfigManager

KRPC_DEFAULT_RPC_PORT = 50000
KRPC_DEFAULT_STREAM_PORT = 50001


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single readiness check."""

    passed: bool
    message: str


class SetupCheck(ABC):
    """Base class for a single setup checklist item."""

    check_id: ClassVar[str]
    """Unique identifier used for the widget ID (e.g. 'check-krpc')."""

    label: ClassVar[str]
    """Human-readable label shown in the checklist."""

    screen: ClassVar[type[Screen[object]] | None]
    """The Screen class with help to pass the check, or None if no specific page exists."""

    @abstractmethod
    def run(self) -> CheckResult:
        """Execute the check synchronously and return the result.

        Checks that do I/O (network, filesystem) should be fast and
        use short timeouts so the UI stays responsive.
        """


def get_default_checks(config_manager: ConfigManager) -> list[SetupCheck]:
    """Return the ordered list of setup checks to run."""
    from ksp_mission_control.setup.kRPC_comms.check import KrpcCommsCheck
    from ksp_mission_control.setup.kRPC_installer.check import KrpcInstalledCheck
    from ksp_mission_control.setup.vessel.check import VesselDetectedCheck

    return [
        KrpcInstalledCheck(config_manager=config_manager),
        KrpcCommsCheck(config_manager=config_manager),
        VesselDetectedCheck(config_manager=config_manager),
    ]
