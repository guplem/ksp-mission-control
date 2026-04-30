"""Tests for LogRegistryWidget - log filtering, tick grouping, and click selection."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import ListView, Static, Switch

from ksp_mission_control.control.actions.base import LogEntry, LogLevel
from ksp_mission_control.control.widgets.log_registry import LogRegistryWidget, _switch_id


class LogRegistryApp(App[None]):
    """Minimal app for testing the log registry widget."""

    def compose(self) -> ComposeResult:
        yield LogRegistryWidget(id="log-registry")


def _item_count(app: App[None]) -> int:
    """Return the number of ListItems (tick groups) in the log."""
    list_view = app.query_one("#log-registry-log", ListView)
    return len(list_view.children)


def _item_text(app: App[None], index: int) -> str:
    """Return the rendered text of the ListItem at the given index."""
    list_view = app.query_one("#log-registry-log", ListView)
    return str(list_view.children[index].query_one(Static).render())


def _make_logs(*levels: LogLevel) -> list[LogEntry]:
    return [LogEntry(level=level, message=f"{level.value} msg") for level in levels]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFilterSwitchesExist:
    """Verify that compose produces a Switch per LogLevel, all enabled."""

    @pytest.mark.asyncio
    async def test_one_switch_per_level(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            for level in LogLevel:
                switch = pilot.app.query_one(f"#{_switch_id(level)}", Switch)
                assert switch.value is True


class TestTickGrouping:
    """Logs from the same tick are grouped into a single ListItem."""

    @pytest.mark.asyncio
    async def test_same_tick_produces_one_item(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)
            widget.append_logs(
                _make_logs(LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARN, LogLevel.ERROR),
                met=10.0,
                tick_id=1,
            )
            await pilot.pause()
            assert _item_count(pilot.app) == 1
            text = _item_text(pilot.app, 0)
            assert "DEBUG" in text
            assert "ERROR" in text

    @pytest.mark.asyncio
    async def test_different_ticks_produce_separate_items(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)
            widget.append_logs(_make_logs(LogLevel.INFO), met=1.0, tick_id=1)
            widget.append_logs(_make_logs(LogLevel.WARN), met=2.0, tick_id=2)
            await pilot.pause()
            assert _item_count(pilot.app) == 2

    @pytest.mark.asyncio
    async def test_second_append_same_tick_updates_existing_item(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)
            widget.append_logs(_make_logs(LogLevel.INFO), met=5.0, tick_id=3)
            widget.append_logs(_make_logs(LogLevel.ERROR), met=5.0, tick_id=3)
            await pilot.pause()
            assert _item_count(pilot.app) == 1
            text = _item_text(pilot.app, 0)
            assert "INFO" in text
            assert "ERROR" in text


class TestAppendLogsRespectFilter:
    """Logs are only shown if their level is enabled."""

    @pytest.mark.asyncio
    async def test_all_levels_shown_by_default(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)
            widget.append_logs(
                _make_logs(LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARN, LogLevel.ERROR),
                met=10.0,
                tick_id=1,
            )
            await pilot.pause()
            assert _item_count(pilot.app) == 1
            text = _item_text(pilot.app, 0)
            for level in LogLevel:
                assert level.value in text

    @pytest.mark.asyncio
    async def test_disabled_level_not_shown(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            # Disable DEBUG
            switch = pilot.app.query_one(f"#{_switch_id(LogLevel.DEBUG)}", Switch)
            switch.value = False
            await pilot.pause()

            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)
            widget.append_logs(
                _make_logs(LogLevel.DEBUG, LogLevel.INFO),
                met=10.0,
                tick_id=1,
            )
            await pilot.pause()
            assert _item_count(pilot.app) == 1
            text = _item_text(pilot.app, 0)
            assert "DEBUG" not in text
            assert "INFO" in text

    @pytest.mark.asyncio
    async def test_all_entries_filtered_produces_no_item(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            switch = pilot.app.query_one(f"#{_switch_id(LogLevel.DEBUG)}", Switch)
            switch.value = False
            await pilot.pause()

            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)
            widget.append_logs(_make_logs(LogLevel.DEBUG), met=10.0, tick_id=1)
            await pilot.pause()
            assert _item_count(pilot.app) == 0


class TestToggleRerendersHistory:
    """Toggling a filter re-renders the full log history."""

    @pytest.mark.asyncio
    async def test_toggle_off_hides_level_from_group(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)
            widget.append_logs(
                _make_logs(LogLevel.DEBUG, LogLevel.INFO),
                met=5.0,
                tick_id=1,
            )
            await pilot.pause()
            assert _item_count(pilot.app) == 1

            # Disable DEBUG
            switch = pilot.app.query_one(f"#{_switch_id(LogLevel.DEBUG)}", Switch)
            switch.value = False
            await pilot.pause()

            assert _item_count(pilot.app) == 1
            text = _item_text(pilot.app, 0)
            assert "DEBUG" not in text
            assert "INFO" in text

    @pytest.mark.asyncio
    async def test_toggle_on_restores_entries(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)

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
            assert _item_count(pilot.app) == 1
            assert "WARN" not in _item_text(pilot.app, 0)

            # Re-enable WARN
            switch.value = True
            await pilot.pause()
            assert _item_count(pilot.app) == 1
            text = _item_text(pilot.app, 0)
            assert "WARN" in text
            assert "ERROR" in text


class TestEmptyLogsIgnored:
    """append_logs with empty list is a no-op."""

    @pytest.mark.asyncio
    async def test_empty_list(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)
            widget.append_logs([], met=0.0, tick_id=1)
            await pilot.pause()
            assert _item_count(pilot.app) == 0
