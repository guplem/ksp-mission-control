"""Tests for tick history formatting in the control screen."""

from __future__ import annotations

from xml.etree.ElementTree import fromstring

from ksp_mission_control.control.actions.base import (
    ActionStatus,
    LogEntry,
    LogLevel,
    VesselCommands,
    VesselState,
)
from ksp_mission_control.control.screen import _format_tick_history
from ksp_mission_control.control.tick_record import TickRecord

_DEFAULT_STATE = VesselState()


class TestFormatTickHistory:
    """Tests for _format_tick_history XML export."""

    def test_idle_tick_with_no_logs_or_commands(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=5.0,
            state=_DEFAULT_STATE,
            action_label=None,
            action_status=None,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        tick_el = root.find("tick")
        assert tick_el is not None
        assert tick_el.get("number") == "1"
        assert tick_el.get("met") == "T+00:05.0"
        assert tick_el.get("action") == "No action"
        assert tick_el.find("idle") is not None

    def test_tick_includes_vessel_state(self) -> None:
        state = VesselState(
            altitude_surface=150.3,
            speed_vertical=-2.5,
            control_throttle=0.65,
            control_sas=True,
        )
        tick = TickRecord(
            tick_number=1,
            met=10.0,
            state=state,
            action_label="Hover",
            action_status=ActionStatus.RUNNING,
            logs=[],
            commands=VesselCommands(throttle=0.7),
            applied_fields=frozenset({"throttle"}),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        state_el = root.find("tick/state")
        assert state_el is not None
        assert state_el.findtext("altitude_surface") == "150.3000"
        assert state_el.findtext("speed_vertical") == "-2.5000"
        assert state_el.findtext("control_throttle") == "0.6500"
        assert state_el.findtext("control_sas") == "True"

    def test_tick_with_logs_and_sent_commands(self) -> None:
        commands = VesselCommands(throttle=0.75, sas=True)
        tick = TickRecord(
            tick_number=42,
            met=330.5,
            state=_DEFAULT_STATE,
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
        root = fromstring(result)
        tick_el = root.find("tick")
        assert tick_el is not None
        assert tick_el.get("met") == "T+05:30.5"
        assert tick_el.get("action") == "Hover (running)"

        # Logs
        logs = tick_el.findall("logs/log")
        assert len(logs) == 2
        assert logs[0].get("level") == "INFO"
        assert logs[0].text == "Holding altitude"
        assert logs[1].get("level") == "DEBUG"
        assert logs[1].text == "PD output: 0.75"

        # Sent commands
        sent = tick_el.find("commands[@type='sent']")
        assert sent is not None
        assert sent.findtext("throttle") == "75%"

        # Redundant commands
        redundant = tick_el.find("commands[@type='redundant']")
        assert redundant is not None
        assert redundant.findtext("sas") == "ON"

    def test_multiple_ticks(self) -> None:
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=_DEFAULT_STATE,
            action_label="Hover",
            action_status=ActionStatus.RUNNING,
            logs=[LogEntry(level=LogLevel.INFO, message="Start")],
            commands=VesselCommands(throttle=0.5),
            applied_fields=frozenset({"throttle"}),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=_DEFAULT_STATE,
            action_label="Hover",
            action_status=ActionStatus.RUNNING,
            logs=[LogEntry(level=LogLevel.INFO, message="Holding")],
            commands=VesselCommands(throttle=0.6),
            applied_fields=frozenset({"throttle"}),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        ticks = root.findall("tick")
        assert len(ticks) == 2
        assert ticks[0].get("number") == "1"
        assert ticks[1].get("number") == "2"

    def test_tick_with_only_redundant_commands(self) -> None:
        commands = VesselCommands(sas=True, rcs=True)
        tick = TickRecord(
            tick_number=5,
            met=10.0,
            state=_DEFAULT_STATE,
            action_label="Land",
            action_status=ActionStatus.RUNNING,
            logs=[],
            commands=commands,
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        tick_el = root.find("tick")
        assert tick_el is not None
        assert tick_el.find("commands[@type='sent']") is None
        redundant = tick_el.find("commands[@type='redundant']")
        assert redundant is not None
        assert redundant.findtext("sas") == "ON"
        assert redundant.findtext("rcs") == "ON"

    def test_tick_with_succeeded_status(self) -> None:
        tick = TickRecord(
            tick_number=100,
            met=600.0,
            state=_DEFAULT_STATE,
            action_label="Land",
            action_status=ActionStatus.SUCCEEDED,
            logs=[LogEntry(level=LogLevel.INFO, message="\u25c0 Finished: Land (succeeded)")],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        tick_el = root.find("tick")
        assert tick_el is not None
        assert tick_el.get("action") == "Land (succeeded)"

    def test_state_section_appears_before_logs(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=5.0,
            state=_DEFAULT_STATE,
            action_label="Hover",
            action_status=ActionStatus.RUNNING,
            logs=[LogEntry(level=LogLevel.INFO, message="test")],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        tick_el = root.find("tick")
        assert tick_el is not None
        children = list(tick_el)
        tag_names = [child.tag for child in children]
        assert tag_names.index("state") < tag_names.index("logs")

    def test_state_delta_compression_omits_unchanged_fields(self) -> None:
        state1 = VesselState(altitude_surface=100.0, speed_vertical=-1.0, control_throttle=0.5)
        state2 = VesselState(altitude_surface=95.0, speed_vertical=-1.0, control_throttle=0.5)
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=state1,
            action_label="Hover",
            action_status=ActionStatus.RUNNING,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=state2,
            action_label="Hover",
            action_status=ActionStatus.RUNNING,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        ticks = root.findall("tick")

        # First tick includes all fields (no previous state)
        state1_el = ticks[0].find("state")
        assert state1_el is not None
        assert state1_el.findtext("altitude_surface") == "100.0000"
        assert state1_el.findtext("speed_vertical") == "-1.0000"
        assert state1_el.findtext("control_throttle") == "0.5000"

        # Second tick only includes altitude_surface (the only changed field)
        state2_el = ticks[1].find("state")
        assert state2_el is not None
        assert state2_el.findtext("altitude_surface") == "95.0000"
        assert state2_el.findtext("speed_vertical") is None
        assert state2_el.findtext("control_throttle") is None

    def test_state_omitted_entirely_when_nothing_changed(self) -> None:
        state = VesselState(altitude_surface=100.0)
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=state,
            action_label="Hover",
            action_status=ActionStatus.RUNNING,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=state,
            action_label="Hover",
            action_status=ActionStatus.RUNNING,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        ticks = root.findall("tick")

        # First tick has state
        assert ticks[0].find("state") is not None
        # Second tick has no state at all (identical to first)
        assert ticks[1].find("state") is None

    def test_output_is_valid_xml_with_declaration(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=0.0,
            state=_DEFAULT_STATE,
            action_label=None,
            action_status=None,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        assert result.startswith("<?xml")
        # Should parse without error
        fromstring(result)
