"""LogRegistryWidget - scrollable log of action debug messages."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import ListItem, ListView, Static, Switch

from ksp_mission_control.control.actions.base import LogEntry, LogLevel
from ksp_mission_control.control.formatting import format_met, resolve_theme_colors

_LEVEL_VARIABLE: dict[LogLevel, str] = {
    LogLevel.DEBUG: "foreground-darken-2",
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
    """Displays a scrolling log of debug messages emitted by actions.

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
        padding: 0;
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
            for level in LogLevel:
                yield Static(level.value, classes="filter-label")
                yield Switch(value=True, id=_switch_id(level))
        yield ListView(id="log-registry-log")

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Post tick ID when a log group is highlighted (single click or keyboard)."""
        item_index = event.list_view.index
        if item_index is not None and 0 <= item_index < len(self._visible_tick_ids):
            self.post_message(self.LogLineClicked(self._visible_tick_ids[item_index]))

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
        list_view = self.query_one("#log-registry-log", ListView)
        if following:
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
        dimmed = tick_id != self._highlighted_tick
        markup = self._build_tick_markup(filtered_lines, colors, dimmed)
        list_view = self.query_one("#log-registry-log", ListView)

        # If the last item is the same tick, replace it with the combined version.
        if self._visible_tick_ids and self._visible_tick_ids[-1] == tick_id:
            list_view.children[-1].remove()
            all_lines = self._collect_tick_lines(tick_id)
            markup = self._build_tick_markup(all_lines, colors, dimmed)
            list_view.append(ListItem(Static(markup, markup=True)))
        else:
            list_view.append(ListItem(Static(markup, markup=True)))
            self._visible_tick_ids.append(tick_id)

        if self._following:
            list_view.scroll_end(animate=False)

    def highlight_tick(self, tick_id: int) -> None:
        """Highlight logs from the given tick, dimming all others.

        Only updates the two affected items (old highlight and new highlight)
        rather than rebuilding the entire list.
        """
        if tick_id == self._highlighted_tick:
            return
        previous_tick = self._highlighted_tick
        self._highlighted_tick = tick_id
        colors = self._resolve_colors()
        list_view = self.query_one("#log-registry-log", ListView)
        items = list_view.children

        for index, visible_tick_id in enumerate(self._visible_tick_ids):
            if visible_tick_id in (previous_tick, tick_id):
                lines = self._collect_tick_lines(visible_tick_id)
                if lines:
                    dimmed = visible_tick_id != tick_id
                    markup = self._build_tick_markup(lines, colors, dimmed)
                    items[index].query_one(Static).update(markup)

        if not self._following:
            self._scroll_to_highlighted_tick()

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
        dimmed: bool,
    ) -> str:
        """Build Rich markup for a group of log entries belonging to one tick."""
        formatted = [self._format_entry(entry, met, colors) for entry, met in lines]
        combined = "\n".join(formatted)
        return f"[dim]{combined}[/dim]" if dimmed else combined

    def _rerender_log(self) -> None:
        """Clear and rewrite the entire log with current filter and highlight settings."""
        colors = self._resolve_colors()
        list_view = self.query_one("#log-registry-log", ListView)
        list_view.clear()
        self._visible_tick_ids.clear()
        highlight = self._highlighted_tick

        filtered = [s for s in self._all_logs if s.entry.level in self._enabled_levels]
        for tick_id, group in groupby(filtered, key=lambda s: s.tick_id):
            entries = [(s.entry, s.met) for s in group]
            dimmed = tick_id != highlight
            markup = self._build_tick_markup(entries, colors, dimmed)
            list_view.append(ListItem(Static(markup, markup=True)))
            self._visible_tick_ids.append(tick_id)

    def _scroll_to_highlighted_tick(self) -> None:
        """Scroll the log to the item belonging to the highlighted tick."""
        if self._highlighted_tick is None:
            return
        for index, tick_id in enumerate(self._visible_tick_ids):
            if tick_id == self._highlighted_tick:
                list_view = self.query_one("#log-registry-log", ListView)
                list_view.scroll_to(y=index, animate=False)
                return

    @staticmethod
    def _format_entry(entry: LogEntry, met: float, colors: dict[LogLevel, str]) -> str:
        """Format a single log entry as Rich markup."""
        met_str = format_met(met)
        color = colors[entry.level]
        tag = f"[{color}]{entry.level.value:>5}[/{color}]"
        return f"[dim]{met_str}[/dim] {tag}  {entry.message}"
