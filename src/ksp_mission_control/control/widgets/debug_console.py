"""DebugConsoleWidget - scrollable log of action debug messages."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import RichLog, Static

from ksp_mission_control.control.actions.base import LogEntry, LogLevel
from ksp_mission_control.control.formatting import format_met, resolve_theme_colors

_LEVEL_VARIABLE: dict[LogLevel, str] = {
    LogLevel.DEBUG: "text-muted",
    LogLevel.INFO: "success",
    LogLevel.WARN: "warning",
    LogLevel.ERROR: "error",
}


class DebugConsoleWidget(Static):
    """Displays a scrolling log of debug messages emitted by actions."""

    DEFAULT_CSS = """
    #debug-console-title {
        padding: 0 0 1 0;
    }

    #debug-console-log {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._level_colors: dict[LogLevel, str] | None = None

    def compose(self) -> ComposeResult:
        yield Static("[b]Action Debug Console[/b]", id="debug-console-title")
        yield RichLog(id="debug-console-log", markup=True)

    def _resolve_colors(self) -> dict[LogLevel, str]:
        """Resolve theme CSS variables to hex colors, cached after first call."""
        if self._level_colors is None:
            self._level_colors = resolve_theme_colors(self.app, _LEVEL_VARIABLE)
        return self._level_colors

    def append_logs(self, logs: list[LogEntry], *, met: float) -> None:
        """Append new log entries to the console, color-coded by level."""
        if not logs:
            return
        colors = self._resolve_colors()
        rich_log = self.query_one("#debug-console-log", RichLog)
        met_str = format_met(met)
        for entry in logs:
            color = colors[entry.level]
            tag = f"[{color}]{entry.level.value:>5}[/{color}]"
            rich_log.write(f"[dim]{met_str}[/dim] {tag}  {entry.message}")
