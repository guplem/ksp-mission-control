"""Control session - owns the poll loop, kRPC connection, and PlanExecutor.

This module has no Textual dependency. The screen bridges session callbacks
to the UI thread via ``app.call_from_thread()``.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import fields as dataclass_fields
from typing import Any

from ksp_mission_control.config import ConfigManager
from ksp_mission_control.control.actions.base import (
    Action,
    LogEntry,
    LogLevel,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.flight_plan import FlightPlan
from ksp_mission_control.control.actions.plan_executor import PlanExecutor, PlanSnapshot
from ksp_mission_control.control.actions.runner import RunnerSnapshot, StepResult
from ksp_mission_control.control.krpc_bridge import (
    NoActiveVesselError,
    apply_controls,
    filter_commands,
    read_vessel_state,
)
from ksp_mission_control.setup.kRPC_comms.parser import resolve_krpc_connection

_KRPC_CALL_TIMEOUT = 10.0
"""Seconds before a kRPC call is considered hung."""

_RECONNECT_INTERVAL = 3.0
"""Seconds to wait before retrying after a connection loss."""


def _merge_manual_command(commands: VesselCommands, manual: VesselCommands) -> list[str]:
    """Merge manual command fields into the commands buffer.

    For each non-None field in *manual*, overrides the corresponding field
    in *commands*. Returns the list of field names that were overridden.
    """
    overridden: list[str] = []
    for field in dataclass_fields(manual):
        value = getattr(manual, field.name)
        if value is not None:
            setattr(commands, field.name, value)
            overridden.append(field.name)
    return overridden


class ControlSession:
    """Owns the kRPC connection, poll loop, and PlanExecutor.

    Communicates with the UI exclusively through typed callbacks.
    """

    def __init__(
        self,
        *,
        on_update: Callable[
            [
                State,
                RunnerSnapshot,
                VesselCommands,
                frozenset[str],
                list[LogEntry],
                PlanSnapshot,
            ],
            None,
        ],
        on_error: Callable[[str], None],
        config_manager: ConfigManager,
    ) -> None:
        self._on_update = on_update
        self._on_error = on_error
        self._config_manager = config_manager
        self._conn: object | None = None
        self._executor = PlanExecutor()
        self._stop_event = threading.Event()
        self._last_state: State = State()
        self._pending_manual_command: VesselCommands | None = None

    def run_poll_loop(self) -> None:
        """Blocking poll loop.

        Two nested loops:
        - **Outer loop**: keeps getting fresh kRPC connections (reconnect on failure).
        - **Inner loop**: polls one connection every 0.5s until it dies.

        Errors fall into two categories:
        - *Transient* (keep polling same connection): NoActiveVesselError, generic exceptions.
        - *Connection dead* (break to outer loop, reconnect): FutureTimeout, ConnectionError.

        Returns only when ``_stop_event`` is set.
        The caller should run this in a ``@work(thread=True)`` worker.
        """
        import krpc  # noqa: PLC0415

        settings = resolve_krpc_connection(self._config_manager)

        # Outer loop: each iteration = one connection attempt + poll until it dies
        while not self._stop_event.is_set():
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

            # Inner loop: poll this connection until it breaks.
            # kRPC calls are synchronous and can hang forever if KSP freezes.
            # We run each tick in a thread pool so we can enforce a timeout.
            pool = ThreadPoolExecutor(max_workers=1)
            try:
                while not self._stop_event.is_set():
                    future = pool.submit(self._poll_tick, conn)
                    try:
                        vessel_state, step_result, applied_fields = future.result(
                            timeout=_KRPC_CALL_TIMEOUT,
                        )
                        if not self._stop_event.is_set():
                            self._on_update(
                                vessel_state,
                                self._executor.snapshot().runner,
                                step_result.commands,
                                applied_fields,
                                step_result.logs,
                                self._executor.snapshot(),
                            )
                    # Connection dead: break to outer loop for reconnect
                    except FutureTimeout:
                        if not self._stop_event.is_set():
                            self._on_error("Connection to vessel lost")
                        break
                    except ConnectionError as exc:
                        if not self._stop_event.is_set():
                            self._on_error(f"Connection lost: {exc}")
                        break
                    # Transient: show error but keep polling this connection
                    except NoActiveVesselError:
                        if not self._stop_event.is_set():
                            self._on_error("No active vessel found")
                    except Exception as exc:
                        if not self._stop_event.is_set():
                            self._on_error(f"Error reading data: {exc}")
                    self._stop_event.wait(0.5)
            finally:
                # wait=False: don't block on a hung kRPC thread; just abandon it
                pool.shutdown(wait=False)
                with contextlib.suppress(Exception):
                    conn.close()

            # Connection died or was never established; wait before reconnecting
            self._wait_for_reconnect()

    def _poll_tick(self, conn: object) -> tuple[State, StepResult, frozenset[str]]:
        """Execute one poll iteration: read state, step executor, filter and apply.

        Runs in a thread pool so a hung kRPC call can be timed out.
        Returns the vessel state, step result, and which command fields were
        actually sent (differed from the vessel's current state).

        If a manual command is pending, its fields are merged into the
        action's commands (overriding them) so the manual command flows
        through the same filter → apply → UI pipeline as action commands.
        """
        vessel_state = read_vessel_state(conn)
        self._last_state = vessel_state
        step_result = self._executor.step(vessel_state, dt=0.5)

        # Merge pending manual command into the action's commands
        pending = self._pending_manual_command
        if pending is not None:
            self._pending_manual_command = None
            overridden = _merge_manual_command(step_result.commands, pending)
            if overridden:
                step_result.logs.append(
                    LogEntry(
                        level=LogLevel.INFO,
                        message=f"Manual command: {', '.join(overridden)}",
                    )
                )

        filtered, applied_fields = filter_commands(step_result.commands, vessel_state)
        apply_controls(conn, filtered)
        return vessel_state, step_result, applied_fields

    def start_action(self, action: Action, params: dict[str, Any] | None = None) -> None:
        """Begin executing a single action. Raises ValueError on invalid params."""
        self._executor.start_action(action, self._last_state, params)

    def start_plan(self, plan: FlightPlan) -> None:
        """Begin executing a flight plan. Raises ValueError on invalid plan."""
        self._executor.start_plan(plan, self._last_state)

    def continue_plan(self) -> None:
        """Continue a paused plan (skip failed step). Raises ValueError if not paused."""
        self._executor.continue_plan(self._last_state)

    def abort_plan(self) -> None:
        """Abort a paused plan after failure."""
        result = self._executor.abort_plan()
        if self._conn is not None:
            with contextlib.suppress(Exception):
                apply_controls(self._conn, result.commands)

    def send_manual_command(self, commands: VesselCommands) -> None:
        """Queue a one-shot manual command for the next poll tick.

        The command is merged into the action's commands during the next
        ``_poll_tick``, so it flows through the same filter → apply → UI
        pipeline as action commands (appears in command history, debug
        console, etc.).
        """
        self._pending_manual_command = commands

    def abort(self) -> None:
        """Abort the current action and apply cleanup commands if connected."""
        result = self._executor.abort()
        if self._conn is not None:
            with contextlib.suppress(Exception):
                apply_controls(self._conn, result.commands)

    @property
    def paused_on_failure(self) -> bool:
        """Whether the plan executor is paused waiting for user decision."""
        return self._executor.paused_on_failure

    def _wait_for_reconnect(self) -> None:
        """Wait before retrying. Returns early if shutdown is requested."""
        self._stop_event.wait(_RECONNECT_INTERVAL)

    def shutdown(self) -> None:
        """Stop the poll loop, abort any running action, and close the connection."""
        self._stop_event.set()
        if self._executor.snapshot().runner.action_id is not None:
            self.abort()
        conn = self._conn
        self._conn = None
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()  # type: ignore[attr-defined]

    def snapshot(self) -> RunnerSnapshot:
        """Return an immutable snapshot of the current runner state."""
        return self._executor.snapshot().runner

    def plan_snapshot(self) -> PlanSnapshot:
        """Return an immutable snapshot of the current plan state."""
        return self._executor.snapshot()
