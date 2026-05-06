"""Unified craft install + launch workflow.

Runs synchronously from a worker thread and pushes modal dialogs via
``app.call_from_thread``. The thread blocks on ``threading.Event`` until
each modal is dismissed, so the workflow reads top-to-bottom even though
each step is async on the UI side.

Used by both the setup screen ("Launch from Flight Plan") and the control
screen (loading a plan whose ``@craft`` differs from the current vessel)
so the dialog UX is identical regardless of entry point.
"""

from __future__ import annotations

import contextlib
import threading
import time
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from ksp_mission_control.control.install_craft_dialog import (
    InstallChoice,
    InstallCraftDialog,
)
from ksp_mission_control.control.krpc_bridge import launch_vessel_from_vab
from ksp_mission_control.control.load_vessel_dialog import (
    LoadChoice,
    LoadVesselDialog,
)
from ksp_mission_control.craft import (
    find_active_save_dir,
    install_craft_to_save,
)

if TYPE_CHECKING:
    from textual.app import App
    from textual.screen import ModalScreen

    from ksp_mission_control.setup.kRPC_comms.parser import KrpcServerSettings


class CraftLoadResult(Enum):
    """Outcome of :func:`load_craft_in_ksp`."""

    LAUNCHED = "launched"
    """Craft is installed and the live vessel in KSP is the requested craft."""

    CANCELLED = "cancelled"
    """User dismissed one of the confirmation dialogs."""


_KRPC_LOAD_SETTLE_SECONDS = 5.0
"""Wait time after launch_vessel_from_vab so KSP can load the new scene."""


def load_craft_in_ksp(
    *,
    app: App[object],
    craft_name: str,
    vessels_dir: Path,
    ksp_path: Path,
    krpc_settings: KrpcServerSettings,
) -> CraftLoadResult:
    """Install ``craft_name`` into the active save and load it onto the pad.

    Pushes :class:`InstallCraftDialog` if the file already exists in the
    save's VAB, and :class:`LoadVesselDialog` unconditionally before placing
    the craft on the pad (since kRPC silently recovers anything already
    there). Both dialogs offer Cancel.

    The actual mission launch (engines, plan execution) happens later via
    the pending-plan tray; this function only loads the craft.

    Must be called from a worker thread; the function blocks on each modal
    via ``threading.Event``. Filesystem and kRPC errors propagate to the
    caller; the caller should surface them via ``on_worker_state_changed``.
    """
    save_dir = find_active_save_dir(ksp_path)
    save_craft_path = save_dir / "Ships" / "VAB" / f"{craft_name}.craft"

    if save_craft_path.is_file():
        install_choice = await_modal(app, InstallCraftDialog(craft_name))
        if install_choice == InstallChoice.CANCEL:
            return CraftLoadResult.CANCELLED
        if install_choice == InstallChoice.OVERWRITE:
            install_craft_to_save(vessels_dir, craft_name, save_dir)
        # USE_EXISTING: leave the save's copy untouched.
    else:
        install_craft_to_save(vessels_dir, craft_name, save_dir)

    import krpc  # noqa: PLC0415

    conn = krpc.connect(
        name="KSP-MC Craft Loader",
        address=krpc_settings.address,
        rpc_port=krpc_settings.rpc_port,
        stream_port=krpc_settings.stream_port,
    )
    try:
        load_choice = await_modal(app, LoadVesselDialog(craft_name))
        if load_choice == LoadChoice.CANCEL:
            return CraftLoadResult.CANCELLED
        launch_vessel_from_vab(conn, craft_name)
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    time.sleep(_KRPC_LOAD_SETTLE_SECONDS)
    return CraftLoadResult.LAUNCHED


def await_modal[T: Enum](app: App[object], modal: ModalScreen[T]) -> T:
    """Push *modal* on the UI thread and block this thread until it's dismissed.

    Both dialogs in this workflow always dismiss with a non-None enum value
    (Cancel is an explicit choice), so the assertion below should never fire.
    """
    event = threading.Event()
    captured: list[T | None] = [None]

    def on_dismiss(result: T | None) -> None:
        captured[0] = result
        event.set()

    app.call_from_thread(app.push_screen, modal, on_dismiss)
    event.wait()
    choice = captured[0]
    assert choice is not None, "Dialog dismissed without a choice"
    return choice
