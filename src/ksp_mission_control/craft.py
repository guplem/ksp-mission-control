"""Craft file management utilities.

Handles copying .craft files between the project's ``crafts/`` directory
and KSP's per-save ``Ships/VAB/`` directory.  Pure filesystem operations
-- no kRPC or Textual dependency.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path


class CraftError(Exception):
    """Raised when a craft file operation fails."""


def sanitize_craft_name(name: str) -> str:
    """Convert a KSP craft/vessel name to a sanitized filename stem.

    Lowercase, replace non-alphanumeric characters with hyphens,
    collapse consecutive hyphens, strip leading/trailing hyphens.

    >>> sanitize_craft_name("Fart - 1")
    'fart-1'
    >>> sanitize_craft_name("  My Cool Rocket!! ")
    'my-cool-rocket'
    """
    lowered = name.strip().lower()
    hyphenated = re.sub(r"[^a-z0-9]+", "-", lowered)
    return hyphenated.strip("-")


def find_active_save_dir(ksp_path: Path) -> Path:
    """Return the most recently used KSP save directory.

    Finds the save whose ``persistent.sfs`` was modified most recently,
    which corresponds to the currently active game.
    """
    saves_root = ksp_path / "saves"
    if not saves_root.is_dir():
        raise CraftError(f"KSP saves directory not found: {saves_root}")

    best_dir: Path | None = None
    best_mtime: float = -1.0

    for candidate in saves_root.iterdir():
        sfs = candidate / "persistent.sfs"
        if sfs.is_file():
            mtime = sfs.stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best_dir = candidate

    if best_dir is None:
        raise CraftError(f"No save directories with persistent.sfs found in {saves_root}")
    return best_dir


def find_craft_in_save(save_dir: Path, vessel_name: str) -> Path:
    """Locate a craft file in a save's VAB directory by vessel name.

    KSP stores VAB craft files as ``Ships/VAB/<vessel_name>.craft``
    where the filename matches the in-game vessel name.
    """
    craft_path = save_dir / "Ships" / "VAB" / f"{vessel_name}.craft"
    if not craft_path.is_file():
        raise CraftError(f"Craft file not found: {craft_path}\nThe vessel may have been built in the Space Plane Hangar (SPH) or renamed.")
    return craft_path


def export_craft_to_project(craft_source: Path, crafts_dir: Path) -> Path:
    """Copy a KSP craft file into the project's ``crafts/`` directory.

    The destination filename is the sanitized version of the craft's
    original stem.  Creates ``crafts/`` if it does not exist.

    Returns the destination path.
    """
    sanitized = sanitize_craft_name(craft_source.stem)
    if not sanitized:
        raise CraftError(f"Cannot sanitize craft name: {craft_source.stem!r}")

    crafts_dir.mkdir(parents=True, exist_ok=True)
    dest = crafts_dir / f"{sanitized}.craft"
    shutil.copy2(craft_source, dest)
    return dest


def load_craft_into_ksp(crafts_dir: Path, craft_name: str, save_dir: Path) -> str:
    """Copy a project craft file into a KSP save's VAB directory.

    *craft_name* is the sanitized stem (without ``.craft``).
    Returns the craft name for use with kRPC's ``launch_vessel_from_vab``.
    """
    source = crafts_dir / f"{craft_name}.craft"
    if not source.is_file():
        raise CraftError(f"Craft file not found in project: {source}")

    vab_dir = save_dir / "Ships" / "VAB"
    vab_dir.mkdir(parents=True, exist_ok=True)
    dest = vab_dir / f"{craft_name}.craft"
    shutil.copy2(source, dest)
    return craft_name
