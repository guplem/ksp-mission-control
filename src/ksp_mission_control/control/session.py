"""Control session - owns the poll loop, kRPC connection, and ActionRunner.

This module has no Textual dependency. The screen bridges session callbacks
to the UI thread via ``app.call_from_thread()``.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from typing import Any

from ksp_mission_control.config import ConfigManager
from ksp_mission_control.control.actions.base import Action, LogEntry, VesselCommands, VesselState
from ksp_mission_control.control.actions.runner import ActionRunner, RunnerSnapshot, StepResult
from ksp_mission_control.control.demo.demo_state import generate_demo_vessel_state
from ksp_mission_control.control.krpc_bridge import (
    NoActiveVesselError,
    apply_controls,
    read_vessel_state,
)
from ksp_mission_control.setup.kRPC_comms.parser import resolve_krpc_connection


class ControlSession:
    """Owns the kRPC connection, poll loop, and ActionRunner.

    Communicates with the UI exclusively through typed callbacks.
    """

    def __init__(
        self,
        *,
        demo: bool,
        on_update: Callable[[VesselState, RunnerSnapshot, VesselCommands, list[LogEntry]], None],
        on_error: Callable[[str], None],
        config_manager: ConfigManager | None = None,
    ) -> None:
        self._demo = demo
        self._on_update = on_update
        self._on_error = on_error
        self._config_manager = config_manager
        self._conn: object | None = None
        self._runner = ActionRunner()
        self._stop_event = threading.Event()
        self._tick: int = 0

    def run_poll_loop(self) -> None:
        """Blocking poll loop for live mode.

        Connects to kRPC, then loops: read -> step -> apply -> callback.
        Returns when ``_stop_event`` is set or connection fails.
        The caller should run this in a ``@work(thread=True)`` worker.
        """
        import krpc  # noqa: PLC0415

        try:
            assert self._config_manager is not None, "config_manager required for live mode"
            settings = resolve_krpc_connection(self._config_manager)
            self._conn = krpc.connect(
                name="KSP-MC Control",
                address=settings.address,
                rpc_port=settings.rpc_port,
                stream_port=settings.stream_port,
            )
            conn = self._conn
        except Exception as exc:
            self._on_error(f"Connection failed: {exc}")
            return

        while not self._stop_event.is_set():
            try:
                vessel_state = read_vessel_state(conn)
                result = self._runner.step(vessel_state, dt=0.5)
                apply_controls(conn, result.commands)
                self._on_update(
                    vessel_state, self._runner.snapshot(), result.commands, result.logs
                )
            except NoActiveVesselError:
                self._on_error("No active vessel found")
            except ConnectionError as exc:
                self._on_error(f"Connection lost: {exc}")
                return
            except Exception as exc:
                self._on_error(f"Error reading data: {exc}")
            self._stop_event.wait(0.5)

    def demo_tick(self) -> None:
        """Execute one demo iteration.

        Generates fake vessel state, steps the runner, and calls on_update.
        Called by the screen's ``set_interval`` timer on the main thread.
        """
        self._tick += 1
        vessel_state = generate_demo_vessel_state(self._tick)
        result = self._runner.step(vessel_state, dt=0.5)
        self._on_update(vessel_state, self._runner.snapshot(), result.commands, result.logs)

    def start_action(self, action: Action, params: dict[str, Any] | None = None) -> None:
        """Begin executing an action. Raises ValueError on invalid params."""
        self._runner.start_action(action, params)

    def abort(self) -> None:
        """Abort the current action and apply cleanup commands if connected."""
        result = self._runner.abort()
        if not self._demo and self._conn is not None:
            with contextlib.suppress(Exception):
                apply_controls(self._conn, result.commands)

    def shutdown(self) -> None:
        """Stop the poll loop, abort any running action, and close the connection."""
        self._stop_event.set()
        if self._runner.snapshot().action_id is not None:
            self.abort()
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.close()  # type: ignore[attr-defined]

    def snapshot(self) -> RunnerSnapshot:
        """Return an immutable snapshot of the current runner state."""
        return self._runner.snapshot()
