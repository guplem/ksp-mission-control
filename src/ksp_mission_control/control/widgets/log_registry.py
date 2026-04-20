"""LogRegistryWidget - scrollable log of action debug messages."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import RichLog, Static, Switch

from ksp_mission_control.control.actions.base import LogEntry, LogLevel
from ksp_mission_control.control.formatting import format_met, resolve_theme_colors

_LEVEL_VARIABLE: dict[LogLevel, str] = {
    LogLevel.DEBUG: "text-muted",
    LogLevel.INFO: "success",
    LogLevel.WARN: "warning",
    LogLevel.ERROR: "error",
}

_SWITCH_ID_PREFIX = "filter-"


def _switch_id(level: LogLevel) -> str:
    return f"{_SWITCH_ID_PREFIX}{level.value.lower()}"


@dataclass(frozen=True)
class _TimestampedLog:
    """Log entry paired with the MET and tick ID at which it was recorded."""

    entry: LogEntry
    met: float
    tick_id: int


class LogRegistryWidget(Static):
    """Displays a scrolling log of debug messages emitted by actions."""

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
    """

    def __init__(self, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._level_colors: dict[LogLevel, str] | None = None
        self._all_logs: list[_TimestampedLog] = []
        self._enabled_levels: set[LogLevel] = set(LogLevel)
        self._highlighted_tick: int | None = None
        self._following: bool = True

    def compose(self) -> ComposeResult:
        with Horizontal(id="log-registry-header"):
            yield Static("[b]Log Registry[/b]", id="log-registry-title")
            for level in LogLevel:
                yield Static(level.value, classes="filter-label")
                yield Switch(value=True, id=_switch_id(level))
        yield RichLog(id="log-registry-log", markup=True)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Re-render the log when a level filter is toggled."""
        switch_id = event.switch.id or ""
        if not switch_id.startswith(_SWITCH_ID_PREFIX):
            return
        level_name = switch_id[len(_SWITCH_ID_PREFIX) :].upper()
        try:
            level = LogLevel(level_name)
        except ValueError:
            return
        if event.value:
            self._enabled_levels.add(level)
        else:
            self._enabled_levels.discard(level)
        self._rerender_log()

    def _resolve_colors(self) -> dict[LogLevel, str]:
        """Resolve theme CSS variables to hex colors, cached after first call."""
        if self._level_colors is None:
            self._level_colors = resolve_theme_colors(self.app, _LEVEL_VARIABLE)
        return self._level_colors

    def set_following(self, following: bool) -> None:
        """Control whether the log auto-scrolls to new entries."""
        self._following = following
        rich_log = self.query_one("#log-registry-log", RichLog)
        rich_log.auto_scroll = following
        if following:
            rich_log.scroll_end(animate=False)

    def append_logs(self, logs: list[LogEntry], *, met: float, tick_id: int) -> None:
        """Append new log entries to the console, color-coded by level."""
        if not logs:
            return
        for entry in logs:
            self._all_logs.append(_TimestampedLog(entry=entry, met=met, tick_id=tick_id))
        colors = self._resolve_colors()
        rich_log = self.query_one("#log-registry-log", RichLog)
        dimmed = tick_id != self._highlighted_tick
        for entry in logs:
            if entry.level in self._enabled_levels:
                line = self._format_entry(entry, met, colors)
                rich_log.write(f"[dim]{line}[/dim]" if dimmed else line)

    def highlight_tick(self, tick_id: int) -> None:
        """Highlight logs from the given tick, dimming all others."""
        if tick_id == self._highlighted_tick:
            return
        self._highlighted_tick = tick_id
        self._rerender_log()
        if not self._following:
            self._scroll_to_highlighted_tick()

    def _rerender_log(self) -> None:
        """Clear and rewrite the entire log with current filter and highlight settings."""
        colors = self._resolve_colors()
        rich_log = self.query_one("#log-registry-log", RichLog)
        rich_log.clear()
        highlight = self._highlighted_tick
        for stamped in self._all_logs:
            if stamped.entry.level in self._enabled_levels:
                line = self._format_entry(stamped.entry, stamped.met, colors)
                if stamped.tick_id != highlight:
                    line = f"[dim]{line}[/dim]"
                rich_log.write(line)

    def _scroll_to_highlighted_tick(self) -> None:
        """Scroll the log to the first line belonging to the highlighted tick."""
        if self._highlighted_tick is None:
            return
        line_index = 0
        for stamped in self._all_logs:
            if stamped.entry.level in self._enabled_levels:
                if stamped.tick_id == self._highlighted_tick:
                    rich_log = self.query_one("#log-registry-log", RichLog)
                    rich_log.scroll_to(y=line_index, animate=False)
                    return
                line_index += 1

    @staticmethod
    def _format_entry(entry: LogEntry, met: float, colors: dict[LogLevel, str]) -> str:
        """Format a single log entry as Rich markup."""
        met_str = format_met(met)
        color = colors[entry.level]
        tag = f"[{color}]{entry.level.value:>5}[/{color}]"
        return f"[dim]{met_str}[/dim] {tag}  {entry.message}"
