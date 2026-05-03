"""LogRegistryWidget - scrollable log of mission control messages."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import ListItem, ListView, Static, Switch

from ksp_mission_control.control.actions.base import LogEntry, LogLevel
from ksp_mission_control.control.formatting import format_met, resolve_theme_colors

_LEVEL_COLOR: dict[LogLevel, str] = {
    # Action lifecycle
    LogLevel.ACTION_START: "primary",
    LogLevel.ACTION_RUNNING: "foreground-darken-2",
    LogLevel.ACTION_SUCCEEDED: "success",
    LogLevel.ACTION_FAILED: "error",
    LogLevel.ACTION_END: "foreground-darken-2",
    # Plan lifecycle
    LogLevel.PLAN_START: "primary",
    LogLevel.PLAN_END: "foreground-darken-2",
    # Action logs
    LogLevel.LOG_DEBUG: "foreground-darken-2",
    LogLevel.LOG_INFO: "foreground",
    LogLevel.LOG_WARN: "warning",
    LogLevel.LOG_ERROR: "error",
    # System
    LogLevel.COMMAND: "warning",
    LogLevel.PYTHON_ERROR: "error",
    LogLevel.PYTHON_WARNING: "warning",
}


_FILTER_CATEGORIES: dict[str, set[LogLevel]] = {
    "Action": {
        LogLevel.ACTION_START,
        LogLevel.ACTION_RUNNING,
        LogLevel.ACTION_SUCCEEDED,
        LogLevel.ACTION_FAILED,
        LogLevel.ACTION_END,
    },
    "Plan": {
        LogLevel.PLAN_START,
        LogLevel.PLAN_END,
    },
    "Log": {
        LogLevel.LOG_DEBUG,
        LogLevel.LOG_INFO,
        LogLevel.LOG_WARN,
        LogLevel.LOG_ERROR,
    },
    "System": {
        LogLevel.COMMAND,
        LogLevel.PYTHON_ERROR,
        LogLevel.PYTHON_WARNING,
    },
}

_SWITCH_ID_PREFIX = "filter-"

_TAG_WIDTH = 16
"""Fixed width for the level tag column so messages align."""


def _switch_id(category: str) -> str:
    return f"{_SWITCH_ID_PREFIX}{category.lower()}"


@dataclass(frozen=True)
class _TimestampedLog:
    """Log entry paired with the MET and tick ID at which it was recorded."""

    entry: LogEntry
    met: float
    tick_id: int


class LogRegistryWidget(Static):
    """Displays a scrolling log of mission control messages.

    Log entries are grouped by tick: all entries from the same tick appear as a
    single list item so that hovering or selecting highlights the whole tick.
    """

    class LogLineClicked(Message):
        """Posted when the user clicks a log line."""

        def __init__(self, tick_id: int) -> None:
            super().__init__()
            self.tick_id = tick_id
            """The tick ID of the clicked log entry."""

    DEFAULT_CSS = """
    #log-registry-header {
        height: auto;
        padding: 0 0 1 0;
    }

    #log-registry-title {
        width: 1fr;
    }

    #log-registry-header .filter-label {
        width: auto;
        padding: 0 1 0 0;
        content-align: center middle;
        margin: 0 0 0 5;
    }

    #log-registry-header Switch {
        width: auto;
        height: auto;
        min-width: 0;
        margin: 0 2 0 0;
        padding: 0;
        border: none;
    }

    #log-registry-log {
        height: 1fr;
    }

    #log-registry-log ListItem {
        height: auto;
        padding: 0 0 0 1;
        margin-bottom: 1;
        border-left: solid $surface-lighten-2;
    }

    #log-registry-log ListItem.-highlight {
        background: $block-hover-background;
        border-left: solid $primary;
    }

    #log-registry-log:focus ListItem.-highlight {
        background: $block-hover-background;
        border-left: solid $primary;
    }

    #log-registry-log ListItem Static {
        height: auto;
        padding: 0;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._level_colors: dict[LogLevel, str] | None = None
        self._all_logs: list[_TimestampedLog] = []
        self._enabled_levels: set[LogLevel] = set(LogLevel)
        self._highlighted_tick: int | None = None
        self._following: bool = True
        self._visible_tick_ids: list[int] = []
        """Maps each visible ListItem index to its tick_id."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="log-registry-header"):
            yield Static("[b]Log Registry[/b]", id="log-registry-title")
            for category in _FILTER_CATEGORIES:
                yield Static(category, classes="filter-label")
                yield Switch(value=True, id=_switch_id(category))
        yield ListView(id="log-registry-log")

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Post tick ID when a log group is highlighted (single click or keyboard)."""
        item_index = event.list_view.index
        if item_index is not None and 0 <= item_index < len(self._visible_tick_ids):
            self.post_message(self.LogLineClicked(self._visible_tick_ids[item_index]))

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Re-render the log when a category filter is toggled."""
        switch_id = event.switch.id or ""
        if not switch_id.startswith(_SWITCH_ID_PREFIX):
            return
        category_name = switch_id[len(_SWITCH_ID_PREFIX) :]
        for cat_name, levels in _FILTER_CATEGORIES.items():
            if cat_name.lower() == category_name:
                if event.value:
                    self._enabled_levels.update(levels)
                else:
                    self._enabled_levels -= levels
                self._rerender_log()
                return

    def _resolve_colors(self) -> dict[LogLevel, str]:
        """Resolve theme CSS variables to hex colors, cached after first call."""
        if self._level_colors is None:
            self._level_colors = resolve_theme_colors(self.app, _LEVEL_COLOR)
        return self._level_colors

    def set_following(self, following: bool) -> None:
        """Control whether the log auto-scrolls to new entries."""
        self._following = following
        list_view = self.query_one("#log-registry-log", ListView)
        if following:
            self._highlighted_tick = None
            list_view.index = None
            list_view.scroll_end(animate=False)

    def append_logs(self, logs: list[LogEntry], *, met: float, tick_id: int) -> None:
        """Append new log entries grouped by tick."""
        if not logs:
            return
        for entry in logs:
            self._all_logs.append(_TimestampedLog(entry=entry, met=met, tick_id=tick_id))

        filtered_lines = self._format_filtered_lines(logs, met)
        if not filtered_lines:
            return

        colors = self._resolve_colors()
        markup = self._build_tick_markup(filtered_lines, colors)
        list_view = self.query_one("#log-registry-log", ListView)

        # If the last item is the same tick, replace it with the combined version.
        if self._visible_tick_ids and self._visible_tick_ids[-1] == tick_id:
            list_view.children[-1].remove()
            all_lines = self._collect_tick_lines(tick_id)
            markup = self._build_tick_markup(all_lines, colors)
            list_view.append(ListItem(Static(markup, markup=True)))
        else:
            list_view.append(ListItem(Static(markup, markup=True)))
            self._visible_tick_ids.append(tick_id)

        if self._following:
            list_view.scroll_end(animate=False)

    def highlight_tick(self, tick_id: int) -> None:
        """Mark a tick as highlighted (no scroll)."""
        self._highlighted_tick = tick_id

    def _format_filtered_lines(self, logs: list[LogEntry], met: float) -> list[tuple[LogEntry, float]]:
        """Return (entry, met) pairs for entries passing the level filter."""
        return [(entry, met) for entry in logs if entry.level in self._enabled_levels]

    def _collect_tick_lines(self, tick_id: int) -> list[tuple[LogEntry, float]]:
        """Collect all filtered log entries for a given tick from the full history."""
        return [
            (stamped.entry, stamped.met) for stamped in self._all_logs if stamped.tick_id == tick_id and stamped.entry.level in self._enabled_levels
        ]

    def _build_tick_markup(
        self,
        lines: list[tuple[LogEntry, float]],
        colors: dict[LogLevel, str],
    ) -> str:
        """Build Rich markup for a group of log entries belonging to one tick.

        Inserts an empty line between different actions within the same
        tick (detected by action_id/plan_step change).
        """
        parts: list[str] = []
        prev_action_key: tuple[str | None, int | None] | None = None
        first = True
        for entry, met in lines:
            action_key = (entry.action_id, entry.plan_step)
            if prev_action_key is not None and action_key != prev_action_key:
                parts.append("")
            prev_action_key = action_key
            parts.append(self._format_entry(entry, met, colors, show_met=first))
            first = False
        return "\n".join(parts)

    def _rerender_log(self) -> None:
        """Clear and rewrite the entire log with current filter and highlight settings."""
        colors = self._resolve_colors()
        list_view = self.query_one("#log-registry-log", ListView)
        list_view.clear()
        self._visible_tick_ids.clear()

        filtered = [s for s in self._all_logs if s.entry.level in self._enabled_levels]
        for tick_id, group in groupby(filtered, key=lambda s: s.tick_id):
            entries = [(s.entry, s.met) for s in group]
            markup = self._build_tick_markup(entries, colors)
            list_view.append(ListItem(Static(markup, markup=True)))
            self._visible_tick_ids.append(tick_id)

    @staticmethod
    def _format_entry(entry: LogEntry, met: float, colors: dict[LogLevel, str], *, show_met: bool = True) -> str:
        """Format a single log entry as Rich markup.

        Context (MET, level tag, plan name, action id, step number) is
        always dim. The message is always fully readable. MET is only
        shown on the first line of each tick group.
        """
        met_str = format_met(met)
        met_col = f"[dim]{met_str}[/dim]" if show_met else " " * len(met_str)
        color = colors[entry.level]
        tag = f"[{color}]{entry.level.value:>{_TAG_WIDTH}}[/{color}]"

        context_parts: list[str] = []
        if entry.track_name is not None:
            context_parts.append(entry.track_name)
        if entry.action_id is not None:
            step_suffix = f":{entry.plan_step}" if entry.plan_step is not None else ""
            context_parts.append(f"{entry.action_id}{step_suffix}")

        context = f" [dim]{' / '.join(context_parts)}[/dim]" if context_parts else ""
        return f"{met_col} {tag}{context}  {entry.message}"
