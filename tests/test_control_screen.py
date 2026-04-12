"""Tests for tick history formatting in the control screen."""

from __future__ import annotations

from ksp_mission_control.control.actions.base import (
    ActionStatus,
    LogEntry,
    LogLevel,
    VesselCommands,
)
from ksp_mission_control.control.screen import TickRecord, _format_tick_history


class TestFormatTickHistory:
    """Tests for _format_tick_history plain-text export."""

    def test_idle_tick_with_no_logs_or_commands(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=5.0,
            action_label=None,
            action_status=None,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        assert "Tick #1" in result
        assert "T+00:05.0" in result
        assert "No action" in result
        assert "(idle)" in result

    def test_tick_with_logs_and_sent_commands(self) -> None:
        commands = VesselCommands(throttle=0.75, sas=True)
        tick = TickRecord(
            tick_number=42,
            met=330.5,
            action_label="Hover",
            action_status=ActionStatus.RUNNING,
            logs=[
                LogEntry(level=LogLevel.INFO, message="Holding altitude"),
                LogEntry(level=LogLevel.DEBUG, message="PD output: 0.75"),
            ],
            commands=commands,
            applied_fields=frozenset({"throttle"}),
        )
        result = _format_tick_history([tick])
        assert "Tick #42" in result
        assert "T+05:30.5" in result
        assert "Hover (running)" in result
        assert "--- Logs ---" in result
        assert "INFO  Holding altitude" in result
        assert "DEBUG  PD output: 0.75" in result
        assert "--- Commands (sent) ---" in result
        assert "Throttle: 75%" in result
        assert "--- Commands (redundant) ---" in result
        assert "Sas: ON" in result

    def test_multiple_ticks_separated_by_blank_line(self) -> None:
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            action_label="Hover",
            action_status=ActionStatus.RUNNING,
            logs=[LogEntry(level=LogLevel.INFO, message="Start")],
            commands=VesselCommands(throttle=0.5),
            applied_fields=frozenset({"throttle"}),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            action_label="Hover",
            action_status=ActionStatus.RUNNING,
            logs=[LogEntry(level=LogLevel.INFO, message="Holding")],
            commands=VesselCommands(throttle=0.6),
            applied_fields=frozenset({"throttle"}),
        )
        result = _format_tick_history([tick1, tick2])
        assert "Tick #1" in result
        assert "Tick #2" in result
        # Ticks are separated by a blank line
        assert "\n\n" in result

    def test_tick_with_only_redundant_commands(self) -> None:
        commands = VesselCommands(sas=True, rcs=True)
        tick = TickRecord(
            tick_number=5,
            met=10.0,
            action_label="Land",
            action_status=ActionStatus.RUNNING,
            logs=[],
            commands=commands,
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        assert "--- Commands (sent) ---" not in result
        assert "--- Commands (redundant) ---" in result
        assert "Sas: ON" in result
        assert "Rcs: ON" in result

    def test_tick_with_succeeded_status(self) -> None:
        tick = TickRecord(
            tick_number=100,
            met=600.0,
            action_label="Land",
            action_status=ActionStatus.SUCCEEDED,
            logs=[LogEntry(level=LogLevel.INFO, message="Finished: Land (succeeded)")],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        assert "Land (succeeded)" in result
