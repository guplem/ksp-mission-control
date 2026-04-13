"""DebugConsoleWidget - scrollable log of action debug messages."""

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
    """Log entry paired with the MET at which it was recorded."""

    entry: LogEntry
    met: float


class DebugConsoleWidget(Static):
    """Displays a scrolling log of debug messages emitted by actions."""

    DEFAULT_CSS = """
    #debug-console-header {
        height: auto;
        padding: 0 0 1 0;
    }

    #debug-console-title {
        width: 1fr;
    }

    #debug-console-header .filter-label {
        width: auto;
        padding: 0 1 0 0;
        content-align: center middle;
        margin: 0 0 0 5;
    }

    #debug-console-header Switch {
        width: auto;
        height: auto;
        min-width: 0;
        margin: 0 2 0 0;
        padding: 0;
        border: none;
    }

    #debug-console-log {
        height: 1fr;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._level_colors: dict[LogLevel, str] | None = None
        self._all_logs: list[_TimestampedLog] = []
        self._enabled_levels: set[LogLevel] = set(LogLevel)

    def compose(self) -> ComposeResult:
        with Horizontal(id="debug-console-header"):
            yield Static("[b]Action Debug Console[/b]", id="debug-console-title")
            for level in LogLevel:
                yield Static(level.value, classes="filter-label")
                yield Switch(value=True, id=_switch_id(level))
        yield RichLog(id="debug-console-log", markup=True)

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

    def append_logs(self, logs: list[LogEntry], *, met: float) -> None:
        """Append new log entries to the console, color-coded by level."""
        if not logs:
            return
        for entry in logs:
            self._all_logs.append(_TimestampedLog(entry=entry, met=met))
        colors = self._resolve_colors()
        rich_log = self.query_one("#debug-console-log", RichLog)
        for entry in logs:
            if entry.level in self._enabled_levels:
                rich_log.write(self._format_entry(entry, met, colors))

    def _rerender_log(self) -> None:
        """Clear and rewrite the entire log with current filter settings."""
        colors = self._resolve_colors()
        rich_log = self.query_one("#debug-console-log", RichLog)
        rich_log.clear()
        for stamped in self._all_logs:
            if stamped.entry.level in self._enabled_levels:
                rich_log.write(self._format_entry(stamped.entry, stamped.met, colors))

    @staticmethod
    def _format_entry(entry: LogEntry, met: float, colors: dict[LogLevel, str]) -> str:
        """Format a single log entry as Rich markup."""
        met_str = format_met(met)
        color = colors[entry.level]
        tag = f"[{color}]{entry.level.value:>5}[/{color}]"
        return f"[dim]{met_str}[/dim] {tag}  {entry.message}"
