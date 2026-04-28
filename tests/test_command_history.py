"""Tests for CommandHistoryWidget - action result message display."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from ksp_mission_control.control.actions.base import ActionStatus, VesselCommands
from ksp_mission_control.control.widgets.command_history import CommandHistoryWidget


class CommandHistoryApp(App[None]):
    """Minimal app for testing the command history widget."""

    def compose(self) -> ComposeResult:
        yield CommandHistoryWidget(id="command-history")


def _record(
    widget: CommandHistoryWidget,
    *,
    tick_id: int = 1,
    throttle: float = 0.5,
    message: str = "",
    status: ActionStatus | None = ActionStatus.RUNNING,
) -> None:
    """Helper to record a command with a throttle value."""
    commands = VesselCommands(throttle=throttle)
    widget.record_commands(
        commands,
        applied_fields=frozenset({"throttle"}),
        action_label="Launch",
        met=10.0,
        tick_id=tick_id,
        status=status,
        message=message,
    )


class TestIdleTickSkip:
    """Idle ticks (no commands set) must not create command history entries."""

    @pytest.mark.asyncio
    async def test_default_commands_skipped(self) -> None:
        """A default VesselCommands() (all None / empty tuple) is idle."""
        async with CommandHistoryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#command-history", CommandHistoryWidget)
            widget.record_commands(
                VesselCommands(),
                applied_fields=frozenset(),
                action_label=None,
                met=0.0,
                tick_id=1,
            )
            await pilot.pause()
            assert len(widget._history) == 0

    @pytest.mark.asyncio
    async def test_empty_tuple_science_commands_skipped(self) -> None:
        """science_commands=() should not count as a real command."""
        async with CommandHistoryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#command-history", CommandHistoryWidget)
            commands = VesselCommands()
            assert commands.science_commands == ()
            widget.record_commands(
                commands,
                applied_fields=frozenset(),
                action_label=None,
                met=0.0,
                tick_id=1,
            )
            await pilot.pause()
            assert len(widget._history) == 0

    @pytest.mark.asyncio
    async def test_real_command_recorded(self) -> None:
        """A VesselCommands with a non-None field is recorded."""
        async with CommandHistoryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#command-history", CommandHistoryWidget)
            widget.record_commands(
                VesselCommands(throttle=1.0),
                applied_fields=frozenset({"throttle"}),
                action_label="Test",
                met=0.0,
                tick_id=1,
            )
            await pilot.pause()
            assert len(widget._history) == 1


class TestMessageDisplay:
    """Action result message is shown in the command history widget."""

    @pytest.mark.asyncio
    async def test_message_displayed_when_present(self) -> None:
        async with CommandHistoryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#command-history", CommandHistoryWidget)
            _record(widget, message="Target apoapsis reached")
            await pilot.pause()
            message_static = pilot.app.query_one("#command-history-message", Static)
            assert "Target apoapsis reached" in message_static.render().plain

    @pytest.mark.asyncio
    async def test_message_hidden_when_empty(self) -> None:
        async with CommandHistoryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#command-history", CommandHistoryWidget)
            _record(widget, message="")
            await pilot.pause()
            message_static = pilot.app.query_one("#command-history-message", Static)
            assert message_static.render().plain.strip() == ""

    @pytest.mark.asyncio
    async def test_message_updates_on_navigation(self) -> None:
        async with CommandHistoryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#command-history", CommandHistoryWidget)
            _record(widget, tick_id=1, message="Ascending")
            _record(widget, tick_id=2, message="Target apoapsis reached")
            await pilot.pause()
            # Currently viewing tick 2 (following mode)
            message_static = pilot.app.query_one("#command-history-message", Static)
            assert "Target apoapsis reached" in message_static.render().plain
            # Navigate back to tick 1
            widget._navigate(-1)
            await pilot.pause()
            assert "Ascending" in message_static.render().plain
