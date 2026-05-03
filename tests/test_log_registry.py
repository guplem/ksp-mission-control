"""Tests for LogRegistryWidget - log filtering, tick grouping, and click selection."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import ListView, Static, Switch

from ksp_mission_control.control.actions.base import LogEntry, LogLevel
from ksp_mission_control.control.widgets.log_registry import (
    _FILTER_CATEGORIES,
    LogRegistryWidget,
    _switch_id,
)


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
    """Verify that compose produces a Switch per category, all enabled."""

    @pytest.mark.asyncio
    async def test_one_switch_per_category(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            for category in _FILTER_CATEGORIES:
                switch = pilot.app.query_one(f"#{_switch_id(category)}", Switch)
                assert switch.value is True


class TestTickGrouping:
    """Logs from the same tick are grouped into a single ListItem."""

    @pytest.mark.asyncio
    async def test_same_tick_produces_one_item(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)
            widget.append_logs(
                _make_logs(LogLevel.LOG_DEBUG, LogLevel.LOG_INFO, LogLevel.LOG_WARN, LogLevel.LOG_ERROR),
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
            widget.append_logs(_make_logs(LogLevel.LOG_INFO), met=1.0, tick_id=1)
            widget.append_logs(_make_logs(LogLevel.LOG_WARN), met=2.0, tick_id=2)
            await pilot.pause()
            assert _item_count(pilot.app) == 2

    @pytest.mark.asyncio
    async def test_second_append_same_tick_updates_existing_item(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)
            widget.append_logs(_make_logs(LogLevel.LOG_INFO), met=5.0, tick_id=3)
            widget.append_logs(_make_logs(LogLevel.LOG_ERROR), met=5.0, tick_id=3)
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
            logs = _make_logs(LogLevel.LOG_DEBUG, LogLevel.LOG_INFO, LogLevel.LOG_WARN, LogLevel.LOG_ERROR)
            widget.append_logs(logs, met=10.0, tick_id=1)
            await pilot.pause()
            assert _item_count(pilot.app) == 1
            text = _item_text(pilot.app, 0)
            for log_entry in logs:
                assert log_entry.level.value in text

    @pytest.mark.asyncio
    async def test_disabled_category_not_shown(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            # Disable Log category (hides LOG_DEBUG, LOG_INFO, LOG_WARN, LOG_ERROR)
            switch = pilot.app.query_one(f"#{_switch_id('Log')}", Switch)
            switch.value = False
            await pilot.pause()

            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)
            widget.append_logs(
                _make_logs(LogLevel.LOG_DEBUG, LogLevel.ACTION_START),
                met=10.0,
                tick_id=1,
            )
            await pilot.pause()
            assert _item_count(pilot.app) == 1
            text = _item_text(pilot.app, 0)
            assert "LOG_DEBUG" not in text
            assert "ACTION_START" in text

    @pytest.mark.asyncio
    async def test_all_entries_filtered_produces_no_item(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            switch = pilot.app.query_one(f"#{_switch_id('Log')}", Switch)
            switch.value = False
            await pilot.pause()

            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)
            widget.append_logs(_make_logs(LogLevel.LOG_DEBUG), met=10.0, tick_id=1)
            await pilot.pause()
            assert _item_count(pilot.app) == 0


class TestToggleRerendersHistory:
    """Toggling a filter re-renders the full log history."""

    @pytest.mark.asyncio
    async def test_toggle_off_hides_category_from_group(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)
            widget.append_logs(
                _make_logs(LogLevel.LOG_INFO, LogLevel.ACTION_START),
                met=5.0,
                tick_id=1,
            )
            await pilot.pause()
            assert _item_count(pilot.app) == 1

            # Disable Log category
            switch = pilot.app.query_one(f"#{_switch_id('Log')}", Switch)
            switch.value = False
            await pilot.pause()

            assert _item_count(pilot.app) == 1
            text = _item_text(pilot.app, 0)
            assert "LOG_INFO" not in text
            assert "ACTION_START" in text

    @pytest.mark.asyncio
    async def test_toggle_on_restores_entries(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)

            # Disable Log category, then add logs
            switch = pilot.app.query_one(f"#{_switch_id('Log')}", Switch)
            switch.value = False
            await pilot.pause()

            widget.append_logs(
                _make_logs(LogLevel.LOG_WARN, LogLevel.ACTION_START),
                met=20.0,
                tick_id=2,
            )
            await pilot.pause()
            assert _item_count(pilot.app) == 1
            assert "LOG_WARN" not in _item_text(pilot.app, 0)

            # Re-enable Log category
            switch.value = True
            await pilot.pause()
            assert _item_count(pilot.app) == 1
            text = _item_text(pilot.app, 0)
            assert "LOG_WARN" in text
            assert "ACTION_START" in text


class TestEmptyLogsIgnored:
    """append_logs with empty list is a no-op."""

    @pytest.mark.asyncio
    async def test_empty_list(self) -> None:
        async with LogRegistryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#log-registry", LogRegistryWidget)
            widget.append_logs([], met=0.0, tick_id=1)
            await pilot.pause()
            assert _item_count(pilot.app) == 0
