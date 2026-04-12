"""CommandHistoryWidget - paginated history of VesselCommands sent to the ship."""

from __future__ import annotations

from dataclasses import dataclass, fields

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Static

from ksp_mission_control.control.actions.base import ActionStatus, VesselCommands
from ksp_mission_control.control.formatting import format_met

_MAX_HISTORY = 10_000
"""Maximum number of command records to keep. Oldest entries are dropped."""

_STATUS_VARIABLE: dict[ActionStatus, str] = {
    ActionStatus.RUNNING: "accent",
    ActionStatus.SUCCEEDED: "success",
    ActionStatus.FAILED: "error",
    ActionStatus.PENDING: "warning",
}


@dataclass(frozen=True)
class CommandRecord:
    """A single snapshot of commands sent to the vessel."""

    action_label: str
    met: float
    commands: VesselCommands
    applied_fields: frozenset[str]
    """Field names that were actually sent (differed from vessel state)."""
    status: ActionStatus | None = None


class CommandHistoryWidget(Static):
    """Paginated history of VesselCommands sent to the ship."""

    DEFAULT_CSS = """
    #command-history-title {
        padding: 0 0 1 0;
    }
    #command-history-nav {
        height: auto;
        padding: 1 0 0 0;
    }
    #command-history-nav Button {
        min-width: 5;
        width: auto;
        margin: 0 1 0 0;
    }
    #command-history-page {
        content-align: right middle;
        width: 1fr;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._history: list[CommandRecord] = []
        self._index: int = -1
        self._following: bool = True
        self._status_colors: dict[ActionStatus, str] | None = None
        self._accent_color: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("[b]Commands[/b]", id="command-history-title")
        yield Static("[dim]No commands yet[/dim]", id="command-history-content")
        with Horizontal(id="command-history-nav"):
            yield Button("\u25c0\u25c0", id="cmd-first", disabled=True)
            yield Button("\u25c0", id="cmd-prev", disabled=True)
            yield Button("\u25b6", id="cmd-next", disabled=True)
            yield Button("\u25b6\u25b6", id="cmd-last", disabled=True)
            yield Static("", id="command-history-page")

    def record_commands(
        self,
        commands: VesselCommands,
        *,
        applied_fields: frozenset[str],
        action_label: str | None,
        met: float,
        status: ActionStatus | None = None,
    ) -> None:
        """Record commands if any field was actually applied to the vessel."""
        if not applied_fields:
            return

        label = action_label or "Manual"
        record = CommandRecord(
            action_label=label,
            met=met,
            commands=commands,
            applied_fields=applied_fields,
            status=status,
        )

        if self._history and self._history[-1].commands == commands:
            return

        self._history.append(record)
        if len(self._history) > _MAX_HISTORY:
            self._history.pop(0)
            self._index = max(0, self._index - 1)

        if self._following:
            self._index = len(self._history) - 1
        self._render_current()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cmd-first":
            self._jump(0)
        elif event.button.id == "cmd-prev":
            self._navigate(-1)
        elif event.button.id == "cmd-next":
            self._navigate(1)
        elif event.button.id == "cmd-last":
            self._jump(len(self._history) - 1)

    def _navigate(self, delta: int) -> None:
        new_index = self._index + delta
        if 0 <= new_index < len(self._history):
            self._jump(new_index)

    def _jump(self, index: int) -> None:
        if not self._history or not (0 <= index < len(self._history)):
            return
        self._index = index
        self._following = self._index == len(self._history) - 1
        self._render_current()

    def _resolve_colors(self) -> dict[ActionStatus, str]:
        """Resolve theme CSS variables to hex colors, cached after first call."""
        if self._status_colors is None:
            css_vars = self.app.get_css_variables()
            self._status_colors = {
                status: css_vars.get(var, "#ffffff") for status, var in _STATUS_VARIABLE.items()
            }
        return self._status_colors

    def _resolve_accent(self) -> str:
        """Resolve the accent CSS variable to a hex color, cached after first call."""
        if self._accent_color is None:
            css_vars = self.app.get_css_variables()
            self._accent_color = css_vars.get("accent", "#ffffff")
        return self._accent_color

    def _render_current(self) -> None:
        if not self._history or self._index < 0:
            return
        record = self._history[self._index]
        colors = self._resolve_colors()
        if record.status is not None and record.status in colors:
            color = colors[record.status]
            status_text = f"[bold {color}]{record.status.value}[/bold {color}]"
        else:
            status_text = "[dim]---[/dim]"
        title = f"[b]{record.action_label}[/b]  {status_text}  [dim]{format_met(record.met)}[/dim]"
        self.query_one("#command-history-title", Static).update(title)
        self.query_one("#command-history-content", Static).update(
            _format_commands(record.commands, record.applied_fields)
        )
        total = len(self._history)
        page = self._index + 1
        accent_color = self._resolve_accent()
        following_indicator = (
            f" [bold {accent_color}]\u25cf[/bold {accent_color}]" if self._following else ""
        )
        self.query_one("#command-history-page", Static).update(
            f"{page}/{total}{following_indicator}"
        )
        self.query_one("#cmd-first", Button).disabled = self._index <= 0
        self.query_one("#cmd-prev", Button).disabled = self._index <= 0
        self.query_one("#cmd-next", Button).disabled = self._index >= total - 1
        self.query_one("#cmd-last", Button).disabled = self._following


def _format_field_value(name: str, value: object) -> str:
    """Format a command field value with appropriate units."""
    if name == "throttle":
        return f"{float(value) * 100:.0f}%"  # type: ignore[arg-type]
    if name in ("pitch", "heading"):
        return f"{float(value):.1f}\u00b0"  # type: ignore[arg-type]
    if name in ("sas", "rcs"):
        return "ON" if value else "OFF"
    if name == "stage":
        return "ACTIVATE" if value else "---"
    return str(value)


def _format_commands(commands: VesselCommands, applied_fields: frozenset[str]) -> str:
    """Format commands with 3 visual states:

    - None: not commanded at all (dim with ---)
    - Has value, not applied: redundant, vessel already had this value (dim with value)
    - Has value, applied: actually sent to vessel (normal)
    """
    lines: list[str] = []
    for field in fields(commands):
        value = getattr(commands, field.name)
        label = field.name.replace("_", " ").title()
        if value is None:
            lines.append(f"[dim]{label}: ---[/dim]")
        else:
            formatted = _format_field_value(field.name, value)
            if field.name in applied_fields:
                lines.append(f"{label}: {formatted}")
            else:
                lines.append(f"[dim]{label}: {formatted}[/dim]")
    return "\n".join(lines)
