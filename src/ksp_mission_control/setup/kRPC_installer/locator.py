"""Detect KSP installation paths across platforms."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

KSP_STEAM_APP_ID = "220200"

# Known KSP executable names per platform.
_KSP_EXECUTABLES = {
    "Linux": ["KSP.x86_64", "KSP.x86"],
    "Darwin": ["KSP.app"],
    "Windows": ["KSP_x64.exe", "KSP.exe"],
}

# All executable names flattened (for cross-platform validation).
_ALL_EXECUTABLES = [name for names in _KSP_EXECUTABLES.values() for name in names]


@dataclass(frozen=True)
class KspInstallInfo:
    """Information about a detected KSP installation."""

    path: Path
    has_krpc: bool

    @property
    def gamedata_path(self) -> Path:
        return self.path / "GameData"


def is_valid_ksp_install(path: Path) -> bool:
    """Check whether *path* looks like a valid KSP installation directory.

    A valid install has a ``GameData/`` sub-directory **and** at least one
    recognised KSP executable (or ``.app`` bundle on macOS).
    """
    if not path.is_dir():
        return False
    if not (path / "GameData").is_dir():
        return False
    return any((path / exe).exists() for exe in _ALL_EXECUTABLES)


def is_krpc_installed(ksp_path: Path) -> bool:
    """Return ``True`` if the kRPC mod is installed inside *ksp_path*."""
    krpc_dll = ksp_path / "GameData" / "kRPC" / "kRPC.dll"
    return krpc_dll.is_file()


def get_default_search_paths() -> list[Path]:
    """Return a list of directories where KSP is commonly installed.

    The list is platform-specific and includes both Steam library locations
    and standalone install paths.
    """
    system = platform.system()
    home = Path.home()
    paths: list[Path] = []

    ksp = "Kerbal Space Program"
    steam_common = "steamapps" / Path("common")

    if system == "Linux":
        paths.extend(
            [
                home / ".steam" / "steam" / steam_common / ksp,
                home / ".local" / "share" / "Steam" / steam_common / ksp,
                home / ".steam" / "debian-installation" / steam_common / ksp,
                Path("/opt/KSP"),
            ]
        )
    elif system == "Darwin":
        paths.extend(
            [
                home / "Library" / "Application Support" / "Steam" / steam_common / ksp,
                Path("/Applications/KSP_osx"),
            ]
        )
    elif system == "Windows":
        paths.extend(
            [
                Path("C:/Program Files (x86)/Steam/steamapps/common/Kerbal Space Program"),
                Path("C:/Program Files/Steam/steamapps/common/Kerbal Space Program"),
                Path("C:/GOG Games/Kerbal Space Program"),
            ]
        )
    else:
        # Unknown platform – nothing to suggest.
        pass

    return paths


def find_ksp_install() -> KspInstallInfo | None:
    """Auto-detect a KSP installation from well-known paths.

    Returns a :class:`KspInstallInfo` for the first valid installation found,
    or ``None`` if none is detected.
    """
    for candidate in get_default_search_paths():
        if is_valid_ksp_install(candidate):
            return KspInstallInfo(
                path=candidate,
                has_krpc=is_krpc_installed(candidate),
            )
    return None
