"""LastCommandWidget - paginated history of VesselCommands sent to the ship."""

from __future__ import annotations

from dataclasses import dataclass, fields

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Static

from ksp_mission_control.control.actions.base import VesselCommands


@dataclass(frozen=True)
class CommandRecord:
    """A single snapshot of commands sent to the vessel."""

    action_label: str
    met: float
    commands: VesselCommands


class LastCommandWidget(Static):
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

    def compose(self) -> ComposeResult:
        yield Static("[b]Commands[/b]", id="command-history-title")
        yield Static("[dim]No commands yet[/dim]", id="command-history-content")
        with Horizontal(id="command-history-nav"):
            yield Button("\u25c0", id="cmd-prev", disabled=True)
            yield Button("\u25b6", id="cmd-next", disabled=True)
            yield Static("", id="command-history-page")

    def record_commands(
        self,
        commands: VesselCommands,
        action_label: str | None,
        met: float,
    ) -> None:
        """Record commands if they contain any non-None values and differ from the last entry."""
        has_values = any(
            getattr(commands, field.name) is not None for field in fields(commands)
        )
        if not has_values:
            return

        label = action_label or "Manual"
        record = CommandRecord(action_label=label, met=met, commands=commands)

        if self._history and _commands_equal(self._history[-1].commands, commands):
            return

        self._history.append(record)

        if self._following:
            self._index = len(self._history) - 1
            self._render_current()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cmd-prev":
            self._navigate(-1)
        elif event.button.id == "cmd-next":
            self._navigate(1)

    def _navigate(self, delta: int) -> None:
        new_index = self._index + delta
        if 0 <= new_index < len(self._history):
            self._index = new_index
            self._following = self._index == len(self._history) - 1
            self._render_current()

    def _render_current(self) -> None:
        if not self._history or self._index < 0:
            return
        record = self._history[self._index]
        title = f"[b]{record.action_label}[/b]  [dim]{_format_met(record.met)}[/dim]"
        self.query_one("#command-history-title", Static).update(title)
        self.query_one("#command-history-content", Static).update(
            _format_commands(record.commands)
        )
        total = len(self._history)
        page = self._index + 1
        self.query_one("#command-history-page", Static).update(f"{page}/{total}")
        self.query_one("#cmd-prev", Button).disabled = self._index <= 0
        self.query_one("#cmd-next", Button).disabled = self._index >= total - 1


def _format_commands(commands: VesselCommands) -> str:
    lines: list[str] = []
    for field in fields(commands):
        value = getattr(commands, field.name)
        label = field.name.replace("_", " ").title()
        if value is None:
            lines.append(f"[dim]{label}: ---[/dim]")
        else:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def _format_met(met: float) -> str:
    """Format MET as MM:SS.t for display."""
    minutes = int(met) // 60
    seconds = met - minutes * 60
    return f"T+{minutes:02d}:{seconds:04.1f}"


def _commands_equal(a: VesselCommands, b: VesselCommands) -> bool:
    """Compare two VesselCommands by their field values."""
    return all(
        getattr(a, field.name) == getattr(b, field.name) for field in fields(a)
    )
