"""Spawn a vessel from a project craft, loading it into KSP first if needed.

Runs synchronously from a worker thread and pushes modal dialogs via
``app.call_from_thread``. The thread blocks on ``threading.Event`` until
each modal is dismissed, so the workflow reads top-to-bottom even though
each step is async on the UI side.

Used by both the setup screen ("Launch from Flight Plan") and the control
screen (loading a plan whose ``@craft`` differs from the current vessel)
so the dialog UX is identical regardless of entry point.

Vocabulary (ADR 0010):

- *load craft*: copy the .craft from the project's ``crafts/`` into KSP's
  ``Ships/VAB/``. Triggers :class:`LoadCraftDialog` if KSP already has a
  copy with that name.
- *spawn vessel*: instantiate the loaded craft as a live vessel on the
  launch pad via ``launch_vessel_from_vab``. Triggers
  :class:`SpawnVesselDialog` unconditionally because the pad recovery
  cannot be detected ahead of time.
"""

from __future__ import annotations

import contextlib
import threading
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from ksp_mission_control.control.krpc_bridge import launch_vessel_from_vab
from ksp_mission_control.control.load_craft_dialog import (
    LoadChoice,
    LoadCraftDialog,
)
from ksp_mission_control.control.spawn_vessel_dialog import (
    SpawnChoice,
    SpawnVesselDialog,
)
from ksp_mission_control.craft import (
    find_active_save_dir,
    load_craft_into_ksp,
)

if TYPE_CHECKING:
    from textual.app import App
    from textual.screen import ModalScreen

    from ksp_mission_control.setup.kRPC_comms.parser import KrpcServerSettings


class SpawnVesselResult(Enum):
    """Outcome of :func:`spawn_vessel_from_craft`."""

    SPAWNED = "spawned"
    """Craft is loaded into KSP and the live vessel on the pad is the requested craft."""

    CANCELLED = "cancelled"
    """User dismissed one of the confirmation dialogs."""


def spawn_vessel_from_craft(
    *,
    app: App[object],
    craft_name: str,
    crafts_dir: Path,
    ksp_path: Path,
    krpc_settings: KrpcServerSettings,
) -> SpawnVesselResult:
    """Load ``craft_name`` into the active save and spawn it as a vessel on the pad.

    Pushes :class:`LoadCraftDialog` if the file is already loaded into the
    save's VAB, and :class:`SpawnVesselDialog` unconditionally before
    spawning the vessel on the pad (since kRPC silently recovers anything
    already there). Both dialogs offer Cancel.

    The actual mission launch (engines, plan execution) happens later via
    the pending-plan tray; this function only spawns the vessel.

    Must be called from a worker thread; the function blocks on each modal
    via ``threading.Event``. Filesystem and kRPC errors propagate to the
    caller; the caller should surface them via ``on_worker_state_changed``.
    """
    save_dir = find_active_save_dir(ksp_path)
    save_craft_path = save_dir / "Ships" / "VAB" / f"{craft_name}.craft"

    if save_craft_path.is_file():
        load_choice = await_modal(app, LoadCraftDialog(craft_name))
        if load_choice == LoadChoice.CANCEL:
            return SpawnVesselResult.CANCELLED
        if load_choice == LoadChoice.OVERWRITE:
            load_craft_into_ksp(crafts_dir, craft_name, save_dir)
        # USE_EXISTING: leave the save's copy untouched.
    else:
        load_craft_into_ksp(crafts_dir, craft_name, save_dir)

    import krpc  # noqa: PLC0415

    conn = krpc.connect(
        name="KSP-MC Vessel Spawner",
        address=krpc_settings.address,
        rpc_port=krpc_settings.rpc_port,
        stream_port=krpc_settings.stream_port,
    )
    try:
        spawn_choice = await_modal(app, SpawnVesselDialog(craft_name))
        if spawn_choice == SpawnChoice.CANCEL:
            return SpawnVesselResult.CANCELLED
        launch_vessel_from_vab(conn, craft_name)
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    return SpawnVesselResult.SPAWNED


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
