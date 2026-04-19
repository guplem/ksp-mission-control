"""Tests for DebugConsoleWidget - log filtering by level."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import RichLog, Switch

from ksp_mission_control.control.actions.base import LogEntry, LogLevel
from ksp_mission_control.control.widgets.debug_console import DebugConsoleWidget, _switch_id


class DebugConsoleApp(App[None]):
    """Minimal app for testing the debug console widget."""

    def compose(self) -> ComposeResult:
        yield DebugConsoleWidget(id="debug-console")


def _log_lines(app: App[None]) -> list[str]:
    """Return the current lines displayed in the RichLog as plain strings."""
    rich_log = app.query_one("#debug-console-log", RichLog)
    return [str(line) for line in rich_log.lines]


def _make_logs(*levels: LogLevel) -> list[LogEntry]:
    return [LogEntry(level=level, message=f"{level.value} msg") for level in levels]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFilterSwitchesExist:
    """Verify that compose produces a Switch per LogLevel, all enabled."""

    @pytest.mark.asyncio
    async def test_one_switch_per_level(self) -> None:
        async with DebugConsoleApp().run_test(size=(120, 40)) as pilot:
            for level in LogLevel:
                switch = pilot.app.query_one(f"#{_switch_id(level)}", Switch)
                assert switch.value is True


class TestAppendLogsRespectFilter:
    """Logs are only written to the RichLog if their level is enabled."""

    @pytest.mark.asyncio
    async def test_all_levels_shown_by_default(self) -> None:
        async with DebugConsoleApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#debug-console", DebugConsoleWidget)
            widget.append_logs(
                _make_logs(LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARN, LogLevel.ERROR),
                met=10.0,
                tick_id=1,
            )
            await pilot.pause()
            lines = _log_lines(pilot.app)
            assert len(lines) == 4

    @pytest.mark.asyncio
    async def test_disabled_level_not_shown(self) -> None:
        async with DebugConsoleApp().run_test(size=(120, 40)) as pilot:
            # Disable DEBUG
            switch = pilot.app.query_one(f"#{_switch_id(LogLevel.DEBUG)}", Switch)
            switch.value = False
            await pilot.pause()

            widget = pilot.app.query_one("#debug-console", DebugConsoleWidget)
            widget.append_logs(
                _make_logs(LogLevel.DEBUG, LogLevel.INFO),
                met=10.0,
                tick_id=1,
            )
            await pilot.pause()
            lines = _log_lines(pilot.app)
            # Only INFO should be visible
            assert len(lines) == 1
            assert "INFO" in lines[0]


class TestToggleRerendersHistory:
    """Toggling a filter re-renders the full log history."""

    @pytest.mark.asyncio
    async def test_toggle_off_hides_existing_entries(self) -> None:
        async with DebugConsoleApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#debug-console", DebugConsoleWidget)
            widget.append_logs(
                _make_logs(LogLevel.DEBUG, LogLevel.INFO),
                met=5.0,
                tick_id=1,
            )
            await pilot.pause()
            assert len(_log_lines(pilot.app)) == 2

            # Disable DEBUG
            switch = pilot.app.query_one(f"#{_switch_id(LogLevel.DEBUG)}", Switch)
            switch.value = False
            await pilot.pause()

            lines = _log_lines(pilot.app)
            assert len(lines) == 1
            assert "INFO" in lines[0]

    @pytest.mark.asyncio
    async def test_toggle_on_restores_entries(self) -> None:
        async with DebugConsoleApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#debug-console", DebugConsoleWidget)

            # Disable WARN, then add logs
            switch = pilot.app.query_one(f"#{_switch_id(LogLevel.WARN)}", Switch)
            switch.value = False
            await pilot.pause()

            widget.append_logs(
                _make_logs(LogLevel.WARN, LogLevel.ERROR),
                met=20.0,
                tick_id=2,
            )
            await pilot.pause()
            assert len(_log_lines(pilot.app)) == 1  # only ERROR

            # Re-enable WARN
            switch.value = True
            await pilot.pause()
            lines = _log_lines(pilot.app)
            assert len(lines) == 2


class TestEmptyLogsIgnored:
    """append_logs with empty list is a no-op."""

    @pytest.mark.asyncio
    async def test_empty_list(self) -> None:
        async with DebugConsoleApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#debug-console", DebugConsoleWidget)
            widget.append_logs([], met=0.0, tick_id=1)
            await pilot.pause()
            assert len(_log_lines(pilot.app)) == 0
