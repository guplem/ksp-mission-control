"""Control session - owns the poll loop, kRPC connection, and ActionRunner.

This module has no Textual dependency. The screen bridges session callbacks
to the UI thread via ``app.call_from_thread()``.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
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

_KRPC_CALL_TIMEOUT = 10.0
"""Seconds before a kRPC call is considered hung."""

_RECONNECT_INTERVAL = 3.0
"""Seconds to wait before retrying after a connection loss."""


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
        self._retry_event = threading.Event()
        self._tick: int = 0

    def run_poll_loop(self) -> None:
        """Blocking poll loop for live mode.

        Connects to kRPC, then loops: read -> step -> apply -> callback.
        On connection loss or timeout, automatically reconnects after a delay.
        Returns only when ``_stop_event`` is set.
        The caller should run this in a ``@work(thread=True)`` worker.
        """
        import krpc  # noqa: PLC0415

        assert self._config_manager is not None, "config_manager required for live mode"
        settings = resolve_krpc_connection(self._config_manager)

        while not self._stop_event.is_set():
            # --- connect (or reconnect) ---
            try:
                self._conn = krpc.connect(
                    name="KSP-MC Control",
                    address=settings.address,
                    rpc_port=settings.rpc_port,
                    stream_port=settings.stream_port,
                )
                conn = self._conn
            except Exception as exc:
                if not self._stop_event.is_set():
                    self._on_error(f"Connection failed: {exc}")
                self._wait_for_reconnect()
                continue

            # --- poll with this connection ---
            pool = ThreadPoolExecutor(max_workers=1)
            try:
                while not self._stop_event.is_set():
                    future = pool.submit(self._poll_tick, conn)
                    try:
                        vessel_state, step_result = future.result(
                            timeout=_KRPC_CALL_TIMEOUT,
                        )
                        if not self._stop_event.is_set():
                            self._on_update(
                                vessel_state,
                                self._runner.snapshot(),
                                step_result.commands,
                                step_result.logs,
                            )
                    except FutureTimeout:
                        if not self._stop_event.is_set():
                            self._on_error("Connection to vessel lost")
                        break
                    except NoActiveVesselError:
                        if not self._stop_event.is_set():
                            self._on_error("No active vessel found")
                    except ConnectionError as exc:
                        if not self._stop_event.is_set():
                            self._on_error(f"Connection lost: {exc}")
                        break
                    except Exception as exc:
                        if not self._stop_event.is_set():
                            self._on_error(f"Error reading data: {exc}")
                    self._stop_event.wait(0.5)
            finally:
                pool.shutdown(wait=False)
                with contextlib.suppress(Exception):
                    conn.close()

            # --- wait before reconnecting ---
            self._wait_for_reconnect()

    def _poll_tick(self, conn: object) -> tuple[VesselState, StepResult]:
        """Execute one poll iteration: read state, step runner, apply controls.

        Runs in a thread pool so a hung kRPC call can be timed out.
        """
        vessel_state = read_vessel_state(conn)
        step_result = self._runner.step(vessel_state, dt=0.5)
        apply_controls(conn, step_result.commands)
        return vessel_state, step_result

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

    def _wait_for_reconnect(self) -> None:
        """Wait for the reconnect interval, or until retry/stop is requested."""
        self._retry_event.clear()
        self._retry_event.wait(_RECONNECT_INTERVAL)
        if not self._stop_event.is_set():
            self._retry_event.clear()

    def retry_now(self) -> None:
        """Interrupt the reconnect delay so the next attempt happens immediately."""
        self._retry_event.set()

    def shutdown(self) -> None:
        """Stop the poll loop, abort any running action, and close the connection."""
        self._stop_event.set()
        self._retry_event.set()
        if self._runner.snapshot().action_id is not None:
            self.abort()
        conn = self._conn
        self._conn = None
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()  # type: ignore[attr-defined]

    def snapshot(self) -> RunnerSnapshot:
        """Return an immutable snapshot of the current runner state."""
        return self._runner.snapshot()
